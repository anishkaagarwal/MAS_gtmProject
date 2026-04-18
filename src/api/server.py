"""
FastAPI backend for Outmate.ai.

Two main endpoints:
1. POST /api/v1/query       — submit a GTM query, get back a request_id
2. GET  /api/v1/query/{id}/stream — SSE stream of pipeline events + final result

Design: the query endpoint enqueues work; the stream endpoint delivers results.
This decouples submission from execution and allows the frontend to reconnect
to an in-progress pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field

from src.models.schemas import PipelineResult
from src.orchestrator.pipeline import PipelineEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=5, max_length=2000)
    session_context: dict[str, Any] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    request_id: str
    status: str  # "accepted", "running", "complete", "failed"


class QueryResult(BaseModel):
    request_id: str
    status: str
    result: PipelineResult | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# In-memory job store (production: replace with Redis + task queue)
# ---------------------------------------------------------------------------

class JobStore:
    """
    Tracks in-flight pipeline executions.
    Production version would use Redis streams or a proper task queue (Celery/Temporal).
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._event_queues: dict[str, asyncio.Queue[PipelineEvent | None]] = {}

    def create(self, request_id: str, query: str) -> None:
        self._jobs[request_id] = {
            "query": query,
            "status": "accepted",
            "result": None,
            "error": None,
        }
        self._event_queues[request_id] = asyncio.Queue(maxsize=100)

    def get(self, request_id: str) -> dict[str, Any] | None:
        return self._jobs.get(request_id)

    def update(self, request_id: str, **kwargs: Any) -> None:
        if request_id in self._jobs:
            self._jobs[request_id].update(kwargs)

    def get_event_queue(self, request_id: str) -> asyncio.Queue[PipelineEvent | None] | None:
        return self._event_queues.get(request_id)

    def cleanup(self, request_id: str, after_seconds: float = 300) -> None:
        """Schedule cleanup — don't leak memory for completed jobs."""
        async def _cleanup():
            await asyncio.sleep(after_seconds)
            self._jobs.pop(request_id, None)
            self._event_queues.pop(request_id, None)
        asyncio.create_task(_cleanup())


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

jobs = JobStore()


def create_app(orchestrator_factory: Any = None) -> FastAPI:
    """
    Factory pattern — allows injecting different orchestrator configs for
    testing vs. production.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Outmate.ai API starting")
        yield
        logger.info("Outmate.ai API shutting down")

    app = FastAPI(
        title="Outmate.ai",
        description="Multi-Agent GTM Intelligence System",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # tighten in production
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Health check ---
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # --- Submit query ---
    @app.post("/api/v1/query", response_model=QueryResponse)
    async def submit_query(req: QueryRequest):
        request_id = str(uuid.uuid4())
        jobs.create(request_id, req.query)

        # Launch pipeline in background
        asyncio.create_task(
            _run_pipeline(request_id, req.query, req.session_context, orchestrator_factory)
        )

        return QueryResponse(request_id=request_id, status="accepted")

    # --- SSE stream ---
    @app.get("/api/v1/query/{request_id}/stream")
    async def stream_events(request_id: str):
        job = jobs.get(request_id)
        if not job:
            raise HTTPException(404, "Job not found")

        queue = jobs.get_event_queue(request_id)
        if not queue:
            raise HTTPException(404, "Event queue not found")

        async def event_generator():
            while True:
                event = await queue.get()
                if event is None:
                    # Pipeline complete — send final result
                    final_job = jobs.get(request_id)
                    yield f"event: complete\ndata: {json.dumps(final_job, default=str)}\n\n"
                    break
                yield f"event: {event.event_type}\ndata: {event.model_dump_json()}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Request-Id": request_id,
            },
        )

    # --- PDF download (must be before the catch-all {request_id} route) ---
    @app.get("/api/v1/query/{request_id}/pdf")
    async def download_pdf(request_id: str):
        job = jobs.get(request_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job["status"] != "complete" or not job.get("result"):
            raise HTTPException(400, "Results not ready yet")

        from src.tools.pdf_report import generate_pdf
        pdf_bytes = generate_pdf(job["result"])

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="outmate-report-{request_id[:8]}.pdf"',
            },
        )

    # --- Fetch result (polling fallback) ---
    @app.get("/api/v1/query/{request_id}", response_model=QueryResult)
    async def get_result(request_id: str):
        job = jobs.get(request_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return QueryResult(
            request_id=request_id,
            status=job["status"],
            result=job.get("result"),
            error=job.get("error"),
        )

    return app


async def _run_pipeline(
    request_id: str,
    query: str,
    session_context: dict[str, Any],
    orchestrator_factory: Any,
) -> None:
    """Background task that runs the orchestrator and pushes events to the SSE queue."""
    queue = jobs.get_event_queue(request_id)
    if not queue:
        return

    try:
        jobs.update(request_id, status="running")
        orchestrator = orchestrator_factory()

        # Wire events to the SSE queue
        async def push_event(event: PipelineEvent) -> None:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event queue full for %s — dropping event", request_id)

        orchestrator.on_event(push_event)

        result = await orchestrator.execute(query, session_context)

        jobs.update(request_id, status="complete", result=result.model_dump())

    except Exception as e:
        logger.exception("Pipeline failed for %s", request_id)
        jobs.update(request_id, status="failed", error=str(e))

    finally:
        await queue.put(None)  # signal stream end
        jobs.cleanup(request_id)
