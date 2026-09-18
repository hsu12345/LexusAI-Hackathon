from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .config import CrawlConfig
from .http_client import RateLimitedClient
from .normalizer import is_relevant

M01_BASE = "https://www.mobile01.com"


@dataclass
class Mobile01Ref:
    forum_id: int
    topic_id: int
    title: str
    href: str


class Mobile01Crawler:
    def __init__(self, client: RateLimitedClient, config: CrawlConfig):
        self.client = client
        self.config = config

    def _parse_topiclist(self, forum_id: int, html: str) -> list[Mobile01Ref]:
        refs: list[Mobile01Ref] = []
        seen: set[str] = set()
        for match in re.finditer(r"topicdetail\.php\?f=(\d+)&t=(\d+)", html):
            f_id, t_id = int(match.group(1)), int(match.group(2))
            key = f"{f_id}_{t_id}"
            if key in seen:
                continue
            seen.add(key)
            href = f"/topicdetail.php?f={f_id}&t={t_id}"
            title = self._title_near(html, match.start()) or f"topic {t_id}"
            refs.append(Mobile01Ref(forum_id=f_id, topic_id=t_id, title=title, href=href))
        return refs

    def _title_near(self, html: str, pos: int) -> str | None:
        chunk = html[max(0, pos - 200) : pos + 300]
        m = re.search(r">([^<>]{4,120})</a>", chunk)
        return m.group(1).strip() if m else None

    def iter_forum_refs(self, forum_id: int) -> Iterator[Mobile01Ref]:
        for page in range(1, self.config.max_search_pages + 1):
            url = f"{M01_BASE}/topiclist.php?f={forum_id}&p={page}"
            try:
                resp = self.client.get(url)
            except Exception:
                break
            refs = self._parse_topiclist(forum_id, resp.text)
            if not refs:
                break
            for ref in refs:
                yield ref

    def iter_search_refs(self, keyword: str) -> Iterator[Mobile01Ref]:
        url = f"{M01_BASE}/googlesearch.php?query={keyword}"
        try:
            resp = self.client.get(url)
        except Exception:
            return
        for ref in self._parse_topiclist(0, resp.text):
            yield ref

    def fetch_topic(self, ref: Mobile01Ref) -> dict | None:
        url = urljoin(M01_BASE, ref.href)
        try:
            resp = self.client.get(url)
        except Exception:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        title_el = soup.select_one("h1") or soup.select_one("title")
        title = title_el.get_text(strip=True) if title_el else ref.title

        parts: list[str] = []
        for sel in [".c-singlePost", ".single-post", "article", ".post-content"]:
            blocks = soup.select(sel)
            if blocks:
                for b in blocks[:5]:
                    text = b.get_text("\n", strip=True)
                    if len(text) > 30:
                        parts.append(text)
                break

        if not parts:
            main = soup.select_one("#content") or soup.select_one("main")
            if main:
                parts.append(main.get_text("\n", strip=True))

        content = "\n\n".join(parts)[:4000].strip()
        if len(content) < 40:
            return None

        text = f"{title} {content}"
        if not is_relevant(
            text,
            self.config.relevance_keywords,
            self.config.service_keywords,
            aftersales_only=self.config.aftersales_only,
        ):
            return None

        reply_count = len(re.findall(r"topicdetail\.php\?f=\d+&t=\d+&p=", resp.text))

        return {
            "id": f"m01_{ref.forum_id}_{ref.topic_id}",
            "source": "Mobile01",
            "board": f"forum_{ref.forum_id}",
            "title": title,
            "content": content,
            "url": url,
            "comment_count": reply_count,
            "engagement": {"likes": 0, "comments": reply_count},
        }

    def collect_refs(self) -> list[Mobile01Ref]:
        refs: dict[str, Mobile01Ref] = {}

        for forum_id in self.config.mobile01_forums:
            for ref in self.iter_forum_refs(forum_id):
                if is_relevant(ref.title, self.config.relevance_keywords, self.config.service_keywords):
                    refs[ref.href] = ref

        for keyword in self.config.mobile01_search_keywords:
            for ref in self.iter_search_refs(keyword):
                if is_relevant(ref.title, self.config.relevance_keywords, self.config.service_keywords):
                    refs[ref.href] = ref

        return list(refs.values())

    def crawl(self) -> list[dict]:
        refs = self.collect_refs()
        posts: list[dict] = []
        for ref in refs[: max(10, self.config.max_articles // 4)]:
            post = self.fetch_topic(ref)
            if post:
                posts.append(post)
        return posts
