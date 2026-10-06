from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import AnalyzeRequest, AnalyzedPost, GenerateCommRequest
from .services.analysis_runner import load_cached_analysis
from .services.communication import generate_plan
from .services.rag import load_kb, llm_available
from .services.insight import build_market_report, build_personas
from .services.nlp_analyzer import analyze_posts

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PATH = ROOT / "data" / "sample_posts.json"
CRAWLED_PATH = ROOT / "data" / "crawled_posts.json"
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(
    title="LexusAI Churn Insight & Smart Communication",
    description="潛在流失風險洞察與智慧溝通規劃系統（黑客松 MVP）",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_posts() -> list[dict]:
    path = CRAWLED_PATH if CRAWLED_PATH.exists() else SAMPLE_PATH
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _data_source() -> str:
    if CRAWLED_PATH.exists():
        return "crawled"
    return "sample"


_analyzed_cache: list[AnalyzedPost] | None = None


def _get_analyzed_posts(*, refresh: bool = False) -> list[AnalyzedPost]:
    global _analyzed_cache
    if _analyzed_cache is not None and not refresh:
        return _analyzed_cache

    cached = load_cached_analysis()
    if cached and not refresh:
        _analyzed_cache = [AnalyzedPost(**p) for p in cached["posts"]]
        return _analyzed_cache

    _analyzed_cache = analyze_posts(_load_posts())
    return _analyzed_cache


@app.get("/api/health")
def health():
    meta_path = ROOT / "data" / "crawl_meta.json"
    meta = None
    if meta_path.exists():
        with meta_path.open(encoding="utf-8") as f:
            meta = json.load(f)
    return {
        "status": "ok",
        "service": "LexusAI",
        "data_source": _data_source(),
        "post_count": len(_load_posts()),
        "crawl_meta": meta,
        "llm_available": llm_available(),
        "rag_enabled": True,
    }


@app.get("/api/knowledge")
def knowledge():
    return load_kb()


@app.get("/api/dashboard")
def dashboard():
    """Fast dashboard payload — reads cached analysis when available."""
    cached = load_cached_analysis()
    if cached:
        return cached
    analyzed = _get_analyzed_posts(refresh=True)
    report = build_market_report(analyzed)
    return {
        "analyzed_at": None,
        "data_source": _data_source(),
        "post_count": len(analyzed),
        "posts": [p.model_dump() for p in analyzed],
        "report": report.model_dump(),
        "cached": False,
    }


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    posts = _load_posts() if req.use_sample or not req.posts else req.posts
    global _analyzed_cache
    _analyzed_cache = analyze_posts(posts)
    report = build_market_report(_analyzed_cache)
    return {
        "posts": [p.model_dump() for p in _analyzed_cache],
        "report": report.model_dump(),
    }


@app.get("/api/report")
def report():
    cached = load_cached_analysis()
    if cached:
        return cached["report"]
    return build_market_report(_get_analyzed_posts()).model_dump()


@app.get("/api/posts")
def posts():
    return [p.model_dump() for p in _get_analyzed_posts()]


@app.get("/api/personas")
def personas():
    return [p.model_dump() for p in build_personas(_get_analyzed_posts())]


@app.post("/api/communication/generate")
def communication_generate(req: GenerateCommRequest):
    analyzed = _get_analyzed_posts()
    personas = build_personas(analyzed)
    persona = next((p for p in personas if p.id == req.persona_id), None)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    plan = generate_plan(
        persona,
        posts=analyzed,
        use_llm=req.use_llm,
        use_rag=req.use_rag,
    )
    return plan.model_dump()


@app.get("/api/communication/{persona_id}")
def communication_get(persona_id: str, use_llm: bool = False):
    analyzed = _get_analyzed_posts()
    personas = build_personas(analyzed)
    persona = next((p for p in personas if p.id == persona_id), None)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return generate_plan(persona, posts=analyzed, use_llm=use_llm).model_dump()


@app.get("/")
def index():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return {"message": "Frontend not found. API is available under /api/*"}
    return FileResponse(index_path)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
