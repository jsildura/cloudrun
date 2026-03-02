"""
Server-Sent Events endpoint for real-time download progress.
Replaces the WebSocket endpoint.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from .download_manager import DownloadManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/events/{job_id}")
async def job_events(request: Request, job_id: str):
    """
    SSE endpoint that streams progress events for a specific job.

    The client connects with EventSource and receives events like:
        data: {"type": "job_update", "data": {...}}

    A keepalive comment is sent every 30 seconds to prevent timeouts.
    """
    # Get the user's DownloadManager (imported from api_routes helper)
    from .api_routes import _extract_token, _get_user_dm

    token = _extract_token(request)
    dm = _get_user_dm(token)

    if job_id not in dm.jobs:
        raise HTTPException(404, f"Job {job_id} not found")

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        dm.register_ws(queue)  # Reuses existing broadcast mechanism

        try:
            # Send current state of the specific job immediately
            job = dm.jobs.get(job_id)
            if job:
                yield f"data: {json.dumps({'type': 'job_update', 'data': job.model_dump()})}\n\n"

            # Stream updates
            while True:
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=30.0)
                    # Only forward events for this specific job
                    if update.get("data", {}).get("job_id") == job_id:
                        yield f"data: {json.dumps(update)}\n\n"
                except asyncio.TimeoutError:
                    # Send SSE comment as keepalive
                    yield ": keepalive\n\n"

                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Stop streaming if job is in a terminal state
                job = dm.jobs.get(job_id)
                if job and job.stage.value in ("done", "error", "cancelled"):
                    # Send final state and close
                    yield f"data: {json.dumps({'type': 'job_complete', 'data': job.model_dump()})}\n\n"
                    break

        except asyncio.CancelledError:
            logger.info(f"SSE stream cancelled for job {job_id}")
        except Exception as e:
            logger.error(f"SSE error for job {job_id}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}})}\n\n"
        finally:
            dm.unregister_ws(queue)
            logger.info(f"SSE client disconnected for job {job_id}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/events")
async def all_events(request: Request):
    """
    SSE endpoint that streams ALL job events for the current user.
    Used by the main dashboard to monitor all active downloads.
    """
    from .api_routes import _extract_token, _get_user_dm

    token = _extract_token(request)
    dm = _get_user_dm(token)

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        dm.register_ws(queue)

        try:
            # Send current state of all jobs
            for job in dm.jobs.values():
                yield f"data: {json.dumps({'type': 'job_update', 'data': job.model_dump()})}\n\n"

            # Stream all updates
            while True:
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(update)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

                if await request.is_disconnected():
                    break

        except asyncio.CancelledError:
            logger.info("SSE all-events stream cancelled")
        except Exception as e:
            logger.error(f"SSE all-events error: {e}")
        finally:
            dm.unregister_ws(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
