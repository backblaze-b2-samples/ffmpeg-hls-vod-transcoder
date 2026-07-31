"""Pydantic models for the VOD (video-on-demand) transcode pipeline.

A `VideoAsset` is the primary entity. Its serialized form is exactly what the
per-video `asset.json` manifest holds in B2, so the same model is the API
response, the library row, and the durable record — one source of truth.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.types.formatting import humanize_bytes


class LadderPreset(StrEnum):
    """Finite quality-ladder presets (a *ceiling*, not a single rendition).

    A preset expands into every rung at or below its height, so "720p" yields
    360p + 720p and "1080p" yields 360p + 720p + 1080p. The Ingest and
    Re-transcode forms present these as a `Select` (finite options).
    """

    P360 = "360p"
    P720 = "720p"
    P1080 = "1080p"


class TranscodeStatus(StrEnum):
    TRANSCODING = "transcoding"
    READY = "ready"
    FAILED = "failed"


# (name, height, video_kbps, audio_kbps). Bitrates are conservative H.264/AAC
# targets that play everywhere. The runner never upscales: a rung taller than
# the source is dropped so a 480p source doesn't get a blurry fake-1080p rung.
LADDER_RUNGS: list[tuple[str, int, int, int]] = [
    ("360p", 360, 800, 96),
    ("720p", 720, 2800, 128),
    ("1080p", 1080, 5000, 192),
]

_LADDER_CEILINGS: dict[LadderPreset, int] = {
    LadderPreset.P360: 360,
    LadderPreset.P720: 720,
    LadderPreset.P1080: 1080,
}


def rungs_for(preset: LadderPreset) -> list[tuple[str, int, int, int]]:
    """Ladder rungs (at or below the preset ceiling), tallest-first is NOT
    guaranteed — callers sort if they need order."""
    ceiling = _LADDER_CEILINGS[preset]
    return [rung for rung in LADDER_RUNGS if rung[1] <= ceiling]


class Rendition(BaseModel):
    name: str  # "360p"
    height: int
    width: int
    video_kbps: int
    playlist_key: str  # videos/{id}/hls/360p/index.m3u8
    segment_count: int
    size_bytes: int
    size_human: str


class VideoAsset(BaseModel):
    id: str
    title: str
    status: TranscodeStatus
    ladder: LadderPreset
    source_key: str
    source_filename: str
    source_size_bytes: int
    source_size_human: str
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    renditions: list[Rendition] = Field(default_factory=list)
    rendition_bytes: int = 0
    rendition_bytes_human: str = "0 B"
    # Storage write-amplification: rendition_bytes / source_size_bytes. The
    # headline "why B2" metric — one source upload fans out to N-times storage.
    amplification_factor: float | None = None
    master_playlist_key: str | None = None
    thumbnail_key: str | None = None
    created_at: datetime
    updated_at: datetime
    error: str | None = None


class IngestResponse(BaseModel):
    """Immediate response to `POST /videos` — the transcode runs in the
    background, so this only confirms the source landed and a job was queued."""

    id: str
    title: str
    status: TranscodeStatus


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class RetranscodeRequest(BaseModel):
    ladder: LadderPreset


class TranscodeStatsResponse(BaseModel):
    total_videos: int
    ready_videos: int
    transcoding_videos: int
    failed_videos: int
    total_renditions: int
    source_bytes: int
    source_bytes_human: str
    rendition_bytes: int
    rendition_bytes_human: str
    # Fleet-wide amplification: total rendition bytes / total source bytes.
    amplification_factor: float | None
    recent: list[VideoAsset] = Field(default_factory=list)


def compute_amplification(source_bytes: int, rendition_bytes: int) -> float | None:
    """Rendition bytes as a multiple of source bytes, rounded to 2 dp.

    None when there is no source to compare against, so the UI shows "—"
    rather than a divide-by-zero or a misleading 0x.
    """
    if source_bytes <= 0:
        return None
    return round(rendition_bytes / source_bytes, 2)


def bytes_human(size: int) -> str:
    return humanize_bytes(size)
