"""O-Crawler High-Speed Asynchronous Concurrency Engine.

Mengorkestrasi operasi crawling berkecepatan tinggi multi-worker (1-20 concurrency),
menghubungkan scraper ke Database Manager dan Cloudflare R2, serta menyiarkan log
dan progres secara real-time via WebSocket / SSE ke Modern SaaS GUI.
"""
from __future__ import annotations
import os
import sys
import time
import asyncio
import uuid
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Set

from db_manager import DatabaseManager
from scrapers.base import AntiWAFClient
from scrapers.peraturan import PeraturanScraper
from scrapers.ma_scraper import MAScraper
from scrapers.mk_scraper import MKScraper

try:
    from r2_storage import R2StorageClient
except ImportError:
    R2StorageClient = None


class CrawlerEngine:
    """Mesin orkestrasi crawler asinkron dengan worker pool & real-time telemetry."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self.r2 = None
        if R2StorageClient:
            try:
                client = R2StorageClient()
                if client.is_configured():
                    self.r2 = client
            except Exception:
                self.r2 = None

        self.pdf_dir = Path(__file__).resolve().parent / "pdf_downloads"
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

        # State mesin
        self.is_running = False
        self.is_paused = False
        self.current_job_id: Optional[str] = None
        self.current_config: Dict[str, Any] = {}
        self.stats = {
            "total_crawled": 0,
            "total_articles": 0,
            "start_time": 0.0,
            "speed_docs_per_sec": 0.0,
            "status": "IDLE",
        }

        # Event bus untuk WebSocket / UI listeners
        self.listeners: Set[Callable[[Dict[str, Any]], None]] = set()
        self._stop_event = asyncio.Event()

    def add_listener(self, callback: Callable[[Dict[str, Any]], None]):
        self.listeners.add(callback)

    def remove_listener(self, callback: Callable[[Dict[str, Any]], None]):
        self.listeners.discard(callback)

    def broadcast(self, event_type: str, data: Dict[str, Any]):
        event = {
            "type": event_type,
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            **data,
        }
        for cb in list(self.listeners):
            try:
                cb(event)
            except Exception:
                pass

    def log(self, message: str, level: str = "info"):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [{level.upper()}] {message}")
        self.broadcast("log", {"level": level, "message": message})

    def get_status(self) -> Dict[str, Any]:
        elapsed = time.time() - self.stats["start_time"] if self.is_running else 0
        speed = round(self.stats["total_crawled"] / elapsed, 2) if elapsed > 0 else 0.0
        return {
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "job_id": self.current_job_id,
            "status": self.stats["status"],
            "total_crawled": self.stats["total_crawled"],
            "total_articles": self.stats["total_articles"],
            "elapsed_seconds": int(elapsed),
            "speed": f"{speed} dok/dtk",
            "config": self.current_config,
            "r2_active": bool(self.r2 and self.r2.is_configured()),
            "db_type": "PostgreSQL" if self.db.is_postgres else "SQLite",
        }

    async def start_crawl(self, config: Dict[str, Any]) -> str:
        """Memulai crawl job asinkron dengan konfigurasi yang ditentukan."""
        if self.is_running:
            raise RuntimeError("Crawler sedang berjalan. Hentikan job aktif terlebih dahulu.")

        self.is_running = True
        self.is_paused = False
        self._stop_event.clear()
        self.current_job_id = f"job-{uuid.uuid4().hex[:8]}"
        self.current_config = config
        self.stats = {
            "total_crawled": 0,
            "total_articles": 0,
            "start_time": time.time(),
            "speed_docs_per_sec": 0.0,
            "status": "RUNNING",
        }

        source = config.get("source", "peraturan").lower()
        self.db.record_job_start(
            job_id=self.current_job_id,
            source=source,
            category=config.get("category", ""),
            query=config.get("query", ""),
            tahun=str(config.get("tahun", "")),
        )

        self.log(f"🚀 Memulai crawl job [{self.current_job_id}] | Sumber: {source.upper()}", "info")
        self.broadcast("status", self.get_status())

        # Jalankan task di background event loop
        asyncio.create_task(self._run_job(source, config))
        return self.current_job_id

    async def stop_crawl(self):
        if not self.is_running:
            return
        self.log("🛑 Menghentikan crawling...", "warning")
        self._stop_event.set()
        self.is_running = False
        self.stats["status"] = "STOPPED"
        self.broadcast("status", self.get_status())
        if self.current_job_id:
            self.db.record_job_finish(
                self.current_job_id,
                status="STOPPED",
                total_crawled=self.stats["total_crawled"],
            )

    async def _run_job(self, source: str, config: Dict[str, Any]):
        error_msg = ""
        try:
            if source == "peraturan":
                await self._crawl_peraturan(config)
            elif source == "ma":
                await self._crawl_ma(config)
            elif source == "mk":
                await self._crawl_mk(config)
            else:
                self.log(f"❌ Sumber tidak dikenal: {source}", "error")
        except Exception as e:
            error_msg = str(e)
            self.log(f"❌ Error fatal crawler: {e}", "error")
        finally:
            self.is_running = False
            self.stats["status"] = "COMPLETED" if not error_msg and not self._stop_event.is_set() else "STOPPED"
            self.broadcast("status", self.get_status())
            if self.current_job_id:
                self.db.record_job_finish(
                    self.current_job_id,
                    status=self.stats["status"],
                    total_crawled=self.stats["total_crawled"],
                    error=error_msg,
                )
            self.log(
                f"🎉 Job selesai! Total dokumen: {self.stats['total_crawled']} | Total pasal: {self.stats['total_articles']}",
                "success",
            )

    # --- PIPELINE 1: PERATURAN.GO.ID ---
    async def _crawl_peraturan(self, config: Dict[str, Any]):
        scraper = PeraturanScraper()
        category = config.get("category", "uu")
        query = config.get("query", "")
        tahun = str(config.get("tahun", ""))
        start_page = int(config.get("start_page", 1))
        max_pages = int(config.get("pages", 0)) or 1000
        limit = int(config.get("limit", 1000))
        concurrency = int(config.get("concurrency", 5))
        delay = float(config.get("delay", 1.0))
        keep_local_pdf = bool(config.get("keep_local_pdf", False))

        sem = asyncio.Semaphore(concurrency)
        total_seen = 0

        for page in range(start_page, start_page + max_pages):
            if self._stop_event.is_set() or total_seen >= limit:
                break

            self.log(f"🌐 [Peraturan] Mengambil daftar halaman {page}...", "info")
            loop = asyncio.get_running_loop()
            links = await loop.run_in_executor(None, scraper.get_document_links, category, query, tahun, page)

            if not links:
                self.log(f"🏁 Batas akhir dokumen Peraturan tercapai pada halaman {page - 1}.", "info")
                break

            self.log(f"📋 Ditemukan {len(links)} dokumen pada halaman {page}.", "info")

            async def process_link(link: str):
                nonlocal total_seen
                if self._stop_event.is_set() or total_seen >= limit:
                    return

                async with sem:
                    meta = await loop.run_in_executor(None, scraper.scrape_detail, link)
                    if not meta or not meta.get("pdf_url"):
                        return

                    # Smart Skip
                    if self.db.has_completed_regulation(meta):
                        self.log(f"⏩ [Skip] Regulasi '{meta['judul'][:40]}...' sudah lengkap.", "debug")
                        self.stats["total_crawled"] += 1
                        total_seen += 1
                        self.broadcast("progress", self.get_status())
                        return

                    pdf_name = f"{meta['jenis']}_{meta['nomor']}_{meta['tahun']}.pdf".replace("/", "_").replace(" ", "_")
                    dest_pdf = self.pdf_dir / pdf_name
                    meta["pdf_path"] = f"/pdf_downloads/{pdf_name}"

                    # Download PDF
                    ok = await loop.run_in_executor(None, scraper.client.download_pdf, meta["pdf_url"], dest_pdf)
                    articles = []
                    if ok and dest_pdf.exists():
                        articles = await loop.run_in_executor(None, scraper.parse_articles_from_pdf, dest_pdf)

                        # Cloudflare R2
                        if self.r2 and self.r2.is_configured():
                            r2_url = await loop.run_in_executor(None, self.r2.upload_file, dest_pdf, pdf_name)
                            if r2_url:
                                meta["pdf_path"] = f"/api/pdf/{pdf_name}"
                                if not keep_local_pdf:
                                    dest_pdf.unlink(missing_ok=True)

                    # Simpan DB
                    reg_id = self.db.upsert_regulation(meta)
                    art_count = 0
                    if reg_id and articles:
                        art_count = self.db.upsert_articles(reg_id, articles)
                        self.stats["total_articles"] += art_count

                    self.stats["total_crawled"] += 1
                    total_seen += 1
                    self.log(f"✅ [Tersimpan] {meta['judul'][:50]}... ({art_count} pasal)", "success")
                    self.broadcast("item_crawled", {"source": "peraturan", "title": meta["judul"], "id": reg_id})
                    self.broadcast("progress", self.get_status())
                    if delay > 0:
                        await asyncio.sleep(delay / concurrency)

            tasks = [process_link(l) for l in links]
            await asyncio.gather(*tasks)

    # --- PIPELINE 2: MAHKAMAH AGUNG ---
    async def _crawl_ma(self, config: Dict[str, Any]):
        scraper = MAScraper()
        category = config.get("category", "pidana-khusus-1")
        query = config.get("query", "")
        tahun = str(config.get("tahun", ""))
        start_page = int(config.get("start_page", 1))
        max_pages = int(config.get("pages", 0)) or 1000
        limit = int(config.get("limit", 1000))
        concurrency = int(config.get("concurrency", 5))
        delay = float(config.get("delay", 1.0))
        keep_local_pdf = bool(config.get("keep_local_pdf", False))

        sem = asyncio.Semaphore(concurrency)
        total_seen = 0
        loop = asyncio.get_running_loop()

        for page in range(start_page, start_page + max_pages):
            if self._stop_event.is_set() or total_seen >= limit:
                break

            self.log(f"🌐 [MA] Mengambil halaman {page} (Kategori: {category})...", "info")
            links = await loop.run_in_executor(None, scraper.get_document_links, category, query, tahun, page)

            if not links:
                self.log(f"🏁 Batas akhir putusan MA tercapai pada halaman {page - 1}.", "info")
                break

            self.log(f"📋 Ditemukan {len(links)} putusan MA pada halaman {page}.", "info")

            async def process_ma_link(link: str):
                nonlocal total_seen
                if self._stop_event.is_set() or total_seen >= limit:
                    return

                async with sem:
                    meta = await loop.run_in_executor(None, scraper.scrape_detail, link)
                    if not meta:
                        return

                    if self.db.has_court_decision(meta):
                        self.log(f"⏩ [Skip] Putusan MA '{meta['nomor_perkara']}' sudah ada.", "debug")
                        self.stats["total_crawled"] += 1
                        total_seen += 1
                        self.broadcast("progress", self.get_status())
                        return

                    # Download PDF jika ada
                    if meta.get("pdf_url"):
                        pdf_name = f"MA_{meta['nomor_perkara'].replace('/', '_').replace(' ', '_')}.pdf"
                        dest_pdf = self.pdf_dir / pdf_name
                        meta["pdf_path"] = f"/pdf_downloads/{pdf_name}"

                        ok = await loop.run_in_executor(None, scraper.client.download_pdf, meta["pdf_url"], dest_pdf)
                        if ok and dest_pdf.exists():
                            pdf_amar = await loop.run_in_executor(None, scraper.extract_amar_from_pdf, dest_pdf)
                            if pdf_amar:
                                meta["full_text"] = pdf_amar
                                if not meta.get("amar_putusan") or meta["amar_putusan"] in ["—", "-", "", "Lain-lain"]:
                                    meta["amar_putusan"] = pdf_amar

                            if self.r2 and self.r2.is_configured():
                                r2_url = await loop.run_in_executor(None, self.r2.upload_file, dest_pdf, pdf_name)
                                if r2_url:
                                    meta["pdf_path"] = f"/api/pdf/{pdf_name}"
                                    if not keep_local_pdf:
                                        dest_pdf.unlink(missing_ok=True)

                    dec_id = self.db.upsert_court_decision(meta)
                    self.stats["total_crawled"] += 1
                    total_seen += 1
                    self.log(f"✅ [Tersimpan MA] No. {meta['nomor_perkara']} - {meta['amar_putusan'][:35]}", "success")
                    self.broadcast("item_crawled", {"source": "ma", "title": meta["judul"], "id": dec_id})
                    self.broadcast("progress", self.get_status())
                    if delay > 0:
                        await asyncio.sleep(delay / concurrency)

            tasks = [process_ma_link(l) for l in links]
            await asyncio.gather(*tasks)

    # --- PIPELINE 3: MAHKAMAH KONSTITUSI ---
    async def _crawl_mk(self, config: Dict[str, Any]):
        scraper = MKScraper()
        category = config.get("category", "ALL")
        query = config.get("query", "")
        tahun = str(config.get("tahun", ""))
        start_page = int(config.get("start_page", 1))
        max_pages = int(config.get("pages", 0)) or 1000
        limit = int(config.get("limit", 1000))
        concurrency = int(config.get("concurrency", 5))
        delay = float(config.get("delay", 1.0))
        keep_local_pdf = bool(config.get("keep_local_pdf", False))

        sem = asyncio.Semaphore(concurrency)
        total_seen = 0
        loop = asyncio.get_running_loop()

        for page in range(start_page, start_page + max_pages):
            if self._stop_event.is_set() or total_seen >= limit:
                break

            self.log(f"🌐 [MK] Mengambil kartu putusan halaman {page} ({category})...", "info")
            items = await loop.run_in_executor(None, scraper.get_document_items, category, query, tahun, page)

            if not items:
                self.log(f"🏁 Batas akhir putusan MK tercapai pada halaman {page - 1}.", "info")
                break

            self.log(f"📋 Ditemukan {len(items)} putusan MK pada halaman {page}.", "info")

            async def process_mk_item(item: Dict[str, Any]):
                nonlocal total_seen
                if self._stop_event.is_set() or total_seen >= limit:
                    return

                async with sem:
                    if self.db.has_court_decision(item):
                        self.log(f"⏩ [Skip] Putusan MK '{item['nomor_perkara']}' sudah ada.", "debug")
                        self.stats["total_crawled"] += 1
                        total_seen += 1
                        self.broadcast("progress", self.get_status())
                        return

                    if item.get("pdf_url"):
                        pdf_name = f"MK_{item['nomor_perkara'].replace('/', '_').replace(' ', '_')}.pdf"
                        dest_pdf = self.pdf_dir / pdf_name
                        item["pdf_path"] = f"/pdf_downloads/{pdf_name}"

                        ok = await loop.run_in_executor(None, scraper.client.download_pdf, item["pdf_url"], dest_pdf)
                        if ok and dest_pdf.exists():
                            pdf_amar = await loop.run_in_executor(None, scraper.extract_amar_from_pdf, dest_pdf)
                            if pdf_amar:
                                item["full_text"] = pdf_amar
                                if not item.get("amar_putusan") or item["amar_putusan"] in ["—", "-", ""]:
                                    item["amar_putusan"] = pdf_amar

                            if self.r2 and self.r2.is_configured():
                                r2_url = await loop.run_in_executor(None, self.r2.upload_file, dest_pdf, pdf_name)
                                if r2_url:
                                    item["pdf_path"] = f"/api/pdf/{pdf_name}"
                                    if not keep_local_pdf:
                                        dest_pdf.unlink(missing_ok=True)

                    dec_id = self.db.upsert_court_decision(item)
                    self.stats["total_crawled"] += 1
                    total_seen += 1
                    self.log(f"✅ [Tersimpan MK] No. {item['nomor_perkara']} ({item['amar_putusan'][:35]}...)", "success")
                    self.broadcast("item_crawled", {"source": "mk", "title": item["judul"], "id": dec_id})
                    self.broadcast("progress", self.get_status())
                    if delay > 0:
                        await asyncio.sleep(delay / concurrency)

            tasks = [process_mk_item(it) for it in items]
            await asyncio.gather(*tasks)
