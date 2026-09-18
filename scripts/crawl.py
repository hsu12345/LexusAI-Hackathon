#!/usr/bin/env python
"""執行 Lexus 社群公開討論爬蟲。

用法：
  python scripts/crawl.py
  python scripts/crawl.py --ptt-only
  python scripts/crawl.py --dcard-only
  python scripts/crawl.py --max-articles 50 --max-search-pages 8
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
    parser.add_argument("--skip-dcard", action="store_true", help="跳過 Dcard")
    parser.add_argument("--dcard-headless", action="store_true", help="Dcard 使用 headless（可能被 Cloudflare 擋）")
    parser.add_argument("--aftersales-only", action="store_true", help="僅保留售後服務相關文章")
    parser.add_argument("--max-articles", type=int, default=80)
    parser.add_argument("--max-dcard-articles", type=int, default=25)
    parser.add_argument("--max-search-pages", type=int, default=5)
    parser.add_argument("--max-board-pages", type=int, default=15)
    parser.add_argument("--delay", type=float, default=1.2, help="請求間隔秒數")
    args = parser.parse_args()

    if args.ptt_only and args.dcard_only:
        parser.error("不可同時使用 --ptt-only 與 --dcard-only")

    config = CrawlConfig(
        max_articles=args.max_articles,
        max_dcard_articles=args.max_dcard_articles,
        max_search_pages=args.max_search_pages,
        max_board_pages=args.max_board_pages,
        request_delay_sec=args.delay,
        aftersales_only=args.aftersales_only,
        dcard_headless=args.dcard_headless,
    )

    result = run_crawl(
        config=config,
        include_ptt=not args.dcard_only,
        include_mobile01=not args.ptt_only and not args.dcard_only,
        include_dcard=not args.ptt_only and not args.skip_dcard,
    )
    print("\n來源統計：", result["meta"]["sources"])


if __name__ == "__main__":
    main()
