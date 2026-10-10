"""O-Crawler Unified Database Layer (PostgreSQL with SQLite Fallback).

Mendukung penyimpanan data regulasi (peraturan.go.id) dan putusan peradilan
(Mahkamah Agung & Mahkamah Konstitusi), serta pelacakan riwayat crawl job.
"""
from __future__ import annotations
import os
import sys
import json
import re
import sqlite3
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


ENV_FILE = Path(__file__).resolve().parent / ".env"

def load_env():
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

load_env()

DEFAULT_DB_URL = os.getenv("DATABASE_URL", "postgresql://owlexia:owlexia_pass@localhost:5432/owlexia_db")
DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent / "ocrawler.db"


class DatabaseManager:
    """Unified Database Manager yang otomatis memilih PostgreSQL jika tersedia,

    atau otomatis beralih ke SQLite lokal untuk zero-configuration desktop mode.
    """

    def __init__(self, db_url: Optional[str] = None):
        load_env()
        self.db_url = db_url or os.getenv("DATABASE_URL", DEFAULT_DB_URL)
        self.is_postgres = False
        self.conn = None
        self.sqlite_path = DEFAULT_SQLITE_PATH
        self._init_connection()

    def _init_connection(self):
        # 1. Coba koneksi ke PostgreSQL jika psycopg2 terpasang
        if PSYCOPG2_AVAILABLE and self.db_url and "postgresql" in self.db_url:
            try:
                self.conn = psycopg2.connect(self.db_url)
                self.conn.autocommit = True
                self.is_postgres = True
                self._init_postgres_schema()
                print("   🗄️ [Database] Terhubung ke PostgreSQL (owlexia_db).")
                return
            except Exception as e:
                print(f"   ⚠️ [Database] PostgreSQL tidak aktif/gagal terhubung ({e}). Beralih ke SQLite lokal...")

        # 2. Fallback ke SQLite
        self.is_postgres = False
        self.conn = sqlite3.connect(str(self.sqlite_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_sqlite_schema()
        print(f"   🗄️ [Database] Mode SQLite aktif ({self.sqlite_path}).")

    def _init_postgres_schema(self):
        with self.conn.cursor() as cur:
            # 1. Tabel regulations
            cur.execute("""
            CREATE TABLE IF NOT EXISTS regulations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                peraturan_id_slug VARCHAR(255) UNIQUE NOT NULL,
                jenis VARCHAR(100) NOT NULL,
                nomor VARCHAR(50) NOT NULL,
                tahun INTEGER NOT NULL,
                judul TEXT NOT NULL,
                status VARCHAR(50) DEFAULT 'BERLAKU',
                sumber_url TEXT,
                pdf_path TEXT,
                total_pasal INTEGER DEFAULT 0,
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_regulations_slug ON regulations(peraturan_id_slug);
            CREATE INDEX IF NOT EXISTS idx_regulations_tahun ON regulations(tahun);
            CREATE INDEX IF NOT EXISTS idx_regulations_jenis ON regulations(jenis);
            """)

            # 2. Tabel legal_articles
            cur.execute("""
            CREATE TABLE IF NOT EXISTS legal_articles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                regulation_id UUID REFERENCES regulations(id) ON DELETE CASCADE,
                article_number VARCHAR(50) NOT NULL,
                chapter VARCHAR(255),
                part VARCHAR(255),
                content TEXT NOT NULL,
                explanation TEXT,
                status VARCHAR(50) DEFAULT 'BERLAKU',
                keywords TEXT[],
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE (regulation_id, article_number)
            );
            CREATE INDEX IF NOT EXISTS idx_articles_reg_id ON legal_articles(regulation_id);
            """)

            # 3. Tabel court_decisions (Putusan MA & MK)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS court_decisions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                putusan_id_slug VARCHAR(255) UNIQUE NOT NULL,
                lembaga VARCHAR(50) NOT NULL,
                nomor_perkara VARCHAR(150) NOT NULL,
                tahun INTEGER,
                tingkat_proses VARCHAR(100),
                klasifikasi VARCHAR(150),
                judul TEXT NOT NULL,
                para_pihak TEXT,
                majelis_hakim TEXT,
                amar_putusan TEXT,
                tanggal_putus VARCHAR(50),
                status VARCHAR(50) DEFAULT 'BERKEKUATAN HUKUM TETAP',
                sumber_url TEXT,
                pdf_path TEXT,
                full_text TEXT,
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_putusan_slug ON court_decisions(putusan_id_slug);
            CREATE INDEX IF NOT EXISTS idx_putusan_lembaga ON court_decisions(lembaga);
            CREATE INDEX IF NOT EXISTS idx_putusan_tahun ON court_decisions(tahun);
            """)

            # 4. Tabel crawl_jobs
            cur.execute("""
            CREATE TABLE IF NOT EXISTS crawl_jobs (
                id SERIAL PRIMARY KEY,
                job_id VARCHAR(64) UNIQUE NOT NULL,
                source VARCHAR(50) NOT NULL,
                category VARCHAR(100),
                query VARCHAR(255),
                tahun VARCHAR(10),
                total_crawled INTEGER DEFAULT 0,
                total_items INTEGER DEFAULT 0,
                status VARCHAR(50) DEFAULT 'RUNNING',
                error_message TEXT,
                started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                finished_at TIMESTAMP WITH TIME ZONE
            );
            """)

    def _init_sqlite_schema(self):
        cur = self.conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS regulations (
            id TEXT PRIMARY KEY,
            peraturan_id_slug TEXT UNIQUE NOT NULL,
            jenis TEXT NOT NULL,
            nomor TEXT NOT NULL,
            tahun INTEGER NOT NULL,
            judul TEXT NOT NULL,
            status TEXT DEFAULT 'BERLAKU',
            sumber_url TEXT,
            pdf_path TEXT,
            total_pasal INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_reg_slug ON regulations(peraturan_id_slug);
        CREATE INDEX IF NOT EXISTS idx_reg_tahun ON regulations(tahun);
        CREATE INDEX IF NOT EXISTS idx_reg_jenis ON regulations(jenis);

        CREATE TABLE IF NOT EXISTS legal_articles (
            id TEXT PRIMARY KEY,
            regulation_id TEXT,
            article_number TEXT NOT NULL,
            chapter TEXT,
            part TEXT,
            content TEXT NOT NULL,
            explanation TEXT,
            status TEXT DEFAULT 'BERLAKU',
            keywords TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT,
            UNIQUE (regulation_id, article_number),
            FOREIGN KEY (regulation_id) REFERENCES regulations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_art_reg ON legal_articles(regulation_id);

        CREATE TABLE IF NOT EXISTS court_decisions (
            id TEXT PRIMARY KEY,
            putusan_id_slug TEXT UNIQUE NOT NULL,
            lembaga TEXT NOT NULL,
            nomor_perkara TEXT NOT NULL,
            tahun INTEGER,
            tingkat_proses TEXT,
            klasifikasi TEXT,
            judul TEXT NOT NULL,
            para_pihak TEXT,
            majelis_hakim TEXT,
            amar_putusan TEXT,
            tanggal_putus TEXT,
            status TEXT DEFAULT 'BERKEKUATAN HUKUM TETAP',
            sumber_url TEXT,
            pdf_path TEXT,
            full_text TEXT,
            metadata TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_putusan_slug ON court_decisions(putusan_id_slug);
        CREATE INDEX IF NOT EXISTS idx_putusan_lembaga ON court_decisions(lembaga);
        CREATE INDEX IF NOT EXISTS idx_putusan_tahun ON court_decisions(tahun);

        CREATE TABLE IF NOT EXISTS crawl_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL,
            category TEXT,
            query TEXT,
            tahun TEXT,
            total_crawled INTEGER DEFAULT 0,
            total_items INTEGER DEFAULT 0,
            status TEXT DEFAULT 'RUNNING',
            error_message TEXT,
            started_at TEXT,
            finished_at TEXT
        );
        """)
        self.conn.commit()

    # --- HELPER SLUG ---
    def create_reg_slug(self, meta: Dict[str, Any]) -> str:
        clean_nomor = str(meta.get("nomor", "1")).lower().replace("/", "-").replace(" ", "-")
        clean_jenis = str(meta.get("jenis", "peraturan")).lower().replace(" ", "-")
        slug = f"{clean_jenis}-no-{clean_nomor}-tahun-{meta.get('tahun', '2026')}"
        slug = re.sub(r"[^a-z0-9\-]", "", slug)
        return re.sub(r"-+", "-", slug).strip("-")

    def create_decision_slug(self, meta: Dict[str, Any]) -> str:
        lembaga = str(meta.get("lembaga", "ma")).lower()
        no_perkara = str(meta.get("nomor_perkara", "1")).lower().replace("/", "-").replace(" ", "-")
        slug = f"{lembaga}-{no_perkara}"
        slug = re.sub(r"[^a-z0-9\-]", "", slug)
        return re.sub(r"-+", "-", slug).strip("-")

    # --- REGULATIONS LOGIC ---
    def has_completed_regulation(self, meta: Dict[str, Any]) -> bool:
        slug = self.create_reg_slug(meta)
        try:
            cur = self.conn.cursor()
            if self.is_postgres:
                cur.execute("SELECT total_pasal FROM regulations WHERE peraturan_id_slug = %s", (slug,))
            else:
                cur.execute("SELECT total_pasal FROM regulations WHERE peraturan_id_slug = ?", (slug,))
            row = cur.fetchone()
            if row and row[0] is not None and row[0] > 0:
                return True
        except Exception:
            pass
        return False

    def upsert_regulation(self, meta: Dict[str, Any]) -> Optional[str]:
        slug = self.create_reg_slug(meta)
        now_iso = datetime.datetime.now().isoformat()
        import uuid
        reg_id = str(uuid.uuid4())

        try:
            cur = self.conn.cursor()
            if self.is_postgres:
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
                cur.execute(
                    query,
                    (
                        slug,
                        meta.get("jenis", "Undang-Undang"),
                        str(meta.get("nomor", "1")),
                        int(meta.get("tahun", 2026)),
                        meta.get("judul", "Dokumen Hukum"),
                        meta.get("status", "BERLAKU"),
                        meta.get("detail_url", ""),
                        str(meta.get("pdf_path", "")),
                        json.dumps(meta.get("metadata", {"source": "peraturan.go.id"})),
                    ),
                )
                row = cur.fetchone()
                return str(row[0]) if row else None
            else:
                # SQLite
                cur.execute("SELECT id FROM regulations WHERE peraturan_id_slug = ?", (slug,))
                row = cur.fetchone()
                if row:
                    reg_id = row[0]
                    cur.execute("""
                    UPDATE regulations SET
                        judul = ?, status = ?, pdf_path = ?, updated_at = ?
                    WHERE id = ?
                    """, (
                        meta.get("judul", "Dokumen Hukum"),
                        meta.get("status", "BERLAKU"),
                        str(meta.get("pdf_path", "")),
                        now_iso,
                        reg_id,
                    ))
                else:
                    cur.execute("""
                    INSERT INTO regulations (
                        id, peraturan_id_slug, jenis, nomor, tahun, judul,
                        status, sumber_url, pdf_path, metadata, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        reg_id,
                        slug,
                        meta.get("jenis", "Undang-Undang"),
                        str(meta.get("nomor", "1")),
                        int(meta.get("tahun", 2026)),
                        meta.get("judul", "Dokumen Hukum"),
                        meta.get("status", "BERLAKU"),
                        meta.get("detail_url", ""),
                        str(meta.get("pdf_path", "")),
                        json.dumps(meta.get("metadata", {"source": "peraturan.go.id"})),
                        now_iso,
                        now_iso,
                    ))
                self.conn.commit()
                return reg_id
        except Exception as e:
            print(f"   ❌ [Database] Gagal upsert regulasi: {e}")
            return None

    def upsert_articles(self, reg_id: str, articles: List[Dict[str, Any]]) -> int:
        if not articles:
            return 0
        count = 0
        import uuid
        now_iso = datetime.datetime.now().isoformat()

        try:
            cur = self.conn.cursor()
            if self.is_postgres:
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
                for art in articles:
                    cur.execute(
                        query,
                        (
                            reg_id,
                            str(art.get("article_number", "1")),
                            art.get("chapter"),
                            art.get("part"),
                            art.get("content", ""),
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
            else:
                for art in articles:
                    art_id = str(uuid.uuid4())
                    art_num = str(art.get("article_number", "1"))
                    cur.execute("""
                    INSERT INTO legal_articles (
                        id, regulation_id, article_number, chapter, part, content,
                        status, keywords, metadata, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(regulation_id, article_number) DO UPDATE SET
                        content = excluded.content,
                        chapter = COALESCE(excluded.chapter, legal_articles.chapter),
                        updated_at = excluded.updated_at
                    """, (
                        art_id,
                        reg_id,
                        art_num,
                        art.get("chapter"),
                        art.get("part"),
                        art.get("content", ""),
                        art.get("status", "BERLAKU"),
                        json.dumps(art.get("keywords", [])),
                        json.dumps({}),
                        now_iso,
                        now_iso,
                    ))
                    count += 1
                cur.execute(
                    "UPDATE regulations SET total_pasal = (SELECT COUNT(*) FROM legal_articles WHERE regulation_id = ?) WHERE id = ?",
                    (reg_id, reg_id),
                )
                self.conn.commit()
            return count
        except Exception as e:
            print(f"   ❌ [Database] Gagal upsert pasal: {e}")
            return count

    # --- COURT DECISIONS (MA & MK) ---
    def has_court_decision(self, meta: Dict[str, Any]) -> bool:
        slug = self.create_decision_slug(meta)
        try:
            cur = self.conn.cursor()
            if self.is_postgres:
                cur.execute("SELECT id FROM court_decisions WHERE putusan_id_slug = %s", (slug,))
            else:
                cur.execute("SELECT id FROM court_decisions WHERE putusan_id_slug = ?", (slug,))
            return bool(cur.fetchone())
        except Exception:
            return False

    def upsert_court_decision(self, meta: Dict[str, Any]) -> Optional[str]:
        slug = self.create_decision_slug(meta)
        import uuid
        dec_id = str(uuid.uuid4())
        now_iso = datetime.datetime.now().isoformat()

        try:
            cur = self.conn.cursor()
            if self.is_postgres:
                query = """
                INSERT INTO court_decisions (
                    putusan_id_slug, lembaga, nomor_perkara, tahun, tingkat_proses,
                    klasifikasi, judul, para_pihak, majelis_hakim, amar_putusan,
                    tanggal_putus, status, sumber_url, pdf_path, full_text, metadata, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (putusan_id_slug) DO UPDATE SET
                    amar_putusan = COALESCE(NULLIF(EXCLUDED.amar_putusan, ''), court_decisions.amar_putusan),
                    pdf_path = COALESCE(EXCLUDED.pdf_path, court_decisions.pdf_path),
                    full_text = CASE 
                        WHEN LENGTH(COALESCE(EXCLUDED.full_text, '')) > LENGTH(COALESCE(court_decisions.full_text, '')) 
                        THEN EXCLUDED.full_text 
                        ELSE COALESCE(court_decisions.full_text, EXCLUDED.full_text) 
                    END,
                    tanggal_putus = COALESCE(NULLIF(EXCLUDED.tanggal_putus, ''), court_decisions.tanggal_putus),
                    metadata = CASE 
                        WHEN EXCLUDED.metadata IS NOT NULL AND EXCLUDED.metadata != '{}'::jsonb 
                        THEN EXCLUDED.metadata 
                        ELSE court_decisions.metadata 
                    END,
                    updated_at = NOW()
                RETURNING id;
                """
                cur.execute(
                    query,
                    (
                        slug,
                        meta.get("lembaga", "MA"),
                        meta.get("nomor_perkara", "-"),
                        int(meta.get("tahun", 2026)) if str(meta.get("tahun", "")).isdigit() else None,
                        meta.get("tingkat_proses", ""),
                        meta.get("klasifikasi", ""),
                        meta.get("judul", f"Putusan {meta.get('nomor_perkara')}"),
                        meta.get("para_pihak", ""),
                        meta.get("majelis_hakim", ""),
                        meta.get("amar_putusan", ""),
                        meta.get("tanggal_putus", ""),
                        meta.get("status", "BERKEKUATAN HUKUM TETAP"),
                        meta.get("sumber_url", ""),
                        str(meta.get("pdf_path", "")),
                        meta.get("full_text", ""),
                        json.dumps(meta.get("metadata", {})),
                    ),
                )
                row = cur.fetchone()
                return str(row[0]) if row else None
            else:
                cur.execute("SELECT id FROM court_decisions WHERE putusan_id_slug = ?", (slug,))
                row = cur.fetchone()
                if row:
                    dec_id = row[0]
                    cur.execute("""
                    UPDATE court_decisions SET
                        amar_putusan = ?, pdf_path = COALESCE(?, pdf_path),
                        full_text = COALESCE(?, full_text), updated_at = ?
                    WHERE id = ?
                    """, (
                        meta.get("amar_putusan", ""),
                        str(meta.get("pdf_path", "")),
                        meta.get("full_text", ""),
                        now_iso,
                        dec_id,
                    ))
                else:
                    cur.execute("""
                    INSERT INTO court_decisions (
                        id, putusan_id_slug, lembaga, nomor_perkara, tahun, tingkat_proses,
                        klasifikasi, judul, para_pihak, majelis_hakim, amar_putusan,
                        tanggal_putus, status, sumber_url, pdf_path, full_text, metadata,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        dec_id,
                        slug,
                        meta.get("lembaga", "MA"),
                        meta.get("nomor_perkara", "-"),
                        int(meta.get("tahun", 2026)) if str(meta.get("tahun", "")).isdigit() else None,
                        meta.get("tingkat_proses", ""),
                        meta.get("klasifikasi", ""),
                        meta.get("judul", f"Putusan {meta.get('nomor_perkara')}"),
                        meta.get("para_pihak", ""),
                        meta.get("majelis_hakim", ""),
                        meta.get("amar_putusan", ""),
                        meta.get("tanggal_putus", ""),
                        meta.get("status", "BERKEKUATAN HUKUM TETAP"),
                        meta.get("sumber_url", ""),
                        str(meta.get("pdf_path", "")),
                        meta.get("full_text", ""),
                        json.dumps(meta.get("metadata", {})),
                        now_iso,
                        now_iso,
                    ))
                self.conn.commit()
                return dec_id
        except Exception as e:
            print(f"   ❌ [Database] Gagal upsert putusan: {e}")
            return None

    # --- STATS & DATA QUERIES ---
    @staticmethod
    def _format_bytes(b: int) -> str:
        if b >= 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024 * 1024):.2f} GB"
        if b >= 1024 * 1024:
            return f"{b / (1024 * 1024):.2f} MB"
        if b >= 1024:
            return f"{b / 1024:.1f} KB"
        return f"{b} B"

    def get_stats(self) -> Dict[str, Any]:
        cur = self.conn.cursor()
        stats = {
            "is_postgres": self.is_postgres,
            "total_regulations": 0,
            "total_articles": 0,
            "total_decisions": 0,
            "decisions_ma": 0,
            "decisions_mk": 0,
            "recent_jobs": [],
            "db_size_bytes": 0,
            "db_size_pretty": "0 KB",
            "pdf_count": 0,
            "pdf_size_bytes": 0,
            "pdf_size_pretty": "0 MB",
        }
        try:
            cur.execute("SELECT COUNT(*) FROM regulations")
            stats["total_regulations"] = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM legal_articles")
            stats["total_articles"] = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM court_decisions")
            stats["total_decisions"] = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM court_decisions WHERE UPPER(lembaga) = 'MA'")
            stats["decisions_ma"] = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM court_decisions WHERE UPPER(lembaga) = 'MK'")
            stats["decisions_mk"] = cur.fetchone()[0] or 0

            # DB File / Schema Size
            if self.is_postgres:
                try:
                    cur.execute("SELECT pg_database_size(current_database())")
                    row = cur.fetchone()
                    sz = row[0] if row else 0
                    stats["db_size_bytes"] = sz
                    stats["db_size_pretty"] = self._format_bytes(sz)
                except Exception:
                    pass
            else:
                try:
                    p = Path(self.sqlite_path)
                    sz = p.stat().st_size if p.exists() else 0
                    stats["db_size_bytes"] = sz
                    stats["db_size_pretty"] = self._format_bytes(sz)
                except Exception:
                    pass

            # Storage Metrics (Prioritaskan Cloudflare R2 Object Storage)
            try:
                from r2_storage import R2StorageClient
                r2 = R2StorageClient()
                if r2.is_configured():
                    r2_info = r2.get_bucket_stats()
                    stats["storage_mode"] = "Cloudflare R2 CDN"
                    stats["pdf_count"] = r2_info.get("total_objects", 0)
                    stats["pdf_size_bytes"] = r2_info.get("total_size_bytes", 0)
                    stats["pdf_size_pretty"] = r2_info.get("total_size_pretty", "0 MB")
                    stats["r2_bucket"] = r2_info.get("bucket_name", "owlexia-r2")
                    stats["r2_public_url"] = r2_info.get("public_url", "")
                    stats["r2_active"] = True
                else:
                    pdf_dir = Path(__file__).resolve().parent / "pdf_downloads"
                    if pdf_dir.exists():
                        pdf_files = [f for f in pdf_dir.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
                        stats["pdf_count"] = len(pdf_files)
                        tot_sz = sum(f.stat().st_size for f in pdf_files)
                        stats["pdf_size_bytes"] = tot_sz
                        stats["pdf_size_pretty"] = self._format_bytes(tot_sz)
                        stats["storage_mode"] = "Penyimpanan Lokal VPS"
                        stats["r2_active"] = False
            except Exception:
                pass


            # Jobs
            cur.execute("SELECT job_id, source, category, query, total_crawled, status, started_at FROM crawl_jobs ORDER BY id DESC LIMIT 5")
            jobs = []
            for row in cur.fetchall():
                if self.is_postgres:
                    jobs.append(dict(row) if isinstance(row, dict) else {
                        "job_id": row[0], "source": row[1], "category": row[2],
                        "query": row[3], "total_crawled": row[4], "status": row[5], "started_at": str(row[6])
                    })
                else:
                    jobs.append(dict(row))
            stats["recent_jobs"] = jobs
        except Exception as e:
            print(f"Error fetching stats: {e}")
        return stats

    def query_regulations(self, q: str = "", limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        results = []
        try:
            if q:
                search_term = f"%{q}%"
                if self.is_postgres:
                    cur.execute(
                        "SELECT id, jenis, nomor, tahun, judul, status, pdf_path, total_pasal, created_at, sumber_url FROM regulations WHERE judul ILIKE %s OR jenis ILIKE %s ORDER BY tahun DESC, nomor DESC LIMIT %s OFFSET %s",
                        (search_term, search_term, limit, offset)
                    )
                else:
                    cur.execute(
                        "SELECT id, jenis, nomor, tahun, judul, status, pdf_path, total_pasal, created_at, sumber_url FROM regulations WHERE judul LIKE ? OR jenis LIKE ? ORDER BY tahun DESC, nomor DESC LIMIT ? OFFSET ?",
                        (search_term, search_term, limit, offset)
                    )
            else:
                if self.is_postgres:
                    cur.execute(
                        "SELECT id, jenis, nomor, tahun, judul, status, pdf_path, total_pasal, created_at, sumber_url FROM regulations ORDER BY tahun DESC, nomor DESC LIMIT %s OFFSET %s",
                        (limit, offset)
                    )
                else:
                    cur.execute(
                        "SELECT id, jenis, nomor, tahun, judul, status, pdf_path, total_pasal, created_at, sumber_url FROM regulations ORDER BY tahun DESC, nomor DESC LIMIT ? OFFSET ?",
                        (limit, offset)
                    )
            
            for row in cur.fetchall():
                results.append(dict(row) if not isinstance(row, tuple) else {
                    "id": str(row[0]), "jenis": row[1], "nomor": row[2], "tahun": row[3],
                    "judul": row[4], "status": row[5], "pdf_path": row[6], "total_pasal": row[7],
                    "created_at": str(row[8]), "sumber_url": row[9] if len(row) > 9 and row[9] else ""
                })
        except Exception as e:
            print(f"Error query regulations: {e}")
        return results

    def query_court_decisions(self, lembaga: str = "", q: str = "", limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        results = []
        try:
            clauses = []
            params = []
            if lembaga:
                clauses.append("UPPER(lembaga) = UPPER(%s)" if self.is_postgres else "UPPER(lembaga) = UPPER(?)")
                params.append(lembaga)
            if q:
                clauses.append("(judul ILIKE %s OR nomor_perkara ILIKE %s OR amar_putusan ILIKE %s)" if self.is_postgres else "(judul LIKE ? OR nomor_perkara LIKE ? OR amar_putusan LIKE ?)")
                q_p = f"%{q}%"
                params.extend([q_p, q_p, q_p])

            where_str = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            query_str = f"SELECT id, lembaga, nomor_perkara, tahun, tingkat_proses, klasifikasi, judul, para_pihak, amar_putusan, tanggal_putus, pdf_path, sumber_url FROM court_decisions {where_str} ORDER BY tahun DESC, id DESC LIMIT {limit} OFFSET {offset}"

            if self.is_postgres:
                cur.execute(query_str, tuple(params))
            else:
                cur.execute(query_str.replace("%s", "?"), tuple(params))

            for row in cur.fetchall():
                results.append(dict(row) if not isinstance(row, tuple) else {
                    "id": str(row[0]), "lembaga": row[1], "nomor_perkara": row[2], "tahun": row[3],
                    "tingkat_proses": row[4], "klasifikasi": row[5], "judul": row[6],
                    "para_pihak": row[7], "amar_putusan": row[8], "tanggal_putus": row[9],
                    "pdf_path": row[10], "sumber_url": row[11] if len(row) > 11 and row[11] else ""
                })
        except Exception as e:
            print(f"Error query court decisions: {e}")
        return results

    def get_sumber_url_by_filename(self, filename: str) -> Optional[str]:
        """Mencari sumber_url resmi dari database berdasarkan nama berkas PDF."""
        clean = Path(filename).name
        try:
            cur = self.conn.cursor()
            search_pattern = f"%{clean}%"
            if self.is_postgres:
                cur.execute(
                    "SELECT sumber_url FROM regulations WHERE pdf_path ILIKE %s AND sumber_url IS NOT NULL AND sumber_url != '' LIMIT 1",
                    (search_pattern,)
                )
                r = cur.fetchone()
                if r:
                    val = r[0] if isinstance(r, tuple) else r.get("sumber_url")
                    if val:
                        return val
                cur.execute(
                    "SELECT sumber_url FROM court_decisions WHERE pdf_path ILIKE %s AND sumber_url IS NOT NULL AND sumber_url != '' LIMIT 1",
                    (search_pattern,)
                )
                d = cur.fetchone()
                if d:
                    val = d[0] if isinstance(d, tuple) else d.get("sumber_url")
                    if val:
                        return val
            else:
                cur.execute(
                    "SELECT sumber_url FROM regulations WHERE pdf_path LIKE ? AND sumber_url IS NOT NULL AND sumber_url != '' LIMIT 1",
                    (search_pattern,)
                )
                r = cur.fetchone()
                if r and r[0]:
                    return r[0]
                cur.execute(
                    "SELECT sumber_url FROM court_decisions WHERE pdf_path LIKE ? AND sumber_url IS NOT NULL AND sumber_url != '' LIMIT 1",
                    (search_pattern,)
                )
                d = cur.fetchone()
                if d and d[0]:
                    return d[0]
        except Exception as e:
            print(f"Error finding sumber_url for {clean}: {e}")
        return None

    # --- JOB TRACKING ---
    def record_job_start(self, job_id: str, source: str, category: str = "", query: str = "", tahun: str = ""):
        now_iso = datetime.datetime.now().isoformat()
        try:
            cur = self.conn.cursor()
            if self.is_postgres:
                cur.execute(
                    "INSERT INTO crawl_jobs (job_id, source, category, query, tahun, started_at) VALUES (%s, %s, %s, %s, %s, NOW())",
                    (job_id, source, category, query, tahun)
                )
            else:
                cur.execute(
                    "INSERT INTO crawl_jobs (job_id, source, category, query, tahun, started_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (job_id, source, category, query, tahun, now_iso)
                )
                self.conn.commit()
        except Exception:
            pass

    def record_job_finish(self, job_id: str, status: str = "COMPLETED", total_crawled: int = 0, error: str = ""):
        now_iso = datetime.datetime.now().isoformat()
        try:
            cur = self.conn.cursor()
            if self.is_postgres:
                cur.execute(
                    "UPDATE crawl_jobs SET status = %s, total_crawled = %s, error_message = %s, finished_at = NOW() WHERE job_id = %s",
                    (status, total_crawled, error, job_id)
                )
            else:
                cur.execute(
                    "UPDATE crawl_jobs SET status = ?, total_crawled = ?, error_message = ?, finished_at = ? WHERE job_id = ?",
                    (status, total_crawled, error, now_iso, job_id)
                )
                self.conn.commit()
        except Exception:
            pass

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
