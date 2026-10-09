# 🦅 O-Crawler

> **High-Speed Legal Ingestion Engine, Court Scraper & Modern SaaS GUI**  
> Unduh, ekstrak, dan indeks regulasi serta putusan pengadilan Indonesia dengan kecepatan tinggi, anti-WAF bypass, dan antarmuka SaaS modern.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B%20%7C%2017-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![SQLite Fallback](https://img.shields.io/badge/SQLite-Auto--Fallback-003B57.svg?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Cloudflare R2](https://img.shields.io/badge/Cloudflare_R2-Streaming_Storage-F38020.svg?logo=cloudflare&logoColor=white)](https://www.cloudflare.com/products/r2/)
[![Anti-WAF](https://img.shields.io/badge/Anti--WAF-curl__cffi%20TLS%2FJA3-2ea44f.svg)](https://github.com/lexiforest/curl_cffi)
[![Cloudflare Tunnel](https://img.shields.io/badge/Cloudflare_Tunnel-ocrawler.cugarete.me-orange.svg?logo=cloudflare)](https://ocrawler.cugarete.me)
[![License](https://img.shields.io/badge/License-ISC-blue.svg)](LICENSE)

---

## 📖 Tentang O-Crawler

**O-Crawler** adalah platform crawling, ekstraksi hierarkis, dan pipeline *data ingestion* dokumen hukum Indonesia yang komprehensif. Didesain untuk kebutuhan riset hukum, sistem AI kecerdasan hukum (**OWLEXIA Intelligence**), serta analisis kepatuhan regulasi secara real-time.

Aplikasi ini mengintegrasikan tiga portal sumber hukum utama di Indonesia:
1. **Regulasi Resmi RI** — [peraturan.go.id](https://peraturan.go.id) *(Undang-Undang, Perpu, Perpres, PP, Permen, Kepmen, Perda)*.
2. **Direktori Putusan Mahkamah Agung RI** — [putusan3.mahkamahagung.go.id](https://putusan3.mahkamahagung.go.id) *(Kasasi, Peninjauan Kembali, Banding, Tingkat Pertama pada bidang Pidana Khusus, Tipikor, Narkotika, Perdata, TUN, Militer, Agama, Pajak)*.
3. **Risalah & Putusan Mahkamah Konstitusi RI** — [mkri.id](https://www.mkri.id) *(Pengujian UU [PUU], Sengketa Kewenangan Lembaga Negara [SKLN], Perselisihan Hasil Pemilu [PHPU], dan Sengketa Pilkada [PHPKADA])*.

O-Crawler bertransformasi dari skrip CLI biasa menjadi sebuah **Aplikasi Web GUI SaaS Modern** dengan telemetri *real-time*, terminal interaktif via WebSocket, kontrol konkurensi dinamis, dan terhubung ke domain publik melalui **Cloudflare Tunnel**.

---

## 🌟 Fitur Utama

- 🖥️ **Modern SaaS GUI & Dashboard**:
  - Tampilan elegan bertema gelap (*Hallmark Design System*) yang bersih, responsif, dan bebas distorsi.
  - Dapat diakses langsung melalui browser desktop lokal maupun internet publik via Cloudflare Tunnel.
  - Kartu KPI telemetri *real-time*: Total Regulasi, Pasal Terurai, Putusan MA & MK, Kecepatan Ekstraksi, dan Status Worker.
- ⚡ **High-Speed Async Worker Pool (1–20 Konkurensi)**:
  - Menggunakan arsitektur asinkron berbasis Python `asyncio` & queue workers.
  - Slider kontrol konkurensi (1 sampai 20 worker) untuk akselerasi crawling 5x hingga 15x lebih cepat dibanding scraper konvensional.
- 🏛️ **Dukungan Multi-Sumber Hukum Lengkap**:
  - **Peraturan.go.id**: Parsing hierarkis Bab, Bagian, Paragraf, Pasal, Ayat, Penjelasan, dan metadata status peraturan.
  - **Mahkamah Agung (MA)**: Ekstraksi nomor perkara, tingkat pengadilan, para pihak (Pemohon/Termohon/Terdakwa), majelis hakim, amar putusan, dan unduhan salinan resmi PDF.
  - **Mahkamah Konstitusi (MK)**: Ekstraksi perkara PUU/SKLN/PHPU, para pemohon, amar putusan, dan unduhan berkas PDF dari CDN `s.mkri.id`.
- 🔍 **Fallback Ekstraksi Amar Putusan dari Berkas PDF**:
  - Untuk putusan di web Mahkamah Agung yang ringkasan HTML-nya kosong atau hanya berupa tanda strip, O-Crawler secara otomatis membedah isi file PDF hasil unduhan menggunakan parser regex cerdas untuk mengekstrak segmen **`M E N G A D I L I`**.
- 🛡️ **Anti-WAF TLS & JA3 Fingerprint Impersonation**:
  - Mengatasi blokir Cloudflare Managed Challenge & WAF menggunakan mesin `curl_cffi` dengan profil sidik jari TLS Safari 17 / Chrome 120.
  - Penyimpanan *cookie session cache* otomatis ke disk agar tidak memicu deteksi bot berulang.
- 🗄️ **Unified Dual-Database Architecture**:
  - Dukungan utama: **PostgreSQL** (`owlexia_db` dengan skema terindeks).
  - Mode cadangan otomatis (*zero-setup fallback*): **SQLite** (`ocrawler.db`) jika PostgreSQL belum aktif.
- ☁️ **Cloudflare R2 Storage & Streaming Reverse Proxy Anti-Blokir**:
  - Seluruh berkas dokumen PDF disimpan di bucket Cloudflare R2 (`owlexia-r2`) dengan biaya egress $0 rupiah.
  - **Streaming Reverse Proxy (`/api/pdf/{filename}`)**: Server bertindak sebagai perantara streaming cerdas yang mengambil berkas dari Cloudflare R2 secara real-time dan menyajikannya langsung ke browser pengguna, mem-bypass sensor dan DNS poisoning domain `*.r2.dev` oleh ISP di Indonesia.
  - Dashboard analitik real-time memantau kapasitas objek (728+ dokumen) dan total volume data di bucket Cloudflare R2 secara real-time.
- 🎨 **Investowl & Material 3 Dark Theme Experience**:
  - Antarmuka modern dengan palette warna hangat khas Investowl (`#141210`, `#211D1A`, `#FFB879`).
  - Navigasi bawah (*Bottom Navigation Bar*) minimalis berbasis ikon.
  - Pemisahan modul halaman: Crawler Studio, Data Explorer, Analitik & Penyimpanan Real-Time, serta Informasi Aplikasi (About).
  - Status persistensi navigasi (anti-reset saat refresh halaman browser).
- 📊 **Interactive Data Explorer & Export**:
  - Pencarian langsung (*live search*), filter per lembaga pengadilan, pratinjau teks amar putusan, tautan streaming PDF langsung.
  - Ekspor instan seluruh data hasil crawling ke format **CSV** dan **JSON**.

---

## 🏗️ Arsitektur Sistem

```mermaid
flowchart TD
    subgraph Sources ["Portal Sumber Data Hukum"]
        A["peraturan.go.id"]
        B["putusan3.mahkamahagung.go.id (MA)"]
        C["mkri.id (MK)"]
    end

    subgraph Core ["O-Crawler Engine (Async Worker Pool)"]
        WAF["Anti-WAF Client (curl_cffi TLS/JA3 Impersonate)"]
        Scrapers["Scrapers: Peraturan | MA | MK"]
        PDFParser["PDF Parser & Fallback 'MENGADILI' (pypdf)"]
        Engine["Crawler Engine (1-20 Concurrent Workers)"]
    end

    subgraph Interface ["FastAPI SaaS GUI & REST Engine"]
        API["FastAPI REST Endpoints (Port 8080)"]
        Proxy["Streaming Reverse Proxy (/api/pdf/...)"]
        WS["WebSocket Telemetry & Live Terminal (/ws/crawler)"]
        UI["Investowl Web GUI (Tailwind CSS / Material 3)"]
    end

    subgraph Storage ["Penyimpanan Data & Dokumen"]
        DB[("PostgreSQL (owlexia_db) / SQLite Fallback")]
        R2[("Cloudflare R2 Object Storage (owlexia-r2)")]
    end

    subgraph Tunnel ["Akses Publik"]
        CF["Cloudflare Tunnel (cugarete.me)"]
    end

    Sources -->|Bypass Cloudflare WAF| WAF
    WAF --> Scrapers
    Scrapers --> Engine
    Engine --> PDFParser
    PDFParser --> DB
    PDFParser --> R2

    Engine -->|Kirim Event & Log| WS
    API <--> DB
    Proxy <-->|Streaming Fetch (Bypass ISP)| R2
    UI <--> API
    UI <--> Proxy
    UI <--> WS

    CF <--> API
    CF <--> Proxy
    CF <--> UI
```

---

## 📁 Struktur Direktori

```text
O-Crawler/
├── crawler_engine.py       # Mesin utama async worker pool, scheduler, dan event broadcaster
├── db_manager.py           # Layer database PostgreSQL (owlexia_db) + SQLite fallback
├── server.py               # Backend FastAPI, WebSocket streaming, REST API, dan file server
├── run_gui.sh              # Skrip launcher interaktif (cek venv, database, systemd, dan server)
├── requirements.txt        # Daftar dependensi Python
├── env.example             # Contoh template konfigurasi environment
├── LICENSE                 # Lisensi open-source (ISC)
├── README.md               # Dokumentasi lengkap dan panduan penggunaan
│
├── scrapers/               # Modul scraper per sumber data
│   ├── base.py             # AntiWAFClient (curl_cffi, cookie caching, retry backoff)
│   ├── peraturan.py        # Scraper portal peraturan.go.id & hierarki pasal
│   ├── ma_scraper.py       # Scraper Direktori Putusan MA & PDF MENGADILI extractor
│   └── mk_scraper.py       # Scraper Risalah Putusan Mahkamah Konstitusi & CDN PDF
│
├── web/                    # Antarmuka Modern SaaS GUI
│   ├── index.html          # Halaman Single Page Application (SPA)
│   ├── style.css           # Styling modern Hallmark Dark-Theme & token layout
│   └── app.js              # State management, WebSocket handler, filter, dan data explorer
│
└── pdf_downloads/          # Direktori berkas PDF lokal yang tersimpan
```

---

## 🛠️ Prasyarat & Instalasi

### 1. Kebutuhan Sistem
- **Sistem Operasi**: Linux (Ubuntu/Debian, CentOS/AlmaLinux, Arch) atau macOS / Windows (WSL2).
- **Python**: Versi 3.10 atau lebih baru.
- **Database**: PostgreSQL 15+ (direkomendasikan) atau otomatis SQLite bawaan.
- **Tools Tambahan**: `curl`, `git`.

### 2. Kloning Repositori
```bash
git clone https://github.com/aryarifki/O-Crawler.git
cd O-Crawler
```

### 3. Setup Virtual Environment & Dependensi
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Konfigurasi Lingkungan (`.env`)
Salin file template konfigurasi dan sesuaikan nilai kredensial Anda:
```bash
cp env.example .env
nano .env
```

Contoh konfigurasi `.env`:
```ini
# PostgreSQL Connection URL (otomatis fallback ke SQLite jika PostgreSQL mati)
DATABASE_URL=postgresql://owlexia:owlexia_pass@localhost:5432/owlexia_db

# Cloudflare R2 Storage (Opsional: jika ingin streaming backup PDF ke cloud)
R2_ACCOUNT_ID=your_cloudflare_account_id
R2_BUCKET_NAME=owlexia-r2
R2_API_TOKEN=your_cloudflare_r2_api_token
R2_PUBLIC_URL=https://pub-xxxxxx.r2.dev
```

---

## 🚀 Panduan Penggunaan Lengkap

### Metode 1: Menggunakan Modern SaaS GUI (Direkomendasikan)

#### A. Menjalankan Server Aplikasi
Jalankan perintah berikut di root folder `O-Crawler`:
```bash
./run_gui.sh
```
Atau jika dijalankan di latar belakang melalui **systemd daemon**:
```bash
sudo systemctl start ocrawler
sudo systemctl status ocrawler
```

#### B. Mengakses Dashboard
Buka peramban (browser) Anda dan akses:
- **Akses Lokal / LAN**: [http://localhost:8080](http://localhost:8080)
- **Akses Publik (Cloudflare Tunnel)**: [https://ocrawler.cugarete.me](https://ocrawler.cugarete.me) *(atau `https://ocrawler.sugarate.me`)*

---

### 🖥️ Langkah Demi Langkah Menjalankan Crawling di Dashboard GUI

#### Langkah 1: Memilih Sumber Data Hukum
Pada panel kontrol **Crawl Configuration**:
1. **Pilih Sumber Data (Source)**:
   - 🏛️ `Peraturan (peraturan.go.id)`: Untuk regulasi resmi negara.
   - ⚖️ `Mahkamah Agung (putusan3.mahkamahagung.go.id)`: Untuk putusan peradilan umum, kasasi, dan PK.
   - 📜 `Mahkamah Konstitusi (mkri.id)`: Untuk pengujian UU, SKLN, dan sengketa pemilu.

#### Langkah 2: Mengonfigurasi Kategori & Kata Kunci
Pilihan kategori akan menyesuaikan secara dinamis sesuai sumber yang dipilih:
- **Jika memilih Peraturan**:
  - Kategori: *Semua Regulasi, Undang-Undang (UU), Peraturan Pemerintah (PP), Peraturan Presiden (Perpres), Peraturan Menteri (Permen)*.
- **Jika memilih Mahkamah Agung**:
  - Kategori: *Semua Klasifikasi, Pidana Khusus (Korupsi, Narkotika), Pidana Umum, Perdata, Tata Usaha Negara (TUN), Perdata Agama, Militer, Pajak*.
- **Jika memilih Mahkamah Konstitusi**:
  - Kategori: *Semua Perkara, Pengujian Undang-Undang (PUU), Sengketa Kewenangan Lembaga Negara (SKLN), Perselisihan Hasil Pemilu (PHPU)*.
- **Kata Kunci Pencarian (Opsional)**: Masukkan kata kunci spesifik (contoh: `"korupsi"`, `"telekomunikasi"`, `"pajak"`, atau nomor perkara tertentu).
- **Target Halaman (Pages)**: Tentukan batas halaman yang akan dikeruk (misal: 1 s.d. 10 halaman).

#### Langkah 3: Mengatur Tingkat Kecepatan (*Concurrency*)
- Gunakan slider **Concurrency (Workers)** untuk menentukan jumlah worker paralel (antara **1** hingga **20** workers).
- Rekomendasi:
  - **3–5 Workers**: Mode stabil & ramah bandwidth.
  - **10–15 Workers**: Mode cepat (*high-speed turbo*).

#### Langkah 4: Memulai Crawling & Memantau Progres
- Klik tombol hijau **`Mulai Crawling`**.
- Amati komponen antarmuka yang bergerak secara dinamis:
  - **Progress Bar**: Persentase pengerjaan halaman dan dokumen.
  - **Kartu Telemetri**: Menampilkan kecepatan ekstraksi (*dokumen/detik*) dan waktu berjalan.
  - **Live Terminal Log**: Aliran log real-time dari WebSocket yang mencatat setiap nomor perkara, dokumen yang berhasil diunduh, dan data yang tersimpan.
- Jika ingin menghentikan proses kapan saja, klik tombol merah **`Hentikan`**.

---

### 🔍 Menggunakan Data Explorer & Manajemen Hasil Crawl

Masuk ke bagian **Data Explorer** di bawah dashboard:

1. **Tab Navigasi**:
   - Tab **Peraturan Perundang-undangan**: Menampilkan tabel peraturan lengkap dengan Nomor, Tahun, Jenis, Judul, Status Berlaku, dan Jumlah Pasal yang terurai.
   - Tab **Putusan Pengadilan (MA & MK)**: Menampilkan tabel komprehensif putusan pengadilan:
     - **Lembaga & No. Perkara**: Badge MA / MK dan nomor register resmi.
     - **Tahun**: Tahun putusan.
     - **Para Pihak / Pokok Perkara**: Menampilkan identitas pemohon, termohon, atau terdakwa.
     - **Amar Putusan**: Teks amar putusan lengkap (hasil scraping web maupun ekstraksi otomatis segmen `M E N G A D I L I` dari PDF).
     - **Aksi**: Tombol pratinjau dan unduh berkas PDF resmi secara langsung.
2. **Pencarian Instan (Live Search)**:
   - Ketik kata kunci di bilah pencarian data explorer untuk memfilter baris data secara instan tanpa memuat ulang halaman.
3. **Ekspor Data**:
   - Klik tombol **`Export CSV`** untuk mengunduh dataset ke format spreadsheet (*Excel / LibreOffice*).
   - Klik tombol **`Export JSON`** untuk mengunduh dataset terstruktur untuk kebutuhan integrasi API atau pelatihan model LLM.

---

### Metode 2: Menggunakan Mode CLI / Background Worker

Jika Anda ingin menjalankan scraping terjadwal via skrip bash, Docker, atau cron job di server:

```bash
# 1. Crawl Regulasi (5 Halaman Undang-Undang)
./venv/bin/python anti_waf_crawler.py --category uu --pages 5

# 2. Crawl Putusan Mahkamah Agung via Python Scraper
./venv/bin/python -c "
import asyncio
from crawler_engine import CrawlerEngine
engine = CrawlerEngine()
asyncio.run(engine.start_crawl({
    'source': 'ma',
    'category': 'pidana-khusus-1',
    'query': 'korupsi',
    'pages': 2,
    'concurrency': 5
}))
"

# 3. Crawl Putusan Mahkamah Konstitusi (Pengujian UU)
./venv/bin/python -c "
import asyncio
from crawler_engine import CrawlerEngine
engine = CrawlerEngine()
asyncio.run(engine.start_crawl({
    'source': 'mk',
    'category': 'PUU',
    'pages': 2,
    'concurrency': 5
}))
"
```

---

## ⚙️ Pengelolaan Daemon Systemd & Cloudflare Tunnel

Aplikasi O-Crawler telah dikonfigurasi sebagai layanan sistem Linux (*systemd daemon*):

```bash
# Memeriksa status server O-Crawler
sudo systemctl status ocrawler

# Me-restart server O-Crawler setelah perubahan kode
sudo systemctl restart ocrawler

# Menghentikan server O-Crawler
sudo systemctl stop ocrawler

# Melihat log live server O-Crawler
sudo journalctl -u ocrawler -f
```

Untuk Cloudflare Tunnel yang menghubungkan domain publik:
```bash
# Memeriksa status tunnel Cloudflare
sudo systemctl status cloudflared

# Konfigurasi ingress tunnel berlokasi di:
# /etc/cloudflared/config.yml -> mapping ocrawler.cugarete.me ke http://localhost:8080
```

---

## 📡 Dokumentasi REST API & WebSocket

| Metode | Endpoint | Deskripsi |
| :--- | :--- | :--- |
| `GET` | `/` | Web GUI Dashboard (*Single Page App*) |
| `WS` | `/ws/crawler` | Kanal WebSocket dua arah untuk telemetri real-time dan live terminal log |
| `GET` | `/api/stats` | Mengambil metrik total regulasi, pasal terurai, dan putusan MA & MK |
| `GET` | `/api/crawl/status` | Mengambil status crawl yang sedang berlangsung, kecepatan, dan progres |
| `POST` | `/api/crawl/start` | Memicu pekerjaan crawl baru (`source`, `category`, `query`, `pages`, `concurrency`) |
| `POST` | `/api/crawl/stop` | Menghentikan paksa proses crawl yang sedang aktif |
| `GET` | `/api/data/regulations` | Mendapatkan daftar regulasi dengan parameter `q`, `page`, dan `limit` |
| `GET` | `/api/data/decisions` | Mendapatkan daftar putusan dengan parameter `lembaga` (MA/MK), `q`, `page`, dan `limit` |
| `GET` | `/api/export` | Mengunduh file ekspor dalam format CSV (`?format=csv`) atau JSON (`?format=json`) |
| `GET` | `/api/health` | Status kesehatan server, kesiapan engine, dan konektivitas database |
| `GET` | `/pdf_downloads/{filename}` | Melayani berkas PDF resmi yang tersimpan di disk lokal |

---

## ❓ FAQ & Troubleshooting

### Q1: Mengapa saat mengunduh berkas PDF muncul pesan 404 / File Not Found?
> **Penanganan**: Pastikan endpoint diarahkan ke `/pdf_downloads/{filename}`. Server O-Crawler sudah dilengkapi *path aliasing* otomatis untuk menangani rute lama (`/root/O-Crawler/pdf_downloads/...`) agar tetap dapat dibuka secara transparan di browser.

### Q2: Mengapa sebagian amar putusan di portal MA bernilai kosong di tabel?
> **Penanganan**: Beberapa panitera Mahkamah Agung tidak menginputkan teks amar ke dalam tabel ringkasan web (hanya mengunggah file PDF resminya). O-Crawler memiliki fitur otomatis **PDF Fallback**: mesin akan memindai berkas PDF yang baru diunduh dan mengekstrak klausa **`M E N G A D I L I`** langsung ke kolom amar putusan di database.

### Q3: Bagaimana jika server tidak memiliki akses PostgreSQL?
> **Penanganan**: O-Crawler dirancang dengan prinsip *resilience*. Jika koneksi PostgreSQL gagal, sistem secara otomatis beralih menggunakan database lokal **SQLite** (`ocrawler.db`) tanpa perlu instalasi tambahan.

### Q4: Apakah crawling aman dari pemblokiran Cloudflare WAF?
> **Penanganan**: Mesin `scrapers/base.py` menggunakan `curl_cffi` dengan profil sidik jari TLS Safari 17 / Chrome 120 dan caching sesi disk. Jika sewaktu-waktu target mengembalikan respon proteksi, klien melakukan *exponential backoff* dan jeda otomatis untuk menjaga integritas koneksi.

---

## 📜 Lisensi & Kontribusi

Proyek ini dilisensikan di bawah lisensi terbuka [ISC License](LICENSE).  
Dirancang dan dikembangkan sebagai pilar data cerdas bagi ekosistem **OWLEXIA Legal AI Intelligence**.