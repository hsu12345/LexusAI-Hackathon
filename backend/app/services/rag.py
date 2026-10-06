from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parents[3]
KB_PATH = ROOT / "knowledge" / "lexus_service_kb.json"


@dataclass(frozen=True)
class KBChunk:
    id: str
    title: str
    text: str
    category: str
    tags: tuple[str, ...]


def load_kb() -> dict:
    with KB_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _flatten(obj: object, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            rows.extend(_flatten(value, path))
    elif isinstance(obj, list):
        if all(isinstance(x, str) for x in obj):
            rows.append((prefix, "；".join(obj)))
        else:
            for i, item in enumerate(obj):
                rows.extend(_flatten(item, f"{prefix}[{i}]"))
    elif obj is not None:
        rows.append((prefix, str(obj)))
    return rows


def _tags_for_path(path: str) -> tuple[str, ...]:
    tags: list[str] = []
    mapping = {
        "warranty": ("保證", "延長保證", "零件保證"),
        "maintenance": ("定保", "保養", "機油"),
        "price": ("價格", "TCO", "費用"),
        "roadside": ("道路救援", "救援"),
        "convenience": ("取送車", "便利", "夜間", "代步車"),
        "loyalty": ("Elite", "Points", "回饋", "尊榮"),
        "communication": ("溝通", "話術"),
        "customer_service": ("客服", "0800"),
        "independent": ("外廠", "非原廠"),
        "wait": ("等待", "預約", "時間"),
        "trust": ("診斷", "專業", "信任"),
    }
    lower = path.lower()
    for key, values in mapping.items():
        if key in lower:
            tags.extend(values)
    return tuple(dict.fromkeys(tags))


def build_kb_chunks(kb: dict | None = None) -> list[KBChunk]:
    kb = kb or load_kb()
    chunks: list[KBChunk] = []

    chunks.append(
        KBChunk(
            id="core_value",
            title="Lexus 售後核心價值",
            text="；".join(kb.get("core_value_proposition", [])),
            category="品牌價值",
            tags=("原廠", "尊榮", "保證"),
        )
    )

    for path, text in _flatten(kb.get("warranty", {}), "warranty"):
        if len(text.strip()) < 4:
            continue
        chunks.append(
            KBChunk(
                id=re.sub(r"[^\w]+", "_", path),
                title=f"保證權益｜{path.split('.')[-1]}",
                text=text,
                category="保證權益",
                tags=_tags_for_path(path) + ("保證", "延長保證"),
            )
        )

    for path, text in _flatten(kb.get("maintenance", {}), "maintenance"):
        if len(text.strip()) < 4:
            continue
        chunks.append(
            KBChunk(
                id=re.sub(r"[^\w]+", "_", path),
                title=f"保養服務｜{path.split('.')[-1]}",
                text=text,
                category="保養服務",
                tags=_tags_for_path(path) + ("定保", "保養"),
            )
        )

    for path, text in _flatten(kb.get("services", {}), "services"):
        if len(text.strip()) < 4:
            continue
        chunks.append(
            KBChunk(
                id=re.sub(r"[^\w]+", "_", path),
                title=f"服務項目｜{path.split('.')[-1]}",
                text=text,
                category="服務項目",
                tags=_tags_for_path(path),
            )
        )

    for key, text in kb.get("communication_talking_points", {}).items():
        chunks.append(
            KBChunk(
                id=f"talking_{key}",
                title=f"溝通話術｜{key}",
                text=text,
                category="溝通話術",
                tags=_tags_for_path(key),
            )
        )

    return chunks


class KnowledgeRetriever:
    """In-memory TF-IDF retriever for Lexus service KB (works offline)."""

    def __init__(self, kb: dict | None = None) -> None:
        self.chunks = build_kb_chunks(kb)
        corpus = [f"{c.title} {c.text} {' '.join(c.tags)}" for c in self.chunks]
        self._vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4))
        self._matrix = self._vectorizer.fit_transform(corpus)

    def retrieve(self, query: str, top_k: int = 4) -> list[tuple[KBChunk, float]]:
        if not query.strip():
            return []
        q_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self._matrix).flatten()
        ranked = np.argsort(scores)[::-1][:top_k]
        return [(self.chunks[i], float(scores[i])) for i in ranked if scores[i] > 0]


_retriever: KnowledgeRetriever | None = None


def get_retriever() -> KnowledgeRetriever:
    global _retriever
    if _retriever is None:
        _retriever = KnowledgeRetriever()
    return _retriever


def build_rag_query(
    *,
    persona_name: str,
    pain_points: list[str],
    strategy: str,
    risk_factors: list[str] | None = None,
    topics: list[str] | None = None,
) -> str:
    parts = [persona_name, strategy, *pain_points]
    if risk_factors:
        parts.extend(risk_factors)
    if topics:
        parts.extend(topics)
    return " ".join(parts)


def llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def generate_rag_content(
    *,
    persona_name: str,
    channel: str,
    pain_points: list[str],
    strategy: str,
    retrieved: list[tuple[KBChunk, float]],
    use_llm: bool = False,
) -> dict[str, str | list[str]]:
    citations = [
        {"chunk_id": c.id, "title": c.title, "excerpt": c.text[:120]}
        for c, _ in retrieved[:3]
    ]
    proof = [c.text for c, _ in retrieved[:3]]

    if use_llm and llm_available():
        try:
            from openai import OpenAI

            context = "\n".join(f"[{c.id}] {c.title}：{c.text}" for c, _ in retrieved[:4])
            client = OpenAI()
            prompt = (
                f"你是 Lexus 台灣售後溝通企劃。針對 Persona「{persona_name}」"
                f"在「{channel}」通路生成一則關懷訊息。\n"
                f"核心策略：{strategy}\n"
                f"痛點：{', '.join(pain_points)}\n\n"
                f"只能引用以下知識庫內容，不可捏造數字或條款：\n{context}\n\n"
                "語氣尊榮、不硬銷、繁體中文。"
                "回傳 JSON：title, body, cta, talking_points（字串陣列）"
            )
            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            return {
                "title": data.get("title", "專屬關懷"),
                "body": data.get("body", ""),
                "cta": data.get("cta", "了解更多"),
                "talking_points": data.get("talking_points", []),
                "value_proof": proof,
                "kb_citations": citations,
                "generation_method": "rag+llm",
            }
        except Exception:
            pass

    # Offline RAG: template synthesis from retrieved chunks
    titles = {
        "LINE": "您的愛車權益，我們已為您整理重點",
        "Email": "給重視長期價值的車主：原廠售後說明",
        "Lexus Plus App": "下次回廠，讓便利成為原廠價值的一部分",
        "電話關懷／專員": "這次，我們用清楚說明重建信任",
        "Instagram／生活誌": "被好好對待的每一刻，都值得被記住",
    }
    lead = retrieved[0][0].text if retrieved else strategy
    body = (
        f"我們理解您關心「{'、'.join(pain_points[:2])}」。"
        f"{lead}"
        " Lexus 原廠服務的價值，在於可追溯的維修紀錄、正廠零件保證與專屬診斷能力；"
        "若您希望進一步了解如何在不犧牲權益的前提下安排保養，服務專員可為您客製說明。"
    )
    return {
        "title": titles.get(channel, f"{persona_name}專屬關懷"),
        "body": body,
        "cta": "查看我的權益進度／預約諮詢",
        "talking_points": [c.title for c, _ in retrieved[:3]],
        "value_proof": proof,
        "kb_citations": citations,
        "generation_method": "rag",
    }
