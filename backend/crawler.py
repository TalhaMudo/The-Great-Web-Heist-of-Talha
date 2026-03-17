from __future__ import annotations

import asyncio
import html.parser
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Set, Tuple
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen

from .indexer import index_service
from .models import CrawlJob, CrawlStats, JobStatus
from .storage import save_job

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
    rate_limit_per_sec: float = 5.0
    last_request_ts: float = 0.0


class CrawlerService:
    def __init__(self, queue_maxsize: int = 1000, worker_count: int = 5) -> None:
        self.queue_maxsize = queue_maxsize
        self.worker_count = worker_count
        self.jobs: Dict[str, CrawlContext] = {}
        self.global_stats = CrawlStats(queue_max=queue_maxsize)
        self._lock = asyncio.Lock()

    def register_job(self, job: CrawlJob) -> None:
        if job.id in self.jobs:
            return
        # Jobs loaded from storage do not have an active queue or workers.
        ctx = CrawlContext(job=job, queue=asyncio.Queue(maxsize=self.queue_maxsize))
        self.jobs[job.id] = ctx

    def get_job(self, job_id: str) -> CrawlJob | None:
        ctx = self.jobs.get(job_id)
        return ctx.job if ctx else None

    def all_jobs(self) -> Dict[str, CrawlJob]:
        return {job_id: ctx.job for job_id, ctx in self.jobs.items()}

    async def start_job(self, job: CrawlJob) -> None:
        queue: "asyncio.Queue[Tuple[str, int, str]]" = asyncio.Queue(maxsize=self.queue_maxsize)
        ctx = CrawlContext(job=job, queue=queue)
        self.jobs[job.id] = ctx

        # Persist job metadata so it can be inspected or reloaded after restart.
        try:
            save_job(job)
        except Exception:
            logger.warning("Failed to persist job %s", job.id)

        await queue.put((job.origin_url, 0, job.origin_url))
        job.status = JobStatus.RUNNING
        job.stats.queue_max = self.queue_maxsize

        for _ in range(self.worker_count):
            asyncio.create_task(self._worker(ctx))

    async def _worker(self, ctx: CrawlContext) -> None:
        job = ctx.job
        self.global_stats.active_workers += 1
        try:
            while True:
                try:
                    url, depth, origin_url = await ctx.queue.get()
                except asyncio.CancelledError:
                    break

                if depth > job.max_depth:
                    ctx.queue.task_done()
                    continue

                if url in ctx.visited:
                    ctx.queue.task_done()
                    continue

                ctx.visited.add(url)
                await self._respect_rate_limit(ctx)
                html_text = await fetch_html(url)

                job.stats.processed_urls += 1
                self.global_stats.processed_urls += 1

                if html_text:
                    index_service.add_page(url=url, origin_url=origin_url, depth=depth, html_text=html_text)

                if html_text and depth < job.max_depth:
                    links = extract_links(url, html_text)
                    for link in links:
                        if link in ctx.visited:
                            continue
                        try:
                            ctx.queue.put_nowait((link, depth + 1, origin_url))
                        except asyncio.QueueFull:
                            job.stats.backpressure_state = "queue_full"
                            self.global_stats.backpressure_state = "queue_full"
                            break

                await self._update_queue_stats(ctx)
                ctx.queue.task_done()

                if ctx.queue.empty():
                    break

        except Exception as exc:  # noqa: BLE001
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            logger.exception("Crawl job %s failed", job.id)
        finally:
            self.global_stats.active_workers -= 1
            if job.status not in (JobStatus.FAILED,):
                job.status = JobStatus.COMPLETED
                job.stats.backpressure_state = "idle"
                self.global_stats.backpressure_state = "idle"

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
        self.global_stats.queued_urls = size
        if size >= self.queue_maxsize:
            ctx.job.stats.backpressure_state = "queue_full"
            self.global_stats.backpressure_state = "queue_full"
        else:
            ctx.job.stats.backpressure_state = "normal"
            self.global_stats.backpressure_state = "normal"


crawler_service = CrawlerService()

