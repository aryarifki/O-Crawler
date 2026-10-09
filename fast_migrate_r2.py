"""Fast Concurrent Migration of PDFs to Cloudflare R2 and PostgreSQL update."""
import os
import sys
import time
import psycopg2
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from r2_storage import R2StorageClient

PDF_DIR = Path(__file__).resolve().parent / "pdf_downloads"
DB_URL = os.getenv("DATABASE_URL", "postgresql://owlexia:owlexia_pass@localhost:5432/owlexia_db")


def process_single_pdf(pdf_path: Path, r2: R2StorageClient):
    filename = pdf_path.name
    file_size = pdf_path.stat().st_size
    r2_url = f"{r2.public_url}/{filename}"

    # Upload to Cloudflare R2
    uploaded = r2.upload_file(pdf_path, filename)
    if not uploaded:
        return {"status": "failed", "file": filename, "error": "upload failed"}

    # Update database
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    reg_affected = 0
    dec_affected = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE regulations
                SET pdf_path = %s, updated_at = NOW()
                WHERE pdf_path LIKE %s OR pdf_path = %s OR pdf_path = %s
                """,
                (r2_url, f"%{filename}", f"/pdf_downloads/{filename}", filename)
            )
            reg_affected = cur.rowcount

            cur.execute(
                """
                UPDATE court_decisions
                SET pdf_path = %s, updated_at = NOW()
                WHERE pdf_path LIKE %s OR pdf_path = %s OR pdf_path = %s
                """,
                (r2_url, f"%{filename}", f"/pdf_downloads/{filename}", filename)
            )
            dec_affected = cur.rowcount
    finally:
        conn.close()

    # Hapus file lokal
    try:
        pdf_path.unlink(missing_ok=True)
        deleted = True
    except Exception:
        deleted = False

    return {
        "status": "success",
        "file": filename,
        "size": file_size,
        "url": r2_url,
        "reg_affected": reg_affected,
        "dec_affected": dec_affected,
        "deleted": deleted
    }


def main():
    r2 = R2StorageClient()
    if not r2.is_configured():
        print("❌ Cloudflare R2 belum terkonfigurasi!")
        sys.exit(1)

    pdf_files = sorted(list(PDF_DIR.glob("*.pdf")) + list(PDF_DIR.glob("*.PDF")))
    total = len(pdf_files)
    print(f"🚀 Memulai migrasi cepat untuk {total} berkas PDF ke Cloudflare R2...")

    success = 0
    failed = 0
    total_bytes = 0
    total_reg = 0
    total_dec = 0

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process_single_pdf, p, r2): p for p in pdf_files}
        done_cnt = 0
        for fut in as_completed(futures):
            done_cnt += 1
            res = fut.result()
            if res["status"] == "success":
                success += 1
                total_bytes += res["size"]
                total_reg += res["reg_affected"]
                total_dec += res["dec_affected"]
                print(f"[{done_cnt}/{total}] ✅ {res['file']} -> R2 CDN (DB: R={res['reg_affected']}, D={res['dec_affected']})")
            else:
                failed += 1
                print(f"[{done_cnt}/{total}] ❌ Gagal: {res['file']}")

    # Final cleanup update di DB untuk semua record yang masih merujuk ke /pdf_downloads/
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
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

        cur.execute(
            """
            UPDATE court_decisions
            SET pdf_path = REPLACE(pdf_path, '/pdf_downloads/', %s || '/'), updated_at = NOW()
            WHERE pdf_path LIKE '/pdf_downloads/%%'
            """,
            (r2.public_url,)
        )
        rem_dec = cur.rowcount
    conn.close()

    elapsed = time.time() - t0
    mb = total_bytes / (1024 * 1024)
    print("=" * 68)
    print(f"🎉 MIGRASI SELESAI dalam {elapsed:.1f} detik!")
    print(f"✅ Sukses: {success} berkas ({mb:.2f} MB)")
    print(f"❌ Gagal : {failed} berkas")
    print(f"🗄️ PostgreSQL Updated: {total_reg + rem_reg} regulasi, {total_dec + rem_dec} putusan")
    print(f"💾 Ruang harddisk VPS dibersihkan.")
    print("=" * 68)


if __name__ == "__main__":
    main()
