<!-- last_verified: 2026-07-31 -->
# Feature: Video Ingest

## Purpose
Upload a source video to Backblaze B2 and queue it for HLS transcoding.

## Used By
- UI: `/upload` (Ingest) page, `ingest-form` component
- API: `POST /videos`
- Job: kicks the background transcode worker (see [Transcode Pipeline](transcode-pipeline.md))

## Core Functions
- `apps/web/src/components/video/ingest-form.tsx` — dropzone + quality-ladder `Select` (default 720p) + title `Input`, submits via the create mutation and redirects to the new detail page
- `apps/web/src/components/upload/dropzone.tsx` — drag-and-drop via `react-dropzone`, parametrized (`accept`, `multiple`, `maxSize`, copy)
- `apps/web/src/lib/api-client.ts` — `createVideo()` (XHR, for upload-progress events)
- `apps/web/src/lib/queries.ts` — `useCreateVideo()` mutation
- `services/api/app/runtime/videos.py` — `POST /videos` handler: streams the source to a temp file, enforces the size cap, schedules `run_transcode_job`
- `services/api/app/service/ingest.py` — `validate_source()`: container extension + magic-byte sniff + size cap
- `services/api/app/service/video.py` — `create_video()`: uploads the source, writes the `transcoding` manifest
- `services/api/app/repo/video_store.py` — `put_file()` (streamed `put_object`), `write_json()` (manifest)

## Canonical Files
- Ingest handler pattern: `services/api/app/runtime/videos.py`
- Source-validation pattern: `services/api/app/service/ingest.py`
- Form-UX exemplar: `apps/web/src/components/settings/settings-form.tsx`

## Inputs
- file: `File` (multipart form data) — MP4 / MOV / WebM / MKV
- ladder: `LadderPreset` (`360p` | `720p` | `1080p`, form field, default `720p`)
- title: string (optional; defaults to the source filename)

## Outputs
- `IngestResponse`: `id`, `title`, `status` (always `transcoding` at this point)
- Side effects: source stored at `videos/{id}/source.<ext>`; `videos/{id}/asset.json` written with `status: "transcoding"`; a `BackgroundTasks` transcode job is queued; the `uploads_total` metric increments

## Flow
- User drops or selects a source video and picks a ladder + title in the Ingest form
- The browser streams a multipart `POST /videos` with XHR progress events
- The API streams the body to a temp file in 1 MB chunks, enforcing the 200 MB cap as it goes (never buffering the whole video in RAM), and captures the first 32 bytes for sniffing
- `validate_source` checks the container extension is supported, the leading bytes match that container (ISO-BMFF `ftyp` for mp4/mov, EBML magic for webm/mkv), and the size is under the cap — the client-declared MIME is not trusted
- `create_video` uploads the temp file to `videos/{id}/source.<ext>` and writes the `transcoding` manifest
- The handler schedules `run_transcode_job(id)` and returns `IngestResponse`
- The form redirects to `/videos/{id}`, which polls `GET /videos/{id}` until the status is terminal

## Edge Cases
- Source exceeds 200 MB → streamed rejection with 413 (client also enforces via dropzone `maxSize`)
- Unsupported container extension → API returns 415
- Contents don't match the extension (e.g. a PNG renamed `.mp4`) → API returns 415
- Empty file → API returns 400 (raised as an `IngestError`)
- Same source uploaded twice → each ingest gets a fresh `id`/prefix; no dedup
- B2 unreachable during upload → API returns 500; the form surfaces the error toast

## UX States
- Empty: dropzone with "Drag & drop a source video" copy
- Selected: a file chip with name + size and a remove button
- Uploading: a determinate progress bar ("Uploading source… N%")
- Error: toast with the rejection reason; the form stays editable
- Success: redirect to the detail page, which shows the transcoding state

## Verification
- Test files: `services/api/tests/test_ingest_validation.py`, `services/api/tests/test_video_pipeline.py`
- Required cases: accept mp4/mov/webm/mkv signatures, reject non-video extension (415), reject spoofed bytes (415), reject oversize (413), reject empty (400), ingest route queues the job and increments `uploads_total`, ingest route maps `IngestError` to its status code
- Focused verify command: `pnpm test:api`
- Default pre-PR verify command: `pnpm verify`
- Full local verify command: `pnpm verify:full` when the E2E/live prerequisites in [Dev Workflows](../dev-workflows.md#commands) are available
- Pass criteria: focused tests and `pnpm verify` green; explain any skipped `pnpm verify:full` prerequisites

## Related Docs
- [ARCHITECTURE.md](../../ARCHITECTURE.md)
- [Transcode Pipeline](transcode-pipeline.md)
- [Video Library](video-library.md)
- [App Workflows](../app-workflows.md)
