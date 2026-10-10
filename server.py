"""O-Crawler FastAPI Application & Real-Time WebSocket Server.

Menyediakan API kontrol, data explorer, streaming log real-time,
serta melayani antarmuka Modern SaaS GUI pada port 8080.
"""
from __future__ import annotations
import os
import sys
import json
import csv
import io
import asyncio
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from db_manager import DatabaseManager
from crawler_engine import CrawlerEngine
from cache import cache, cached, invalidate_cache


app = FastAPI(
    title="O-Crawler SaaS API",
    description="High-Speed Legal Crawler & Ingestion Engine (Peraturan, MA, MK)",
    version="2.0.0",
)

# GZip Middleware (Kompresi JSON besar untuk transfer super cepat ke frontend)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inisialisasi DB dan Engine
db = DatabaseManager()
engine = CrawlerEngine(db=db)

# Folder Web Static
WEB_DIR = Path(__file__).resolve().parent / "web"
WEB_DIR.mkdir(parents=True, exist_ok=True)


class CrawlStartRequest(BaseModel):
    source: str = Field(default="peraturan", description="peraturan | ma | mk")
    category: str = Field(default="", description="Slug kategori")
    query: str = Field(default="", description="Kata kunci pencarian")
    tahun: str = Field(default="", description="Filter tahun")
    start_page: int = Field(default=1, ge=1)
    pages: int = Field(default=0, ge=0)
    limit: int = Field(default=500, ge=1, le=10000)
    concurrency: int = Field(default=5, ge=1, le=20)
    delay: float = Field(default=1.0, ge=0.0, le=30.0)
    keep_local_pdf: bool = Field(default=False)


# --- WEBSOCKET CONNECTION MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_json(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                self.disconnect(connection)


ws_manager = ConnectionManager()

# Sambungkan event bus engine ke WebSocket broadcaster
def on_engine_event(event: dict):
    try:
        # Invalidasi cache data & statistik ketika proses crawling menghasilkan dokumen baru
        evt_type = event.get("type")
        if evt_type in ("complete", "stopped", "error", "item_saved", "saved", "stat_update"):
            invalidate_cache("stats:*")
            invalidate_cache("data:*")
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(ws_manager.broadcast_json(event))
    except Exception:
        pass

engine.add_listener(on_engine_event)


@app.websocket("/ws/crawler")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    # Kirim status inisial saat tersambung
    await websocket.send_text(json.dumps({"type": "status", **engine.get_status()}))
    try:
        while True:
            data = await websocket.receive_text()
            # Dukungan perintah sederhana via WS
            try:
                cmd = json.loads(data)
                if cmd.get("action") == "stop":
                    await engine.stop_crawl()
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# --- REST API ENDPOINTS ---
@app.get("/api/stats")
@cached(ttl_seconds=10, prefix="stats")
async def get_stats():
    """Mengambil metrik statistik dokumen dan job crawler (Cached 10s via L1 Memory + Redis)."""
    stats = db.get_stats()
    stats["engine"] = engine.get_status()
    stats["cache"] = cache.get_stats()
    return stats


@app.get("/api/crawl/status")
async def get_crawl_status():
    """Mengambil status real-time crawler aktif."""
    return engine.get_status()


@app.post("/api/crawl/start")
async def start_crawl(req: CrawlStartRequest):
    """Menjalankan job crawling baru."""
    if engine.is_running:
        raise HTTPException(status_code=400, detail="Crawler sedang berjalan. Hentikan job aktif terlebih dahulu.")
    try:
        invalidate_cache("stats:*")
        invalidate_cache("data:*")
        job_id = await engine.start_crawl(req.dict())
        return {"success": True, "job_id": job_id, "message": f"Crawling sumber '{req.source}' dimulai."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/crawl/stop")
async def stop_crawl():
    """Menghentikan crawling yang sedang berjalan."""
    await engine.stop_crawl()
    invalidate_cache("stats:*")
    return {"success": True, "message": "Perintah stop dikirim."}


@app.get("/api/data/regulations")
@cached(ttl_seconds=60, prefix="data")
async def get_regulations(q: str = "", page: int = 1, limit: int = 25):
    """Mendapatkan daftar regulasi tersimpan (Cached 60s)."""
    offset = (page - 1) * limit
    items = db.query_regulations(q=q, limit=limit, offset=offset)
    return {"page": page, "limit": limit, "items": items, "count": len(items)}


@app.get("/api/data/decisions")
@cached(ttl_seconds=60, prefix="data")
async def get_court_decisions(lembaga: str = "", q: str = "", page: int = 1, limit: int = 25):
    """Mendapatkan daftar putusan peradilan tersimpan (MA/MK) (Cached 60s)."""
    offset = (page - 1) * limit
    items = db.query_court_decisions(lembaga=lembaga, q=q, limit=limit, offset=offset)
    return {"page": page, "limit": limit, "items": items, "count": len(items)}


@app.get("/api/export")
async def export_data(type: str = Query("regulations", pattern="^(regulations|decisions)$"), format: str = Query("json", pattern="^(json|csv)$")):
    """Ekspor data ke format CSV atau JSON."""
    if type == "regulations":
        data = db.query_regulations(limit=5000)
        filename = "o_crawler_regulations"
    else:
        data = db.query_court_decisions(limit=5000)
        filename = "o_crawler_court_decisions"

    if format == "json":
        return Response(
            content=json.dumps(data, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}.json"},
        )
    else:
        # CSV Export
        output = io.StringIO()
        if data:
            writer = csv.DictWriter(output, fieldnames=list(data[0].keys()))
            writer.writeheader()
            writer.writerows(data)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
        )


@app.get("/api/cache/stats")
async def get_cache_stats():
    """Mengambil status metrik diagnostik layer cache."""
    return cache.get_stats()


@app.post("/api/cache/clear")
async def clear_cache():
    """Mengosongkan cache in-memory dan Redis."""
    cache.clear()
    return {"success": True, "message": "Seluruh cache (L1 RAM + L2 Redis) berhasil dibersihkan."}


@app.get("/api/health")
@cached(ttl_seconds=10, prefix="health")
async def health_check():
    """Status kesehatan sistem."""
    return {
        "status": "healthy",
        "app_name": "O-Crawler",
        "version": "2.0.0",
        "database": "PostgreSQL (owlexia_db)" if db.is_postgres else "SQLite Local",
        "r2_storage": bool(engine.r2 and engine.r2.is_configured()),
        "crawler_active": engine.is_running,
        "cache": cache.get_stats(),
    }


PDF_DIR = Path(__file__).resolve().parent / "pdf_downloads"
PDF_DIR.mkdir(parents=True, exist_ok=True)


@app.api_route("/pdf_downloads/{filename}", methods=["GET", "HEAD"])
@app.api_route("/root/O-Crawler/pdf_downloads/{filename}", methods=["GET", "HEAD"])
@app.api_route("/api/pdf/{filename}", methods=["GET", "HEAD"])
async def serve_downloaded_pdf(filename: str):
    """Menyajikan berkas PDF: langsung dari disk jika ada, atau Cloudflare R2 API (Zero-blocking),
    dengan fallback otomatis Redirect (HTTP 302) ke portal dokumen hukum resmi."""
    clean_name = Path(filename).name
    file_path = PDF_DIR / clean_name

    # 1. Cache HIT dari disk lokal (< 1ms)
    if file_path.is_file():
        return FileResponse(
            path=str(file_path),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=\"{clean_name}\"",
                "Cache-Control": "public, max-age=604800, immutable",
                "X-Cache-Status": "HIT_DISK",
            },
        )

    # 2. Ambil dari Cloudflare R2 via REST API resmi (Bypass pemblokiran DNS *.r2.dev dan non-blocking)
    def fetch_from_r2(key: str) -> Optional[tuple[bytes, str]]:
        if not (engine.r2 and engine.r2.is_configured()):
            return None
        target_url = f"{engine.r2.base_api}/{urllib.parse.quote(key)}"
        req = urllib.request.Request(
            target_url,
            headers={
                "Authorization": f"Bearer {engine.r2.api_token}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) O-Crawler/2.0",
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    content = resp.read()
                    ct = resp.headers.get("Content-Type", "application/pdf")
                    return (content, ct)
        except Exception:
            return None
        return None

    r2_data = await asyncio.to_thread(fetch_from_r2, clean_name)
    if r2_data:
        pdf_bytes, content_type = r2_data
        # Simpan ke cache lokal disk secara atomik
        try:
            temp_file = file_path.with_suffix(f".tmp.{os.getpid()}.{int(asyncio.get_event_loop().time()*1000)}")
            temp_file.write_bytes(pdf_bytes)
            os.replace(temp_file, file_path)
        except Exception:
            pass

        return Response(
            content=pdf_bytes,
            media_type=content_type or "application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=\"{clean_name}\"",
                "Cache-Control": "public, max-age=604800",
                "X-Cache-Status": "MISS_R2_API",
            },
        )

    # 3. Fallback: Cari tautan resmi (sumber_url) dari database dan redirect 302 seketika
    sumber_url = await asyncio.to_thread(db.get_sumber_url_by_filename, clean_name)
    if sumber_url:
        return RedirectResponse(url=sumber_url, status_code=302)

    # 4. Berkas benar-benar tidak ditemukan
    raise HTTPException(
        status_code=404,
        detail=f"Berkas PDF '{clean_name}' tidak ditemukan di penyimpanan lokal, Cloudflare R2, maupun tautan sumber resmi."
    )


# Explicit Frontend Handlers with Anti-Caching headers
@app.get("/")
async def serve_index():
    return FileResponse(
        WEB_DIR / "index.html",
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/app.js")
async def serve_app_js():
    return FileResponse(
        WEB_DIR / "app.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/style.css")
async def serve_style_css():
    return FileResponse(
        WEB_DIR / "style.css",
        media_type="text/css",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


# Mount PDF downloads directory
app.mount("/pdf_downloads", StaticFiles(directory=str(PDF_DIR)), name="pdf_downloads")

# Mount Static Frontend
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")


def main():
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    print(f"🚀 Memulai O-Crawler SaaS Server di http://0.0.0.0:{port}")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False, access_log=False)


if __name__ == "__main__":
    main()
