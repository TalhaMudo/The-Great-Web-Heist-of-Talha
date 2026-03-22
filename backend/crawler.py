from __future__ import annotations

import asyncio
import html.parser
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Dict, List, Set, Tuple
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen

from .indexer import index_service
from .models import CrawlJob, CrawlStats, JobStatus
from .storage import append_job_event, load_job_state, save_job_state

logger = logging.getLogger(__name__)


class LinkExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)


def normalize_url(base_url: str, link: str) -> str | None:
    absolute = urljoin(base_url, link)
    absolute, _ = urldefrag(absolute)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    return absolute


async def fetch_html(url: str, timeout: float = 10.0) -> str | None:
    loop = asyncio.get_running_loop()

    def _blocking_fetch() -> str | None:
        req = Request(url, headers={"User-Agent": "TalhaCrawler/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            if "text/html" not in resp.headers.get("Content-Type", ""):
                return None
            return resp.read().decode(errors="ignore")

    try:
        return await loop.run_in_executor(None, _blocking_fetch)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def extract_links(url: str, html_text: str) -> List[str]:
    parser = LinkExtractor()
    parser.feed(html_text)
    links: List[str] = []
    for raw in parser.links:
        normalized = normalize_url(url, raw)
        if normalized:
            links.append(normalized)
    return links


@dataclass
class CrawlContext:
    job: CrawlJob
    queue: "asyncio.Queue[Tuple[str, int, str]]"
    visited: Set[str] = field(default_factory=set)
    frontier: Set[str] = field(default_factory=set)
    rate_limit_per_sec: float = 5.0
    last_request_ts: float = 0.0
    active_requests: int = 0
    worker_tasks: List[asyncio.Task[None]] = field(default_factory=list)
    stop_requested: bool = False
    state_dirty: bool = False
    checkpoint_counter: int = 0
    checkpoint_ts: float = 0.0


class CrawlerService:
    def __init__(
        self,
        queue_maxsize: int = 1000,
        worker_count: int = 5,
        default_rate_limit_per_sec: float = 1.0,
    ) -> None:
        self.queue_maxsize = queue_maxsize
        self.worker_count = worker_count
        self.jobs: Dict[str, CrawlContext] = {}
        self.global_stats = CrawlStats(queue_max=queue_maxsize)
        self.default_rate_limit_per_sec = default_rate_limit_per_sec
        self._lock = asyncio.Lock()

    def register_job(self, job: CrawlJob) -> None:
        if job.id in self.jobs:
            return
        visited, frontier_items = load_job_state(job.id)
        queue: "asyncio.Queue[Tuple[str, int, str]]" = asyncio.Queue(maxsize=self.queue_maxsize)
        frontier: Set[str] = set()
        for item in frontier_items:
            queue.put_nowait(item)
            frontier.add(item[0])
        if queue.empty() and job.status in (JobStatus.PENDING, JobStatus.PAUSED, JobStatus.RUNNING):
            queue.put_nowait((job.origin_url, 0, job.origin_url))
            frontier.add(job.origin_url)
        # Any previously-running job from storage is treated as paused after restart.
        if job.status == JobStatus.RUNNING:
            job.status = JobStatus.PAUSED
            job.updated_at = datetime.utcnow()
        job.stats.queue_max = self.queue_maxsize
        job.stats.queued_urls = queue.qsize()
        ctx = CrawlContext(
            job=job,
            queue=queue,
            visited=visited,
            frontier=frontier,
            rate_limit_per_sec=job.rate_limit_per_sec or self.default_rate_limit_per_sec,
            checkpoint_ts=time.monotonic(),
        )
        self.jobs[job.id] = ctx
        if job.status == JobStatus.PAUSED:
            try:
                save_job_state(job, visited, frontier_items)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to persist recovered paused state for %s", job.id)
        self._update_global_stats()

    def get_job(self, job_id: str) -> CrawlJob | None:
        ctx = self.jobs.get(job_id)
        return ctx.job if ctx else None

    def get_job_context(self, job_id: str) -> CrawlContext | None:
        return self.jobs.get(job_id)

    def all_jobs(self) -> Dict[str, CrawlJob]:
        return {job_id: ctx.job for job_id, ctx in self.jobs.items()}

    async def start_job(self, job: CrawlJob, rate_limit_per_sec: float | None = None) -> None:
        queue: "asyncio.Queue[Tuple[str, int, str]]" = asyncio.Queue(maxsize=self.queue_maxsize)
        effective_rate = rate_limit_per_sec or self.default_rate_limit_per_sec
        job.rate_limit_per_sec = effective_rate
        job.status = JobStatus.RUNNING
        ctx = CrawlContext(job=job, queue=queue, rate_limit_per_sec=effective_rate, checkpoint_ts=time.monotonic())
        self.jobs[job.id] = ctx

        await self._enqueue(ctx, job.origin_url, 0, job.origin_url)
        job.stats.queue_max = self.queue_maxsize
        job.updated_at = datetime.utcnow()
        self._append_event(job.id, "info", "Job started", url=job.origin_url, depth=0)
        await self._persist_state(ctx, force=True)
        self._spawn_workers(ctx)
        self._update_global_stats()

    async def pause_job(self, job_id: str) -> CrawlJob | None:
        ctx = self.jobs.get(job_id)
        if ctx is None:
            return None
        if ctx.job.status != JobStatus.RUNNING:
            return ctx.job
        ctx.stop_requested = True
        ctx.job.status = JobStatus.PAUSED
        ctx.job.updated_at = datetime.utcnow()
        self._append_event(job_id, "info", "Pause requested")
        tasks = list(ctx.worker_tasks)
        ctx.worker_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._persist_state(ctx, force=True)
        self._update_global_stats()
        return ctx.job

    async def resume_job(self, job_id: str) -> CrawlJob | None:
        ctx = self.jobs.get(job_id)
        if ctx is None:
            return None
        if ctx.job.status not in (JobStatus.PAUSED, JobStatus.PENDING):
            return ctx.job
        ctx.stop_requested = False
        ctx.job.status = JobStatus.RUNNING
        if ctx.queue.empty() and not ctx.visited:
            await self._enqueue(ctx, ctx.job.origin_url, 0, ctx.job.origin_url)
        ctx.job.error_message = None
        ctx.job.updated_at = datetime.utcnow()
        self._append_event(job_id, "info", "Job resumed")
        self._spawn_workers(ctx)
        await self._persist_state(ctx, force=True)
        self._update_global_stats()
        return ctx.job

    def _spawn_workers(self, ctx: CrawlContext) -> None:
        for _ in range(self.worker_count):
            task = asyncio.create_task(self._worker(ctx))
            ctx.worker_tasks.append(task)

    async def _worker(self, ctx: CrawlContext) -> None:
        job = ctx.job
        job.stats.active_workers += 1
        self._update_global_stats()
        try:
            while True:
                if ctx.stop_requested or job.status != JobStatus.RUNNING:
                    break
                try:
                    url, depth, origin_url = await asyncio.wait_for(ctx.queue.get(), timeout=0.5)
                except asyncio.CancelledError:
                    break
                except asyncio.TimeoutError:
                    if ctx.queue.empty() and ctx.active_requests == 0:
                        break
                    await self._maybe_checkpoint(ctx)
                    continue

                ctx.frontier.discard(url)
                if depth > job.max_depth:
                    ctx.queue.task_done()
                    continue

                if not await self._try_mark_visited(ctx, url, depth):
                    ctx.queue.task_done()
                    continue
                ctx.active_requests += 1
                await self._respect_rate_limit(ctx)
                html_text = await fetch_html(url)
                ctx.active_requests -= 1

                job.stats.processed_urls += 1
                if not html_text:
                    job.stats.failed_urls += 1
                    self._append_event(job.id, "warning", "Fetch returned no HTML", url=url, depth=depth)
                else:
                    index_service.add_page(url=url, origin_url=origin_url, depth=depth, html_text=html_text)
                    self._append_event(job.id, "info", "Indexed page", url=url, depth=depth)

                if html_text and depth < job.max_depth:
                    links = extract_links(url, html_text)
                    for link in links:
                        if await self._already_visited(ctx, link):
                            job.stats.duplicate_urls += 1
                            continue
                        await self._enqueue(ctx, link, depth + 1, origin_url)

                await self._update_queue_stats(ctx)
                ctx.state_dirty = True
                ctx.checkpoint_counter += 1
                job.updated_at = datetime.utcnow()
                ctx.queue.task_done()
                await self._maybe_checkpoint(ctx)

        except Exception as exc:  # noqa: BLE001
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.updated_at = datetime.utcnow()
            self._append_event(job.id, "error", f"Worker failed: {exc}")
            logger.exception("Crawl job %s failed", job.id)
        finally:
            job.stats.active_workers = max(0, job.stats.active_workers - 1)
            if (
                job.status == JobStatus.RUNNING
                and ctx.queue.empty()
                and ctx.active_requests == 0
                and job.stats.active_workers == 0
            ):
                job.status = JobStatus.COMPLETED
                job.stats.backpressure_state = "idle"
                job.updated_at = datetime.utcnow()
                self._append_event(job.id, "info", "Job completed")
            self._update_global_stats()
            await self._persist_state(ctx, force=True)

    async def _try_mark_visited(self, ctx: CrawlContext, url: str, depth: int) -> bool:
        async with self._lock:
            if url in ctx.visited:
                self._append_event(ctx.job.id, "debug", "Skipped already-visited URL", url=url, depth=depth)
                return False
            ctx.visited.add(url)
            ctx.state_dirty = True
            return True

    async def _already_visited(self, ctx: CrawlContext, url: str) -> bool:
        async with self._lock:
            return url in ctx.visited or url in ctx.frontier

    async def _respect_rate_limit(self, ctx: CrawlContext) -> None:
        min_interval = 1.0 / ctx.rate_limit_per_sec
        now = time.monotonic()
        delta = now - ctx.last_request_ts
        if delta < min_interval:
            await asyncio.sleep(min_interval - delta)
        ctx.last_request_ts = time.monotonic()

    async def _update_queue_stats(self, ctx: CrawlContext) -> None:
        size = ctx.queue.qsize()
        ctx.job.stats.queued_urls = size
        if size >= self.queue_maxsize:
            ctx.job.stats.backpressure_state = "queue_full"
        elif size > max(1, int(self.queue_maxsize * 0.8)):
            ctx.job.stats.backpressure_state = "high"
        else:
            ctx.job.stats.backpressure_state = "normal"
        self._update_global_stats()

    async def _enqueue(self, ctx: CrawlContext, url: str, depth: int, origin_url: str) -> bool:
        if depth > ctx.job.max_depth:
            return False
        if await self._already_visited(ctx, url):
            return False
        while True:
            if ctx.stop_requested or ctx.job.status != JobStatus.RUNNING:
                return False
            try:
                await asyncio.wait_for(ctx.queue.put((url, depth, origin_url)), timeout=0.5)
                ctx.frontier.add(url)
                ctx.job.stats.discovered_urls += 1
                ctx.state_dirty = True
                await self._update_queue_stats(ctx)
                return True
            except asyncio.TimeoutError:
                ctx.job.stats.backpressure_state = "queue_full"
                self._update_global_stats()
                await asyncio.sleep(0)

    async def _maybe_checkpoint(self, ctx: CrawlContext) -> None:
        if not ctx.state_dirty:
            return
        now = time.monotonic()
        if ctx.checkpoint_counter >= 20 or (now - ctx.checkpoint_ts) >= 3:
            await self._persist_state(ctx, force=True)
            ctx.checkpoint_counter = 0
            ctx.checkpoint_ts = now

    async def _persist_state(self, ctx: CrawlContext, force: bool = False) -> None:
        if not force and not ctx.state_dirty:
            return
        ctx.job.stats.queued_urls = ctx.queue.qsize()
        ctx.job.stats.queue_max = self.queue_maxsize
        ctx.job.updated_at = datetime.utcnow()
        queue_items: Deque[Tuple[str, int, str]] = getattr(ctx.queue, "_queue", deque())
        frontier_items = list(queue_items)
        try:
            save_job_state(ctx.job, set(ctx.visited), frontier_items)
            ctx.state_dirty = False
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist state for job %s", ctx.job.id)

    def _append_event(self, job_id: str, level: str, message: str, url: str | None = None, depth: int | None = None) -> None:
        try:
            append_job_event(job_id, level, message, url=url, depth=depth)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to append event for job %s", job_id)

    def _update_global_stats(self) -> None:
        stats = CrawlStats(queue_max=self.queue_maxsize)
        backpressure_levels: List[str] = []
        for ctx in self.jobs.values():
            stats.processed_urls += ctx.job.stats.processed_urls
            stats.discovered_urls += ctx.job.stats.discovered_urls
            stats.duplicate_urls += ctx.job.stats.duplicate_urls
            stats.failed_urls += ctx.job.stats.failed_urls
            stats.queued_urls += ctx.job.stats.queued_urls
            stats.active_workers += ctx.job.stats.active_workers
            backpressure_levels.append(ctx.job.stats.backpressure_state)
        if "queue_full" in backpressure_levels:
            stats.backpressure_state = "queue_full"
        elif "high" in backpressure_levels:
            stats.backpressure_state = "high"
        elif "normal" in backpressure_levels:
            stats.backpressure_state = "normal"
        else:
            stats.backpressure_state = "idle"
        self.global_stats = stats


crawler_service = CrawlerService()

