"""Source-video ingest validation.

The client-declared MIME type is untrusted, so ingest is gated on three checks:
container extension is one we can transcode, the leading bytes actually look
like that container (magic-byte sniff), and the size is under the cap. This is
the video analogue of the starter kit's image/PDF upload validation.
"""

from __future__ import annotations

import re

from app.config import settings
from app.types.formatting import humanize_bytes

# Container extension -> canonical content type. We trust the extension + magic
# bytes over the browser-sent MIME (which is often generic octet-stream).
EXT_TO_CTYPE: dict[str, str] = {
    "mp4": "video/mp4",
    "m4v": "video/x-m4v",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "mkv": "video/x-matroska",
}

# Bytes we need to sniff the container. ISO-BMFF (mp4/mov/m4v) carries a 'ftyp'
# box at offset 4; Matroska/WebM start with the EBML magic.
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"
SNIFF_BYTES = 32

_SAFE_FILENAME_RE = re.compile(r"[^\w\-.]")


class IngestError(Exception):
    """Raised when a source video fails validation."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def sanitize_filename(filename: str) -> str:
    name = filename.replace("\\", "/").split("/")[-1].replace("\x00", "")
    name = _SAFE_FILENAME_RE.sub("_", name).lstrip(".").strip()
    return name[:200] or "source"


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def matches_video_signature(head: bytes, ext: str) -> bool:
    """True if `head`'s leading bytes are consistent with the container `ext`."""
    if ext in ("mp4", "m4v", "mov"):
        return len(head) >= 8 and head[4:8] == b"ftyp"
    if ext in ("webm", "mkv"):
        return head[:4] == _EBML_MAGIC
    return False


def validate_source(
    filename: str, size_bytes: int, head: bytes
) -> tuple[str, str, str]:
    """Validate a source video. Returns (safe_filename, ext, content_type).

    Raises IngestError (413 oversize, 415 unsupported/spoofed, 400 empty).
    """
    if size_bytes <= 0:
        raise IngestError("Empty file")
    if size_bytes > settings.max_source_size:
        raise IngestError(
            "Source video too large. "
            f"Max size: {humanize_bytes(settings.max_source_size)}",
            status_code=413,
        )

    safe_name = sanitize_filename(filename)
    ext = extension_of(safe_name)
    if ext not in EXT_TO_CTYPE:
        raise IngestError(
            f"Unsupported container '.{ext or '?'}'. "
            f"Supported: {', '.join(sorted(EXT_TO_CTYPE))}",
            status_code=415,
        )
    if not matches_video_signature(head, ext):
        raise IngestError(
            "File contents do not look like a video for that extension",
            status_code=415,
        )
    return safe_name, ext, EXT_TO_CTYPE[ext]
