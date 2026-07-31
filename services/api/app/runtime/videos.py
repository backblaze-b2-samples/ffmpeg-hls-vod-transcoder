"""Video routes: ingest (create), CRUD + re-transcode (run), stats, and the
HLS playback proxy.

Handlers stay thin — every decision lives in `service/video.py`. Two handlers
are `async` because they stream: `POST /videos` reads the multipart source in
chunks (never buffering a whole video in RAM), and the HLS proxy streams
playlists/segments straight from B2. The rest are sync `def` so Starlette runs
the blocking boto3 calls in its threadpool.
"""

import logging
import os
import tempfile

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.config import settings
from app.repo import video_store
from app.runtime.metrics import record_upload
from app.service import video as video_service
from app.service.ingest import SNIFF_BYTES, IngestError
from app.types import (
    IngestResponse,
    LadderPreset,
    RenameRequest,
    RetranscodeRequest,
    TranscodeStatsResponse,
    VideoAsset,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _stream_to_temp(file: UploadFile) -> tuple[str, int, bytes]:
    """Stream an upload to a temp file, enforcing the size cap as we go. Returns
    (temp_path, size_bytes, head_bytes). The caller must delete the temp file."""
    fd, temp_path = tempfile.mkstemp(suffix="-source")
    total = 0
    head = b""
    with os.fdopen(fd, "wb") as tmp:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            if not head:
                head = chunk[:SNIFF_BYTES]
            total += len(chunk)
            if total > settings.max_source_size:
                raise HTTPException(status_code=413, detail="Source video too large")
            tmp.write(chunk)
    return temp_path, total, head


@router.post("/videos", response_model=IngestResponse)
async def ingest_video(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    ladder: LadderPreset = Form(LadderPreset.P720),
    title: str = Form(""),
):
    temp_path, size, head = await _stream_to_temp(file)
    try:
        asset = await run_in_threadpool(
            video_service.create_video,
            source_path=temp_path,
            filename=file.filename or "source",
            size_bytes=size,
            head=head,
            ladder=ladder,
            title=title,
        )
    except IngestError as e:
        record_upload(success=False)
        raise HTTPException(status_code=e.status_code, detail=e.detail) from None
    finally:
        os.unlink(temp_path)

    record_upload(success=True)
    background_tasks.add_task(video_service.run_transcode_job, asset.id)
    logger.info("Ingest queued: id=%s ladder=%s", asset.id, ladder)
    return IngestResponse(id=asset.id, title=asset.title, status=asset.status)


@router.get("/videos", response_model=list[VideoAsset])
def list_videos_endpoint():
    return video_service.list_videos()


# Declared before /videos/{video_id} so "stats" is not captured as an id.
@router.get("/videos/stats", response_model=TranscodeStatsResponse)
def video_stats_endpoint():
    return video_service.get_transcode_stats()


@router.get("/videos/{video_id}", response_model=VideoAsset)
def get_video_endpoint(video_id: str):
    asset = video_service.get_video(video_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Video not found")
    return asset


@router.patch("/videos/{video_id}", response_model=VideoAsset)
def rename_video_endpoint(video_id: str, body: RenameRequest):
    try:
        return video_service.rename_video(video_id, body.title)
    except video_service.VideoNotFoundError:
        raise HTTPException(status_code=404, detail="Video not found") from None


@router.delete("/videos/{video_id}")
def delete_video_endpoint(video_id: str):
    try:
        count = video_service.delete_video(video_id)
    except video_service.VideoNotFoundError:
        raise HTTPException(status_code=404, detail="Video not found") from None
    logger.info("Video deleted: id=%s objects=%d", video_id, count)
    return {"deleted": True, "id": video_id, "objects": count}


@router.post("/videos/{video_id}/retranscode", response_model=IngestResponse)
def retranscode_endpoint(
    video_id: str, body: RetranscodeRequest, background_tasks: BackgroundTasks
):
    try:
        asset = video_service.retranscode(video_id, body.ladder)
    except video_service.VideoNotFoundError:
        raise HTTPException(status_code=404, detail="Video not found") from None
    background_tasks.add_task(video_service.run_transcode_job, video_id)
    return IngestResponse(id=asset.id, title=asset.title, status=asset.status)


def _reject_traversal(path: str) -> None:
    if ".." in path.split("/") or path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")


@router.get("/videos/{video_id}/hls/{path:path}")
def hls_proxy_endpoint(video_id: str, path: str):
    """Stream an HLS playlist/segment straight from B2 with a 1:1
    request-path -> B2-key map, so relative segment references resolve with no
    playlist rewriting. Hit directly by hls.js / native <video>, not the
    typed api-client — so it lives in SERVER_ONLY_OPERATIONS."""
    _reject_traversal(path)
    key = f"{settings.video_prefix}{video_id}/hls/{path}"
    return _stream_b2_object(key)


@router.get("/videos/{video_id}/thumbnail")
def thumbnail_endpoint(video_id: str):
    """Stream the sprite sheet (scrub-preview thumbnails). Hit directly by an
    <img>, so it is a SERVER_ONLY_OPERATION too."""
    key = f"{settings.video_prefix}{video_id}/thumbs/sprite.jpg"
    return _stream_b2_object(key)


def _stream_b2_object(key: str) -> StreamingResponse:
    try:
        handle = video_store.get_object_stream(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Not found") from None
    except RuntimeError:
        raise HTTPException(status_code=502, detail="Storage read failed") from None
    body = handle["body"]

    def _iter():
        try:
            yield from body.iter_chunks(256 * 1024)
        finally:
            body.close()

    return StreamingResponse(_iter(), media_type=handle["content_type"])
