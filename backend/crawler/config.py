from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CrawlConfig:
    """爬蟲設定：關鍵字、看板、速率限制。"""

    # 會「瀏覽最新頁 + 關鍵字搜尋」的看板（Auto／luxury／e-cars 實測不存在，已移除）
    ptt_boards: list[str] = field(default_factory=lambda: ["car", "CarShop"])
    # 只做關鍵字搜尋的看板（非汽車板，瀏覽雜訊太多），只搜 ptt_side_keywords
    ptt_search_only_boards: list[str] = field(
        default_factory=lambda: ["EV", "Gossiping", "Taoyuan", "TaichungBun", "Hsinchu", "Kaohsiung"]
    )
    ptt_side_keywords: list[str] = field(default_factory=lambda: ["lexus", "凌志"])
    # PTT 搜尋每頁 20 篇；car 板搜 lexus 有 1000+ 篇，頁數給多一點
    ptt_search_pages: int = 30
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
            "ES300h",
            "ES200",
            "NX350h",
            "NX200",
            "RX350",
            "RX450h",
            "RX500h",
            "UX250h",
            "UX300e",
            "LBX",
            "LM350h",
            "IS300h",
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
            "凌志",
            "ES300h",
            "RX350",
            "NX350h",
            "UX300h",
            "LBX",
            "LM350h",
        ]
    )
    max_dcard_articles: int = 60
    # 每個 Dcard 看板往回翻的頁數（每頁 30 篇）
    dcard_forum_pages: int = 5
    dcard_headless: bool = False
    dcard_use_edge: bool = True
    dcard_cookie_path: str = "data/dcard_cookies.json"

    # 未登入時 Threads 搜尋含空白的多詞查詢（如「lexus 保養」）會查無結果，只用單一詞；
    # 英文「lexus」多半回傳無關動態，中文「凌志」與車款型號命中率較高
    threads_search_keywords: list[str] = field(
        default_factory=lambda: [
            "凌志",
            "Lexus",
            "ES300h",
            "ES200",
            "RX350",
            "RX350h",
            "RX450h",
            "RX500h",
            "NX350h",
            "NX200",
            "NX250",
            "UX300h",
            "UX250h",
            "LBX",
            "LM350h",
            "IS300h",
        ]
    )
    max_threads_articles: int = 200
    # 每個關鍵字搜尋結果往下捲動的次數，越多抓到的貼文越多
    threads_scroll_rounds: int = 12
    # 實測 Threads 搜尋結果目前不需登入即可瀏覽，預設 headless 即可；
    # 若之後 Threads 又鎖回需登入，搭配 threads_require_login=True 使用
    threads_headless: bool = True
    threads_use_edge: bool = True
    threads_cookie_path: str = "data/threads_cookies.json"
    threads_require_login: bool = False
    # 登入等待逾時（秒）：threads_require_login=True 時，會等使用者在瀏覽器內手動登入
    threads_login_wait_sec: int = 180

    max_search_pages: int = 10
    max_board_pages: int = 30
    max_articles: int = 500
    request_delay_sec: float = 1.2
    timeout_sec: int = 20
    # 請求重試次數與退避基數（秒），用於暫時性錯誤（timeout／429／5xx）
    request_max_retries: int = 3
    request_backoff_base: float = 1.6
    # 例如 http://user:pass@host:port 或 socks5://host:port；
    # 用於繞過 Mobile01 等站台對本機 IP 的封鎖（Akamai WAF 403）
    proxy: str | None = None
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
