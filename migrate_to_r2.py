"""Batch Migration Script: Upload Local PDFs to Cloudflare R2 and Update PostgreSQL.

Memindahkan seluruh berkas PDF dari folder lokal /root/Peraturan-Crawler/pdf_peraturan
ke bucket Cloudflare R2 'owlexia-r2', memperbarui kolom pdf_path di PostgreSQL,
dan membersihkan berkas lokal agar harddisk server tetap bersih.
"""
import os
import sys
import psycopg2
from pathlib import Path
from r2_storage import R2StorageClient

PDF_DIR = Path(__file__).resolve().parent / "pdf_peraturan"
DB_URL = os.getenv("DATABASE_URL", "postgresql://owlexia:owlexia_pass@localhost:5432/owlexia_db")


def migrate():
    r2 = R2StorageClient()
    if not r2.is_configured():
        print("❌ Konfigurasi Cloudflare R2 belum lengkap di .env!")
        sys.exit(1)

    print("=" * 68)
    print("☁️  MIGRASI DOKUMEN PDF KE CLOUDFLARE R2")
    print("=" * 68)
    print(f"📦 Target Bucket  : {r2.bucket_name}")
    print(f"🌐 Public Domain  : {r2.public_url}")
    print(f"📂 Folder Asal    : {PDF_DIR}")
    print("=" * 68 + "\n")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True

    pdf_files = list(PDF_DIR.glob("*.pdf")) + list(PDF_DIR.glob("*.PDF"))
    total_files = len(pdf_files)
    print(f"Ditemukan {total_files} berkas PDF lokal untuk dimigrasikan.\n")

    success_count = 0
    skipped_count = 0
    failed_count = 0
    total_bytes_saved = 0

    for idx, pdf_path in enumerate(pdf_files, 1):
        filename = pdf_path.name
        file_size = pdf_path.stat().st_size
        size_mb = file_size / (1024 * 1024)

        print(f"[{idx}/{total_files}] Memproses: {filename} ({size_mb:.2f} MB)...")

        # 1. Upload ke Cloudflare R2
        r2_url = r2.upload_file(pdf_path, filename)
        if not r2_url:
            print(f"   ❌ Gagal mengunggah {filename} ke Cloudflare R2!")
            failed_count += 1
            continue

        # 2. Update PostgreSQL regulations table
        with conn.cursor() as cur:
            # Update matching exact filename or local path
            cur.execute(
                """
                UPDATE regulations
                SET pdf_path = %s, updated_at = NOW()
                WHERE pdf_path = %s 
                   OR pdf_path LIKE %s
                   OR pdf_path = %s
                """,
                (r2_url, str(pdf_path), f"%/{filename}", filename)
            )
            affected = cur.rowcount

        # 3. Hapus berkas lokal setelah sukses
        try:
            pdf_path.unlink()
            total_bytes_saved += file_size
            success_count += 1
            print(f"   ✅ Sukses -> R2: {r2_url} (DB updated: {affected} baris, lokal dihapus)")
        except Exception as e:
            print(f"   ⚠️ Sukses ke R2 tetapi gagal hapus lokal: {e}")
            success_count += 1

    conn.close()

    mb_saved = total_bytes_saved / (1024 * 1024)
    print("\n" + "=" * 68)
    print("🎉 MIGRASI KE CLOUDFLARE R2 SELESAI")
    print("=" * 68)
    print(f"✅ Berhasil Diunggah & Dimigrasikan : {success_count} berkas")
    print(f"❌ Gagal                           : {failed_count} berkas")
    print(f"💾 Ruang Harddisk Lokal Dihemat    : {mb_saved:.2f} MB")
    print(f"🌐 Akses Dokumen                   : {r2.public_url}/<nama-berkas.pdf>")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    migrate()
