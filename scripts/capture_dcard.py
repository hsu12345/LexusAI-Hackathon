#!/usr/bin/env python
"""攔截 Dcard 網頁 API 封包，寫入 JSON。

若 Playwright 開 Edge 被擋（Sorry, you have been blocked），請改用：

  方案 A — HAR 匯入（最穩）：
    一般 Edge 開 dcard → F12 Network → 匯出 HAR →
    python scripts/import_dcard_har.py data/dcard_export.har

  方案 B — CDP 附加（連到你自己的 Edge）：
    msedge.exe --remote-debugging-port=9222
    python scripts/capture_dcard.py --cdp

  方案 C — Playwright（易被擋，不推薦）：
    python scripts/capture_dcard.py --interactive
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
from backend.crawler.dcard import DcardCrawler
from backend.crawler.normalizer import dedupe_posts, normalize_post

CRAWLED_PATH = ROOT / "data" / "crawled_posts.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Dcard API 封包攔截 → JSON")
    parser.add_argument("--max-dcard-articles", type=int, default=100)
    parser.add_argument("--dcard-cloudflare-wait", type=int, default=180)
    parser.add_argument("--aftersales-only", action="store_true")
    parser.add_argument("--no-merge", action="store_true", help="不合併進 crawled_posts.json")
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Playwright 互動模式（易被 Dcard 封鎖，不推薦）",
    )
    parser.add_argument(
        "--cdp",
        action="store_true",
        help="附加到已開啟的 Edge（需 --remote-debugging-port=9222）",
    )
    parser.add_argument("--cdp-url", type=str, default="http://127.0.0.1:9222")
    args = parser.parse_args()

    config = CrawlConfig(
        max_dcard_articles=args.max_dcard_articles,
        dcard_backend="capture",
        dcard_use_pttbrain=False,
        dcard_cloudflare_wait_sec=args.dcard_cloudflare_wait,
        dcard_capture_interactive=args.interactive,
        aftersales_only=args.aftersales_only,
    )

    if args.cdp:
        from backend.crawler.dcard_cdp import DcardCdpAutomator

        config.dcard_cdp_port = int(args.cdp_url.rsplit(":", 1)[-1])
        posts = DcardCdpAutomator(config).crawl()
    else:
        if not args.interactive:
            print("提示：若 Edge 顯示 blocked，請改用 HAR：scripts/import_dcard_har.py\n")
        posts = DcardCrawler(config).crawl()
    print(f"\n篩選後 Lexus 相關：{len(posts)} 篇")

    if args.no_merge:
        out = ROOT / "data" / "dcard_captured_posts.json"
        out.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已寫入 {out}")
        return

    existing: list[dict] = []
    if CRAWLED_PATH.exists():
        existing = json.loads(CRAWLED_PATH.read_text(encoding="utf-8"))
        existing = [p for p in existing if p.get("source") != "Dcard"]

    merged = dedupe_posts(existing + [normalize_post(p) for p in posts])
    CRAWLED_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    dcard_n = sum(1 for p in merged if p.get("source") == "Dcard")
    print(f"已合併 → {CRAWLED_PATH}（Dcard 共 {dcard_n} 篇，總計 {len(merged)} 篇）")


if __name__ == "__main__":
    main()
