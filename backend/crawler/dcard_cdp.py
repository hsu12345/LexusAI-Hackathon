from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .config import CrawlConfig
from .dcard import DCARD_BASE
from .dcard_api import collect_via_api
from .dcard_capture import DcardApiSniffer, finalize_capture, save_capture

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = ROOT / "data" / "dcard_edge_profile"
DEFAULT_PORT = 9222


def _edge_paths() -> list[Path]:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    return [p for p in candidates if p.exists()]


def _cdp_ready(port: int) -> bool:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def start_edge_cdp(
    *,
    profile_dir: Path = DEFAULT_PROFILE,
    port: int = DEFAULT_PORT,
    start_url: str = DCARD_BASE,
) -> subprocess.Popen[Any] | None:
    """以真實 Edge（非 Playwright launch）開啟 CDP，較不易被 Dcard 封鎖。"""
    if _cdp_ready(port):
        print(f"      [Dcard/Auto] Edge CDP 已在 port {port} 運行")
        return None

    edge = next(iter(_edge_paths()), None)
    if not edge:
        raise RuntimeError("找不到 msedge.exe，請確認已安裝 Microsoft Edge")

    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        str(edge),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        start_url,
    ]
    print(f"      [Dcard/Auto] 啟動 Edge → {profile_dir.name} (port {port})")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(40):
        if _cdp_ready(port):
            time.sleep(1.5)
            return proc
        time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("Edge CDP 啟動逾時")


def _is_blocked(page) -> bool:
    try:
        title = (page.title() or "").lower()
        if "blocked" in title or "attention" in title:
            return True
        body = page.content().lower()
        return "you have been blocked" in body or "unable to access dcard" in body
    except Exception:
        return False


def _wait_dcard_ready(page, config: CrawlConfig) -> None:
    max_wait = int(getattr(config, "dcard_cloudflare_wait_sec", 180))
    waited = 0
    while waited < max_wait:
        if not _is_blocked(page):
            title = (page.title() or "").lower()
            if "dcard" in title or "搜尋" in title or "car" in page.url:
                return
        if waited == 0:
            print(
                "      [Dcard/Auto] 若看到 Cloudflare／blocked，請在此 Edge 視窗手動完成一次"
                "（之後 profile 會記住，可全自動）"
            )
        time.sleep(3)
        waited += 3
    if _is_blocked(page):
        raise RuntimeError(
            "Dcard 仍顯示 blocked。請關閉 Edge，刪除 data/dcard_edge_profile 後重試，"
            "或先用一般 Edge 登入 dcard 再跑。"
        )


class DcardCdpAutomator:
    """真實 Edge + CDP 附加 + 自動瀏覽 + API 封包攔截。"""

    def __init__(self, config: CrawlConfig):
        self.config = config
        self.port = int(getattr(config, "dcard_cdp_port", DEFAULT_PORT))
        self.profile_dir = Path(getattr(config, "dcard_edge_profile", DEFAULT_PROFILE))
        self.capture_path = Path(getattr(config, "dcard_capture_path", "data/dcard_api_capture.json"))
        self._edge_proc: subprocess.Popen[Any] | None = None

    def _keywords(self) -> list[str]:
        limit = int(getattr(self.config, "dcard_max_search_keywords", 8))
        return list(dict.fromkeys(self.config.dcard_search_keywords))[:limit]

    def _bind_sniffer(self, context, sniffer: DcardApiSniffer) -> None:
        def on_page(page) -> None:
            page.on("response", sniffer.on_response)

        context.on("page", on_page)
        for pg in context.pages:
            on_page(pg)

    def _browse_search(self, page, sniffer: DcardApiSniffer, keyword: str) -> None:
        page.goto(f"{DCARD_BASE}/search?query={quote(keyword)}", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        if _is_blocked(page):
            _wait_dcard_ready(page, self.config)
        scrolls = self.config.dcard_search_scrolls + 1
        for i in range(scrolls):
            page.mouse.wheel(0, 2600)
            page.wait_for_timeout(max(int(self.config.request_delay_sec * 1000), 1000))
        print(f"      [Dcard/Auto] 搜尋「{keyword}」完成，累計 {len(sniffer.posts)} 篇 API")

    def _browse_forum(self, page, sniffer: DcardApiSniffer, forum: str) -> None:
        page.goto(f"{DCARD_BASE}/f/{forum}", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        for _ in range(self.config.dcard_forum_pages + 2):
            page.mouse.wheel(0, 2600)
            page.wait_for_timeout(max(int(self.config.request_delay_sec * 1000), 1000))
        print(f"      [Dcard/Auto] 看板 {forum} 完成，累計 {len(sniffer.posts)} 篇 API")

    def _fill_content(self, page, sniffer: DcardApiSniffer) -> None:
        need: list[str] = []
        for pid, item in sniffer.posts.items():
            text = (item.get("content") or item.get("excerpt") or "").strip()
            if len(text) < 40:
                need.append(pid)
        for pid in need[: min(30, getattr(self.config, "max_dcard_articles", 200))]:
            alias = sniffer.posts[pid].get("forumAlias") or "car"
            if pid.isdigit():
                page.goto(f"{DCARD_BASE}/f/{alias}/p/{pid}", timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(900)

    def init_profile(self) -> None:
        """首次使用：只開 Edge 讓使用者手動通過驗證並瀏覽，建立可信 profile。"""
        self._edge_proc = start_edge_cdp(profile_dir=self.profile_dir, port=self.port, start_url=f"{DCARD_BASE}/search?query=lexus")
        print("\n" + "=" * 60)
        print("  [Dcard/Auto] Profile 初始化")
        print("  1. 在 Edge 完成 Cloudflare／登入（若需要）")
        print("  2. 搜尋 lexus、瀏覽 car 看板")
        print("  3. 完成後按 Enter 關閉（profile 會保留供下次全自動）")
        print("=" * 60 + "\n")
        try:
            input(">>> 按 Enter 結束初始化… ")
        except EOFError:
            time.sleep(60)
        if self._edge_proc:
            self._edge_proc.terminate()
        ready = self.profile_dir / ".profile_ready"
        ready.write_text("ok", encoding="utf-8")
        print(f"      [Dcard/Auto] Profile 就緒 → {self.profile_dir}")

    def crawl(self, *, keep_edge: bool = False) -> list[dict]:
        from playwright.sync_api import sync_playwright

        sniffer = DcardApiSniffer()
        cdp_url = f"http://127.0.0.1:{self.port}"

        self._edge_proc = start_edge_cdp(profile_dir=self.profile_dir, port=self.port)

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            self._bind_sniffer(context, sniffer)

            page.goto(DCARD_BASE, timeout=90000, wait_until="domcontentloaded")
            _wait_dcard_ready(page, self.config)

            # 主力：在瀏覽器 session 內直接呼叫 API（比純封包攔截可靠）
            print("      [Dcard/Auto] 開始 API 分頁抓取…")
            collect_via_api(page, self.config, sniffer)

            for keyword in self._keywords():
                try:
                    self._browse_search(page, sniffer, keyword)
                except Exception as exc:
                    print(f"      [Dcard/Auto] 搜尋「{keyword}」略過：{exc}")
                time.sleep(max(self.config.request_delay_sec, 1.0))

            if len(sniffer.posts) < getattr(self.config, "max_dcard_articles", 200) // 2:
                for forum in self.config.dcard_forums:
                    try:
                        self._browse_forum(page, sniffer, forum)
                    except Exception as exc:
                        print(f"      [Dcard/Auto] 看板 {forum} 略過：{exc}")

            self._fill_content(page, sniffer)
            browser.close()

        if self._edge_proc and not keep_edge:
            self._edge_proc.terminate()

        out = save_capture(sniffer, self.capture_path)
        print(f"      [Dcard/Auto] 原始 API → {out}（{len(sniffer.posts)} 篇）")
        if not sniffer.posts:
            debug = ROOT / "data" / "dcard_api_debug.json"
            debug.write_text(
                json.dumps({"api_hits": sniffer.hits[-80:], "hint": "若 hits 為空，Edge 可能仍被 blocked；請跑 --init-profile"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"      [Dcard/Auto] 未取得文章，除錯資訊 → {debug}")
            print("      建議：python scripts/capture_dcard_auto.py --init-profile")
        return finalize_capture(sniffer, self.config)
