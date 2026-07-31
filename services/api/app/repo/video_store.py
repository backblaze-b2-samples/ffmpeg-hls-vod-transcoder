"""B2 (S3-compatible) storage helpers for the VOD pipeline.

Kept separate from `b2_client.py` (which is at the 300-line structural ceiling)
but reuses that module's single user-agent-bearing S3 client — every S3 call in
the app flows through one factory, so the custom user agent (Standard #2) is set
exactly once. boto3/botocore stays confined to this repo/ layer.

All keys are opaque strings the caller builds under `videos/{id}/`; this module
never guesses layout. Streaming reads/writes operate on file paths or streaming
bodies and never buffer a whole video in memory.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings
from app.repo.b2_client import get_s3_client
from app.repo.list_cache import invalidate as _invalidate_list_cache

# Content types for the artifacts the pipeline writes, so browsers and hls.js
# get the right MIME on the proxied read.
_CONTENT_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".vtt": "text/vtt",
    ".json": "application/json",
}


def content_type_for(key: str) -> str:
    for ext, ctype in _CONTENT_TYPES.items():
        if key.endswith(ext):
            return ctype
    return "application/octet-stream"


def put_file(local_path: str, key: str, content_type: str | None = None) -> int:
    """Stream a local file up to B2. Returns the byte size. Raises RuntimeError
    on S3 failure."""
    client = get_s3_client()
    ctype = content_type or content_type_for(key)
    try:
        with open(local_path, "rb") as fh:
            client.put_object(
                Bucket=settings.b2_bucket_name,
                Key=key,
                Body=fh,
                ContentType=ctype,
            )
    except (ClientError, BotoCoreError, OSError) as e:
        raise RuntimeError(f"B2 put_file failed for '{key}': {e}") from e
    _invalidate_list_cache()
    import os

    return os.path.getsize(local_path)


def put_bytes(data: bytes, key: str, content_type: str | None = None) -> None:
    """Upload a small in-memory object (playlist, manifest). Raises RuntimeError
    on S3 failure."""
    client = get_s3_client()
    ctype = content_type or content_type_for(key)
    try:
        client.put_object(
            Bucket=settings.b2_bucket_name,
            Key=key,
            Body=data,
            ContentType=ctype,
        )
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"B2 put_bytes failed for '{key}': {e}") from e
    _invalidate_list_cache()


def download_to(key: str, local_path: str) -> None:
    """Stream an object from B2 to a local file. Raises RuntimeError on failure."""
    client = get_s3_client()
    try:
        client.download_file(settings.b2_bucket_name, key, local_path)
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"B2 download failed for '{key}': {e}") from e


def object_exists(key: str) -> bool:
    client = get_s3_client()
    try:
        client.head_object(Bucket=settings.b2_bucket_name, Key=key)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise RuntimeError(f"B2 head_object failed for '{key}': {e}") from e


def get_object_stream(key: str) -> dict[str, Any]:
    """Return a streaming handle for the HLS proxy.

    Yields `{"body": StreamingBody, "content_length": int, "content_type": str}`.
    The caller iterates `body` and must close it. Raises RuntimeError on failure;
    a missing object surfaces as a FileNotFoundError so the route can 404.
    """
    client = get_s3_client()
    try:
        response = client.get_object(Bucket=settings.b2_bucket_name, Key=key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            raise FileNotFoundError(key) from e
        raise RuntimeError(f"B2 get_object failed for '{key}': {e}") from e
    except BotoCoreError as e:
        raise RuntimeError(f"B2 get_object failed for '{key}': {e}") from e
    return {
        "body": response["Body"],
        "content_length": response.get("ContentLength", 0),
        "content_type": response.get("ContentType", content_type_for(key)),
    }


def iter_object(key: str, chunk_size: int = 256 * 1024) -> Iterator[bytes]:
    """Convenience generator over an object's body for StreamingResponse."""
    handle = get_object_stream(key)
    body = handle["body"]
    try:
        for chunk in body.iter_chunks(chunk_size):
            yield chunk
    finally:
        body.close()


def read_json(key: str) -> dict[str, Any] | None:
    """Read and parse a JSON object (the asset manifest). None when missing."""
    try:
        handle = get_object_stream(key)
    except FileNotFoundError:
        return None
    body = handle["body"]
    try:
        raw = body.read()
    finally:
        body.close()
    return json.loads(raw)


def write_json(key: str, obj: dict[str, Any]) -> None:
    """Serialize and upload a JSON object (the asset manifest)."""
    put_bytes(json.dumps(obj, default=str).encode("utf-8"), key, "application/json")


def list_prefix(prefix: str) -> list[dict[str, Any]]:
    """Every object under `prefix` as `{"key", "size", "last_modified"}` dicts.

    Direct paginated read (not the shared cache) so the Videos Library sees the
    app's own writes immediately. Raises RuntimeError on S3 failure.
    """
    client = get_s3_client()
    out: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "Bucket": settings.b2_bucket_name,
        "Prefix": prefix,
        "MaxKeys": 1000,
    }
    try:
        while True:
            response = client.list_objects_v2(**kwargs)
            for obj in response.get("Contents", []):
                out.append(
                    {
                        "key": obj["Key"],
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"],
                    }
                )
            if not response.get("IsTruncated"):
                break
            kwargs["ContinuationToken"] = response["NextContinuationToken"]
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"B2 list failed for '{prefix}': {e}") from e
    return out


def delete_prefix(prefix: str) -> int:
    """Delete every object under `prefix` in batches. Returns the count deleted.

    SAFETY: refuses an empty prefix so a bug can never trigger a bucket-wide
    wipe — callers always pass a specific `videos/{id}/` prefix.
    """
    if not prefix or prefix in ("/", "videos/"):
        raise ValueError(f"refusing to delete unscoped prefix: {prefix!r}")
    client = get_s3_client()
    objects = list_prefix(prefix)
    deleted = 0
    try:
        for start in range(0, len(objects), 1000):
            batch = objects[start : start + 1000]
            client.delete_objects(
                Bucket=settings.b2_bucket_name,
                Delete={"Objects": [{"Key": o["key"]} for o in batch]},
            )
            deleted += len(batch)
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"B2 delete_prefix failed for '{prefix}': {e}") from e
    if deleted:
        _invalidate_list_cache()
    return deleted
