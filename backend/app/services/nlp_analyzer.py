from __future__ import annotations

import re
from collections import defaultdict

from ..models import AnalyzedPost, RiskLevel, SentimentLabel


TOPIC_LEXICON: dict[str, list[str]] = {
    "服務體驗": ["服務", "態度", "專員", "禮貌", "體驗", "休息區", "安全感", "溝通", "推銷", "信任"],
    "零件保修": ["保固", "保證", "零件", "電瓶", "電池", "HEV", "維修", "故障", "異音", "診斷", "延長保證"],
    "價格價值": ["貴", "報價", "價格", "成本", "便宜", "CP", "TCO", "划算", "費用", "25900", "兩萬"],
    "便利性": ["預約", "等待", "等太久", "取送車", "代步", "時間", "App", "LINE", "道路救援"],
    "回饋忠誠": ["Points", "回饋", "Elite", "點數", "升等", "聯名", "禮遇"],
    "替代通路": ["外廠", "外面", "獨立", "工作室", "連鎖", "輪胎館", "非原廠"],
    "產品品質": ["品質", "保值", "油耗", "車況", "電子系統", "模組"],
}

POSITIVE_WORDS = [
    "好", "推薦", "有感", "方便", "專業", "加分", "細心", "透明", "舒適", "安心", "值得", "準時", "貼心"
]
NEGATIVE_WORDS = [
    "貴", "猶豫", "不爽", "抱怨", "差", "等太久", "嚇死", "擔心", "怕", "不想", "變差", "硬推", "缺料", "信任感下降"
]
RISK_PATTERNS = [
    (r"外廠|外面|獨立保修|工作室|輪胎館", "偏好替代保修通路", 0.28),
    (r"猶豫|不想回|之後.*外|全面外廠|轉向", "明確流失意圖", 0.32),
    (r"貴|報價|便宜很多|一半價格|成本", "價格敏感", 0.18),
    (r"保固.*過|保證.*到期|保固外|保證快到期", "保證期轉換風險", 0.22),
    (r"等太久|缺料|代步|等待", "時間與便利痛點", 0.15),
    (r"推銷|換人|信任|態度", "關係與溝通裂痕", 0.16),
    (r"異音|說正常|抓不到|診斷", "問題解決信任危機", 0.17),
]


def _sentiment(text: str) -> tuple[SentimentLabel, float]:
    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)
    raw = (pos - neg) / max(pos + neg, 1)
    # map to 0~1 where 1 is positive
    score = (raw + 1) / 2
    if score >= 0.62:
        return SentimentLabel.positive, round(score, 3)
    if score <= 0.42:
        return SentimentLabel.negative, round(score, 3)
    return SentimentLabel.neutral, round(score, 3)


def _topics(text: str) -> list[str]:
    hits: list[tuple[str, int]] = []
    for topic, words in TOPIC_LEXICON.items():
        score = sum(1 for w in words if w.lower() in text.lower() or w in text)
        if score:
            hits.append((topic, score))
    hits.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in hits[:3]] or ["其他"]


def _risk(text: str, sentiment: SentimentLabel) -> tuple[float, RiskLevel, list[str], list[str]]:
    factors: list[str] = []
    score = 0.15 if sentiment == SentimentLabel.negative else 0.05
    if sentiment == SentimentLabel.neutral:
        score = 0.1

    alternatives: list[str] = []
    for pattern, label, weight in RISK_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            factors.append(label)
            score += weight
            if "替代" in label or "外" in pattern:
                if "工作室" in text:
                    alternatives.append("獨立工作室")
                if "輪胎" in text:
                    alternatives.append("連鎖輪胎館")
                if "外廠" in text or "外面" in text:
                    alternatives.append("一般保修廠")

    score = min(round(score, 3), 0.99)
    if score >= 0.55:
        level = RiskLevel.high
    elif score >= 0.32:
        level = RiskLevel.medium
    else:
        level = RiskLevel.low
    return score, level, list(dict.fromkeys(factors)), list(dict.fromkeys(alternatives))


def analyze_post(raw: dict) -> AnalyzedPost:
    text = f"{raw.get('title', '')} {raw.get('content', '')}"
    sentiment, s_score = _sentiment(text)
    topics = _topics(text)
    risk_score, risk_level, factors, alts = _risk(text, sentiment)
    meta = raw.get("author_meta") or {}
    return AnalyzedPost(
        id=raw["id"],
        source=raw.get("source", "unknown"),
        board=raw.get("board"),
        title=raw.get("title", ""),
        content=raw.get("content", ""),
        posted_at=raw.get("posted_at"),
        url=raw.get("url"),
        engagement=raw.get("engagement") or {},
        topics=topics,
        sentiment=sentiment,
        sentiment_score=s_score,
        churn_risk_score=risk_score,
        risk_level=risk_level,
        risk_factors=factors,
        alternative_preference=alts,
        model_hint=meta.get("model_hint"),
        tenure_hint=meta.get("tenure_hint"),
    )


def analyze_posts(posts: list[dict]) -> list[AnalyzedPost]:
    return [analyze_post(p) for p in posts]


def topic_keyword_stats(posts: list[AnalyzedPost]) -> dict[str, list[str]]:
    topic_words: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for p in posts:
        text = p.title + p.content
        for topic in p.topics:
            for w in TOPIC_LEXICON.get(topic, []):
                if w in text:
                    topic_words[topic][w] += 1
    result: dict[str, list[str]] = {}
    for topic, counter in topic_words.items():
        ranked = sorted(counter.items(), key=lambda x: x[1], reverse=True)
        result[topic] = [w for w, _ in ranked[:5]]
    return result
