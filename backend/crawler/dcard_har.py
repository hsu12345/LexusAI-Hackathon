from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from .config import CrawlConfig
from .dcard_capture import (
    API_PATH_PREFIX,
    DcardApiSniffer,
    finalize_capture,
    save_capture,
)


def parse_har_file(har_path: Path) -> DcardApiSniffer:
    """從 Edge DevTools 匯出的 HAR 檔解析 Dcard API JSON。"""
    raw = json.loads(har_path.read_text(encoding="utf-8"))
    entries = raw.get("log", {}).get("entries", [])
    if not entries and isinstance(raw, list):
        entries = raw

    sniffer = DcardApiSniffer()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        req = entry.get("request") or {}
        resp = entry.get("response") or {}
        url = req.get("url") or ""
        if API_PATH_PREFIX not in url:
            continue
        if int(resp.get("status") or 0) != 200:
            continue
        content = resp.get("content") or {}
        text = content.get("text") or ""
        if not text:
            continue
        if content.get("encoding") == "base64":
            text = base64.b64decode(text).decode("utf-8", errors="ignore")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        before = len(sniffer.posts)
        sniffer.ingest_payload(data, url)
        added = len(sniffer.posts) - before
        if added:
            print(f"      [Dcard/HAR] +{added} 篇 ← {url.split('?')[0][-56:]}")

    sniffer.hits.append({"source": str(har_path), "total": len(sniffer.posts)})
    return sniffer


def import_har(har_path: Path, config: CrawlConfig) -> list[dict]:
    sniffer = parse_har_file(har_path)
    capture_path = Path(getattr(config, "dcard_capture_path", "data/dcard_api_capture.json"))
    save_capture(sniffer, capture_path)
    print(f"      [Dcard/HAR] 原始 API → {capture_path}（{len(sniffer.posts)} 篇）")
    return finalize_capture(sniffer, config)
