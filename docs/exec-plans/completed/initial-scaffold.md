# Build plan — `ffmpeg-hls-vod-transcoder`

Source of truth for the starter tree: `.claude/scratch/vcsk-706cc512-c4d4-4dee-8266-8cb563fd2bce/`
(freshly cloned in Phase 0). All keep/trim/add deltas below are computed against that tree.

---

## 1. Purpose

`ffmpeg-hls-vod-transcoder` is a **self-hosted VOD (video-on-demand) transcoding pipeline** backed
by Backblaze B2 — a Mux / Cloudflare-Stream alternative at B2 storage costs. A creator, VOD-platform
operator, or archivist uploads a **source video**; the app runs **FFmpeg locally** to fan that one
source out into a multi-bitrate **HLS adaptive-bitrate ladder** (360p / 720p / 1080p) plus a
**thumbnail sprite**, writes every rendition segment, playlist, master manifest, and sprite **back to
B2 per-video**, and streams the result adaptively in the browser via **hls.js** through a thin API
proxy. The B2 story is **write amplification**: one source upload becomes 3–5× storage in derived
renditions, and B2's cheap object storage is what makes self-hosted VOD economical — the dashboard
surfaces that source→rendition amplification factor as the headline metric.

Heavy workload is **on-device FFmpeg**, so it is `deployment: local` with **no external API provider
and no second key** — B2 credentials only. CPU/`libx264` software encoding is the portable default
(optional hardware-encoder autodetect, never required — see §4).

---

## 2. Architecture delta from vibe-coding-starter-kit

The starter kit is the ceiling. Keep the reusable B2 scaffolding + design system; strip the generic
image/PDF-centric surfaces this app doesn't need; add the video pipeline.

| KEEP (as-is) | TRIM (remove/replace) | ADD (new for this app) |
|---|---|---|
| UI kit `apps/web/src/components/ui/**` (generated — never edit) | Generic `POST /upload` **evolves** into video ingest: `service/upload.py`→`service/ingest.py`, `runtime/upload.py` ingest handler folds into `runtime/videos.py` (reuse streaming + magic-byte machinery, retarget to video containers) | **Videos Library** page `/videos` (scoped asset explorer, `videos/` prefix) — the sample-specific scoped explorer |
| Design tokens `apps/web/src/app/globals.css` + `/design` page | Image/PDF-only `ALLOWED_TYPES` in the upload path (retarget to video/* container types) | **Video detail** page `/videos/[id]` — hls.js adaptive player + rendition table + amplification stat + Rename / Re-transcode / Delete actions |
| **Bucket explorer** `/files`, `app/files/`, `components/files/**` — full-bucket browse (**NON-NEGOTIABLE keep**; shows the fanned-out rendition objects, so it's a perfect fit) | Upload tests `tests/test_upload_*.py` → adapt to ingest (`tests/test_ingest_*.py`) | `types/video.py` (Pydantic models), `repo/ffmpeg_runner.py` (FFmpeg subprocess adapter), `service/video.py` (orchestration + jobs), `runtime/videos.py` (CRUD+run + HLS proxy) |
| Sidebar nav shell `components/layout/app-sidebar.tsx` (relabel entries, keep structure) | Dashboard default content (stats-cards / upload-chart / recent-uploads) — **adapt** per AGENTS.md §2 (Dashboard is *the* screen to rewrite) | Video UI components: `ingest-form`, `video-library-grid` / `video-card`, `hls-player`, `rendition-table`, `status-badge`, `rename-dialog`, `retranscode-dialog` |
| `/settings` page + settings-form (demo — keep; it's the **form-UX exemplar**, §4) | — | New TanStack Query hooks in `lib/queries.ts` + `API_CLIENT_ROUTES` entries in `lib/api-client.ts` for the video routes; HLS-proxy + thumbnail routes registered in `SERVER_ONLY_OPERATIONS` |
| `/upload` **route** + dropzone/progress components (repurposed to the video **Ingest** create flow — reuse machinery) | — | Feature docs: `video-ingest.md`, `video-library.md`, `transcode-pipeline.md`; adapt `dashboard.md`; keep `file-browser.md`, `metadata-extraction.md`, `settings.md` |
| Backend layering `types→config→repo→service→runtime` + all structural/contract tests + `/health` `/metrics` rate-limit machinery | — | Dashboard transcode metrics (videos, renditions, source vs rendition bytes, amplification factor, recent transcodes) via a videos stats endpoint |
| `service/metadata.py` (image/PDF detail — still used by the kept file-browser detail view + its tests) | — | `imageio-ffmpeg` dependency (bundled static ffmpeg w/ libx264) + hls.js frontend dep |

**Non-negotiable keep + add — satisfied:** bucket explorer (`/files`) stays in KEEP; the
sample-specific scoped asset explorer is the **Videos Library** (`/videos`, scoped to the `videos/`
prefix). Both present. No tension to record.

**Scoping decisions (deliberate, recorded so builder/reviewer don't treat them as gaps):**
- **HLS is the built, first-class path** (it's in the sample's name; hls.js player). **DASH is
  documented-only** (an easy extension note in `transcode-pipeline.md`) — building both doubles player
  + pipeline work for no extra B2 story. Not a defect.
- **Transcode runs as a background job**, not synchronously: `POST /videos` uploads the source, writes
  an asset manifest with `status: "transcoding"`, and kicks a FastAPI `BackgroundTasks` worker that
  transcodes + uploads renditions, then flips the manifest to `"ready"` (or `"failed"` + error). The
  frontend polls `GET /videos/{id}` (TanStack Query) until terminal. Single-worker constraint (same
  stance as the existing rate-limit / download-counter notes) — document it; don't build a queue/DB.
- **Playback is API-proxied**, not presigned-per-segment: `GET /videos/{id}/hls/{path:path}` streams
  the master/variant playlists + `.ts` segments straight from B2 with a **1:1 request-path→B2-key
  map**, so HLS relative segment paths resolve with **no playlist rewriting**. Presigned query-string
  URLs break HLS relative resolution; a public-bucket+CDN is the production path (documented).
  `B2_PUBLIC_URL_BASE` therefore stays **optional**.

---

## 3. B2 surface (S3-compatible only — no b2-native)

All operations go through the single `repo/b2_client.get_s3_client()` factory (keeps the custom
user-agent — Standard #2). No bare boto3 clients elsewhere (structural invariant: boto3 only in `repo/`).

| S3 op | Used for |
|---|---|
| `put_object` | source video; every rendition segment (`.ts`), variant playlist (`.m3u8`), master playlist, thumbnail sprite (`.jpg`) + sprite `.vtt`, and the per-video `asset.json` manifest |
| `list_objects_v2` | bucket explorer (`/files`) + scoped Videos Library (list `asset.json` under `videos/`) |
| `head_object` | object existence / size checks |
| `get_object` | download source for re-transcode; read `asset.json`; **stream playlists + segments for the HLS proxy** |
| `delete_object` / `delete_objects` | delete a video's **entire `videos/{id}/` prefix** on delete (batch) — **scoped to the app's own prefix, never bucket-wide** (CLAUDE.local.md safety) |
| `generate_presigned_url` | optional source/thumbnail direct download; optional public playback when `B2_PUBLIC_URL_BASE` set |

No b2-native API anywhere. ✅ Standard #1 (S3 default).

**Per-video B2 layout** (relative structure mirrors the HLS playlist references so the proxy needs no
rewriting):
```
videos/{id}/source.<ext>
videos/{id}/asset.json               # manifest: title, status, source_size, renditions[], amplification…
videos/{id}/hls/master.m3u8
videos/{id}/hls/{360p,720p,1080p}/index.m3u8
videos/{id}/hls/{360p,720p,1080p}/seg_00001.ts …
videos/{id}/thumbs/sprite.jpg
videos/{id}/thumbs/sprite.vtt
```

---

## 4. Key features (seed README + `docs/features/<feature>.md` stubs)

Per-feature `deployment` recorded as an explicit field (builder/reviewer gate on it):

1. **Source ingest to B2** — `deployment: n/a` (plain B2 write). Drop a source video (dropzone,
   chunked stream to a temp file → `put_object` to `videos/{id}/source.<ext>`), pick a quality ladder
   + title, queue transcoding.
2. **FFmpeg HLS transcode ladder** — `deployment: local`, **no external provider, no key**. Local
   FFmpeg fans the source into a 360p/720p/1080p HLS ladder + master playlist. **CPU `libx264` +
   AAC audio is the default** (universally available in the bundled binary); optionally autodetect a
   hardware encoder (VideoToolbox on macOS / NVENC on CUDA) and fall back CPU — **never hard-require a
   GPU** (this is the FFmpeg analogue of the CUDA→MPS→CPU rule in `api-provider-selection.md`).
   Estimated cost per full demo run: **$0** (local compute only). Env: none (B2 only).
3. **Thumbnail sprite generation** — `deployment: local`, no key. FFmpeg samples frames into a sprite
   sheet + WebVTT for scrub-preview. Cost: **$0**.
4. **Renditions written back to B2 (write amplification)** — `deployment: n/a` (B2). Every segment /
   playlist / master / sprite stored per-video; dashboard shows source→rendition amplification factor.
   **The B2 star.**
5. **Adaptive playback from B2** — `deployment: n/a` (B2). Next.js shell streams the master playlist
   via **hls.js** through the API HLS proxy (`GET /videos/{id}/hls/{path}`) reading manifests+segments
   straight from B2.
6. **Full video lifecycle (primary-entity UI completeness)** — Library (list), detail (play), Rename
   (edit), Re-transcode (run), Delete-with-prefix-cleanup.

**External API provider:** NONE. The description's Trending OSS is FFmpeg (local); no
Genblaze/`genblaze-*`/`genblaze-s3` mention, so **no Genblaze routing**. No provider key anywhere;
`.env` holds B2 credentials only.

### Primary-entity lifecycle — entity: **Video** (VOD asset)

The DEFAULT is that the UI exposes ALL lifecycle verbs, and Phase 2 builds them. All five are built —
`omitted_ui_verbs` is expected **empty**:

| Verb | UI surface | Endpoint | Notes |
|---|---|---|---|
| **create** | Ingest page (`/upload`) | `POST /videos` (multipart: source + ladder + title) | uploads source, writes `status:transcoding` manifest, kicks BackgroundTasks worker |
| **read** | Library (`/videos`) + detail (`/videos/[id]`) | `GET /videos`, `GET /videos/{id}`, HLS proxy | list from manifests; detail = hls.js player + renditions + amplification |
| **edit** | Rename dialog on detail | `PATCH /videos/{id}` (title) | updates `title` in `asset.json` — cheap, user-meaningful (fix a title typo) |
| **delete** | Delete action on library/detail | `DELETE /videos/{id}` | deletes the whole `videos/{id}/` prefix (scoped batch delete) |
| **run** | Re-transcode dialog on detail | `POST /videos/{id}/retranscode` (ladder) | re-runs the pipeline on the stored source (e.g. add 1080p later) |

### Form UX conventions (exemplar: `apps/web/src/components/settings/settings-form.tsx`)

- **(a) Finite-set fields use a selector, never free text** — applies to create + edit forms:
  - **Quality ladder** (finite: `360p` / `Up to 720p` / `Up to 1080p`) → **`Select`**. Present on the
    **Ingest (create)** form AND the **Re-transcode (run)** dialog.
  - **Title** is open-ended → free-text `Input` (correct).
  - HLS is the only container built → no container selector needed (documented, not a UI choice).
- **(b) Safe default per field surfaced as placeholder / `FormDescription` on the CREATE form only**
  (guidance, never an autofill button): ladder defaults to **"Up to 720p"** with a `FormDescription`
  like "720p is a fast, representative demo run"; title `Input` placeholder e.g. `"Big Buck Bunny — clip"`.
  The **Rename (edit)** form opens **pre-filled** with the current title (no default-hint needed).

---

## 5. Doc transforms

- **Rewrite:** `README.md` (VOD purpose, ffmpeg-via-`imageio-ffmpeg` prerequisite note, ingest→
  transcode→B2→playback flow, write-amplification "why B2" section, Standard `B2_*` env vars,
  `pnpm` commands unchanged). `docs/features/file-upload.md` → **`video-ingest.md`**.
  `docs/features/dashboard.md` → transcode metrics. `ARCHITECTURE.md` (add `videos` router,
  `ffmpeg_runner` repo adapter, background-job flow, HLS-proxy data flow, per-video B2 layout).
- **Keep:** `docs/features/file-browser.md`, `metadata-extraction.md`, `settings.md`; `docs/SECURITY.md`
  (retarget the "vibe-coding-starter-kit" name refs), `RELIABILITY.md`, `dev-workflows.md`,
  `app-workflows.md` (update journeys to ingest→watch).
- **Add stubs (from `docs/features/_template.md`):** `video-ingest.md`, `video-library.md`,
  `transcode-pipeline.md` (FFmpeg ladder + HLS output + sprite + **B2 write-amplification economics**,
  incl. the DASH-extension note).
- **AGENTS.md:** update Repo Map + Doc Map + Doc-Update-Mapping for the new feature docs; keep it
  agent-sized (≥1KB, ≤20KB, ≤250 lines) and keep every setup/verify command claim consistent so
  `pnpm check:agent-docs` stays green. Update the three thin shims (`CLAUDE.md`, `GEMINI.md`,
  `.github/copilot-instructions.md`) only if pointers change (they stay thin).

---

## 6. Rename table (`vibe-coding-starter-kit` → `ffmpeg-hls-vod-transcoder`)

| Kind | From | To | Where |
|---|---|---|---|
| kebab / repo name | `vibe-coding-starter-kit` | `ffmpeg-hls-vod-transcoder` | `package.json` name, README, docs, `infra/railway/web.railway.json`, `next.config.ts`, git strip |
| npm workspace pkg | `@vibe-coding-starter-kit/web` `@vibe-coding-starter-kit/shared` | `@ffmpeg-hls-vod-transcoder/web` `@ffmpeg-hls-vod-transcoder/shared` | `package.json` (root scripts `--filter`), `apps/web/package.json`, `packages/shared/package.json`, any `pnpm --filter` in docs/scripts |
| Title Case / brand | `OSS Starter Kit` / `Vibe Coding Starter Kit` | `FFmpeg HLS VOD Transcoder` | `apps/web/src/lib/app-config.ts` `APP_NAME`/`APP_DESCRIPTION` (single source — drives sidebar, header breadcrumb, titles) |
| FastAPI title | `OSS Starter Kit API` | `FFmpeg HLS VOD Transcoder API` | `services/api/main.py` |
| nav / breadcrumb labels | `Upload`, (new) | `Ingest`; add `/videos`→`Videos` | `app-sidebar.tsx` navItems, `header.tsx` `pageTitles` map (add `/videos`, relabel `/upload`) |
| UTM content tag | `utm_content=b2ai-oss-start` | `utm_content=ffmpeg-hls-vod-transcoder` | README links, `app-sidebar.tsx` footer link, `settings.md`/docs |
| user-agent | `user_agent_extra="b2ai-oss-start"` | keep `b2ai-oss-start` (program tag; no sub-issue `user_agent_extra` provided) — **must stay set on the single S3 factory** | `repo/b2_client.py` |
| misc name refs | `vibe-coding-starter-kit` strings | `ffmpeg-hls-vod-transcoder` | `file-preview.tsx`, `file-tree-row.tsx`, `file-browser.tsx`, `file-metadata-panel.tsx`, `upload-progress.tsx`, `api-client.ts`, `queries.ts`, `upload-status.ts`, `file-tree.ts`, `upload-queue-context.tsx`, tests, `docs/*`, `tech-debt-tracker.md` |

**Header branding note:** this starter version's `header.tsx`
already derives the brand from `APP_NAME` + a `pageTitles` override map (no hardcoded `oss-starter-kit`
here), so the fix is just: set `APP_NAME` in `app-config.ts` and add the new routes to `pageTitles`
(`/videos`→"Videos", `/upload`→"Ingest"). Verify no stray literal `"Page"`/old-name fallback survives.

---

## 7. B2 env-var standardization — Standard #3 (MANDATORY; graded standard)

The starter kit ships **non-standard** B2 env names. Rename to the parent CLAUDE.md Standard #3 set.
This touches `settings.py`, `main.py` (`REQUIRED_B2_SETTINGS` + `PLACEHOLDER_VALUES`), `b2_client.py`,
`.env.example`, README, docs, and any tests referencing these.

| Starter (settings attr / env) | → Standard #3 (env) | Settings handling |
|---|---|---|
| `b2_key_id` / `B2_KEY_ID` | **`B2_APPLICATION_KEY_ID`** | `b2_application_key_id: str = ""` |
| `b2_application_key` / `B2_APPLICATION_KEY` | `B2_APPLICATION_KEY` (unchanged ✅) | `b2_application_key: str = ""` |
| `b2_bucket_name` / `B2_BUCKET_NAME` | `B2_BUCKET_NAME` (unchanged ✅) | `b2_bucket_name: str = ""` |
| `b2_endpoint` / `B2_ENDPOINT` | **`B2_REGION`** (+ keep optional `B2_ENDPOINT` override) | `b2_region: str = "us-east-005"` (default → no seed-env false-BLOCK); derive `endpoint` property = `B2_ENDPOINT` override else `https://s3.{b2_region}.backblazeb2.com` |
| `b2_public_url` / (none) | **`B2_PUBLIC_URL_BASE`** (optional) | `b2_public_url_base: str = ""` — **OPTIONAL**, don't require at startup / don't seed-env-BLOCK |

`REQUIRED_B2_SETTINGS` becomes `B2_APPLICATION_KEY_ID`, `B2_APPLICATION_KEY`, `B2_BUCKET_NAME`
(region has a default; public-url-base optional). Update `PLACEHOLDER_VALUES` + `.env.example`
accordingly (placeholders only — the `deny-b2-secrets` hook blocks real `K00…`/`005…` values).

✅ Standard #1 S3-default, ✅ Standard #2 custom UA on the single factory, ✅ Standard #3 `B2_*` names.

---

## 8. Backend additions (respect `types→config→repo→service→runtime`; files <300 lines; JSON logging; no boto3/subprocess outside `repo/`)

- **`types/video.py`** — `VideoAsset`, `Rendition`, `LadderPreset` (enum), `TranscodeStatus` (enum:
  transcoding/ready/failed), `IngestResponse`, `TranscodeStatsResponse`, `RenameRequest`,
  `RetranscodeRequest`. Split if >300 lines.
- **`config/settings.py`** — env rename (§7) + `video_prefix="videos/"`, `hls_segment_seconds=4`,
  `default_ladder`, `max_source_size` (~200 MB, configurable), optional `ffmpeg_binary`/`ffprobe_binary`
  overrides, `hwaccel` autodetect toggle.
- **`repo/ffmpeg_runner.py`** — the FFmpeg subprocess adapter (external tool ⇒ lives in `repo/`, the
  same discipline as boto3-in-repo). Resolve the binary via `imageio_ffmpeg.get_ffmpeg_exe()` (bundled,
  libx264) with `FFMPEG_BINARY` override; `probe()` (duration + w×h via ffprobe-if-present else parse
  `ffmpeg -i` stderr — no hard ffprobe dep), `transcode_hls()` (emit master + per-rendition
  playlists/segments, CPU-default/hw-accel-autodetect), `generate_sprite()`. Never buffer video in
  RAM — operate on temp files.
- **`repo/b2_client.py`** — add `put_file`(stream local file→B2), `get_object_stream`(HLS proxy),
  `read_json`/`write_json`(manifest), `list_prefix`, `delete_prefix`(scoped batch delete). Reuse the
  existing UA-bearing factory.
- **`service/video.py`** — `create_video`, `run_transcode_job`(worker: temp-download source → probe →
  transcode → sprite → upload renditions → update manifest), `list_videos`, `get_video`,
  `rename_video`, `delete_video`(prefix-scoped), `retranscode`, `get_transcode_stats`(amplification).
  Ladder-building + amplification math here. Prefix-scope every delete to `videos/{id}/`.
- **`runtime/videos.py`** — `POST /videos` (BackgroundTasks), `GET /videos`, `GET /videos/{id}`,
  `PATCH /videos/{id}`, `DELETE /videos/{id}`, `POST /videos/{id}/retranscode`, `GET /videos/stats`,
  and the HLS proxy `GET /videos/{id}/hls/{path:path}` (+ optional `GET /videos/{id}/thumbnail`).
  No business logic — delegate to service. `main.py`: drop `upload` router, add `videos` router.
- **Contract/tests:** every route change re-runs `pnpm contract:export` (regenerates
  `docs/api/openapi.json`, else `pnpm test:api` fails) and updates `API_CLIENT_ROUTES`
  (`lib/api-client.ts`) + `lib/queries.ts`; **HLS-proxy + thumbnail routes** go in
  `SERVER_ONLY_OPERATIONS` (`api-contract.test.ts`) since `<video>`/hls.js/`<img>` hit them directly.
  New backend unit tests (mock the ffmpeg subprocess — verify:api stays credential-free & fast):
  ladder build, manifest read/write, **prefix-scoped delete**, validation (reject non-video / oversize),
  amplification math. Keep structural tests green (subprocess only in `repo/`).

**Definition of build-green = `pnpm verify` passes** (`check:agent-docs` + `verify:api` +
`verify:web`). Real end-to-end transcoding of a live clip is exercised later by the pipeline's `verify`
step, **not** here — unit tests mock FFmpeg.

---

## 9. Frontend additions

- **Deps:** add `hls.js` (player) + `imageio-ffmpeg` (backend). Wire the player as a client component
  with a graceful fallback to native HLS (`<video>` `canPlayType`) on Safari.
- **Pages:** adapt `/` dashboard (transcode/amplification cards + recent transcodes + amplification
  chart, all via TanStack Query hooks — no bare `useEffect+fetch`); repurpose `/upload`→Ingest form;
  add `/videos` (library grid of `video-card`s w/ thumbnail + status badge) and `/videos/[id]`
  (hls-player + rendition-table + amplification stat + Rename/Re-transcode/Delete).
- **Components:** `ingest-form` (dropzone + ladder `Select` + title `Input`, default-hints),
  `video-library-grid`/`video-card`, `hls-player`, `rendition-table`, `status-badge`,
  `rename-dialog` (pre-filled), `retranscode-dialog` (ladder `Select`). Build only with `components/ui`
  primitives; restyle via tokens only.
- **Data layer:** new hooks in `lib/queries.ts` (list/get/create/rename/delete/retranscode/stats) with
  poll-until-`ready` on the detail query; cache invalidation after each mutation.

---

## 10. Risks / notes for the builder

- **Scope is real but domain-justified.** Core must-land (B2 story): ingest → transcode → B2 renditions
  → manifest → library → detail-with-playback → amplification stat → prefix-scoped delete. Rename +
  re-transcode are smaller but required for verb-completeness. Keep each piece minimal.
- **Reproducibility:** ffmpeg comes from `imageio-ffmpeg` (bundled, no system install), so a fresh
  clone transcodes without `brew/apt`. Note that Homebrew ffmpeg is slim (no libass) — irrelevant here
  (no subtitles), but don't switch to a system binary that might lack libx264.
- **Verify-step heads-up (not a build task):** the later `verify` step needs a small, safe,
  license-clean source clip to exercise the real pipeline — flag in build-result "next steps".
- **Bucket may be shared** — the app writes only under `videos/{id}/` and deletes are
  prefix-scoped; never touch other prefixes.
