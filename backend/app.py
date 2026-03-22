from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .crawler import crawler_service
from .indexer import index_service
from .models import CrawlJob, JobStatus, summarize_jobs
from .semantic_index import semantic_index_service
from .storage import init_db, load_job_events, load_jobs, load_pages


class IndexRequest(BaseModel):
    origin: str
    k: int
    max_urls_to_visit: int | None = None
    rate_limit_per_sec: float | None = None


class IndexResponse(BaseModel):
    job_id: str


class SearchResult(BaseModel):
    relevant_url: str
    origin_url: str
    depth: int
    score: float | None = None
    title: str | None = None


class SearchResponse(BaseModel):
    results: List[SearchResult]


class EmbeddingStartRequest(BaseModel):
    rate_limit_per_sec: float = 1.0
    max_pages: int | None = None


class EmbeddingRateLimitRequest(BaseModel):
    rate_limit_per_sec: float


class EmbeddingStatusResponse(BaseModel):
    updated_at: str
    status: str
    model_name: str
    rate_limit_per_sec: float
    max_pages: int | None = None
    total_pages: int
    embedded_pages: int
    failed_pages: int
    remaining_pages: int
    progress_percent: float
    error_message: str | None = None


class JobEventResponse(BaseModel):
    created_at: str
    level: str
    message: str
    url: str | None = None
    depth: int | None = None


class JobDetailResponse(BaseModel):
    id: str
    origin_url: str
    max_depth: int
    max_urls_to_visit: int | None = None
    created_at: str
    updated_at: str
    status: str
    error_message: str | None = None
    rate_limit_per_sec: float
    stats: Dict[str, object]
    visited_count: int
    frontier_count: int
    frontier_preview: List[Dict[str, object]]
    recent_events: List[JobEventResponse]


class GlobalQueueLimitRequest(BaseModel):
    global_queue_limit: int


class JobRateLimitRequest(BaseModel):
    rate_limit_per_sec: float


class MetricsResponse(BaseModel):
    processed_urls: int
    discovered_urls: int
    duplicate_urls: int
    failed_urls: int
    queued_urls: int
    queue_max: int
    backpressure_state: str
    active_workers: int
    jobs_summary: List[Dict[str, object]]


app = FastAPI(title="The Great Web Heist of Talha")


@app.post("/index", response_model=IndexResponse)
async def index(request: IndexRequest) -> IndexResponse:
    if request.k < 0:
        raise HTTPException(status_code=400, detail="k must be non-negative")
    if request.max_urls_to_visit is not None and request.max_urls_to_visit <= 0:
        raise HTTPException(status_code=400, detail="max_urls_to_visit must be positive")

    job_id = str(uuid.uuid4())
    job = CrawlJob(
        id=job_id,
        origin_url=request.origin,
        max_depth=request.k,
        max_urls_to_visit=request.max_urls_to_visit,
        created_at=datetime.utcnow(),
        status=JobStatus.PENDING,
    )
    await crawler_service.start_job(job, rate_limit_per_sec=request.rate_limit_per_sec)

    return IndexResponse(job_id=job_id)


@app.get("/search", response_model=SearchResponse)
async def search(query: str, limit: int | None = None) -> SearchResponse:
    raw_results = index_service.search(query, limit=limit)
    results = [
        SearchResult(
            relevant_url=url,
            origin_url=origin_url,
            depth=depth,
            score=score,
            title=title or None,
        )
        for url, origin_url, depth, score, title in raw_results
    ]
    return SearchResponse(results=results)


@app.get("/search/semantic", response_model=SearchResponse)
async def semantic_search(query: str, limit: int | None = None) -> SearchResponse:
    raw_results = await semantic_index_service.search(query, limit=limit)
    results = [
        SearchResult(
            relevant_url=url,
            origin_url=origin_url,
            depth=depth,
            score=score,
            title=title or None,
        )
        for url, origin_url, depth, score, title in raw_results
    ]
    return SearchResponse(results=results)


async def _serialize_embedding_status() -> EmbeddingStatusResponse:
    status = await semantic_index_service.get_engine_status()
    return EmbeddingStatusResponse(
        updated_at=status.updated_at.isoformat(),
        status=status.status,
        model_name=status.model_name,
        rate_limit_per_sec=status.rate_limit_per_sec,
        max_pages=status.max_pages,
        total_pages=status.total_pages,
        embedded_pages=status.embedded_pages,
        failed_pages=status.failed_pages,
        remaining_pages=status.remaining_pages,
        progress_percent=status.progress_percent,
        error_message=status.error_message,
    )


@app.get("/embeddings/status", response_model=EmbeddingStatusResponse)
async def embedding_status() -> EmbeddingStatusResponse:
    return await _serialize_embedding_status()


@app.post("/embeddings/start", response_model=EmbeddingStatusResponse)
async def start_embedding_engine(request: EmbeddingStartRequest) -> EmbeddingStatusResponse:
    if request.rate_limit_per_sec <= 0:
        raise HTTPException(status_code=400, detail="rate_limit_per_sec must be positive")
    if request.max_pages is not None and request.max_pages <= 0:
        raise HTTPException(status_code=400, detail="max_pages must be positive")
    await semantic_index_service.start_engine(
        rate_limit_per_sec=request.rate_limit_per_sec,
        max_pages=request.max_pages,
    )
    return await _serialize_embedding_status()


@app.post("/embeddings/pause", response_model=EmbeddingStatusResponse)
async def pause_embedding_engine() -> EmbeddingStatusResponse:
    await semantic_index_service.pause_engine()
    return await _serialize_embedding_status()


@app.post("/embeddings/rate-limit", response_model=EmbeddingStatusResponse)
async def update_embedding_engine_rate_limit(request: EmbeddingRateLimitRequest) -> EmbeddingStatusResponse:
    if request.rate_limit_per_sec <= 0:
        raise HTTPException(status_code=400, detail="rate_limit_per_sec must be positive")
    await semantic_index_service.update_rate_limit(request.rate_limit_per_sec)
    return await _serialize_embedding_status()


@app.post("/embeddings/clear", response_model=EmbeddingStatusResponse)
async def clear_embeddings() -> EmbeddingStatusResponse:
    await semantic_index_service.clear_embeddings()
    return await _serialize_embedding_status()


def _serialize_job(job_id: str) -> JobDetailResponse:
    ctx = crawler_service.get_job_context(job_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job = ctx.job
    queue_items: deque[tuple[str, int, str]] = getattr(ctx.queue, "_queue", deque())
    preview: List[Dict[str, object]] = []
    for url, depth, origin_url in list(queue_items)[:20]:
        preview.append({"url": url, "depth": depth, "origin_url": origin_url})
    events = [
        JobEventResponse(
            created_at=created_at,
            level=level,
            message=message,
            url=url or None,
            depth=depth,
        )
        for created_at, level, message, url, depth in load_job_events(job_id, limit=150)
    ]
    return JobDetailResponse(
        id=job.id,
        origin_url=job.origin_url,
        max_depth=job.max_depth,
        max_urls_to_visit=job.max_urls_to_visit,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        status=job.status.value,
        error_message=job.error_message,
        rate_limit_per_sec=job.rate_limit_per_sec,
        stats={
            "processed_urls": job.stats.processed_urls,
            "discovered_urls": job.stats.discovered_urls,
            "duplicate_urls": job.stats.duplicate_urls,
            "failed_urls": job.stats.failed_urls,
            "queued_urls": job.stats.queued_urls,
            "queue_max": job.stats.queue_max,
            "active_workers": job.stats.active_workers,
            "backpressure_state": job.stats.backpressure_state,
        },
        visited_count=len(ctx.visited),
        frontier_count=len(ctx.frontier),
        frontier_preview=preview,
        recent_events=events,
    )


@app.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str) -> JobDetailResponse:
    return _serialize_job(job_id)


@app.post("/jobs/{job_id}/pause", response_model=JobDetailResponse)
async def pause_job(job_id: str) -> JobDetailResponse:
    job = await crawler_service.pause_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(job.id)


@app.post("/jobs/{job_id}/resume", response_model=JobDetailResponse)
async def resume_job(job_id: str) -> JobDetailResponse:
    job = await crawler_service.resume_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(job.id)


@app.post("/jobs/{job_id}/rate-limit", response_model=JobDetailResponse)
async def update_job_rate_limit(job_id: str, request: JobRateLimitRequest) -> JobDetailResponse:
    if request.rate_limit_per_sec <= 0:
        raise HTTPException(status_code=400, detail="rate_limit_per_sec must be positive")
    job = await crawler_service.update_job_rate_limit(job_id, request.rate_limit_per_sec)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(job.id)


@app.post("/settings/queue-limit", response_model=MetricsResponse)
async def update_global_queue_limit(request: GlobalQueueLimitRequest) -> MetricsResponse:
    if request.global_queue_limit <= 0:
        raise HTTPException(status_code=400, detail="global_queue_limit must be positive")
    await crawler_service.set_global_queue_limit(request.global_queue_limit)
    return await metrics()


@app.get("/metrics", response_model=MetricsResponse)
async def metrics() -> MetricsResponse:
    return MetricsResponse(
        processed_urls=crawler_service.global_stats.processed_urls,
        discovered_urls=crawler_service.global_stats.discovered_urls,
        duplicate_urls=crawler_service.global_stats.duplicate_urls,
        failed_urls=crawler_service.global_stats.failed_urls,
        queued_urls=crawler_service.global_stats.queued_urls,
        queue_max=crawler_service.global_stats.queue_max,
        backpressure_state=crawler_service.global_stats.backpressure_state,
        active_workers=crawler_service.global_stats.active_workers,
        jobs_summary=summarize_jobs(crawler_service.all_jobs()),
    )


@app.get("/")
async def root() -> Dict[str, str]:
    return {"message": "The Great Web Heist of Talha backend is running."}


@app.on_event("startup")
async def on_startup() -> None:
    # Initialize storage and rebuild the in-memory index and job list from previous runs.
    init_db()

    for url, origin_url, depth, title, body_snippet in load_pages():
        index_service.add_snapshot_page(
            url=url,
            origin_url=origin_url,
            depth=depth,
            title=title,
            body_snippet=body_snippet,
        )

    for job in load_jobs():
        crawler_service.register_job(job)
    await semantic_index_service.initialize()

