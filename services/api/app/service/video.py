"""VOD orchestration: ingest, the background transcode job, CRUD, and stats.

The per-video `asset.json` manifest in B2 is the single source of truth — there
is no database. Each verb reads/writes that manifest; the transcode worker flips
it `transcoding -> ready|failed`. Ladder expansion and write-amplification math
live here; all FFmpeg work is delegated to `repo/ffmpeg_runner` + `repo/sprite`,
all B2 work to `repo/video_store`.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
import uuid
from datetime import UTC, datetime

from app.config import settings
from app.repo import ffmpeg_runner, sprite, video_store
from app.service.ingest import validate_source
from app.types.video import (
    LadderPreset,
    Rendition,
    TranscodeStatsResponse,
    TranscodeStatus,
    VideoAsset,
    bytes_human,
    compute_amplification,
    rungs_for,
)

logger = logging.getLogger(__name__)

# Derived artifacts live in these sub-prefixes under videos/{id}/. Kept as a
# tuple so the upload walk and the pre-retranscode cleanup agree on the set.
_DERIVED_DIRS = ("hls", "thumbs")


class VideoNotFoundError(Exception):
    """Raised when a video id has no manifest in B2."""


def _prefix(video_id: str) -> str:
    return f"{settings.video_prefix}{video_id}/"


def _source_key(video_id: str, ext: str) -> str:
    return f"{_prefix(video_id)}source.{ext}"


def _manifest_key(video_id: str) -> str:
    return f"{_prefix(video_id)}asset.json"


def _now() -> datetime:
    return datetime.now(UTC)


def _publish_progress(asset: VideoAsset, stage: str, progress: float) -> None:
    """Persist progress (0..1) + stage on the manifest so the polling detail page
    shows a determinate bar. Best-effort: a failed write never aborts the job."""
    asset.progress = round(progress, 3)
    asset.stage = stage
    asset.updated_at = _now()
    with contextlib.suppress(Exception):
        video_store.write_json(_manifest_key(asset.id), asset.model_dump())


# --- CRUD ------------------------------------------------------------------


def create_video(
    source_path: str,
    filename: str,
    size_bytes: int,
    head: bytes,
    ladder: LadderPreset,
    title: str,
) -> VideoAsset:
    """Validate a source, upload it to B2, and write a `transcoding` manifest.

    Does NOT run the transcode — the caller schedules `run_transcode_job` in the
    background. Raises `ingest.IngestError` on a bad source.
    """
    safe_name, ext, content_type = validate_source(filename, size_bytes, head)
    video_id = uuid.uuid4().hex[:12]
    source_key = _source_key(video_id, ext)
    video_store.put_file(source_path, source_key, content_type)

    now = _now()
    asset = VideoAsset(
        id=video_id,
        title=(title or "").strip() or safe_name,
        status=TranscodeStatus.TRANSCODING,
        progress=0.0,
        stage="queued",
        ladder=ladder,
        source_key=source_key,
        source_filename=safe_name,
        source_size_bytes=size_bytes,
        source_size_human=bytes_human(size_bytes),
        created_at=now,
        updated_at=now,
    )
    video_store.write_json(_manifest_key(video_id), asset.model_dump())
    logger.info("Video ingested: id=%s ladder=%s size=%d", video_id, ladder, size_bytes)
    return asset


def get_video(video_id: str) -> VideoAsset | None:
    data = video_store.read_json(_manifest_key(video_id))
    return VideoAsset.model_validate(data) if data else None


def list_videos() -> list[VideoAsset]:
    """Every video, newest first, read from its manifest under `videos/`."""
    assets: list[VideoAsset] = []
    for obj in video_store.list_prefix(settings.video_prefix):
        if not obj["key"].endswith("/asset.json"):
            continue
        data = video_store.read_json(obj["key"])
        if data:
            assets.append(VideoAsset.model_validate(data))
    assets.sort(key=lambda a: a.created_at, reverse=True)
    return assets


def rename_video(video_id: str, title: str) -> VideoAsset:
    asset = get_video(video_id)
    if not asset:
        raise VideoNotFoundError(video_id)
    asset.title = title.strip()
    asset.updated_at = _now()
    video_store.write_json(_manifest_key(video_id), asset.model_dump())
    return asset


def delete_video(video_id: str) -> int:
    """Delete the whole `videos/{id}/` prefix (scoped batch delete). Returns the
    object count removed. Never touches data outside this video's prefix."""
    if not video_id:
        raise VideoNotFoundError(video_id)
    return video_store.delete_prefix(_prefix(video_id))


def retranscode(video_id: str, ladder: LadderPreset) -> VideoAsset:
    """Reset the manifest to `transcoding` for the new ladder. The caller
    schedules `run_transcode_job`, which re-runs FFmpeg on the stored source."""
    asset = get_video(video_id)
    if not asset:
        raise VideoNotFoundError(video_id)
    asset.status = TranscodeStatus.TRANSCODING
    asset.progress = 0.0
    asset.stage = "queued"
    asset.ladder = ladder
    asset.renditions = []
    asset.rendition_bytes = 0
    asset.rendition_bytes_human = bytes_human(0)
    asset.amplification_factor = None
    asset.master_playlist_key = None
    asset.thumbnail_key = None
    asset.error = None
    asset.updated_at = _now()
    video_store.write_json(_manifest_key(video_id), asset.model_dump())
    return asset


def get_transcode_stats() -> TranscodeStatsResponse:
    videos = list_videos()
    source_bytes = sum(v.source_size_bytes for v in videos)
    rendition_bytes = sum(v.rendition_bytes for v in videos)
    return TranscodeStatsResponse(
        total_videos=len(videos),
        ready_videos=sum(v.status == TranscodeStatus.READY for v in videos),
        transcoding_videos=sum(v.status == TranscodeStatus.TRANSCODING for v in videos),
        failed_videos=sum(v.status == TranscodeStatus.FAILED for v in videos),
        total_renditions=sum(len(v.renditions) for v in videos),
        source_bytes=source_bytes,
        source_bytes_human=bytes_human(source_bytes),
        rendition_bytes=rendition_bytes,
        rendition_bytes_human=bytes_human(rendition_bytes),
        amplification_factor=compute_amplification(source_bytes, rendition_bytes),
        recent=videos[:5],
    )


# --- Background transcode worker -------------------------------------------


def run_transcode_job(video_id: str) -> None:
    """Worker: download source -> probe -> transcode ladder -> sprite -> upload
    renditions -> flip the manifest to `ready` (or `failed` + error).

    Runs in a threadpool (FastAPI BackgroundTasks). Never raises — a failure is
    persisted on the manifest so the UI can surface it.
    """
    asset = get_video(video_id)
    if not asset:
        logger.warning("Transcode job for missing video id=%s", video_id)
        return

    workdir = tempfile.mkdtemp(prefix=f"vod-{video_id}-")
    try:
        _transcode_into(asset, workdir)
    except Exception as e:  # persist the failure, never crash the worker
        logger.exception("Transcode failed for id=%s", video_id)
        latest = get_video(video_id) or asset
        latest.status = TranscodeStatus.FAILED
        latest.error = str(e)[:500]
        latest.updated_at = _now()
        video_store.write_json(_manifest_key(video_id), latest.model_dump())
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _transcode_into(asset: VideoAsset, workdir: str) -> None:
    prefix = _prefix(asset.id)
    # Clear any prior renditions so a re-transcode never leaves orphan segments.
    for name in _DERIVED_DIRS:
        with contextlib.suppress(ValueError, RuntimeError):
            video_store.delete_prefix(f"{prefix}{name}/")

    source_local = os.path.join(workdir, "_src", os.path.basename(asset.source_key))
    os.makedirs(os.path.dirname(source_local), exist_ok=True)
    video_store.download_to(asset.source_key, source_local)

    _publish_progress(asset, "probing source", 0.05)
    probe = ffmpeg_runner.probe(source_local)

    def _on_rung_done(done: int, total: int) -> None:
        # Rung fraction maps into the encode band [0.10, 0.85].
        pct = 0.1 + 0.75 * (done / total if total else 1.0)
        _publish_progress(asset, f"encoding rendition {done}/{total}", pct)

    outputs = ffmpeg_runner.transcode_hls(
        source_local, workdir, rungs_for(asset.ladder), probe.width, probe.height,
        on_rung_done=_on_rung_done,
    )
    _publish_progress(asset, "generating thumbnails", 0.9)
    sprite_result = sprite.generate_sprite(source_local, workdir, probe.duration_seconds)

    rendition_bytes = _upload_derived(workdir, prefix)
    renditions = [_rendition_for(out, prefix) for out in outputs]

    asset.status = TranscodeStatus.READY
    asset.progress = 1.0
    asset.stage = "ready"
    asset.duration_seconds = probe.duration_seconds
    asset.width, asset.height = probe.width, probe.height
    asset.renditions = renditions
    asset.rendition_bytes = rendition_bytes
    asset.rendition_bytes_human = bytes_human(rendition_bytes)
    asset.amplification_factor = compute_amplification(
        asset.source_size_bytes, rendition_bytes
    )
    asset.master_playlist_key = f"{prefix}hls/master.m3u8"
    asset.thumbnail_key = f"{prefix}thumbs/sprite.jpg" if sprite_result else None
    asset.error = None
    asset.updated_at = _now()
    video_store.write_json(_manifest_key(asset.id), asset.model_dump())
    logger.info(
        "Transcode ready: id=%s renditions=%d amplification=%s",
        asset.id, len(renditions), asset.amplification_factor,
    )


def _rendition_for(out: ffmpeg_runner.RungOutput, prefix: str) -> Rendition:
    size = os.path.getsize(out.playlist_path) + sum(
        os.path.getsize(seg) for seg in out.segment_paths
    )
    return Rendition(
        name=out.name,
        height=out.height,
        width=out.width,
        video_kbps=out.video_kbps,
        playlist_key=f"{prefix}hls/{out.name}/index.m3u8",
        segment_count=len(out.segment_paths),
        size_bytes=size,
        size_human=bytes_human(size),
    )


def _upload_derived(workdir: str, prefix: str) -> int:
    """Upload every derived artifact (hls tree + thumbs) to B2, preserving the
    relative path 1:1 under the video prefix. Returns total bytes written."""
    total = 0
    for name in _DERIVED_DIRS:
        root = os.path.join(workdir, name)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fname in files:
                local = os.path.join(dirpath, fname)
                rel = os.path.relpath(local, workdir).replace(os.sep, "/")
                total += video_store.put_file(local, f"{prefix}{rel}")
    return total
