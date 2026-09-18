#!/usr/bin/env python
"""對目前資料執行 NLP 分析並輸出報告。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.analysis_runner import run_analysis


def main() -> None:
    result = run_analysis(save=True)
    report = result["report"]
    print(f"資料來源：{result['data_source']}")
    print(f"分析篇數：{result['post_count']}")
    print(f"平均流失風險：{report['avg_churn_risk']}")
    print(f"高風險占比：{report['risk_breakdown'].get('high', 0)}/{report['total_posts']}")
    print("\nPersona 分布：")
    for p in report["personas"]:
        print(f"  - {p['name']}: {p['share_pct']}%")
    print(f"\n已輸出：data/analysis_report.json")
    print(f"已輸出：data/analyzed_posts.json")


if __name__ == "__main__":
    main()
