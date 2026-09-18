from __future__ import annotations

import json
import os
from pathlib import Path

from ..models import CommunicationContent, CommunicationPlan, PersonaProfile

ROOT = Path(__file__).resolve().parents[3]
KB_PATH = ROOT / "knowledge" / "lexus_service_kb.json"


def load_kb() -> dict:
    with KB_PATH.open(encoding="utf-8") as f:
        return json.load(f)


CONTENT_BANK: dict[str, list[dict]] = {
    "price_switcher": [
        {
            "channel": "LINE",
            "title": "您的愛車保證權益進度，值得被看見",
            "body": "您好，關於近期車主關心的定保費用與保證權益，我們整理了專屬於您的重點：若在基本保證到期前連續準時完成 8 次原廠定保（原廠機油＋定保套餐），即有機會享延長保證。此外，於 Lexus 服務廠更換的正廠零件（消耗品除外）另享 2 年或 5 萬公里零件保證。原廠價值不只是當次報價，更是可追溯的品質與往後幾年的安心。",
            "cta": "立即查看我的定保／保證進度",
            "talking_points": ["準時 8 次定保延長保證", "正廠零件 2 年／5 萬保證", "長期 TCO 與殘值保護"],
            "value_proof": ["基本保證 4 年／12 萬公里", "HEV 電池最長 8 年／16 萬", "和泰 Points 1.5% 回饋可折抵"],
        },
        {
            "channel": "Email",
            "title": "一份給精算車主的原廠價值說明",
            "body": "我們理解您會比較外廠價格。差異往往來自專用診斷、原廠油品驗證、技師認證與完整車輛履歷。若您希望採『關鍵項目回原廠、耗材彈性安排』的策略，服務專員可依車況協助規劃，避免因資訊不清而誤觸保證外事項。",
            "cta": "預約 15 分鐘權益諮詢",
            "talking_points": ["透明說明保證外事項", "折衷保養建議", "非強迫式方案"],
            "value_proof": ["延長保證加購方案資訊公開", "官網／App 可查詢紀錄"],
        },
    ],
    "time_friction": [
        {
            "channel": "Lexus Plus App",
            "title": "下次回廠，把半天變成一趟取送",
            "body": "不想為了保養犧牲行程？只要於預定入廠日前 2 天預約，單程 10 公里內可申請到府取送車；亦可改約夜間延長服務時段。我們會在零件進度有變時主動通知，讓等待變成可預期的安排。",
            "cta": "一鍵預約取送車／夜間服務",
            "talking_points": ["取送車", "夜間／例假日服務", "進度主動通知"],
            "value_proof": ["洗車吸塵隨定保／維修", "維修留廠達 72 小時可申請代步車（條件適用時）"],
        }
    ],
    "trust_seeker": [
        {
            "channel": "電話關懷／專員",
            "title": "這次，我們用路試紀錄把問題說清楚",
            "body": "若您仍感受到異音或不適，我們建議安排技師陪同路試，並提供檢測項目與結果說明，不做模糊帶過。電子系統與複雜故障尤其需要原廠專用診斷；在保證範圍內，我們會依規範協助判定。溝通上，我們承諾以您聽得懂的語言說明選項，而非制式推銷。",
            "cta": "預約技師路試檢測",
            "talking_points": ["路試與檢測透明化", "專用診斷價值", "非強迫溝通"],
            "value_proof": ["顧客服務中心 0800-036-036", "AI 客服多通路入口"],
        }
    ],
    "loyalty_advocate": [
        {
            "channel": "Instagram／生活誌",
            "title": "因為被好好對待，所以願意再回來",
            "body": "從滿月檢查的客製化設定，到取送車與道路救援的關鍵時刻，這些細節構成 Lexus 的服務記憶。邀請您續寫下一段：準時定保累積 Elite Rewards 等級，並用和泰 Points 兌換下一次更自在的用車生活。",
            "cta": "分享我的服務時光／查看會員禮遇",
            "talking_points": ["體驗記憶", "會員升級", "口碑擴散"],
            "value_proof": ["Elite / Premium / Eternity 回饋", "車主專屬活動與刊物"],
        }
    ],
}


def _plan_meta(persona: PersonaProfile, kb: dict) -> CommunicationPlan:
    samples = CONTENT_BANK.get(persona.id, CONTENT_BANK["loyalty_advocate"])
    contents = [
        CommunicationContent(
            persona_id=persona.id,
            persona_name=persona.name,
            channel=s["channel"],
            title=s["title"],
            body=s["body"],
            cta=s["cta"],
            talking_points=s["talking_points"],
            value_proof=s["value_proof"],
        )
        for s in samples
    ]

    touch = [
        {"channel": t["name"], "purpose": t["use"]}
        for t in kb.get("touchpoints", [])
    ]

    objectives_map = {
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
            "降低『被推銷』感受",
            "重建專員關係連續性",
        ],
        "loyalty_advocate": [
            "強化擁護者內容分享",
            "提升回廠頻率與會員升級",
            "擴大正向口碑",
        ],
    }

    flow = [
        {"step": "1. Listen", "desc": "監測 PTT／Dcard／Mobile01 公開討論並自動標籤"},
        {"step": "2. Detect", "desc": "計算流失風險分數，標記高風險貼文與客群 Persona"},
        {"step": "3. Match", "desc": "將風險因子對應至原廠知識庫話術與權益證明點"},
        {"step": "4. Generate", "desc": "AI 生成接觸點文案（LINE／App／Email／專員腳本）"},
        {"step": "5. Activate", "desc": "經售後決策者審核後，推播至對應通路並追蹤 KPI"},
        {"step": "6. Learn", "desc": "回收互動與回廠數據，回寫模型權重與內容成效"},
    ]

    return CommunicationPlan(
        persona_id=persona.id,
        persona_name=persona.name,
        core_strategy=persona.recommended_strategy,
        objectives=objectives_map.get(persona.id, ["提升黏著與滿意"]),
        touchpoints=touch,
        contents=contents,
        kpi=[
            "高風險客群回廠率",
            "外廠轉向相關負面聲量占比",
            "取送車／夜間服務採用率",
            "溝通內容 CTR 與預約完成率",
            "NPS／服務問卷中『被理解』分數",
        ],
        flow_steps=flow,
    )


def generate_plan(persona: PersonaProfile, use_llm: bool = False) -> CommunicationPlan:
    kb = load_kb()
    plan = _plan_meta(persona, kb)

    if use_llm and os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI

            client = OpenAI()
            prompt = (
                f"你是 Lexus 台灣售後溝通企劃。請針對 Persona「{persona.name}」"
                f"痛點 {persona.pain_points} 生成一則 LINE 關懷訊息。"
                f"必須引用這些原廠價值：{kb['communication_talking_points']}。"
                "語氣尊榮、不硬銷、繁體中文。回傳 JSON：title, body, cta"
            )
            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
            plan.contents.insert(
                0,
                CommunicationContent(
                    persona_id=persona.id,
                    persona_name=persona.name,
                    channel="LINE（LLM 即時生成）",
                    title=data.get("title", "專屬關懷"),
                    body=data.get("body", ""),
                    cta=data.get("cta", "了解更多"),
                    talking_points=list(kb["communication_talking_points"].keys()),
                    value_proof=kb["core_value_proposition"][:3],
                ),
            )
        except Exception:
            # keep template contents if LLM fails
            pass

    return plan
