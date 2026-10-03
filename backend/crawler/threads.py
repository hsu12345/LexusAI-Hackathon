from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from .config import CrawlConfig
from .normalizer import is_relevant
from .stealth import apply_stealth, stealth_launch_args

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COOKIE_PATH = ROOT / "data" / "threads_cookies.json"
BASE_URL = "https://www.threads.net"

POST_LINK_RE = re.compile(r"/post/([A-Za-z0-9_-]+)")

# 貼文卡片渲染出來的文字大致長這樣（每行一個 DOM 節點的 innerText）：
#   使用者名稱 / 顯示名稱
#   相對時間（如 "6天"、"1天") 或絕對日期（"2026-7-19"）
#   ……貼文本文……
#   翻譯
#   讚數 / 留言數 / 轉發數 / 分享數（純數字，逐行）
# 以下規則用來把使用者名稱／時間／互動數字從本文中剝離。
USERNAME_LINE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
DATE_LINE_RE = re.compile(r"^(\d+[天小時分鐘週月年]|\d{4}-\d{1,2}-\d{1,2}|\d+[hdwm])$")
NUM_LINE_RE = re.compile(r"^[\d,]+$")


@dataclass
class ThreadsPostRef:
    post_id: str
    url: str
    text: str
    posted_at: str | None


class ThreadsBrowserSession:
    """透過 Playwright 開啟瀏覽器存取 Threads 搜尋結果。

    實測 Threads 網頁版的搜尋結果目前（2026 年）不需要登入即可瀏覽，因此預設走
    headless、免登入的公開瀏覽模式；若之後 Threads 又鎖回「需登入才能搜尋」，
    可用 `threads_require_login=True`（CLI: --threads-require-login）切換回
    「開可見瀏覽器等使用者手動登入 → 存 cookie → 之後重複使用」的備援流程。
    """

    def __init__(self, config: CrawlConfig):
        self.config = config
        self.cookie_path = Path(getattr(config, "threads_cookie_path", DEFAULT_COOKIE_PATH))
        self.headless = getattr(config, "threads_headless", True)
        self.require_login = getattr(config, "threads_require_login", False)
        self.login_wait_sec = getattr(config, "threads_login_wait_sec", 180)
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self) -> "ThreadsBrowserSession":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "args": stealth_launch_args(),
        }
        if getattr(self.config, "proxy", None):
            launch_kwargs["proxy"] = {"server": self.config.proxy}

        if getattr(self.config, "threads_use_edge", True):
            try:
                self._browser = self._playwright.chromium.launch(channel="msedge", **launch_kwargs)
            except Exception:
                self._browser = self._playwright.chromium.launch(**launch_kwargs)
        else:
            self._browser = self._playwright.chromium.launch(**launch_kwargs)

        self._context = self._browser.new_context(
            locale="zh-TW",
            viewport={"width": 1366, "height": 900},
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
        except Exception:
            pass
        finally:
            try:
                if self._browser:
                    self._browser.close()
            except Exception:
                pass
            if self._playwright:
                self._playwright.stop()

    def _is_logged_in(self) -> bool:
        assert self.page is not None
        try:
            # 未登入時頁面上會有「登入」連結／按鈕
            login_link = self.page.query_selector('a[href*="/login"]')
            return login_link is None
        except Exception:
            return False

    def _bootstrap_session(self) -> None:
        assert self.page is not None
        try:
            self.page.goto(BASE_URL, timeout=60000, wait_until="domcontentloaded")
            self.page.wait_for_timeout(1200)
        except Exception:
            pass

        if self._is_logged_in():
            print("[Threads] 偵測到已登入（沿用先前存下的 cookie）")
            return

        if not self.require_login:
            print("[Threads] 未登入，改用公開瀏覽模式抓取搜尋結果（不保證涵蓋所有內容）")
            return

        print(
            "[Threads] 已設定必須登入。請在剛開啟的瀏覽器視窗內手動完成登入，"
            f"完成後爬蟲會自動繼續（最多等待 {self.login_wait_sec} 秒）…"
        )
        waited = 0
        interval = 3
        while waited < self.login_wait_sec:
            time.sleep(interval)
            waited += interval
            if self._is_logged_in():
                print("[Threads] 偵測到已登入，繼續爬取…")
                return
        raise RuntimeError(
            f"等待手動登入逾時（{self.login_wait_sec} 秒）。"
            "請重新執行並於時限內於瀏覽器完成登入，登入狀態會存到 "
            f"{self.cookie_path} 供下次重複使用。"
        )


def _parse_card_text(text: str) -> tuple[str, str, dict[str, int]]:
    """把貼文卡片的 innerText 拆成 (title, content, engagement)。"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    numbers: list[int] = []
    while lines and NUM_LINE_RE.match(lines[-1]):
        numbers.append(int(lines.pop().replace(",", "")))
    numbers.reverse()

    if lines and lines[-1] == "翻譯":
        lines.pop()

    # 開頭通常是使用者名稱／顯示名稱／相對時間，非貼文本文
    while len(lines) > 1 and (USERNAME_LINE_RE.match(lines[0]) or DATE_LINE_RE.match(lines[0])):
        lines.pop(0)

    content = "\n".join(lines).strip()
    if not content:
        content = text.strip()
    title = content.splitlines()[0][:60] if content else text[:60]
    engagement = {
        "likes": numbers[0] if numbers else 0,
        "comments": numbers[1] if len(numbers) > 1 else 0,
    }
    return title, content[:4000], engagement


class ThreadsCrawler:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.max_posts = getattr(config, "max_threads_articles", max(15, config.max_articles // 3))
        self.scroll_rounds = getattr(config, "threads_scroll_rounds", 4)

    def _extract_refs(self, session: ThreadsBrowserSession) -> list[ThreadsPostRef]:
        page = session.page
        assert page is not None

        # 每捲動一次就收集一次，避免長列表被虛擬化回收後漏抓前面的貼文
        refs: dict[str, ThreadsPostRef] = {}
        for _ in range(self.scroll_rounds + 1):
            self._collect_visible(page, refs)
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(1000)
        return list(refs.values())

    def _collect_visible(self, page, refs: dict[str, ThreadsPostRef]) -> None:
        containers = page.query_selector_all('div[data-pressable-container="true"]')
        for container in containers:
            try:
                link_el = container.query_selector('a[href*="/post/"]')
                href = link_el.get_attribute("href") if link_el else None
                if not href:
                    continue
                match = POST_LINK_RE.search(href)
                if not match:
                    continue
                post_id = match.group(1)
                if post_id in refs:
                    continue

                text = (container.inner_text() or "").strip()
                if len(text) < 20:
                    continue

                time_el = container.query_selector("time")
                posted_at = time_el.get_attribute("datetime") if time_el else None

                refs[post_id] = ThreadsPostRef(
                    post_id=post_id,
                    url=urljoin(BASE_URL, href),
                    text=text,
                    posted_at=posted_at,
                )
            except Exception:
                continue

    def _search(self, session: ThreadsBrowserSession, keyword: str) -> list[ThreadsPostRef]:
        page = session.page
        assert page is not None
        url = f"{BASE_URL}/search?q={quote(keyword)}&serp_type=default"
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
        except Exception:
            return []
        # 搜尋結果載入時間不一，固定等 2.5 秒常抓到空頁；改成等到貼文連結出現
        try:
            page.wait_for_selector('a[href*="/post/"]', timeout=12000)
        except Exception:
            return []  # 查無結果或被要求登入
        page.wait_for_timeout(1000)
        return self._extract_refs(session)

    def _to_post(self, ref: ThreadsPostRef) -> dict | None:
        if not is_relevant(
            ref.text,
            self.config.relevance_keywords,
            self.config.service_keywords,
            aftersales_only=self.config.aftersales_only,
        ):
            return None

        title, content, engagement = _parse_card_text(ref.text)
        if len(content) < 10:
            return None

        return {
            "id": f"threads_{ref.post_id}",
            "source": "Threads",
            "board": None,
            "title": title,
            "content": content,
            "posted_at": ref.posted_at,
            "url": ref.url,
            "engagement": engagement,
            "comment_count": engagement.get("comments", 0),
        }

    def crawl(self) -> list[dict]:
        posts: dict[str, dict] = {}
        try:
            with ThreadsBrowserSession(self.config) as session:
                for keyword in self.config.threads_search_keywords:
                    try:
                        for ref in self._search(session, keyword):
                            post = self._to_post(ref)
                            if post:
                                posts[post["id"]] = post
                    except Exception as exc:
                        print(f"      [Threads] 關鍵字「{keyword}」略過：{exc}")
                        continue
                    time.sleep(self.config.request_delay_sec)
                    if len(posts) >= self.max_posts:
                        break
        except Exception as exc:
            raise RuntimeError(f"Threads 爬蟲失敗（頁面結構可能已變更）：{exc}") from exc
        return list(posts.values())[: self.max_posts]
