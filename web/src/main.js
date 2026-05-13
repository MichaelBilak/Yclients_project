import Chart from 'chart.js/auto';

const apiBase = import.meta.env.VITE_API_BASE || '';
const apiKey = import.meta.env.VITE_API_KEY || '';

function headers() {
  const h = {};
  if (apiKey) h['X-API-Key'] = apiKey;
  return h;
}

function bundleUrl() {
  const start = document.getElementById('start').value;
  const end = document.getElementById('end').value;
  const qs = new URLSearchParams({ start_date: start, end_date: end });
  const path = `/dashboard/bundle?${qs}`;
  if (apiBase) return `${apiBase.replace(/\/$/, '')}${path}`;
  return path;
}

let chart;

function renderKpi(summary) {
  const el = document.getElementById('kpi');
  const rev = summary.revenue;
  const cards = [
    ['Выручка', `${Math.round(rev.total).toLocaleString('ru-RU')} ₽`, rev.change_pct],
    ['Записи (посещ.)', String(rev.appointments), rev.appointments_change_pct],
    ['Уник. клиенты', String(rev.unique_clients), rev.unique_clients_change_pct],
  ];
  el.innerHTML = cards
    .map(
      ([t, v, ch]) => `
    <div class="card">
      <h3>${t}</h3>
      <div class="v">${v}</div>
      <div class="muted">${ch == null ? '—' : `${ch > 0 ? '+' : ''}${ch}% к прошлому периоду`}</div>
    </div>`,
    )
    .join('');
}

function renderChart(daily) {
  const ctx = document.getElementById('chart');
  const labels = daily.map((d) => d.date);
  const values = daily.map((d) => d.revenue);
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Выручка',
          data: values,
          borderColor: '#ea580c',
          backgroundColor: 'rgba(234, 88, 12, 0.08)',
          fill: true,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true },
      },
    },
  });
}

async function load() {
  const r = await fetch(bundleUrl(), { headers: headers() });
  if (!r.ok) {
    alert(`Ошибка ${r.status}: ${await r.text()}`);
    return;
  }
  const body = await r.json();
  if (!body.success) {
    alert('Ответ без success');
    return;
  }
  const { summary, revenue_daily: daily } = body.data;
  renderKpi(summary);
  renderChart(daily);
}

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 30);
  document.getElementById('end').value = end.toISOString().slice(0, 10);
  document.getElementById('start').value = start.toISOString().slice(0, 10);
}

defaultDates();
document.getElementById('load').addEventListener('click', () => load());
