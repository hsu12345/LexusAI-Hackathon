#!/usr/bin/env python
"""從 Edge DevTools 匯出的 HAR 檔匯入 Dcard API 資料。

步驟（不會被 Playwright 封鎖）：
  1. 用「一般方式」開 Edge，前往 https://www.dcard.tw
  2. F12 → Network（網路）→ 勾選 Preserve log
  3. 搜尋 lexus / 凌志，瀏覽 car 看板並捲動
  4. Network 列表右鍵 → Save all as HAR with content
  5. 存成 data/dcard_export.har
  6. python scripts/import_dcard_har.py data/dcard_export.har
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
from backend.crawler.dcard_har import import_har
from backend.crawler.normalizer import dedupe_posts, normalize_post

CRAWLED_PATH = ROOT / "data" / "crawled_posts.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Dcard HAR → JSON")
    parser.add_argument("har", type=str, help="HAR 檔路徑，例如 data/dcard_export.har")
    parser.add_argument("--max-dcard-articles", type=int, default=200)
    parser.add_argument("--aftersales-only", action="store_true")
    parser.add_argument("--no-merge", action="store_true")
    args = parser.parse_args()

    har_path = Path(args.har)
    if not har_path.exists():
        raise SystemExit(f"找不到 HAR：{har_path}")

    config = CrawlConfig(
        max_dcard_articles=args.max_dcard_articles,
        aftersales_only=args.aftersales_only,
    )
    posts = import_har(har_path, config)
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
