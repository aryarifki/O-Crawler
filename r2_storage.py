"""Cloudflare R2 Object Storage Integration for OWLEXIA Crawler.

Mengunggah berkas PDF dokumen hukum ke Cloudflare R2 secara streaming
dan menyediakan URL akses publik CDN berbiaya 0 rupiah egress.
"""
import os
import json
import time
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("owlexia.r2")

ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load_env():
    if not ENV_FILE.exists():
        return
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_env()


class R2StorageClient:
    """Manages uploads and verification for Cloudflare R2 Object Storage."""

    def __init__(
        self,
        account_id: Optional[str] = None,
        bucket_name: Optional[str] = None,
        api_token: Optional[str] = None,
        public_url: Optional[str] = None
    ):
        _load_env()
        self.account_id = account_id or os.getenv("R2_ACCOUNT_ID", "")
        self.bucket_name = bucket_name or os.getenv("R2_BUCKET_NAME", "")
        self.api_token = api_token or os.getenv("R2_API_TOKEN", "")
        self.public_url = (public_url or os.getenv("R2_PUBLIC_URL", "")).rstrip("/")
        self.base_api = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/r2/buckets/{self.bucket_name}/objects"

    def is_configured(self) -> bool:
        return bool(self.account_id and self.bucket_name and self.api_token)

    def get_public_url(self, object_name: str) -> str:
        """Menghasilkan URL CDN publik untuk berkas di Cloudflare R2."""
        clean_name = object_name.lstrip("/")
        return f"{self.public_url}/{clean_name}"

    def upload_file(
        self,
        local_path: Path,
        object_name: Optional[str] = None,
        retries: int = 3,
        timeout: int = 120
    ) -> Optional[str]:
        """Mengunggah berkas lokal ke Cloudflare R2 dengan streaming (hemat RAM).
        
        Returns:
            URL publik berkas di Cloudflare R2 jika sukses, atau None jika gagal.
        """
        path = Path(local_path)
        if not path.is_file():
            logger.error(f"Berkas lokal tidak ditemukan: {path}")
            return None

        key = object_name or path.name
        file_size = path.stat().st_size
        target_url = f"{self.base_api}/{urllib.parse.quote(key)}"

        content_type = "application/pdf" if key.lower().endswith(".pdf") else "application/octet-stream"

        for attempt in range(retries):
            try:
                with open(path, "rb") as f:
                    req = urllib.request.Request(target_url, data=f, method="PUT")
                    req.add_header("Authorization", f"Bearer {self.api_token}")
                    req.add_header("Content-Type", content_type)
                    req.add_header("Content-Length", str(file_size))

                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        if res_data.get("success"):
                            pub_url = self.get_public_url(key)
                            return pub_url
                        else:
                            err_msg = res_data.get("errors", [])
                            logger.warning(f"[R2] Upload {key} ditolak: {err_msg}")
            except Exception as e:
                logger.warning(f"[R2] Percobaan upload {key} ke-{attempt + 1} gagal: {e}")
                if attempt < retries - 1:
                    time.sleep(3 * (attempt + 1))

        return None

    def delete_file(self, object_name: str) -> bool:
        """Menghapus berkas dari Cloudflare R2."""
        target_url = f"{self.base_api}/{urllib.parse.quote(object_name)}"
        try:
            req = urllib.request.Request(target_url, method="DELETE")
            req.add_header("Authorization", f"Bearer {self.api_token}")
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return bool(res.get("success"))
        except Exception as e:
            logger.error(f"[R2] Gagal menghapus {object_name}: {e}")
            return False

    def file_exists(self, object_name: str) -> bool:
        """Memeriksa keberadaan berkas di Cloudflare R2."""
        target_url = f"{self.base_api}/{urllib.parse.quote(object_name)}"
        try:
            req = urllib.request.Request(target_url, method="HEAD")
            req.add_header("Authorization", f"Bearer {self.api_token}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            # Fallback ke GET metadata
            try:
                get_req = urllib.request.Request(target_url, method="GET")
                get_req.add_header("Authorization", f"Bearer {self.api_token}")
                with urllib.request.urlopen(get_req, timeout=10) as resp:
                    return resp.status == 200
            except Exception:
                return False
        except Exception:
            return False
