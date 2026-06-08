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
let _currentJobConfig = null;
let _currentFilter = null;
let _currentSearch = '';
let _currentExclude = '';
let _currentGroupBy = 'none';
let _currentPage = 1;
let _eventsBound = false;
let _pollInterval = 5000;

function startPolling(jobId) {
  if (_pollTimer) return;
  _pollTimer = setInterval(() => refreshJobDetail(jobId), _pollInterval);
}

function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

function showConfirm(title, message, confirmText = '確定', isDanger = false) {
  return new Promise((resolve) => {
    const modal = document.getElementById('confirm-modal');
    const titleEl = document.getElementById('confirm-modal-title');
    const messageEl = document.getElementById('confirm-modal-message');
    const submitBtn = document.getElementById('confirm-modal-submit');
    const cancelBtn = document.getElementById('confirm-modal-cancel');
    const closeBtn = document.getElementById('confirm-modal-close');

    titleEl.textContent = title;
    messageEl.textContent = message;
    submitBtn.textContent = confirmText;
    submitBtn.className = isDanger ? 'btn btn-danger' : 'btn btn-primary';

    const cleanup = () => {
      submitBtn.removeEventListener('click', onConfirm);
      cancelBtn.removeEventListener('click', onCancel);
      closeBtn.removeEventListener('click', onCancel);
      modal.style.display = 'none';
    };

    const onConfirm = () => { cleanup(); resolve(true); };
    const onCancel = () => { cleanup(); resolve(false); };

    submitBtn.addEventListener('click', onConfirm);
    cancelBtn.addEventListener('click', onCancel);
    closeBtn.addEventListener('click', onCancel);

    modal.style.display = 'flex';
  });
}

export async function initJobDetailPage(jobId) {
  _currentJobId = jobId;
  _currentFilter = null;
  _currentSearch = '';

  // 初始化時載入儲存在 localStorage 的排除清單
  _currentExclude = localStorage.getItem('ext-link-checker-exclude-domains') || '';

  _currentGroupBy = 'none';
  _currentPage = 1;

  // 清除舊的 UI 狀態 (如搜尋框、過濾器狀態)
  document.querySelectorAll('.filter-chip[data-filter]').forEach(c => c.classList.remove('active'));
  const searchInput = document.getElementById('results-search');
  if (searchInput) searchInput.value = '';
  const groupSelect = document.getElementById('results-group-select');
  if (groupSelect) groupSelect.value = 'none';

  // 依照是否有排除設定來改變按鈕的視覺呈現
  const btnOpenExclude = document.getElementById('btn-open-exclude-modal');
  if (btnOpenExclude) {
    btnOpenExclude.style.color = _currentExclude ? 'var(--color-brand-500)' : '';
    btnOpenExclude.style.borderColor = _currentExclude ? 'var(--color-brand-500)' : '';
    btnOpenExclude.style.background = _currentExclude ? 'hsla(221, 83%, 53%, 0.1)' : '';
  }

  if (!_eventsBound) {
    bindControlButtons();
    bindResultsControls();
    _eventsBound = true;
  }

  await refreshJobDetail(jobId);
  await loadResults(jobId);
}

export function destroyJobDetailPage() {
  stopPolling();
}

async function refreshJobDetail(jobId) {
  try {
    const job = await api.get(`/api/jobs/${jobId}`);

    // 動態更新輪詢間隔 (如果環境變數有變化)
    if (job.ui_poll_interval && _pollInterval !== job.ui_poll_interval) {
      _pollInterval = job.ui_poll_interval;
      if (_pollTimer) stopPolling(); // 先停止，讓下方邏輯用新間隔重啟
    }

    renderJobInfo(job);

    const isActuallyRunning = job.status === 'running' || job.is_running;
    if (isActuallyRunning) {
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

  const isPausing = job.status === 'paused' && job.is_running;
  const isActuallyRunning = job.status === 'running' || job.is_running;

  _currentJobConfig = job.config;

  const statusEl = el('job-status');
  if (statusEl) {
    let displayStatus = job.status;
    if (isPausing) displayStatus = 'paused';
    else if (isActuallyRunning) displayStatus = 'running';

    statusEl.className = `badge badge-${displayStatus}`;
    statusEl.textContent = isPausing ? '暫停中...' : (STATUS_LABELS[displayStatus] || displayStatus);
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
  setTextContent('stat-skipped', progress.skipped || 0);
  setTextContent('stat-failed', progress.failed || 0);

  const canStart = ['pending', 'paused'].includes(job.status) && !job.is_running;
  const canPause = isActuallyRunning && !isPausing;
  const canReset = ['completed', 'error', 'paused'].includes(job.status) && !job.is_running;

  toggleDisplay('btn-start-job', canStart);
  toggleDisplay('btn-resume-job', false);
  toggleDisplay('btn-pause-job', canPause);
  toggleDisplay('btn-reset-job', canReset);
}

function bindControlButtons() {
  bindBtn('btn-start-job', async () => {
    const confirmed = await showConfirm('啟動任務', '確定要開始執行此爬蟲任務嗎？', '啟動');
    if (!confirmed) return;
    await api.post(`/api/jobs/${_currentJobId}/start`);
    toast.success('任務已啟動！');
    await refreshJobDetail(_currentJobId);
  });

  bindBtn('btn-pause-job', async () => {
    const confirmed = await showConfirm('暫停任務', '確定要暫停此爬蟲任務嗎？任務將在完成當前頁面後停止。', '暫停');
    if (!confirmed) return;
    await api.post(`/api/jobs/${_currentJobId}/pause`);
    toast.info('暫停指令已送出，任務將在完成當前頁面後停止。');
    await refreshJobDetail(_currentJobId);
  });

  bindBtn('btn-reset-job', async () => {
    const confirmed = await showConfirm('⚠️ 重置任務', '確定要重置任務嗎？這將清除所有外連結果並重新開始。', '重置', true);
    if (!confirmed) return;
    await api.post(`/api/jobs/${_currentJobId}/reset`);
    toast.success('任務已重置。');
    await refreshJobDetail(_currentJobId);
    await loadResults(_currentJobId);
  });

  bindBtn('btn-delete-job', async () => {
    const confirmed = await showConfirm('🚨 刪除任務', '確定要刪除此任務嗎？此操作無法復原。', '永久刪除', true);
    if (!confirmed) return;
    await api.del(`/api/jobs/${_currentJobId}`);
    toast.success('任務已刪除。');
    window.location.hash = '#/jobs';
  });

  bindBtn('btn-back-jobs', () => {
    window.location.hash = '#/jobs';
  });

  bindBtn('btn-export-full', async () => {
    await download(`/api/jobs/${_currentJobId}/export/full`);
  });

  const btnViewConfig = document.getElementById('btn-view-job-config');
  const modalConfig = document.getElementById('job-config-modal');
  if (btnViewConfig && modalConfig) {
    btnViewConfig.addEventListener('click', () => {
      const container = document.getElementById('job-config-display-container');
      if (container) {
        if (!_currentJobConfig) {
          container.innerHTML = '<div class="text-muted" style="text-align:center;padding:2rem">無設定資料</div>';
        } else {
          const c = _currentJobConfig;
          const esc = (s) => {
            const d = document.createElement('div');
            d.textContent = String(s || '');
            return d.innerHTML;
          };
          const formatList = (list) => {
            if (!Array.isArray(list) || list.length === 0) return '<span class="text-muted">-</span>';
            return list.map(item => `<span style="display:inline-block; background:var(--surface-overlay); border:1px solid var(--surface-border); border-radius:4px; padding:2px 6px; margin:2px 2px 2px 0; font-size:0.75rem;">${esc(item)}</span>`).join('');
          };

          container.innerHTML = `
            <div style="display:flex; flex-direction:column; gap:1.5rem;">
              <div>
                <div style="font-weight:600; border-bottom:1px solid var(--surface-border); padding-bottom:0.5rem; margin-bottom:0.75rem;">🌐 網域設定</div>
                <div style="display:grid; grid-template-columns: 110px 1fr; gap:0.75rem 0.5rem; font-size:0.875rem;">
                  <div class="text-muted">目標網域</div><div>${formatList(c.target_domains)}</div>
                  <div class="text-muted">內部網域</div><div>${formatList(c.internal_domains)}</div>
                </div>
              </div>
              <div>
                <div style="font-weight:600; border-bottom:1px solid var(--surface-border); padding-bottom:0.5rem; margin-bottom:0.75rem;">⚙️ 資源與限制</div>
                <div style="display:grid; grid-template-columns: 110px 1fr; gap:0.75rem 0.5rem; font-size:0.875rem;">
                  <div class="text-muted">最大爬取深度</div><div>${c.max_depth === null ? '不限制' : esc(c.max_depth)}</div>
                  <div class="text-muted">最大抓取頁數</div><div>${c.max_pages === null ? '不限制' : esc(c.max_pages)}</div>
                  <div class="text-muted">請求延遲</div><div>${c.delay ?? '-'} 秒</div>
                  <div class="text-muted">連線逾時</div><div>${c.timeout ?? '-'} 秒</div>
                  <div class="text-muted">失敗重試</div><div>${c.retries ?? '-'} 次</div>
                  ${c.proxy_url !== undefined ? `<div class="text-muted">代理伺服器</div><div class="font-mono text-xs" style="word-break:break-all">${esc(c.proxy_url) || '-'}</div>` : ''}
                </div>
              </div>
              <div>
                <div style="font-weight:600; border-bottom:1px solid var(--surface-border); padding-bottom:0.5rem; margin-bottom:0.75rem;">🛡️ 過濾與排除</div>
                <div style="display:grid; grid-template-columns: 110px 1fr; gap:0.75rem 0.5rem; font-size:0.875rem;">
                  <div class="text-muted">忽略路徑規則</div><div>${formatList(c.ignore_regexes)}</div>
                  <div class="text-muted">忽略副檔名</div>
                  <div style="max-height:160px; overflow-y:auto; padding-right:4px;">
                    ${formatList(c.ignore_extensions)}
                  </div>
                </div>
              </div>
            </div>
          `;
        }
      }
      modalConfig.style.display = 'flex';
    });
    document.getElementById('job-config-close')?.addEventListener('click', () => modalConfig.style.display = 'none');
    document.getElementById('job-config-ok')?.addEventListener('click', () => modalConfig.style.display = 'none');
  }
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
      exclude: _currentExclude || undefined,
      group_by: _currentGroupBy,
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
  setTextContent('summary-healthy', summary.healthy_count ?? 0);
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

  const isGroupTarget = _currentGroupBy === 'target';
  const isGroupSource = _currentGroupBy === 'source';
  const isGroupDomain = _currentGroupBy === 'domain';
  let headers;

  if (isGroupTarget) {
    headers = ['目標 URL', 'IP 位址', '安全', 'HTTP 狀態', '來源數', '錯誤訊息'];
  } else if (isGroupSource) {
    headers = ['來源頁面', '外連數量', '詳細連結清單'];
  } else if (isGroupDomain) {
    headers = ['外部網域', '總出現次數', '不重複網址數', '包含網址清單'];
  } else {
    headers = ['來源頁面', '目標 URL', 'IP 位址', '安全', 'HTTP 狀態', '錯誤訊息'];
  }

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
    if (isGroupDomain) {
      const tr = document.createElement('tr');

      const tdDomain = document.createElement('td');
      tdDomain.className = 'font-mono font-medium';
      tdDomain.textContent = item.domain;
      tr.appendChild(tdDomain);

      const tdOcc = document.createElement('td');
      tdOcc.style.fontWeight = '600';
      tdOcc.style.fontFeatureSettings = '"tnum"';
      tdOcc.textContent = item.occurrence_count;
      tr.appendChild(tdOcc);

      const tdUnique = document.createElement('td');
      tdUnique.textContent = item.unique_urls_count;
      tr.appendChild(tdUnique);

      const tdUrls = document.createElement('td');
      const divUrls = document.createElement('div');
      divUrls.style.maxHeight = '150px';
      divUrls.style.overflowY = 'auto';
      divUrls.style.paddingRight = '4px';
      const ul = document.createElement('ul');
      ul.style.margin = '0';
      ul.style.paddingLeft = '0';
      ul.style.listStyle = 'none';
      ul.style.fontSize = '0.8125rem';
      item.unique_urls.forEach(u => {
        const li = document.createElement('li');
        li.className = 'truncate';
        li.style.maxWidth = '360px';
        li.style.marginBottom = '0.25rem';
        li.title = u;
        li.textContent = u;
        ul.appendChild(li);
      });
      divUrls.appendChild(ul);
      tdUrls.appendChild(divUrls);
      tr.appendChild(tdUrls);

      tbody.appendChild(tr);
      return;
    }

    if (isGroupSource) {
      const tr = document.createElement('tr');

      const tdSource = document.createElement('td');
      tdSource.className = 'truncate';
      tdSource.style.maxWidth = '300px';
      tdSource.title = item.source_url;
      tdSource.innerHTML = `<a href="${escapeHtml(item.source_url)}" target="_blank" class="text-link">${escapeHtml(item.source_url)}</a>`;
      tr.appendChild(tdSource);

      const tdCount = document.createElement('td');
      tdCount.innerHTML = `<span class="badge badge-danger">${item.occurrence_count}</span>`;
      tr.appendChild(tdCount);

      const tdTargets = document.createElement('td');
      const divTargets = document.createElement('div');
      divTargets.style.maxHeight = '150px';
      divTargets.style.overflowY = 'auto';
      divTargets.style.paddingRight = '4px';
      const ul = document.createElement('ul');
      ul.style.margin = '0';
      ul.style.paddingLeft = '0';
      ul.style.listStyle = 'none';
      ul.style.fontSize = '0.8125rem';
      item.targets.forEach(t => {
        const li = document.createElement('li');
        li.style.marginBottom = '0.375rem';

        let badgeClass = 'badge-pending';
        if (t.status.includes('404') || t.status.includes('500') || t.status === 'Error' || t.status === 'DNS Failed') badgeClass = 'badge-danger';

        const badge = `<span class="badge ${badgeClass}" style="padding:0.125rem 0.375rem; font-size:0.7rem; margin-right:0.5rem; display:inline-block; min-width:3.5rem; text-align:center">${escapeHtml(t.status)}</span>`;
        const secBadge = t.is_secure ? '' : `<span class="text-danger" style="margin-right:0.25rem" title="非 HTTPS">🔓</span>`;

        li.innerHTML = `${badge}${secBadge}<span class="truncate" style="display:inline-block; max-width:400px; vertical-align:bottom" title="${escapeHtml(t.url)}">${escapeHtml(t.url)}</span>`;
        ul.appendChild(li);
      });
      divTargets.appendChild(ul);
      tdTargets.appendChild(divTargets);
      tr.appendChild(tdTargets);

      tbody.appendChild(tr);
      return;
    }

    const isSecure = item.is_secure;
    const status = item.http_status_code;
    const statusClass = !status ? 'text-muted' : (status >= 400 ? 'text-danger' : 'text-success');

    const tr = document.createElement('tr');

    if (!isGroupTarget) {
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

    if (isGroupTarget) {
      const tdOcc = document.createElement('td');
      tdOcc.textContent = item.occurrence_count ?? '-';
      tr.appendChild(tdOcc);
    }

    const tdError = document.createElement('td');
    tdError.className = 'text-xs text-muted truncate';
    tdError.style.maxWidth = isGroupTarget ? '180px' : '160px';
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

function bindResultsControls() {
  document.querySelectorAll('.filter-chip[data-filter]').forEach(chip => {
    chip.addEventListener('click', async () => {
      const filter = chip.dataset.filter || null;
      _currentFilter = _currentFilter === filter ? null : filter;
      _currentPage = 1;
      document.querySelectorAll('.filter-chip[data-filter]').forEach(c => {
        c.classList.toggle('active', c.dataset.filter === _currentFilter);
      });
      await loadResultsPage(_currentJobId);
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
        await loadResultsPage(_currentJobId);
      }, 400);
    });
  }

  // ── 綁定排除網域 Modal 邏輯 ──────────────────────────────────────────
  const btnOpenExclude = document.getElementById('btn-open-exclude-modal');
  const excludeModal = document.getElementById('exclude-domains-modal');
  const excludeTextarea = document.getElementById('exclude-domains-textarea');
  const excludeSubmit = document.getElementById('exclude-domains-submit');
  const excludeClose = document.getElementById('exclude-domains-close');
  const excludeCancel = document.getElementById('exclude-domains-cancel');

  if (btnOpenExclude && excludeModal) {
    const closeExcludeModal = () => { excludeModal.style.display = 'none'; };

    btnOpenExclude.addEventListener('click', () => {
      excludeTextarea.value = _currentExclude.split(',').filter(Boolean).join('\n');
      excludeModal.style.display = 'flex';
      setTimeout(() => excludeTextarea.focus(), 50);
    });

    excludeClose.addEventListener('click', closeExcludeModal);
    excludeCancel.addEventListener('click', closeExcludeModal);

    excludeSubmit.addEventListener('click', async () => {
      const lines = excludeTextarea.value.split('\n').map(s => s.trim()).filter(Boolean);
      _currentExclude = lines.join(',');
      localStorage.setItem('ext-link-checker-exclude-domains', _currentExclude);

      btnOpenExclude.style.color = _currentExclude ? 'var(--color-brand-500)' : '';
      btnOpenExclude.style.borderColor = _currentExclude ? 'var(--color-brand-500)' : '';
      btnOpenExclude.style.background = _currentExclude ? 'hsla(221, 83%, 53%, 0.1)' : '';

      closeExcludeModal();
      _currentPage = 1;
      await loadResultsPage(_currentJobId);
    });
  }

  const groupSelect = document.getElementById('results-group-select');
  if (groupSelect) {
    groupSelect.addEventListener('change', async () => {
      _currentGroupBy = groupSelect.value;
      _currentPage = 1;
      await loadResultsPage(_currentJobId);
    });
  }

  bindBtn('btn-export-csv', async () => {
    const params = new URLSearchParams({ fmt: 'csv', group_by: _currentGroupBy });
    if (_currentFilter) params.set('filter', _currentFilter);
    if (_currentExclude) params.set('exclude', _currentExclude);
    await download(`/api/jobs/${_currentJobId}/results/export?${params}`);
  });

  bindBtn('btn-export-json', async () => {
    const params = new URLSearchParams({ fmt: 'json', group_by: _currentGroupBy });
    if (_currentFilter) params.set('filter', _currentFilter);
    if (_currentExclude) params.set('exclude', _currentExclude);
    await download(`/api/jobs/${_currentJobId}/results/export?${params}`);
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

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = String(s || '');
  return d.innerHTML;
}
