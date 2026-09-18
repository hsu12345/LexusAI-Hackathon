from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .config import CrawlConfig
from .http_client import RateLimitedClient
from .normalizer import is_relevant


PTT_BASE = "https://www.ptt.cc"


@dataclass
class PttArticleRef:
    board: str
    title: str
    href: str
    date: str | None = None


class PttCrawler:
    def __init__(self, client: RateLimitedClient, config: CrawlConfig):
        self.client = client
        self.config = config

    def _parse_index(self, board: str, html: str) -> list[PttArticleRef]:
        soup = BeautifulSoup(html, "lxml")
        refs: list[PttArticleRef] = []
        for row in soup.select("div.r-ent"):
            title_a = row.select_one(".title a")
            if not title_a or not title_a.get("href"):
                continue
            href = title_a["href"]
            if "M." not in href:
                continue
            date_el = row.select_one(".date")
            refs.append(
                PttArticleRef(
                    board=board,
                    title=title_a.get_text(strip=True),
                    href=href,
                    date=date_el.get_text(strip=True) if date_el else None,
                )
            )
        return refs

    def iter_board_refs(self, board: str) -> Iterator[PttArticleRef]:
        for page_idx in range(self.config.max_board_pages):
            page = "index.html" if page_idx == 0 else f"index{page_idx}.html"
            url = f"{PTT_BASE}/bbs/{board}/{page}"
            try:
                resp = self.client.get(url)
            except Exception:
                break
            refs = self._parse_index(board, resp.text)
            if not refs:
                break
            yield from refs

    def iter_search_refs(self, board: str, keyword: str) -> Iterator[PttArticleRef]:
        for page in range(1, self.config.max_search_pages + 1):
            url = f"{PTT_BASE}/bbs/{board}/search?q={keyword}&page={page}"
            try:
                resp = self.client.get(url)
            except Exception:
                break
            refs = self._parse_index(board, resp.text)
            if not refs:
                break
            yield from refs

    def fetch_article(self, ref: PttArticleRef) -> dict | None:
        url = urljoin(PTT_BASE, ref.href)
        try:
            resp = self.client.get(url)
        except Exception:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        main = soup.select_one("#main-content")
        if not main:
            return None

        for tag in main.select("span.article-meta-tag, span.article-meta-value, div.push"):
            tag.decompose()

        content = main.get_text("\n", strip=True)
        content = re.sub(r"--\s*\n.*?(ptt\.cc|批踢踢).*$", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = content.strip()
        if len(content) < 20:
            return None

        text = f"{ref.title} {content}"
        if not is_relevant(
            text,
            self.config.relevance_keywords,
            self.config.service_keywords,
            aftersales_only=self.config.aftersales_only,
        ):
            return None

        meta_values = [el.get_text(strip=True) for el in soup.select(".article-meta-value")]
        posted_at = meta_values[3] if len(meta_values) >= 4 else ref.date
        comment_count = len(soup.select("div.push, .push"))

        return {
            "id": ref.href.replace("/", "_").strip("_"),
            "source": "PTT",
            "board": ref.board,
            "title": ref.title,
            "content": content[:4000],
            "posted_at": posted_at,
            "url": url,
            "comment_count": comment_count,
            "engagement": {"likes": 0, "comments": comment_count},
        }

    def collect_refs(self) -> list[PttArticleRef]:
        refs: dict[str, PttArticleRef] = {}

        for board in self.config.ptt_boards:
            for ref in self.iter_board_refs(board):
                text = ref.title
                if is_relevant(
                    text,
                    self.config.relevance_keywords,
                    self.config.service_keywords,
                    aftersales_only=False,
                ):
                    refs[ref.href] = ref

            for keyword in self.config.ptt_search_keywords:
                for ref in self.iter_search_refs(board, keyword):
                    refs[ref.href] = ref

        return list(refs.values())

    def crawl(self) -> list[dict]:
        refs = self.collect_refs()
        posts: list[dict] = []
        for ref in refs[: self.config.max_articles]:
            post = self.fetch_article(ref)
            if post:
                posts.append(post)
        return posts
