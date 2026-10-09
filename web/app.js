/**
 * O-Crawler SaaS Frontend Engine.
 * Menghubungkan antarmuka GUI ke FastAPI backend & WebSocket telemetry.
 */

// State Aplikasi
let currentSource = 'peraturan';
let activeTab = 'studio';
let explorerType = 'regulations';
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

// Inisialisasi Saat Load
document.addEventListener('DOMContentLoaded', () => {
  initWebSocket();
  populateCategories(currentSource);
  fetchStats();
  fetchExplorerData();
  initAnalyticsChart();

  // Polling stats setiap 5 detik
  setInterval(fetchStats, 5000);
});

// --- WEBSOCKET TELEMETRY ---
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/crawler`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    document.getElementById('ws-indicator').className = 'w-2 h-2 rounded-full bg-emerald-500 animate-pulse';
    document.getElementById('ws-status-text').innerText = 'Tersambung';
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
    document.getElementById('ws-indicator').className = 'w-2 h-2 rounded-full bg-rose-500';
    document.getElementById('ws-status-text').innerText = 'Terputus';
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
  document.getElementById('terminal-logs').innerHTML = '';
}

// --- STATE & CONTROLS ---
function selectSource(source) {
  currentSource = source;
  document.querySelectorAll('.source-card').forEach(c => c.classList.remove('active'));
  document.getElementById(`src-btn-${source}`).classList.add('active');

  const catLabel = document.getElementById('category-label');
  if (source === 'peraturan') catLabel.innerText = 'Kategori Peraturan';
  else if (source === 'ma') catLabel.innerText = 'Kategori Klasifikasi MA';
  else catLabel.innerText = 'Jenis Perkara MK';

  populateCategories(source);
}

function populateCategories(source) {
  const select = document.getElementById('crawl-category');
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
  document.getElementById('concurrency-val').innerText = `${val} Workers`;
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
    statusTitle.innerText = `Sedang Berjalan (${state.config ? state.config.source.toUpperCase() : ''})`;
    statusPulse.className = 'w-3 h-3 rounded-full bg-emerald-500 animate-ping';
    speedBadge.innerText = state.speed || '0 dok/dtk';
    detail.innerText = `Dokumen terproses: ${state.total_crawled || 0} (${state.total_articles || 0} pasal/ekstraksi)`;
    bar.style.width = '75%';
  } else {
    statusTitle.innerText = state.status === 'COMPLETED' ? 'Selesai' : 'Crawler Standby';
    statusPulse.className = 'w-3 h-3 rounded-full bg-slate-600';
    speedBadge.innerText = '0 dok/dtk';
    bar.style.width = state.status === 'COMPLETED' ? '100%' : '0%';
  }

  // Update DB & R2 badge
  if (state.db_type) document.getElementById('db-badge').innerText = state.db_type;
  if (state.r2_active !== undefined) {
    document.getElementById('r2-badge').innerText = state.r2_active ? 'R2 Aktif' : 'R2 Non-aktif';
  }
}

function updateUIButtons(running) {
  document.getElementById('btn-start-crawl').disabled = running;
  document.getElementById('btn-stop-crawl').disabled = !running;
  if (running) {
    document.getElementById('btn-start-crawl').classList.add('opacity-50', 'cursor-not-allowed');
  } else {
    document.getElementById('btn-start-crawl').classList.remove('opacity-50', 'cursor-not-allowed');
  }
}

// --- STATS OVERVIEW ---
async function fetchStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById('stat-regulations').innerText = (data.total_regulations || 0).toLocaleString();
    document.getElementById('stat-articles').innerText = (data.total_articles || 0).toLocaleString();
    document.getElementById('stat-ma').innerText = (data.decisions_ma || 0).toLocaleString();
    document.getElementById('stat-mk').innerText = (data.decisions_mk || 0).toLocaleString();

    document.getElementById('db-badge').innerText = data.is_postgres ? 'PostgreSQL' : 'SQLite Local';

    updateAnalyticsChart(data.total_regulations, data.decisions_ma, data.decisions_mk);
  } catch (e) {
    console.error(e);
  }
}

// --- DATA EXPLORER ---
function setExplorerTab(type) {
  explorerType = type;
  explorerPage = 1;

  if (type === 'regulations') {
    document.getElementById('exp-tab-reg').className = 'px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white transition';
    document.getElementById('exp-tab-dec').className = 'px-3 py-1.5 text-xs font-semibold rounded-lg text-slate-400 hover:text-white transition';
    document.getElementById('btn-export-csv').href = '/api/export?type=regulations&format=csv';
    document.getElementById('btn-export-json').href = '/api/export?type=regulations&format=json';
  } else {
    document.getElementById('exp-tab-dec').className = 'px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white transition';
    document.getElementById('exp-tab-reg').className = 'px-3 py-1.5 text-xs font-semibold rounded-lg text-slate-400 hover:text-white transition';
    document.getElementById('btn-export-csv').href = '/api/export?type=decisions&format=csv';
    document.getElementById('btn-export-json').href = '/api/export?type=decisions&format=json';
  }

  fetchExplorerData();
}

function debounceSearch() {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    explorerPage = 1;
    fetchExplorerData();
  }, 400);
}

function changePage(delta) {
  explorerPage = Math.max(1, explorerPage + delta);
  fetchExplorerData();
}

async function fetchExplorerData() {
  const q = document.getElementById('explorer-search').value.trim();
  const endpoint = explorerType === 'regulations'
    ? `/api/data/regulations?q=${encodeURIComponent(q)}&page=${explorerPage}&limit=20`
    : `/api/data/decisions?q=${encodeURIComponent(q)}&page=${explorerPage}&limit=20`;

  try {
    const res = await fetch(endpoint);
    const data = await res.json();
    renderTable(data.items || []);
    document.getElementById('explorer-page-info').innerText = `Halaman ${explorerPage} (${data.count} dokumen)`;
    document.getElementById('btn-prev-page').disabled = explorerPage <= 1;
    document.getElementById('btn-next-page').disabled = (data.items || []).length < 20;
  } catch (e) {
    console.error(e);
  }
}

function renderTable(items) {
  const headers = document.getElementById('table-headers');
  const tbody = document.getElementById('table-body');
  tbody.innerHTML = '';

  if (explorerType === 'regulations') {
    headers.innerHTML = `
      <th class="py-3 px-4">Jenis & No</th>
      <th class="py-3 px-4">Tahun</th>
      <th class="py-3 px-4">Judul Dokumen</th>
      <th class="py-3 px-4">Total Pasal</th>
      <th class="py-3 px-4 text-right">Aksi</th>
    `;
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="py-8 text-center text-slate-500">Belum ada regulasi tersimpan. Jalankan crawler untuk mulai mengumpulkan data.</td></tr>`;
      return;
    }
    items.forEach(it => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-slate-900/40 transition';
      tr.innerHTML = `
        <td class="py-3 px-4 font-semibold text-white whitespace-nowrap">${it.jenis} No. ${it.nomor}</td>
        <td class="py-3 px-4 text-slate-400">${it.tahun}</td>
        <td class="py-3 px-4 max-w-md truncate" title="${it.judul}">${it.judul}</td>
        <td class="py-3 px-4"><span class="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 font-mono text-[11px]">${it.total_pasal || 0} Pasal</span></td>
        <td class="py-3 px-4 text-right whitespace-nowrap">
          ${it.pdf_path ? `<a href="${it.pdf_path}" target="_blank" class="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-indigo-400 rounded-lg mr-1 inline-flex items-center space-x-1"><span>PDF</span></a>` : ''}
          <button onclick='viewRegulationDetail(${JSON.stringify(it).replace(/'/g, "&#39;")})' class="px-2.5 py-1 text-xs bg-indigo-600/20 text-indigo-300 hover:bg-indigo-600 hover:text-white rounded-lg">Detail</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } else {
    // Court Decisions
    headers.innerHTML = `
      <th class="py-3 px-4">Lembaga</th>
      <th class="py-3 px-4">No. Perkara</th>
      <th class="py-3 px-4">Tahun</th>
      <th class="py-3 px-4">Amar / Pokok Perkara</th>
      <th class="py-3 px-4 text-right">Aksi</th>
    `;
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="py-8 text-center text-slate-500">Belum ada putusan tersimpan. Jalankan crawler Mahkamah Agung / Mahkamah Konstitusi.</td></tr>`;
      return;
    }
    items.forEach(it => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-slate-900/40 transition';
      const badgeColor = it.lembaga === 'MA' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-400';
      tr.innerHTML = `
        <td class="py-3 px-4"><span class="px-2 py-0.5 rounded font-bold text-[10px] ${badgeColor}">${it.lembaga}</span></td>
        <td class="py-3 px-4 font-semibold text-white whitespace-nowrap">${it.nomor_perkara}</td>
        <td class="py-3 px-4 text-slate-400">${it.tahun || '-'}</td>
        <td class="py-3 px-4 max-w-md truncate" title="${it.amar_putusan || it.judul}">${it.amar_putusan || it.judul}</td>
        <td class="py-3 px-4 text-right whitespace-nowrap">
          ${it.pdf_path ? `<a href="${it.pdf_path}" target="_blank" class="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-indigo-400 rounded-lg mr-1 inline-flex items-center space-x-1"><span>PDF</span></a>` : ''}
          <button onclick='viewDecisionDetail(${JSON.stringify(it).replace(/'/g, "&#39;")})' class="px-2.5 py-1 text-xs bg-indigo-600/20 text-indigo-300 hover:bg-indigo-600 hover:text-white rounded-lg">Detail</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }
}

// --- MODAL PREVIEWS ---
function viewRegulationDetail(it) {
  document.getElementById('modal-title').innerText = `${it.jenis} Nomor ${it.nomor} Tahun ${it.tahun}`;
  const c = document.getElementById('modal-content');
  c.innerHTML = `
    <div class="p-3 bg-slate-950 rounded-xl border border-slate-800">
      <span class="text-slate-400 block text-[11px] mb-1">Judul Resmi:</span>
      <p class="font-medium text-white">${it.judul}</p>
    </div>
    <div class="grid grid-cols-2 gap-3">
      <div class="p-3 bg-slate-950 rounded-xl border border-slate-800">
        <span class="text-slate-400 block text-[11px] mb-1">Status Keberlakuan:</span>
        <span class="font-semibold text-emerald-400">${it.status || 'BERLAKU'}</span>
      </div>
      <div class="p-3 bg-slate-950 rounded-xl border border-slate-800">
        <span class="text-slate-400 block text-[11px] mb-1">Total Pasal Terindeks:</span>
        <span class="font-mono text-indigo-400 font-bold">${it.total_pasal || 0} Pasal</span>
      </div>
    </div>
    ${it.pdf_path ? `
    <div class="pt-2">
      <a href="${it.pdf_path}" target="_blank" class="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl flex items-center justify-center space-x-2 font-medium">
        <span>Buka / Unduh Berkas Salinan Asli (PDF)</span>
      </a>
    </div>` : ''}
  `;
  document.getElementById('detail-modal').classList.remove('hidden');
}

function viewDecisionDetail(it) {
  document.getElementById('modal-title').innerText = `Putusan ${it.lembaga} No. ${it.nomor_perkara}`;
  const c = document.getElementById('modal-content');
  c.innerHTML = `
    <div class="p-3 bg-slate-950 rounded-xl border border-slate-800">
      <span class="text-slate-400 block text-[11px] mb-1">Judul / Pokok Perkara:</span>
      <p class="font-medium text-white">${it.judul}</p>
    </div>
    ${it.para_pihak ? `
    <div class="p-3 bg-slate-950 rounded-xl border border-slate-800">
      <span class="text-slate-400 block text-[11px] mb-1">Para Pihak Berperkara:</span>
      <p class="text-slate-200">${it.para_pihak}</p>
    </div>` : ''}
    <div class="p-3 bg-slate-950 rounded-xl border border-slate-800">
      <span class="text-slate-400 block text-[11px] mb-1">Amar Putusan:</span>
      <p class="text-slate-200 whitespace-pre-wrap">${it.amar_putusan || 'Amar belum dimuat'}</p>
    </div>
    ${it.pdf_path ? `
    <div class="pt-2">
      <a href="${it.pdf_path}" target="_blank" class="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl flex items-center justify-center space-x-2 font-medium">
        <span>Buka / Unduh Berkas Putusan Resmi (PDF)</span>
      </a>
    </div>` : ''}
  `;
  document.getElementById('detail-modal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('detail-modal').classList.add('hidden');
}

// --- TAB SWITCHER ---
function switchTab(tabId) {
  activeTab = tabId;
  document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));
  document.getElementById(`tab-btn-${tabId}`).classList.add('active');

  document.getElementById('tab-content-studio').classList.toggle('hidden', tabId !== 'studio');
  document.getElementById('tab-content-explorer').classList.toggle('hidden', tabId !== 'explorer');
  document.getElementById('tab-content-analytics').classList.toggle('hidden', tabId !== 'analytics');

  if (tabId === 'explorer') fetchExplorerData();
}

// --- ANALYTICS CHART ---
function initAnalyticsChart() {
  const ctx = document.getElementById('sourceChart');
  if (!ctx) return;
  chartInstance = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Peraturan (peraturan.go.id)', 'Mahkamah Agung (MA)', 'Mahkamah Konstitusi (MK)'],
      datasets: [{
        data: [0, 0, 0],
        backgroundColor: ['#6366f1', '#10b981', '#f59e0b'],
        borderWidth: 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#94a3b8', font: { family: 'Inter', size: 11 } }
        }
      }
    }
  });
}

function updateAnalyticsChart(reg, ma, mk) {
  if (!chartInstance) return;
  chartInstance.data.datasets[0].data = [reg || 0, ma || 0, mk || 0];
  chartInstance.update();
}
