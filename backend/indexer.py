from __future__ import annotations

import html
import html.parser
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Dict, List, Tuple

from .models import IndexEntry, PageRecord


class TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: List[str] = []
        self.text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs):  # type: ignore[override]
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str):  # type: ignore[override]
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        text = data.strip()
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        else:
            self.text_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts)

    @property
    def body_text(self) -> str:
        return " ".join(self.text_parts)


TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> List[str]:
    text = text.lower()
    return TOKEN_RE.findall(text)


@dataclass
class IndexedPage:
    url: str
    origin_url: str
    depth: int
    title: str
    tokens: List[str]


class IndexService:
    def __init__(self) -> None:
        self.inverted: DefaultDict[str, List[IndexEntry]] = defaultdict(list)
        self.pages: Dict[str, IndexedPage] = {}

    def add_page(self, url: str, origin_url: str, depth: int, html_text: str) -> None:
        parser = TextExtractor()
        parser.feed(html_text)
        title = html.unescape(parser.title)
        body = html.unescape(parser.body_text)

        tokens = tokenize(f"{title} {body}")
        if not tokens:
            return

        page = IndexedPage(url=url, origin_url=origin_url, depth=depth, title=title, tokens=tokens)
        self.pages[url] = page

        term_counts: DefaultDict[str, int] = defaultdict(int)
        for token in tokens:
            term_counts[token] += 1

        for token, count in term_counts.items():
            score = float(count)
            self.inverted[token].append((url, origin_url, depth, score))

        # Persist a lightweight snapshot suitable for rebuilding the index after a restart.
        body_snippet = " ".join(tokens)[:1000]
        try:
            from . import storage  # Local import to avoid circular dependency
        except Exception:
            storage = None  # type: ignore[assignment]
        if storage is not None:
            try:
                storage.save_page(url=url, origin_url=origin_url, depth=depth, title=title, body_snippet=body_snippet)
            except Exception:
                # Persistence failures should not break crawling.
                pass

    def add_snapshot_page(self, url: str, origin_url: str, depth: int, title: str, body_snippet: str) -> None:
        tokens = tokenize(f"{title} {body_snippet}")
        if not tokens:
            return
        page = IndexedPage(url=url, origin_url=origin_url, depth=depth, title=title, tokens=tokens)
        self.pages[url] = page

        term_counts: DefaultDict[str, int] = defaultdict(int)
        for token in tokens:
            term_counts[token] += 1

        for token, count in term_counts.items():
            score = float(count)
            self.inverted[token].append((url, origin_url, depth, score))

    def search(self, query: str, limit: int | None = None) -> List[Tuple[str, str, int, float, str]]:
        tokens = tokenize(query)
        if not tokens:
            return []

        scores: DefaultDict[str, float] = defaultdict(float)
        meta: Dict[str, Tuple[str, int, str]] = {}

        for token in tokens:
            for url, origin_url, depth, score in self.inverted.get(token, []):
                scores[url] += score
                if url not in meta:
                    title = self.pages.get(url).title if url in self.pages else ""
                    meta[url] = (origin_url, depth, title)

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if limit is not None:
            ranked = ranked[:limit]
        results: List[Tuple[str, str, int, float, str]] = []
        for url, score in ranked:
            origin_url, depth, title = meta.get(url, ("", 0, ""))
            results.append((url, origin_url, depth, score, title))
        return results


index_service = IndexService()

