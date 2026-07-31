<!-- last_verified: 2026-07-31 -->
# Feature: Dashboard

## Purpose
Provide an at-a-glance overview of transcode activity and the source → rendition write-amplification that makes self-hosted VOD on B2 economical.

## Used By
- UI: `/` page (dashboard home)
- API: `GET /videos/stats`

## Core Functions
- `apps/web/src/components/dashboard/transcode-stats-cards.tsx` — 4 stat cards (videos, renditions, source → rendition bytes, amplification)
- `apps/web/src/components/dashboard/recent-transcodes-table.tsx` — recent videos with status + amplification, linking to each detail page
- `apps/web/src/components/video/status-badge.tsx` — shared transcode-status badge
- `apps/web/src/lib/queries.ts` — `useVideoStats()` (polls every 5s)
- `services/api/app/runtime/videos.py` — `GET /videos/stats` handler
- `services/api/app/service/video.py` — `get_transcode_stats()` aggregation
- `services/api/app/repo/video_store.py` — `list_prefix()` + `read_json()` over the `videos/` manifests

## Canonical Files
- Dashboard cards pattern: `apps/web/src/components/dashboard/transcode-stats-cards.tsx`
- Stats service logic: `services/api/app/service/video.py`

## Inputs
- None (dashboard loads data automatically)

## Outputs
- `GET /videos/stats` → `TranscodeStats`: `total_videos`, `ready_videos`, `transcoding_videos`, `failed_videos`, `total_renditions`, `source_bytes(_human)`, `rendition_bytes(_human)`, `amplification_factor`, and `recent` (the 5 newest `VideoAsset`s)

## Flow
- Page loads → `useVideoStats` fetches `GET /videos/stats`, which lists every `asset.json` under `videos/` and aggregates counts, bytes, and the fleet-wide amplification factor
- Stat cards display total videos, total renditions, source → rendition bytes, and the amplification multiple
- The recent-transcodes table shows the newest videos with a status badge and per-video amplification; each title links to `/videos/{id}`
- The query re-polls every 5s so the numbers track in-flight jobs without a manual refresh

## Edge Cases
- API unavailable → cards and table show inline error states with retry
- No videos yet → cards read `0` / `—`; the table shows an empty state
- Fleet amplification with zero source bytes → `null`, rendered as `—` (never a divide-by-zero)
- Many videos → `get_transcode_stats` reads one manifest per video; fine for the demo scale (no queue/DB by design)

## UX States
- Loading: skeleton cards + skeleton table rows
- Empty: `0`/`—` cards and a "No transcodes yet" table
- Loaded: populated cards and recent-transcodes table

## Verification
- Test files: `services/api/tests/test_video_pipeline.py`
- Required cases: amplification math (incl. the divide-by-zero → None case), stats aggregation reflects manifest states
- Focused verify command: `pnpm test:api`
- Default pre-PR verify command: `pnpm verify`
- Full local verify command: `pnpm verify:full` when the E2E/live prerequisites in [Dev Workflows](../dev-workflows.md#commands) are available
- Pass criteria: focused tests and `pnpm verify` green; explain any skipped `pnpm verify:full` prerequisites

## Related Docs
- [ARCHITECTURE.md](../../ARCHITECTURE.md)
- [Transcode Pipeline](transcode-pipeline.md)
- [App Workflows](../app-workflows.md)
