#!/usr/bin/env python
"""匯出 LexusAI 運作流程圖（PNG + SVG）供簡報使用。"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.communication import FLOW_MERMAID

OUT_DIR = ROOT / "assets"

def _html(
    diagram: str,
    *,
    title: str = "LexusAI 運作流程",
    font_size: str = "16px",
    title_size: str = "18px",
) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8" />
  <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      background: #f3efe6;
      font-family: "Microsoft JhengHei", "Segoe UI", sans-serif;
    }}
    #card {{
      display: inline-block;
      background: #fffef9;
      border: 1px solid rgba(20, 20, 20, 0.12);
      padding: 24px 28px;
      box-shadow: 0 18px 50px rgba(40, 30, 10, 0.08);
    }}
    h1 {{
      font-size: {title_size};
      font-weight: 600;
      margin: 0 0 20px;
      color: #141414;
      letter-spacing: 0.08em;
      text-align: center;
    }}
    #diagram svg {{
      max-width: 100%;
      height: auto;
    }}
  </style>
</head>
<body>
  <div id="card">
    <h1>{title}</h1>
    <div id="diagram"></div>
  </div>
  <script>
    mermaid.initialize({{
      startOnLoad: false,
      theme: "neutral",
      securityLevel: "loose",
      flowchart: {{
        htmlLabels: true,
        curve: "basis",
        padding: 18,
        nodeSpacing: 36,
        rankSpacing: 44,
        useMaxWidth: false
      }},
      themeVariables: {{
        fontSize: "{font_size}",
        fontFamily: "Microsoft JhengHei, Segoe UI, sans-serif"
      }}
    }});
    (async () => {{
      const def = {diagram!r};
      const {{ svg }} = await mermaid.render("lexus-flow-export", def);
      document.getElementById("diagram").innerHTML = svg;
    }})();
  </script>
</body>
</html>"""


def export_diagram(
    diagram: str,
    png_path: Path,
    svg_path: Path,
    *,
    viewport_width: int,
    viewport_height: int,
    font_size: str = "16px",
    title_size: str = "18px",
) -> None:
    from playwright.sync_api import sync_playwright

    png_path.parent.mkdir(parents=True, exist_ok=True)
    html = _html(diagram.strip(), font_size=font_size, title_size=title_size)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(
            viewport={"width": viewport_width, "height": viewport_height},
            device_scale_factor=2,
        )
        page.set_content(html, wait_until="networkidle")
        page.wait_for_selector("#diagram svg", timeout=60000)
        page.wait_for_timeout(1000)

        svg = page.locator("#diagram svg").evaluate(
            "(el) => new XMLSerializer().serializeToString(el)"
        )
        svg_path.write_text(svg, encoding="utf-8")
        page.locator("#card").screenshot(path=str(png_path), type="png")
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="匯出 LexusAI 流程圖")
    parser.add_argument(
        "--large-only",
        action="store_true",
        help="只輸出橫向大字版（lexusai_flow_diagram_large.*，略窄略高）",
    )
    parser.add_argument(
        "--portrait-only",
        action="store_true",
        help="同 --large-only（保留舊參數名稱）",
    )
    parser.add_argument(
        "--landscape-only",
        action="store_true",
        help="只輸出橫向版（lexusai_flow_diagram.*）",
    )
    args = parser.parse_args()

    large_only = args.large_only or args.portrait_only
    do_landscape = not large_only
    do_large = not args.landscape_only

    if do_landscape:
        export_diagram(
            FLOW_MERMAID,
            OUT_DIR / "lexusai_flow_diagram.png",
            OUT_DIR / "lexusai_flow_diagram.svg",
            viewport_width=1600,
            viewport_height=900,
            font_size="16px",
            title_size="18px",
        )
        print(f"已輸出橫向 PNG → {OUT_DIR / 'lexusai_flow_diagram.png'}")
        print(f"已輸出橫向 SVG → {OUT_DIR / 'lexusai_flow_diagram.svg'}")

    if do_large:
        # 仍為 flowchart LR；字較大、畫布略窄略高，適合簡報
        export_diagram(
            FLOW_MERMAID,
            OUT_DIR / "lexusai_flow_diagram_large.png",
            OUT_DIR / "lexusai_flow_diagram_large.svg",
            viewport_width=1120,
            viewport_height=980,
            font_size="22px",
            title_size="22px",
        )
        shutil.copy(
            OUT_DIR / "lexusai_flow_diagram_large.png",
            OUT_DIR / "lexusai_flow_diagram_portrait.png",
        )
        shutil.copy(
            OUT_DIR / "lexusai_flow_diagram_large.svg",
            OUT_DIR / "lexusai_flow_diagram_portrait.svg",
        )
        print(f"已輸出橫向大字 PNG → {OUT_DIR / 'lexusai_flow_diagram_large.png'}")
        print(f"已輸出橫向大字 SVG → {OUT_DIR / 'lexusai_flow_diagram_large.svg'}")


if __name__ == "__main__":
    main()
