#!/usr/bin/env python3
"""OWLEXIA O-Crawler - Repair & Data Quality Enrichment Script.

Memperbaiki data regulasi dan pasal-pasal yang sebelumnya terkontaminasi:
1. Menghilangkan bug 'Cukup jelas' pada Batang Tubuh dengan memisahkan teks Penjelasan ke kolom explanation.
2. Memisahkan teks Lampiran agar tidak membengkak pada pasal penutup.
3. Membersihkan artefak watermark, nomor halaman, dan security paper.
4. Mengisi array keywords esensial pada legal_articles.
5. Memperbarui total_pasal pada regulations.
"""
from __future__ import annotations
import os
import sys
import re
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor

# Setup path ke project O-Crawler
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from scrapers.peraturan import PeraturanScraper
from db_manager import DatabaseManager

DB_URL = os.getenv("DATABASE_URL", "postgresql://owlexia:owlexia_pass@localhost:5432/owlexia_db")


def repair_local_pdfs():
    print("=" * 60)
    print("🚀 MEMULAI PERBAIKAN DAN ENRICHMENT DATA HUKUM O-CRAWLER")
    print("=" * 60)

    db = DatabaseManager(db_url=DB_URL)
    pdf_dir = PROJECT_DIR / "pdf_downloads"

    if not pdf_dir.exists():
        print(f"❌ Direktori {pdf_dir} tidak ditemukan.")
        return

    pdf_files = list(pdf_dir.glob("*.pdf"))
    print(f"📁 Ditemukan {len(pdf_files)} berkas PDF lokal untuk diperbaiki:")
    for f in pdf_files:
        print(f"   - {f.name} ({f.stat().st_size / 1024 / 1024:.2f} MB)")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True

    fixed_regulations = 0
    total_articles_repaired = 0

    for pdf_path in pdf_files:
        filename = pdf_path.name
        # Match pattern e.g. UNDANG-UNDANG_59_2024.pdf or PERATURAN_PRESIDEN_7_2026.pdf
        m = re.match(r"([A-Za-z_-]+)_([0-9A-Za-z]+)_(\d{4})\.pdf", filename)
        if not m:
            continue

        jenis_raw = m.group(1).replace("_", " ")
        nomor = m.group(2)
        tahun = int(m.group(3))

        print(f"\n🔍 [Memproses] {jenis_raw} No. {nomor} Tahun {tahun} ({filename})...")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, judul, total_pasal FROM regulations WHERE jenis ILIKE %s AND nomor = %s AND tahun = %s LIMIT 1",
                (jenis_raw, nomor, tahun)
            )
            reg = cur.fetchone()

        if not reg:
            print(f"   ⚠️ Regulasi tidak ditemukan di database regulations, lewati.")
            continue

        reg_id = reg["id"]
        print(f"   📄 Ditemukan regulasi ID: {reg_id} | Judul: {reg['judul'][:50]}...")

        # Parse ulang dengan parser baru berzonasi Batang Tubuh & Penjelasan
        articles = PeraturanScraper.parse_articles_from_pdf(pdf_path)
        if not articles:
            print(f"   ⚠️ Gagal mengekstrak pasal dari {filename}.")
            continue

        print(f"   ✅ Berhasil ekstrak {len(articles)} pasal bersih.")

        # Hapus pasal lama yang rusak untuk regulasi ini
        with conn.cursor() as cur:
            cur.execute("DELETE FROM legal_articles WHERE regulation_id = %s", (reg_id,))
            deleted_count = cur.rowcount
            print(f"   🗑️ Menghapus {deleted_count} pasal lama yang terkompromi.")

        # Simpan pasal baru yang bersih
        inserted = db.upsert_articles(reg_id, articles)
        print(f"   ✨ Berhasil menyisipkan {inserted} pasal baru dengan pemisahan penjelasan & keywords.")

        # Verifikasi panjang artikel penutup
        last_art = articles[-1]
        print(f"   📊 Pasal penutup: Pasal {last_art['article_number']} (Panjang: {len(last_art['content'])} char)")
        if last_art.get('explanation'):
            print(f"      Penjelasan pasal penutup: {last_art['explanation'][:60]}...")

        fixed_regulations += 1
        total_articles_repaired += inserted

    conn.close()
    print("\n" + "=" * 60)
    print(f"🎉 SELESAI: {fixed_regulations} regulasi diperbaiki, total {total_articles_repaired} pasal dipulihkan.")
    print("=" * 60)


if __name__ == "__main__":
    repair_local_pdfs()
