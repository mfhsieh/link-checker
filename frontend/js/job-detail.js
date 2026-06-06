/**
 * job-detail.js — 任務詳情頁面邏輯（ESM）
 */

import * as api from './api.js';
import { download } from './api.js';
import { toast } from './toast.js';

const STATUS_LABELS = {
  pending: '等待中', running: '執行中',
  paused: '已暫停', completed: '已完成', error: '錯誤',
};

let _pollTimer = null;
let _currentJobId = null;
let _currentFilter = null;
let _currentSearch = '';
let _currentGroup = false;
let _currentPage = 1;

function startPolling(jobId) {
  stopPolling();
  _pollTimer = setInterval(() => refreshJobDetail(jobId), 3000);
}

function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

export async function initJobDetailPage(jobId) {
  _currentJobId = jobId;
  _currentFilter = null;
  _currentSearch = '';
  _currentGroup = false;
  _currentPage = 1;

  await refreshJobDetail(jobId);
  await loadResults(jobId);
  bindControlButtons(jobId);
  bindResultsControls(jobId);
}

export function destroyJobDetailPage() {
  stopPolling();
}

async function refreshJobDetail(jobId) {
  try {
    const job = await api.get(`/api/jobs/${jobId}`);
    renderJobInfo(job);

    if (job.status === 'running') {
      startPolling(jobId);
    } else {
      stopPolling();
    }
  } catch (err) {
    toast.error('無法取得任務資訊：' + err.message);
  }
}

function renderJobInfo(job) {
  const el = (id) => document.getElementById(id);

  const statusEl = el('job-status');
  if (statusEl) {
    statusEl.className = `badge badge-${job.status}`;
    statusEl.textContent = STATUS_LABELS[job.status] || job.status;
  }

  setTextContent('job-start-url', job.start_url);
  setTextContent('job-created-at', job.created_at ? new Date(job.created_at).toLocaleString('zh-TW') : '-');
  setTextContent('job-updated-at', job.updated_at ? new Date(job.updated_at).toLocaleString('zh-TW') : '-');
  setTextContent('job-external-count', job.external_link_count ?? 0);

  const progress = job.progress || {};
  const total = progress.total || 0;
  const done = (progress.completed || 0) + (progress.skipped || 0) + (progress.failed || 0);
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const progressFill = el('job-progress-fill');
  const progressText = el('job-progress-text');
  if (progressFill) progressFill.style.width = pct + '%';
  if (progressText) progressText.textContent = `${pct}% (${done} / ${total})`;

  setTextContent('stat-total', total);
  setTextContent('stat-completed', progress.completed || 0);
  setTextContent('stat-pending', progress.pending || 0);
  setTextContent('stat-failed', progress.failed || 0);

  const canStart = ['pending', 'paused'].includes(job.status);
  const canPause = job.status === 'running';
  const canReset = ['completed', 'error', 'paused'].includes(job.status);

  toggleDisplay('btn-start-job', canStart);
  toggleDisplay('btn-resume-job', false);
  toggleDisplay('btn-pause-job', canPause);
  toggleDisplay('btn-reset-job', canReset);
}

function bindControlButtons(jobId) {
  bindBtn('btn-start-job', async () => {
    await api.post(`/api/jobs/${jobId}/start`);
    toast.success('任務已啟動！');
    await refreshJobDetail(jobId);
  });

  bindBtn('btn-pause-job', async () => {
    await api.post(`/api/jobs/${jobId}/pause`);
    toast.info('暫停指令已送出，任務將在完成當前頁面後停止。');
    await refreshJobDetail(jobId);
  });

  bindBtn('btn-reset-job', async () => {
    if (!confirm('確定要重置任務嗎？這將清除所有外連結果並重新開始。')) return;
    await api.post(`/api/jobs/${jobId}/reset`);
    toast.success('任務已重置。');
    await refreshJobDetail(jobId);
    await loadResults(jobId);
  });

  bindBtn('btn-delete-job', async () => {
    if (!confirm('確定要刪除此任務嗎？此操作無法復原。')) return;
    await api.del(`/api/jobs/${jobId}`);
    toast.success('任務已刪除。');
    window.location.hash = '#/jobs';
  });

  bindBtn('btn-back-jobs', () => {
    window.location.hash = '#/jobs';
  });
}

async function loadResults(jobId) {
  const container = document.getElementById('results-container');
  if (!container) return;

  try {
    const summary = await api.get(`/api/jobs/${jobId}/results/summary`);
    renderResultsSummary(summary);
  } catch (_) { /* 忽略 */ }

  await loadResultsPage(jobId);
}

async function loadResultsPage(jobId) {
  const container = document.getElementById('results-container');
  if (!container) return;

  container.replaceChildren();
  const skeleton = document.createElement('div');
  skeleton.className = 'skeleton';
  skeleton.style.height = '200px';
  skeleton.style.borderRadius = '0.5rem';
  container.appendChild(skeleton);

  try {
    const params = {
      filter: _currentFilter || undefined,
      search: _currentSearch || undefined,
      group: _currentGroup ? 'true' : 'false',
      page: _currentPage,
      page_size: 50,
    };
    const res = await api.get(`/api/jobs/${jobId}/results`, params);
    renderResultsTable(res, container);
    renderPagination(res, jobId);
  } catch (err) {
    container.replaceChildren();
    const emptyState = document.createElement('div');
    emptyState.className = 'empty-state';
    const desc = document.createElement('div');
    desc.className = 'empty-state-desc text-danger';
    desc.textContent = err.message;
    emptyState.appendChild(desc);
    container.appendChild(emptyState);
  }
}

function renderResultsSummary(summary) {
  setTextContent('summary-total', summary.total_external_links ?? 0);
  setTextContent('summary-dns-failed', summary.dns_failed_count ?? 0);
  setTextContent('summary-http-error', summary.http_error_count ?? 0);
  setTextContent('summary-insecure', summary.insecure_count ?? 0);
}

function renderResultsTable(res, container) {
  const items = res.items || [];
  container.replaceChildren();
  if (items.length === 0) {
    const emptyState = document.createElement('div');
    emptyState.className = 'empty-state';
    const title = document.createElement('div');
    title.className = 'empty-state-title';
    title.textContent = '無結果';
    const desc = document.createElement('div');
    desc.className = 'empty-state-desc';
    desc.textContent = '目前沒有符合條件的外連結果';
    emptyState.appendChild(title);
    emptyState.appendChild(desc);
    container.appendChild(emptyState);
    return;
  }

  const isGrouped = _currentGroup;
  const headers = isGrouped
    ? ['目標 URL', 'IP 位址', '安全', 'HTTP 狀態', '來源數', '錯誤訊息']
    : ['來源頁面', '目標 URL', 'IP 位址', '安全', 'HTTP 狀態', '錯誤訊息'];

  const wrapper = document.createElement('div');
  wrapper.className = 'table-wrapper';

  const table = document.createElement('table');
  table.className = 'table';

  const thead = document.createElement('thead');
  const trHead = document.createElement('tr');
  headers.forEach(h => {
    const th = document.createElement('th');
    th.textContent = h;
    trHead.appendChild(th);
  });
  thead.appendChild(trHead);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  items.forEach(item => {
    const isSecure = item.is_secure;
    const status = item.http_status_code;
    const statusClass = !status ? 'text-muted' : (status >= 400 ? 'text-danger' : 'text-success');

    const tr = document.createElement('tr');
    
    if (!isGrouped) {
      const tdSource = document.createElement('td');
      tdSource.className = 'truncate text-xs text-muted';
      tdSource.style.maxWidth = '200px';
      tdSource.title = item.source_url;
      tdSource.textContent = item.source_url;
      tr.appendChild(tdSource);
    }

    const tdTarget = document.createElement('td');
    tdTarget.className = 'truncate';
    tdTarget.style.maxWidth = '260px';
    tdTarget.title = item.target_url;
    tdTarget.textContent = item.target_url;
    tr.appendChild(tdTarget);

    const tdIp = document.createElement('td');
    tdIp.className = 'font-mono text-xs';
    tdIp.textContent = item.ip_address || '-';
    tr.appendChild(tdIp);

    const tdSecure = document.createElement('td');
    const spanSecure = document.createElement('span');
    spanSecure.className = isSecure ? 'text-success' : 'text-danger';
    spanSecure.textContent = isSecure ? '✓' : '✗';
    tdSecure.appendChild(spanSecure);
    tr.appendChild(tdSecure);

    const tdStatus = document.createElement('td');
    tdStatus.className = statusClass;
    tdStatus.textContent = status ?? '-';
    tr.appendChild(tdStatus);

    if (isGrouped) {
      const tdOcc = document.createElement('td');
      tdOcc.textContent = item.occurrence_count ?? '-';
      tr.appendChild(tdOcc);
    }

    const tdError = document.createElement('td');
    tdError.className = 'text-xs text-muted truncate';
    tdError.style.maxWidth = isGrouped ? '180px' : '160px';
    tdError.textContent = item.error_message || '-';
    tr.appendChild(tdError);

    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrapper.appendChild(table);

  container.appendChild(wrapper);

  const paginationContainer = document.createElement('div');
  paginationContainer.id = 'results-pagination';
  container.appendChild(paginationContainer);
}

function renderPagination(res, jobId) {
  const paginationEl = document.getElementById('results-pagination');
  if (!paginationEl) return;

  paginationEl.replaceChildren();
  const { page, total_pages } = res;
  if (total_pages <= 1) return;

  const paginationDiv = document.createElement('div');
  paginationDiv.className = 'pagination';

  const btnPrev = document.createElement('button');
  btnPrev.className = 'page-btn';
  btnPrev.textContent = '‹';
  if (page <= 1) btnPrev.disabled = true;
  else {
    btnPrev.dataset.page = page - 1;
    btnPrev.addEventListener('click', async () => {
      _currentPage = page - 1;
      await loadResultsPage(jobId);
    });
  }
  paginationDiv.appendChild(btnPrev);

  const delta = 2;
  const start = Math.max(1, page - delta);
  const end = Math.min(total_pages, page + delta);

  for (let i = start; i <= end; i++) {
    const pBtn = document.createElement('button');
    pBtn.className = i === page ? 'page-btn active' : 'page-btn';
    pBtn.textContent = i;
    pBtn.dataset.page = i;
    if (i !== page) {
      pBtn.addEventListener('click', async () => {
        _currentPage = i;
        await loadResultsPage(jobId);
      });
    }
    paginationDiv.appendChild(pBtn);
  }

  const btnNext = document.createElement('button');
  btnNext.className = 'page-btn';
  btnNext.textContent = '›';
  if (page >= total_pages) btnNext.disabled = true;
  else {
    btnNext.dataset.page = page + 1;
    btnNext.addEventListener('click', async () => {
      _currentPage = page + 1;
      await loadResultsPage(jobId);
    });
  }
  paginationDiv.appendChild(btnNext);

  paginationEl.appendChild(paginationDiv);
}

function bindResultsControls(jobId) {
  document.querySelectorAll('.filter-chip[data-filter]').forEach(chip => {
    chip.addEventListener('click', async () => {
      const filter = chip.dataset.filter || null;
      _currentFilter = _currentFilter === filter ? null : filter;
      _currentPage = 1;
      document.querySelectorAll('.filter-chip[data-filter]').forEach(c => {
        c.classList.toggle('active', c.dataset.filter === _currentFilter);
      });
      await loadResultsPage(jobId);
    });
  });

  const searchInput = document.getElementById('results-search');
  if (searchInput) {
    let debounceTimer;
    searchInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(async () => {
        _currentSearch = searchInput.value.trim();
        _currentPage = 1;
        await loadResultsPage(jobId);
      }, 400);
    });
  }

  const groupToggle = document.getElementById('results-group-toggle');
  if (groupToggle) {
    groupToggle.addEventListener('change', async () => {
      _currentGroup = groupToggle.checked;
      _currentPage = 1;
      await loadResultsPage(jobId);
    });
  }

  bindBtn('btn-export-csv', async () => {
    const params = new URLSearchParams({ fmt: 'csv', group: _currentGroup });
    if (_currentFilter) params.set('filter', _currentFilter);
    await download(`/api/jobs/${jobId}/results/export?${params}`);
  });

  bindBtn('btn-export-json', async () => {
    const params = new URLSearchParams({ fmt: 'json', group: _currentGroup });
    if (_currentFilter) params.set('filter', _currentFilter);
    await download(`/api/jobs/${jobId}/results/export?${params}`);
  });
}

function setTextContent(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? '-';
}

function toggleDisplay(id, show) {
  const el = document.getElementById(id);
  if (el) el.style.display = show ? '' : 'none';
}

function bindBtn(id, handler) {
  const btn = document.getElementById(id);
  if (!btn) return;
  btn.addEventListener('click', async () => {
    btn.classList.add('loading');
    btn.disabled = true;
    try {
      await handler();
    } catch (err) {
      toast.error(err.message || '操作失敗，請稍後再試。');
    } finally {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  });
}
