"""Scraper Direktori Putusan Mahkamah Konstitusi RI (mkri.id).

Mendukung pencarian putusan pengujian undang-undang (PUU), sengketa kewenangan
lembaga negara (SKLN), dan perselisihan hasil pemilu/pilkada (PHPU/PHPKADA),
serta download berkas PDF dari CDN resmi s.mkri.id.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
import bs4
from pypdf import PdfReader
from scrapers.base import AntiWAFClient


MK_BASE_URL = "https://www.mkri.id"
MK_PUTUSAN_URL = "https://www.mkri.id/perkara/persidangan/putusan"

MK_CATEGORIES = {
    "ALL": "Semua Jenis Perkara",
    "PUU": "Pengujian Undang-Undang (PUU)",
    "SKLN": "Sengketa Kewenangan Lembaga Negara (SKLN)",
    "PHPU": "Perselisihan Hasil Pemilu (PHPU)",
    "PHPKADA": "Perselisihan Hasil Pilkada (PHPKADA)",
}


class MKScraper:
    """Scraper Mahkamah Konstitusi RI."""

    def __init__(self, client: Optional[AntiWAFClient] = None):
        self.client = client or AntiWAFClient(cache_name="mk", impersonate="safari17_0")
        self.client.warm_up(MK_BASE_URL)

    def build_list_url(self, category: str = "", query: str = "", tahun: str = "", page: int = 1) -> str:
        jenis = category.upper() if category and category.upper() in MK_CATEGORIES else "ALL"
        url = f"{MK_PUTUSAN_URL}?jenis={jenis}&page={page}"
        if query:
            url += f"&search={query}"
        return url

    def get_document_items(self, category: str = "", query: str = "", tahun: str = "", page: int = 1) -> List[Dict[str, Any]]:
        """Mengambil data kartu putusan MK langsung dari halaman direktori."""
        url = self.build_list_url(category=category, query=query, tahun=tahun, page=page)
        resp = self.client.get(url, timeout=25)
        if not resp:
            return []

        soup = bs4.BeautifulSoup(resp.text, "html.parser")
        items: List[Dict[str, Any]] = []
        seen_pdfs = set()

        for a in soup.find_all("a", href=lambda h: h and "putusan_mkri" in h):
            pdf_url = a["href"]
            if pdf_url in seen_pdfs:
                continue
            seen_pdfs.add(pdf_url)

            parent = a.find_parent("div")
            while parent and "No Perkara" not in parent.get_text():
                parent = parent.find_parent("div")

            if not parent:
                continue

            text = parent.get_text(" | ", strip=True)

            def extract_field(label: str, next_labels: List[str]) -> str:
                pattern = rf"{label}\s*\|\s*:\s*\|\s*(.*?)(?=\s*\|\s*(?:{'|'.join(next_labels)})\s*\|\s*:|$)"
                m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                return m.group(1).strip() if m else ""

            no_perkara = extract_field("No Perkara", ["Pokok Perkara", "Pemohon", "Amar Putusan", "File Pendukung"])
            pokok = extract_field("Pokok Perkara", ["Pemohon", "Amar Putusan", "File Pendukung"])
            pemohon = extract_field("Pemohon", ["Amar Putusan", "File Pendukung"])
            amar = extract_field("Amar Putusan", ["File Pendukung"])

            # Cari tahun dari nomor perkara (misal: 322/PUU-XXIV/2026 -> 2026)
            yr_m = re.search(r"/(20\d\d)", no_perkara)
            tahun_int = int(yr_m.group(1)) if yr_m else 2026

            item = {
                "source": "mk",
                "lembaga": "MK",
                "sumber_url": url,
                "nomor_perkara": no_perkara or f"Putusan MK {len(items)+1}",
                "tingkat_proses": "Tingkat Pertama dan Terakhir",
                "klasifikasi": category.upper() if category else "PUU",
                "tahun": tahun_int,
                "judul": f"Putusan MK No. {no_perkara}: {pokok[:120]}..." if pokok else f"Putusan MK No. {no_perkara}",
                "para_pihak": f"Pemohon: {pemohon}" if pemohon else "",
                "majelis_hakim": "Mahkamah Konstitusi RI",
                "amar_putusan": amar,
                "tanggal_putus": "",
                "status": "BERKEKUATAN HUKUM TETAP",
                "pdf_url": pdf_url,
                "metadata": {"pokok_perkara": pokok, "pemohon": pemohon},
            }
            items.append(item)

        return items

    @staticmethod
    def extract_pdf_summary(pdf_path: Path) -> str:
        """Mengekstrak teks ringkasan amar dari PDF putusan MK."""
        try:
            reader = PdfReader(str(pdf_path))
            num_pages = len(reader.pages)
            if num_pages == 0:
                return ""
            # Baca halaman terakhir tempat amar putusan diletakkan
            pages_to_read = [max(0, num_pages - 2), max(0, num_pages - 1)]
            text = " ".join([reader.pages[p].extract_text() or "" for p in pages_to_read])
            return text[:4000].strip()
        except Exception:
            return ""
