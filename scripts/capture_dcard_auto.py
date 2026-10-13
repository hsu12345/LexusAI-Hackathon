#!/usr/bin/env python
"""Dcard 全自動抓取（真實 Edge + CDP，非 Playwright launch）。

用法：
  python scripts/capture_dcard_auto.py
  python scripts/capture_dcard_auto.py --max-dcard-articles 100

首次若被 Cloudflare 擋，請在跳出的 Edge 手動驗證一次；
profile 會存到 data/dcard_edge_profile，之後可全自動。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.crawler.config import CrawlConfig
from backend.crawler.dcard_cdp import DcardCdpAutomator
from backend.crawler.normalizer import dedupe_posts, normalize_post

CRAWLED_PATH = ROOT / "data" / "crawled_posts.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Dcard 自動 CDP 抓取")
    parser.add_argument("--max-dcard-articles", type=int, default=100)
    parser.add_argument("--delay", type=float, default=2.5, help="API 請求間隔（秒）")
    parser.add_argument("--aftersales-only", action="store_true")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--keep-edge", action="store_true", help="結束後不關 Edge")
    parser.add_argument(
        "--init-profile",
        action="store_true",
        help="首次使用：只開 Edge 手動通過驗證（只需做一次）",
    )
    args = parser.parse_args()

    config = CrawlConfig(
        max_dcard_articles=args.max_dcard_articles,
        aftersales_only=args.aftersales_only,
        dcard_backend="cdp",
        request_delay_sec=args.delay,
        dcard_forum_pages=max(8, args.max_dcard_articles // 15),
    )

    automator = DcardCdpAutomator(config)
    if args.init_profile:
        automator.init_profile()
        print("\n初始化完成。下次執行：python scripts/capture_dcard_auto.py")
        return

    posts = automator.crawl(keep_edge=args.keep_edge)
    print(f"\n篩選後 Lexus 相關：{len(posts)} 篇")

    if args.no_merge:
        out = ROOT / "data" / "dcard_captured_posts.json"
        out.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已寫入 {out}")
        return

    existing: list[dict] = []
    if CRAWLED_PATH.exists():
        existing = json.loads(CRAWLED_PATH.read_text(encoding="utf-8"))

    merged = dedupe_posts(existing + [normalize_post(p) for p in posts])
    CRAWLED_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    dcard_n = sum(1 for p in merged if p.get("source") == "Dcard")
    print(f"已合併 → {CRAWLED_PATH}（Dcard 共 {dcard_n} 篇，總計 {len(merged)} 篇）")


if __name__ == "__main__":
    main()
