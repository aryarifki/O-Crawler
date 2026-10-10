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
    def clean_watermarks(text: str) -> str:
        """Membersihkan watermark security paper, header lembaran negara, dan running numbers."""
        text = re.sub(r'SK\s*No\s*\d+[A-Z]?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'PRES\s*!?\s*DEN\s+R\.?EPUBLIK\s+INDONESIA\s*[-_]\s*\d+\s*[-_]', '', text, flags=re.IGNORECASE)
        text = re.sub(r'TAMBAHAN\s+LEMBARAN\s+NEGARA\s+REPUBLIK\s+INDONESIA\s+NOMOR\s+\d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'LEMBARAN\s+NEGARA\s+REPUBLIK\s+INDONESIA\s+TAHUN\s+\d+\s+NOMOR\s+\d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^\s*[-_]\s*\d+\s*[-_]\s*$', '', text, flags=re.MULTILINE)
        return text

    @staticmethod
    def extract_keywords_from_text(text: str) -> List[str]:
        """Mengekstrak kata kunci esensial dan frasa bernilai hukum dari teks pasal."""
        keywords = set()
        # Frasa dalam tanda kutip (definisi/terminologi khusus)
        for m in re.findall(r'\"([^\"]{3,40})\"', text):
            clean_kw = m.strip()
            if len(clean_kw) > 3 and not clean_kw.lower().startswith('cukup'):
                keywords.add(clean_kw.lower())

        # Istilah teknis perundang-undangan umum
        common_terms = [
            'pidana', 'denda', 'pemerintah pusat', 'pemerintah daerah', 'menteri',
            'presiden', 'ganti rugi', 'izin', 'pengawasan', 'sanksi', 'perencanaan',
            'pelanggaran', 'kewenangan', 'larangan', 'kewajiban', 'hak', 'gugatan'
        ]
        for term in common_terms:
            if re.search(rf'\b{term}\b', text, re.IGNORECASE):
                keywords.add(term)
        return sorted(list(keywords))[:8]

    @classmethod
    def parse_articles_from_pdf(cls, pdf_path: Path) -> List[Dict[str, Any]]:
        """Mengekstrak teks PDF dengan pemilahan zona Batang Tubuh, Penjelasan, dan Lampiran secara ketat."""
        try:
            reader = PdfReader(str(pdf_path))
            full_text = "\n".join([page.extract_text() or "" for page in reader.pages])
        except Exception:
            return []

        cleaned_text = cls.clean_watermarks(full_text)

        # 1. Identifikasi Batas Zona (Batang Tubuh vs Penjelasan vs Lampiran)
        penj_m = re.search(r'^\s*PENJELASAN\s+(?:ATAS\s+)?(?:UNDANG-UNDANG|PERATURAN|RANCANGAN)', cleaned_text, re.MULTILINE | re.IGNORECASE)
        lamp_m = re.search(r'^\s*LAMPIRAN(?:\s+[IVXLCDM0-9]+|\s*$)', cleaned_text, re.MULTILINE | re.IGNORECASE)

        penj_start = penj_m.start() if penj_m else len(cleaned_text)
        lamp_start = lamp_m.start() if lamp_m else len(cleaned_text)

        # Batang Tubuh berakhir di awal Penjelasan atau Lampiran (mana yang muncul lebih awal)
        batang_end = min(penj_start, lamp_start)
        batang_tubuh_text = cleaned_text[:batang_end]

        # Zona Penjelasan
        penjelasan_text = ""
        if penj_m and penj_start < lamp_start:
            penjelasan_text = cleaned_text[penj_start:lamp_start]

        # 2. Parse Penjelasan Pasal demi Pasal
        explanations: Dict[str, str] = {}
        if penjelasan_text:
            penj_pasal_regex = re.compile(r'^\s*Pasal\s+([0-9A-Za-z]+)\s*[\.:]?\s*$', re.MULTILINE | re.IGNORECASE)
            penj_matches = list(penj_pasal_regex.finditer(penjelasan_text))
            for i, m in enumerate(penj_matches):
                raw_num = m.group(1).strip()
                art_num = re.sub(r'([0-9])O$', r'\g<1>0', raw_num)
                start_pos = m.end()
                end_pos = penj_matches[i+1].start() if i+1 < len(penj_matches) else len(penjelasan_text)
                exp_content = re.sub(r'\s+', ' ', cls.clean_watermarks(penjelasan_text[start_pos:end_pos])).strip()
                if exp_content:
                    explanations[art_num] = exp_content

        # 3. Parse Batang Tubuh
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
                        "keywords": cls.extract_keywords_from_text(c_text),
                        "status": "BERLAKU",
                    })
                    current_content = []
                raw_art = pasal_match.group(1).strip()
                # Normalisasi typo OCR 1O -> 10
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
                "keywords": cls.extract_keywords_from_text(c_text),
                "status": "BERLAKU",
            })

        return articles
