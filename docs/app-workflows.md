<!-- last_verified: 2026-07-28 -->
# App Workflows

User journeys inside the application.

## Ingest a Video

- User navigates to `/upload` (Ingest)
- Drops or selects one source video (MP4 / MOV / WebM / MKV) in the dropzone
- Picks a quality ladder from a `Select` (default "Up to 720p", with a hint that 720p is a fast demo run) and an optional title
- A determinate progress bar tracks the source bytes leaving the browser
- On success: a toast, and a redirect to the video's detail page, which shows the transcoding state and updates itself
- The transcode runs in the background on the server (FFmpeg) — the user does not wait on the page for it
- On failure (oversize, unsupported container, spoofed bytes): a toast with the reason; the form stays editable
- See: [Video Ingest](features/video-ingest.md), [Transcode Pipeline](features/transcode-pipeline.md)

## Watch and Manage Videos

- User navigates to `/videos` — a grid of cards, each with a sprite thumbnail, a status badge, and its amplification factor
- Opening a card routes to `/videos/[id]`, which polls until the transcode is `ready` or `failed`
- On `ready`: an adaptive hls.js player (native HLS on Safari) streams the master playlist through the API proxy from B2; a rendition table lists each rung's resolution/bitrate/segments/size; an amplification card shows source vs rendition bytes
- **Rename**: a dialog opens pre-filled with the current title; saving updates the manifest
- **Re-transcode**: a dialog with a ladder `Select` re-runs FFmpeg on the stored source (e.g. to add a 1080p rung)
- **Delete**: a confirmation removes the entire `videos/{id}/` prefix and returns to the library
- See: [Video Library](features/video-library.md)

## Browse and Manage Files

- User navigates to `/files`
- Page loads the 100 most recent objects from the API (sorted most recent first). While it loads, the page says so on screen and escalates the wording if the wait runs long — a full bucket listing measured 2.8s-21s cold
- If that limit was hit, a notice states how many objects the bucket actually holds — the page never claims to show everything
- Files displayed in tree view with folders and type-specific icons
- Folders auto-expand on load until the *majority* of the listed files are reachable without clicking, so the page's own "click a file" instruction is always actionable. Stopping at the first visible file was not enough: one stray top-level object left the other 99 sealed in collapsed folders while the page claimed to show 100
- Clicking a file row opens its preview; the per-row actions menu (preview / download / delete) is always visible, on every viewport
- Arriving at `/files?preview=<key>` expands that file's folders and opens its preview directly. This is how the ⌘K palette and the dashboard's recent-uploads rows hand off a *specific* file; the param is consumed on arrival so it doesn't re-fire later
- **Preview**: opens dialog with image/PDF preview + metadata panel, and the file's Download / Delete actions — the advertised "click a file" path offers everything the row menu does. The loading state holds until the media paints; a failure offers "Open in a new tab". The preview URL is signed with `Content-Disposition: inline` so PDFs render in place
- **Download**: shows a pending state on the row plus a toast while the presigned URL is fetched, then starts the download via an anchor click (which, unlike a popup, still works if the click's user activation expired during a slow presign). Failures are reported; the click can never silently do nothing
- **Delete**: the confirmation dialog stays open showing "Deleting..." until the request settles, then the row disappears with the toast (optimistic cache update) and the list reconciles with the server. The dialog is held deliberately — Radix closes on action click by default, which dismissed the only pending state and left the row looking untouched while the delete was still in flight
- Empty bucket shows "No files found" with upload prompt
- See: [File Browser](features/file-browser.md)

## View Dashboard

- User navigates to `/` (home)
- `GET /videos/stats` loads and the cards show: total videos, total renditions, source → rendition bytes, and the fleet-wide write-amplification multiple
- The recent-transcodes table lists the newest videos with a status badge and per-video amplification; each title links through to its detail page
- The stats re-poll every few seconds so in-flight transcodes surface without a refresh
- Empty state: `0`/`—` cards and a "No transcodes yet" table
- See: [Dashboard](features/dashboard.md)

## Change Preferences

- User navigates to `/settings`
- A banner at the top states that the page is mostly a demonstration: only Theme is wired up for real, the rest showcases what a settings page can look like when you adapt the kit
- **Theme** (real): editing it and saving applies it immediately and persists it (`next-themes`), and the header's theme toggle drives the same state
- **Profile and preference fields** (demo): Display name, Bio, Default file view (Tree/List/Grid), Email me on every upload, Warn me when approaching quota + threshold. Each is labelled "Demo field", persists to `localStorage` only, and drives no behaviour — there is no account system, mailer, quota banner, activity log, or List/Grid view behind them yet
- Saving reports honestly: a success toast that separates the real theme change from the locally-stored demo values, or a warning toast if the browser blocked storage (theme still changes). It never claims a save that did not happen — the original page toasted "Settings saved" for fields that changed nothing
- Danger Zone actions are a demo — no real delete runs
- See: [Settings](features/settings.md)
