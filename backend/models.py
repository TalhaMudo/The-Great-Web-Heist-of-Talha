from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CrawlStats:
    processed_urls: int = 0
    queued_urls: int = 0
    queue_max: int = 0
    active_workers: int = 0
    backpressure_state: str = "idle"


@dataclass
class CrawlJob:
    id: str
    origin_url: str
    max_depth: int
    created_at: datetime
    status: JobStatus = JobStatus.PENDING
    error_message: Optional[str] = None
    stats: CrawlStats = field(default_factory=CrawlStats)


PageRecord = Tuple[str, str, int]
IndexEntry = Tuple[str, str, int, float]


def summarize_jobs(jobs: Dict[str, CrawlJob]) -> List[Dict[str, object]]:
    summary: List[Dict[str, object]] = []
    for job in jobs.values():
        summary.append(
            {
                "id": job.id,
                "origin_url": job.origin_url,
                "max_depth": job.max_depth,
                "created_at": job.created_at.isoformat(),
                "status": job.status.value,
                "processed_urls": job.stats.processed_urls,
            }
        )
    return summary

