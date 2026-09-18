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


class CommunicationContent(BaseModel):
    persona_id: str
    persona_name: str
    channel: str
    title: str
    body: str
    cta: str
    talking_points: list[str]
    value_proof: list[str]


class CommunicationPlan(BaseModel):
    persona_id: str
    persona_name: str
    core_strategy: str
    objectives: list[str]
    touchpoints: list[dict[str, str]]
    contents: list[CommunicationContent]
    kpi: list[str]
    flow_steps: list[dict[str, str]]


class AnalyzeRequest(BaseModel):
    use_sample: bool = True
    posts: list[dict[str, Any]] | None = None


class GenerateCommRequest(BaseModel):
    persona_id: str
    use_llm: bool = False
