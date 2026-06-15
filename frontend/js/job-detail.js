/**
 * job-detail.js — 任務詳情頁面邏輯（ESM）
 */

import * as api from './api.js';
import { download } from './api.js';
import { toast } from './toast.js';



let _pollTimer = null;
let _currentJobId = null;
let _currentJobConfig = null;
let _currentFilter = null;
let _currentExclude = '';
let _currentExcludeEnabled = true;
let _currentGroupBy = 'none';
let _currentPage = 1;
let _eventsBound = false;
let _pollInterval = 5000;
let _currentTab = 'external';
let _internalCurrentPage = 1;
let _internalFilter = null;
let _internalGroupBy = 'none';
let _internalResultItems = [];
let _detailSort = { key: null, asc: true };
let _detailColFilters = {};
let _internalSort = { key: null, asc: true };
let _internalColFilters = {};
let _currentDetailHeaders = [];
let _currentResultItems = [];

function startPolling(jobId) {
    if (_pollTimer) clearTimeout(_pollTimer);
    // 使用 setTimeout 取代 setInterval，配合執行完畢後再次呼叫，避免非同步請求堆疊
    _pollTimer = setTimeout(() => refreshJobDetail(jobId), _pollInterval);
}

function stopPolling() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }
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

/**
 * 初始化任務詳情頁面邏輯
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>} 無回傳值
 */
export async function initJobDetailPage(jobId) {
    _currentJobId = jobId;
    _currentFilter = null;

    _currentTab = 'external';
    _internalCurrentPage = 1;
    _internalGroupBy = 'none';
    _internalFilter = null;
    // 初始化時載入儲存在 localStorage 的排除清單
    _currentExclude = localStorage.getItem('ext-link-checker-exclude-domains') || '';
    _currentExcludeEnabled = localStorage.getItem('ext-link-checker-exclude-enabled') !== 'false';

    _currentGroupBy = 'none';
    _currentPage = 1;
    _detailSort = { key: null, asc: true };
    _detailColFilters = {};
    _internalSort = { key: null, asc: true };
    _internalColFilters = {};

    // 清除舊的 UI 狀態 (如搜尋框、過濾器狀態)
    document.querySelectorAll('#tab-content-internal .filter-card[data-filter]').forEach(c => {
        const isActive = c.dataset.filter === 'all';
        c.classList.toggle('active', isActive);
        if (isActive) {
            const descBox = document.getElementById('int-filter-desc');
            if (descBox) {
                descBox.style.borderLeftColor = c.dataset.color || 'var(--color-brand-400)';
                const span = descBox.querySelector('span');
                if (span) span.textContent = c.dataset.desc;
            }
        }
    });
    document.querySelectorAll('#tab-content-external .filter-card[data-filter]').forEach(c => {
        const isActive = c.dataset.filter === 'all';
        c.classList.toggle('active', isActive);
        if (isActive) {
            const descBox = document.getElementById('ext-filter-desc');
            if (descBox) {
                descBox.style.borderLeftColor = c.dataset.color || 'var(--color-brand-400)';
                const span = descBox.querySelector('span');
                if (span) span.textContent = c.dataset.desc;
            }
        }
    });
    const groupSelectEl = document.getElementById('results-group-select');
    if (groupSelectEl) groupSelectEl.value = 'none';

    const internalGroupSelectEl = document.getElementById('internal-results-group-select');
    if (internalGroupSelectEl) internalGroupSelectEl.value = 'none';

    // 重置 Tab UI 狀態
    document.querySelectorAll('#job-detail-tabs .tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === 'external');
    });
    document.getElementById('tab-content-external').style.display = 'block';
    document.getElementById('tab-content-internal').style.display = 'none';

    // 依照是否有排除設定來改變按鈕的視覺呈現
    const openExcludeBtn = document.getElementById('btn-open-exclude-modal');
    if (openExcludeBtn) {
        const isActive = _currentExcludeEnabled && _currentExclude;
        openExcludeBtn.style.color = isActive ? 'var(--color-brand-500)' : '';
        openExcludeBtn.style.borderColor = isActive ? 'var(--color-brand-500)' : '';
        openExcludeBtn.style.background = isActive ? 'hsla(221, 83%, 53%, 0.1)' : '';
    }

    if (!_eventsBound) {
        bindControlButtons();
        bindResultsControls();
        _eventsBound = true;
    }

    await refreshJobDetail(jobId);
    await loadResults(jobId);
}

/**
 * 銷毀任務詳情頁面邏輯，停止輪詢
 * @returns {void} 無回傳值
 */
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

        const isActuallyRunning = ['running', 'starting'].includes(job.status) || job.is_running;
        if (isActuallyRunning) {
            startPolling(jobId);
        } else {
            stopPolling();
        }
    } catch (err) {
        toast.error('無法取得任務資訊：' + err.message);
        // 即使發生網路連線錯誤，仍持續輪詢，避免單次斷線導致畫面永久卡死
        if (err.status !== 404 && err.status !== 401 && err.status !== 403) {
            if (_currentJobId) {
                startPolling(_currentJobId);
            }
        } else {
            stopPolling();
        }
    }
}

async function loadInternalResultsPage(jobId) {
    const containerEl = document.getElementById('internal-results-container');
    if (!containerEl) return;

    let tableEl = containerEl.querySelector('.table');
    if (!tableEl || containerEl.dataset.renderedInternalGroup !== _internalGroupBy) {
        containerEl.replaceChildren();
        const skeletonEl = document.createElement('div');
        skeletonEl.className = 'skeleton';
        skeletonEl.style.height = '200px';
        skeletonEl.style.borderRadius = '0.5rem';
        containerEl.appendChild(skeletonEl);
    } else {
        tableEl.style.opacity = '0.5';
    }

    try {
        const params = {};
        if (_internalGroupBy && _internalGroupBy !== 'none') {
            params.group_by = _internalGroupBy;
        }
        const summary = await api.get(`/api/jobs/${jobId}/internal-results/summary`, Object.keys(params).length > 0 ? params : undefined);
        renderInternalSummary(summary);
    } catch (_) { /* 忽略 */ }

    try {
        const params = { group_by: _internalGroupBy, page: _internalCurrentPage, page_size: 50, sort_by: _internalSort.key || undefined, sort_asc: _internalSort.asc };
        if (_internalFilter && _internalFilter !== 'all') params.filter = _internalFilter;
        const activeFilters = Object.fromEntries(Object.entries(_internalColFilters).filter(([_, v]) => v !== ''));
        if (Object.keys(activeFilters).length > 0) {
            params.col_filters = JSON.stringify(activeFilters);
        }
        const res = await api.get(`/api/jobs/${jobId}/internal-results`, params);
        if (tableEl) tableEl.style.opacity = '1';
        renderInternalResultsTable(res, containerEl);
        renderInternalPagination(res, jobId);
    } catch (err) {
        containerEl.replaceChildren();
        const emptyStateEl = document.createElement('div');
        emptyStateEl.className = 'empty-state';
        const descEl = document.createElement('div');
        descEl.className = 'empty-state-desc text-danger';
        descEl.textContent = err.message;
        emptyStateEl.appendChild(descEl);
        containerEl.appendChild(emptyStateEl);
    }
}

function renderInternalSummary(summary) {
    setTextContent('int-summary-total', summary.total ?? 0);
    setTextContent('int-summary-server-error', summary.server_error ?? 0);
    setTextContent('int-summary-connection-error', summary.connection_error ?? 0);
    setTextContent('int-summary-timeout', summary.timeout ?? 0);
    setTextContent('int-summary-not-found', summary.not_found ?? 0);
    setTextContent('int-summary-other-error', summary.other_error ?? 0);
    setTextContent('int-summary-access-denied', summary.access_denied ?? 0);
}

function renderInternalResultsTable(res, containerEl) {
    _internalResultItems = res.items || [];

    if (_internalResultItems.length === 0) {
        containerEl.replaceChildren();
        const emptyStateEl = document.createElement('div');
        emptyStateEl.className = 'empty-state';
        const titleEl = document.createElement('div');
        titleEl.className = 'empty-state-title';
        titleEl.textContent = '太棒了！';
        const descEl = document.createElement('div');
        descEl.className = 'empty-state-desc';
        descEl.textContent = '您的網站內部沒有這類錯誤。';
        emptyStateEl.appendChild(titleEl);
        emptyStateEl.appendChild(descEl);
        containerEl.appendChild(emptyStateEl);
        return;
    }

    let headers = [];
    const isInternalGroupSource = _internalGroupBy === 'source';

    if (isInternalGroupSource) {
        headers = [
            { label: '來源頁面 (Source)', key: 'source_url' },
            { label: '失效數量', key: 'occurrence_count' },
            { label: '目標 URL', key: 'targets', sortable: false, filterable: false }
        ];
    } else {
        headers = [
            { label: '來源頁面 (Source)', key: 'Source URL' },
            { label: '目標 URL', key: 'URL' },
            { label: 'HTTP 狀態', key: 'HTTP Status Code' },
            { label: '錯誤訊息', key: 'Error Message' }
        ];
    }

    let tableEl = containerEl.querySelector('.table');
    if (!tableEl || containerEl.dataset.renderedInternalGroup !== _internalGroupBy) {
        containerEl.replaceChildren();
        const wrapper = document.createElement('div');
        wrapper.className = 'table-wrapper';
        tableEl = document.createElement('table');
        tableEl.className = 'table';
        const thead = document.createElement('thead');
        const trHead = document.createElement('tr');

        headers.forEach(h => {
            const th = document.createElement('th');
            th.style.verticalAlign = 'top';
            const headerTop = document.createElement('div');
            headerTop.style.display = 'flex';
            headerTop.style.justifyContent = 'space-between';
            headerTop.style.alignItems = 'center';
            if (h.sortable !== false) headerTop.style.cursor = 'pointer';

            const label = document.createElement('span');
            label.textContent = h.label;
            headerTop.appendChild(label);

            if (h.sortable !== false) {
                const sortIcon = document.createElement('span');
                sortIcon.className = 'sort-icon';
                sortIcon.dataset.key = h.key;
                sortIcon.style.color = 'var(--text-muted)';
                sortIcon.style.fontSize = '0.75rem';
                sortIcon.style.marginLeft = '0.25rem';
                sortIcon.textContent = _internalSort.key === h.key ? (_internalSort.asc ? '▲' : '▼') : '⇅';
                if (_internalSort.key === h.key) sortIcon.style.color = 'var(--color-brand-500)';
                headerTop.appendChild(sortIcon);

                headerTop.addEventListener('click', () => {
                    if (_internalSort.key === h.key) _internalSort.asc = !_internalSort.asc;
                    else { _internalSort.key = h.key; _internalSort.asc = true; }

                    api.updateSortIcons(trHead, _internalSort.key, _internalSort.asc);
                    _internalCurrentPage = 1;
                    loadInternalResultsPage(_currentJobId);
                });
            }
            th.appendChild(headerTop);

            if (h.filterable !== false) {
                const filterInput = api.createFilterInput(_internalColFilters[h.key], (newVal) => {
                    _internalColFilters[h.key] = newVal;
                    _internalCurrentPage = 1;
                    if (window._internalFilterTimeout) clearTimeout(window._internalFilterTimeout);
                    window._internalFilterTimeout = setTimeout(() => {
                        loadInternalResultsPage(_currentJobId);
                    }, 500);
                });
                th.appendChild(filterInput);
            }
            trHead.appendChild(th);
        });
        thead.appendChild(trHead);
        tableEl.appendChild(thead);
        tableEl.appendChild(document.createElement('tbody'));
        wrapper.appendChild(tableEl);
        containerEl.appendChild(wrapper);
        containerEl.dataset.renderedInternalGroup = _internalGroupBy;

        const paginationContainerEl = document.createElement('div');
        paginationContainerEl.id = 'internal-results-pagination';
        containerEl.appendChild(paginationContainerEl);
    }

    renderInternalTbody(tableEl);
}

function getInternalStatusColorClass(code, errMsg) {
    if (!code || code === '-' || code === 'Error' || code === 'DNS Failed') {
        const msg = String(errMsg || '').toLowerCase();
        if (msg.includes('timeout') || msg.includes('timed out')) return 'text-info';
        return 'text-brand';
    }
    const c = parseInt(code, 10);
    if (c === 401 || c === 403) return 'text-muted';
    if (c === 404 || c === 410) return 'text-warning';
    if (c >= 500) return 'text-danger';
    return 'text-secondary';
}

function getInternalBadgeClass(code, errMsg) {
    if (!code || code === '-' || code === 'Error' || code === 'DNS Failed') {
        const msg = String(errMsg || '').toLowerCase();
        if (msg.includes('timeout') || msg.includes('timed out')) return 'badge-info';
        return 'badge-admin';
    }
    const c = parseInt(code, 10);
    if (c === 401 || c === 403) return 'badge-pending';
    if (c === 404 || c === 410) return 'badge-warning';
    if (c >= 500) return 'badge-danger';
    return 'badge-secondary';
}

function renderInternalTbody(tableEl) {
    let data = [..._internalResultItems];

    let tbody = tableEl.querySelector('tbody');
    tbody.replaceChildren();

    data.forEach(item => {
        const tr = document.createElement('tr');

        if (_internalGroupBy === 'source') {
            const tdSource = document.createElement('td');
            tdSource.className = 'truncate';
            tdSource.style.maxWidth = '260px';
            tdSource.title = item.source_url || '-';
            if (item.source_url) {
                const aSource = document.createElement('a');
                aSource.href = item.source_url;
                aSource.target = '_blank';
                aSource.rel = 'noopener noreferrer';
                aSource.className = 'text-brand';
                aSource.textContent = item.source_url;
                tdSource.appendChild(aSource);
            } else {
                tdSource.textContent = '-';
            }
            tr.appendChild(tdSource);

            const tdCount = document.createElement('td');
            tdCount.style.fontWeight = '600';
            tdCount.style.fontFeatureSettings = '"tnum"';
            tdCount.textContent = item.occurrence_count;
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

                const badgeClass = 'badge-danger';
                const badge = document.createElement('span');
                badge.className = `badge ${badgeClass}`;
                badge.style.padding = '0.125rem 0.375rem';
                badge.style.fontSize = '0.7rem';
                badge.style.marginRight = '0.5rem';
                badge.style.display = 'inline-block';
                badge.style.minWidth = '3.5rem';
                badge.style.textAlign = 'center';
                badge.textContent = t.status || 'Error';
                li.appendChild(badge);

                const spanTargetWrapper = document.createElement('span');
                spanTargetWrapper.className = 'truncate text-muted';
                spanTargetWrapper.style.display = 'inline-block';
                spanTargetWrapper.style.maxWidth = '400px';
                spanTargetWrapper.style.verticalAlign = 'bottom';
                spanTargetWrapper.title = t.url;

                const aTarget = document.createElement('a');
                aTarget.href = t.url;
                aTarget.target = '_blank';
                aTarget.rel = 'noopener noreferrer';
                aTarget.style.color = 'inherit';
                aTarget.textContent = t.url;

                spanTargetWrapper.appendChild(aTarget);
                li.appendChild(spanTargetWrapper);

                if (t.error_message) {
                    const errSpan = document.createElement('span');
                    errSpan.className = 'text-xs text-muted';
                    errSpan.style.display = 'block';
                    errSpan.style.marginTop = '0.125rem';
                    errSpan.style.marginLeft = '4.25rem';
                    errSpan.textContent = t.error_message;
                    li.appendChild(errSpan);
                }

                ul.appendChild(li);
            });
            if (item.targets.length >= 10) {
                const truncLi = document.createElement('li');
                truncLi.className = 'text-xs text-muted';
                truncLi.style.marginTop = '0.25rem';
                truncLi.textContent = '... (為確保效能已截斷，請匯出 CSV 檢視完整清單)';
                ul.appendChild(truncLi);
            }
            divTargets.appendChild(ul);
            tdTargets.appendChild(divTargets);
            tr.appendChild(tdTargets);
        } else {
            const tdSource = document.createElement('td');
            tdSource.className = 'truncate';
            tdSource.style.maxWidth = '260px';
            tdSource.title = item['Source URL'] || '-';
            if (item['Source URL']) {
                const aSource = document.createElement('a');
                aSource.href = item['Source URL'];
                aSource.target = '_blank';
                aSource.rel = 'noopener noreferrer';
                aSource.className = 'text-brand';
                aSource.textContent = item['Source URL'];
                tdSource.appendChild(aSource);
            } else {
                tdSource.textContent = '-';
            }
            tr.appendChild(tdSource);

            const tdUrl = document.createElement('td');
            tdUrl.className = 'truncate';
            tdUrl.style.maxWidth = '260px';
            tdUrl.title = item.URL;
            const aUrl = document.createElement('a');
            aUrl.href = item.URL;
            aUrl.target = '_blank';
            aUrl.rel = 'noopener noreferrer';
            aUrl.className = 'text-brand';
            aUrl.textContent = item.URL;
            tdUrl.appendChild(aUrl);
            tr.appendChild(tdUrl);

            const tdStatus = document.createElement('td');
            tdStatus.className = getInternalStatusColorClass(item['HTTP Status Code'], item['Error Message']);
            tdStatus.style.fontWeight = '600';
            tdStatus.textContent = item['HTTP Status Code'] || '-';
            tr.appendChild(tdStatus);

            const tdError = document.createElement('td');
            tdError.className = 'text-xs text-muted truncate';
            tdError.style.maxWidth = '160px';
            tdError.title = item['Error Message'] || '-';
            tdError.textContent = item['Error Message'] || '-';
            tr.appendChild(tdError);
        }

        tbody.appendChild(tr);
    });
}

function renderInternalPagination(res, jobId) {
    const paginationEl = document.getElementById('internal-results-pagination');
    if (!paginationEl) return;

    paginationEl.replaceChildren();
    const { page, total_pages } = res;
    if (total_pages <= 1) return;

    const paginationDivEl = document.createElement('div');
    paginationDivEl.className = 'pagination';

    const firstBtn = document.createElement('button');
    firstBtn.className = 'page-btn';
    firstBtn.textContent = '«';
    firstBtn.title = '第一頁';
    if (page <= 1) firstBtn.disabled = true;
    else {
        firstBtn.addEventListener('click', async () => {
            _internalCurrentPage = 1;
            await loadInternalResultsPage(jobId);
        });
    }
    paginationDivEl.appendChild(firstBtn);

    const prevBtn = document.createElement('button');
    prevBtn.className = 'page-btn';
    prevBtn.textContent = '‹';
    if (page <= 1) prevBtn.disabled = true;
    else {
        prevBtn.addEventListener('click', async () => {
            _internalCurrentPage = page - 1;
            await loadInternalResultsPage(jobId);
        });
    }
    paginationDivEl.appendChild(prevBtn);

    const delta = 2;
    const start = Math.max(1, page - delta);
    const end = Math.min(total_pages, page + delta);

    for (let i = start; i <= end; i++) {
        const pageBtn = document.createElement('button');
        pageBtn.className = i === page ? 'page-btn active' : 'page-btn';
        pageBtn.textContent = i;
        if (i !== page) {
            pageBtn.addEventListener('click', async () => {
                _internalCurrentPage = i;
                await loadInternalResultsPage(jobId);
            });
        }
        paginationDivEl.appendChild(pageBtn);
    }

    const nextBtn = document.createElement('button');
    nextBtn.className = 'page-btn';
    nextBtn.textContent = '›';
    if (page >= total_pages) nextBtn.disabled = true;
    else {
        nextBtn.addEventListener('click', async () => {
            _internalCurrentPage = page + 1;
            await loadInternalResultsPage(jobId);
        });
    }
    paginationDivEl.appendChild(nextBtn);

    const lastBtn = document.createElement('button');
    lastBtn.className = 'page-btn';
    lastBtn.textContent = '»';
    lastBtn.title = '最後一頁';
    if (page >= total_pages) lastBtn.disabled = true;
    else {
        lastBtn.addEventListener('click', async () => {
            _internalCurrentPage = total_pages;
            await loadInternalResultsPage(jobId);
        });
    }
    paginationDivEl.appendChild(lastBtn);

    paginationEl.appendChild(paginationDivEl);
}

function renderJobInfo(job) {
    const el = (id) => document.getElementById(id);

    const isPausing = job.status === 'paused' && job.is_running;
    const isActuallyRunning = ['running', 'starting'].includes(job.status) || job.is_running;

    _currentJobConfig = job.config;

    const statusEl = el('job-status');
    if (statusEl) {
        let displayStatus = job.status;
        if (isPausing) displayStatus = 'paused';
        else if (job.status === 'starting') displayStatus = 'starting';
        else if (isActuallyRunning) displayStatus = 'running';

        statusEl.className = `badge badge-${displayStatus}`;
        statusEl.textContent = isPausing ? '暫停中...' : api.formatStatus(displayStatus);
    }

    const startUrlEl = el('job-start-url');
    if (startUrlEl) {
        startUrlEl.textContent = job.start_url || '-';
        if (job.start_url) {
            startUrlEl.href = job.start_url;
        } else {
            startUrlEl.removeAttribute('href');
        }
    }
    setTextContent('job-created-at', api.formatLocalTime(job.created_at));
    setTextContent('job-updated-at', api.formatLocalTime(job.updated_at));
    setTextContent('job-external-count', job.external_link_count ?? 0);

    const progress = job.progress || {};
    const total = progress.total || 0;
    const done = (progress.completed || 0) + (progress.skipped || 0) + (progress.failed || 0) + (progress.warning || 0);
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;

    const progressFillEl = el('job-progress-fill');
    const progressTextEl = el('job-progress-text');
    if (progressFillEl) progressFillEl.style.width = pct + '%';
    if (progressTextEl) progressTextEl.textContent = `${pct}% (${done} / ${total})`;

    setTextContent('stat-total', total);
    setTextContent('stat-completed', progress.completed || 0);
    setTextContent('stat-warning', progress.warning || 0);
    setTextContent('stat-pending', progress.pending || 0);
    setTextContent('stat-skipped', progress.skipped || 0);
    setTextContent('stat-failed', progress.failed || 0);

    const canStart = ['pending', 'paused'].includes(job.status) && !job.is_running;
    const canPause = isActuallyRunning && !isPausing;
    const canCompare = job.status === 'completed';
    const canTransfer = !isActuallyRunning;
    const canReset = ['completed', 'error', 'paused'].includes(job.status) && !job.is_running;
    const canRetry = ['completed', 'error'].includes(job.status) && !job.is_running;

    toggleDisplay('btn-start-job', canStart);
    toggleDisplay('btn-resume-job', false);
    toggleDisplay('btn-pause-job', canPause);
    toggleDisplay('btn-goto-compare', canCompare);
    toggleDisplay('btn-transfer-job', canTransfer);
    toggleDisplay('btn-duplicate-job', true);
    toggleDisplay('btn-reset-job', canReset);
    toggleDisplay('btn-retry-failed-job', canRetry);
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

    bindBtn('btn-retry-failed-job', async () => {
        const confirmed = await showConfirm('重試失敗項目', '確定要將爬取失敗的內部網頁，以及包含無效外連的網頁重新加入佇列並重試嗎？\n（系統將自動清除失效的外部連結並重新發起探測）', '確定重試');
        if (!confirmed) return;
        await api.post(`/api/jobs/${_currentJobId}/retry-failed`);
        toast.success('失敗項目已重置！您可以點擊啟動繼續任務。');
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

    bindBtn('btn-goto-compare', () => {
        window.location.hash = `#/compare?base=${_currentJobId}`;
    });

    // ── 移交任務跳轉邏輯 ──────────────────────────────────────────
    bindBtn('btn-transfer-job', () => {
        window.location.hash = `#/transfer?job=${_currentJobId}`;
    });

    bindBtn('btn-duplicate-job', () => {
        window.location.hash = `#/new?clone=${_currentJobId}`;
    });

    bindBtn('btn-export-full', async () => {
        await download(`/api/jobs/${_currentJobId}/export/full`);
    });

    const viewConfigBtn = document.getElementById('btn-view-job-config');
    const configModalEl = document.getElementById('job-config-modal');
    if (viewConfigBtn && configModalEl) {
        viewConfigBtn.addEventListener('click', () => {
            const container = document.getElementById('job-config-display-container');
            if (container) {
                container.replaceChildren();
                if (!_currentJobConfig) {
                    const empty = document.createElement('div');
                    empty.className = 'text-muted';
                    empty.style.textAlign = 'center';
                    empty.style.padding = '2rem';
                    empty.textContent = '無設定資料';
                    container.appendChild(empty);
                } else {
                    const c = _currentJobConfig;

                    const formatList = (list, parentNode) => {
                        if (!Array.isArray(list) || list.length === 0) {
                            const span = document.createElement('span');
                            span.className = 'text-muted';
                            span.textContent = '-';
                            parentNode.appendChild(span);
                            return;
                        }
                        list.forEach(item => {
                            const span = document.createElement('span');
                            span.style.display = 'inline-block';
                            span.style.background = 'var(--surface-overlay)';
                            span.style.border = '1px solid var(--surface-border)';
                            span.style.borderRadius = '4px';
                            span.style.padding = '2px 6px';
                            span.style.margin = '2px 2px 2px 0';
                            span.style.fontSize = '0.75rem';
                            span.textContent = item;
                            parentNode.appendChild(span);
                        });
                    };

                    const createSection = (title, items) => {
                        const section = document.createElement('div');

                        const titleEl = document.createElement('div');
                        titleEl.style.fontWeight = '600';
                        titleEl.style.borderBottom = '1px solid var(--surface-border)';
                        titleEl.style.paddingBottom = '0.5rem';
                        titleEl.style.marginBottom = '0.75rem';
                        titleEl.textContent = title;
                        section.appendChild(titleEl);

                        const grid = document.createElement('div');
                        grid.style.display = 'grid';
                        grid.style.gridTemplateColumns = '110px 1fr';
                        grid.style.gap = '0.75rem 0.5rem';
                        grid.style.fontSize = '0.875rem';

                        items.forEach(item => {
                            if (!item) return;
                            const lbl = document.createElement('div');
                            lbl.className = 'text-muted';
                            lbl.textContent = item.label;
                            grid.appendChild(lbl);

                            const val = document.createElement('div');
                            if (typeof item.value === 'function') {
                                item.value(val);
                            } else {
                                val.textContent = item.value;
                            }
                            if (item.valStyle) {
                                Object.assign(val.style, item.valStyle);
                            }
                            if (item.valClass) {
                                val.className = item.valClass;
                            }
                            grid.appendChild(val);
                        });

                        section.appendChild(grid);
                        return section;
                    };

                    const wrapper = document.createElement('div');
                    wrapper.style.display = 'flex';
                    wrapper.style.flexDirection = 'column';
                    wrapper.style.gap = '1.5rem';

                    wrapper.appendChild(createSection('🌐 基本設定', [
                        { label: '目標網域', value: el => formatList(c.target_domains, el) },
                        { label: '信任網域', value: el => formatList(c.trusted_domains, el) }
                    ]));

                    wrapper.appendChild(createSection('🛡️ 進階過濾與網路', [
                        { label: '忽略副檔名', value: el => formatList(c.ignore_extensions, el), valStyle: { maxHeight: '160px', overflowY: 'auto', paddingRight: '4px' } },
                        { label: '忽略路徑規則', value: el => formatList(c.ignore_regexes, el) },
                        {
                            label: '特定網域延遲', value: el => formatList(
                                c.domain_delays ? Object.entries(c.domain_delays).map(([k, v]) => `${k}: ${v}s`) : [], el
                            )
                        },
                        { label: '自簽憑證豁免', value: el => formatList(c.ssl_exempt_domains, el) },
                        { label: '社群與反爬蟲', value: el => formatList(c.social_domains, el) },
                        { label: '自訂 User-Agent', value: c.user_agent || '系統預設 (自動輪替)', valClass: 'text-xs text-muted' },
                        c.proxy_url !== undefined ? { label: '代理伺服器', value: c.proxy_url || '-', valClass: 'font-mono text-xs', valStyle: { wordBreak: 'break-all' } } : null
                    ]));

                    wrapper.appendChild(createSection('⚙️ 資源與限制', [
                        { label: '最大爬取深度', value: c.max_depth === null ? '不限制' : c.max_depth },
                        { label: '最大抓取頁數', value: c.max_pages === null ? '不限制' : c.max_pages },
                        { label: '請求延遲', value: `${c.delay ?? '-'} 秒` },
                        { label: '總連線逾時', value: `${c.timeout ?? '-'} 秒` },
                        { label: 'TCP 連線逾時', value: `${c.connect_timeout ?? '-'} 秒` },
                        { label: '外連探測逾時', value: `${c.external_check_timeout ?? '-'} 秒` },
                        { label: '失敗重試次數', value: `${c.retries ?? '-'} 次` }
                    ]));

                    container.appendChild(wrapper);
                }
            }
            configModalEl.style.display = 'flex';
        });
        document.getElementById('job-config-close')?.addEventListener('click', () => configModalEl.style.display = 'none');
        document.getElementById('job-config-ok')?.addEventListener('click', () => configModalEl.style.display = 'none');
    }
}

async function loadResults(jobId) {
    const containerEl = document.getElementById('results-container');
    if (!containerEl) return;

    try {
        const params = {};
        if (_currentExcludeEnabled && _currentExclude) {
            params.exclude = _currentExclude;
        }
        if (_currentGroupBy && _currentGroupBy !== 'none') {
            params.group_by = _currentGroupBy;
        }
        const summary = await api.get(`/api/jobs/${jobId}/results/summary`, Object.keys(params).length > 0 ? params : undefined);
        renderResultsSummary(summary);
    } catch (_) { /* 忽略 */ }

    if (_currentTab === 'external') {
        await loadResultsPage(jobId);
    } else {
        await loadInternalResultsPage(jobId);
    }
}

async function loadResultsPage(jobId) {
    const containerEl = document.getElementById('results-container');
    if (!containerEl) return;

    let tableEl = containerEl.querySelector('.table');
    if (!tableEl || containerEl.dataset.renderedGroup !== _currentGroupBy) {
        containerEl.replaceChildren();
        const skeletonEl = document.createElement('div');
        skeletonEl.className = 'skeleton';
        skeletonEl.style.height = '200px';
        skeletonEl.style.borderRadius = '0.5rem';
        containerEl.appendChild(skeletonEl);
    } else {
        tableEl.style.opacity = '0.5';
    }

    try {
        const params = {
            filter: _currentFilter || undefined,
            exclude: (_currentExcludeEnabled && _currentExclude) ? _currentExclude : undefined,
            group_by: _currentGroupBy,
            page: _currentPage,
            page_size: 50,
            sort_by: _detailSort.key || undefined,
            sort_asc: _detailSort.asc,
        };
        const activeFilters = Object.fromEntries(Object.entries(_detailColFilters).filter(([_, v]) => v !== ''));
        if (Object.keys(activeFilters).length > 0) {
            params.col_filters = JSON.stringify(activeFilters);
        }
        const res = await api.get(`/api/jobs/${jobId}/results`, params);
        if (tableEl) tableEl.style.opacity = '1';
        renderResultsTable(res, containerEl);
        renderPagination(res, jobId);
    } catch (err) {
        containerEl.replaceChildren();
        const emptyStateEl = document.createElement('div');
        emptyStateEl.className = 'empty-state';
        const descEl = document.createElement('div');
        descEl.className = 'empty-state-desc text-danger';
        descEl.textContent = err.message;
        emptyStateEl.appendChild(descEl);
        containerEl.appendChild(emptyStateEl);
    }
}

function renderResultsSummary(summary) {
    setTextContent('summary-total', summary.total_external_links ?? 0);
    setTextContent('summary-healthy', summary.healthy_count ?? 0);
    setTextContent('summary-dns-failed', summary.dns_failed_count ?? 0);
    setTextContent('summary-http-error', summary.http_error_count ?? 0);
    setTextContent('summary-insecure', summary.insecure_count ?? 0);
}

function renderResultsTable(res, containerEl) {
    _currentResultItems = res.items || [];

    if (_currentResultItems.length === 0) {
        containerEl.replaceChildren();
        const emptyStateEl = document.createElement('div');
        emptyStateEl.className = 'empty-state';
        const titleEl = document.createElement('div');
        titleEl.className = 'empty-state-title';
        titleEl.textContent = '太棒了！';
        const descEl = document.createElement('div');
        descEl.className = 'empty-state-desc';
        descEl.textContent = '您的外部連結沒有這類錯誤。';
        emptyStateEl.appendChild(titleEl);
        emptyStateEl.appendChild(descEl);
        containerEl.appendChild(emptyStateEl);
        delete containerEl.dataset.renderedGroup;
        return;
    }

    const isGroupTarget = _currentGroupBy === 'target';
    const isGroupSource = _currentGroupBy === 'source';
    const isGroupDomain = _currentGroupBy === 'domain';

    if (isGroupTarget) {
        _currentDetailHeaders = [{ label: '目標 URL', key: 'target_url' }, { label: 'IP 位址', key: 'ip_address' }, { label: 'HTTPS', key: 'is_secure' }, { label: 'HTTP 狀態', key: 'http_status_code' }, { label: '來源數', key: 'occurrence_count' }, { label: '錯誤訊息', key: 'error_message' }, { label: '來源頁面', key: 'source_urls', sortable: false, filterable: false }];
    } else if (isGroupSource) {
        _currentDetailHeaders = [{ label: '來源頁面', key: 'source_url' }, { label: '外連數量', key: 'occurrence_count' }, { label: '目標 URL', key: 'targets', sortable: false, filterable: false }];
    } else if (isGroupDomain) {
        _currentDetailHeaders = [{ label: '外部網域', key: 'domain' }, { label: '來源數', key: 'occurrence_count' }, { label: '不重複網址數', key: 'unique_urls_count' }, { label: '目標 URL', key: 'unique_urls', sortable: false, filterable: false }, { label: '來源頁面', key: 'source_urls', sortable: false, filterable: false }];
    } else {
        _currentDetailHeaders = [{ label: '來源頁面', key: 'source_url' }, { label: '目標 URL', key: 'target_url' }, { label: 'IP 位址', key: 'ip_address' }, { label: 'HTTPS', key: 'is_secure' }, { label: 'HTTP 狀態', key: 'http_status_code' }, { label: '錯誤訊息', key: 'error_message' }];
    }

    let tableEl = containerEl.querySelector('.table');
    if (!tableEl || containerEl.dataset.renderedGroup !== _currentGroupBy) {
        containerEl.replaceChildren();
        const wrapper = document.createElement('div');
        wrapper.className = 'table-wrapper';
        tableEl = document.createElement('table');
        tableEl.className = 'table';
        const thead = document.createElement('thead');
        const trHead = document.createElement('tr');

        _currentDetailHeaders.forEach(h => {
            const th = document.createElement('th');
            th.style.verticalAlign = 'top';
            const headerTop = document.createElement('div');
            headerTop.style.display = 'flex';
            headerTop.style.justifyContent = 'space-between';
            headerTop.style.alignItems = 'center';
            if (h.sortable !== false) headerTop.style.cursor = 'pointer';

            const label = document.createElement('span');
            label.textContent = h.label;
            headerTop.appendChild(label);

            if (h.sortable !== false) {
                const sortIcon = document.createElement('span');
                sortIcon.className = 'sort-icon';
                sortIcon.dataset.key = h.key;
                sortIcon.style.color = 'var(--text-muted)';
                sortIcon.style.fontSize = '0.75rem';
                sortIcon.style.marginLeft = '0.25rem';
                sortIcon.textContent = _detailSort.key === h.key ? (_detailSort.asc ? '▲' : '▼') : '⇅';
                if (_detailSort.key === h.key) sortIcon.style.color = 'var(--color-brand-500)';
                headerTop.appendChild(sortIcon);

                headerTop.addEventListener('click', () => {
                    if (_detailSort.key === h.key) _detailSort.asc = !_detailSort.asc;
                    else { _detailSort.key = h.key; _detailSort.asc = true; }

                    api.updateSortIcons(trHead, _detailSort.key, _detailSort.asc);
                    _currentPage = 1;
                    loadResultsPage(_currentJobId);
                });
            }
            th.appendChild(headerTop);

            if (h.filterable !== false) {
                const filterInput = api.createFilterInput(_detailColFilters[h.key], (newVal) => {
                    _detailColFilters[h.key] = newVal;
                    _currentPage = 1;
                    if (window._filterTimeout) clearTimeout(window._filterTimeout);
                    window._filterTimeout = setTimeout(() => {
                        loadResultsPage(_currentJobId);
                    }, 500);
                });
                th.appendChild(filterInput);
            }
            trHead.appendChild(th);
        });
        thead.appendChild(trHead);
        tableEl.appendChild(thead);
        tableEl.appendChild(document.createElement('tbody'));
        wrapper.appendChild(tableEl);
        containerEl.appendChild(wrapper);
        containerEl.dataset.renderedGroup = _currentGroupBy;

        const paginationContainerEl = document.createElement('div');
        paginationContainerEl.id = 'results-pagination';
        containerEl.appendChild(paginationContainerEl);
    }

    renderResultsTbody(tableEl);
}

function renderResultsTbody(tableEl) {
    let data = [..._currentResultItems];

    let tbody = tableEl.querySelector('tbody');
    tbody.replaceChildren();

    if (data.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = _currentDetailHeaders.length;
        td.className = 'text-center text-muted';
        td.style.padding = '1rem';
        td.textContent = '本頁無符合篩選條件的結果';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
    }

    const isGroupTarget = _currentGroupBy === 'target';
    const isGroupSource = _currentGroupBy === 'source';
    const isGroupDomain = _currentGroupBy === 'domain';

    data.forEach(item => {
        if (isGroupDomain) {
            const tr = document.createElement('tr');

            const tdDomain = document.createElement('td');
            tdDomain.className = 'font-mono font-medium truncate';
            tdDomain.style.maxWidth = '260px';
            tdDomain.title = item.domain;
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
                li.className = 'truncate text-muted';
                li.style.maxWidth = '250px';
                li.style.marginBottom = '0.25rem';
                li.title = u;
                const aU = document.createElement('a');
                aU.href = u;
                aU.target = '_blank';
                aU.rel = 'noopener noreferrer';
                aU.style.color = 'inherit';
                aU.textContent = u;
                li.appendChild(aU);
                ul.appendChild(li);
            });
            if (item.unique_urls.length >= 10) {
                const truncLi = document.createElement('li');
                truncLi.className = 'text-xs text-muted';
                truncLi.style.marginTop = '0.25rem';
                truncLi.textContent = '... (為確保效能已截斷，請匯出 CSV 檢視完整清單)';
                ul.appendChild(truncLi);
            }
            divUrls.appendChild(ul);
            tdUrls.appendChild(divUrls);
            tr.appendChild(tdUrls);

            const tdSources = document.createElement('td');
            if (item.source_urls && item.source_urls.length > 0) {
                const divSources = document.createElement('div');
                divSources.style.maxHeight = '150px';
                divSources.style.overflowY = 'auto';
                divSources.style.paddingRight = '4px';
                const ulSources = document.createElement('ul');
                ulSources.style.margin = '0';
                ulSources.style.paddingLeft = '0';
                ulSources.style.listStyle = 'none';
                ulSources.style.fontSize = '0.8125rem';
                item.source_urls.forEach(src => {
                    const li = document.createElement('li');
                    li.className = 'truncate text-muted';
                    li.style.maxWidth = '250px';
                    li.style.marginBottom = '0.25rem';
                    li.title = src;
                    const aSrc = document.createElement('a');
                    aSrc.href = src;
                    aSrc.target = '_blank';
                    aSrc.rel = 'noopener noreferrer';
                    aSrc.style.color = 'inherit';
                    aSrc.textContent = src;
                    li.appendChild(aSrc);
                    ulSources.appendChild(li);
                });
                if (item.source_urls.length >= 10) {
                    const truncLi = document.createElement('li');
                    truncLi.className = 'text-xs text-muted';
                    truncLi.style.marginTop = '0.25rem';
                    truncLi.textContent = '... (為確保效能已截斷，請匯出 CSV 檢視完整清單)';
                    ulSources.appendChild(truncLi);
                }
                divSources.appendChild(ulSources);
                tdSources.appendChild(divSources);
            } else {
                tdSources.className = 'text-muted';
                tdSources.textContent = '-';
            }
            tr.appendChild(tdSources);

            tbody.appendChild(tr);
            return;
        }

        if (isGroupSource) {
            const tr = document.createElement('tr');

            const tdSource = document.createElement('td');
            tdSource.className = 'truncate';
            tdSource.style.maxWidth = '260px';
            tdSource.title = item.source_url;
            const aSource = document.createElement('a');
            aSource.href = item.source_url;
            aSource.target = '_blank';
            aSource.rel = 'noopener noreferrer';
            aSource.className = 'text-link';
            aSource.textContent = item.source_url;
            tdSource.appendChild(aSource);
            tr.appendChild(tdSource);

            const tdCount = document.createElement('td');
            tdCount.style.fontWeight = '600';
            tdCount.style.fontFeatureSettings = '"tnum"';
            tdCount.textContent = item.occurrence_count;
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

                const badgeClass = getInternalBadgeClass(t.status, t.error_message);
                const badge = document.createElement('span');
                badge.className = `badge ${badgeClass}`;
                badge.style.padding = '0.125rem 0.375rem';
                badge.style.fontSize = '0.7rem';
                badge.style.marginRight = '0.5rem';
                badge.style.display = 'inline-block';
                badge.style.minWidth = '3.5rem';
                badge.style.textAlign = 'center';
                badge.textContent = t.status;
                li.appendChild(badge);

                if (!t.is_secure) {
                    const secBadge = document.createElement('span');
                    secBadge.className = 'text-danger';
                    secBadge.style.marginRight = '0.25rem';
                    secBadge.title = '非 HTTPS';
                    secBadge.textContent = '🔓';
                    li.appendChild(secBadge);
                }

                const spanTargetWrapper = document.createElement('span');
                spanTargetWrapper.className = 'truncate';
                spanTargetWrapper.style.display = 'inline-block';
                spanTargetWrapper.style.maxWidth = '400px';
                spanTargetWrapper.style.verticalAlign = 'bottom';
                spanTargetWrapper.title = t.url;

                const aTarget = document.createElement('a');
                aTarget.href = t.url;
                aTarget.target = '_blank';
                aTarget.rel = 'noopener noreferrer';
                aTarget.className = 'text-link';
                aTarget.style.color = 'inherit';
                aTarget.textContent = t.url;

                spanTargetWrapper.appendChild(aTarget);
                li.appendChild(spanTargetWrapper);
                ul.appendChild(li);
            });
            if (item.targets.length >= 10) {
                const truncLi = document.createElement('li');
                truncLi.className = 'text-xs text-muted';
                truncLi.style.marginTop = '0.25rem';
                truncLi.textContent = '... (為確保效能已截斷，請匯出 CSV 檢視完整清單)';
                ul.appendChild(truncLi);
            }
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
            tdSource.className = 'truncate';
            tdSource.style.maxWidth = '260px';
            tdSource.title = item.source_url;
            const aSource = document.createElement('a');
            aSource.href = item.source_url;
            aSource.target = '_blank';
            aSource.rel = 'noopener noreferrer';
            aSource.className = 'text-link';
            aSource.textContent = item.source_url;
            tdSource.appendChild(aSource);
            tr.appendChild(tdSource);
        }

        const tdTarget = document.createElement('td');
        tdTarget.className = 'truncate';
        tdTarget.style.maxWidth = '260px';
        tdTarget.title = item.target_url;
        const aTarget = document.createElement('a');
        aTarget.href = item.target_url;
        aTarget.target = '_blank';
        aTarget.rel = 'noopener noreferrer';
        aTarget.className = 'text-link';
        aTarget.textContent = item.target_url;
        tdTarget.appendChild(aTarget);
        tr.appendChild(tdTarget);

        const tdIp = document.createElement('td');
        tdIp.className = 'font-mono text-xs text-muted';
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
        tdError.style.maxWidth = '160px';
        tdError.title = item.error_message || '';
        tdError.textContent = item.error_message || '-';
        tr.appendChild(tdError);

        if (isGroupTarget) {
            const tdSources = document.createElement('td');
            if (item.source_urls && item.source_urls.length > 0) {
                const divSources = document.createElement('div');
                divSources.style.maxHeight = '150px';
                divSources.style.overflowY = 'auto';
                divSources.style.paddingRight = '4px';
                const ul = document.createElement('ul');
                ul.style.margin = '0';
                ul.style.paddingLeft = '0';
                ul.style.listStyle = 'none';
                ul.style.fontSize = '0.8125rem';
                item.source_urls.forEach(src => {
                    const li = document.createElement('li');
                    li.className = 'truncate text-muted';
                    li.style.maxWidth = '250px';
                    li.style.marginBottom = '0.25rem';
                    li.title = src;
                    const aSrc = document.createElement('a');
                    aSrc.href = src;
                    aSrc.target = '_blank';
                    aSrc.rel = 'noopener noreferrer';
                    aSrc.style.color = 'inherit';
                    aSrc.textContent = src;
                    li.appendChild(aSrc);
                    ul.appendChild(li);
                });
                if (item.source_urls.length >= 10) {
                    const truncLi = document.createElement('li');
                    truncLi.className = 'text-xs text-muted';
                    truncLi.style.marginTop = '0.25rem';
                    truncLi.textContent = '... (為確保效能已截斷，請匯出 CSV 檢視完整清單)';
                    ul.appendChild(truncLi);
                }
                divSources.appendChild(ul);
                tdSources.appendChild(divSources);
            } else {
                tdSources.className = 'text-muted';
                tdSources.textContent = '-';
            }
            tr.appendChild(tdSources);
        }

        tbody.appendChild(tr);
    });
}

function renderPagination(res, jobId) {
    const paginationEl = document.getElementById('results-pagination');
    if (!paginationEl) return;

    paginationEl.replaceChildren();
    const { page, total_pages } = res;
    if (total_pages <= 1) return;

    const paginationDivEl = document.createElement('div');
    paginationDivEl.className = 'pagination';

    const firstBtn = document.createElement('button');
    firstBtn.className = 'page-btn';
    firstBtn.textContent = '«';
    firstBtn.title = '第一頁';
    if (page <= 1) firstBtn.disabled = true;
    else {
        firstBtn.dataset.page = 1;
        firstBtn.addEventListener('click', async () => {
            _currentPage = 1;
            await loadResultsPage(jobId);
        });
    }
    paginationDivEl.appendChild(firstBtn);

    const prevBtn = document.createElement('button');
    prevBtn.className = 'page-btn';
    prevBtn.textContent = '‹';
    if (page <= 1) prevBtn.disabled = true;
    else {
        prevBtn.dataset.page = page - 1;
        prevBtn.addEventListener('click', async () => {
            _currentPage = page - 1;
            await loadResultsPage(jobId);
        });
    }
    paginationDivEl.appendChild(prevBtn);

    const delta = 2;
    const start = Math.max(1, page - delta);
    const end = Math.min(total_pages, page + delta);

    for (let i = start; i <= end; i++) {
        const pageBtn = document.createElement('button');
        pageBtn.className = i === page ? 'page-btn active' : 'page-btn';
        pageBtn.textContent = i;
        pageBtn.dataset.page = i;
        if (i !== page) {
            pageBtn.addEventListener('click', async () => {
                _currentPage = i;
                await loadResultsPage(jobId);
            });
        }
        paginationDivEl.appendChild(pageBtn);
    }

    const nextBtn = document.createElement('button');
    nextBtn.className = 'page-btn';
    nextBtn.textContent = '›';
    if (page >= total_pages) nextBtn.disabled = true;
    else {
        nextBtn.dataset.page = page + 1;
        nextBtn.addEventListener('click', async () => {
            _currentPage = page + 1;
            await loadResultsPage(jobId);
        });
    }
    paginationDivEl.appendChild(nextBtn);

    const lastBtn = document.createElement('button');
    lastBtn.className = 'page-btn';
    lastBtn.textContent = '»';
    lastBtn.title = '最後一頁';
    if (page >= total_pages) lastBtn.disabled = true;
    else {
        lastBtn.dataset.page = total_pages;
        lastBtn.addEventListener('click', async () => {
            _currentPage = total_pages;
            await loadResultsPage(jobId);
        });
    }
    paginationDivEl.appendChild(lastBtn);

    paginationEl.appendChild(paginationDivEl);
}

function bindResultsControls() {
    document.querySelectorAll('#tab-content-external .filter-card[data-filter]').forEach(chip => {
        chip.addEventListener('click', async () => {
            const filter = chip.dataset.filter;
            _currentFilter = (_currentFilter === filter || filter === 'all') ? null : filter;
            _currentPage = 1;

            let activeDesc = '';
            let activeColor = 'var(--color-brand-400)';

            document.querySelectorAll('#tab-content-external .filter-card[data-filter]').forEach(c => {
                const isActive = _currentFilter === c.dataset.filter || (_currentFilter === null && c.dataset.filter === 'all');
                c.classList.toggle('active', isActive);
                if (isActive) {
                    activeDesc = c.dataset.desc;
                    activeColor = c.dataset.color || 'var(--color-brand-400)';
                }
            });
            const descBox = document.getElementById('ext-filter-desc');
            if (descBox) {
                descBox.style.borderLeftColor = activeColor;
                const span = descBox.querySelector('span');
                if (span) span.textContent = activeDesc;
            }
            await loadResultsPage(_currentJobId);
        });
    });

    document.querySelectorAll('#tab-content-internal .filter-card[data-filter]').forEach(chip => {
        chip.addEventListener('click', async () => {
            const filter = chip.dataset.filter;
            _internalFilter = (_internalFilter === filter || filter === 'all') ? null : filter;
            _internalCurrentPage = 1;

            let activeDesc = '';
            let activeColor = 'var(--color-brand-400)';

            document.querySelectorAll('#tab-content-internal .filter-card[data-filter]').forEach(c => {
                const isActive = _internalFilter === c.dataset.filter || (_internalFilter === null && c.dataset.filter === 'all');
                c.classList.toggle('active', isActive);
                if (isActive) {
                    activeDesc = c.dataset.desc;
                    activeColor = c.dataset.color || 'var(--color-brand-400)';
                }
            });
            const descBox = document.getElementById('int-filter-desc');
            if (descBox) {
                descBox.style.borderLeftColor = activeColor;
                const span = descBox.querySelector('span');
                if (span) span.textContent = activeDesc;
            }
            await loadInternalResultsPage(_currentJobId);
        });
    });

    document.querySelectorAll('#job-detail-tabs .tab-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            document.querySelectorAll('#job-detail-tabs .tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            _currentTab = btn.dataset.tab;

            document.getElementById('tab-content-external').style.display = _currentTab === 'external' ? 'block' : 'none';
            document.getElementById('tab-content-internal').style.display = _currentTab === 'internal' ? 'block' : 'none';

            await loadResults(_currentJobId);
        });
    });

    // ── 綁定排除網域 Modal 邏輯 ──────────────────────────────────────────
    const openExcludeBtn = document.getElementById('btn-open-exclude-modal');
    const excludeModalEl = document.getElementById('exclude-domains-modal');
    const excludeTextareaInput = document.getElementById('exclude-domains-textarea');
    const excludeEnabledCheckbox = document.getElementById('exclude-domains-enabled');
    const excludeSubmitBtn = document.getElementById('exclude-domains-submit');
    const excludeCloseBtn = document.getElementById('exclude-domains-close');
    const excludeCancelBtn = document.getElementById('exclude-domains-cancel');

    if (openExcludeBtn && excludeModalEl) {
        const closeExcludeModal = () => { excludeModalEl.style.display = 'none'; };

        openExcludeBtn.addEventListener('click', () => {
            excludeTextareaInput.value = _currentExclude.split(',').filter(Boolean).join('\n');
            if (excludeEnabledCheckbox) excludeEnabledCheckbox.checked = _currentExcludeEnabled;
            excludeModalEl.style.display = 'flex';
            setTimeout(() => excludeTextareaInput.focus(), 50);
        });

        excludeCloseBtn.addEventListener('click', closeExcludeModal);
        excludeCancelBtn.addEventListener('click', closeExcludeModal);

        excludeSubmitBtn.addEventListener('click', async () => {
            if (document.getElementById('view-job-detail').style.display === 'none') return;

            if (excludeEnabledCheckbox) {
                _currentExcludeEnabled = excludeEnabledCheckbox.checked;
                localStorage.setItem('ext-link-checker-exclude-enabled', _currentExcludeEnabled);
            }

            const lines = excludeTextareaInput.value.split('\n').map(s => s.trim()).filter(Boolean);
            _currentExclude = lines.join(',');
            localStorage.setItem('ext-link-checker-exclude-domains', _currentExclude);

            const isActive = _currentExcludeEnabled && _currentExclude;
            openExcludeBtn.style.color = isActive ? 'var(--color-brand-500)' : '';
            openExcludeBtn.style.borderColor = isActive ? 'var(--color-brand-500)' : '';
            openExcludeBtn.style.background = isActive ? 'hsla(221, 83%, 53%, 0.1)' : '';

            closeExcludeModal();
            _currentPage = 1;
            await loadResults(_currentJobId);
        });
    }

    const groupSelectEl = document.getElementById('results-group-select');
    if (groupSelectEl) {
        groupSelectEl.addEventListener('change', async () => {
            _currentGroupBy = groupSelectEl.value;
            _currentPage = 1;
            _detailSort = { key: null, asc: true };
            _detailColFilters = {};
            await loadResults(_currentJobId);
        });
    }

    const internalGroupSelectEl = document.getElementById('internal-results-group-select');
    if (internalGroupSelectEl) {
        internalGroupSelectEl.addEventListener('change', async () => {
            _internalGroupBy = internalGroupSelectEl.value;
            _internalCurrentPage = 1;
            _internalSort = { key: null, asc: true };
            _internalColFilters = {};
            await loadInternalResultsPage(_currentJobId);
        });
    }

    bindBtn('btn-export-csv', async () => {
        const params = new URLSearchParams({ fmt: 'csv', group_by: _currentGroupBy });
        if (_currentFilter) params.set('filter', _currentFilter);
        if (_currentExcludeEnabled && _currentExclude) params.set('exclude', _currentExclude);
        await download(`/api/jobs/${_currentJobId}/results/export?${params}`);
    });

    bindBtn('btn-export-json', async () => {
        const params = new URLSearchParams({ fmt: 'json', group_by: _currentGroupBy });
        if (_currentFilter) params.set('filter', _currentFilter);
        if (_currentExcludeEnabled && _currentExclude) params.set('exclude', _currentExclude);
        await download(`/api/jobs/${_currentJobId}/results/export?${params}`);
    });

    bindBtn('btn-int-export-csv', async () => {
        const params = new URLSearchParams({ fmt: 'csv', group_by: _internalGroupBy });
        if (_internalFilter && _internalFilter !== 'all') params.set('filter', _internalFilter);
        await download(`/api/jobs/${_currentJobId}/internal-results/export?${params}`);
    });

    bindBtn('btn-int-export-json', async () => {
        const params = new URLSearchParams({ fmt: 'json', group_by: _internalGroupBy });
        if (_internalFilter && _internalFilter !== 'all') params.set('filter', _internalFilter);
        await download(`/api/jobs/${_currentJobId}/internal-results/export?${params}`);
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
