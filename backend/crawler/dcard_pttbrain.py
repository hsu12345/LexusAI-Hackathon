from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin

from .config import CrawlConfig
from .normalizer import is_relevant

PTTBRAIN_BASE = "https://www.pttbrain.com"
# Dcard 汽車看板（PTT Brain 鏡像）；參考 https://github.com/enjuichang/Dcard-Crawler
DEFAULT_FORUM_IDS = [
    "1ce3ebca-8701-42d5-b14c-076fc629bc8e",  # 汽車
]


@dataclass
class PttBrainRef:
    title: str
    content: str
    url: str
    post_id: str


class PttBrainCrawler:
    """透過 PTT Brain 鏡像站抓取 Dcard 文章，避開 Dcard Cloudflare。

    思路參考 enjuichang/Dcard-Crawler，改為：
    - 使用 Playwright（與專案一致，免 Selenium / chromedriver）
    - 從列表頁直接解析標題／摘要，減少逐篇點進點出
    """

    def __init__(self, config: CrawlConfig):
        self.config = config
        self.max_posts = getattr(config, "max_dcard_articles", 200)
        self.forum_ids = getattr(config, "dcard_pttbrain_forums", DEFAULT_FORUM_IDS)
        self.max_pages = getattr(config, "dcard_pttbrain_pages", 15)

    def _extract_list_items(self, page) -> list[dict[str, str]]:
        return page.evaluate(
            """() => {
                const rows = [];
                const items = document.querySelectorAll('a.item, .ui.selection.list a.item, a[href*="/dcard/"]');
                for (const a of items) {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || a.textContent || '').trim();
                    if (!href || !text || text.length < 4) continue;
                    rows.push({ href, text });
                }
                return rows;
            }"""
        )

    def _parse_item(self, href: str, text: str) -> PttBrainRef | None:
        url = urljoin(PTTBRAIN_BASE, href)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        title = lines[0] if lines else text[:80]
        content = " ".join(lines[1:]) if len(lines) > 1 else text
        post_id = re.sub(r"[^\w-]+", "_", href.strip("/").split("/")[-1]) or str(abs(hash(url)))
        return PttBrainRef(title=title, content=content[:4000], url=url, post_id=post_id)

    def _to_post(self, ref: PttBrainRef) -> dict | None:
        text = f"{ref.title} {ref.content}"
        if not is_relevant(
            text,
            self.config.relevance_keywords,
            self.config.service_keywords,
            aftersales_only=self.config.aftersales_only,
        ):
            return None
        if len(ref.content.strip()) < 8 and len(ref.title.strip()) < 8:
            return None
        content = ref.content if len(ref.content.strip()) >= 15 else ref.title
        return {
            "id": f"dcard_pb_{ref.post_id}",
            "source": "Dcard",
            "board": "PTTBrain/汽車",
            "title": ref.title[:200],
            "content": content[:4000],
            "posted_at": None,
            "url": ref.url,
            "comment_count": 0,
            "engagement": {"likes": 0, "comments": 0},
        }

    def _click_next_page(self, page) -> bool:
        for selector in [
            'a[aria-label="Next item"]',
            "text=⟩",
            ".ui.pagination.menu a:last-child",
        ]:
            try:
                loc = page.locator(selector).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=3000)
                    page.wait_for_timeout(1200)
                    return True
            except Exception:
                continue
        return False

    def crawl(self) -> list[dict]:
        from playwright.sync_api import sync_playwright

        posts: list[dict] = []
        seen: set[str] = set()

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=getattr(self.config, "dcard_headless", True))
                page = browser.new_page(locale="zh-TW")
                for forum_id in self.forum_ids:
                    if len(posts) >= self.max_posts:
                        break
                    forum_url = f"{PTTBRAIN_BASE}/dcard/forum/{forum_id}"
                    print(f"      [Dcard/PTTBrain] 論壇 {forum_id[:8]}…")
                    try:
                        page.goto(forum_url, timeout=45000, wait_until="domcontentloaded")
                        page.wait_for_timeout(1500)
                    except Exception as exc:
                        print(f"      [Dcard/PTTBrain] 無法開啟論壇：{exc}")
                        continue

                    for page_idx in range(self.max_pages):
                        if len(posts) >= self.max_posts:
                            break
                        items = self._extract_list_items(page)
                        added = 0
                        for item in items:
                            ref = self._parse_item(item.get("href", ""), item.get("text", ""))
                            if not ref or ref.url in seen:
                                continue
                            seen.add(ref.url)
                            post = self._to_post(ref)
                            if post:
                                posts.append(post)
                                added += 1
                        print(f"      [Dcard/PTTBrain] 第 {page_idx + 1} 頁 +{added} 篇（累計 {len(posts)}）")
                        if not self._click_next_page(page):
                            break
                        time.sleep(max(self.config.request_delay_sec, 0.8))
                browser.close()
        except Exception as exc:
            print(f"      [Dcard/PTTBrain] 中止：{exc}")
        return posts
