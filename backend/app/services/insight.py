from __future__ import annotations

from collections import Counter, defaultdict

from .nlp_analyzer import topic_keyword_stats
from ..models import (
    AnalyzedPost,
    MarketInsightReport,
    PersonaProfile,
    RiskLevel,
    TopicInsight,
)


PERSONA_TEMPLATES: list[dict] = [
    {
        "id": "price_switcher",
        "name": "精算比價轉向者",
        "tagline": "保證將屆／已過，以價格與 TCO 決定是否離開原廠",
        "match_any_factors": {"價格敏感", "保證期轉換風險", "偏好替代保修通路", "明確流失意圖"},
        "risk_level": RiskLevel.high,
        "demographics": {
            "車齡": "3–6 年／保證末期或剛過",
            "車款傾向": "RX / UX / IS 等主流車系",
            "資訊管道": "PTT、Mobile01 價格討論串",
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
        "name": "時間敏感體驗者",
        "tagline": "認同品牌服務，但被等待、缺料與行程摩擦推向外廠",
        "match_any_factors": {"時間與便利痛點", "關係與溝通裂痕"},
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
        "name": "信任與專業守護者",
        "tagline": "在意被理解與專業診斷，價格可接受但拒絕制式推銷",
        "match_any_factors": {"問題解決信任危機", "關係與溝通裂痕"},
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
        "name": "尊榮體驗擁護者",
        "tagline": "高度認同取送車、救援與服務氛圍，是口碑擴散核心",
        "match_any_factors": set(),
        "risk_level": RiskLevel.low,
        "demographics": {
            "車齡": "新車～3 年為主",
            "價值觀": "安全感、儀式感、品牌溫度",
            "活躍管道": "Dcard 心得、社群分享",
            "決策風格": "體驗優先，價格次之",
        },
        "needs": ["持續被看見的尊榮感", "生活風格活動與內容", "數位權益提醒（非硬推銷）"],
        "pain_points": ["若後續變得制式，容易失落"],
        "preferred_alternatives": [],
        "key_considerations": ["服務溫度", "品牌一致性"],
        "recommended_strategy": "將擁護者轉為推薦大使，並用個人化權益進度（定保次數、Points、活動）維持黏著。",
    },
]


def _assign_persona(post: AnalyzedPost) -> str:
    factor_set = set(post.risk_factors)
    best_id = "loyalty_advocate"
    best_score = -1
    for tpl in PERSONA_TEMPLATES:
        keys = tpl["match_any_factors"]
        if not keys:
            # fallback low-risk positive/neutral
            score = 1 if post.risk_level == RiskLevel.low and post.sentiment.value != "negative" else 0
        else:
            score = len(factor_set & keys)
            if post.risk_level == RiskLevel.high and tpl["risk_level"] == RiskLevel.high:
                score += 1
        if score > best_score:
            best_score = score
            best_id = tpl["id"]
    return best_id


def build_personas(posts: list[AnalyzedPost]) -> list[PersonaProfile]:
    buckets: dict[str, list[AnalyzedPost]] = defaultdict(list)
    for p in posts:
        buckets[_assign_persona(p)].append(p)

    total = max(len(posts), 1)
    personas: list[PersonaProfile] = []
    for tpl in PERSONA_TEMPLATES:
        group = buckets.get(tpl["id"], [])
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
                representative_quotes=[
                    f"「{g.title}」— {g.content[:48]}…"
                    for g in sorted(group, key=lambda x: x.churn_risk_score, reverse=True)[:2]
                ] or ["（此 Persona 在目前樣本中樣本較少，採規則模板描繪）"],
                recommended_strategy=tpl["recommended_strategy"],
            )
        )
    return personas


def build_market_report(posts: list[AnalyzedPost]) -> MarketInsightReport:
    source_breakdown = dict(Counter(p.source for p in posts))
    sentiment_breakdown = dict(Counter(p.sentiment.value for p in posts))
    risk_breakdown = dict(Counter(p.risk_level.value for p in posts))
    avg_risk = round(sum(p.churn_risk_score for p in posts) / max(len(posts), 1), 3)

    topic_counter: Counter[str] = Counter()
    topic_neg: Counter[str] = Counter()
    topic_risk: dict[str, list[float]] = defaultdict(list)
    for p in posts:
        for t in p.topics:
            topic_counter[t] += 1
            topic_risk[t].append(p.churn_risk_score)
            if p.sentiment.value == "negative":
                topic_neg[t] += 1

    kw = topic_keyword_stats(posts)
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

    factor_counter = Counter(f for p in posts for f in p.risk_factors)
    top_risk_factors = [
        {"factor": k, "count": v, "share_pct": round(100 * v / max(len(posts), 1), 1)}
        for k, v in factor_counter.most_common(8)
    ]

    personas = build_personas(posts)
    high = risk_breakdown.get("high", 0)
    executive = (
        f"在 {len(posts)} 則 Lexus 相關公開討論中，高流失風險內容約占 {round(100*high/max(len(posts),1),1)}%，"
        f"平均流失風險指數 {avg_risk}。"
        f"負面情緒主要集中於價格價值、零件保修與替代通路討論；"
        f"正面聲量則來自取送車、道路救援與服務安全感。"
        f"建議優先鎖定「{personas[0].name}」與時間摩擦型客群，以權益透明與便利接觸點進行攔截。"
    )

    return MarketInsightReport(
        total_posts=len(posts),
        source_breakdown=source_breakdown,
        sentiment_breakdown=sentiment_breakdown,
        risk_breakdown=risk_breakdown,
        avg_churn_risk=avg_risk,
        topic_insights=topic_insights,
        top_risk_factors=top_risk_factors,
        personas=personas,
        ai_methods=[
            "中文詞典規則 + 正負向詞彙計分之情緒分析（可替換為 Transformer 中文情緒模型）",
            "多標籤主題分類（服務體驗／零件保修／價格價值／便利性／回饋忠誠／替代通路）",
            "流失風險評分模型（意圖、價格敏感、保證轉換、便利摩擦、信任裂痕加權）",
            "Persona 分群：風險因子共現規則分群（可延伸為嵌入向量聚類）",
            "知識庫增強生成（RAG）：車主權益手冊結構化知識 → 溝通文案",
        ],
        executive_summary=executive,
    )
