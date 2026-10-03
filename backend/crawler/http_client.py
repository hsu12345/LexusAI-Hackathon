from __future__ import annotations

import random
import time
from typing import Any

import requests
from requests import Response

from .config import CrawlConfig

# 429/5xx 屬於暫時性錯誤，值得重試；403 通常是 WAF 直接拒絕（如 Mobile01 的
# Akamai），重試沒有意義，只會浪費時間並增加被判定為攻擊流量的風險。
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RateLimitedClient:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                # 不宣告 br：未安裝 brotli 套件時 requests 無法解壓，會拿到亂碼
                "Accept-Encoding": "gzip, deflate",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Cookie": "over18=1",
            }
        )
        if config.proxy:
            self.session.proxies.update({"http": config.proxy, "https": config.proxy})
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        # 加入隨機抖動，避免固定間隔的請求節奏被行為分析判定為機器人
        jitter = random.uniform(0, self.config.request_delay_sec * 0.4)
        elapsed = time.time() - self._last_request_at
        wait = self.config.request_delay_sec + jitter - elapsed
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, **kwargs: Any) -> Response:
        last_exc: Exception | None = None
        for attempt in range(self.config.request_max_retries + 1):
            self._throttle()
            self._last_request_at = time.time()
            try:
                resp = self.session.get(url, timeout=self.config.timeout_sec, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
            else:
                if resp.status_code not in RETRYABLE_STATUS:
                    resp.raise_for_status()
                    return resp
                last_exc = requests.HTTPError(
                    f"{resp.status_code} retryable error for url: {url}", response=resp
                )

            if attempt < self.config.request_max_retries:
                backoff = (self.config.request_backoff_base ** attempt) + random.uniform(0, 1)
                time.sleep(backoff)

        assert last_exc is not None
        raise last_exc
