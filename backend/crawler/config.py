from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CrawlConfig:
    """爬蟲設定：關鍵字、看板、速率限制。"""

    ptt_boards: list[str] = field(
        default_factory=lambda: ["car", "Auto", "luxury", "e-cars"]
    )
    ptt_search_keywords: list[str] = field(
        default_factory=lambda: [
            "lexus 保養",
            "lexus 保修",
            "lexus 原廠",
            "lexus 外廠",
            "lexus 保固",
            "lexus 定保",
            "lexus 道路救援",
            "lexus 服務",
            "lexus",
            "凌志 保養",
            "凌志 原廠",
            "凌志",
        ]
    )
    # False = 收較多 Lexus 討論；True = 僅保留售後服務相關
    aftersales_only: bool = False
    mobile01_forums: list[int] = field(default_factory=lambda: [267, 606, 264])
    mobile01_search_keywords: list[str] = field(
        default_factory=lambda: ["lexus", "lexus 保養", "lexus 保修", "凌志"]
    )
    dcard_forums: list[str] = field(default_factory=lambda: ["car", "automobile"])
    dcard_search_keywords: list[str] = field(
        default_factory=lambda: [
            "lexus 保養",
            "lexus 保修",
            "lexus 原廠",
            "lexus",
        ]
    )
    max_dcard_articles: int = 25
    dcard_headless: bool = False
    dcard_use_edge: bool = True
    dcard_cookie_path: str = "data/dcard_cookies.json"
    max_search_pages: int = 5
    max_board_pages: int = 15
    max_articles: int = 80
    request_delay_sec: float = 1.2
    timeout_sec: int = 20
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # 標題或內文需符合至少一個才算 Lexus 相關
    relevance_keywords: list[str] = field(
        default_factory=lambda: [
            "lexus",
            "凌志",
            "ES300",
            "ES200",
            "ES250",
            "RX350",
            "RX450",
            "NX200",
            "NX350",
            "UX250",
            "IS300",
            "GS350",
            "GS450",
            "LM350",
            "LBX",
            "和泰",
        ]
    )

    service_keywords: list[str] = field(
        default_factory=lambda: [
            "保養",
            "保修",
            "定保",
            "原廠",
            "外廠",
            "保固",
            "保證",
            "零件",
            "維修",
            "服務",
            "報價",
            "道路救援",
            "代步",
            "取送",
        ]
    )
