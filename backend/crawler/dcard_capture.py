from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import CrawlConfig
from .dcard import DCARD_BASE, DcardBrowserSession
from .normalizer import is_relevant

ROOT = Path(__file__).resolve().parents[2]
CAPTURE_PATH = ROOT / "data" / "dcard_api_capture.json"


def is_dcard_api_url(url: str) -> bool:
    if "dcard.tw" not in url:
        return False
    markers = (
        "/service/api/",
        "/api/v2/",
        "/graphql",
        "search/posts",
        "/posts/",
        "/forums/",
    )
    return any(m in url for m in markers)


class DcardApiSniffer:
    """攔截或解析 Dcard API JSON，彙整文章。"""

    def __init__(self) -> None:
        self.posts: dict[str, dict[str, Any]] = {}
        self.hits: list[dict[str, Any]] = []
        self.samples: list[dict[str, Any]] = []

    @staticmethod
    def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id") or item.get("postId"),
            "title": item.get("title") or item.get("postTitle") or "",
            "content": item.get("content") or item.get("excerpt") or item.get("summary") or "",
            "excerpt": item.get("excerpt") or "",
            "forumAlias": item.get("forumAlias") or item.get("forum") or "",
            "forumName": item.get("forumName") or "",
            "createdAt": item.get("createdAt"),
            "likeCount": item.get("likeCount"),
            "commentCount": item.get("commentCount"),
            **{k: v for k, v in item.items() if k not in {"id", "title", "content"}},
        }

    @staticmethod
    def _post_key(item: dict[str, Any]) -> str | None:
        norm = DcardApiSniffer.normalize_item(item)
        post_id = norm.get("id")
        title = (norm.get("title") or "").strip()
        if post_id is None or not title:
            return None
        # 論壇 meta（UUID id、無內文）略過
        body = (norm.get("content") or norm.get("excerpt") or "").strip()
        has_forum = bool(norm.get("forumAlias") or norm.get("forumName"))
        has_engagement = norm.get("likeCount") is not None or norm.get("commentCount") is not None
        pid_str = str(post_id)
        if pid_str.isdigit() or has_forum or has_engagement or len(body) >= 8:
            return pid_str
        return None

    def _ingest_item(self, item: dict[str, Any], source_url: str) -> None:
        norm = self.normalize_item(item)
        pid = self._post_key(norm)
        if not pid:
            return
        prev = self.posts.get(pid)
        new_content = (norm.get("content") or norm.get("excerpt") or "").strip()
        prev_content = (prev.get("content") or prev.get("excerpt") or "").strip() if prev else ""
        if not prev or len(new_content) >= len(prev_content):
            merged = dict(prev or {})
            merged.update(norm)
            merged["_capture_url"] = source_url
            self.posts[pid] = merged

    def _walk(self, obj: Any, source_url: str, depth: int = 0) -> None:
        if depth > 14:
            return
        if isinstance(obj, dict):
            if self._post_key(self.normalize_item(obj)):
                self._ingest_item(obj, source_url)
            for value in obj.values():
                self._walk(value, source_url, depth + 1)
        elif isinstance(obj, list):
            for value in obj:
                self._walk(value, source_url, depth + 1)

    def ingest_payload(self, data: Any, source_url: str) -> None:
        if isinstance(data, dict):
            self._walk(data, source_url)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    self._ingest_item(item, source_url)

    def on_response(self, response) -> None:
        try:
            url = response.url
            if not is_dcard_api_url(url):
                return
            status = response.status
            if status != 200:
                self.hits.append({"url": url, "status": status, "added": 0})
                return
            try:
                data = response.json()
            except Exception:
                return
            if len(self.samples) < 5 and len(self.posts) == 0:
                preview = json.dumps(data, ensure_ascii=False)[:500]
                self.samples.append({"url": url, "preview": preview})
            before = len(self.posts)
            self.ingest_payload(data, url)
            added = len(self.posts) - before
            self.hits.append({"url": url, "status": status, "added": added, "total": len(self.posts)})
            if added:
                print(f"      [Dcard/Capture] +{added} 篇 ← {url.split('?')[0][-52:]}")
        except Exception:
            return


def _post_from_api(item: dict[str, Any], config: CrawlConfig) -> dict | None:
    title = (item.get("title") or "").strip()
    content = (item.get("content") or item.get("excerpt") or "").strip()
    # 搜尋 API 常只有 excerpt
    if len(content) < 8 and title:
        content = title
    if len(content) < 8:
        return None
    text = f"{title} {content}"
    if not is_relevant(
        text,
        config.relevance_keywords,
        config.service_keywords,
        aftersales_only=config.aftersales_only,
    ):
        return None
    forum_alias = item.get("forumAlias") or "car"
    post_id = str(item["id"])
    safe_id = re.sub(r"[^\w-]+", "_", post_id)
    return {
        "id": f"dcard_{safe_id}",
        "source": "Dcard",
        "board": item.get("forumName") or forum_alias,
        "title": title,
        "content": content[:4000],
        "posted_at": item.get("createdAt"),
        "url": f"{DCARD_BASE}/f/{forum_alias}/p/{post_id}",
        "comment_count": item.get("commentCount", 0),
        "engagement": {
            "likes": item.get("likeCount", 0),
            "comments": item.get("commentCount", 0),
        },
    }


def finalize_capture(sniffer: DcardApiSniffer, config: CrawlConfig) -> list[dict]:
    max_posts = getattr(config, "max_dcard_articles", 200)
    posts: list[dict] = []
    for item in sniffer.posts.values():
        post = _post_from_api(item, config)
        if post:
            posts.append(post)
        if len(posts) >= max_posts:
            break
    posts.sort(key=lambda p: p.get("posted_at") or "", reverse=True)
    return posts[:max_posts]


def save_capture(sniffer: DcardApiSniffer, path: Path = CAPTURE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "post_count": len(sniffer.posts),
        "api_hits": len(sniffer.hits),
        "posts": {str(k): v for k, v in sniffer.posts.items()},
        "samples": sniffer.samples[:5],
        "recent_hits": sniffer.hits[-20:],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class DcardCaptureCrawler:
    """開啟 Dcard 搜尋／看板頁，被動攔截 API 流量並輸出 JSON。"""

    def __init__(self, config: CrawlConfig):
        self.config = config
        self.max_posts = getattr(config, "max_dcard_articles", 200)
        self.capture_path = Path(getattr(config, "dcard_capture_path", CAPTURE_PATH))

    def _keywords(self) -> list[str]:
        limit = getattr(self.config, "dcard_max_search_keywords", 8)
        return list(dict.fromkeys(self.config.dcard_search_keywords))[:limit]

    def _browse_search(self, page, sniffer: DcardApiSniffer, keyword: str) -> None:
        page.goto(f"{DCARD_BASE}/search?query={quote(keyword)}", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        for i in range(self.config.dcard_search_scrolls + 1):
            page.mouse.wheel(0, 2600)
            page.wait_for_timeout(max(int(self.config.request_delay_sec * 1000), 1200))

    def _browse_forum(self, page, sniffer: DcardApiSniffer, forum: str) -> None:
        page.goto(f"{DCARD_BASE}/f/{forum}", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        for _ in range(self.config.dcard_forum_pages + 2):
            page.mouse.wheel(0, 2600)
            page.wait_for_timeout(max(int(self.config.request_delay_sec * 1000), 1200))

    def _interactive_wait(self, page, sniffer: DcardApiSniffer) -> None:
        print("\n" + "=" * 60)
        print("  [Dcard/Capture] 互動模式")
        print("  1. 請在 Edge 視窗完成 Cloudflare 驗證")
        print("  2. 自行搜尋 lexus / 凌志 / 瀏覽 car 看板並捲動")
        print("  3. 完成後回到此終端機按 Enter")
        print("=" * 60 + "\n")
        page.goto(f"{DCARD_BASE}/search?query=lexus", timeout=90000, wait_until="domcontentloaded")
        try:
            input(">>> 瀏覽完成後按 Enter 開始整理 JSON… ")
        except EOFError:
            time.sleep(30)
        from .dcard_api import collect_via_api

        collect_via_api(page, self.config, sniffer)

    def crawl(self, *, interactive: bool = False) -> list[dict]:
        sniffer = DcardApiSniffer()
        print("      [Dcard/Capture] 模式：攔截 /service/api/v2/ 流量 → JSON")

        with DcardBrowserSession(self.config) as session:
            page = session.page
            assert page is not None
            page.on("response", sniffer.on_response)

            if interactive:
                self._interactive_wait(page, sniffer)
            else:
                from .dcard_api import collect_via_api

                collect_via_api(page, self.config, sniffer)
                for keyword in self._keywords():
                    try:
                        self._browse_search(page, sniffer, keyword)
                    except Exception as exc:
                        print(f"      [Dcard/Capture] 搜尋「{keyword}」略過：{exc}")
                    time.sleep(max(self.config.request_delay_sec, 1.0))

                if len(sniffer.posts) < self.max_posts // 2:
                    for forum in self.config.dcard_forums:
                        try:
                            self._browse_forum(page, sniffer, forum)
                        except Exception as exc:
                            print(f"      [Dcard/Capture] 看板 {forum} 略過：{exc}")

        capture_file = save_capture(sniffer, self.capture_path)
        print(f"      [Dcard/Capture] 原始 API 資料 → {capture_file}（{len(sniffer.posts)} 篇）")
        return finalize_capture(sniffer, self.config)
