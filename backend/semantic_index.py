from __future__ import annotations

import asyncio
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from .storage import (
    count_page_embeddings,
    count_pages,
    delete_page_embeddings,
    load_embedding_targets,
    load_page_embeddings,
    save_page_embedding,
)

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


@dataclass
class EmbeddingEngineStatus:
    status: str
    model_name: str
    rate_limit_per_sec: float
    max_pages: int | None
    total_pages: int
    embedded_pages: int
    remaining_pages: int
    failed_pages: int
    progress_percent: float
    updated_at: datetime
    error_message: str | None = None


class SemanticIndexService:
    def __init__(self) -> None:
        self._model = None
        self._embeddings: Dict[str, List[float]] = {}
        self._meta: Dict[str, Tuple[str, int, str]] = {}
        self._task: asyncio.Task[None] | None = None
        self._status: str = "idle"
        self._rate_limit_per_sec: float = 1.0
        self._max_pages: int | None = None
        self._failed_pages: int = 0
        self._error_message: str | None = None
        self._updated_at: datetime = datetime.utcnow()

    async def initialize(self) -> None:
        self._load_embeddings_cache()
        self._status = "idle"
        self._updated_at = datetime.utcnow()

    async def get_engine_status(self) -> EmbeddingEngineStatus:
        total_pages = count_pages()
        embedded_pages = count_page_embeddings(DEFAULT_EMBEDDING_MODEL)
        remaining_pages = max(total_pages - embedded_pages, 0)
        progress = 100.0 if total_pages == 0 else (embedded_pages / total_pages) * 100.0
        return EmbeddingEngineStatus(
            status=self._status,
            model_name=DEFAULT_EMBEDDING_MODEL,
            rate_limit_per_sec=self._rate_limit_per_sec,
            max_pages=self._max_pages,
            total_pages=total_pages,
            embedded_pages=embedded_pages,
            remaining_pages=remaining_pages,
            failed_pages=self._failed_pages,
            progress_percent=progress,
            updated_at=self._updated_at,
            error_message=self._error_message,
        )

    async def start_engine(self, rate_limit_per_sec: float, max_pages: int | None = None) -> EmbeddingEngineStatus:
        self._rate_limit_per_sec = rate_limit_per_sec
        self._max_pages = max_pages
        self._error_message = None
        if self._task and not self._task.done():
            self._updated_at = datetime.utcnow()
            return await self.get_engine_status()

        self._failed_pages = 0
        self._status = "running"
        self._updated_at = datetime.utcnow()
        self._task = asyncio.create_task(self._run_engine())
        return await self.get_engine_status()

    async def pause_engine(self) -> EmbeddingEngineStatus:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._status = "paused"
        self._updated_at = datetime.utcnow()
        return await self.get_engine_status()

    async def update_rate_limit(self, rate_limit_per_sec: float) -> EmbeddingEngineStatus:
        self._rate_limit_per_sec = rate_limit_per_sec
        self._updated_at = datetime.utcnow()
        return await self.get_engine_status()

    async def clear_embeddings(self) -> EmbeddingEngineStatus:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        delete_page_embeddings(DEFAULT_EMBEDDING_MODEL)
        self._embeddings.clear()
        self._meta.clear()
        self._failed_pages = 0
        self._error_message = None
        self._status = "idle"
        self._updated_at = datetime.utcnow()
        self._task = None
        return await self.get_engine_status()

    async def search(self, query: str, limit: int | None = None) -> List[Tuple[str, str, int, float, str]]:
        query = query.strip()
        if not query:
            return []
        if not self._embeddings:
            return []
        query_vector = await self._encode_text(query)
        if not query_vector:
            return []

        scored: List[Tuple[str, float]] = []
        for url, vector in self._embeddings.items():
            if len(vector) != len(query_vector):
                continue
            score = sum(a * b for a, b in zip(query_vector, vector))
            scored.append((url, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        if limit is not None:
            scored = scored[:limit]

        results: List[Tuple[str, str, int, float, str]] = []
        for url, score in scored:
            origin_url, depth, title = self._meta.get(url, ("", 0, ""))
            results.append((url, origin_url, depth, score, title))
        return results

    async def _run_engine(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            # Fail fast if model cannot load, instead of failing every page.
            await loop.run_in_executor(None, self._get_or_load_model_sync)
            rows = load_embedding_targets(
                model_name=DEFAULT_EMBEDDING_MODEL,
                limit=self._max_pages,
                only_missing=True,
            )
            if not rows:
                self._status = "completed"
                self._updated_at = datetime.utcnow()
                return

            for url, origin_url, depth, title, body_snippet in rows:
                text = f"{title}\n{body_snippet}".strip()
                if not text:
                    continue
                try:
                    vector = await loop.run_in_executor(None, self._encode_text_sync, text)
                    if not vector:
                        raise ValueError("empty embedding")
                    save_page_embedding(
                        url=url,
                        origin_url=origin_url,
                        depth=depth,
                        title=title,
                        model_name=DEFAULT_EMBEDDING_MODEL,
                        vector_json=json.dumps(vector),
                    )
                    self._embeddings[url] = vector
                    self._meta[url] = (origin_url, depth, title)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Embedding failed for %s: %s", url, exc)
                    self._failed_pages += 1
                self._updated_at = datetime.utcnow()
                await asyncio.sleep(1.0 / max(self._rate_limit_per_sec, 0.1))

            self._status = "completed"
            self._updated_at = datetime.utcnow()
        except asyncio.CancelledError:
            self._status = "paused"
            self._updated_at = datetime.utcnow()
        except Exception as exc:  # noqa: BLE001
            self._status = "failed"
            self._error_message = str(exc)
            self._updated_at = datetime.utcnow()
            logger.exception("Embedding engine failed")
        finally:
            self._task = None

    async def _encode_text(self, text: str) -> List[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._encode_text_sync, text)

    def _encode_text_sync(self, text: str) -> List[float]:
        model = self._get_or_load_model_sync()
        encoded = model.encode([text], normalize_embeddings=True)
        values = encoded[0].tolist() if hasattr(encoded, "tolist") else list(encoded[0])
        norm = math.sqrt(sum(v * v for v in values))
        if norm > 0:
            values = [v / norm for v in values]
        return [float(v) for v in values]

    def _get_or_load_model_sync(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "sentence-transformers is required for semantic search. Install requirements first."
            ) from exc
        self._model = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)
        return self._model

    def _load_embeddings_cache(self) -> None:
        self._embeddings.clear()
        self._meta.clear()
        for url, origin_url, depth, title, _model_name, vector_json in load_page_embeddings():
            try:
                vector = [float(v) for v in json.loads(vector_json)]
            except Exception:
                continue
            self._embeddings[url] = vector
            self._meta[url] = (origin_url, depth, title)


semantic_index_service = SemanticIndexService()
