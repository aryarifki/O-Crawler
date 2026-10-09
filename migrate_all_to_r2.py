"""Comprehensive Migration Script: Upload all local PDFs to Cloudflare R2 and update PostgreSQL.

Memindahkan seluruh berkas PDF dari folder lokal /root/O-Crawler/pdf_downloads
ke bucket Cloudflare R2 'owlexia-r2', memperbarui kolom pdf_path di tabel regulations
dan court_decisions di PostgreSQL, dan menghapus berkas fisik lokal agar disk VPS bersih.
"""
import os
import sys
import psycopg2
from pathlib import Path
from r2_storage import R2StorageClient

PDF_DIR = Path(__file__).resolve().parent / "pdf_downloads"
DB_URL = os.getenv("DATABASE_URL", "postgresql://owlexia:owlexia_pass@localhost:5432/owlexia_db")


def run_migration():
    r2 = R2StorageClient()
    if not r2.is_configured():
        print("❌ Konfigurasi Cloudflare R2 belum lengkap di .env!")
        sys.exit(1)

    print("=" * 68)
    print("☁️  MIGRASI LENGKAP DOKUMEN PDF KE CLOUDFLARE R2 CDN")
    print("=" * 68)
    print(f"📦 Target Bucket  : {r2.bucket_name}")
    print(f"🌐 Public CDN URL : {r2.public_url}")
    print(f"📂 Folder Asal    : {PDF_DIR}")
    print("=" * 68 + "\n")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True

    pdf_files = sorted(list(PDF_DIR.glob("*.pdf")) + list(PDF_DIR.glob("*.PDF")))
    total_files = len(pdf_files)
    print(f"Ditemukan {total_files} berkas PDF lokal untuk dimigrasikan.\n")

    success_count = 0
    already_r2_count = 0
    failed_count = 0
    total_bytes_saved = 0
    regulations_updated = 0
    decisions_updated = 0

    for idx, pdf_path in enumerate(pdf_files, 1):
        filename = pdf_path.name
        file_size = pdf_path.stat().st_size
        size_mb = file_size / (1024 * 1024)

        print(f"[{idx}/{total_files}] Memproses: {filename} ({size_mb:.2f} MB)...")

        # 1. Cek atau Unggah ke Cloudflare R2
        r2_url = f"{r2.public_url}/{filename}"
        if not r2.file_exists(filename):
            uploaded_url = r2.upload_file(pdf_path, filename)
            if not uploaded_url:
                print(f"   ❌ Gagal mengunggah {filename} ke Cloudflare R2!")
                failed_count += 1
                continue
            r2_url = uploaded_url
            print(f"   ☁️ Diunggah ke R2: {r2_url}")
        else:
            already_r2_count += 1
            print(f"   ℹ️ Sudah ada di R2: {r2_url}")

        # 2. Update PostgreSQL regulations table
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE regulations
                SET pdf_path = %s, updated_at = NOW()
                WHERE pdf_path LIKE %s 
                   OR pdf_path = %s
                   OR pdf_path = %s
                """,
                (r2_url, f"%{filename}", f"/pdf_downloads/{filename}", filename)
            )
            reg_affected = cur.rowcount
            regulations_updated += reg_affected

        # 3. Update PostgreSQL court_decisions table
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE court_decisions
                SET pdf_path = %s, updated_at = NOW()
                WHERE pdf_path LIKE %s 
                   OR pdf_path = %s
                   OR pdf_path = %s
                """,
                (r2_url, f"%{filename}", f"/pdf_downloads/{filename}", filename)
            )
            dec_affected = cur.rowcount
            decisions_updated += dec_affected

        # 4. Hapus berkas lokal setelah sukses
        try:
            pdf_path.unlink()
            total_bytes_saved += file_size
            success_count += 1
            print(f"   ✅ Sukses -> DB updated (Reg: {reg_affected}, Dec: {dec_affected}) | Berkas lokal dihapus.")
        except Exception as e:
            print(f"   ⚠️ Sukses ke R2 tetapi gagal hapus berkas lokal: {e}")
            success_count += 1

    # Update any remaining records that might have filename reference without local file
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE regulations
            SET pdf_path = REPLACE(pdf_path, '/pdf_downloads/', %s || '/'), updated_at = NOW()
            WHERE pdf_path LIKE '/pdf_downloads/%%'
            """,
            (r2.public_url,)
        )
        rem_reg = cur.rowcount
        regulations_updated += rem_reg

        cur.execute(
            """
            UPDATE court_decisions
            SET pdf_path = REPLACE(pdf_path, '/pdf_downloads/', %s || '/'), updated_at = NOW()
            WHERE pdf_path LIKE '/pdf_downloads/%%'
            """,
            (r2.public_url,)
        )
        rem_dec = cur.rowcount
        decisions_updated += rem_dec

    conn.close()

    mb_saved = total_bytes_saved / (1024 * 1024)
    print("\n" + "=" * 68)
    print("🎉 MIGRASI KE CLOUDFLARE R2 SELESAI")
    print("=" * 68)
    print(f"✅ Total Sukses Dimigrasikan : {success_count} berkas")
    print(f"   - Diunggah Baru ke R2     : {success_count - already_r2_count} berkas")
    print(f"   - Sudah Ada di R2         : {already_r2_count} berkas")
    print(f"❌ Gagal                     : {failed_count} berkas")
    print(f"💾 Ruang Harddisk Dihemat    : {mb_saved:.2f} MB")
    print(f"📊 PostgreSQL Baris Update   : {regulations_updated} regulasi, {decisions_updated} putusan")
    print(f"🌐 Akses CDN Publik          : {r2.public_url}/<nama-berkas.pdf>")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    run_migration()
