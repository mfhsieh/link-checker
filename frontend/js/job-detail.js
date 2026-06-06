/**
 * job-detail.js — 任務詳情頁面邏輯（ESM）
 *
 * 功能：
 * - 任務詳情（狀態、進度條、統計摘要）
 * - 3 秒輪詢進度（任務執行中時）
 * - 啟動 / 暫停 / 恢復 / 重置 / 刪除
 * - 外連結果查閱（篩選、搜尋、分頁）
 * - CSV / JSON 匯出下載
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

// ── 進度輪詢 ──────────────────────────────────────────────────

function startPolling(jobId) {
  stopPolling();
  _pollTimer = setInterval(() => refreshJobDetail(jobId), 3000);
}

function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

// ── 主初始化 ──────────────────────────────────────────────────

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

// ── 渲染任務資訊 ───────────────────────────────────────────────

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

  // 進度條
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

  // 控制按鈕顯示邏輯
  const canStart = ['pending', 'paused'].includes(job.status);
  const canPause = job.status === 'running';
  const canReset = ['completed', 'error', 'paused'].includes(job.status);

  toggleDisplay('btn-start-job', canStart);
  toggleDisplay('btn-resume-job', false);  // 合併到 start
  toggleDisplay('btn-pause-job', canPause);
  toggleDisplay('btn-reset-job', canReset);
}

// ── 控制按鈕 ──────────────────────────────────────────────────

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

// ── 外連結果 ──────────────────────────────────────────────────

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

  container.innerHTML = '<div class="skeleton" style="height:200px;border-radius:0.5rem"></div>';

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
    container.innerHTML = `<div class="empty-state"><div class="empty-state-desc text-danger">${escapeHtml(err.message)}</div></div>`;
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
  if (items.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-title">無結果</div>
        <div class="empty-state-desc">目前沒有符合條件的外連結果</div>
      </div>
    `;
    return;
  }

  const isGrouped = _currentGroup;

  const headers = isGrouped
    ? ['目標 URL', 'IP 位址', '安全', 'HTTP 狀態', '來源數', '錯誤訊息']
    : ['來源頁面', '目標 URL', 'IP 位址', '安全', 'HTTP 狀態', '錯誤訊息'];

  const rows = items.map(item => {
    const isSecure = item.is_secure;
    const status = item.http_status_code;
    const statusClass = !status ? 'text-muted' : (status >= 400 ? 'text-danger' : 'text-success');

    if (isGrouped) {
      return `<tr>
        <td class="truncate" style="max-width:260px" title="${escapeHtml(item.target_url)}">${escapeHtml(item.target_url)}</td>
        <td class="font-mono text-xs">${escapeHtml(item.ip_address || '-')}</td>
        <td>${isSecure ? '<span class="text-success">✓</span>' : '<span class="text-danger">✗</span>'}</td>
        <td class="${statusClass}">${status ?? '-'}</td>
        <td>${item.occurrence_count ?? '-'}</td>
        <td class="text-xs text-muted truncate" style="max-width:180px">${escapeHtml(item.error_message || '-')}</td>
      </tr>`;
    } else {
      return `<tr>
        <td class="truncate text-xs text-muted" style="max-width:200px" title="${escapeHtml(item.source_url)}">${escapeHtml(item.source_url)}</td>
        <td class="truncate" style="max-width:260px" title="${escapeHtml(item.target_url)}">${escapeHtml(item.target_url)}</td>
        <td class="font-mono text-xs">${escapeHtml(item.ip_address || '-')}</td>
        <td>${isSecure ? '<span class="text-success">✓</span>' : '<span class="text-danger">✗</span>'}</td>
        <td class="${statusClass}">${status ?? '-'}</td>
        <td class="text-xs text-muted truncate" style="max-width:160px">${escapeHtml(item.error_message || '-')}</td>
      </tr>`;
    }
  }).join('');

  container.innerHTML = `
    <div class="table-wrapper">
      <table class="table">
        <thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div id="results-pagination"></div>
  `;
}

function renderPagination(res, jobId) {
  const paginationEl = document.getElementById('results-pagination');
  if (!paginationEl) return;

  const { page, total_pages } = res;
  if (total_pages <= 1) { paginationEl.innerHTML = ''; return; }

  const pages = [];
  const delta = 2;
  for (let i = Math.max(1, page - delta); i <= Math.min(total_pages, page + delta); i++) {
    pages.push(i);
  }

  paginationEl.innerHTML = `
    <div class="pagination">
      <button class="page-btn" ${page <= 1 ? 'disabled' : ''} data-page="${page - 1}">‹</button>
      ${pages.map(p => `<button class="page-btn ${p === page ? 'active' : ''}" data-page="${p}">${p}</button>`).join('')}
      <button class="page-btn" ${page >= total_pages ? 'disabled' : ''} data-page="${page + 1}">›</button>
    </div>
  `;

  paginationEl.querySelectorAll('.page-btn:not([disabled])').forEach(btn => {
    btn.addEventListener('click', async () => {
      _currentPage = parseInt(btn.dataset.page);
      await loadResultsPage(jobId);
    });
  });
}

function bindResultsControls(jobId) {
  // 篩選 Chips
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

  // 搜尋
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

  // 去重聚合切換
  const groupToggle = document.getElementById('results-group-toggle');
  if (groupToggle) {
    groupToggle.addEventListener('change', async () => {
      _currentGroup = groupToggle.checked;
      _currentPage = 1;
      await loadResultsPage(jobId);
    });
  }

  // 匯出按鈕
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

// ── 工具函式 ───────────────────────────────────────────────────

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

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = String(str || '');
  return div.innerHTML;
}
