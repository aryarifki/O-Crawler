#!/usr/bin/env python3
"""OWLEXIA Anti-WAF Peraturan Crawler & Ingestion Engine.

Mengadopsi metode Anti-WAF dari SMtracker (IDXClient):
1. TLS Fingerprint Impersonation via curl_cffi (Safari 17 / Chrome 120).
2. Session Warming ke halaman navigasi utama.
3. Cookie WAF Caching ke disk (/tmp/.peraturan_session_cache.json, TTL 25m).
4. Auto-rotation profil browser pada respon HTTP 403 & exponential backoff pada 429.
5. Ekstraksi hierarki pasal & direct ingestion ke PostgreSQL (owlexia_db).
"""

from __future__ import annotations
import os
import sys
import time
import json
import re
import argparse
from pathlib import Path
from typing import Optional, Dict, Any, List

# Unbuffered output agar log selalu tampil real-time di terminal/log file
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

import bs4
import psycopg2
from psycopg2.extras import RealDictCursor
from pypdf import PdfReader
from curl_cffi import requests as cffi_requests

try:
    from r2_storage import R2StorageClient
except ImportError:
    R2StorageClient = None

DB_URL = os.getenv("DATABASE_URL", "postgresql://owlexia:owlexia_pass@localhost:5432/owlexia_db")
BASE_URL = "https://peraturan.go.id"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

_NAV_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "User-Agent": _USER_AGENT,
}


class AntiWAFClient:
    """Client Anti-WAF menggunakan curl_cffi dengan impersonasi browser real."""

    _shared_session: Optional[cffi_requests.Session] = None
    _COOKIE_CACHE_PATH: Path = Path("/tmp/.peraturan_session_cache.json")
    _COOKIE_TTL: int = 1500  # 25 menit

    def __init__(self, impersonate: str = "safari17_0"):
        self.impersonate = impersonate
        if AntiWAFClient._shared_session is None:
            AntiWAFClient._shared_session = cffi_requests.Session(impersonate=self.impersonate)
            self.session = AntiWAFClient._shared_session
            self.warm_up_session()
        else:
            self.session = AntiWAFClient._shared_session

    def _load_cached_cookies(self) -> bool:
        """Memuat cookie WAF dari disk cache jika masih segar (< 25 menit)."""
        if not self._COOKIE_CACHE_PATH.exists():
            return False
        try:
            mtime = self._COOKIE_CACHE_PATH.stat().st_mtime
            if (time.time() - mtime) > self._COOKIE_TTL:
                return False
            with self._COOKIE_CACHE_PATH.open("r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached and isinstance(cached, dict):
                self.session.cookies.update(cached)
                print("   🔄 [Anti-WAF] Memuat cookie WAF terverifikasi dari cache disk.")
                return True
        except Exception:
            return False
        return False

    def _save_cached_cookies(self) -> None:
        """Menyimpan cookie WAF ke disk agar eksekusi berikutnya tidak di-challenge."""
        try:
            cookies_dict = self.session.cookies.get_dict()
            if cookies_dict:
                with self._COOKIE_CACHE_PATH.open("w", encoding="utf-8") as f:
                    json.dump(cookies_dict, f)
        except Exception:
            pass

    def _clear_cached_cookies(self) -> None:
        """Menghapus cookie basi dari memori dan disk."""
        try:
            if self._COOKIE_CACHE_PATH.exists():
                self._COOKIE_CACHE_PATH.unlink()
            if hasattr(self, "session") and self.session:
                self.session.cookies.clear()
        except Exception:
            pass

    def warm_up_session(self, force: bool = False):
        """Mampir ke halaman utama untuk memicu penerbitan cookie keamanan WAF."""
        if not force and self._load_cached_cookies():
            return

        try:
            if force:
                self._clear_cached_cookies()
                AntiWAFClient._shared_session = cffi_requests.Session(impersonate=self.impersonate)
                self.session = AntiWAFClient._shared_session

            print(f"   🔥 [Anti-WAF] Melakukan warm-up session dengan profil '{self.impersonate}'...")
            resp = self.session.get(f"{BASE_URL}/uu", headers=_NAV_HEADERS, timeout=20)
            time.sleep(1.0)
            if resp.status_code == 200:
                self._save_cached_cookies()
                print("   ✅ [Anti-WAF] Session warmed up successfully (Cookies didapat).")
        except Exception as e:
            print(f"   ⚠️ [Anti-WAF] Warning saat warm-up sesi: {e}")

    def get(self, url: str, params: Optional[dict] = None, retries: int = 4, timeout: int = 30) -> Optional[cffi_requests.Response]:
        """Request GET anti-WAF dengan retry dan profil fallback."""
        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params, headers=_NAV_HEADERS, timeout=timeout)
                if resp.status_code == 200:
                    self._save_cached_cookies()
                    return resp
                elif resp.status_code == 403:
                    # Rotasi profil impersonasi jika terdeteksi WAF 403
                    alt_imp = "chrome120" if "safari" in self.impersonate else "safari17_0"
                    print(f"   ⚠️ [Anti-WAF] HTTP 403 pada {url}. Merotasi profil browser ke '{alt_imp}' (attempt {attempt + 1}/{retries})...")
                    self.impersonate = alt_imp
                    self.warm_up_session(force=True)
                    time.sleep(2.0)
                    continue
                elif resp.status_code == 429:
                    wait_time = 15 * (attempt + 1)
                    print(f"   ⚠️ [Anti-WAF] HTTP 429 (Rate Limit). Istirahat {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"   ⚠️ [Anti-WAF] HTTP {resp.status_code} pada {url}")
                    return None
            except Exception as e:
                if attempt < retries - 1:
                    wait_retry = 3 * (attempt + 1)
                    print(f"   ⚠️ [Anti-WAF] Error ({e}). Retry dalam {wait_retry}s...")
                    time.sleep(wait_retry)
                else:
                    print(f"   ❌ [Anti-WAF] Gagal mengambil {url}: {e}")
        return None

    def download_pdf(self, pdf_url: str, dest_path: Path, timeout: int = 120) -> bool:
        """Mengunduh berkas PDF secara streaming dengan verifikasi integritas file."""
        if dest_path.exists() and dest_path.stat().st_size > 1000:
            try:
                reader = PdfReader(str(dest_path))
                if len(reader.pages) > 0:
                    return True
            except Exception:
                print(f"   ⚠️ [Anti-WAF] File {dest_path.name} korup/tidak lengkap di disk. Mengunduh ulang...")
                dest_path.unlink(missing_ok=True)

        for attempt in range(3):
            try:
                resp = self.session.get(pdf_url, headers=_NAV_HEADERS, stream=True, timeout=timeout)
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
                            print(f"   ⚠️ [Anti-WAF] Berkas PDF tidak valid atau stream terpotong. Menghapus file...")
                            dest_path.unlink(missing_ok=True)
                            return False
                elif resp.status_code == 429:
                    time.sleep(15 * (attempt + 1))
                else:
                    print(f"   ⚠️ [Anti-WAF] HTTP {resp.status_code} saat download PDF: {pdf_url}")
            except Exception as e:
                print(f"   ⚠️ [Anti-WAF] Error download PDF (attempt {attempt + 1}): {e}")
                time.sleep(3)
        return False


class DatabaseManager:
    """PostgreSQL Manager untuk integrasi langsung ke owlexia_db."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.conn = None

    def connect(self):
        self.conn = psycopg2.connect(self.db_url)
        self.conn.autocommit = True
        print("   🗄️ [PostgreSQL] Terhubung ke owlexia_db.")

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()

    def _create_slug(self, meta: Dict[str, Any]) -> str:
        clean_nomor = str(meta.get("nomor", "1")).lower().replace("/", "-").replace(" ", "-")
        clean_jenis = str(meta.get("jenis", "peraturan")).lower().replace(" ", "-")
        slug = f"{clean_jenis}-no-{clean_nomor}-tahun-{meta.get('tahun', '2026')}"
        slug = re.sub(r"[^a-z0-9\-]", "", slug)
        return re.sub(r"-+", "-", slug).strip("-")

    def has_completed_articles(self, meta: Dict[str, Any]) -> bool:
        """Cek apakah regulasi sudah pernah diproses lengkap dengan pasal di database."""
        slug = self._create_slug(meta)
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT total_pasal FROM regulations WHERE peraturan_id_slug = %s",
                    (slug,)
                )
                row = cur.fetchone()
                if row and row[0] is not None and row[0] > 0:
                    return True
        except Exception:
            pass
        return False

    def upsert_regulation(self, meta: Dict[str, Any]) -> Optional[str]:
        slug = self._create_slug(meta)

        query = """
        INSERT INTO regulations (
            peraturan_id_slug, jenis, nomor, tahun, judul, status,
            sumber_url, pdf_path, metadata, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
        )
        ON CONFLICT (peraturan_id_slug) DO UPDATE SET
            judul = EXCLUDED.judul,
            status = EXCLUDED.status,
            pdf_path = EXCLUDED.pdf_path,
            updated_at = NOW()
        RETURNING id;
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        slug,
                        meta["jenis"],
                        str(meta["nomor"]),
                        int(meta["tahun"]),
                        meta["judul"],
                        meta["status"],
                        meta.get("detail_url", ""),
                        str(meta.get("pdf_path", "")),
                        json.dumps({"source": "anti_waf_crawler"}),
                    ),
                )
                row = cur.fetchone()
                return str(row[0]) if row else None
        except Exception as e:
            print(f"   ❌ [Database] Gagal upsert regulasi: {e}")
            return None

    def upsert_articles(self, reg_id: str, articles: List[Dict[str, Any]]) -> int:
        if not articles:
            return 0

        query = """
        INSERT INTO legal_articles (
            regulation_id, article_number, chapter, part, content,
            explanation, status, keywords, metadata, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
        )
        ON CONFLICT (regulation_id, article_number) DO UPDATE SET
            content = CASE 
                WHEN EXCLUDED.content ILIKE 'cukup jelas%%' AND legal_articles.content NOT ILIKE 'cukup jelas%%' 
                THEN legal_articles.content 
                ELSE EXCLUDED.content 
            END,
            explanation = COALESCE(NULLIF(EXCLUDED.explanation, ''), legal_articles.explanation),
            chapter = COALESCE(NULLIF(EXCLUDED.chapter, ''), legal_articles.chapter),
            part = COALESCE(NULLIF(EXCLUDED.part, ''), legal_articles.part),
            keywords = CASE WHEN array_length(EXCLUDED.keywords, 1) > 0 THEN EXCLUDED.keywords ELSE legal_articles.keywords END,
            status = EXCLUDED.status,
            updated_at = NOW();
        """
        count = 0
        try:
            with self.conn.cursor() as cur:
                for art in articles:
                    cur.execute(
                        query,
                        (
                            reg_id,
                            str(art["article_number"]),
                            art.get("chapter"),
                            art.get("part"),
                            art["content"],
                            art.get("explanation", ""),
                            art.get("status", "BERLAKU"),
                            art.get("keywords", []),
                            json.dumps({}),
                        ),
                    )
                    count += 1
                cur.execute(
                    "UPDATE regulations SET total_pasal = (SELECT COUNT(*) FROM legal_articles WHERE regulation_id = %s) WHERE id = %s",
                    (reg_id, reg_id),
                )
            return count
        except Exception as e:
            print(f"   ❌ [Database] Gagal upsert pasal: {e}")
            return count


def clean_watermarks(text: str) -> str:
    """Membersihkan watermark security paper, header lembaran negara, dan running numbers."""
    text = re.sub(r'SK\s*No\s*\d+[A-Z]?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'PRES\s*!?\s*DEN\s+R\.?EPUBLIK\s+INDONESIA\s*[-_]\s*\d+\s*[-_]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'TAMBAHAN\s+LEMBARAN\s+NEGARA\s+REPUBLIK\s+INDONESIA\s+NOMOR\s+\d+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'LEMBARAN\s+NEGARA\s+REPUBLIK\s+INDONESIA\s+TAHUN\s+\d+\s+NOMOR\s+\d+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\s*[-_]\s*\d+\s*[-_]\s*$', '', text, flags=re.MULTILINE)
    return text


def extract_keywords_from_text(text: str) -> List[str]:
    """Mengekstrak kata kunci esensial dari teks pasal."""
    keywords = set()
    for m in re.findall(r'\"([^\"]{3,40})\"', text):
        clean_kw = m.strip()
        if len(clean_kw) > 3 and not clean_kw.lower().startswith('cukup'):
            keywords.add(clean_kw.lower())

    common_terms = [
        'pidana', 'denda', 'pemerintah pusat', 'pemerintah daerah', 'menteri',
        'presiden', 'ganti rugi', 'izin', 'pengawasan', 'sanksi', 'perencanaan',
        'pelanggaran', 'kewenangan', 'larangan', 'kewajiban', 'hak', 'gugatan'
    ]
    for term in common_terms:
        if re.search(rf'\b{term}\b', text, re.IGNORECASE):
            keywords.add(term)
    return sorted(list(keywords))[:8]


def parse_articles_from_pdf(pdf_path: Path) -> List[Dict[str, Any]]:
    """Mengekstrak teks PDF dan memilahnya menjadi hierarki pasal & bab tanpa kontaminasi penjelasan/lampiran."""
    try:
        reader = PdfReader(str(pdf_path))
        full_text = "\n".join([page.extract_text() or "" for page in reader.pages])
    except Exception as e:
        print(f"   ⚠️ [Parser] Gagal membaca teks PDF: {e}")
        return []

    cleaned_text = clean_watermarks(full_text)

    # Identifikasi Batas Zona
    penj_m = re.search(r'^\s*PENJELASAN\s+(?:ATAS\s+)?(?:UNDANG-UNDANG|PERATURAN|RANCANGAN)', cleaned_text, re.MULTILINE | re.IGNORECASE)
    lamp_m = re.search(r'^\s*LAMPIRAN(?:\s+[IVXLCDM0-9]+|\s*$)', cleaned_text, re.MULTILINE | re.IGNORECASE)

    penj_start = penj_m.start() if penj_m else len(cleaned_text)
    lamp_start = lamp_m.start() if lamp_m else len(cleaned_text)

    batang_end = min(penj_start, lamp_start)
    batang_tubuh_text = cleaned_text[:batang_end]

    penjelasan_text = ""
    if penj_m and penj_start < lamp_start:
        penjelasan_text = cleaned_text[penj_start:lamp_start]

    explanations: Dict[str, str] = {}
    if penjelasan_text:
        penj_pasal_regex = re.compile(r'^\s*Pasal\s+([0-9A-Za-z]+)\s*[\.:]?\s*$', re.MULTILINE | re.IGNORECASE)
        penj_matches = list(penj_pasal_regex.finditer(penjelasan_text))
        for i, m in enumerate(penj_matches):
            raw_num = m.group(1).strip()
            art_num = re.sub(r'([0-9])O$', r'\g<1>0', raw_num)
            start_pos = m.end()
            end_pos = penj_matches[i+1].start() if i+1 < len(penj_matches) else len(penjelasan_text)
            exp_content = re.sub(r'\s+', ' ', clean_watermarks(penjelasan_text[start_pos:end_pos])).strip()
            if exp_content:
                explanations[art_num] = exp_content

    # Normalisasi line break yang terputus (e.g. "Pasal \n 12" -> "Pasal 12")
    normalized_text = re.sub(r"Pasal\s*\n\s*([0-9A-Za-z]+)", r"Pasal \1", batang_tubuh_text, flags=re.IGNORECASE)
    lines = normalized_text.splitlines()

    articles: List[Dict[str, Any]] = []
    current_chapter = ""
    current_part = ""
    current_art_num = ""
    current_content: List[str] = []

    pasal_regex = re.compile(r"^\s*Pasal\s+([0-9A-Za-z]+)\s*[\.:]?\s*$", re.IGNORECASE)
    bab_regex = re.compile(r"^\s*(BAB\s+[IVXLCDM0-9]+.*)$", re.IGNORECASE)
    bagian_regex = re.compile(r"^\s*(Bagian\s+(?:Kesatu|Kedua|Ketiga|Keempat|Kelima|Keenam|Ketujuh|Kedelapan|Kesembilan|Kesepuluh|[A-Za-z0-9]+).*)$", re.IGNORECASE)

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        bab_match = bab_regex.match(line)
        if bab_match:
            current_chapter = bab_match.group(1).strip()
            continue

        bagian_match = bagian_regex.match(line)
        if bagian_match:
            current_part = bagian_match.group(1).strip()
            continue

        pasal_match = pasal_regex.match(line)
        if pasal_match:
            if current_art_num and current_content:
                c_text = " ".join(current_content).strip()
                articles.append({
                    "article_number": current_art_num,
                    "chapter": current_chapter,
                    "part": current_part,
                    "content": c_text,
                    "explanation": explanations.get(current_art_num, ""),
                    "keywords": extract_keywords_from_text(c_text),
                    "status": "BERLAKU",
                })
                current_content = []
            raw_art = pasal_match.group(1).strip()
            current_art_num = re.sub(r'([0-9])O$', r'\g<1>0', raw_art)
            continue

        if current_art_num:
            current_content.append(line)

    if current_art_num and current_content:
        c_text = " ".join(current_content).strip()
        articles.append({
            "article_number": current_art_num,
            "chapter": current_chapter,
            "part": current_part,
            "content": c_text,
            "explanation": explanations.get(current_art_num, ""),
            "keywords": extract_keywords_from_text(c_text),
            "status": "BERLAKU",
        })

    return articles


def scrape_regulation_detail(client: AntiWAFClient, detail_url: str) -> Optional[Dict[str, Any]]:
    """Scrape metadata regulasi dari tabel resmi dan mencari URL download PDF."""
    resp = client.get(detail_url, timeout=25)
    if not resp:
        return None

    soup = bs4.BeautifulSoup(resp.text, "html.parser")
    title = soup.find("title").get_text(strip=True) if soup.find("title") else "Dokumen Hukum"

    pdf_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf") or "/files/" in href:
            pdf_url = href if href.startswith("http") else f"{BASE_URL}{href}"
            break

    jenis = "Undang-Undang"
    nomor = "1"
    tahun = 2026
    status = "BERLAKU"

    # Ambil metadata dari tabel rincian (table#w2 / table#w3)
    for row in soup.find_all("tr"):
        th = row.find("th")
        td = row.find("td")
        if not th or not td:
            continue
        header = th.get_text(strip=True).lower()
        value = td.get_text(strip=True)

        if "jenis/bentuk" in header:
            jenis = value
        elif header == "nomor" or ("nomor" in header and "pengundangan" not in header and "tambahan" not in header):
            nomor = value
        elif header == "tahun" or ("tahun" in header and "pengundangan" not in header):
            try:
                tahun = int(value)
            except ValueError:
                pass
        elif "tentang" in header and len(value) > 3:
            title = value
        elif "status" in header:
            status = "DICABUT" if "dicabut" in value.lower() else "BERLAKU"

    return {
        "judul": title,
        "jenis": jenis,
        "nomor": nomor,
        "tahun": tahun,
        "status": status,
        "pdf_url": pdf_url,
        "detail_url": detail_url,
    }


AVAILABLE_CATEGORIES: Dict[str, Dict[str, str]] = {
    "1": {"slug": "uu", "name": "Undang-Undang (UU)"},
    "2": {"slug": "pp", "name": "Peraturan Pemerintah (PP)"},
    "3": {"slug": "perpres", "name": "Peraturan Presiden (Perpres)"},
    "4": {"slug": "perppu", "name": "Peraturan Pemerintah Pengganti UU (Perppu)"},
    "5": {"slug": "tapmpr", "name": "Ketetapan MPR (TAP MPR)"},
    "6": {"slug": "permen", "name": "Peraturan Menteri (Permen)"},
    "7": {"slug": "permenkumham", "name": "Peraturan Menkumham (Permenkumham)"},
    "8": {"slug": "permenkum", "name": "Peraturan Menteri Hukum (Permenkum)"},
    "9": {"slug": "perban", "name": "Peraturan Badan / Lembaga (Perban)"},
    "10": {"slug": "perda", "name": "Peraturan Daerah (Perda)"},
}


def prompt_interactive_menu() -> tuple[List[str], int, int, float]:
    """Menampilkan menu interaktif terminal agar user dapat memilih kategori peraturan."""
    print("\n" + "=" * 68)
    print("       ⚖️  OWLEXIA ANTI-WAF PERATURAN CRAWLER & ETL ENGINE")
    print("=" * 68)
    print(" Silakan pilih jenis peraturan yang ingin di-crawl:")
    print("-" * 68)
    for key, info in AVAILABLE_CATEGORIES.items():
        print(f"  [{key:>2}] {info['name']:<42} (/{info['slug']})")
    print("  [ A] SEMUA KATEGORI (Crawl seluruh jenis peraturan secara berurutan)")
    print("  [ 0] Keluar")
    print("-" * 68)

    try:
        raw_choice = input(" Masukkan nomor pilihan [1-10 / A / koma untuk multi] (Default: 1 - UU): ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        print("\nOperasi dibatalkan.")
        sys.exit(0)

    if raw_choice == "0":
        print("Keluar.")
        sys.exit(0)

    selected = []
    if raw_choice == "A":
        selected = [c["slug"] for c in AVAILABLE_CATEGORIES.values()]
    elif not raw_choice:
        selected = ["uu"]
    else:
        for item in raw_choice.split(","):
            item = item.strip()
            if item in AVAILABLE_CATEGORIES:
                selected.append(AVAILABLE_CATEGORIES[item]["slug"])
            elif any(c["slug"] == item.lower() for c in AVAILABLE_CATEGORIES.values()):
                selected.append(item.lower())
        if not selected:
            print("⚠️ Pilihan tidak dikenali, otomatis menggunakan default: Undang-Undang (UU)")
            selected = ["uu"]

    # Input halaman mulai
    try:
        p_start_str = input(" Mulai dari halaman [Default: 1]: ").strip()
        start_page = int(p_start_str) if p_start_str.isdigit() and int(p_start_str) > 0 else 1
    except Exception:
        start_page = 1

    # Input jumlah halaman
    try:
        p_max_str = input(" Berapa jumlah halaman [Default: Semua sampai akhir]: ").strip()
        pages = int(p_max_str) if p_max_str.isdigit() and int(p_max_str) > 0 else 0
    except Exception:
        pages = 0

    # Input delay
    try:
        delay_str = input(" Jeda antar request dalam detik [Default: 2.0]: ").strip()
        delay = float(delay_str) if delay_str else 2.0
    except Exception:
        delay = 2.0

    return selected, start_page, pages, delay


def crawl_category(
    client: AntiWAFClient,
    db: Optional[DatabaseManager],
    pdf_dir: Path,
    category: str,
    start_page: int = 1,
    pages: int = 0,
    limit: int = 5000,
    delay: float = 2.0,
    query: str = "",
    tahun: str = "",
    r2: Optional[Any] = None,
    keep_local_pdf: bool = False,
) -> tuple[int, int]:
    """Crawl regulasi untuk kategori tertentu."""
    print("\n" + "=" * 68)
    print(f"🚀 MEMULAI CRAWLER: {category.upper()}")
    print("=" * 68)
    print(f"📂 Kategori       : {category.upper()}")
    print(f"📄 Halaman Mulai  : Halaman {start_page}")
    print(f"📄 Target Halaman : {'Semua sampai akhir' if pages <= 0 else f'{pages} halaman'}")
    print(f"🎯 Batas Limit    : {limit} regulasi")
    print(f"⏱️  Jeda (Delay)   : {delay} detik")
    print("=" * 68 + "\n")

    total_crawled = 0
    total_articles = 0
    prev_page_links: List[str] = []

    # Jika pages <= 0, crawl otomatis sampai habis (maks 2500 halaman)
    max_pages = 2500 if pages <= 0 else pages
    end_page = start_page + max_pages - 1

    for page in range(start_page, end_page + 1):
        if total_crawled >= limit:
            print(f"🎯 Mencapai batas limit {limit} regulasi.")
            break

        if category:
            search_url = f"{BASE_URL}/{category}?page={page}"
        elif query and tahun:
            search_url = f"{BASE_URL}/cariglobal?PeraturanSearch[idglobal]={query}&PeraturanSearch[tahun]={tahun}&page={page}"
        elif query:
            search_url = f"{BASE_URL}/cariglobal?PeraturanSearch[idglobal]={query}&page={page}"
        elif tahun:
            search_url = f"{BASE_URL}/cariglobal?PeraturanSearch[idglobal]={tahun}&page={page}"
        else:
            search_url = f"{BASE_URL}/cariglobal?page={page}"

        print(f"\n🌐 [{category.upper()} - Halaman {page}] Mengambil daftar regulasi: {search_url}")
        resp = client.get(search_url, timeout=25)
        if not resp:
            print(f"   ❌ Gagal memuat halaman {page}. Beralih/selesai.")
            break

        soup = bs4.BeautifulSoup(resp.text, "html.parser")
        detail_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if (href.startswith("/id/") or "/peraturan/" in href) and not href.endswith("#") and href != "/id/":
                full_link = href if href.startswith("http") else f"{BASE_URL}{href}"
                if full_link not in detail_links:
                    detail_links.append(full_link)

        # Jika link kosong atau sama dengan halaman sebelumnya, kita sudah tiba di halaman terakhir
        if not detail_links or detail_links == prev_page_links:
            print(f"   🏁 Mencapai batas akhir peraturan {category.upper()} pada halaman {page - 1}.")
            break
        prev_page_links = detail_links

        print(f"   📋 Ditemukan {len(detail_links)} tautan regulasi.")

        for link in detail_links:
            if total_crawled >= limit:
                break

            print(f"\n--> Memproses: {link}")
            meta = scrape_regulation_detail(client, link)
            if not meta or not meta.get("pdf_url"):
                print("   ⚠️ Lewati: URL PDF tidak ditemukan atau gagal scrape.")
                continue

            # Cek apakah regulasi sudah ada dan lengkap di database
            if db and db.has_completed_articles(meta):
                print(f"   ⏩ [Database] Regulasi '{meta['judul'][:55]}...' sudah ada & lengkap. Lewati.")
                total_crawled += 1
                continue

            pdf_name = Path(meta["pdf_url"].split("?")[0]).name
            dest_pdf = pdf_dir / pdf_name
            meta["pdf_path"] = str(dest_pdf)

            print(f"   ⬇️ Mengunduh PDF: {pdf_name}")
            download_ok = client.download_pdf(meta["pdf_url"], dest_pdf)
            if not download_ok:
                print(f"   ❌ Gagal mengunduh berkas PDF valid: {meta['pdf_url']}")
                continue

            print(f"   ✅ PDF tersimpan: {dest_pdf.name} ({dest_pdf.stat().st_size:,} bytes)")

            # Parsing pasal
            articles = parse_articles_from_pdf(dest_pdf)
            print(f"   📜 Berhasil mengekstrak {len(articles)} pasal.")

            # Unggah berkas ke Cloudflare R2 jika aktif
            if r2 and r2.is_configured():
                print(f"   ☁️ Mengunggah ke Cloudflare R2: {dest_pdf.name}...")
                r2_url = r2.upload_file(dest_pdf, dest_pdf.name)
                if r2_url:
                    meta["pdf_path"] = r2_url
                    print(f"   ☁️ Berhasil disimpan di Cloudflare R2: {r2_url}")
                    if not keep_local_pdf:
                        dest_pdf.unlink(missing_ok=True)
                        print(f"   🧹 Berkas PDF lokal dibersihkan (tersimpan aman di Cloudflare R2)")

            # Ingestion ke database
            if db:
                reg_id = db.upsert_regulation(meta)
                if reg_id:
                    inserted_count = db.upsert_articles(reg_id, articles)
                    total_articles += inserted_count
                    print(f"   🗄️ [PostgreSQL] {inserted_count} pasal di-upsert ke owlexia_db!")

            total_crawled += 1
            if delay > 0:
                time.sleep(delay)

    return total_crawled, total_articles


def main():
    parser = argparse.ArgumentParser(description="OWLEXIA Anti-WAF Crawler & Ingestion Engine")
    parser.add_argument("--category", "-c", default="", help="Kategori peraturan (uu, pp, perpres, perppu, tapmpr, permen, permenkumham, perban, perda, permenkum)")
    parser.add_argument("--query", "-q", default="", help="Kata kunci pencarian")
    parser.add_argument("--tahun", "-t", default="", help="Filter tahun")
    parser.add_argument("--start-page", type=int, default=1, help="Halaman mulai (default: 1)")
    parser.add_argument("--pages", "-p", type=int, default=0, help="Jumlah halaman yang dijelajahi (0 = sampai akhir)")
    parser.add_argument("--limit", "-l", type=int, default=5000, help="Batas maksimum dokumen")
    parser.add_argument("--delay", type=float, default=2.0, help="Jeda antar request dalam detik (default: 2.0)")
    parser.add_argument("--no-db", action="store_true", help="Lewati penyimpanan ke PostgreSQL")
    parser.add_argument("--non-interactive", action="store_true", help="Jalankan langsung tanpa menu interaktif")
    parser.add_argument("--keep-local-pdf", action="store_true", help="Jangan hapus berkas PDF lokal setelah diunggah ke Cloudflare R2")
    args = parser.parse_args()

    # Inisialisasi Cloudflare R2 Client
    r2 = None
    if R2StorageClient:
        try:
            r2 = R2StorageClient()
            if r2.is_configured():
                print(f"☁️  [Cloudflare R2] Terhubung ke bucket '{r2.bucket_name}'. Berkas PDF akan otomatis diunggah.")
            else:
                r2 = None
        except Exception:
            r2 = None

    # Mode interaktif aktif jika dijalankan di terminal (TTY) tanpa flag CLI khusus
    is_interactive = (
        sys.stdin.isatty()
        and not args.non_interactive
        and not any(a in sys.argv for a in ["--category", "-c", "--query", "-q", "--non-interactive"])
    )

    if is_interactive:
        categories, start_page, pages, delay = prompt_interactive_menu()
        limit = args.limit
        no_db = args.no_db
        query = ""
        tahun = ""
    else:
        cat = args.category.strip().lower() or "uu"
        categories = [cat]
        start_page = args.start_page
        pages = args.pages
        delay = args.delay
        limit = args.limit
        no_db = args.no_db
        query = args.query
        tahun = args.tahun

    pdf_dir = Path(__file__).resolve().parent / "pdf_peraturan"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    client = AntiWAFClient(impersonate="safari17_0")

    db = None
    if not no_db:
        db = DatabaseManager(DB_URL)
        db.connect()

    grand_total_crawled = 0
    grand_total_articles = 0

    try:
        for cat in categories:
            crawled, articles = crawl_category(
                client=client,
                db=db,
                pdf_dir=pdf_dir,
                category=cat,
                start_page=start_page,
                pages=pages,
                limit=limit,
                delay=delay,
                query=query,
                tahun=tahun,
                r2=r2,
                keep_local_pdf=args.keep_local_pdf,
            )
            grand_total_crawled += crawled
            grand_total_articles += articles
    finally:
        if db:
            db.close()

    print("\n" + "=" * 68)
    print(f"🎉 SEMUA SELESAI! Grand Total Regulasi: {grand_total_crawled} | Total Pasal Terindeks: {grand_total_articles}")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    main()
