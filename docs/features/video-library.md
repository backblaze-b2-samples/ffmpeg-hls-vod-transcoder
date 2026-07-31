<!-- last_verified: 2026-07-31 -->
# Feature: Video Library

## Purpose
Browse every ingested video (scoped to the `videos/` prefix), then play, rename, re-transcode, or delete one.

## Used By
- UI: `/videos` (library grid) and `/videos/[id]` (detail)
- API: `GET /videos`, `GET /videos/{id}`, `PATCH /videos/{id}`, `DELETE /videos/{id}`, `POST /videos/{id}/retranscode`, and the HLS proxy `GET /videos/{id}/hls/{path}` + `GET /videos/{id}/thumbnail`

## Core Functions
- `apps/web/src/components/video/video-library-grid.tsx` + `video-card.tsx` — grid of cards (thumbnail + status badge + amplification)
- `apps/web/src/components/video/video-detail.tsx` — detail page: player + rendition table + amplification stat + actions
- `apps/web/src/components/video/hls-player.tsx` — hls.js player with native-HLS (Safari) fallback
- `apps/web/src/components/video/rendition-table.tsx`, `status-badge.tsx`, `rename-dialog.tsx`, `retranscode-dialog.tsx`
- `apps/web/src/lib/queries.ts` — `useVideos`, `useVideo` (polls while `transcoding`), `useRenameVideo`, `useRetranscodeVideo`, `useDeleteVideo`
- `services/api/app/runtime/videos.py` — CRUD + run handlers and the HLS/thumbnail proxy
- `services/api/app/service/video.py` — `list_videos`, `get_video`, `rename_video`, `delete_video` (prefix-scoped), `retranscode`

## Canonical Files
- CRUD + proxy handler pattern: `services/api/app/runtime/videos.py`
- Detail UI pattern: `apps/web/src/components/video/video-detail.tsx`

## Inputs
- Library: none (lists all manifests under `videos/`)
- Detail: `id` (route param)
- Rename: `{ title }`; Re-transcode: `{ ladder }`

## Outputs
- `GET /videos` → `VideoAsset[]` (newest first)
- `GET /videos/{id}` → `VideoAsset`
- `PATCH` → updated `VideoAsset` (title written to `asset.json`)
- `DELETE` → `{ deleted, id, objects }` after deleting the whole `videos/{id}/` prefix
- `POST /retranscode` → `IngestResponse` (manifest reset to `transcoding`, job re-queued)
- HLS proxy → streamed playlist/segment bytes; thumbnail → the sprite JPEG

## Flow
- The library lists every `asset.json` under `videos/` and renders a card per video; a ready card shows its sprite thumbnail and amplification
- Opening a card routes to the detail page, which fetches the manifest and **polls every 2s while `transcoding`**, then stops on `ready`/`failed`
- On `ready`, `hls-player` loads `GET /videos/{id}/hls/master.m3u8`; native HLS is used on Safari, otherwise hls.js over Media Source Extensions. The player, segment fetches, and the `<img>` thumbnail hit the API proxy directly (these routes are in `SERVER_ONLY_OPERATIONS`)
- The HLS proxy maps the request path to the B2 key 1:1 and streams the object — no playlist rewriting, so relative segment paths resolve
- Rename opens **pre-filled** with the current title; Re-transcode offers a ladder `Select`; Delete confirms, then removes the whole prefix and returns to the library

## Edge Cases
- Missing/deleted video → `GET /videos/{id}` returns 404
- Proxy path with `..` or a leading `/` → 400 (traversal guard)
- Proxy object missing → 404; storage read error → 502
- Browser without native HLS and without MSE → the player shows an "unsupported" message instead of a broken frame
- Delete → only objects under `videos/{id}/` are removed; `delete_prefix` refuses an unscoped prefix, so a bucket-wide wipe is impossible
- Re-transcode while already `transcoding` → the dialog trigger is disabled

## UX States
- Library — Loading: skeleton cards; Empty: "No videos yet" CTA; Error: inline retry
- Detail — Loading: skeletons; Transcoding: spinner placeholder that auto-updates; Failed: error alert with the message + Re-transcode; Ready: player + amplification card + rendition table

## Verification
- Test files: `services/api/tests/test_video_pipeline.py` (list/get/rename/delete + prefix-scope guard), `apps/web/src/lib/api-contract.test.ts` (HLS proxy + thumbnail registered as server-only)
- Required cases: rename updates the manifest, delete is prefix-scoped to `videos/{id}/`, `delete_prefix` refuses a bucket-wide prefix, missing video raises, the proxy routes are declared server-only
- Focused verify command: `pnpm test:api`
- Default pre-PR verify command: `pnpm verify`
- Full local verify command: `pnpm verify:full` when the E2E/live prerequisites in [Dev Workflows](../dev-workflows.md#commands) are available
- Pass criteria: focused tests and `pnpm verify` green; explain any skipped `pnpm verify:full` prerequisites

## Related Docs
- [ARCHITECTURE.md](../../ARCHITECTURE.md)
- [Video Ingest](video-ingest.md)
- [Transcode Pipeline](transcode-pipeline.md)
- [App Workflows](../app-workflows.md)
