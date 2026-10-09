"""Scraper Direktori Putusan Mahkamah Agung RI (putusan3.mahkamahagung.go.id).

Mendukung pencarian berdasarkan kategori, kata kunci, tingkat proses,
serta ekstraksi amar putusan yang konsisten (baik dari tabel web maupun dari PDF).
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
            if page > 1:
                return f"{MA_BASE_URL}/search.html?q={query}&page={page}"
            return f"{MA_BASE_URL}/search.html?q={query}"
        elif category and category in MA_CATEGORIES:
            return f"{MA_BASE_URL}/direktori/index/kategori/{category}{page_suffix}"
        elif category:
            return f"{MA_BASE_URL}/direktori/index/kategori/{category}{page_suffix}"
        else:
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

        # Cek apakah halaman kosong / direktori rusak
        h1 = soup.find(["h1", "h2", "h3"])
        h1_text = h1.get_text(strip=True) if h1 else ""
        if h1_text.lower() == "direktori" and not soup.find_all("tr"):
            return None

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
        amar_ringkas = ""
        amar_lainnya = ""
        catatan_amar = ""
        klasifikasi_val = ""

        for tr in soup.find_all("tr"):
            text = tr.get_text(" | ", strip=True)
            if " | " in text:
                parts = text.split(" | ", 1)
                k = parts[0].lower().strip()
                v = parts[1].strip()

                if k == "nomor" or (k.startswith("nomor") and "register" not in k):
                    if v and v not in ["—", "-"]:
                        meta["nomor_perkara"] = v
                elif "tingkat" in k:
                    meta["tingkat_proses"] = v
                elif "klasifikasi" in k:
                    klasifikasi_val = v.replace("->", "•").replace("|", "•")
                    meta["klasifikasi"] = klasifikasi_val
                elif "kata kunci" in k:
                    meta["metadata"]["kata_kunci"] = v
                elif k == "tahun" or ("tahun" in k and "register" not in k):
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
                elif k == "amar lainnya":
                    if v and v not in ["—", "-"]:
                        amar_lainnya = v
                elif k == "amar":
                    if v and v not in ["—", "-"]:
                        amar_ringkas = v
                elif k == "catatan amar":
                    if v and v not in ["—", "-"]:
                        catatan_amar = v
                elif k == "kaidah":
                    meta["metadata"]["kaidah"] = v
                elif k == "abstrak":
                    meta["metadata"]["abstrak"] = v

        # Validasi nomor perkara: jangan simpan jika tidak ada nomor valid
        if not meta["nomor_perkara"] or meta["nomor_perkara"] in ["-", "—"]:
            return None

        if hakim_parts:
            meta["majelis_hakim"] = "; ".join(hakim_parts)

        # Penentuan Amar Putusan secara prioritas:
        if amar_lainnya:
            meta["amar_putusan"] = amar_lainnya
        elif amar_ringkas and amar_ringkas.lower() != "lain-lain":
            meta["amar_putusan"] = amar_ringkas
        elif catatan_amar:
            meta["amar_putusan"] = catatan_amar

        # Ekstraksi Para Pihak dari H2 atau TR pertama
        h2 = soup.find(["h2", "h3"])
        if h2 and "—" in h2.get_text():
            meta["para_pihak"] = h2.get_text().split("—", 1)[1].strip()
        else:
            for tr in soup.find_all("tr"):
                t = tr.get_text(" ", strip=True)
                if "—" in t and ("Nomor" in t or "Tanggal" in t):
                    meta["para_pihak"] = t.split("—", 1)[1].strip()
                    break

        # Cari URL download PDF
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/pdf/" in href or (href.lower().endswith(".pdf") and "putusan3" in href):
                meta["pdf_url"] = href if href.startswith("http") else f"{MA_BASE_URL}{href}"
                break

        # Susun Judul yang deskriptif dan konsisten
        if meta["para_pihak"]:
            meta["judul"] = f"Putusan MA No. {meta['nomor_perkara']}: {meta['para_pihak']}"
        elif klasifikasi_val:
            meta["judul"] = f"Putusan MA No. {meta['nomor_perkara']} ({klasifikasi_val})"
        else:
            meta["judul"] = f"Putusan MA No. {meta['nomor_perkara']}"

        return meta

    @staticmethod
    def extract_amar_from_pdf(pdf_path: Path) -> str:
        """Mengekstrak blok amar putusan resmi ('M E N G A D I L I' / 'MENGADILI') dari PDF."""
        try:
            reader = PdfReader(str(pdf_path))
            num_pages = len(reader.pages)
            if num_pages == 0:
                return ""
            # Cari dari halaman akhir ke awal (sampai 10 halaman terakhir)
            for p_idx in range(num_pages - 1, max(-1, num_pages - 12), -1):
                text = reader.pages[p_idx].extract_text() or ""
                # Cari blok MENGADILI yang diikuti titik dua (:)
                m = re.search(r'(?:M\s*E\s*N\s*G\s*A\s*D\s*I\s*L\s*I|MENGADILI)\s*[:;]\s*(?:KEMBALI\s*[:;]\s*)?(.*?)(?:Demikianlah|Demikian|Ditetapkan|Panitera Pengganti|Hakim Anggota|$)', text, re.DOTALL | re.IGNORECASE)
                if m:
                    extracted = re.sub(r'\s+', ' ', m.group(1)).strip()
                    if len(extracted) > 15:
                        return extracted[:1000]
        except Exception:
            pass
        return ""

    @staticmethod
    def extract_pdf_summary(pdf_path: Path) -> str:
        """Mengekstrak teks ringkasan amar atau isi putusan dari PDF."""
        return MAScraper.extract_amar_from_pdf(pdf_path)
