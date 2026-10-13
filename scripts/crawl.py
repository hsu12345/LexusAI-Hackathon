#!/usr/bin/env python
"""執行 Lexus 社群公開討論爬蟲。

用法：
  python scripts/crawl.py
  python scripts/crawl.py --ptt-only
  python scripts/crawl.py --dcard-only
  python scripts/crawl.py --mobile01-only
  python scripts/crawl.py --threads-only       # 只爬 Threads（免登入，headless 執行）
  python scripts/crawl.py --include-threads    # 完整爬取時一併加入 Threads
  python scripts/crawl.py --max-articles 300 --max-dcard-articles 100 --max-threads-articles 100
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.crawler.config import CrawlConfig
from backend.crawler.runner import run_crawl


def main() -> None:
    parser = argparse.ArgumentParser(description="LexusAI 社群爬蟲")
    parser.add_argument("--ptt-only", action="store_true", help="只爬 PTT")
    parser.add_argument("--dcard-only", action="store_true", help="只爬 Dcard")
    parser.add_argument("--mobile01-only", action="store_true", help="只爬 Mobile01")
    parser.add_argument("--threads-only", action="store_true", help="只爬 Threads（免登入公開瀏覽）")
    parser.add_argument(
        "--include-threads",
        action="store_true",
        help="完整爬取時一併加入 Threads（預設不包含，需手動指定）",
    )
    parser.add_argument("--skip-dcard", action="store_true", help="跳過 Dcard")
    parser.add_argument("--dcard-headless", action="store_true", help="Dcard 使用 headless（可能被 Cloudflare 擋）")
    parser.add_argument(
        "--dcard-backend",
        choices=["auto", "cdp", "capture", "pttbrain", "direct"],
        default="auto",
        help="Dcard：auto=CDP自動+鏡像、cdp=真實Edge自動、capture=Playwright、pttbrain、direct",
    )
    parser.add_argument("--dcard-auto", action="store_true", help="Dcard 使用真實 Edge CDP 全自動（推薦）")
    parser.add_argument("--dcard-pttbrain-only", action="store_true", help="等同 --dcard-backend pttbrain")
    parser.add_argument("--dcard-capture-only", action="store_true", help="等同 --dcard-backend capture（攔截 API 封包）")
    parser.add_argument("--dcard-direct-only", action="store_true", help="等同 --dcard-backend direct（DOM 舊版）")
    parser.add_argument("--dcard-pttbrain-pages", type=int, default=15, help="PTT Brain 每個論壇最多翻頁數")
    parser.add_argument(
        "--dcard-cloudflare-wait",
        type=int,
        default=180,
        help="等待 Cloudflare 驗證秒數（可見瀏覽器時手動點選）",
    )
    parser.add_argument(
        "--threads-require-login",
        action="store_true",
        help="強制要求登入 Threads 才爬（預設免登入公開瀏覽即可；此選項用於 Threads 未來鎖回登入時的備援）",
    )
    parser.add_argument(
        "--threads-show-browser",
        action="store_true",
        help="Threads 使用可見瀏覽器（除錯用，或搭配 --threads-require-login 手動登入）",
    )
    parser.add_argument("--aftersales-only", action="store_true", help="僅保留售後服務相關文章")
    parser.add_argument("--max-articles", type=int, default=500, help="PTT 最多抓取篇數")
    parser.add_argument("--ptt-search-pages", type=int, default=30, help="PTT 每個關鍵字搜尋頁數（每頁 20 篇）")
    parser.add_argument("--max-dcard-articles", type=int, default=200)
    parser.add_argument("--max-mobile01-articles", type=int, default=300)
    parser.add_argument("--max-threads-articles", type=int, default=200)
    parser.add_argument("--max-search-pages", type=int, default=10)
    parser.add_argument("--max-board-pages", type=int, default=30)
    parser.add_argument("--delay", type=float, default=1.2, help="請求間隔秒數")
    parser.add_argument(
        "--proxy",
        type=str,
        default=None,
        help="代理伺服器，如 http://user:pass@host:port 或 socks5://host:port（用於繞過 Mobile01 的 IP 封鎖）",
    )
    args = parser.parse_args()

    only_flags = [args.ptt_only, args.dcard_only, args.mobile01_only, args.threads_only]
    if sum(only_flags) > 1:
        parser.error("--ptt-only、--dcard-only、--mobile01-only、--threads-only 不可同時使用")
    only_backends = [args.dcard_pttbrain_only, args.dcard_capture_only, args.dcard_direct_only]
    if sum(only_backends) > 1:
        parser.error("--dcard-pttbrain-only / --dcard-capture-only / --dcard-direct-only 不可同時使用")

    dcard_backend = args.dcard_backend
    if args.dcard_pttbrain_only:
        dcard_backend = "pttbrain"
    if args.dcard_capture_only:
        dcard_backend = "capture"
    if args.dcard_direct_only:
        dcard_backend = "direct"
    if args.dcard_auto:
        dcard_backend = "cdp"

    config = CrawlConfig(
        max_articles=args.max_articles,
        max_dcard_articles=args.max_dcard_articles,
        max_threads_articles=args.max_threads_articles,
        max_mobile01_articles=args.max_mobile01_articles,
        max_search_pages=args.max_search_pages,
        max_board_pages=args.max_board_pages,
        ptt_search_pages=args.ptt_search_pages,
        request_delay_sec=args.delay,
        aftersales_only=args.aftersales_only,
        dcard_headless=args.dcard_headless,
        dcard_backend=dcard_backend,
        dcard_use_pttbrain=dcard_backend in ("auto", "pttbrain"),
        dcard_capture_path="data/dcard_api_capture.json",
        dcard_pttbrain_pages=args.dcard_pttbrain_pages,
        dcard_cloudflare_wait_sec=args.dcard_cloudflare_wait,
        threads_headless=not args.threads_show_browser,
        threads_require_login=args.threads_require_login,
        proxy=args.proxy,
    )

    any_only = args.ptt_only or args.dcard_only or args.mobile01_only or args.threads_only
    result = run_crawl(
        config=config,
        include_ptt=not any_only or args.ptt_only,
        include_mobile01=(not any_only or args.mobile01_only) and not args.dcard_only,
        include_dcard=(not any_only or args.dcard_only) and not args.skip_dcard,
        include_threads=args.threads_only or (not any_only and args.include_threads),
    )
    print("\n來源統計：", result["meta"]["sources"])


if __name__ == "__main__":
    main()
