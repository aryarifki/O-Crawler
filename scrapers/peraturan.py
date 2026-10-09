"""Scraper untuk portal peraturan.go.id (Undang-Undang, PP, Perpres, Permen, Perda, dll.)."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
import bs4
from pypdf import PdfReader
from scrapers.base import AntiWAFClient


BASE_URL = "https://peraturan.go.id"

AVAILABLE_CATEGORIES = {
    "uu": "Undang-Undang (UU)",
    "pp": "Peraturan Pemerintah (PP)",
    "perpres": "Peraturan Presiden (Perpres)",
    "perppu": "Peraturan Pemerintah Pengganti UU (Perppu)",
    "tapmpr": "Ketetapan MPR (TAP MPR)",
    "permen": "Peraturan Menteri (Permen)",
    "permenkumham": "Peraturan Menkumham (Permenkumham)",
    "permenkum": "Peraturan Menteri Hukum (Permenkum)",
    "perban": "Peraturan Badan / Lembaga (Perban)",
    "perda": "Peraturan Daerah (Perda)",
}


class PeraturanScraper:
    """Scraper portal peraturan.go.id."""

    def __init__(self, client: Optional[AntiWAFClient] = None):
        self.client = client or AntiWAFClient(cache_name="peraturan", impersonate="safari17_0")
        self.client.warm_up(f"{BASE_URL}/uu")

    def build_list_url(self, category: str = "", query: str = "", tahun: str = "", page: int = 1) -> str:
        if category and category in AVAILABLE_CATEGORIES:
            return f"{BASE_URL}/{category}?page={page}"
        elif query and tahun:
            return f"{BASE_URL}/cariglobal?PeraturanSearch[idglobal]={query}&PeraturanSearch[tahun]={tahun}&page={page}"
        elif query:
            return f"{BASE_URL}/cariglobal?PeraturanSearch[idglobal]={query}&page={page}"
        elif tahun:
            return f"{BASE_URL}/cariglobal?PeraturanSearch[tahun]={tahun}&page={page}"
        elif category:
            return f"{BASE_URL}/{category}?page={page}"
        return f"{BASE_URL}/cariglobal?page={page}"

    def get_document_links(self, category: str = "", query: str = "", tahun: str = "", page: int = 1) -> List[str]:
        url = self.build_list_url(category=category, query=query, tahun=tahun, page=page)
        resp = self.client.get(url, timeout=25)
        if not resp:
            return []

        soup = bs4.BeautifulSoup(resp.text, "html.parser")
        detail_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if (href.startswith("/id/") or "/peraturan/" in href) and not href.endswith("#") and href != "/id/":
                full_link = href if href.startswith("http") else f"{BASE_URL}{href}"
                if full_link not in detail_links:
                    detail_links.append(full_link)
        return detail_links

    def scrape_detail(self, detail_url: str) -> Optional[Dict[str, Any]]:
        resp = self.client.get(detail_url, timeout=25)
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
            "source": "peraturan",
            "judul": title,
            "jenis": jenis,
            "nomor": nomor,
            "tahun": tahun,
            "status": status,
            "pdf_url": pdf_url,
            "detail_url": detail_url,
        }

    @staticmethod
    def parse_articles_from_pdf(pdf_path: Path) -> List[Dict[str, Any]]:
        """Mengekstrak teks PDF dan memilahnya menjadi hierarki pasal & bab."""
        try:
            reader = PdfReader(str(pdf_path))
            full_text = "\n".join([page.extract_text() or "" for page in reader.pages])
        except Exception:
            return []

        normalized_text = re.sub(r"Pasal\s*\n\s*([0-9A-Za-z]+)", r"Pasal \1", full_text, flags=re.IGNORECASE)
        lines = normalized_text.splitlines()

        articles: List[Dict[str, Any]] = []
        current_chapter = ""
        current_art_num = ""
        current_content: List[str] = []

        pasal_regex = re.compile(r"^\s*Pasal\s+([0-9A-Za-z]+)\s*[\.:]?\s*$", re.IGNORECASE)
        bab_regex = re.compile(r"^\s*(BAB\s+[IVXLCDM0-9]+.*)$", re.IGNORECASE)

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            bab_match = bab_regex.match(line)
            if bab_match:
                current_chapter = bab_match.group(1).strip()
                continue

            pasal_match = pasal_regex.match(line)
            if pasal_match:
                if current_art_num and current_content:
                    articles.append({
                        "article_number": current_art_num,
                        "chapter": current_chapter,
                        "content": " ".join(current_content).strip(),
                    })
                    current_content = []
                current_art_num = pasal_match.group(1).strip()
                continue

            if current_art_num:
                current_content.append(line)

        if current_art_num and current_content:
            articles.append({
                "article_number": current_art_num,
                "chapter": current_chapter,
                "content": " ".join(current_content).strip(),
            })

        return articles
