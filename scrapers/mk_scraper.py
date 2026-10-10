"""Scraper Direktori Putusan Mahkamah Konstitusi RI (mkri.id).

Mendukung ekstraksi pokok perkara, pemohon, amar putusan, dan jenis amar secara konsisten.
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

            all_labels = ["Pokok Perkara", "Pemohon", "Amar Putusan", "Jenis Amar Putusan", "Di Unduh", "Kata Kunci", "File Pendukung"]
            no_perkara = extract_field("No Perkara", ["Pokok Perkara", "Pemohon", "Amar Putusan", "Jenis Amar Putusan", "Di Unduh", "File Pendukung"])
            pokok = extract_field("Pokok Perkara", ["Pemohon", "Amar Putusan", "Jenis Amar Putusan", "Di Unduh", "File Pendukung"])
            pemohon = extract_field("Pemohon", ["Amar Putusan", "Jenis Amar Putusan", "Di Unduh", "File Pendukung"])
            amar = extract_field("Amar Putusan", ["Jenis Amar Putusan", "Di Unduh", "Kata Kunci", "File Pendukung"])
            jenis_amar = extract_field("Jenis Amar Putusan", ["Di Unduh", "Kata Kunci", "File Pendukung"])

            if not no_perkara or no_perkara in ["-", "—"]:
                continue

            yr_m = re.search(r"/(20\d\d)", no_perkara)
            tahun_int = int(yr_m.group(1)) if yr_m else 2026

            # Gabungkan amar dengan jenis amar jika ada
            final_amar = amar
            if jenis_amar and jenis_amar not in amar:
                final_amar = f"[{jenis_amar}] {amar}" if amar else jenis_amar

            item = {
                "source": "mk",
                "lembaga": "MK",
                "sumber_url": url,
                "nomor_perkara": no_perkara,
                "tingkat_proses": "Tingkat Pertama dan Terakhir",
                "klasifikasi": category.upper() if category else "PUU",
                "tahun": tahun_int,
                "judul": f"Putusan MK No. {no_perkara}: {pokok[:120]}..." if pokok else f"Putusan MK No. {no_perkara}",
                "para_pihak": f"Pemohon: {pemohon}" if pemohon else "",
                "majelis_hakim": "Mahkamah Konstitusi RI",
                "amar_putusan": final_amar,
                "tanggal_putus": "",
                "status": "BERKEKUATAN HUKUM TETAP",
                "pdf_url": pdf_url,
                "metadata": {
                    "pokok_perkara": pokok,
                    "pemohon": pemohon,
                    "jenis_amar": jenis_amar,
                },
            }
            items.append(item)

        return items

    @staticmethod
    def extract_amar_from_pdf(pdf_path: Path) -> str:
        """Mengekstrak teks amar putusan MK dari PDF."""
        try:
            reader = PdfReader(str(pdf_path))
            num_pages = len(reader.pages)
            if num_pages == 0:
                return ""
            for p_idx in range(num_pages - 1, max(-1, num_pages - 8), -1):
                text = reader.pages[p_idx].extract_text() or ""
                m = re.search(r'(?:M\s*E\s*N\s*G\s*A\s*D\s*I\s*L\s*I|MENGADILI)\s*[:;]\s*(.*?)(?:Demikianlah|Ditetapkan|$)', text, re.DOTALL | re.IGNORECASE)
                if m:
                    extracted = re.sub(r'\s+', ' ', m.group(1)).strip()
                    if len(extracted) > 10:
                        return extracted[:1000]
        except Exception:
            pass
        return ""

    @staticmethod
    def extract_full_text_from_pdf(pdf_path: Path, max_pages: int = 150) -> str:
        """Mengekstrak seluruh isi salinan putusan MK secara lengkap."""
        try:
            reader = PdfReader(str(pdf_path))
            num_pages = min(len(reader.pages), max_pages)
            if num_pages == 0:
                return ""
            pages_text = []
            for p_idx in range(num_pages):
                raw = (reader.pages[p_idx].extract_text() or "").strip()
                if raw:
                    pages_text.append(raw)
            return "\n\n".join(pages_text)
        except Exception:
            return ""

    @staticmethod
    def extract_tanggal_putus_from_pdf(pdf_path: Path) -> str:
        """Mengekstrak tanggal pengucapan putusan MK dari bagian penutup."""
        try:
            reader = PdfReader(str(pdf_path))
            num_pages = len(reader.pages)
            if num_pages == 0:
                return ""
            for p_idx in range(num_pages - 1, max(-1, num_pages - 5), -1):
                text = reader.pages[p_idx].extract_text() or ""
                # Cari pola tanggal resmi pengucapan putusan sidang pleno
                m = re.search(r"pada hari\s+[A-Za-z]+,\s+tanggal\s+([^,]+,\s+tahun\s+[A-Za-z0-9\s]+?)(?:,|\.|\s+yang diucapkan|$)", text, re.IGNORECASE)
                if m:
                    return re.sub(r'\s+', ' ', m.group(1)).strip()
                m_simple = re.search(r"(\d{1,2}\s+(?:Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember)\s+\d{4})", text, re.IGNORECASE)
                if m_simple:
                    return m_simple.group(1).strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def extract_pdf_summary(pdf_path: Path) -> str:
        return MKScraper.extract_amar_from_pdf(pdf_path)

