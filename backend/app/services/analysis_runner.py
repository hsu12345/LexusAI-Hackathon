from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .insight import build_market_report
from .nlp_analyzer import analyze_posts

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
CRAWLED_PATH = DATA_DIR / "crawled_posts.json"
SAMPLE_PATH = DATA_DIR / "sample_posts.json"
ANALYZED_PATH = DATA_DIR / "analyzed_posts.json"
REPORT_PATH = DATA_DIR / "analysis_report.json"


def load_posts() -> tuple[list[dict], str]:
    if CRAWLED_PATH.exists():
        path = CRAWLED_PATH
        source = "crawled"
    else:
        path = SAMPLE_PATH
        source = "sample"
    with path.open(encoding="utf-8") as f:
        return json.load(f), source


def run_analysis(save: bool = True) -> dict[str, Any]:
    posts, data_source = load_posts()
    analyzed = analyze_posts(posts)
    report = build_market_report(analyzed)

    result = {
        "analyzed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "data_source": data_source,
        "post_count": len(analyzed),
        "posts": [p.model_dump() for p in analyzed],
        "report": report.model_dump(),
    }

    if save:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with ANALYZED_PATH.open("w", encoding="utf-8") as f:
            json.dump(result["posts"], f, ensure_ascii=False, indent=2)
        with REPORT_PATH.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "analyzed_at": result["analyzed_at"],
                    "data_source": result["data_source"],
                    "post_count": result["post_count"],
                    "report": result["report"],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    return result


def load_cached_analysis() -> dict[str, Any] | None:
    """Return pre-computed analysis from disk (fast path for dashboard)."""
    if not ANALYZED_PATH.exists() or not REPORT_PATH.exists():
        return None
    with ANALYZED_PATH.open(encoding="utf-8") as f:
        posts = json.load(f)
    with REPORT_PATH.open(encoding="utf-8") as f:
        meta = json.load(f)
    return {
        "analyzed_at": meta.get("analyzed_at"),
        "data_source": meta.get("data_source"),
        "post_count": meta.get("post_count", len(posts)),
        "posts": posts,
        "report": meta["report"],
        "cached": True,
    }
