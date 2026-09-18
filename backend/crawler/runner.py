from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CrawlConfig
from .http_client import RateLimitedClient
from .mobile01 import Mobile01Crawler
from .normalizer import dedupe_posts, normalize_post
from .ptt import PttCrawler

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CRAWLED_PATH = DATA_DIR / "crawled_posts.json"
META_PATH = DATA_DIR / "crawl_meta.json"


def run_crawl(
    config: CrawlConfig | None = None,
    *,
    include_ptt: bool = True,
    include_mobile01: bool = True,
    include_dcard: bool = True,
) -> dict[str, Any]:
    config = config or CrawlConfig()
    client = RateLimitedClient(config)

    ptt_raw: list[dict] = []
    m01_raw: list[dict] = []
    dcard_raw: list[dict] = []

    step = 1
    total_steps = sum([include_ptt, include_mobile01, include_dcard, 2])

    if include_ptt:
        print(f"[{step}/{total_steps}] 開始爬取 PTT…")
        ptt = PttCrawler(client, config)
        ptt_raw = ptt.crawl()
        print(f"      PTT 取得 {len(ptt_raw)} 篇")
        step += 1

    if include_mobile01:
        print(f"[{step}/{total_steps}] 開始爬取 Mobile01…")
        try:
            m01 = Mobile01Crawler(client, config)
            m01_raw = m01.crawl()
            print(f"      Mobile01 取得 {len(m01_raw)} 篇")
        except Exception as exc:
            print(f"      Mobile01 跳過：{exc}")
        step += 1

    if include_dcard:
        print(f"[{step}/{total_steps}] 開始爬取 Dcard（Playwright）…")
        try:
            from .dcard import DcardCrawler

            dcard = DcardCrawler(config)
            dcard_raw = dcard.crawl()
            print(f"      Dcard 取得 {len(dcard_raw)} 篇")
        except Exception as exc:
            print(f"      Dcard 跳過：{exc}")
        step += 1

    print(f"[{step}/{total_steps}] 正規化與去重…")
    normalized = [normalize_post(p) for p in ptt_raw + m01_raw + dcard_raw]

    # 部分爬取時保留既有資料，避免覆蓋
    existing: list[dict] = []
    if CRAWLED_PATH.exists() and not (include_ptt and include_mobile01 and include_dcard):
        try:
            with CRAWLED_PATH.open(encoding="utf-8") as f:
                existing = json.load(f)
            existing = [p for p in existing if "示範" not in p.get("source", "")]
        except Exception:
            existing = []

    merged = dedupe_posts(existing + normalized)

    if len(merged) < 8:
        sample_path = DATA_DIR / "sample_posts.json"
        if sample_path.exists():
            with sample_path.open(encoding="utf-8") as f:
                sample_raw = json.load(f)
            sample_tagged = []
            for item in sample_raw:
                tagged = dict(item)
                tagged["source"] = tagged.get("source", "Sample") + "（示範）"
                sample_tagged.append(tagged)
            merged = dedupe_posts(merged + sample_tagged)

    print(f"[{step + 1}/{total_steps}] 寫入資料檔…")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CRAWLED_PATH.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    meta = {
        "crawled_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "total_posts": len(merged),
        "sources": {
            "PTT": sum(1 for p in merged if p.get("source") == "PTT"),
            "Mobile01": sum(1 for p in merged if p.get("source") == "Mobile01"),
            "Dcard": sum(1 for p in merged if p.get("source") == "Dcard"),
            "Sample": sum(1 for p in merged if "示範" in p.get("source", "")),
        },
        "real_posts": sum(1 for p in merged if "example" not in (p.get("url") or "")),
    }
    with META_PATH.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"完成：共 {len(merged)} 篇 → {CRAWLED_PATH}")

    print("執行 NLP 分析…")
    try:
        from backend.app.services.analysis_runner import run_analysis

        analysis = run_analysis(save=True)
        report = analysis["report"]
        print(
            f"      分析完成：{analysis['post_count']} 篇，"
            f"平均風險 {report['avg_churn_risk']} → data/analysis_report.json"
        )
    except Exception as exc:
        print(f"      分析略過：{exc}")

    return {"posts": merged, "meta": meta, "path": str(CRAWLED_PATH)}
