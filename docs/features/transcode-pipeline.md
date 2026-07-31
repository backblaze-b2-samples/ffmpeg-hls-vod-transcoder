<!-- last_verified: 2026-07-31 -->
# Feature: Transcode Pipeline

## Purpose
Fan one source video into a multi-bitrate HLS ladder + thumbnail sprite with local FFmpeg, store every artifact on B2, and record the write-amplification factor.

## Used By
- Job: `run_transcode_job` (FastAPI `BackgroundTasks` worker)
- API: triggered by `POST /videos` and `POST /videos/{id}/retranscode`
- UI: observed on `/videos/[id]` by polling `GET /videos/{id}`

## Core Functions
- `services/api/app/service/video.py` — `run_transcode_job()` orchestration (download → probe → transcode → sprite → upload → flip manifest), ladder expansion, and amplification math
- `services/api/app/repo/ffmpeg_runner.py` — the FFmpeg subprocess adapter: `probe()`, `transcode_hls()`, `select_video_encoder()`
- `services/api/app/repo/sprite.py` — `generate_sprite()` (sprite sheet + WebVTT)
- `services/api/app/repo/video_store.py` — `download_to()`, `put_file()`, `delete_prefix()`, `write_json()`
- `services/api/app/types/video.py` — `LADDER_RUNGS`, `rungs_for()`, `compute_amplification()`

## Canonical Files
- FFmpeg adapter pattern (subprocess only in `repo/`): `services/api/app/repo/ffmpeg_runner.py`
- Worker orchestration pattern: `services/api/app/service/video.py`

## Inputs
- A stored source at `videos/{id}/source.<ext>` and a manifest with `status: "transcoding"` + a chosen `ladder`

## Outputs
- Per-video B2 artifacts: `hls/master.m3u8`, `hls/{rung}/index.m3u8`, `hls/{rung}/seg_*.ts`, `thumbs/sprite.jpg`, `thumbs/sprite.vtt`
- Manifest updated to `ready` with `renditions[]`, `rendition_bytes`, `amplification_factor`, `master_playlist_key`, `thumbnail_key`, `duration_seconds`, `width`/`height`, `progress` = 1.0, `stage` = `"ready"` — or to `failed` + `error`
- While the job runs it also writes a determinate `progress` (0.0..1.0) + a coarse `stage` label onto the manifest, so the polling detail page renders a real progress bar instead of an indeterminate spinner

## Flow
- The worker reads the manifest, then clears any prior `hls/` + `thumbs/` objects (so a re-transcode leaves no orphan segments — each `delete_prefix` is scoped to `videos/{id}/hls/` or `.../thumbs/`)
- It downloads the source to a temp dir (never buffered in RAM)
- `probe()` reads duration + width/height via `ffprobe` if present, otherwise by parsing `ffmpeg -i` stderr — so `ffprobe` is never a hard dependency
- `transcode_hls()` expands the ladder preset into every rung at or below its height, and for each rung runs one FFmpeg invocation that emits `hls/{rung}/index.m3u8` + `seg_*.ts`. A rung taller than the source is dropped — the encoder never upscales
- A `master.m3u8` is written with relative variant paths, so the B2 layout mirrors the playlist references 1:1 and the [HLS proxy](video-library.md) needs no rewriting
- `generate_sprite()` samples frames into `thumbs/sprite.jpg` + a WebVTT cue map (best-effort; a sprite failure does not fail the job). These are the standard HLS thumbnail-track artifacts that scrub-preview-capable / CDN players consume; the bundled hls.js demo player uses `sprite.jpg` as the `<video>` poster rather than a hover-scrub overlay, so the artifacts are produced and stored but the minimal player does not render a scrub-preview UI
- Every derived file is uploaded preserving its relative path under `videos/{id}/`; `rendition_bytes` totals the derived bytes
- As the job advances it persists a determinate `progress` (0.0..1.0) + `stage` label onto the manifest — probe (0.05) → per-rung encode (rungs_done / rungs_total mapped into 0.10..0.85) → thumbnails (0.90) → ready (1.0) — via the `runtime → service → repo` layering (the service passes an `on_rung_done` callback into `ffmpeg_runner.transcode_hls`)
- The manifest is flipped to `ready` with `amplification_factor = rendition_bytes / source_bytes`

## Hardware-encoder policy
CPU `libx264` + AAC is the always-available default from the bundled `imageio-ffmpeg` build. When `HWACCEL_AUTODETECT` is on, `select_video_encoder()` probes the binary's encoder list and prefers `h264_videotoolbox` (macOS) or `h264_nvenc` (CUDA) **only if present**, always falling back to `libx264`. A GPU is never required — this mirrors the CUDA → MPS → CPU rule used elsewhere in the sample family.

## B2 write-amplification economics
Adaptive streaming stores the same content several times: a 360p + 720p + 1080p ladder, each segmented, plus playlists, a master manifest, and a sprite. A typical H.264 ladder lands around **3–5× the source size** in derived objects. Managed VOD services bill that fan-out at a premium; on B2 it costs a fraction, which is what makes self-hosting viable. The pipeline records the ratio per video and the dashboard aggregates it fleet-wide. B2's flat egress-friendly pricing also suits the proxied playback path, where segments are read back on demand.

## Edge Cases
- Source shorter/smaller than every rung → `transcode_hls` raises; the manifest records `failed` + error
- FFmpeg non-zero exit on a rung → `RuntimeError` with the tail of stderr; job marked `failed`
- Sprite generation fails → logged; the video still becomes `ready` with `thumbnail_key = null`
- Worker exception anywhere → caught and persisted as `failed` (`run_transcode_job` never raises)
- Re-transcode with a different ladder → prior renditions are deleted first, then rebuilt

## DASH — future extension
Only **HLS** is built (it is in the sample's name and drives the hls.js player). MPEG-DASH would be an easy addition: FFmpeg can emit a DASH manifest + segments (`-f dash`) alongside HLS into `videos/{id}/dash/`, served through the same proxy pattern. It is intentionally left as a documented extension — building both players + pipelines doubles the work for no additional B2 story.

## Verification
- Test files: `services/api/tests/test_video_pipeline.py`
- Required cases: ladder expands to rungs at/below the ceiling, amplification math (incl. divide-by-zero → None), manifest read/write round-trip, `run_transcode_job` flips to `ready` with renditions + amplification (FFmpeg mocked), the manifest's `progress` advances monotonically 0→1 with a `stage` label as the job runs, a worker exception is recorded as `failed`. Unit tests **mock the FFmpeg subprocess** so `verify:api` stays credential-free and fast — a real end-to-end transcode is exercised later by the pipeline `verify` step
- Focused verify command: `pnpm test:api`
- Default pre-PR verify command: `pnpm verify`
- Full local verify command: `pnpm verify:full` when the E2E/live prerequisites in [Dev Workflows](../dev-workflows.md#commands) are available
- Pass criteria: focused tests and `pnpm verify` green; explain any skipped `pnpm verify:full` prerequisites

## Related Docs
- [ARCHITECTURE.md](../../ARCHITECTURE.md)
- [Video Ingest](video-ingest.md)
- [Video Library](video-library.md)
