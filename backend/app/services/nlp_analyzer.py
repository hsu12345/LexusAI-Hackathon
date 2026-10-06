from __future__ import annotations

import re
from collections import defaultdict

import numpy as np

from ..models import AnalyzedPost, RiskLevel, SentimentLabel
from .text_features import (
    TOPIC_LEXICON,
    extract_keywords_for_topic,
    pick_topics,
    sentiment_with_negation,
    service_relevance_score,
)

RISK_PATTERNS: list[tuple[str, str, float]] = [
    (r"外廠|外面|獨立保修|工作室|輪胎館|副廠", "偏好替代保修通路", 0.22),
    (r"猶豫|不想回|之後.*外|全面外廠|轉向|改去|不再回", "明確流失意圖", 0.28),
    (r"貴|報價|便宜很多|一半價格|成本|太貴|坑", "價格敏感", 0.16),
    (r"保固.*過|保證.*到期|保固外|保證快到期|過保", "保證期轉換風險", 0.2),
    (r"等太久|缺料|代步|等待|久候|排隊", "時間與便利痛點", 0.14),
    (r"推銷|換人|硬推|不被尊重|不被理解", "關係與溝通裂痕", 0.14),
    (r"異音|說正常|抓不到|修不好|沒改善|敷衍", "問題解決信任危機", 0.18),
    (r"原廠.*值得|還是回原廠|繼續回原廠", "原廠黏著訊號", -0.12),
]

RISK_LEVEL_HIGH_PCT = 90
RISK_LEVEL_MEDIUM_PCT = 70


def _sentiment_label(score: float) -> SentimentLabel:
    if score >= 0.62:
        return SentimentLabel.positive
    if score <= 0.42:
        return SentimentLabel.negative
    return SentimentLabel.neutral


def _detect_risk_factors(text: str) -> tuple[list[str], list[str], float]:
    factors: list[str] = []
    alternatives: list[str] = []
    score = 0.0

    for pattern, label, weight in RISK_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            if weight > 0:
                factors.append(label)
                score += weight
                if "替代" in label:
                    if "工作室" in text:
                        alternatives.append("獨立工作室")
                    if "輪胎" in text:
                        alternatives.append("連鎖輪胎館")
                    if "外廠" in text or "外面" in text:
                        alternatives.append("一般保修廠")
            else:
                score += weight

    return list(dict.fromkeys(factors)), list(dict.fromkeys(alternatives)), score


def _engagement_boost(engagement: dict) -> float:
    comments = int(engagement.get("comments") or 0)
    likes = int(engagement.get("likes") or 0)
    if comments >= 20 or likes >= 50:
        return 0.06
    if comments >= 5 or likes >= 10:
        return 0.03
    return 0.0


def _risk_level_from_score(score: float, thresholds: tuple[float, float]) -> RiskLevel:
    high_cut, medium_cut = thresholds
    if score >= high_cut:
        return RiskLevel.high
    if score >= medium_cut:
        return RiskLevel.medium
    return RiskLevel.low


def analyze_post(
    raw: dict,
    *,
    thresholds: tuple[float, float] = (0.55, 0.32),
) -> AnalyzedPost:
    title = raw.get("title") or ""
    content = raw.get("content") or ""
    text = f"{title}\n{content}"
    meta = raw.get("author_meta") or {}
    engagement = raw.get("engagement") or {}

    service_score = service_relevance_score(text)
    _, _, sentiment_score = sentiment_with_negation(text)
    sentiment = _sentiment_label(sentiment_score)
    topics = pick_topics(text)

    factors, alternatives, pattern_score = _detect_risk_factors(text)
    risk_score = 0.08
    if sentiment == SentimentLabel.negative:
        risk_score += 0.12
    elif sentiment == SentimentLabel.neutral:
        risk_score += 0.06
    else:
        risk_score += 0.02

    risk_score += pattern_score
    risk_score += max(0.0, (0.45 - service_score) * 0.08)
    risk_score += _engagement_boost(engagement)
    risk_score = round(min(max(risk_score, 0.0), 0.99), 3)

    return AnalyzedPost(
        id=raw["id"],
        source=raw.get("source", "unknown"),
        board=raw.get("board"),
        title=title,
        content=content,
        posted_at=raw.get("posted_at"),
        url=raw.get("url"),
        engagement=engagement,
        topics=topics,
        sentiment=sentiment,
        sentiment_score=sentiment_score,
        churn_risk_score=risk_score,
        risk_level=_risk_level_from_score(risk_score, thresholds),
        risk_factors=factors,
        alternative_preference=alternatives,
        model_hint=meta.get("model_hint"),
        tenure_hint=meta.get("tenure_hint"),
        service_relevance_score=service_score,
        is_aftersales_focus=service_score >= 0.35,
    )


def analyze_posts(posts: list[dict]) -> list[AnalyzedPost]:
    if not posts:
        return []

    preliminary = [analyze_post(p) for p in posts]
    scores = [p.churn_risk_score for p in preliminary]
    high_cut = float(np.percentile(scores, RISK_LEVEL_HIGH_PCT))
    medium_cut = float(np.percentile(scores, RISK_LEVEL_MEDIUM_PCT))
    thresholds = (max(high_cut, 0.45), max(medium_cut, 0.28))

    analyzed: list[AnalyzedPost] = []
    for raw, pre in zip(posts, preliminary):
        post = analyze_post(raw, thresholds=thresholds)
        post.churn_risk_score = pre.churn_risk_score
        post.risk_level = _risk_level_from_score(pre.churn_risk_score, thresholds)
        analyzed.append(post)
    return analyzed


def topic_keyword_stats(posts: list[AnalyzedPost]) -> dict[str, list[str]]:
    topic_texts: dict[str, list[str]] = defaultdict(list)
    for p in posts:
        text = f"{p.title} {p.content}"
        for topic in p.topics:
            topic_texts[topic].append(text)

    result: dict[str, list[str]] = {}
    for topic in TOPIC_LEXICON:
        result[topic] = extract_keywords_for_topic(topic_texts.get(topic, []), topic)
    return result
