from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Set, Tuple

from .models import CrawlJob, CrawlStats, JobStatus

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
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                rate_limit_per_sec REAL NOT NULL DEFAULT 1.0,
                error_message TEXT,
                processed_urls INTEGER NOT NULL DEFAULT 0,
                discovered_urls INTEGER NOT NULL DEFAULT 0,
                duplicate_urls INTEGER NOT NULL DEFAULT 0,
                failed_urls INTEGER NOT NULL DEFAULT 0,
                queued_urls INTEGER NOT NULL DEFAULT 0,
                queue_max INTEGER NOT NULL DEFAULT 0,
                active_workers INTEGER NOT NULL DEFAULT 0,
                backpressure_state TEXT NOT NULL DEFAULT 'idle'
            )
            """
        )
        _add_column_if_missing(cur, "jobs", "updated_at", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(cur, "jobs", "rate_limit_per_sec", "REAL NOT NULL DEFAULT 1.0")
        _add_column_if_missing(cur, "jobs", "error_message", "TEXT")
        _add_column_if_missing(cur, "jobs", "processed_urls", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "jobs", "discovered_urls", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "jobs", "duplicate_urls", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "jobs", "failed_urls", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "jobs", "queued_urls", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "jobs", "queue_max", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "jobs", "active_workers", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(cur, "jobs", "backpressure_state", "TEXT NOT NULL DEFAULT 'idle'")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS job_visited (
                job_id TEXT NOT NULL,
                url TEXT NOT NULL,
                PRIMARY KEY (job_id, url)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS job_frontier (
                job_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                url TEXT NOT NULL,
                depth INTEGER NOT NULL,
                origin_url TEXT NOT NULL,
                PRIMARY KEY (job_id, url)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                url TEXT,
                depth INTEGER
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _add_column_if_missing(cur: sqlite3.Cursor, table_name: str, column_name: str, definition: str) -> None:
    cur.execute(f"PRAGMA table_info({table_name})")
    existing = {str(row[1]) for row in cur.fetchall()}
    if column_name not in existing:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


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
        _upsert_job(cur, job)
        conn.commit()
    finally:
        conn.close()


def save_job_state(
    job: CrawlJob,
    visited_urls: Set[str],
    frontier_items: List[Tuple[str, int, str]],
) -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        _upsert_job(cur, job)
        cur.execute("DELETE FROM job_visited WHERE job_id = ?", (job.id,))
        cur.execute("DELETE FROM job_frontier WHERE job_id = ?", (job.id,))
        cur.executemany(
            "INSERT OR IGNORE INTO job_visited (job_id, url) VALUES (?, ?)",
            [(job.id, url) for url in visited_urls],
        )
        cur.executemany(
            """
            INSERT OR REPLACE INTO job_frontier (job_id, position, url, depth, origin_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(job.id, idx, url, depth, origin_url) for idx, (url, depth, origin_url) in enumerate(frontier_items)],
        )
        conn.commit()
    finally:
        conn.close()


def _upsert_job(cur: sqlite3.Cursor, job: CrawlJob) -> None:
    cur.execute(
        """
        INSERT OR REPLACE INTO jobs (
            id,
            origin_url,
            max_depth,
            created_at,
            updated_at,
            status,
            rate_limit_per_sec,
            error_message,
            processed_urls,
            discovered_urls,
            duplicate_urls,
            failed_urls,
            queued_urls,
            queue_max,
            active_workers,
            backpressure_state
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.id,
            job.origin_url,
            job.max_depth,
            job.created_at.isoformat(),
            job.updated_at.isoformat(),
            job.status.value,
            job.rate_limit_per_sec,
            job.error_message,
            job.stats.processed_urls,
            job.stats.discovered_urls,
            job.stats.duplicate_urls,
            job.stats.failed_urls,
            job.stats.queued_urls,
            job.stats.queue_max,
            job.stats.active_workers,
            job.stats.backpressure_state,
        ),
    )


def load_job_state(job_id: str) -> Tuple[Set[str], List[Tuple[str, int, str]]]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT url FROM job_visited WHERE job_id = ?", (job_id,))
        visited = {str(row[0]) for row in cur.fetchall()}
        cur.execute(
            """
            SELECT url, depth, origin_url
            FROM job_frontier
            WHERE job_id = ?
            ORDER BY position ASC
            """,
            (job_id,),
        )
        frontier = [(str(url), int(depth), str(origin_url)) for url, depth, origin_url in cur.fetchall()]
        return visited, frontier
    finally:
        conn.close()


def append_job_event(
    job_id: str,
    level: str,
    message: str,
    url: str | None = None,
    depth: int | None = None,
) -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO job_events (job_id, created_at, level, message, url, depth)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, datetime.utcnow().isoformat(), level, message, url, depth),
        )
        conn.commit()
    finally:
        conn.close()


def load_job_events(job_id: str, limit: int = 100) -> List[Tuple[str, str, str, str, int | None]]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT created_at, level, message, url, depth
            FROM job_events
            WHERE job_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (job_id, limit),
        )
        rows = cur.fetchall()
        rows.reverse()
        return [
            (str(created_at), str(level), str(message), str(url or ""), int(depth) if depth is not None else None)
            for created_at, level, message, url, depth in rows
        ]
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
        cur.execute(
            """
            SELECT
                id,
                origin_url,
                max_depth,
                created_at,
                updated_at,
                status,
                rate_limit_per_sec,
                error_message,
                processed_urls,
                discovered_urls,
                duplicate_urls,
                failed_urls,
                queued_urls,
                queue_max,
                active_workers,
                backpressure_state
            FROM jobs
            """
        )
        rows = cur.fetchall()
        jobs: List[CrawlJob] = []
        for (
            job_id,
            origin_url,
            max_depth,
            created_at,
            updated_at,
            status,
            rate_limit_per_sec,
            error_message,
            processed_urls,
            discovered_urls,
            duplicate_urls,
            failed_urls,
            queued_urls,
            queue_max,
            active_workers,
            backpressure_state,
        ) in rows:
            jobs.append(
                CrawlJob(
                    id=str(job_id),
                    origin_url=str(origin_url),
                    max_depth=int(max_depth),
                    created_at=datetime.fromisoformat(str(created_at)),
                    status=JobStatus(str(status)),
                    rate_limit_per_sec=float(rate_limit_per_sec or 1.0),
                    error_message=str(error_message) if error_message is not None else None,
                    updated_at=datetime.fromisoformat(str(updated_at)) if updated_at else datetime.fromisoformat(str(created_at)),
                    stats=CrawlStats(
                        processed_urls=int(processed_urls or 0),
                        discovered_urls=int(discovered_urls or 0),
                        duplicate_urls=int(duplicate_urls or 0),
                        failed_urls=int(failed_urls or 0),
                        queued_urls=int(queued_urls or 0),
                        queue_max=int(queue_max or 0),
                        active_workers=int(active_workers or 0),
                        backpressure_state=str(backpressure_state or "idle"),
                    ),
                )
            )
        return jobs
    finally:
        conn.close()

