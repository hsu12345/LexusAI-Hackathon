from __future__ import annotations

from collections import Counter

from ..models import (
    AnalyzedPost,
    CommunicationContent,
    CommunicationPlan,
    FlowNode,
    InsightResponse,
    KBCitation,
    PersonaProfile,
    RiskLevel,
    TouchpointPlan,
)
from .insight import get_persona_posts
from .rag import (
    build_rag_query,
    generate_rag_content,
    get_retriever,
    llm_available,
    load_kb,
)

PERSONA_TOUCHPOINTS: dict[str, list[dict[str, str]]] = {
    "price_switcher": [
        {
            "channel": "Lexus LINE 官方帳號",
            "purpose": "保證窗口期主動關懷",
            "trigger": "CRM 偵測保證剩餘 ≤12 個月或定保間隔 >8 個月",
            "timing": "T-12 個月、T-6 個月、T-3 個月",
            "priority": "high",
            "message_theme": "準時 8 次定保延長保證 + TCO 說明",
        },
        {
            "channel": "Email",
            "purpose": "精算型車主深度權益說明",
            "trigger": "高流失風險分數 ≥ P90 或社群提及外廠比價",
            "timing": "風險標記後 48 小時內",
            "priority": "high",
            "message_theme": "原廠 vs 外廠差異化價值",
        },
        {
            "channel": "服務專員電話",
            "purpose": "一對一權益諮詢",
            "trigger": "連續 2 次未回廠或保證即將到期",
            "timing": "工作日上午 10–12 點",
            "priority": "medium",
            "message_theme": "折衷保養方案 + 殘值保護",
        },
    ],
    "time_friction": [
        {
            "channel": "Lexus Plus App",
            "purpose": "便利服務推播",
            "trigger": "預約未完成或上次回廠等待 >2 小時",
            "timing": "定保到期前 14 天",
            "priority": "high",
            "message_theme": "取送車 + 夜間服務 + 進度通知",
        },
        {
            "channel": "Lexus LINE 官方帳號",
            "purpose": "缺料／工時主動通知",
            "trigger": "零件缺料或工時延長",
            "timing": "異常發生 2 小時內",
            "priority": "high",
            "message_theme": "透明進度 + 代步車資格",
        },
        {
            "channel": "簡訊",
            "purpose": "預約提醒",
            "trigger": "預約前 1 天未確認",
            "timing": "預約日前 24 小時",
            "priority": "medium",
            "message_theme": "一鍵確認 + 取送車選項",
        },
    ],
    "trust_seeker": [
        {
            "channel": "服務專員電話",
            "purpose": "技師路試邀約",
            "trigger": "重複進廠同一問題或負向情緒帖匹配",
            "timing": "下次預約前或客訴後 24 小時",
            "priority": "high",
            "message_theme": "檢測透明化 + 非推銷承諾",
        },
        {
            "channel": "Email",
            "purpose": "檢測報告與方案說明",
            "trigger": "完成路試／診斷後",
            "timing": "回廠當日",
            "priority": "medium",
            "message_theme": "專用診斷價值 + 保證範圍",
        },
        {
            "channel": "Lexus LINE 官方帳號",
            "purpose": "專員關係延續",
            "trigger": "專員異動或長期未聯繫",
            "timing": "每季 1 次",
            "priority": "low",
            "message_theme": "專屬聯絡窗口 + 預約優先",
        },
    ],
    "loyalty_advocate": [
        {
            "channel": "Lexus Plus App",
            "purpose": "會員權益進度",
            "trigger": "準時定保完成或 Elite 升級節點",
            "timing": "定保完成後 24 小時",
            "priority": "medium",
            "message_theme": "Points 回饋 + 活動邀請",
        },
        {
            "channel": "Instagram／生活誌",
            "purpose": "口碑擴散與品牌情感",
            "trigger": "正向服務評價或 NPS ≥9",
            "timing": "季度活動檔期",
            "priority": "low",
            "message_theme": "尊榮體驗故事 + 推薦計畫",
        },
        {
            "channel": "Email",
            "purpose": "專屬活動邀請",
            "trigger": "Elite / Premium 會員",
            "timing": "活動前 2 週",
            "priority": "medium",
            "message_theme": "生活風格 + 車主社群",
        },
    ],
}

PERSONA_OBJECTIVES: dict[str, list[str]] = {
    "price_switcher": [
        "在保證轉換窗口降低外廠轉向率",
        "提升延長保證／準時定保認知",
        "建立 TCO 與殘值溝通框架",
    ],
    "time_friction": [
        "提高取送車與夜間服務使用率",
        "降低因等待產生的負面聲量",
        "提升預約完成率",
    ],
    "trust_seeker": [
        "提升一次修好／說明滿意度",
        "降低「被推銷」感受",
        "重建專員關係連續性",
    ],
    "loyalty_advocate": [
        "強化擁護者內容分享",
        "提升回廠頻率與會員升級",
        "擴大正向口碑",
    ],
}

RAG_CHANNELS: dict[str, list[str]] = {
    "price_switcher": ["LINE", "Email", "電話關懷／專員"],
    "time_friction": ["Lexus Plus App", "LINE", "簡訊"],
    "trust_seeker": ["電話關懷／專員", "Email", "LINE"],
    "loyalty_advocate": ["Lexus Plus App", "Instagram／生活誌", "Email"],
}

FLOW_NODES: list[FlowNode] = [
    FlowNode(
        id="listen",
        label="Listen｜輿情監測",
        description="PTT / Dcard / Threads 公開討論爬取與去重",
        layer="data",
    ),
    FlowNode(
        id="detect",
        label="Detect｜風險偵測",
        description="jieba + TF-IDF 主題、情緒、流失風險、售後相關度",
        layer="analysis",
    ),
    FlowNode(
        id="segment",
        label="Segment｜Persona 分群",
        description="多特徵加權匹配，標記高風險／低黏著客群",
        layer="analysis",
    ),
    FlowNode(
        id="retrieve",
        label="Retrieve｜RAG 检索",
        description="車主權益手冊 chunk → TF-IDF 检索最相關條文",
        layer="decision",
    ),
    FlowNode(
        id="generate",
        label="Generate｜AI 文案",
        description="RAG 增強生成 LINE / App / Email / 專員腳本",
        layer="action",
    ),
    FlowNode(
        id="review",
        label="Review｜人工審核",
        description="售後決策者審核文案與 KB 引用正確性",
        layer="decision",
    ),
    FlowNode(
        id="activate",
        label="Activate｜通路推送",
        description="依觸發條件推送至 CRM / LINE / App",
        layer="action",
    ),
    FlowNode(
        id="learn",
        label="Learn｜成效回寫",
        description="回廠率、CTR、NPS 回寫模型與內容庫",
        layer="learn",
    ),
]

FLOW_MERMAID = """flowchart LR
  subgraph data [資料層]
    A[公開輿情監測]
    B[車主權益知識庫]
  end
  subgraph analysis [分析層]
    C[NLP 風險偵測]
    D[Persona 分群]
  end
  subgraph action [行動層]
    E[RAG 检索]
    F[AI 文案生成]
    G[人工審核]
    H[通路推送]
  end
  A --> C --> D
  D --> E
  B --> E
  E --> F --> G --> H
  H -->|KPI 回寫| C"""


def _build_insight_response(
    persona: PersonaProfile,
    posts: list[AnalyzedPost] | None,
) -> InsightResponse:
    if not posts:
        return InsightResponse(
            linked_topics=["價格價值", "零件保修"],
            linked_risk_factors=["價格敏感", "保證期轉換風險"],
            segment_post_count=0,
            segment_share_pct=persona.share_pct,
            segment_avg_risk=0.0,
            segment_high_risk_count=0,
            rationale=(
                f"產出 1 顯示「{persona.name}」占售後討論 {persona.share_pct}%，"
                f"此計畫以「{persona.recommended_strategy[:24]}…」回應其痛點。"
            ),
        )

    segment = get_persona_posts(posts, persona.id)
    aftersales_total = max(sum(1 for p in posts if p.is_aftersales_focus), 1)
    topics = [t for p in segment for t in p.topics]
    factors = [f for p in segment for f in p.risk_factors]
    top_topics = [k for k, _ in Counter(topics).most_common(3)]
    top_factors = [k for k, _ in Counter(factors).most_common(3)]
    high_risk = sum(1 for p in segment if p.risk_level == RiskLevel.high)
    avg_risk = round(sum(p.churn_risk_score for p in segment) / max(len(segment), 1), 3)

    topic_str = "、".join(top_topics) if top_topics else "價格價值"
    factor_str = "、".join(top_factors) if top_factors else "價格敏感"

    return InsightResponse(
        linked_topics=top_topics or ["價格價值"],
        linked_risk_factors=top_factors or ["價格敏感"],
        segment_post_count=len(segment),
        segment_share_pct=round(100 * len(segment) / aftersales_total, 1),
        segment_avg_risk=avg_risk,
        segment_high_risk_count=high_risk,
        rationale=(
            f"產出 1 中，{len(segment)} 則討論歸屬「{persona.name}」（售後子集 {round(100 * len(segment) / aftersales_total, 1)}%），"
            f"主要議題為「{topic_str}」，驅動因子含「{factor_str}」，"
            f"其中 {high_risk} 則為高流失風險（平均風險 {avg_risk}）。"
            f"本計畫以「{persona.recommended_strategy[:30]}…」直接回應上述洞察。"
        ),
    )


def _touchpoint_timeline(persona_id: str) -> list[TouchpointPlan]:
    return [TouchpointPlan(**row) for row in PERSONA_TOUCHPOINTS.get(persona_id, [])]


def _rag_contents(
    persona: PersonaProfile,
    *,
    use_rag: bool,
    use_llm: bool,
    insight: InsightResponse,
) -> list[CommunicationContent]:
    if not use_rag:
        return []

    retriever = get_retriever()
    query = build_rag_query(
        persona_name=persona.name,
        pain_points=persona.pain_points,
        strategy=persona.recommended_strategy,
        risk_factors=insight.linked_risk_factors,
        topics=insight.linked_topics,
    )
    retrieved = retriever.retrieve(query, top_k=5)
    channels = RAG_CHANNELS.get(persona.id, ["LINE", "Email"])
    timeline = _touchpoint_timeline(persona.id)
    contents: list[CommunicationContent] = []

    for i, channel in enumerate(channels):
        tp = timeline[i] if i < len(timeline) else None
        generated = generate_rag_content(
            persona_name=persona.name,
            channel=channel,
            pain_points=persona.pain_points,
            strategy=persona.recommended_strategy,
            retrieved=retrieved,
            use_llm=use_llm,
        )
        citations = [
            KBCitation(**c) for c in generated.get("kb_citations", [])
        ]
        method = generated.get("generation_method", "rag")
        label = channel
        if method == "rag+llm":
            label = f"{channel}（RAG + LLM）"
        elif method == "rag":
            label = f"{channel}（RAG 增強）"

        contents.append(
            CommunicationContent(
                persona_id=persona.id,
                persona_name=persona.name,
                channel=label,
                title=str(generated.get("title", "")),
                body=str(generated.get("body", "")),
                cta=str(generated.get("cta", "")),
                talking_points=list(generated.get("talking_points", [])),
                value_proof=list(generated.get("value_proof", [])),
                kb_citations=citations,
                generation_method=str(method),
                trigger=tp.trigger if tp else None,
                timing=tp.timing if tp else None,
            )
        )
    return contents


def generate_plan(
    persona: PersonaProfile,
    *,
    posts: list[AnalyzedPost] | None = None,
    use_llm: bool = False,
    use_rag: bool = True,
) -> CommunicationPlan:
    kb = load_kb()
    insight = _build_insight_response(persona, posts)
    timeline = _touchpoint_timeline(persona.id)

    touch = [{"channel": t["name"], "purpose": t["use"]} for t in kb.get("touchpoints", [])]

    flow = [
        {"step": "1. Listen", "desc": "監測 PTT／Dcard／Threads 公開討論並自動標籤"},
        {"step": "2. Detect", "desc": "計算流失風險分數，標記高風險貼文與 Persona"},
        {"step": "3. Match", "desc": "將風險因子對應 Persona，連結產出 1 洞察"},
        {"step": "4. Retrieve", "desc": "RAG 从車主權益手冊检索相關條文（TF-IDF / Embedding）"},
        {"step": "5. Generate", "desc": "AI 生成接觸點文案（RAG 增強，可選 LLM）"},
        {"step": "6. Review", "desc": "售後決策者審核文案與 KB 引用"},
        {"step": "7. Activate", "desc": "依觸發條件推送至 LINE／App／Email／專員"},
        {"step": "8. Learn", "desc": "回收回廠率與互動數據，回寫模型權重"},
    ]

    contents = _rag_contents(
        persona,
        use_rag=use_rag,
        use_llm=use_llm,
        insight=insight,
    )

    return CommunicationPlan(
        persona_id=persona.id,
        persona_name=persona.name,
        core_strategy=persona.recommended_strategy,
        objectives=PERSONA_OBJECTIVES.get(persona.id, ["提升黏著與滿意"]),
        touchpoints=touch,
        touchpoint_timeline=timeline,
        insight_response=insight,
        contents=contents,
        kpi=[
            "高風險客群回廠率",
            "外廠轉向相關負面聲量占比",
            "取送車／夜間服務採用率",
            "溝通內容 CTR 與預約完成率",
            "NPS／服務問卷中「被理解」分數",
        ],
        flow_steps=flow,
        flow_nodes=FLOW_NODES,
        flow_mermaid=FLOW_MERMAID,
        llm_available=llm_available(),
        rag_enabled=use_rag,
    )
