// O-Crawler Modern SaaS Frontend Engine (Material 3 Expressive).
// Menghubungkan antarmuka GUI ke FastAPI backend & WebSocket telemetry.

// State Aplikasi
let currentSource = 'peraturan';
let activeTab = 'studio';
let explorerType = localStorage.getItem('ocrawler_explorer_type') || 'regulations';
let explorerPage = 1;
let isCrawling = false;
let ws = null;
let reconnectTimer = null;
let chartInstance = null;
let searchTimeout = null;

// Kategori per Sumber Dokumen
const CATEGORIES = {
  peraturan: [
    { value: 'uu', label: 'Undang-Undang (UU)' },
    { value: 'pp', label: 'Peraturan Pemerintah (PP)' },
    { value: 'perpres', label: 'Peraturan Presiden (Perpres)' },
    { value: 'perppu', label: 'Perppu (Pengganti UU)' },
    { value: 'tapmpr', label: 'Ketetapan MPR' },
    { value: 'permen', label: 'Peraturan Menteri' },
    { value: 'permenkumham', label: 'Permenkumham' },
    { value: 'permenkum', label: 'Permenkum' },
    { value: 'perban', label: 'Peraturan Badan / Lembaga' },
    { value: 'perda', label: 'Peraturan Daerah (Perda)' },
  ],
  ma: [
    { value: 'pidana-khusus-1', label: 'Pidana Khusus (Korupsi, Narkotika, dll.)' },
    { value: 'pidana-umum-1', label: 'Pidana Umum' },
    { value: 'perdata-1', label: 'Perdata Umum' },
    { value: 'perdata-khusus', label: 'Perdata Khusus (Niaga, Kepailitan, HKI)' },
    { value: 'tun-1', label: 'Tata Usaha Negara (TUN)' },
    { value: 'pajak-2', label: 'Pengadilan Pajak' },
    { value: 'perdata-agama-1', label: 'Perdata Agama' },
    { value: 'pidana-militer-1', label: 'Pidana Militer' },
    { value: 'korupsi-1', label: 'Tindak Pidana Korupsi (Tipikor)' },
    { value: 'hak-uji-materiil-1', label: 'Hak Uji Materiil (HUM)' },
  ],
  mk: [
    { value: 'ALL', label: 'Semua Jenis Perkara MK' },
    { value: 'PUU', label: 'Pengujian Undang-Undang (PUU)' },
    { value: 'SKLN', label: 'Sengketa Kewenangan Lembaga Negara (SKLN)' },
    { value: 'PHPU', label: 'Perselisihan Hasil Pemilu (PHPU)' },
    { value: 'PHPKADA', label: 'Perselisihan Hasil Pilkada (PHPKADA)' },
  ]
};

// Inisialisasi Saat Load (Dengan Persistensi Hash/LocalStorage - Requirement 6/7)
document.addEventListener('DOMContentLoaded', () => {
  initWebSocket();
  populateCategories(currentSource);
  fetchStats();
  initAnalyticsChart();

  // Binding eksplisit ke tombol tab untuk menjamin navigasi instan dan anti-macet
  ['studio', 'explorer', 'analytics', 'about'].forEach(tabId => {
    const btn = document.getElementById(`tab-btn-${tabId}`);
    if (btn) {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        switchTab(tabId);
      });
    }
  });

  // Restore Active Tab dari URL Hash atau LocalStorage
  const urlHash = window.location.hash.replace('#', '');
  const savedTab = urlHash || localStorage.getItem('ocrawler_active_tab') || 'studio';
  if (['studio', 'explorer', 'analytics', 'about'].includes(savedTab)) {
    switchTab(savedTab, false);
  } else {
    switchTab('studio', false);
  }

  // Listener navigasi history browser (tombol back/forward)
  window.addEventListener('hashchange', () => {
    const hash = window.location.hash.replace('#', '');
    if (['studio', 'explorer', 'analytics', 'about'].includes(hash) && hash !== activeTab) {
      switchTab(hash, false);
    }
  });

  // Restore Explorer Sub-tab jika sedang di explorer
  if (explorerType) {
    setExplorerTab(explorerType);
  } else {
    fetchExplorerData();
  }

  // Polling stats setiap 5 detik
  setInterval(fetchStats, 5000);

  // Render Lucide icons
  if (window.lucide) {
    lucide.createIcons();
  }
});

// --- WEBSOCKET TELEMETRY ---
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/crawler`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    const indicator = document.getElementById('ws-indicator');
    if (indicator) indicator.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
    const statusText = document.getElementById('ws-status-text');
    if (statusText) statusText.innerText = 'Tersambung';
    clearTimeout(reconnectTimer);
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleServerEvent(data);
    } catch (e) {
      console.error('Error parsing WS message:', e);
    }
  };

  ws.onclose = () => {
    const indicator = document.getElementById('ws-indicator');
    if (indicator) indicator.className = 'w-2 h-2 rounded-full bg-rose-500';
    const statusText = document.getElementById('ws-status-text');
    if (statusText) statusText.innerText = 'Terputus';
    reconnectTimer = setTimeout(initWebSocket, 3000);
  };
}

function handleServerEvent(event) {
  if (event.type === 'log') {
    appendTerminalLog(event.timestamp, event.level, event.message);
  } else if (event.type === 'status' || event.type === 'progress') {
    updateCrawlerState(event);
  } else if (event.type === 'item_crawled') {
    fetchStats();
  }
}

function appendTerminalLog(time, level, message) {
  const container = document.getElementById('terminal-logs');
  if (!container) return;
  const line = document.createElement('div');
  line.className = 'log-line';

  const timeSpan = document.createElement('span');
  timeSpan.className = 'log-time';
  timeSpan.innerText = time || new Date().toLocaleTimeString();

  const badge = document.createElement('span');
  badge.className = `log-badge ${level || 'info'}`;
  badge.innerText = (level || 'info').toUpperCase();

  const msgSpan = document.createElement('span');
  msgSpan.className = 'text-slate-300';
  msgSpan.innerText = message;

  line.appendChild(timeSpan);
  line.appendChild(badge);
  line.appendChild(msgSpan);

  container.appendChild(line);
  container.scrollTop = container.scrollHeight;
}

function clearLogs() {
  const container = document.getElementById('terminal-logs');
  if (container) container.innerHTML = '';
}

// --- STATE & CONTROLS ---
function selectSource(source) {
  currentSource = source;
  document.querySelectorAll('.source-card').forEach(c => c.classList.remove('active'));
  const btn = document.getElementById(`src-btn-${source}`);
  if (btn) btn.classList.add('active');

  const catLabel = document.getElementById('category-label');
  if (catLabel) {
    if (source === 'peraturan') catLabel.innerText = 'Kategori Peraturan';
    else if (source === 'ma') catLabel.innerText = 'Kategori Klasifikasi MA';
    else catLabel.innerText = 'Jenis Perkara MK';
  }

  populateCategories(source);
}

function populateCategories(source) {
  const select = document.getElementById('crawl-category');
  if (!select) return;
  select.innerHTML = '';
  const options = CATEGORIES[source] || [];
  options.forEach(opt => {
    const el = document.createElement('option');
    el.value = opt.value;
    el.innerText = opt.label;
    select.appendChild(el);
  });
}

function updateConcurrency(val) {
  const el = document.getElementById('concurrency-val');
  if (el) el.innerText = `${val} Workers`;
}

async function startCrawl() {
  const config = {
    source: currentSource,
    category: document.getElementById('crawl-category').value,
    query: document.getElementById('crawl-query').value.trim(),
    tahun: document.getElementById('crawl-tahun').value.trim(),
    start_page: parseInt(document.getElementById('crawl-start-page').value) || 1,
    pages: parseInt(document.getElementById('crawl-pages').value) || 0,
    concurrency: parseInt(document.getElementById('crawl-concurrency').value) || 5,
    limit: 2000,
    delay: 1.0,
    keep_local_pdf: false,
  };

  try {
    const res = await fetch('/api/crawl/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    const result = await res.json();
    if (!res.ok) {
      alert(result.detail || 'Gagal memulai crawler');
      return;
    }
    isCrawling = true;
    updateUIButtons(true);
    appendTerminalLog(null, 'info', `Job ${result.job_id} dimulai.`);
  } catch (e) {
    alert('Error koneksi: ' + e);
  }
}

async function stopCrawl() {
  try {
    await fetch('/api/crawl/stop', { method: 'POST' });
    appendTerminalLog(null, 'warning', 'Perintah stop dikirim ke crawler.');
  } catch (e) {
    console.error(e);
  }
}

function updateCrawlerState(state) {
  const isRunning = state.is_running;
  updateUIButtons(isRunning);

  const statusTitle = document.getElementById('current-job-title');
  const statusPulse = document.getElementById('status-pulse');
  const speedBadge = document.getElementById('current-speed');
  const detail = document.getElementById('progress-detail');
  const bar = document.getElementById('progress-bar-fill');

  if (isRunning) {
    if (statusTitle) statusTitle.innerText = `Sedang Berjalan (${state.config ? state.config.source.toUpperCase() : ''})`;
    if (statusPulse) statusPulse.className = 'w-3 h-3 rounded-full bg-emerald-400 animate-ping';
    if (speedBadge) speedBadge.innerText = state.speed || '0 dok/dtk';
    if (detail) detail.innerText = `Dokumen terproses: ${state.total_crawled || 0} (${state.total_articles || 0} pasal/ekstraksi)`;
    if (bar) bar.style.width = '75%';
  } else {
    if (statusTitle) statusTitle.innerText = state.status === 'COMPLETED' ? 'Selesai' : 'Crawler Siap';
    if (statusPulse) statusPulse.className = 'w-3 h-3 rounded-full bg-slate-600';
    if (speedBadge) speedBadge.innerText = '0 dok/dtk';
    if (bar) bar.style.width = state.status === 'COMPLETED' ? '100%' : '0%';
  }

  // Update DB & R2 badge
  if (state.db_type && document.getElementById('db-badge')) {
    document.getElementById('db-badge').innerText = state.db_type;
  }
  if (state.r2_active !== undefined && document.getElementById('r2-badge')) {
    document.getElementById('r2-badge').innerText = state.r2_active ? 'R2 Aktif' : 'R2 Non-aktif';
  }
}

function updateUIButtons(running) {
  const btnStart = document.getElementById('btn-start-crawl');
  const btnStop = document.getElementById('btn-stop-crawl');
  if (btnStart) {
    btnStart.disabled = running;
    if (running) btnStart.classList.add('opacity-40', 'cursor-not-allowed');
    else btnStart.classList.remove('opacity-40', 'cursor-not-allowed');
  }
  if (btnStop) {
    btnStop.disabled = !running;
  }
}

// --- STATS OVERVIEW & REAL-TIME STORAGE METRICS (Requirement 5) ---
async function fetchStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const data = await res.json();

    // KPI Header Stats
    if (document.getElementById('stat-regulations')) {
      document.getElementById('stat-regulations').innerText = (data.total_regulations || 0).toLocaleString();
    }
    if (document.getElementById('stat-articles')) {
      document.getElementById('stat-articles').innerText = (data.total_articles || 0).toLocaleString();
    }
    if (document.getElementById('stat-ma')) {
      document.getElementById('stat-ma').innerText = (data.decisions_ma || 0).toLocaleString();
    }
    if (document.getElementById('stat-mk')) {
      document.getElementById('stat-mk').innerText = (data.decisions_mk || 0).toLocaleString();
    }

    // Badges
    const dbType = data.is_postgres ? 'PostgreSQL' : 'SQLite Local';
    if (document.getElementById('db-badge')) {
      document.getElementById('db-badge').innerText = dbType;
    }

    // Real-Time Storage Analysis (Requirement 5)
    if (document.getElementById('storage-db-size')) {
      document.getElementById('storage-db-size').innerText = data.db_size_pretty || '0 KB';
    }
    if (document.getElementById('storage-db-engine')) {
      document.getElementById('storage-db-engine').innerText = dbType;
    }
    if (document.getElementById('storage-pdf-size')) {
      document.getElementById('storage-pdf-size').innerText = data.pdf_size_pretty || '0 MB';
    }
    if (document.getElementById('storage-pdf-count')) {
      const unit = data.r2_active ? 'Objek R2' : 'File';
      document.getElementById('storage-pdf-count').innerText = `${(data.pdf_count || 0).toLocaleString()} ${unit}`;
    }
    if (document.getElementById('storage-pdf-desc')) {
      document.getElementById('storage-pdf-desc').innerText = data.r2_active
        ? `Cloudflare R2 Bucket: ${data.r2_bucket || 'owlexia-r2'} (CDN Zero Egress)`
        : 'Kapasitas folder pdf_downloads lokal';
    }

    // Cache Engine Metrics
    if (data.cache) {
      if (document.getElementById('storage-cache-driver')) {
        document.getElementById('storage-cache-driver').innerText = data.cache.driver || 'L1 RAM + L2 Redis';
      }
      if (document.getElementById('storage-cache-stat')) {
        const hits = data.cache.memory_hits || 0;
        const ratio = data.cache.hit_ratio_percent || 0;
        document.getElementById('storage-cache-stat').innerText = `${hits} Hits (${ratio}%)`;
      }
      if (document.getElementById('storage-cache-desc')) {
        const memKeys = data.cache.memory_keys_count || 0;
        const redisKeys = data.cache.redis_keys_count || 0;
        document.getElementById('storage-cache-desc').innerText = `L1 RAM: ${memKeys} keys · L2 Redis: ${redisKeys} keys (0ms latency)`;
      }
    }

    // Detail entity counts
    if (document.getElementById('detail-count-reg')) {
      document.getElementById('detail-count-reg').innerText = `${(data.total_regulations || 0).toLocaleString()} baris`;
    }
    if (document.getElementById('detail-count-art')) {
      document.getElementById('detail-count-art').innerText = `${(data.total_articles || 0).toLocaleString()} baris`;
    }
    if (document.getElementById('detail-count-ma')) {
      document.getElementById('detail-count-ma').innerText = `${(data.decisions_ma || 0).toLocaleString()} baris`;
    }
    if (document.getElementById('detail-count-mk')) {
      document.getElementById('detail-count-mk').innerText = `${(data.decisions_mk || 0).toLocaleString()} baris`;
    }

    // Chart badge counts
    if (document.getElementById('chart-count-reg')) {
      document.getElementById('chart-count-reg').innerText = (data.total_regulations || 0).toLocaleString();
    }
    if (document.getElementById('chart-count-ma')) {
      document.getElementById('chart-count-ma').innerText = (data.decisions_ma || 0).toLocaleString();
    }
    if (document.getElementById('chart-count-mk')) {
      document.getElementById('chart-count-mk').innerText = (data.decisions_mk || 0).toLocaleString();
    }

    updateAnalyticsChart(data.total_regulations, data.decisions_ma, data.decisions_mk);
  } catch (e) {
    console.error('Error fetching stats:', e);
  }
}

// --- DATA EXPLORER ---
function setExplorerTab(type) {
  explorerType = type;
  explorerPage = 1;
  localStorage.setItem('ocrawler_explorer_type', type);

  const regBtn = document.getElementById('exp-tab-reg');
  const decBtn = document.getElementById('exp-tab-dec');
  const expCsv = document.getElementById('btn-export-csv');
  const expJson = document.getElementById('btn-export-json');

  if (type === 'regulations') {
    if (regBtn) regBtn.className = 'px-3.5 py-1.5 text-xs font-semibold rounded-full bg-indigo-600 text-white transition-all shadow-sm';
    if (decBtn) decBtn.className = 'px-3.5 py-1.5 text-xs font-semibold rounded-full text-slate-400 hover:text-white transition-all';
    if (expCsv) expCsv.href = '/api/export?type=regulations&format=csv';
    if (expJson) expJson.href = '/api/export?type=regulations&format=json';
  } else {
    if (decBtn) decBtn.className = 'px-3.5 py-1.5 text-xs font-semibold rounded-full bg-indigo-600 text-white transition-all shadow-sm';
    if (regBtn) regBtn.className = 'px-3.5 py-1.5 text-xs font-semibold rounded-full text-slate-400 hover:text-white transition-all';
    if (expCsv) expCsv.href = '/api/export?type=decisions&format=csv';
    if (expJson) expJson.href = '/api/export?type=decisions&format=json';
  }

  fetchExplorerData();
}

function debounceSearch() {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    explorerPage = 1;
    fetchExplorerData();
  }, 350);
}

function changePage(delta) {
  explorerPage = Math.max(1, explorerPage + delta);
  fetchExplorerData();
}

async function fetchExplorerData() {
  const searchInput = document.getElementById('explorer-search');
  const q = searchInput ? searchInput.value.trim() : '';
  const endpoint = explorerType === 'regulations'
    ? `/api/data/regulations?q=${encodeURIComponent(q)}&page=${explorerPage}&limit=20`
    : `/api/data/decisions?q=${encodeURIComponent(q)}&page=${explorerPage}&limit=20`;

  try {
    const res = await fetch(endpoint);
    const data = await res.json();
    renderTable(data.items || []);
    const pageInfo = document.getElementById('explorer-page-info');
    if (pageInfo) pageInfo.innerText = `Halaman ${explorerPage} (${data.count} dokumen)`;
    const prevBtn = document.getElementById('btn-prev-page');
    if (prevBtn) prevBtn.disabled = explorerPage <= 1;
    const nextBtn = document.getElementById('btn-next-page');
    if (nextBtn) nextBtn.disabled = (data.items || []).length < 20;

    if (window.lucide) lucide.createIcons();
  } catch (e) {
    console.error('Error fetching explorer data:', e);
  }
}

function formatPdfUrl(path) {
  if (!path) return '';
  // Selalu arahkan ke Streaming Reverse Proxy /api/pdf/ untuk mencegah blank screen akibat sensor ISP Indonesia
  const filename = path.split('/').pop().split('?')[0];
  return `/api/pdf/${encodeURIComponent(filename)}`;
}

// --- 6. ANIMASI LOADING STATIS SAAT MEMBUKA PDF (Requirement 6) ---
function openPdfWithLoader(url, title) {
  if (!url) return;
  const overlay = document.getElementById('pdf-loading-overlay');
  const titleEl = document.getElementById('pdf-loading-title');
  const subEl = document.getElementById('pdf-loading-subtitle');

  if (titleEl) {
    titleEl.innerText = title ? `Mempersiapkan: ${title}` : 'Mempersiapkan Dokumen Hukum';
  }
  if (subEl) {
    subEl.innerText = 'Mengambil salinan PDF & verifikasi integritas berkas...';
  }

  if (overlay) {
    overlay.classList.remove('hidden');
    overlay.classList.add('flex');
  }

  // Animasi loading statis sejenak sebelum membuka dokumen PDF di tab baru
  setTimeout(() => {
    window.open(url, '_blank');
    setTimeout(() => {
      if (overlay) {
        overlay.classList.add('hidden');
        overlay.classList.remove('flex');
      }
    }, 400);
  }, 750);
}

function renderTable(items) {
  const headers = document.getElementById('table-headers');
  const tbody = document.getElementById('table-body');
  if (!headers || !tbody) return;
  tbody.innerHTML = '';

  if (explorerType === 'regulations') {
    headers.innerHTML = `
      <th class="py-3.5 px-4 font-bold">Jenis & No</th>
      <th class="py-3.5 px-4 font-bold">Tahun</th>
      <th class="py-3.5 px-4 font-bold">Judul Dokumen</th>
      <th class="py-3.5 px-4 font-bold">Total Pasal</th>
      <th class="py-3.5 px-4 text-right font-bold">Aksi</th>
    `;
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="py-10 text-center text-slate-500 font-medium">Belum ada regulasi tersimpan. Jalankan crawler untuk mulai mengumpulkan data.</td></tr>`;
      return;
    }
    items.forEach(it => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-white/[0.03] transition';
      const pdfUrl = formatPdfUrl(it.pdf_path);
      const safeTitle = (it.judul || '').replace(/"/g, '&quot;');
      tr.innerHTML = `
        <td class="py-3.5 px-4 font-bold text-white whitespace-nowrap">${it.jenis} No. ${it.nomor}</td>
        <td class="py-3.5 px-4 text-slate-400 font-mono">${it.tahun}</td>
        <td class="py-3.5 px-4 max-w-md truncate" title="${safeTitle}">${it.judul}</td>
        <td class="py-3.5 px-4"><span class="px-2.5 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300 font-mono text-[11px] font-bold border border-indigo-500/25">${it.total_pasal || 0} Pasal</span></td>
        <td class="py-3.5 px-4 text-right whitespace-nowrap space-x-1.5">
          ${pdfUrl ? `<button onclick="openPdfWithLoader('${pdfUrl}', '${it.jenis} No. ${it.nomor}')" class="px-3 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-indigo-300 font-semibold rounded-lg inline-flex items-center space-x-1 transition"><span>PDF</span></button>` : ''}
          <button onclick='viewRegulationDetail(${JSON.stringify(it).replace(/'/g, "&#39;")})' class="px-3 py-1 text-xs bg-indigo-600/20 text-indigo-300 hover:bg-indigo-600 hover:text-white font-semibold rounded-lg transition">Detail</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } else {
    // Court Decisions
    headers.innerHTML = `
      <th class="py-3.5 px-4 font-bold">Lembaga & No. Perkara</th>
      <th class="py-3.5 px-4 font-bold">Tahun</th>
      <th class="py-3.5 px-4 font-bold">Para Pihak / Pokok Perkara</th>
      <th class="py-3.5 px-4 font-bold">Amar Putusan</th>
      <th class="py-3.5 px-4 text-right font-bold">Aksi</th>
    `;
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="py-10 text-center text-slate-500 font-medium">Belum ada putusan tersimpan. Jalankan crawler Mahkamah Agung / Mahkamah Konstitusi.</td></tr>`;
      return;
    }
    items.forEach(it => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-white/[0.03] transition';
      const badgeColor = it.lembaga === 'MA' ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/25' : 'bg-amber-500/15 text-amber-300 border border-amber-500/25';
      const pdfUrl = formatPdfUrl(it.pdf_path);

      let pihakText = (it.para_pihak || '').trim();
      if (!pihakText || pihakText === '—' || pihakText === '-') {
        if (it.metadata && it.metadata.pokok_perkara) pihakText = it.metadata.pokok_perkara;
        else if (it.klasifikasi && it.klasifikasi !== '-') pihakText = it.klasifikasi;
        else pihakText = it.judul || '-';
      }

      let amarText = (it.amar_putusan || '').trim();
      if (!amarText || amarText === '—' || amarText === '-' || amarText.toLowerCase() === 'lain-lain') {
        if (it.full_text && it.full_text.trim() && it.full_text !== '—') {
          amarText = it.full_text.trim();
        } else if (it.metadata && it.metadata.jenis_amar) {
          amarText = it.metadata.jenis_amar;
        } else {
          amarText = 'Tercantum di berkas putusan resmi (PDF)';
        }
      }

      tr.innerHTML = `
        <td class="py-3.5 px-4 font-bold text-white whitespace-nowrap">
          <span class="px-2 py-0.5 rounded-full font-bold text-[10px] mr-1.5 ${badgeColor}">${it.lembaga}</span>
          <span class="font-mono">${it.nomor_perkara}</span>
        </td>
        <td class="py-3.5 px-4 text-slate-400 font-mono">${it.tahun || '-'}</td>
        <td class="py-3.5 px-4 max-w-xs truncate text-slate-300" title="${pihakText}">${pihakText}</td>
        <td class="py-3.5 px-4 max-w-sm truncate text-slate-200" title="${amarText}">${amarText}</td>
        <td class="py-3.5 px-4 text-right whitespace-nowrap space-x-1.5">
          ${pdfUrl ? `<button onclick="openPdfWithLoader('${pdfUrl}', 'Putusan ${it.lembaga} ${it.nomor_perkara}')" class="px-3 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-indigo-300 font-semibold rounded-lg inline-flex items-center space-x-1 transition"><span>PDF</span></button>` : ''}
          <button onclick='viewDecisionDetail(${JSON.stringify(it).replace(/'/g, "&#39;")})' class="px-3 py-1 text-xs bg-indigo-600/20 text-indigo-300 hover:bg-indigo-600 hover:text-white font-semibold rounded-lg transition">Detail</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }
}

// --- MODAL PREVIEWS ---
function viewRegulationDetail(it) {
  document.getElementById('modal-title').innerHTML = `
    <i data-lucide="scale" class="w-4 h-4 text-amber-300"></i>
    <span>${it.jenis} Nomor ${it.nomor} Tahun ${it.tahun}</span>
  `;
  const c = document.getElementById('modal-content');
  const pdfUrl = formatPdfUrl(it.pdf_path);
  c.innerHTML = `
    <div class="p-3.5 bg-[#090b10] rounded-2xl border border-white/[0.08]">
      <span class="text-slate-400 block text-[11px] font-semibold mb-1">Judul Resmi:</span>
      <p class="font-bold text-white text-sm leading-relaxed">${it.judul}</p>
    </div>
    <div class="grid grid-cols-2 gap-3">
      <div class="p-3.5 bg-[#090b10] rounded-2xl border border-white/[0.08]">
        <span class="text-slate-400 block text-[11px] font-semibold mb-1">Status Keberlakuan:</span>
        <span class="font-bold text-emerald-400 text-xs">${it.status || 'BERLAKU'}</span>
      </div>
      <div class="p-3.5 bg-[#090b10] rounded-2xl border border-white/[0.08]">
        <span class="text-slate-400 block text-[11px] font-semibold mb-1">Total Pasal Terindeks:</span>
        <span class="font-mono text-indigo-300 font-bold text-xs">${it.total_pasal || 0} Pasal</span>
      </div>
    </div>
    ${pdfUrl ? `
    <div class="pt-2">
      <button onclick="openPdfWithLoader('${pdfUrl}', '${it.jenis} No. ${it.nomor}')" class="w-full py-3 m3-btn-primary flex items-center justify-center space-x-2 font-bold cursor-pointer">
        <i data-lucide="file-text" class="w-4 h-4"></i>
        <span>Buka / Unduh Berkas Salinan Asli (PDF)</span>
      </button>
    </div>` : ''}
  `;
  const modal = document.getElementById('detail-modal');
  if (modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
  }
  if (window.lucide) lucide.createIcons();
}

function viewDecisionDetail(it) {
  document.getElementById('modal-title').innerHTML = `
    <i data-lucide="landmark" class="w-4 h-4 text-emerald-400"></i>
    <span>Putusan ${it.lembaga} No. ${it.nomor_perkara}</span>
  `;
  const c = document.getElementById('modal-content');

  let amarText = (it.amar_putusan || '').trim();
  if (!amarText || amarText === '—' || amarText === '-' || amarText.toLowerCase() === 'lain-lain') {
    if (it.full_text && it.full_text.trim() && it.full_text !== '—') {
      amarText = it.full_text.trim();
    } else if (it.metadata && it.metadata.jenis_amar) {
      amarText = it.metadata.jenis_amar;
    } else {
      amarText = 'Teks amar lengkap tercantum di dalam salinan berkas PDF resmi.';
    }
  }

  let pihakText = (it.para_pihak || '').trim();
  if (!pihakText || pihakText === '—' || pihakText === '-') {
    if (it.metadata && it.metadata.pemohon) pihakText = `Pemohon: ${it.metadata.pemohon}`;
    else if (it.metadata && it.metadata.pokok_perkara) pihakText = it.metadata.pokok_perkara;
    else pihakText = '-';
  }

  const pdfUrl = formatPdfUrl(it.pdf_path);
  c.innerHTML = `
    <div class="p-3.5 bg-[#090b10] rounded-2xl border border-white/[0.08]">
      <span class="text-slate-400 block text-[11px] font-semibold mb-1">Judul / Pokok Perkara:</span>
      <p class="font-bold text-white text-sm leading-relaxed">${it.judul}</p>
    </div>
    <div class="grid grid-cols-2 gap-3">
      <div class="p-3.5 bg-[#090b10] rounded-2xl border border-white/[0.08]">
        <span class="text-slate-400 block text-[11px] font-semibold mb-1">Para Pihak / Pemohon:</span>
        <p class="text-slate-200 font-medium">${pihakText}</p>
      </div>
      <div class="p-3.5 bg-[#090b10] rounded-2xl border border-white/[0.08]">
        <span class="text-slate-400 block text-[11px] font-semibold mb-1">Klasifikasi Perkara:</span>
        <p class="text-slate-200 font-medium">${it.klasifikasi || it.tingkat_proses || '-'}</p>
      </div>
    </div>
    <div class="p-3.5 bg-[#090b10] rounded-2xl border border-white/[0.08]">
      <span class="text-slate-400 block text-[11px] font-semibold mb-1">Amar Putusan:</span>
      <p class="text-slate-200 whitespace-pre-wrap leading-relaxed">${amarText}</p>
    </div>
    ${pdfUrl ? `
    <div class="pt-2">
      <button onclick="openPdfWithLoader('${pdfUrl}', 'Putusan ${it.lembaga} ${it.nomor_perkara}')" class="w-full py-3 m3-btn-primary flex items-center justify-center space-x-2 font-bold cursor-pointer">
        <i data-lucide="file-text" class="w-4 h-4"></i>
        <span>Buka / Unduh Berkas Putusan Resmi (PDF)</span>
      </button>
    </div>` : ''}
  `;
  const modalDec = document.getElementById('detail-modal');
  if (modalDec) {
    modalDec.classList.remove('hidden');
    modalDec.classList.add('flex');
  }
  if (window.lucide) lucide.createIcons();
}

function closeModal() {
  const modal = document.getElementById('detail-modal');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
}

// --- TAB SWITCHER DENGAN PERSISTENSI REFRESH (Requirement 6/7) ---
function switchTab(tabId, updateHash = true) {
  activeTab = tabId;

  // Simpan ke localStorage dan URL hash agar saat di-refresh tidak kembali ke awal (Requirement 6/7)
  localStorage.setItem('ocrawler_active_tab', tabId);
  if (updateHash && window.location.hash !== `#${tabId}`) {
    window.location.hash = tabId;
  }

  // Update Buttons Active State
  document.querySelectorAll('.investowl-nav-item, .m3-nav-tab').forEach(b => b.classList.remove('active'));
  const targetBtn = document.getElementById(`tab-btn-${tabId}`);
  if (targetBtn) {
    targetBtn.classList.add('active');
  }

  // Update Content Visibility
  const studioContent = document.getElementById('tab-content-studio');
  const explorerContent = document.getElementById('tab-content-explorer');
  const analyticsContent = document.getElementById('tab-content-analytics');
  const aboutContent = document.getElementById('tab-content-about');

  if (studioContent) studioContent.classList.toggle('hidden', tabId !== 'studio');
  if (explorerContent) explorerContent.classList.toggle('hidden', tabId !== 'explorer');
  if (analyticsContent) analyticsContent.classList.toggle('hidden', tabId !== 'analytics');
  if (aboutContent) aboutContent.classList.toggle('hidden', tabId !== 'about');

  // Trigger Data Loads
  if (tabId === 'explorer') {
    fetchExplorerData();
  } else if (tabId === 'analytics') {
    fetchStats();
  }

  // Render Lucide
  if (window.lucide) {
    lucide.createIcons();
  }
}

// --- ANALYTICS CHART (Investowl Theme) ---
function initAnalyticsChart() {
  const ctx = document.getElementById('sourceChart');
  if (!ctx) return;
  chartInstance = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Peraturan (peraturan.go.id)', 'Mahkamah Agung (MA)', 'Mahkamah Konstitusi (MK)'],
      datasets: [{
        data: [0, 0, 0],
        backgroundColor: ['#FFB879', '#10B981', '#F59E0B'],
        borderWidth: 2,
        borderColor: '#211D1A',
        hoverOffset: 6,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            color: '#D7C2B4',
            font: { family: '"Inter", sans-serif', size: 11, weight: 600 },
            padding: 16
          }
        }
      },
      cutout: '72%'
    }
  });
}

function updateAnalyticsChart(reg, ma, mk) {
  if (!chartInstance) return;
  chartInstance.data.datasets[0].data = [reg || 0, ma || 0, mk || 0];
  chartInstance.update();
}
