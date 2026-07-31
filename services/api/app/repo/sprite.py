"""Thumbnail-sprite generation — an FFmpeg subprocess adapter (repo/ layer).

Samples frames across the source into a single sprite sheet plus a WebVTT that
maps each time range to a tile region, so the player can show scrub-preview
thumbnails. CPU-only image scaling — never GPU-bound. Best-effort: the caller
treats a None return (or exception) as "no sprite" and keeps the transcode.
"""

from __future__ import annotations

import logging
import os

from app.repo.ffmpeg_runner import _run, ffmpeg_exe

logger = logging.getLogger(__name__)


def generate_sprite(
    source_path: str,
    out_dir: str,
    duration_seconds: float | None,
    columns: int = 5,
    tile_width: int = 160,
    tile_height: int = 90,
) -> tuple[str, str] | None:
    """Write `thumbs/sprite.jpg` + `thumbs/sprite.vtt` under `out_dir`.

    Returns (sprite_jpg_path, sprite_vtt_path) or None if generation failed.
    """
    thumbs_dir = os.path.join(out_dir, "thumbs")
    os.makedirs(thumbs_dir, exist_ok=True)
    sprite_jpg = os.path.join(thumbs_dir, "sprite.jpg")
    sprite_vtt = os.path.join(thumbs_dir, "sprite.vtt")

    total = max(duration_seconds or 0.0, 1.0)
    count = max(1, min(25, int(total // 4) or 1))
    interval = total / count
    rows = (count + columns - 1) // columns

    args = [
        ffmpeg_exe(), "-hide_banner", "-y", "-i", source_path,
        "-vf",
        f"fps=1/{interval:.4f},scale={tile_width}:{tile_height},tile={columns}x{rows}",
        "-frames:v", "1", sprite_jpg,
    ]
    result = _run(args)
    if result.returncode != 0 or not os.path.exists(sprite_jpg):
        logger.warning("sprite generation failed: %s", (result.stderr or "")[-200:])
        return None

    _write_sprite_vtt(
        sprite_vtt, "sprite.jpg", count, columns, interval, tile_width, tile_height
    )
    return sprite_jpg, sprite_vtt


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _write_sprite_vtt(
    path: str,
    sprite_name: str,
    count: int,
    columns: int,
    interval: float,
    tile_width: int,
    tile_height: int,
) -> None:
    lines = ["WEBVTT", ""]
    for i in range(count):
        start, end = i * interval, (i + 1) * interval
        col, row = i % columns, i // columns
        x, y = col * tile_width, row * tile_height
        lines.append(f"{_fmt_ts(start)} --> {_fmt_ts(end)}")
        lines.append(f"{sprite_name}#xywh={x},{y},{tile_width},{tile_height}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
