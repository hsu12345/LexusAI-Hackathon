from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote

from .config import CrawlConfig
from .dcard import API_BASE
from .dcard_capture import DcardApiSniffer, finalize_capture
from .normalizer import is_relevant

SEARCH_PATHS = (
    "/search/posts",
    "/search",
)


def fetch_json_in_page(
    page,
    url: str,
    *,
    retries: int = 5,
    rate_state: dict[str, int] | None = None,
) -> Any | None:
    rate_state = rate_state if rate_state is not None else {}
    last_status = 0
    for attempt in range(retries):
        try:
            result = page.evaluate(
                """async (url) => {
                    const resp = await fetch(url, { credentials: 'include' });
                    const text = await resp.text();
                    return { status: resp.status, text };
                }""",
                url,
            )
        except Exception as exc:
            msg = str(exc)
            if "Execution context was destroyed" in msg or "Target closed" in msg:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                time.sleep(2 + attempt)
                continue
            raise
        last_status = int(result["status"])
        if last_status == 200:
            rate_state["consecutive_429"] = 0
            try:
                return json.loads(result["text"])
            except json.JSONDecodeError:
                return None
        if last_status in (429, 503):
            rate_state["consecutive_429"] = rate_state.get("consecutive_429", 0) + 1
            wait = min(90, 15 * (2**attempt))
            if rate_state["consecutive_429"] >= 3:
                wait = 90
            print(f"      [Dcard/API] 限流 {last_status}，等待 {wait}s…")
            time.sleep(wait)
            continue
        break
    print(f"      [Dcard/API] {last_status} {url[:90]}")
    return None


def _extract_items(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("posts", "items", "results", "data"):
        bucket = data.get(key)
        if isinstance(bucket, list):
            return [x for x in bucket if isinstance(x, dict)]
    if data.get("id") and data.get("title"):
        return [data]
    return []


def _is_post_candidate(item: dict) -> bool:
    title = item.get("title")
    pid = item.get("id")
    if not title or pid is None:
        return False
    if item.get("forumAlias") or item.get("forumName"):
        return True
    return str(pid).isdigit()


def collect_via_api(page, config: CrawlConfig, sniffer: DcardApiSniffer) -> None:
    """在已通過驗證的瀏覽器 session 內，直接分頁呼叫 Dcard API。"""
    max_posts = getattr(config, "max_dcard_articles", 200)
    delay = max(config.request_delay_sec, 2.0)
    rate_state: dict[str, int] = {"consecutive_429": 0}
    keywords = list(dict.fromkeys(config.dcard_search_keywords))[
        : getattr(config, "dcard_max_search_keywords", 8)
    ]
    forum_pages = max(
        getattr(config, "dcard_forum_pages", 5) + 3,
        max_posts // 12,
    )

    # 1) 汽車看板分頁（較不易觸發搜尋限流）
    for forum in config.dcard_forums:
        if len(sniffer.posts) >= max_posts * 3:
            break
        before: int | None = None
        for page_idx in range(forum_pages):
            url = f"{API_BASE}/forums/{forum}/posts?popular=false&limit=100"
            if before is not None:
                url += f"&before={before}"
            data = fetch_json_in_page(page, url, rate_state=rate_state)
            if not data:
                if rate_state.get("consecutive_429", 0) >= 3:
                    print(f"      [Dcard/API] 看板 {forum} 限流過重，改走搜尋")
                    break
                continue
            items = _extract_items(data)
            if not items:
                break
            for item in items:
                if _is_post_candidate(item):
                    sniffer.ingest_payload(item, url)
            before = items[-1].get("id")
            if not isinstance(before, int):
                try:
                    before = int(before)
                except (TypeError, ValueError):
                    break
            print(f"      [Dcard/API] 看板 {forum} 第 {page_idx + 1} 頁，累計 {len(sniffer.posts)} 篇")
            time.sleep(delay)

    # 2) 關鍵字搜尋
    for keyword in keywords:
        if len(sniffer.posts) >= max_posts * 3:
            break
        if rate_state.get("consecutive_429", 0) >= 5:
            print("      [Dcard/API] 搜尋 API 限流，略過剩餘關鍵字")
            break
        for path in SEARCH_PATHS:
            url = f"{API_BASE}{path}?query={quote(keyword)}&limit=100"
            data = fetch_json_in_page(page, url, rate_state=rate_state)
            if not data:
                continue
            items = _extract_items(data)
            added = 0
            for item in items:
                if _is_post_candidate(item):
                    sniffer.ingest_payload(item, url)
                    added += 1
            if added:
                print(f"      [Dcard/API] 搜尋「{keyword}」+{added} 篇（累計 {len(sniffer.posts)}）")
                break
        time.sleep(delay)

    # 3) 補全文：限流時少抓
    if rate_state.get("consecutive_429", 0) >= 3:
        print("      [Dcard/API] 略過補全文（避免 429）")
        return
    need_full: list[str] = []
    for pid, item in list(sniffer.posts.items()):
        body = (item.get("content") or item.get("excerpt") or "").strip()
        if len(body) < 40:
            need_full.append(pid)
    for pid in need_full[: min(40, max_posts // 2)]:
        url = f"{API_BASE}/posts/{pid}"
        data = fetch_json_in_page(page, url, rate_state=rate_state)
        if rate_state.get("consecutive_429", 0) >= 3:
            break
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            sniffer.ingest_payload(data, url)
        time.sleep(delay)


def filter_relevant_posts(sniffer: DcardApiSniffer, config: CrawlConfig) -> list[dict]:
    """先收集全部 API 文章，再依 Lexus 關鍵字篩選。"""
    return finalize_capture(sniffer, config)
