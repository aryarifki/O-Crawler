"""O-Crawler Anti-WAF Base Scraper with TLS/JA3 Fingerprinting and Resilient Retries."""
from __future__ import annotations
import os
import sys
import time
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from pypdf import PdfReader
from curl_cffi import requests as cffi_requests


_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

_COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "User-Agent": _DEFAULT_USER_AGENT,
}


class AntiWAFClient:
    """Client Anti-WAF berkecepatan tinggi menggunakan curl_cffi dengan impersonasi TLS Safari 17 / Chrome 120."""

    def __init__(self, cache_name: str = "general", impersonate: str = "safari17_0"):
        self.impersonate = impersonate
        self.cache_path = Path(f"/tmp/.ocrawler_{cache_name}_session_cache.json")
        self.cookie_ttl = 1800  # 30 menit
        self.session = cffi_requests.Session(impersonate=self.impersonate)
        self._load_cached_cookies()

    def _load_cached_cookies(self) -> bool:
        if not self.cache_path.exists():
            return False
        try:
            mtime = self.cache_path.stat().st_mtime
            if (time.time() - mtime) > self.cookie_ttl:
                return False
            with self.cache_path.open("r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached and isinstance(cached, dict):
                self.session.cookies.update(cached)
                return True
        except Exception:
            return False
        return False

    def _save_cached_cookies(self) -> None:
        try:
            cookies_dict = self.session.cookies.get_dict()
            if cookies_dict:
                with self.cache_path.open("w", encoding="utf-8") as f:
                    json.dump(cookies_dict, f)
        except Exception:
            pass

    def warm_up(self, target_url: str, force: bool = False):
        if not force and self._load_cached_cookies():
            return
        try:
            resp = self.session.get(target_url, headers=_COMMON_HEADERS, timeout=20)
            if resp.status_code == 200:
                self._save_cached_cookies()
        except Exception:
            pass

    def get(
        self,
        url: str,
        params: Optional[dict] = None,
        retries: int = 4,
        timeout: int = 25,
        headers: Optional[dict] = None,
    ) -> Optional[cffi_requests.Response]:
        req_headers = {**_COMMON_HEADERS, **(headers or {})}
        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params, headers=req_headers, timeout=timeout)
                if resp.status_code == 200:
                    self._save_cached_cookies()
                    return resp
                elif resp.status_code == 403:
                    alt_imp = "chrome120" if "safari" in self.impersonate else "safari17_0"
                    self.impersonate = alt_imp
                    self.session = cffi_requests.Session(impersonate=self.impersonate)
                    time.sleep(1.5)
                    continue
                elif resp.status_code == 429:
                    wait_time = 5 * (attempt + 1)
                    time.sleep(wait_time)
                    continue
                else:
                    return None
            except Exception:
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        return None

    def download_pdf(self, pdf_url: str, dest_path: Path, timeout: int = 120) -> bool:
        """Mengunduh berkas PDF secara streaming dan memverifikasi integritas (%PDF)."""
        if dest_path.exists() and dest_path.stat().st_size > 1000:
            try:
                reader = PdfReader(str(dest_path))
                if len(reader.pages) > 0:
                    return True
            except Exception:
                dest_path.unlink(missing_ok=True)

        for attempt in range(3):
            try:
                resp = self.session.get(pdf_url, headers=_COMMON_HEADERS, stream=True, timeout=timeout)
                if resp.status_code == 200:
                    with dest_path.open("wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)

                    if dest_path.exists() and dest_path.stat().st_size > 100:
                        try:
                            reader = PdfReader(str(dest_path))
                            if len(reader.pages) > 0:
                                return True
                        except Exception:
                            dest_path.unlink(missing_ok=True)
                            return False
                elif resp.status_code == 429:
                    time.sleep(10 * (attempt + 1))
            except Exception:
                time.sleep(2)
        return False
