from __future__ import annotations

import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.http.mount("https://", adapter)
        self.http.mount("http://", adapter)
        self._text_cache: dict[str, tuple[float, str]] = {}

    def get_text(self, url: str, *, cache_ttl: float | None = None) -> str:
        if cache_ttl and cache_ttl > 0:
            cached = self._text_cache.get(url)
            if cached and time.time() - cached[0] < cache_ttl:
                return cached[1]

        response = self.http.get(url, timeout=self.timeout)
        response.raise_for_status()
        text = response.text.strip()
        if cache_ttl and cache_ttl > 0:
            self._text_cache[url] = (time.time(), text)
        return text

    def get_json(self, url: str) -> Any:
        response = self.http.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.json()
