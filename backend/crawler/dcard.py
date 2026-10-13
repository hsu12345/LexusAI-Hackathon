from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import CrawlConfig
from .normalizer import is_relevant

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COOKIE_PATH = ROOT / "data" / "dcard_cookies.json"
API_BASE = "https://www.dcard.tw/service/api/v2"
DCARD_BASE = "https://www.dcard.tw"


@dataclass
class DcardPostRef:
    post_id: int
    title: str
    forum_alias: str
    forum_name: str
    url: str
    excerpt: str = ""


class DcardBrowserSession:
    """透過 Playwright 建立 Dcard session，優先 DOM 抓取，必要時才呼叫 API。"""

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
        from .stealth import apply_stealth, stealth_launch_args

        use_stealth = getattr(self.config, "dcard_stealth", False)
        launch_kwargs: dict[str, Any] = {"headless": self.headless}
        if use_stealth:
            launch_kwargs["args"] = stealth_launch_args()
        if getattr(self.config, "proxy", None):
            launch_kwargs["proxy"] = {"server": self.config.proxy}
        if getattr(self.config, "dcard_use_edge", True):
            try:
                self._browser = self._playwright.chromium.launch(channel="msedge", **launch_kwargs)
            except Exception:
                self._browser = self._playwright.chromium.launch(**launch_kwargs)
        else:
            self._browser = self._playwright.chromium.launch(**launch_kwargs)

        context_kwargs: dict[str, Any] = {"locale": "zh-TW", "viewport": {"width": 1366, "height": 768}}
        if use_stealth:
            context_kwargs["user_agent"] = self.config.user_agent
        self._context = self._browser.new_context(**context_kwargs)
        if use_stealth:
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

    def _is_cloudflare(self, title: str) -> bool:
        markers = ("請稍候", "Attention", "Just a moment", "Cloudflare", "驗證")
        return any(m in title for m in markers)

    def _bootstrap_session(self) -> None:
        assert self.page is not None
        self.page.goto(DCARD_BASE, timeout=90000, wait_until="domcontentloaded")
        interactive = getattr(self.config, "dcard_capture_interactive", False)
        max_wait = int(getattr(self.config, "dcard_cloudflare_wait_sec", 180))
        waited = 0
        while waited < max_wait:
            title = self.page.title()
            if not self._is_cloudflare(title):
                break
            if waited == 0:
                print(
                    "      [Dcard] 偵測到 Cloudflare 驗證。"
                    + ("請在開啟的瀏覽器完成驗證…" if not self.headless else " headless 模式易被擋，請勿加 --dcard-headless")
                )
            time.sleep(3)
            waited += 3
        if self._is_cloudflare(self.page.title()) and not interactive:
            raise RuntimeError(
                "Cloudflare 驗證未通過。請改用互動模式："
                "python scripts/capture_dcard.py --interactive"
            )
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
        self.dom_first = getattr(config, "dcard_dom_first", True)
        self.use_pttbrain = getattr(config, "dcard_use_pttbrain", True)
        self.backend = getattr(config, "dcard_backend", "auto")

    def _search_keywords(self) -> list[str]:
        limit = getattr(self.config, "dcard_max_search_keywords", 8)
        keywords = list(dict.fromkeys(self.config.dcard_search_keywords))
        return keywords[:limit]

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
                    url=f"{DCARD_BASE}/f/{forum_alias}/p/{post_id}",
                    excerpt=(item.get("excerpt") or item.get("content") or "")[:500],
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

    def _extract_search_dom(self, page) -> list[DcardPostRef]:
        rows = page.evaluate(
            """() => {
                const out = [];
                const seen = new Set();
                for (const a of document.querySelectorAll('a[href*="/p/"]')) {
                    const href = a.getAttribute('href') || '';
                    const m = href.match(/\\/f\\/([^/]+)\\/p\\/(\\d+)/);
                    if (!m || seen.has(m[2])) continue;
                    seen.add(m[2]);
                    const block = a.closest('article, li, div') || a;
                    const text = (block.innerText || a.innerText || '').trim();
                    const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);
                    const title = lines[0] || a.innerText.trim();
                    const excerpt = lines.slice(1).join(' ');
                    out.push({
                        post_id: Number(m[2]),
                        forum_alias: m[1],
                        title,
                        excerpt,
                        url: href.startsWith('http') ? href : 'https://www.dcard.tw' + href,
                    });
                }
                return out;
            }"""
        )
        refs: list[DcardPostRef] = []
        for row in rows:
            refs.append(
                DcardPostRef(
                    post_id=int(row["post_id"]),
                    title=row.get("title") or "",
                    forum_alias=row.get("forum_alias") or "unknown",
                    forum_name=row.get("forum_alias") or "unknown",
                    url=row.get("url") or "",
                    excerpt=row.get("excerpt") or "",
                )
            )
        return refs

    def _search_page_refs(self, session: DcardBrowserSession, keyword: str) -> list[DcardPostRef]:
        page = session.page
        assert page is not None
        page.goto(f"{DCARD_BASE}/search?query={quote(keyword)}", timeout=60000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector('a[href*="/p/"]', timeout=20000)
        except Exception:
            return []

        found: dict[int, DcardPostRef] = {}
        for _ in range(self.config.dcard_search_scrolls + 1):
            for ref in self._extract_search_dom(page):
                if ref.post_id not in found or (not found[ref.post_id].title and ref.title):
                    found[ref.post_id] = ref
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(1200)
        return list(found.values())

    def _scrape_post_dom(self, session: DcardBrowserSession, ref: DcardPostRef) -> tuple[str, str] | None:
        page = session.page
        assert page is not None
        try:
            page.goto(ref.url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            data = page.evaluate(
                """() => {
                    const title = document.querySelector('h1')?.innerText?.trim()
                        || document.querySelector('[data-testid="post-title"]')?.innerText?.trim()
                        || document.title;
                    const selectors = [
                        '[data-testid="post-content"]',
                        'article',
                        'main',
                    ];
                    let content = '';
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText && el.innerText.length > content.length) {
                            content = el.innerText;
                        }
                    }
                    return { title, content: (content || '').trim() };
                }"""
            )
            title = (data.get("title") or ref.title or "").strip()
            content = (data.get("content") or ref.excerpt or "").strip()
            if len(content) < 15:
                return None
            return title, content[:4000]
        except Exception:
            return None

    def collect_refs(self, session: DcardBrowserSession) -> list[DcardPostRef]:
        refs: dict[int, DcardPostRef] = {}

        for keyword in self._search_keywords():
            try:
                for ref in self._search_page_refs(session, keyword):
                    refs.setdefault(ref.post_id, ref)
            except Exception as exc:
                print(f"      [Dcard] 關鍵字「{keyword}」略過：{exc}")
            time.sleep(max(self.config.request_delay_sec, 2.0))

        if len(refs) < self.max_posts // 2:
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
                    time.sleep(max(self.config.request_delay_sec, 2.0))

        return list(refs.values())

    def _build_post(self, ref: DcardPostRef, title: str, content: str, extra: dict | None = None) -> dict | None:
        text = f"{title} {content}"
        if not is_relevant(
            text,
            self.config.relevance_keywords,
            self.config.service_keywords,
            aftersales_only=self.config.aftersales_only,
        ):
            return None
        extra = extra or {}
        return {
            "id": f"dcard_{ref.post_id}",
            "source": "Dcard",
            "board": extra.get("forumName") or ref.forum_name,
            "title": title,
            "content": content[:4000],
            "posted_at": extra.get("createdAt"),
            "url": ref.url,
            "comment_count": extra.get("commentCount", 0),
            "engagement": {
                "likes": extra.get("likeCount", 0),
                "comments": extra.get("commentCount", 0),
            },
        }

    def fetch_post(self, session: DcardBrowserSession, ref: DcardPostRef) -> dict | None:
        title = ref.title
        content = ref.excerpt

        if self.dom_first:
            scraped = self._scrape_post_dom(session, ref)
            if scraped:
                title, content = scraped
                if len(content) >= 15:
                    return self._build_post(ref, title, content)

        if len((content or "").strip()) >= 40 and title:
            post = self._build_post(ref, title, content)
            if post:
                return post

        try:
            data = session.fetch_json(f"{API_BASE}/posts/{ref.post_id}")
        except Exception:
            return None

        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            return None

        title = data.get("title") or ref.title
        content = (data.get("content") or data.get("excerpt") or ref.excerpt or "").strip()
        if len(content) < 15:
            return None
        return self._build_post(ref, title, content, extra=data)

    def _crawl_pttbrain(self) -> list[dict]:
        from .dcard_pttbrain import PttBrainCrawler

        print("      [Dcard] 嘗試 PTT Brain 鏡像（免 Cloudflare）…")
        posts = PttBrainCrawler(self.config).crawl()
        print(f"      [Dcard/PTTBrain] 取得 {len(posts)} 篇")
        return posts

    def _crawl_direct_dom(self) -> list[dict]:
        posts: list[dict] = []
        seen_ids: set[str] = set()
        with DcardBrowserSession(self.config) as session:
            refs = self.collect_refs(session)
            print(f"      [Dcard/DOM] 候選 {len(refs)} 篇，目標 {self.max_posts} 篇")
            for ref in refs:
                if len(posts) >= self.max_posts:
                    break
                post = self.fetch_post(session, ref)
                if post and post["id"] not in seen_ids:
                    seen_ids.add(post["id"])
                    posts.append(post)
                time.sleep(max(self.config.request_delay_sec, 0.8))
        return posts

    def _crawl_capture(self) -> list[dict]:
        from .dcard_capture import DcardCaptureCrawler

        interactive = getattr(self.config, "dcard_capture_interactive", False)
        return DcardCaptureCrawler(self.config).crawl(interactive=interactive)

    def crawl(self) -> list[dict]:
        posts: list[dict] = []
        seen: set[str] = set()

        use_pttbrain = self.backend in ("auto", "pttbrain") and self.use_pttbrain
        use_capture = self.backend in ("auto", "capture")
        use_cdp_auto = self.backend in ("auto", "cdp") or getattr(self.config, "dcard_cdp_auto", False)
        use_direct_dom = self.backend == "direct"

        if use_pttbrain:
            try:
                for post in self._crawl_pttbrain():
                    if post["id"] not in seen:
                        seen.add(post["id"])
                        posts.append(post)
            except Exception as exc:
                print(f"      [Dcard/PTTBrain] 跳過：{exc}")

        if len(posts) < self.max_posts and use_cdp_auto:
            try:
                from .dcard_cdp import DcardCdpAutomator

                print("      [Dcard] 自動模式：真實 Edge + CDP 攔截 API…")
                for post in DcardCdpAutomator(self.config).crawl():
                    if post["id"] in seen:
                        continue
                    seen.add(post["id"])
                    posts.append(post)
                    if len(posts) >= self.max_posts:
                        break
            except Exception as exc:
                print(f"      [Dcard/Auto] 中止：{exc}")

        if len(posts) < self.max_posts and use_capture and not use_cdp_auto:
            try:
                for post in self._crawl_capture():
                    if post["id"] in seen:
                        continue
                    seen.add(post["id"])
                    posts.append(post)
                    if len(posts) >= self.max_posts:
                        break
            except Exception as exc:
                if not posts:
                    raise RuntimeError(
                        f"Dcard 封包攔截失敗（可改 --dcard-auto 或 HAR 匯入）：{exc}"
                    ) from exc
                print(f"      [Dcard/Capture] 中止：{exc}")

        if len(posts) < self.max_posts and use_direct_dom:
            try:
                for post in self._crawl_direct_dom():
                    if post["id"] in seen:
                        continue
                    seen.add(post["id"])
                    posts.append(post)
                    if len(posts) >= self.max_posts:
                        break
            except Exception as exc:
                if not posts:
                    raise RuntimeError(f"Dcard DOM 爬蟲失敗：{exc}") from exc
                print(f"      [Dcard/DOM] 中止：{exc}")

        return posts[: self.max_posts]
