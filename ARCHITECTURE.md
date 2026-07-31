<!-- last_verified: 2026-07-28 -->
# Architecture

## Components

- **apps/web/** — Next.js 16 frontend (App Router, Tailwind v4, shadcn/ui)
  - Dashboard with transcode metrics + write-amplification
  - Video Ingest (dropzone + ladder select) and Video Library (grid + hls.js detail)
  - File browser with preview, download, delete (shows fanned-out rendition objects)
  - Dark mode via `next-themes`
- **services/api/** — FastAPI backend (layered architecture)
  - REST API for video ingest, transcode, library CRUD, and the HLS playback proxy
  - Local FFmpeg transcoding (via the bundled `imageio-ffmpeg` binary)
  - B2 S3 integration via boto3
  - Health check endpoint with B2 connectivity verification
  - Structured JSON logging with request tracing
  - Prometheus-format metrics endpoint
- **packages/shared/** — TypeScript type definitions
  - Mirrors Pydantic models from the API
  - Consumed by `apps/web/` as workspace dependency

## Backend Layering

The API follows a strict layered architecture:

```
types/     Pydantic models — no logic, no imports from other layers
  |
config/    Settings (pydantic-settings) — depends only on types
  |
repo/      Data access (boto3 B2 client) — no business logic
  |
service/   Business logic — calls repo, returns types
  |
runtime/   FastAPI routes — calls service, never repo directly
```

### Layering Rules

1. Dependencies flow downward only: `types` -> `config` -> `repo` -> `service` -> `runtime`
2. No backward imports (e.g., service must not import from runtime)
3. `boto3` only allowed in `repo/` layer
4. All boundary data uses Pydantic models (no raw dicts across layers)
5. Each file stays under 300 lines

### Directory Structure

```
services/api/
  main.py                  App entrypoint, middleware, router registration
  app/
    types/                 Pydantic models (VideoAsset, Rendition, FileMetadata, ...)
    config/                Settings loaded from environment
    repo/                  Data access: b2_client + video_store (boto3), ffmpeg_runner + sprite (FFmpeg subprocess)
    service/               Business logic (video orchestration, ingest validation, files, metadata)
    runtime/               FastAPI route handlers (videos incl. the HLS proxy, files, health, metrics)
  tests/                   pytest tests (structural + integration)
```

## Boundary Invariants

- **No external SDK/tool leakage**: `boto3` and the FFmpeg `subprocess` calls are only in `app/repo/` (`b2_client`/`video_store` for B2; `ffmpeg_runner`/`sprite` for FFmpeg). All other layers go through the repo interface. `service/video.py` orchestrates but never shells out or calls boto3 directly.
- **No raw dicts at boundaries**: All data crossing layer boundaries uses typed Pydantic models.
- **No cross-layer mutable state**: Configuration is read-only after init, and no mutable state is shared *between* layers. Intra-layer caches/counters (the listing cache in `repo/list_cache.py`, the B2 connectivity cache in `repo/b2_client.py`, the download counter in `repo/counter.py`, the rate-limit and metrics state in `runtime/`) are module-local and guarded by a `threading.Lock`. The listing cache also owns the only background thread in the app: a stale entry is served immediately while that thread re-scans (stale-while-revalidate), and `main.lifespan` warms it once at startup so no user pays for the cold full-bucket scan.
- **Validated inputs**: All HTTP inputs validated by FastAPI/Pydantic. File keys reject empty and path-traversal patterns; optional prefix confinement via `ALLOWED_KEY_PREFIX` (off by default).

## Deployment

- **Local dev** — `pnpm dev` runs both services via `concurrently`
  - Web: `localhost:3000`
  - API: `localhost:8000`
- **Railway** — two services from the same repository: `web` builds from the
  repository root because it consumes `packages/shared`; `api` builds from
  `services/api`. The versioned per-service configs and the human-approved
  staging/production contract live in [infra/railway/README.md](infra/railway/README.md).
  External provisioning and deployment remain explicit user-approved actions.

## Data Stores

- **Backblaze B2** — object storage (S3-compatible API)
  - All app data lives under the `videos/` prefix; each video owns a `videos/{id}/` subtree
  - The per-video `asset.json` manifest is the record of truth — **there is no application database**
  - Listing/metadata via S3 `list_objects_v2` / `head_object`; playback streams via `get_object`

### Per-video B2 layout

```
videos/{id}/source.<ext>            # original upload
videos/{id}/asset.json              # manifest: title, status, source_size, renditions[], amplification
videos/{id}/hls/master.m3u8         # multivariant playlist (relative variant paths)
videos/{id}/hls/{360p,720p,1080p}/index.m3u8
videos/{id}/hls/{360p,720p,1080p}/seg_00001.ts …
videos/{id}/thumbs/sprite.jpg       # scrub-preview sprite sheet
videos/{id}/thumbs/sprite.vtt       # WebVTT cue map into the sprite
```

## External Services

- **Backblaze B2 S3 API** — file storage, retrieval, deletion, presigned URLs

## Trust Boundaries

See [docs/SECURITY.md](docs/SECURITY.md) for full security documentation.

- **Frontend -> API** — CORS-restricted to configured origins. `CORSMiddleware` is registered LAST in `main.py` (outermost) so it wraps **every** response, including uncaught-exception 500s — otherwise the browser would block error responses and the UI would only see an opaque "network error". See [docs/RELIABILITY.md](docs/RELIABILITY.md#error-handling). A per-IP rate-limit middleware sits inner to CORS; see [docs/SECURITY.md](docs/SECURITY.md#rate-limiting).
- **API -> B2** — authenticated via application keys, signature v4
- **Client -> B2** — presigned URLs for download (10-min expiry, forced attachment)

## Data Flows

- **Ingest**: Browser -> `POST /videos` (multipart) -> API streams source to a temp file (size-capped, RAM-safe) -> `service.create_video` validates (container + magic bytes) -> repo uploads to `videos/{id}/source.<ext>` -> writes `transcoding` manifest -> schedules the background job -> `IngestResponse`
- **Transcode job** (`BackgroundTasks`, runs after the response): `run_transcode_job` -> repo downloads source to temp -> `ffmpeg_runner.probe` -> `ffmpeg_runner.transcode_hls` (per-rung playlists + segments + master) -> `sprite.generate_sprite` -> repo uploads the derived tree -> manifest flipped to `ready` (with renditions + `amplification_factor`) or `failed` + error
- **HLS playback**: `<video>`/hls.js -> `GET /videos/{id}/hls/{path}` -> repo `get_object` streams the playlist/segment straight from B2 with a 1:1 request-path -> B2-key map (no playlist rewriting). The thumbnail sprite streams the same way via `GET /videos/{id}/thumbnail`
- **Library / detail**: Browser -> `GET /videos` / `GET /videos/{id}` -> service reads manifests -> returns `VideoAsset(s)`; the detail query polls while `transcoding`
- **Rename / Re-transcode / Delete**: `PATCH` updates the manifest title; `POST .../retranscode` resets the manifest and re-queues the job; `DELETE` removes the entire `videos/{id}/` prefix (scoped batch delete — never bucket-wide)

## Observability

- Structured JSON logging on all requests with `request_id`
- Request timing middleware (logs duration per request; also the catch-all that converts uncaught exceptions to a typed JSON 500)
- `/metrics` endpoint (Prometheus format: request count, latency, upload count)
- `/health` endpoint (B2 connectivity check)

## API Contract

- Checked-in OpenAPI artifact: `docs/api/openapi.json`
- Export/check command: `pnpm contract:export` / `pnpm contract:check`
- FastAPI freshness test: `services/api/tests/test_openapi_contract.py`
- Frontend route drift test: `apps/web/src/lib/api-contract.test.ts`

The frontend client keeps a small `API_CLIENT_ROUTES` registry in
`apps/web/src/lib/api-client.ts`. Tests compare that registry to the checked-in
OpenAPI artifact so route changes fail loudly before the hand-written client can
silently drift from FastAPI. `GET /metrics`, the HLS proxy
`GET /videos/{video_id}/hls/{path}`, and `GET /videos/{video_id}/thumbnail` are
intentionally server-only (hit by scrapers / hls.js / `<img>` directly), so they
live in `SERVER_ONLY_OPERATIONS` rather than the client registry.

## Canonical Files

- Layered API handler (routes + HLS proxy): `services/api/app/runtime/videos.py`
- Service orchestration + transcode worker: `services/api/app/service/video.py`
- FFmpeg subprocess adapter (repo layer): `services/api/app/repo/ffmpeg_runner.py`
- B2 data access (repo layer): `services/api/app/repo/b2_client.py`, `services/api/app/repo/video_store.py`
- Pydantic models: `services/api/app/types/` (`video.py`, `files.py`, `stats.py`, `formatting.py`)
- Config (pydantic-settings): `services/api/app/config/settings.py`
- Structural tests: `services/api/tests/test_structure.py`
- OpenAPI contract: `docs/api/openapi.json`
- OpenAPI exporter: `services/api/scripts/export_openapi.py`
- Frontend API client: `apps/web/src/lib/api-client.ts`
- Shared TypeScript types: `packages/shared/src/types.ts`

## Core Features

- [Video Ingest](docs/features/video-ingest.md)
- [Transcode Pipeline](docs/features/transcode-pipeline.md)
- [Video Library](docs/features/video-library.md)
- [File Browser](docs/features/file-browser.md)
- [Dashboard](docs/features/dashboard.md)
- [Metadata Extraction](docs/features/metadata-extraction.md)

## References

- [docs/SECURITY.md](docs/SECURITY.md) — security principles and implementation
- [docs/RELIABILITY.md](docs/RELIABILITY.md) — reliability expectations
- [AGENTS.md](AGENTS.md) — architectural invariants and agent instructions
