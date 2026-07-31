"""FFmpeg subprocess adapter — the transcode engine.

FFmpeg is an external tool, so (like boto3) it is confined to the `repo/` layer:
this is the only module that shells out to `ffmpeg`/`ffprobe`. The binary comes
from the bundled static `imageio-ffmpeg` build (libx264 included), so a fresh
clone transcodes with no system `brew/apt install ffmpeg`. A `FFMPEG_BINARY`
override points at any other build.

Everything operates on file paths under a caller-provided temp directory — a
whole video is never buffered in memory.

Hardware-encoder policy (mirrors the CUDA->MPS->CPU rule in
docs/features/api-provider-selection.md): CPU `libx264` is the always-available
default. When `hwaccel_autodetect` is on we probe the binary's encoder list and
prefer VideoToolbox (macOS) / NVENC (CUDA) *only if present*, always falling
back to libx264. A GPU is never required.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

from app.config import settings

# How long a single ffmpeg/ffprobe invocation may run before we give up. A
# demo clip transcodes in seconds; this only bounds a pathological input.
_PROC_TIMEOUT_SECONDS = 60 * 30

_DURATION_RE = re.compile(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)")
_RESOLUTION_RE = re.compile(r"Video:.*?(\d{2,5})x(\d{2,5})")


@dataclass
class ProbeResult:
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class RungOutput:
    """One transcoded rung of the HLS ladder, described in local-filesystem
    terms. The service turns these into B2 keys + `Rendition` models."""

    name: str
    height: int
    width: int
    video_kbps: int
    audio_kbps: int
    playlist_path: str  # absolute local path to this rung's index.m3u8
    segment_paths: list[str] = field(default_factory=list)


def ffmpeg_exe() -> str:
    """Resolve the ffmpeg binary: explicit override, else the bundled static
    build from imageio-ffmpeg (libx264 included)."""
    if settings.ffmpeg_binary:
        return settings.ffmpeg_binary
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def ffprobe_exe() -> str | None:
    """Resolve an ffprobe binary if one is available; otherwise None (the
    caller then parses `ffmpeg -i` stderr — no hard ffprobe dependency)."""
    if settings.ffprobe_binary:
        return settings.ffprobe_binary
    sibling = os.path.join(os.path.dirname(ffmpeg_exe()), "ffprobe")
    if os.path.exists(sibling):
        return sibling
    return shutil.which("ffprobe")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing text output. Isolated so tests patch exactly
    one seam and never spawn a real ffmpeg."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=_PROC_TIMEOUT_SECONDS,
        check=False,
    )


@lru_cache(maxsize=1)
def _available_encoders() -> frozenset[str]:
    """Encoder names the resolved ffmpeg build actually ships. Cached — the
    binary does not change within a process."""
    try:
        result = _run([ffmpeg_exe(), "-hide_banner", "-encoders"])
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    names: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        # Encoder rows look like: " V..... libx264   H.264 ...". The name is the
        # second whitespace token after the capability flags column.
        if len(parts) >= 2 and parts[0].startswith("V"):
            names.add(parts[1])
    return frozenset(names)


def select_video_encoder() -> str:
    """Pick the H.264 encoder to use. CPU libx264 is the default and always
    viable; a hardware encoder is used only when autodetect is on AND the
    binary actually offers it. Never requires a GPU."""
    if settings.hwaccel_autodetect:
        available = _available_encoders()
        for hw in ("h264_videotoolbox", "h264_nvenc"):
            if hw in available:
                return hw
    return "libx264"


def _video_encoder_args(encoder: str, video_kbps: int) -> list[str]:
    maxrate = int(video_kbps * 1.07)
    bufsize = video_kbps * 2
    common = [
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{maxrate}k",
        "-bufsize", f"{bufsize}k",
    ]
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", *common]
    if encoder == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", *common]
    return ["-c:v", "libx264", "-preset", "veryfast", "-profile:v", "main", *common]


def probe(source_path: str) -> ProbeResult:
    """Duration + source width/height. Uses ffprobe when available, else parses
    `ffmpeg -i` stderr so ffprobe is never a hard dependency."""
    ffprobe = ffprobe_exe()
    if ffprobe:
        parsed = _probe_with_ffprobe(ffprobe, source_path)
        if parsed is not None:
            return parsed
    return _probe_with_ffmpeg(source_path)


def _probe_with_ffprobe(ffprobe: str, source_path: str) -> ProbeResult | None:
    args = [
        ffprobe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-show_entries", "format=duration",
        "-of", "json", source_path,
    ]
    try:
        result = _run(args)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    stream = (data.get("streams") or [{}])[0]
    duration = data.get("format", {}).get("duration")
    return ProbeResult(
        duration_seconds=float(duration) if duration else None,
        width=stream.get("width"),
        height=stream.get("height"),
    )


def _probe_with_ffmpeg(source_path: str) -> ProbeResult:
    # `ffmpeg -i <file>` with no output exits non-zero but prints the stream
    # metadata we need to stderr.
    try:
        result = _run([ffmpeg_exe(), "-hide_banner", "-i", source_path])
    except (OSError, subprocess.SubprocessError):
        return ProbeResult()
    stderr = result.stderr or ""
    out = ProbeResult()
    dm = _DURATION_RE.search(stderr)
    if dm:
        h, m, s = int(dm.group(1)), int(dm.group(2)), float(dm.group(3))
        out.duration_seconds = h * 3600 + m * 60 + s
    rm = _RESOLUTION_RE.search(stderr)
    if rm:
        out.width, out.height = int(rm.group(1)), int(rm.group(2))
    return out


def _even(n: int) -> int:
    return n if n % 2 == 0 else n - 1


def transcode_hls(
    source_path: str,
    out_dir: str,
    rungs: list[tuple[str, int, int, int]],
    source_width: int | None,
    source_height: int | None,
) -> list[RungOutput]:
    """Fan `source_path` into an HLS ladder under `out_dir/hls/`.

    Each rung yields `hls/<name>/index.m3u8` + `hls/<name>/seg_*.ts`; a
    `hls/master.m3u8` ties them together with relative variant paths so the B2
    layout mirrors the playlist references 1:1 (the proxy never rewrites URLs).

    `rungs` are (name, height, video_kbps, audio_kbps). A rung taller than the
    source is dropped — the runner never upscales. Returns one `RungOutput` per
    rung actually produced. Raises RuntimeError if ffmpeg fails on a rung.
    """
    encoder = select_video_encoder()
    hls_dir = os.path.join(out_dir, "hls")
    os.makedirs(hls_dir, exist_ok=True)
    produced: list[RungOutput] = []

    for name, height, video_kbps, audio_kbps in rungs:
        if source_height and height > source_height:
            continue  # never upscale
        width = (
            _even(round(source_width * height / source_height))
            if source_width and source_height
            else _even(round(height * 16 / 9))
        )
        rung_dir = os.path.join(hls_dir, name)
        os.makedirs(rung_dir, exist_ok=True)
        playlist_path = os.path.join(rung_dir, "index.m3u8")
        args = [
            ffmpeg_exe(), "-hide_banner", "-y", "-i", source_path,
            "-vf", f"scale=-2:{height}",
            *_video_encoder_args(encoder, video_kbps),
            "-c:a", "aac", "-b:a", f"{audio_kbps}k", "-ac", "2",
            "-f", "hls",
            "-hls_time", str(settings.hls_segment_seconds),
            "-hls_playlist_type", "vod",
            "-hls_segment_filename", os.path.join(rung_dir, "seg_%05d.ts"),
            playlist_path,
        ]
        result = _run(args)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed on rung {name}: {(result.stderr or '')[-500:]}"
            )
        segments = sorted(
            os.path.join(rung_dir, f)
            for f in os.listdir(rung_dir)
            if f.endswith(".ts")
        )
        produced.append(
            RungOutput(
                name=name,
                height=height,
                width=width,
                video_kbps=video_kbps,
                audio_kbps=audio_kbps,
                playlist_path=playlist_path,
                segment_paths=segments,
            )
        )

    if not produced:
        raise RuntimeError("no rungs produced — source shorter than every rung")
    _write_master_playlist(hls_dir, produced)
    return produced


def _write_master_playlist(hls_dir: str, rungs: list[RungOutput]) -> None:
    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for r in rungs:
        bandwidth = (r.video_kbps + r.audio_kbps) * 1000
        lines.append(
            f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},"
            f"RESOLUTION={r.width}x{r.height}"
        )
        lines.append(f"{r.name}/index.m3u8")  # relative → 1:1 B2 key mapping
    with open(os.path.join(hls_dir, "master.m3u8"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
