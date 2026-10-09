"""Scraper Direktori Putusan Mahkamah Agung RI (putusan3.mahkamahagung.go.id).

Mendukung pencarian berdasarkan kategori, kata kunci, tingkat proses (Kasasi, PK, dll.),
serta pengunduhan berkas PDF salinan putusan resmi.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
import bs4
from pypdf import PdfReader
from scrapers.base import AntiWAFClient


MA_BASE_URL = "https://putusan3.mahkamahagung.go.id"

MA_CATEGORIES = {
    "pidana-khusus-1": "Pidana Khusus (Korupsi, Narkotika, dll.)",
    "pidana-umum-1": "Pidana Umum",
    "perdata-1": "Perdata",
    "perdata-khusus": "Perdata Khusus (Niaga, Kepailitan, dll.)",
    "tun-1": "Tata Usaha Negara (TUN)",
    "pajak-2": "Pajak",
    "perdata-agama-1": "Perdata Agama",
    "pidana-militer-1": "Pidana Militer",
    "korupsi-1": "Tindak Pidana Korupsi (Tipikor)",
    "narkotika-dan-psikotropika-1": "Narkotika dan Psikotropika",
    "hak-uji-materiil-1": "Hak Uji Materiil (HUM)",
}


class MAScraper:
    """Scraper Mahkamah Agung RI."""

    def __init__(self, client: Optional[AntiWAFClient] = None):
        self.client = client or AntiWAFClient(cache_name="ma", impersonate="safari17_0")
        self.client.warm_up(MA_BASE_URL)

    def build_list_url(self, category: str = "", query: str = "", tahun: str = "", page: int = 1) -> str:
        page_suffix = f"/page/{page}.html" if page > 1 else ".html"
        if query:
            # Search global
            if page > 1:
                return f"{MA_BASE_URL}/search.html?q={query}&page={page}"
            return f"{MA_BASE_URL}/search.html?q={query}"
        elif category and category in MA_CATEGORIES:
            return f"{MA_BASE_URL}/direktori/index/kategori/{category}{page_suffix}"
        elif category:
            return f"{MA_BASE_URL}/direktori/index/kategori/{category}{page_suffix}"
        else:
            # Default ke Kasasi/Putusan Mahkamah Agung
            return f"{MA_BASE_URL}/direktori/index/kategori/pidana-khusus-1{page_suffix}"

    def get_document_links(self, category: str = "", query: str = "", tahun: str = "", page: int = 1) -> List[str]:
        url = self.build_list_url(category=category, query=query, tahun=tahun, page=page)
        resp = self.client.get(url, timeout=25)
        if not resp:
            return []

        soup = bs4.BeautifulSoup(resp.text, "html.parser")
        detail_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/direktori/putusan/" in href and href.endswith(".html"):
                full_link = href if href.startswith("http") else f"{MA_BASE_URL}{href}"
                if full_link not in detail_links:
                    detail_links.append(full_link)
        return detail_links

    def scrape_detail(self, detail_url: str) -> Optional[Dict[str, Any]]:
        resp = self.client.get(detail_url, timeout=25)
        if not resp:
            return None

        soup = bs4.BeautifulSoup(resp.text, "html.parser")

        meta: Dict[str, Any] = {
            "source": "ma",
            "lembaga": "MA",
            "sumber_url": detail_url,
            "nomor_perkara": "-",
            "tingkat_proses": "",
            "klasifikasi": "",
            "tahun": 2026,
            "judul": "Putusan Mahkamah Agung",
            "para_pihak": "",
            "majelis_hakim": "",
            "amar_putusan": "",
            "tanggal_putus": "",
            "status": "BERKEKUATAN HUKUM TETAP",
            "pdf_url": None,
            "metadata": {},
        }

        hakim_parts = []
        for tr in soup.find_all("tr"):
            text = tr.get_text(" | ", strip=True)
            if " | " in text:
                parts = text.split(" | ", 1)
                k = parts[0].lower().strip()
                v = parts[1].strip()

                if "nomor" in k and "register" not in k:
                    meta["nomor_perkara"] = v
                elif "tingkat" in k:
                    meta["tingkat_proses"] = v
                elif "klasifikasi" in k:
                    meta["klasifikasi"] = v
                elif "tahun" in k and "register" not in k:
                    try:
                        meta["tahun"] = int(v)
                    except ValueError:
                        pass
                elif "hakim ketua" in k:
                    hakim_parts.append(f"Ketua: {v}")
                elif "hakim anggota" in k:
                    hakim_parts.append(f"Anggota: {v}")
                elif "panitera" in k:
                    hakim_parts.append(f"Panitera: {v}")
                elif "tanggal" in k and "register" not in k and not meta["tanggal_putus"]:
                    meta["tanggal_putus"] = v
                elif "amar" in k:
                    meta["amar_putusan"] = v

        if hakim_parts:
            meta["majelis_hakim"] = "; ".join(hakim_parts)

        # Cari para pihak dan ringkasan judul
        for el in soup.find_all(["p", "div", "td", "span"]):
            t = el.get_text(strip=True)
            if (" VS " in t or "Penggugat" in t or "Pemohon" in t) and len(t) < 450:
                if "—" in t:
                    meta["para_pihak"] = t.split("—", 1)[1].strip()
                else:
                    meta["para_pihak"] = t
                break

        # Cari URL download PDF
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/pdf/" in href or (href.lower().endswith(".pdf") and "putusan3" in href):
                meta["pdf_url"] = href if href.startswith("http") else f"{MA_BASE_URL}{href}"
                break

        h1 = soup.find(["h1", "h2", "h3"])
        if h1:
            meta["judul"] = h1.get_text(strip=True)
        else:
            meta["judul"] = f"Putusan MA No. {meta['nomor_perkara']}"

        return meta

    @staticmethod
    def extract_pdf_summary(pdf_path: Path) -> str:
        """Mengekstrak teks ringkasan amar atau isi putusan dari PDF."""
        try:
            reader = PdfReader(str(pdf_path))
            num_pages = len(reader.pages)
            if num_pages == 0:
                return ""
            # Ambil halaman awal dan akhir (tempat amar biasanya diletakkan)
            pages_to_read = [0]
            if num_pages > 1:
                pages_to_read.append(num_pages - 1)
            text = " ".join([reader.pages[p].extract_text() or "" for p in pages_to_read])
            return text[:4000].strip()
        except Exception:
            return ""
