"""Source-video ingest validation tests (no B2, no ffmpeg)."""

import pytest

from app.service import ingest
from app.service.ingest import (
    IngestError,
    matches_video_signature,
    validate_source,
)

# Minimal container signatures.
_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
_MOV = b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 16
_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 28
_MKV = b"\x1a\x45\xdf\xa3" + b"\x01" * 28


@pytest.mark.parametrize(
    ("head", "ext", "expected"),
    [
        (_MP4, "mp4", True),
        (_MOV, "mov", True),
        (_MP4, "m4v", True),
        (_WEBM, "webm", True),
        (_MKV, "mkv", True),
        (b"<html>not a video", "mp4", False),  # spoofed
        (b"PK\x03\x04zip", "mp4", False),
        (b"\x00\x00", "webm", False),  # too short / wrong magic
        (_MP4, "gif", False),  # unknown ext
    ],
)
def test_matches_video_signature(head, ext, expected):
    assert matches_video_signature(head, ext) is expected


def test_validate_source_accepts_mp4():
    safe_name, ext, ctype = validate_source("Big Buck Bunny.mp4", len(_MP4), _MP4)
    assert ext == "mp4"
    assert ctype == "video/mp4"
    assert safe_name == "Big_Buck_Bunny.mp4"


def test_validate_source_normalizes_content_type_from_extension():
    # Trust the extension + magic, not a browser-sent generic type.
    _, _, ctype = validate_source("clip.webm", len(_WEBM), _WEBM)
    assert ctype == "video/webm"


def test_validate_source_rejects_non_video_extension():
    with pytest.raises(IngestError) as exc:
        validate_source("photo.png", 1000, b"\x89PNG\r\n\x1a\n")
    assert exc.value.status_code == 415


def test_validate_source_rejects_spoofed_bytes():
    with pytest.raises(IngestError) as exc:
        validate_source("fake.mp4", 1000, b"<html>gotcha")
    assert exc.value.status_code == 415


def test_validate_source_rejects_oversize(monkeypatch):
    monkeypatch.setattr(ingest.settings, "max_source_size", 10)
    with pytest.raises(IngestError) as exc:
        validate_source("clip.mp4", 999, _MP4)
    assert exc.value.status_code == 413


def test_validate_source_rejects_empty():
    with pytest.raises(IngestError):
        validate_source("clip.mp4", 0, b"")
