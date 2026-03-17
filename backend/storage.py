from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple

from .models import CrawlJob, JobStatus

DB_PATH = Path(__file__).resolve().parent.parent / "crawler.db"


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pages (
                url TEXT PRIMARY KEY,
                origin_url TEXT NOT NULL,
                depth INTEGER NOT NULL,
                title TEXT,
                body_snippet TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                origin_url TEXT NOT NULL,
                max_depth INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_page(url: str, origin_url: str, depth: int, title: str, body_snippet: str) -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO pages (url, origin_url, depth, title, body_snippet)
            VALUES (?, ?, ?, ?, ?)
            """,
            (url, origin_url, depth, title, body_snippet),
        )
        conn.commit()
    finally:
        conn.close()


def save_job(job: CrawlJob) -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO jobs (id, origin_url, max_depth, created_at, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.origin_url,
                job.max_depth,
                job.created_at.isoformat(),
                job.status.value,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_pages() -> List[Tuple[str, str, int, str, str]]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT url, origin_url, depth, title, body_snippet FROM pages")
        rows = list(cur.fetchall())
        return [(str(u), str(o), int(d), str(t or ""), str(b or "")) for (u, o, d, t, b) in rows]
    finally:
        conn.close()


def load_jobs() -> List[CrawlJob]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, origin_url, max_depth, created_at, status FROM jobs")
        rows = cur.fetchall()
        jobs: List[CrawlJob] = []
        for job_id, origin_url, max_depth, created_at, status in rows:
            jobs.append(
                CrawlJob(
                    id=str(job_id),
                    origin_url=str(origin_url),
                    max_depth=int(max_depth),
                    created_at=datetime.fromisoformat(str(created_at)),
                    status=JobStatus(str(status)),
                )
            )
        return jobs
    finally:
        conn.close()

