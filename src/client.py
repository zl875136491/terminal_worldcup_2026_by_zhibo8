from __future__ import annotations

from typing import Any

import requests

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.zhibo8.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class Zhibo8Client:
    def __init__(self, timeout: float = 12.0) -> None:
        self.timeout = timeout
        self.http = requests.Session()
        self.http.headers.update(COMMON_HEADERS)

    def get_text(self, url: str) -> str:
        response = self.http.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text.strip()

    def get_json(self, url: str) -> Any:
        response = self.http.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.json()
