"""VOD service + route tests. FFmpeg and B2 are fully mocked, so this suite is
credential-free and never spawns a real transcode."""

import os
from datetime import UTC, datetime

import pytest

from app.repo import video_store
from app.repo.ffmpeg_runner import ProbeResult, RungOutput
from app.service import video as video_service
from app.service.ingest import IngestError
from app.types.video import (
    LadderPreset,
    TranscodeStatus,
    VideoAsset,
    compute_amplification,
    rungs_for,
)

# --- ladder expansion -------------------------------------------------------


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        (LadderPreset.P360, ["360p"]),
        (LadderPreset.P720, ["360p", "720p"]),
        (LadderPreset.P1080, ["360p", "720p", "1080p"]),
    ],
)
def test_ladder_expands_to_rungs_at_or_below_ceiling(preset, expected):
    assert [r[0] for r in rungs_for(preset)] == expected


# --- amplification math -----------------------------------------------------


@pytest.mark.parametrize(
    ("source", "rendition", "expected"),
    [
        (100, 350, 3.5),
        (200, 900, 4.5),
        (0, 500, None),  # no source -> None, never divide-by-zero
        (100, 0, 0.0),
    ],
)
def test_amplification_factor(source, rendition, expected):
    assert compute_amplification(source, rendition) == expected


# --- manifest read/write round-trip -----------------------------------------


@pytest.fixture
def memory_store(monkeypatch):
    """Back video_store's JSON manifest calls with an in-memory dict."""
    store: dict[str, dict] = {}

    def _write(key, obj):
        store[key] = obj

    def _read(key):
        return store.get(key)

    monkeypatch.setattr(video_store, "write_json", _write)
    monkeypatch.setattr(video_store, "read_json", _read)
    return store


def test_create_video_writes_transcoding_manifest(memory_store, monkeypatch):
    monkeypatch.setattr(video_store, "put_file", lambda path, key, ctype=None: 1234)
    head = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16

    asset = video_service.create_video(
        source_path="/tmp/x.mp4",
        filename="clip.mp4",
        size_bytes=1234,
        head=head,
        ladder=LadderPreset.P720,
        title="My Clip",
    )

    assert asset.status == TranscodeStatus.TRANSCODING
    assert asset.title == "My Clip"
    assert asset.source_key == f"videos/{asset.id}/source.mp4"
    # Round-trips through the manifest store as the same model.
    fetched = video_service.get_video(asset.id)
    assert fetched is not None
    assert fetched.id == asset.id
    assert fetched.ladder == LadderPreset.P720


def test_create_video_rejects_non_video(memory_store):
    with pytest.raises(IngestError):
        video_service.create_video(
            source_path="/tmp/x.png",
            filename="photo.png",
            size_bytes=10,
            head=b"\x89PNG\r\n\x1a\n",
            ladder=LadderPreset.P720,
            title="",
        )


def test_rename_video_updates_title(memory_store, monkeypatch):
    monkeypatch.setattr(video_store, "put_file", lambda path, key, ctype=None: 1)
    head = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
    asset = video_service.create_video(
        "/tmp/x.mp4", "clip.mp4", 1, head, LadderPreset.P360, "Old"
    )
    renamed = video_service.rename_video(asset.id, "New Title")
    assert renamed.title == "New Title"
    assert video_service.get_video(asset.id).title == "New Title"


def test_rename_missing_video_raises(memory_store):
    with pytest.raises(video_service.VideoNotFoundError):
        video_service.rename_video("nope", "x")


# --- prefix-scoped delete ---------------------------------------------------


def test_delete_video_is_prefix_scoped(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(video_store, "delete_prefix", lambda prefix: calls.append(prefix) or 3)
    count = video_service.delete_video("abc123")
    assert calls == ["videos/abc123/"]
    assert count == 3


def test_delete_prefix_refuses_bucket_wide():
    # Guard: an unscoped prefix must never reach delete_objects.
    for bad in ("", "/", "videos/"):
        with pytest.raises(ValueError):
            video_store.delete_prefix(bad)


# --- background transcode job (ffmpeg mocked) -------------------------------


def _write_src(key, local):
    with open(local, "wb") as fh:
        fh.write(b"src")


def _fake_transcode(source_path, out_dir, rungs, width, height, on_rung_done=None):
    hls = os.path.join(out_dir, "hls")
    outs = []
    for name, h, vk, ak in rungs:
        rung_dir = os.path.join(hls, name)
        os.makedirs(rung_dir, exist_ok=True)
        playlist = os.path.join(rung_dir, "index.m3u8")
        with open(playlist, "w") as fh:
            fh.write("#EXTM3U\n")
        seg = os.path.join(rung_dir, "seg_00001.ts")
        with open(seg, "wb") as fh:
            fh.write(b"x" * 2000)
        outs.append(RungOutput(name, h, (h * 16) // 9, vk, ak, playlist, [seg]))
        if on_rung_done is not None:
            on_rung_done(len(outs), len(rungs))
    with open(os.path.join(hls, "master.m3u8"), "w") as fh:
        fh.write("#EXTM3U\n")
    return outs


def test_run_transcode_job_flips_manifest_to_ready(memory_store, monkeypatch):
    # Seed a transcoding manifest via create_video.
    monkeypatch.setattr(video_store, "put_file", lambda path, key, ctype=None: os.path.getsize(path) if os.path.exists(path) else 100)
    head = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
    asset = video_service.create_video(
        "/tmp/x.mp4", "clip.mp4", 1000, head, LadderPreset.P720, "Clip"
    )

    # Mock every external effect the worker touches.
    monkeypatch.setattr(video_store, "download_to", _write_src)
    monkeypatch.setattr(video_store, "delete_prefix", lambda prefix: 0)
    monkeypatch.setattr(video_service.ffmpeg_runner, "probe", lambda p: ProbeResult(12.0, 1280, 720))
    monkeypatch.setattr(video_service.ffmpeg_runner, "transcode_hls", _fake_transcode)
    monkeypatch.setattr(video_service.sprite, "generate_sprite", lambda *a, **k: None)

    video_service.run_transcode_job(asset.id)

    done = video_service.get_video(asset.id)
    assert done.status == TranscodeStatus.READY
    assert [r.name for r in done.renditions] == ["360p", "720p"]
    assert done.master_playlist_key == f"videos/{asset.id}/hls/master.m3u8"
    assert done.rendition_bytes > 0
    assert done.amplification_factor == compute_amplification(1000, done.rendition_bytes)
    assert done.duration_seconds == 12.0


def test_run_transcode_job_reports_determinate_progress(memory_store, monkeypatch):
    monkeypatch.setattr(video_store, "put_file", lambda path, key, ctype=None: os.path.getsize(path) if os.path.exists(path) else 100)
    head = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
    asset = video_service.create_video(
        "/tmp/x.mp4", "clip.mp4", 1000, head, LadderPreset.P720, "Clip"
    )
    # A freshly-created (queued) manifest is not yet progressed.
    seeded = video_service.get_video(asset.id)
    assert seeded.progress == 0.0
    assert seeded.stage == "queued"

    # Record the progress value persisted on every manifest write during the job.
    inner_write = video_store.write_json
    progress_trace: list[float] = []

    def _tracing_write(key, obj):
        if key.endswith("asset.json"):
            progress_trace.append(obj["progress"])
        inner_write(key, obj)

    monkeypatch.setattr(video_store, "write_json", _tracing_write)
    monkeypatch.setattr(video_store, "download_to", _write_src)
    monkeypatch.setattr(video_store, "delete_prefix", lambda prefix: 0)
    monkeypatch.setattr(video_service.ffmpeg_runner, "probe", lambda p: ProbeResult(12.0, 1280, 720))
    monkeypatch.setattr(video_service.ffmpeg_runner, "transcode_hls", _fake_transcode)
    monkeypatch.setattr(video_service.sprite, "generate_sprite", lambda *a, **k: None)

    video_service.run_transcode_job(asset.id)

    done = video_service.get_video(asset.id)
    assert done.status == TranscodeStatus.READY
    assert done.progress == 1.0
    assert done.stage == "ready"
    # Progress advanced monotonically, passed through an intermediate value, and
    # ended at 1.0 — a genuinely determinate signal, not a spinner.
    assert progress_trace == sorted(progress_trace)
    assert progress_trace[-1] == 1.0
    assert any(0.0 < p < 1.0 for p in progress_trace)


def test_run_transcode_job_records_failure(memory_store, monkeypatch):
    monkeypatch.setattr(video_store, "put_file", lambda path, key, ctype=None: 100)
    head = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
    asset = video_service.create_video(
        "/tmp/x.mp4", "clip.mp4", 1000, head, LadderPreset.P360, "Clip"
    )
    monkeypatch.setattr(video_store, "download_to", _write_src)
    monkeypatch.setattr(video_store, "delete_prefix", lambda prefix: 0)

    def _boom(path):
        raise RuntimeError("bad codec")

    monkeypatch.setattr(video_service.ffmpeg_runner, "probe", _boom)

    video_service.run_transcode_job(asset.id)  # never raises

    failed = video_service.get_video(asset.id)
    assert failed.status == TranscodeStatus.FAILED
    assert "bad codec" in failed.error


# --- ingest route -----------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_route_queues_job_and_counts_metric(client, monkeypatch):
    from app.runtime import metrics

    monkeypatch.setattr(metrics, "_upload_count", 0)
    captured: list[str] = []

    def _fake_create(**kwargs):
        now = datetime.now(UTC)
        return VideoAsset(
            id="vid123", title="Clip", status=TranscodeStatus.TRANSCODING,
            ladder=LadderPreset.P720, source_key="videos/vid123/source.mp4",
            source_filename="clip.mp4", source_size_bytes=5,
            source_size_human="5 B", created_at=now, updated_at=now,
        )

    monkeypatch.setattr(video_service, "create_video", _fake_create)
    monkeypatch.setattr(video_service, "run_transcode_job", lambda vid: captured.append(vid))

    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
    resp = await client.post(
        "/videos",
        files={"file": ("clip.mp4", mp4, "video/mp4")},
        data={"ladder": "720p", "title": "Clip"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == "vid123"

    metrics_resp = await client.get("/metrics")
    assert "uploads_total 1" in metrics_resp.text


@pytest.mark.asyncio
async def test_ingest_route_rejects_bad_source(client, monkeypatch):
    def _raise(**kwargs):
        raise IngestError("bad", status_code=415)

    monkeypatch.setattr(video_service, "create_video", _raise)
    resp = await client.post(
        "/videos",
        files={"file": ("x.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        data={"ladder": "720p", "title": ""},
    )
    assert resp.status_code == 415
