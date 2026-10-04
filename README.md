# 🦅 O-Crawler (OWLEXIA Legal Crawler & Ingestion Engine)

[![Status](https://img.shields.io/badge/status-active-success.svg)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)]()
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B%20%7C%2017-336791.svg)]()
[![Cloudflare R2](https://img.shields.io/badge/Cloudflare_R2-Streaming_Storage-F38020.svg)]()
[![Anti-WAF](https://img.shields.io/badge/Anti--WAF-curl__cffi%20TLS%2FJA3-green.svg)]()
[![License](https://img.shields.io/badge/license-ISC-lightgrey.svg)]()

**O-Crawler** adalah mesin *crawler*, *extractor*, dan *pipeline ingestion* dokumen hukum Indonesia modern berbasis Python yang dirancang untuk mengunduh, mengekstrak, dan mengindeks seluruh regulasi resmi dari portal [peraturan.go.id](https://peraturan.go.id).

Proyek ini terintegrasi penuh ke dalam ekosistem kecerdasan artifisial **OWLEXIA Legal AI Agent**. Seluruh pasal perundang-undangan diekstrak secara hierarkis (BAB, Bagian, Nomor Pasal, Isi Teks, dan Penjelasan) ke dalam **PostgreSQL**, sedangkan salinan otentik berkas fisik PDF otomatis diunggah ke **Cloudflare R2 Object Storage** dengan biaya transfer data (*egress*) Rp 0.

---

## 🌟 Fitur Utama

- 🛡️ **Anti-WAF & Cloudflare Bypass**: Menggunakan `curl_cffi` untuk meniru sidik jari TLS/JA3 browser otentik (Safari 17 / Chrome 120), rotasi user-agent otomatis, dan penanganan cookie dinamis.
- 🧙‍♂️ **Interactive Terminal Wizard**: Cukup jalankan `python3 anti_waf_crawler.py` tanpa argumen untuk memunculkan menu interaktif yang mudah dipahami.
- 📜 **Hierarchical Legal Article Parser**: Membedah dokumen PDF secara presisi menggunakan `pypdf`:
  - Menghapus watermark lembaran negara (`SK No ...`, `PRESIDEN REPUBLIK INDONESIA`).
  - Mengekstrak struktur hierarkis BAB, Bagian, Nomor Pasal, teks isi pasal, dan Penjelasan resmi.
- 🗄️ **PostgreSQL Ingestion Pipeline**: Melakukan `UPSERT` langsung ke tabel `regulations` dan `legal_articles` di `owlexia_db`.
- ☁️ **Cloudflare R2 Streaming Storage**: Berkas PDF otomatis diunggah ke Cloudflare R2 secara streaming (hemat RAM), lalu berkas lokal dibersihkan agar harddisk server lokal tidak pernah penuh.
- ⏩ **Smart Skip (Anti-Duplikasi)**: Otomatis mendeteksi dan melewati regulasi yang sudah tersimpan lengkap di database untuk menghemat waktu dan bandwidth.
- 📦 **Batch Migration Utility (`migrate_to_r2.py`)**: Skrip mandiri untuk memigrasikan tumpukan PDF lokal lama ke Cloudflare R2 secara massal.

---

## 🏗️ Arsitektur Sistem

```mermaid
flowchart TD
    A["Portal peraturan.go.id"] -->|Bypass WAF via curl_cffi| B["anti_waf_crawler.py"]
    B -->|Validasi Integritas %PDF-| C{"PDF Valid?"}
    C -->|Gagal / Corrupt| D["Auto Retry & Rotasi Profil"]
    D --> B
    C -->|Valid| E["Ekstraksi Teks (pypdf)"]
    E -->|BAB, Pasal, Penjelasan| F[("PostgreSQL: owlexia_db")]
    E -->|Streaming Upload| G["Cloudflare R2 Bucket (owlexia-r2)"]
    G -->|Update URL Publik CDN| F
    G -->|Hapus Berkas Lokal| H["Disk Server Bersih (0 MB)"]
    F -->|Retrieval & Penalaran IRAC| I["OWLEXIA Legal AI Agent"]
```

---

## 📋 Prasyarat Sistem

- **Python**: v3.10 atau lebih baru
- **PostgreSQL**: v15+ (direkomendasikan v17)
- **Akun Cloudflare R2**: (Kredensial S3-compatible API token)

---

## 🚀 Instalasi & Persiapan

### 1. Clone Repositori
```bash
git clone git@github.com:aryarifki/O-Crawler.git
cd O-Crawler
```

### 2. Buat & Aktifkan Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Konfigurasi Lingkungan (`.env`)
Salin file template `env.example`:
```bash
cp env.example .env
```
Sesuaikan nilai konfigurasi:
```env
# Koneksi Database PostgreSQL
DATABASE_URL=postgresql://owlexia:owlexia_pass@localhost:5432/owlexia_db

# Konfigurasi Cloudflare R2
R2_ACCOUNT_ID=your_cloudflare_account_id
R2_BUCKET_NAME=owlexia-r2
R2_API_TOKEN=your_r2_api_token
R2_PUBLIC_URL=https://pub-xxxxxx.r2.dev
```

---

## 📖 Panduan Penggunaan

### 1. Mode Interaktif (Wizard Paling Praktis)
Jalankan skrip langsung di terminal Anda:
```bash
python3 anti_waf_crawler.py
```
Anda akan disambut oleh menu pemilihan kategori peraturan:
```text
====================================================================
🏛️  OWLEXIA REGULATION CRAWLER - PILIH KATEGORI PERATURAN
====================================================================
 [1]  UU          - Undang-Undang
 [2]  PP          - Peraturan Pemerintah
 [3]  PERPRES     - Peraturan Presiden
 [4]  PERPPU      - Peraturan Pemerintah Pengganti Undang-Undang
 [5]  TAPMPR      - Ketetapan MPR
 [6]  PERMEN      - Peraturan Menteri
 [7]  PERMENKUMHAM- Peraturan Menteri Hukum dan HAM
 [8]  PERMENKUM   - Peraturan Menteri Hukum
 [9]  PERBAN      - Peraturan Badan / Lembaga
 [10] PERDA       - Peraturan Daerah
 [11] ALL         - Tarik SEMUA Jenis Peraturan Sekaligus
====================================================================
 Pilih nomor jenis peraturan [1-11]: 1
 Halaman mulai [Default: 1]: 1
 Jumlah halaman [0 = Jelajahi sampai akhir]: 10
 Jeda antar request dalam detik [Default: 2.0]: 2.0
```

---

## ⚡ Mode Perintah CLI (Otomasi & Scripting)
Gunakan flag CLI untuk keperluan background task atau cron job:

```bash
# Menarik 10 halaman Undang-Undang (UU)
python3 anti_waf_crawler.py --category uu --start-page 1 --pages 10 --limit 500

# Menarik peraturan berdasarkan kata kunci dan tahun tertentu
python3 anti_waf_crawler.py --query "perpajakan" --tahun 2026 --pages 5

# Menarik semua regulasi tanpa menghapus berkas fisik PDF di lokal
python3 anti_waf_crawler.py --category pp --keep-local-pdf

# Menjalankan crawling di latar belakang (Background Process)
nohup python3 -u anti_waf_crawler.py --category uu --pages 50 --delay 2.5 > crawler.log 2>&1 &
```

### Parameter CLI Lengkap:
| Opsi | Tipe | Default | Deskripsi |
| :--- | :--- | :--- | :--- |
| `--category`, `-c` | string | `"uu"` | Kategori peraturan (`uu`, `pp`, `perpres`, `perppu`, `tapmpr`, `permen`, dll.) |
| `--query`, `-q` | string | `""` | Kata kunci pencarian spesifik |
| `--tahun`, `-t` | string | `""` | Filter tahun pengundangan |
| `--start-page` | integer | `1` | Halaman awal pagination |
| `--pages`, `-p` | integer | `0` | Jumlah halaman (`0` = jelajahi sampai halaman terakhir) |
| `--limit`, `-l` | integer | `5000` | Batas maksimum regulasi yang diproses |
| `--delay` | float | `2.0` | Jeda (detik) antar request untuk keamanan WAF |
| `--keep-local-pdf` | flag | `false` | Jangan hapus PDF lokal setelah berhasil diunggah ke Cloudflare R2 |
| `--no-db` | flag | `false` | Hanya unduh dan parse tanpa menyimpan ke PostgreSQL |
| `--non-interactive` | flag | `false` | Lewati menu wizard interaktif |

---

## 🗃️ Migrasi Dokumen Massal ke Cloudflare R2 (`migrate_to_r2.py`)
Jika Anda memiliki berkas PDF lokal yang sebelumnya tersimpan di folder `pdf_peraturan/`:
```bash
python3 migrate_to_r2.py
```
Skrip ini akan secara otomatis:
1. Mengunggah seluruh PDF ke Cloudflare R2 secara streaming.
2. Memperbarui kolom `pdf_path` di PostgreSQL ke URL CDN publik R2.
3. Menghapus berkas lokal yang telah terverifikasi aman di cloud.

---

## 🔗 Ekosistem Integrasi OWLEXIA
O-Crawler berfungsi sebagai penyedia data utama bagi:
- **OWLEXIA Legal Reasoning Engine**: Memasok pasal-pasal terkini ke database PostgreSQL.
- **Hierarchical Hybrid RAG**: Mengaktifkan pencarian semantik dan FTS di atas basis data peraturan terindeks.
- **OWLEXIA REST API**: Menyediakan endpoint sinkronisasi `/api/sync-database` dan status `/api/crawler-status`.

---

## 📄 Lisensi
Didistribusikan di bawah lisensi [ISC License](LICENSE).  
Dikembangkan untuk ekosistem **OWLEXIA Legal AI Intelligence**.