from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from .nlp_analyzer import RISK_LEVEL_HIGH_PCT, RISK_LEVEL_MEDIUM_PCT, topic_keyword_stats
from ..models import (
    AftersalesInsight,
    AnalyzedPost,
    MarketInsightReport,
    PersonaProfile,
    RiskLevel,
    TopicInsight,
)


PERSONA_TEMPLATES: list[dict] = [
    {
        "id": "price_switcher",
        "name": "保固比價型",
        "tagline": "保固快到期，在意報價、總成本，考慮改外廠",
        "risk_level": RiskLevel.high,
        "demographics": {
            "車齡": "3–6 年／保證末期或剛過",
            "車款傾向": "RX / UX / IS 等主流車系",
            "資訊管道": "PTT、Threads 價格討論",
            "決策風格": "數據導向、會算五年持有成本",
        },
        "needs": ["透明且可比較的報價", "耗材與定保的彈性方案", "保證權益不受影響的清楚說明"],
        "pain_points": ["原廠定保與零件報價偏高", "外廠價格差一倍以上的落差感", "不確定折衷保養會不會傷害權益／殘值"],
        "preferred_alternatives": ["獨立保修廠", "連鎖輪胎／耗材通路"],
        "key_considerations": ["總擁有成本", "保證／延長保證條件", "中古車殘值與維修紀錄"],
        "recommended_strategy": "用「權益保全 + 分期價值」取代單純折扣戰，強調準時定保延長保證、正廠零件保證與診斷能力。",
    },
    {
        "id": "time_friction",
        "name": "時間敏感型",
        "tagline": "認同原廠，但等太久、缺料、代步不確定會想換地方",
        "risk_level": RiskLevel.medium,
        "demographics": {
            "車齡": "1–4 年",
            "生活型態": "都會通勤、行程緊湊",
            "數位習慣": "高（App / LINE 預約）",
            "決策風格": "體驗導向，怕浪費時間",
        },
        "needs": ["可預期的工時", "取送車／夜間服務", "缺料與代步車的主動溝通"],
        "pain_points": ["未預約等待過久", "零件缺料資訊不透明", "代步車需看調度的不確定感"],
        "preferred_alternatives": ["就近快速保修據點"],
        "key_considerations": ["時間成本", "溝通透明度", "服務一致性"],
        "recommended_strategy": "以便利接觸點（取送車、夜間、進度推播）降低摩擦，把『省心省時』做成可感知的原廠價值。",
    },
    {
        "id": "trust_seeker",
        "name": "信任修復型",
        "tagline": "問題沒解決、說明不清楚，或覺得被推銷而卻步",
        "risk_level": RiskLevel.medium,
        "demographics": {
            "車齡": "2–5 年",
            "關注點": "異音、電子系統、診斷正確性",
            "關係期待": "固定專員、被記住的感受",
            "決策風格": "情感 + 專業雙軌",
        },
        "needs": ["清楚的檢測說明與路試紀錄", "非強迫式的方案建議", "專員關係連續性"],
        "pain_points": ["多次告知『正常』但問題仍在", "專員更換後變制式推銷", "感覺不被傾聽"],
        "preferred_alternatives": ["口碑工作室（解說型師傅）"],
        "key_considerations": ["信任", "專業設備", "被尊重的溝通"],
        "recommended_strategy": "以診斷透明度與專屬管家式溝通重建信任，再用原廠專用診斷與電池／電子系統保證作理性支撐。",
    },
    {
        "id": "loyalty_advocate",
        "name": "滿意擁護型",
        "tagline": "對服務有感，願意回廠，也會在網路上分享好經驗",
        "risk_level": RiskLevel.low,
        "demographics": {
            "車齡": "新車～3 年為主",
            "價值觀": "安全感、儀式感、品牌溫度",
            "活躍管道": "Dcard / Threads 心得分享",
            "決策風格": "體驗優先，價格次之",
        },
        "needs": ["持續被看見的尊榮感", "生活風格活動與內容", "數位權益提醒（非硬推銷）"],
        "pain_points": ["若後續變得制式，容易失落"],
        "preferred_alternatives": [],
        "key_considerations": ["服務溫度", "品牌一致性"],
        "recommended_strategy": "將擁護者轉為推薦大使，並用個人化權益進度（定保次數、Points、活動）維持黏著。",
    },
]

PERSONA_SIGNALS: dict[str, dict[str, float]] = {
    "price_switcher": {
        "topic:價格價值": 1.4,
        "topic:替代通路": 1.3,
        "topic:零件保修": 0.8,
        "factor:價格敏感": 1.6,
        "factor:保證期轉換風險": 1.4,
        "factor:偏好替代保修通路": 1.5,
        "factor:明確流失意圖": 1.8,
        "risk_score": 1.0,
    },
    "time_friction": {
        "topic:便利性": 1.6,
        "topic:服務體驗": 1.0,
        "factor:時間與便利痛點": 1.8,
        "factor:關係與溝通裂痕": 0.8,
        "risk_score": 0.7,
    },
    "trust_seeker": {
        "topic:服務體驗": 1.2,
        "topic:產品品質": 1.0,
        "topic:零件保修": 0.9,
        "factor:問題解決信任危機": 1.8,
        "factor:關係與溝通裂痕": 1.2,
        "sentiment:negative": 0.8,
        "risk_score": 0.75,
    },
    "loyalty_advocate": {
        "topic:回饋忠誠": 1.2,
        "topic:便利性": 0.8,
        "topic:服務體驗": 0.9,
        "sentiment:positive": 1.4,
        "service_relevance": 0.6,
        "risk_score": -0.8,
    },
}


def _persona_feature_vector(post: AnalyzedPost) -> dict[str, float]:
    features: dict[str, float] = {
        "risk_score": post.churn_risk_score,
        "service_relevance": post.service_relevance_score,
        f"sentiment:{post.sentiment.value}": 1.0,
    }
    for topic in post.topics:
        features[f"topic:{topic}"] = 1.0
    for factor in post.risk_factors:
        features[f"factor:{factor}"] = 1.0
    return features


def _assign_persona(post: AnalyzedPost) -> str:
    features = _persona_feature_vector(post)
    best_id = "loyalty_advocate"
    best_score = -999.0

    for tpl in PERSONA_TEMPLATES:
        persona_id = tpl["id"]
        weights = PERSONA_SIGNALS[persona_id]
        score = 0.0
        for key, weight in weights.items():
            if key in features:
                score += features[key] * weight
        if post.is_aftersales_focus:
            score += 0.15
        if persona_id == "loyalty_advocate" and post.risk_level == RiskLevel.low:
            score += 0.25
        if score > best_score:
            best_score = score
            best_id = persona_id
    return best_id


def get_persona_posts(posts: list[AnalyzedPost], persona_id: str) -> list[AnalyzedPost]:
    aftersales = [p for p in posts if _assign_persona(p) == persona_id and p.is_aftersales_focus]
    if aftersales:
        return aftersales
    return [p for p in posts if _assign_persona(p) == persona_id]


def build_personas(posts: list[AnalyzedPost], *, aftersales_only: bool = False) -> list[PersonaProfile]:
    pool = [p for p in posts if p.is_aftersales_focus] if aftersales_only else posts
    if not pool:
        pool = posts

    buckets: dict[str, list[AnalyzedPost]] = defaultdict(list)
    for p in pool:
        buckets[_assign_persona(p)].append(p)

    total = max(len(pool), 1)
    personas: list[PersonaProfile] = []
    for tpl in PERSONA_TEMPLATES:
        group = buckets.get(tpl["id"], [])
        top_posts = sorted(group, key=lambda x: x.churn_risk_score, reverse=True)
        quotes = [
            f"「{g.title}」— {g.content[:56].replace(chr(10), ' ')}…"
            for g in top_posts[:2]
            if g.content or g.title
        ]
        personas.append(
            PersonaProfile(
                id=tpl["id"],
                name=tpl["name"],
                tagline=tpl["tagline"],
                risk_level=tpl["risk_level"],
                share_pct=round(100 * len(group) / total, 1),
                demographics=tpl["demographics"],
                needs=tpl["needs"],
                pain_points=tpl["pain_points"],
                preferred_alternatives=tpl["preferred_alternatives"],
                key_considerations=tpl["key_considerations"],
                representative_quotes=quotes or ["（此 Persona 在目前樣本中較少，採模板描繪）"],
                recommended_strategy=tpl["recommended_strategy"],
            )
        )
    return personas


def _aftersales_insight(posts: list[AnalyzedPost]) -> AftersalesInsight:
    subset = [p for p in posts if p.is_aftersales_focus]
    total = max(len(posts), 1)
    if not subset:
        return AftersalesInsight(
            total_posts=0,
            share_pct=0.0,
            avg_churn_risk=0.0,
            risk_breakdown={},
            sentiment_breakdown={},
        )
    return AftersalesInsight(
        total_posts=len(subset),
        share_pct=round(100 * len(subset) / total, 1),
        avg_churn_risk=round(sum(p.churn_risk_score for p in subset) / len(subset), 3),
        risk_breakdown=dict(Counter(p.risk_level.value for p in subset)),
        sentiment_breakdown=dict(Counter(p.sentiment.value for p in subset)),
    )


def _executive_summary(posts: list[AnalyzedPost], personas: list[PersonaProfile], aftersales: AftersalesInsight) -> str:
    high = sum(1 for p in posts if p.risk_level == RiskLevel.high)
    aftersales_high = sum(
        1 for p in posts if p.is_aftersales_focus and p.risk_level == RiskLevel.high
    )
    top_persona = max(personas, key=lambda x: x.share_pct)
    top_topic = Counter(t for p in posts if p.is_aftersales_focus for t in p.topics).most_common(1)
    topic_name = top_topic[0][0] if top_topic else "價格價值"

    return (
        f"已分析 {len(posts)} 則 Lexus 相關討論，其中售後服務相關 {aftersales.total_posts} 則（{aftersales.share_pct}%）。"
        f"整體高流失風險占 {round(100 * high / max(len(posts), 1), 1)}%，"
        f"售後子集高風險 {aftersales_high} 則、平均風險 {aftersales.avg_churn_risk}。"
        f"售後輿情最熱議題為「{topic_name}」，"
        f"討論量最多的是「{top_persona.name}」這類車主（約 {top_persona.share_pct}%）。"
        f"可先從高風險售後議題著手規劃關懷與說明，凸顯原廠保固與服務便利。"
    )


def build_market_report(posts: list[AnalyzedPost]) -> MarketInsightReport:
    source_breakdown = dict(Counter(p.source for p in posts))
    sentiment_breakdown = dict(Counter(p.sentiment.value for p in posts))
    risk_breakdown = dict(Counter(p.risk_level.value for p in posts))
    avg_risk = round(sum(p.churn_risk_score for p in posts) / max(len(posts), 1), 3)

    aftersales_posts = [p for p in posts if p.is_aftersales_focus]
    topic_pool = aftersales_posts or posts

    topic_counter: Counter[str] = Counter()
    topic_neg: Counter[str] = Counter()
    topic_risk: dict[str, list[float]] = defaultdict(list)
    for p in topic_pool:
        for t in p.topics:
            topic_counter[t] += 1
            topic_risk[t].append(p.churn_risk_score)
            if p.sentiment.value == "negative":
                topic_neg[t] += 1

    kw = topic_keyword_stats(topic_pool)
    topic_insights = [
        TopicInsight(
            topic=topic,
            count=count,
            negative_ratio=round(topic_neg[topic] / count, 3),
            avg_risk=round(sum(topic_risk[topic]) / len(topic_risk[topic]), 3),
            top_keywords=kw.get(topic, []),
        )
        for topic, count in topic_counter.most_common()
    ]

    factor_counter = Counter(f for p in aftersales_posts for f in p.risk_factors)
    top_risk_factors = [
        {"factor": k, "count": v, "share_pct": round(100 * v / max(len(aftersales_posts), 1), 1)}
        for k, v in factor_counter.most_common(8)
    ]

    personas = build_personas(posts, aftersales_only=True)
    aftersales = _aftersales_insight(posts)
    scores = [p.churn_risk_score for p in posts]
    thresholds = {
        "high_percentile": RISK_LEVEL_HIGH_PCT,
        "medium_percentile": RISK_LEVEL_MEDIUM_PCT,
        "high_cut": round(float(np.percentile(scores, RISK_LEVEL_HIGH_PCT)), 3),
        "medium_cut": round(float(np.percentile(scores, RISK_LEVEL_MEDIUM_PCT)), 3),
    }

    return MarketInsightReport(
        total_posts=len(posts),
        source_breakdown=source_breakdown,
        sentiment_breakdown=sentiment_breakdown,
        risk_breakdown=risk_breakdown,
        avg_churn_risk=avg_risk,
        topic_insights=topic_insights,
        top_risk_factors=top_risk_factors,
        personas=personas,
        aftersales_insight=aftersales,
        risk_thresholds=thresholds,
        ai_methods=[
            "jieba 中文分詞 + TF-IDF 向量與主題原型 cosine 相似度（混合詞典加權）",
            "否定詞與程度副詞修飾的情緒分析（非單純詞頻計分）",
            "售後服務相關度模型：品牌 × 保修關鍵字 − 購車雜訊懲罰",
            "流失風險：規則因子 + 情緒 + 互動熱度 + 動態分位數分級（P70/P90）",
            "車主樣態：依主題、風險因子、情緒與售後相關度加權歸類",
            "手冊引用撰稿：依車主權益手冊條文產出各通路建議文案",
        ],
        executive_summary=_executive_summary(posts, personas, aftersales),
    )
