from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from typing import Any, Iterator
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


@dataclass
class _BrowserResponse:
    text: str
    status: int


class Mobile01BrowserClient:
    """以一般 Edge 瀏覽器讀取 Mobile01 頁面。

    Mobile01 的 Akamai WAF 會直接 403 拒絕 requests 發出的請求，但一般瀏覽器可正常瀏覽；
    提供與 RateLimitedClient 相同的 get(url) 介面，讓 Mobile01Crawler 不需改動解析邏輯。
    """

    def __init__(self, config: CrawlConfig):
        self.config = config
        self._playwright = None
        self._browser = None
        self.page = None
        self._last_request_at = 0.0

    def __enter__(self) -> Mobile01BrowserClient:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": False}
        if self.config.proxy:
            launch_kwargs["proxy"] = {"server": self.config.proxy}
        try:
            self._browser = self._playwright.chromium.launch(channel="msedge", **launch_kwargs)
        except Exception:
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self.page = self._browser.new_page(locale="zh-TW")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def get(self, url: str) -> _BrowserResponse:
        assert self.page is not None
        wait = self.config.request_delay_sec + random.uniform(0, 0.5) - (time.time() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()
        resp = self.page.goto(url, timeout=self.config.timeout_sec * 3000, wait_until="domcontentloaded")
        status = resp.status if resp else 0
        if status >= 400:
            raise RuntimeError(f"Mobile01 {status}: {url}")
        return _BrowserResponse(text=self.page.content(), status=status)


class Mobile01Crawler:
    def __init__(self, client: RateLimitedClient | Mobile01BrowserClient, config: CrawlConfig):
        self.client = client
        self.config = config
        self.max_posts = getattr(config, "max_mobile01_articles", max(10, config.max_articles // 4))

    def _parse_topiclist(self, forum_id: int, html: str) -> list[Mobile01Ref]:
        refs: list[Mobile01Ref] = []
        seen: set[str] = set()
        for match in re.finditer(r"topicdetail\.php\?f=(\d+)&(?:amp;)?t=(\d+)", html):
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
        for page in range(1, self.config.mobile01_pages + 1):
            url = f"{M01_BASE}/topiclist.php?f={forum_id}&p={page}"
            try:
                resp = self.client.get(url)
            except Exception:
                break
            refs = self._parse_topiclist(forum_id, resp.text)
            if not refs:
                break
            for ref in refs:
                if ref.forum_id == forum_id:  # 排除側欄推薦的其他看板文章
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

        date_el = soup.select_one(".o-fNotes")
        posted_at = date_el.get_text(strip=True) if date_el else None
        reply_count = len(re.findall(r"topicdetail\.php\?f=\d+&(?:amp;)?t=\d+&(?:amp;)?p=", resp.text))

        return {
            "id": f"m01_{ref.forum_id}_{ref.topic_id}",
            "source": "Mobile01",
            "board": f"forum_{ref.forum_id}",
            "title": title,
            "content": content,
            "posted_at": posted_at,
            "url": url,
            "comment_count": reply_count,
            "engagement": {"likes": 0, "comments": reply_count},
        }

    def collect_refs(self) -> list[Mobile01Ref]:
        refs: dict[str, Mobile01Ref] = {}

        # Lexus 專屬看板內的文章不用標題篩選（標題常只寫車款），抓內文後 fetch_topic 會再全文篩選
        for forum_id in self.config.mobile01_forums:
            for ref in self.iter_forum_refs(forum_id):
                refs.setdefault(ref.href, ref)

        for keyword in self.config.mobile01_search_keywords:
            for ref in self.iter_search_refs(keyword):
                if is_relevant(ref.title, self.config.relevance_keywords, self.config.service_keywords):
                    refs[ref.href] = ref

        return list(refs.values())

    def crawl(self) -> list[dict]:
        refs = self.collect_refs()
        print(f"      [Mobile01] 候選文章 {len(refs)} 篇，最多抓取 {self.max_posts} 篇")
        posts: list[dict] = []
        for i, ref in enumerate(refs, 1):
            if len(posts) >= self.max_posts:
                break
            post = self.fetch_topic(ref)
            if post:
                posts.append(post)
            if i % 50 == 0:
                print(f"      [Mobile01] 已處理 {i} 篇候選，保留 {len(posts)} 篇")
        return posts
