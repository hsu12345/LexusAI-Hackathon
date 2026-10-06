from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SentimentLabel(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class TopicLabel(str, Enum):
    service_experience = "服務體驗"
    parts_warranty = "零件保修"
    price_value = "價格價值"
    convenience = "便利性"
    loyalty_rewards = "回饋忠誠"
    alternative_channel = "替代通路"
    product_quality = "產品品質"
    other = "其他"


class RiskLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class AnalyzedPost(BaseModel):
    id: str
    source: str
    board: str | None = None
    title: str
    content: str
    posted_at: str | None = None
    url: str | None = None
    engagement: dict[str, int] = Field(default_factory=dict)
    topics: list[str] = Field(default_factory=list)
    sentiment: SentimentLabel
    sentiment_score: float
    churn_risk_score: float
    risk_level: RiskLevel
    risk_factors: list[str] = Field(default_factory=list)
    alternative_preference: list[str] = Field(default_factory=list)
    model_hint: str | None = None
    tenure_hint: str | None = None
    service_relevance_score: float = 0.0
    is_aftersales_focus: bool = False


class PersonaProfile(BaseModel):
    id: str
    name: str
    tagline: str
    risk_level: RiskLevel
    share_pct: float
    demographics: dict[str, str]
    needs: list[str]
    pain_points: list[str]
    preferred_alternatives: list[str]
    key_considerations: list[str]
    representative_quotes: list[str]
    recommended_strategy: str


class TopicInsight(BaseModel):
    topic: str
    count: int
    negative_ratio: float
    avg_risk: float
    top_keywords: list[str]


class AftersalesInsight(BaseModel):
    total_posts: int
    share_pct: float
    avg_churn_risk: float
    risk_breakdown: dict[str, int]
    sentiment_breakdown: dict[str, int]


class MarketInsightReport(BaseModel):
    total_posts: int
    source_breakdown: dict[str, int]
    sentiment_breakdown: dict[str, int]
    risk_breakdown: dict[str, int]
    avg_churn_risk: float
    topic_insights: list[TopicInsight]
    top_risk_factors: list[dict[str, Any]]
    personas: list[PersonaProfile]
    ai_methods: list[str]
    executive_summary: str
    aftersales_insight: AftersalesInsight | None = None
    risk_thresholds: dict[str, float] = Field(default_factory=dict)


class KBCitation(BaseModel):
    chunk_id: str
    title: str
    excerpt: str


class TouchpointPlan(BaseModel):
    channel: str
    purpose: str
    trigger: str
    timing: str
    priority: str
    message_theme: str


class InsightResponse(BaseModel):
    linked_topics: list[str]
    linked_risk_factors: list[str]
    segment_post_count: int
    segment_share_pct: float
    segment_avg_risk: float
    segment_high_risk_count: int
    rationale: str


class FlowNode(BaseModel):
    id: str
    label: str
    description: str
    layer: str


class CommunicationContent(BaseModel):
    persona_id: str
    persona_name: str
    channel: str
    title: str
    body: str
    cta: str
    talking_points: list[str]
    value_proof: list[str]
    kb_citations: list[KBCitation] = Field(default_factory=list)
    generation_method: str = "template"
    trigger: str | None = None
    timing: str | None = None


class CommunicationPlan(BaseModel):
    persona_id: str
    persona_name: str
    core_strategy: str
    objectives: list[str]
    touchpoints: list[dict[str, str]]
    touchpoint_timeline: list[TouchpointPlan]
    insight_response: InsightResponse
    contents: list[CommunicationContent]
    kpi: list[str]
    flow_steps: list[dict[str, str]]
    flow_nodes: list[FlowNode]
    flow_mermaid: str
    llm_available: bool = False
    rag_enabled: bool = True


class AnalyzeRequest(BaseModel):
    use_sample: bool = True
    posts: list[dict[str, Any]] | None = None


class GenerateCommRequest(BaseModel):
    persona_id: str
    use_llm: bool = False
    use_rag: bool = True
