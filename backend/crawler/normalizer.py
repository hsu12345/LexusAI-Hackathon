from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any


MODEL_PATTERNS = [
    (r"LBX", "LBX"),
    (r"LM\d*", "LM"),
    (r"UX\d*", "UX"),
    (r"NX\d*", "NX"),
    (r"RX\d*", "RX"),
    (r"ES\d*", "ES"),
    (r"IS\d*", "IS"),
    (r"GS\d*", "GS"),
    (r"RC\d*", "RC"),
    (r"LC\d*", "LC"),
]

TENURE_PATTERNS = [
    (r"新車|剛交車|滿月", "新車主"),
    (r"保固剛過|保證剛過|保固外|保證外|保固期外", "保固外"),
    (r"保固期|保證期|還在保", "保證期內"),
    (r"(\d+)\s*年", "年車主"),
]


def _guess_model(text: str) -> str | None:
    for pattern, model in MODEL_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return model
    if re.search(r"lexus|凌志", text, flags=re.IGNORECASE):
        return "Lexus"
    return None


def _guess_tenure(text: str) -> str | None:
    for pattern, label in TENURE_PATTERNS:
        m = re.search(pattern, text)
        if m:
            if label == "年車主" and m.lastindex:
                return f"{m.group(1)}年車主"
            return label
    return None


def is_relevant(
    text: str,
    relevance_keywords: list[str],
    service_keywords: list[str],
    *,
    aftersales_only: bool = False,
) -> bool:
    lower = text.lower()
    has_lexus = "lexus" in lower or "凌志" in text
    has_service = any(k in text for k in service_keywords)
    has_hotai = "和泰" in text and has_lexus

    if aftersales_only:
        return has_lexus and (has_service or has_hotai)

    has_brand = any(k.lower() in lower for k in relevance_keywords if k.lower() != "和泰")
    return has_lexus or has_hotai or (has_brand and has_service)


def normalize_post(raw: dict[str, Any]) -> dict[str, Any]:
    title = (raw.get("title") or "").strip()
    content = (raw.get("content") or "").strip()
    text = f"{title} {content}"
    source = raw.get("source", "unknown")
    board = raw.get("board") or ""
    url = raw.get("url") or ""
    stable = raw.get("id") or hashlib.md5(f"{source}|{url}|{title}".encode()).hexdigest()[:12]

    return {
        "id": f"{source.lower()}_{stable}",
        "source": source,
        "board": board,
        "title": title,
        "content": content,
        "author_meta": {
            "tenure_hint": _guess_tenure(text),
            "model_hint": _guess_model(text),
        },
        "posted_at": raw.get("posted_at") or datetime.now().isoformat(timespec="seconds"),
        "url": url,
        "engagement": raw.get("engagement") or {"likes": 0, "comments": raw.get("comment_count", 0)},
    }


def dedupe_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for p in posts:
        key = p.get("url") or f"{p.get('source')}|{p.get('title')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out
