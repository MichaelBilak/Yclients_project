import Chart from 'chart.js/auto';

const apiBase = import.meta.env.VITE_API_BASE || '';
const apiKey = import.meta.env.VITE_API_KEY || '';

const els = {
  start: document.getElementById('start'),
  end: document.getElementById('end'),
  branch: document.getElementById('branch'),
  load: document.getElementById('load'),
  kpi: document.getElementById('kpi'),
  error: document.getElementById('error'),
  apiState: document.getElementById('api-state'),
  syncState: document.getElementById('sync-state'),
  periodLabel: document.getElementById('period-label'),
  revenueMeta: document.getElementById('revenue-meta'),
  appointmentsMeta: document.getElementById('appointments-meta'),
  servicesMeta: document.getElementById('services-meta'),
  tableMeta: document.getElementById('table-meta'),
  servicesTable: document.getElementById('services-table'),
  revenueChart: document.getElementById('revenue-chart'),
  appointmentsChart: document.getElementById('appointments-chart'),
  servicesChart: document.getElementById('services-chart'),
};

const charts = {
  revenue: null,
  appointments: null,
  services: null,
};

function headers() {
  const h = {};
  if (apiKey) h['X-API-Key'] = apiKey;
  return h;
}

function apiUrl(path, params = {}) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      qs.set(key, value);
    }
  });
  const suffix = qs.toString() ? `?${qs}` : '';
  const normalizedPath = `${path}${suffix}`;
  if (!apiBase) return normalizedPath;
  return `${apiBase.replace(/\/$/, '')}${normalizedPath}`;
}

function formatMoney(value) {
  return `${Math.round(Number(value || 0)).toLocaleString('ru-RU')} ₽`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString('ru-RU');
}

function formatPct(value) {
  if (value === null || value === undefined) return 'нет базы';
  const sign = value > 0 ? '+' : '';
  return `${sign}${Number(value).toLocaleString('ru-RU')}% к прошлому периоду`;
}

function deltaClass(value) {
  if (value === null || value === undefined || value === 0) return '';
  return value > 0 ? 'up' : 'down';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function setApiState(text, kind = 'warn') {
  els.apiState.textContent = text;
  els.apiState.className = `pill ${kind}`;
}

function showError(message) {
  els.error.textContent = message;
  els.error.classList.add('visible');
  setApiState('API: ошибка', 'error');
}

function clearError() {
  els.error.textContent = '';
  els.error.classList.remove('visible');
}

async function fetchJson(path, params) {
  const url = apiUrl(path, params);
  let response;
  try {
    response = await fetch(url, { headers: headers() });
  } catch (error) {
    throw new Error(
      `Не удалось подключиться к API: ${url}\n\n${error.message}\n\nПроверь, что локальный API запущен на 127.0.0.1:8000 и в Vercel задан VITE_API_BASE.`,
    );
  }

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`API вернул ${response.status} для ${url}\n\n${body.slice(0, 1000)}`);
  }

  const payload = await response.json();
  if (payload.success === false) {
    throw new Error(`API вернул success=false для ${url}`);
  }
  return payload;
}

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 30);
  els.end.value = end.toISOString().slice(0, 10);
  els.start.value = start.toISOString().slice(0, 10);
}

function renderKpi(summary) {
  const revenue = summary.revenue || {};
  const appointments = summary.appointments_breakdown || {};
  const cards = [
    {
      label: 'Выручка',
      value: formatMoney(revenue.total),
      delta: formatPct(revenue.change_pct),
      deltaValue: revenue.change_pct,
    },
    {
      label: 'Посещенные записи',
      value: formatNumber(revenue.appointments),
      delta: formatPct(revenue.appointments_change_pct),
      deltaValue: revenue.appointments_change_pct,
    },
    {
      label: 'Уникальные клиенты',
      value: formatNumber(revenue.unique_clients),
      delta: formatPct(revenue.unique_clients_change_pct),
      deltaValue: revenue.unique_clients_change_pct,
    },
    {
      label: 'Отмены / ожидание',
      value: `${formatNumber(appointments.cancelled)} / ${formatNumber(appointments.pending)}`,
      delta: `${formatNumber(appointments.attended)} посещений`,
      deltaValue: null,
    },
  ];

  els.kpi.innerHTML = cards
    .map(
      (card) => `
        <article class="card">
          <div class="label">${escapeHtml(card.label)}</div>
          <div class="value">${escapeHtml(card.value)}</div>
          <div class="delta ${deltaClass(card.deltaValue)}">${escapeHtml(card.delta)}</div>
        </article>
      `,
    )
    .join('');
}

function destroyChart(name) {
  if (charts[name]) {
    charts[name].destroy();
    charts[name] = null;
  }
}

function renderRevenueChart(daily) {
  destroyChart('revenue');
  charts.revenue = new Chart(els.revenueChart, {
    type: 'line',
    data: {
      labels: daily.map((item) => item.date),
      datasets: [
        {
          label: 'Выручка',
          data: daily.map((item) => item.revenue),
          borderColor: '#0f766e',
          backgroundColor: 'rgba(15, 118, 110, 0.12)',
          fill: true,
          tension: 0.28,
          pointRadius: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { callback: (value) => formatMoney(value).replace(' ₽', '') },
        },
      },
      plugins: {
        tooltip: {
          callbacks: { label: (ctx) => ` ${formatMoney(ctx.parsed.y)}` },
        },
      },
    },
  });
}

function renderAppointmentsChart(daily) {
  destroyChart('appointments');
  charts.appointments = new Chart(els.appointmentsChart, {
    type: 'bar',
    data: {
      labels: daily.map((item) => item.date),
      datasets: [
        {
          label: 'Записи',
          data: daily.map((item) => item.appointments),
          backgroundColor: '#2563eb',
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true } },
    },
  });
}

function renderServicesChart(services) {
  destroyChart('services');
  charts.services = new Chart(els.servicesChart, {
    type: 'bar',
    data: {
      labels: services.map((item) => item.title || `Услуга ${item.service_id || ''}`),
      datasets: [
        {
          label: 'Выручка',
          data: services.map((item) => item.revenue),
          backgroundColor: '#b45309',
          borderRadius: 4,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          beginAtZero: true,
          ticks: { callback: (value) => formatMoney(value).replace(' ₽', '') },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: (ctx) => ` ${formatMoney(ctx.parsed.x)}` },
        },
      },
    },
  });
}

function renderServicesTable(services) {
  if (!services.length) {
    els.servicesTable.innerHTML = '<div class="empty">Нет услуг за выбранный период</div>';
    return;
  }

  els.servicesTable.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Услуга</th>
          <th class="number">Продано</th>
          <th class="number">Выручка</th>
        </tr>
      </thead>
      <tbody>
        ${services
          .map(
            (item) => `
              <tr>
                <td>${escapeHtml(item.title || `Услуга ${item.service_id || ''}`)}</td>
                <td class="number">${formatNumber(item.sold)}</td>
                <td class="number">${formatMoney(item.revenue)}</td>
              </tr>
            `,
          )
          .join('')}
      </tbody>
    </table>
  `;
}

function renderBundle(bundle) {
  const { summary, revenue_daily: daily = [], top_services: services = [] } = bundle;
  renderKpi(summary);
  renderRevenueChart(daily);
  renderAppointmentsChart(daily);
  renderServicesChart(services.slice(0, 8));
  renderServicesTable(services);

  els.periodLabel.textContent = `${summary.period.start} .. ${summary.period.end}`;
  els.revenueMeta.textContent = `${daily.length} дней`;
  els.appointmentsMeta.textContent = `${formatNumber(summary.revenue.appointments)} записей`;
  els.servicesMeta.textContent = `${services.length} услуг`;
  els.tableMeta.textContent = `${formatMoney(summary.revenue.total)} всего`;
}

async function loadBranches() {
  try {
    const payload = await fetchJson('/dashboard/branches');
    const branches = payload.data || [];
    els.branch.innerHTML = '<option value="">Все филиалы</option>';
    branches.forEach((branch) => {
      const option = document.createElement('option');
      option.value = branch.id;
      option.textContent = branch.title;
      els.branch.appendChild(option);
    });
  } catch (error) {
    showError(error.message);
  }
}

async function loadSyncStatus() {
  try {
    const payload = await fetchJson('/dashboard/widget/sync_status');
    const lastRun = payload.data?.sync?.last_run;
    const queue = payload.data?.queue;
    const parts = [];
    if (lastRun?.status) parts.push(`последний запуск: ${lastRun.status}`);
    if (lastRun?.finished_at) parts.push(lastRun.finished_at.slice(0, 19).replace('T', ' '));
    if (queue) parts.push(`очередь: ${queue.queued_jobs}, running: ${queue.running_jobs}`);
    els.syncState.textContent = parts.length ? `Синхронизация: ${parts.join(' · ')}` : 'Синхронизация: нет запусков';
  } catch {
    els.syncState.textContent = 'Синхронизация: статус недоступен';
  }
}

async function loadDashboard() {
  clearError();
  els.load.disabled = true;
  els.load.textContent = 'Загрузка';
  setApiState('API: загрузка', 'warn');

  try {
    const payload = await fetchJson('/dashboard/bundle', {
      start_date: els.start.value,
      end_date: els.end.value,
      company_id: els.branch.value,
    });
    renderBundle(payload.data);
    setApiState('API: подключен', 'ok');
    await loadSyncStatus();
  } catch (error) {
    showError(error.message);
  } finally {
    els.load.disabled = false;
    els.load.textContent = 'Обновить';
  }
}

async function init() {
  defaultDates();
  renderServicesTable([]);
  await loadBranches();
  await loadDashboard();
}

els.load.addEventListener('click', () => loadDashboard());
els.branch.addEventListener('change', () => loadDashboard());
init();
