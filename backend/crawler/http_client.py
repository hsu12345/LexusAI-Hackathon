from __future__ import annotations

import time
from typing import Any

import requests
from requests import Response

from .config import CrawlConfig


class RateLimitedClient:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                "Cookie": "over18=1",
            }
        )
        self._last_request_at = 0.0

    def get(self, url: str, **kwargs: Any) -> Response:
        elapsed = time.time() - self._last_request_at
        if elapsed < self.config.request_delay_sec:
            time.sleep(self.config.request_delay_sec - elapsed)

        resp = self.session.get(url, timeout=self.config.timeout_sec, **kwargs)
        self._last_request_at = time.time()
        resp.raise_for_status()
        return resp
