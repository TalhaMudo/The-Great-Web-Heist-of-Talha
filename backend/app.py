from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .crawler import crawler_service
from .indexer import index_service
from .models import CrawlJob, CrawlStats, JobStatus, summarize_jobs
from .storage import init_db, load_jobs, load_pages, save_job


class IndexRequest(BaseModel):
    origin: str
    k: int
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


class MetricsResponse(BaseModel):
    processed_urls: int
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

    job_id = str(uuid.uuid4())
    job = CrawlJob(
        id=job_id,
        origin_url=request.origin,
        max_depth=request.k,
        created_at=datetime.utcnow(),
        status=JobStatus.PENDING,
    )
    await crawler_service.start_job(job, rate_limit_per_sec=request.rate_limit_per_sec)

    return IndexResponse(job_id=job_id)


@app.get("/search", response_model=SearchResponse)
async def search(query: str) -> SearchResponse:
    raw_results = index_service.search(query)
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


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, object]:
    job = crawler_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "origin_url": job.origin_url,
        "max_depth": job.max_depth,
        "created_at": job.created_at.isoformat(),
        "status": job.status.value,
        "error_message": job.error_message,
        "stats": {
            "processed_urls": job.stats.processed_urls,
            "queued_urls": job.stats.queued_urls,
            "queue_max": job.stats.queue_max,
            "active_workers": job.stats.active_workers,
            "backpressure_state": job.stats.backpressure_state,
        },
    }


@app.get("/metrics", response_model=MetricsResponse)
async def metrics() -> MetricsResponse:
    return MetricsResponse(
        processed_urls=crawler_service.global_stats.processed_urls,
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

