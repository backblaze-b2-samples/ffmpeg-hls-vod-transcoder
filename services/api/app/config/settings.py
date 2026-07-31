from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Backblaze B2 (S3-compatible) — Standard B2_* env names ---
    # The endpoint is derived from the region so operational code never hardcodes
    # a region string; a user only sets B2_REGION. The default below is a startup
    # fallback for tests and cold clones — real deployments set B2_REGION in .env.
    b2_application_key_id: str = ""
    b2_application_key: str = ""
    b2_bucket_name: str = ""
    b2_region: str = "us-east-005"
    # Optional. Only used to build public object URLs for a public bucket; the
    # app runs fine without it (playback is API-proxied — see runtime/videos.py).
    b2_public_url_base: str = ""

    api_port: int = 8000
    # Interactive API docs (/docs, /redoc, /openapi.json). On by default for
    # local dev and starter-kit exploration; set false to hide the full API
    # surface in production.
    enable_docs: bool = True
    # Explicit allowlist by default — covers Next on :3000 and the
    # fallback :3001 it picks if 3000 is busy. Production deploys should
    # override with the exact frontend origin.
    api_cors_origins: str = "http://localhost:3000,http://localhost:3001"
    # Optional dev-only escape hatch: a regex that matches additional
    # allowed origins. Empty by default — set this to e.g.
    # `^http://localhost:\d+$` to accept any localhost port without
    # listing each one. NEVER ship this to production.
    api_cors_origin_regex: str = ""

    # --- VOD / transcode pipeline ---
    # All video assets live under this prefix so the scoped Videos Library and
    # prefix-scoped delete never touch unrelated bucket data.
    video_prefix: str = "videos/"
    # HLS target segment duration (seconds). 4s is a common ABR default.
    hls_segment_seconds: int = 4
    # Default quality ladder preset applied when none is chosen (fast demo run).
    default_ladder: str = "720p"
    # Max source upload size. Video is streamed to a temp file, never buffered
    # whole in RAM, but this caps a single ingest. ~200 MB by default.
    max_source_size: int = 200 * 1024 * 1024
    # Ceiling for the kept Files browser's on-demand detail view, which buffers
    # the whole object in memory to re-extract metadata. Independent of the video
    # ingest cap above. ~200 MB by default.
    max_detail_size: int = 200 * 1024 * 1024
    # Optional overrides for the ffmpeg/ffprobe binaries. Empty means resolve the
    # bundled static ffmpeg from imageio-ffmpeg (libx264 included, no system
    # install). Set to an absolute path only to use a different binary.
    ffmpeg_binary: str = ""
    ffprobe_binary: str = ""
    # Auto-detect a hardware encoder (VideoToolbox on macOS / NVENC on CUDA) and
    # fall back to CPU libx264. Never hard-requires a GPU — CPU is always viable.
    hwaccel_autodetect: bool = True

    # Optional confinement for key-addressed reads/deletes. Empty by default so
    # the by-key routes accept any key shape (they deliberately support nested
    # folders and reserved-word segments). Point a fork at a bucket shared with
    # other data? Set to e.g. "videos/" to restrict all key ops to app data.
    allowed_key_prefix: str = ""

    # Full-bucket listing cache (repo/list_cache.py). Both /files and
    # /files/stats need every object, and paginating a 16k-object bucket takes
    # ~8-20s, so one scan is shared. Entries older than the TTL are still
    # served *immediately* while a background thread refreshes them
    # (stale-while-revalidate), so only the very first scan can make a user
    # wait. Uploads and deletes invalidate the cache outright, so the app's own
    # writes are never served stale — only bucket changes made elsewhere can lag
    # by up to this TTL.
    list_cache_ttl_seconds: float = 300.0
    # Scan the bucket once at startup so the first page view doesn't pay for the
    # cold scan. Set false for offline dev or when startup must not touch B2.
    warm_list_cache_on_startup: bool = True

    # Rate limiting (per client IP, per 60s window). In-process per replica —
    # documented in docs/RELIABILITY.md; horizontal scaling needs a shared
    # store (e.g. Redis). Writes/downloads get the tighter cap.
    rate_limit_per_minute: int = 120
    # Covers ingest, deletes, downloads and previews — kept generous enough
    # that a normal browsing/ingest session doesn't trip it.
    rate_limit_write_per_minute: int = 60

    # Small durable counters (downloads, etc). Relative paths resolve against
    # the repo root (see repo/counter.py). Point at a persistent volume in
    # production if you care about surviving restarts.
    #
    # It must stay OUTSIDE services/api/: that is the directory `uvicorn
    # --reload` watches in dev, so a counter file there means every download
    # writes into the reloader's watch tree. Today uvicorn only restarts for
    # `*.py`, so the writes surface as misleading "N changes detected" log noise
    # on every download — but a single added `--reload-include` would turn a
    # normal user action into an API restart that drops in-flight requests.
    download_count_file: str = ".data/download_count.json"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def endpoint(self) -> str:
        """S3 endpoint derived from the configured region."""
        return f"https://s3.{self.b2_region}.backblazeb2.com"

    @property
    def cors_origins(self) -> list[str]:
        # Drop empties so a trailing comma or API_CORS_ORIGINS="" doesn't yield
        # a stray "" origin.
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


settings = Settings()
