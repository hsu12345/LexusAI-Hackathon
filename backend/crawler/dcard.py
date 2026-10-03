from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import CrawlConfig
from .normalizer import is_relevant
from .stealth import apply_stealth, stealth_launch_args

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COOKIE_PATH = ROOT / "data" / "dcard_cookies.json"
API_BASE = "https://www.dcard.tw/service/api/v2"


@dataclass
class DcardPostRef:
    post_id: int
    title: str
    forum_alias: str
    forum_name: str
    url: str


class DcardBrowserSession:
    """透過 Playwright 建立 Dcard session，並以 in-page fetch 呼叫官方 API。"""

    def __init__(self, config: CrawlConfig):
        self.config = config
        self.cookie_path = Path(getattr(config, "dcard_cookie_path", DEFAULT_COOKIE_PATH))
        self.headless = getattr(config, "dcard_headless", False)
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self) -> DcardBrowserSession:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "args": stealth_launch_args(),
        }
        if getattr(self.config, "proxy", None):
            launch_kwargs["proxy"] = {"server": self.config.proxy}
        if getattr(self.config, "dcard_use_edge", True):
            try:
                self._browser = self._playwright.chromium.launch(channel="msedge", **launch_kwargs)
            except Exception:
                self._browser = self._playwright.chromium.launch(**launch_kwargs)
        else:
            self._browser = self._playwright.chromium.launch(**launch_kwargs)

        self._context = self._browser.new_context(
            locale="zh-TW",
            viewport={"width": 1366, "height": 768},
            user_agent=self.config.user_agent,
        )
        apply_stealth(self._context)
        if self.cookie_path.exists():
            try:
                cookies = json.loads(self.cookie_path.read_text(encoding="utf-8"))
                self._context.add_cookies(cookies)
            except Exception:
                pass

        self.page = self._context.new_page()
        self._bootstrap_session()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._context:
                cookies = self._context.cookies()
                self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
                self.cookie_path.write_text(
                    json.dumps(cookies, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        finally:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()

    def _bootstrap_session(self) -> None:
        assert self.page is not None
        self.page.goto("https://www.dcard.tw", timeout=90000, wait_until="domcontentloaded")
        for _ in range(20):
            title = self.page.title()
            if "請稍候" not in title and "Attention" not in title and "Just a moment" not in title:
                break
            time.sleep(2)
        time.sleep(1)

    def fetch_json(self, url: str, retries: int = 3) -> Any:
        assert self.page is not None
        last_status = 0
        for attempt in range(retries):
            result = self.page.evaluate(
                """async (url) => {
                    const resp = await fetch(url, { credentials: 'include' });
                    const text = await resp.text();
                    return { status: resp.status, text };
                }""",
                url,
            )
            last_status = int(result["status"])
            if last_status == 200:
                return json.loads(result["text"])
            if last_status == 429:
                time.sleep(10 * (attempt + 1))
                continue
            break
        raise RuntimeError(f"Dcard API {last_status}: {url}")


class DcardCrawler:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.max_posts = getattr(config, "max_dcard_articles", max(15, config.max_articles // 3))

    def _parse_list(self, items: list[dict]) -> list[DcardPostRef]:
        refs: list[DcardPostRef] = []
        for item in items:
            post_id = item.get("id")
            title = item.get("title") or ""
            forum_alias = item.get("forumAlias") or "unknown"
            if not post_id or not title:
                continue
            refs.append(
                DcardPostRef(
                    post_id=int(post_id),
                    title=title,
                    forum_alias=forum_alias,
                    forum_name=item.get("forumName") or forum_alias,
                    url=f"https://www.dcard.tw/f/{forum_alias}/p/{post_id}",
                )
            )
        return refs

    def _fetch_list(self, session: DcardBrowserSession, url: str) -> list[DcardPostRef]:
        data = session.fetch_json(url)
        if isinstance(data, list):
            return self._parse_list(data)
        if isinstance(data, dict):
            items = data.get("items") or data.get("posts") or data.get("results") or []
            return self._parse_list(items)
        return []

    def collect_refs(self, session: DcardBrowserSession) -> list[DcardPostRef]:
        refs: dict[int, DcardPostRef] = {}

        for keyword in self.config.dcard_search_keywords:
            limit = min(100, max(10, self.config.max_search_pages * 10))
            url = f"{API_BASE}/search/posts?query={quote(keyword)}&limit={limit}"
            # 搜尋結果不用標題篩選（標題常沒寫 Lexus），抓內文後 fetch_post 會再做全文篩選
            try:
                for ref in self._fetch_list(session, url):
                    refs.setdefault(ref.post_id, ref)
            except Exception:
                pass
            time.sleep(max(self.config.request_delay_sec, 3.0))

        for forum in self.config.dcard_forums:
            before: int | None = None
            for _ in range(self.config.dcard_forum_pages):
                url = f"{API_BASE}/forums/{forum}/posts?popular=false&limit=30"
                if before:
                    url += f"&before={before}"
                try:
                    batch = self._fetch_list(session, url)
                except Exception:
                    break
                if not batch:
                    break
                for ref in batch:
                    if is_relevant(
                        ref.title,
                        self.config.relevance_keywords,
                        self.config.service_keywords,
                        aftersales_only=False,
                    ):
                        refs[ref.post_id] = ref
                before = batch[-1].post_id
                time.sleep(max(self.config.request_delay_sec, 2.5))

        return list(refs.values())

    def fetch_post(self, session: DcardBrowserSession, ref: DcardPostRef) -> dict | None:
        try:
            data = session.fetch_json(f"{API_BASE}/posts/{ref.post_id}")
        except Exception:
            return None

        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            return None

        title = data.get("title") or ref.title
        content = (data.get("content") or data.get("excerpt") or "").strip()
        if len(content) < 15:
            return None

        text = f"{title} {content}"
        if not is_relevant(
            text,
            self.config.relevance_keywords,
            self.config.service_keywords,
            aftersales_only=self.config.aftersales_only,
        ):
            return None

        return {
            "id": f"dcard_{ref.post_id}",
            "source": "Dcard",
            "board": ref.forum_name,
            "title": title,
            "content": content[:4000],
            "posted_at": data.get("createdAt"),
            "url": ref.url,
            "comment_count": data.get("commentCount", 0),
            "engagement": {
                "likes": data.get("likeCount", 0),
                "comments": data.get("commentCount", 0),
            },
        }

    def crawl(self) -> list[dict]:
        posts: list[dict] = []
        try:
            with DcardBrowserSession(self.config) as session:
                refs = self.collect_refs(session)
                print(f"      [Dcard] 候選文章 {len(refs)} 篇，最多抓取 {self.max_posts} 篇")
                # 抓到 max_posts 篇通過篩選的文章才停，而非只抓前 N 個候選
                for ref in refs:
                    if len(posts) >= self.max_posts:
                        break
                    post = self.fetch_post(session, ref)
                    if post:
                        posts.append(post)
                    time.sleep(self.config.request_delay_sec)
        except Exception as exc:
            raise RuntimeError(f"Dcard 爬蟲失敗（可能需使用可見瀏覽器通過 Cloudflare）：{exc}") from exc
        return posts
