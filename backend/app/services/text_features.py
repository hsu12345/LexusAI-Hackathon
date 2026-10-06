from __future__ import annotations

import re
from functools import lru_cache

import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

TOPIC_PROFILES: dict[str, str] = {
    "服務體驗": "服務 態度 專員 禮貌 體驗 休息區 安全感 溝通 推銷 信任 滿意 失望",
    "零件保修": "保固 保證 零件 電瓶 電池 混動 維修 故障 異音 診斷 延長保證 保修 保養",
    "價格價值": "貴 報價 價格 成本 便宜 划算 費用 兩萬 菜單 值得  cp值 總成本",
    "便利性": "預約 等待 等太久 取送車 代步 時間 道路救援 排隊 久候",
    "回饋忠誠": "points 回饋 elite 點數 升等 聯名 禮遇 會員 紅利",
    "替代通路": "外廠 外面 獨立 工作室 連鎖 輪胎館 非原廠 副廠 自己找",
    "產品品質": "品質 保值 油耗 車況 電子 模組 異常 耐用",
}

TOPIC_LEXICON: dict[str, list[str]] = {
    k: v.split() for k, v in TOPIC_PROFILES.items()
}

SERVICE_KEYWORDS = [
    "保養", "保修", "定保", "原廠", "外廠", "保固", "保證", "零件", "維修", "服務",
    "報價", "道路救援", "代步", "取送", "機油", "工資", "回廠", "服務廠", "保修廠",
    "延長保證", "保養券", "定保", "接車", "洗車",
]

PURCHASE_NOISE = [
    "交車", "試駕", "菜單", "購車", "新車", "改款", "外觀", "內裝", "配備", "下訂",
    "業代", "議價", "車色", "發表", "上市", "開箱", "賞車", "試乘",
]

BRAND_PATTERN = re.compile(r"lexus|凌志|和泰", re.I)

POSITIVE_WORDS = [
    "推薦", "有感", "方便", "專業", "加分", "細心", "透明", "舒適", "安心", "值得",
    "準時", "貼心", "滿意", "優質", "讚", "不錯", "喜歡",
]
NEGATIVE_WORDS = [
    "貴", "猶豫", "不爽", "抱怨", "差", "等太久", "嚇死", "擔心", "怕", "不想",
    "變差", "硬推", "缺料", "失望", "後悔", "坑", "離譜", "爛", "空虛",
]
NEGATORS = ["不", "沒", "無", "別", "未", "非", "不太", "不是很"]
INTENSIFIERS = ["非常", "超", "很", "太", "極度", "真的"]

STOPWORDS = set(
    "的 了 是 在 我 有 和 就 不 人 都 一 一個 上 也 很 到 說 要 去 你 "
    "會 著 沒有 看 好 自己 這 那 嗎 吧 啊 呢 還 可以 如果 但是 因為 所以 "
    "請問 大家 有人 謝謝 覺得 應該 可能 一些 什麼 如何 怎麼 這樣 已經".split()
)


def normalize_text(text: str) -> str:
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text: str) -> list[str]:
    text = normalize_text(text.lower())
    return [
        tok.strip()
        for tok in jieba.lcut(text)
        if len(tok.strip()) >= 2 and tok.strip() not in STOPWORDS
    ]


@lru_cache(maxsize=1)
def _topic_vectorizer() -> tuple[TfidfVectorizer, list[str], np.ndarray]:
    topic_names = list(TOPIC_PROFILES.keys())
    corpus = list(TOPIC_PROFILES.values())
    vectorizer = TfidfVectorizer(tokenizer=tokenize, token_pattern=None, min_df=1)
    topic_matrix = vectorizer.fit_transform(corpus)
    return vectorizer, topic_names, topic_matrix.toarray()


def topic_scores(text: str) -> dict[str, float]:
    vectorizer, topic_names, topic_matrix = _topic_vectorizer()
    doc_vec = vectorizer.transform([normalize_text(text)])
    sims = cosine_similarity(doc_vec, topic_matrix)[0]

    lexicon_boost = {}
    lower = text.lower()
    for name, words in TOPIC_LEXICON.items():
        lexicon_boost[name] = min(sum(1 for w in words if w.lower() in lower) * 0.08, 0.35)

    combined = {
        name: round(float(sims[i] * 0.65 + lexicon_boost.get(name, 0)), 4)
        for i, name in enumerate(topic_names)
    }
    return combined


def pick_topics(text: str, top_k: int = 3, threshold: float = 0.12) -> list[str]:
    scores = topic_scores(text)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    picked = [name for name, score in ranked if score >= threshold][:top_k]
    return picked or [ranked[0][0] if ranked else "其他"]


def service_relevance_score(text: str) -> float:
    lower = text.lower()
    brand = 0.15 if BRAND_PATTERN.search(text) else 0.0
    service_hits = sum(1 for w in SERVICE_KEYWORDS if w in text)
    noise_hits = sum(1 for w in PURCHASE_NOISE if w in text)
    service_part = min(service_hits * 0.12, 0.72)
    noise_penalty = min(noise_hits * 0.08, 0.35)
    score = brand + service_part - noise_penalty
    return round(max(0.0, min(1.0, score)), 3)


def sentiment_with_negation(text: str) -> tuple[float, float, float]:
    """回傳 pos_strength, neg_strength, normalized score(0~1)."""
    pos = 0.0
    neg = 0.0
    for word in POSITIVE_WORDS:
        for m in re.finditer(re.escape(word), text):
            start = max(0, m.start() - 3)
            window = text[start : m.start()]
            weight = 1.5 if any(n in window for n in INTENSIFIERS) else 1.0
            if any(n in window for n in NEGATORS):
                neg += 0.6 * weight
            else:
                pos += weight
    for word in NEGATIVE_WORDS:
        for m in re.finditer(re.escape(word), text):
            start = max(0, m.start() - 3)
            window = text[start : m.start()]
            weight = 1.5 if any(n in window for n in INTENSIFIERS) else 1.0
            if any(n in window for n in NEGATORS):
                pos += 0.4 * weight
            else:
                neg += weight
    total = pos + neg
    if total == 0:
        return pos, neg, 0.5
    raw = (pos - neg) / total
    score = (raw + 1) / 2
    return pos, neg, round(score, 3)


def extract_keywords_for_topic(texts: list[str], topic: str, top_n: int = 5) -> list[str]:
    if not texts:
        return TOPIC_LEXICON.get(topic, [])[:top_n]
    seed = " ".join(TOPIC_LEXICON.get(topic, []))
    corpus = [seed, *texts[:500]]
    vectorizer = TfidfVectorizer(tokenizer=tokenize, token_pattern=None, max_features=2000)
    matrix = vectorizer.fit_transform(corpus)
    scores = np.asarray(matrix[1:].sum(axis=0)).ravel()
    terms = vectorizer.get_feature_names_out()
    ranked = sorted(zip(terms, scores), key=lambda x: x[1], reverse=True)
    return [term for term, score in ranked[:top_n] if score > 0]
