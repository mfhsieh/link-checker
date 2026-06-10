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
let _currentExclude = '';
let _currentExcludeEnabled = true;
let _currentGroupBy = 'none';
let _currentPage = 1;
let _eventsBound = false;
let _pollInterval = 5000;
let _detailSort = { key: null, asc: true };
let _detailColFilters = {};
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

    // 初始化時載入儲存在 localStorage 的排除清單
    _currentExclude = localStorage.getItem('ext-link-checker-exclude-domains') || '';
    _currentExcludeEnabled = localStorage.getItem('ext-link-checker-exclude-enabled') !== 'false';

    _currentGroupBy = 'none';
    _currentPage = 1;
    _detailSort = { key: null, asc: true };
    _detailColFilters = {};

    // 清除舊的 UI 狀態 (如搜尋框、過濾器狀態)
    document.querySelectorAll('.filter-card[data-filter]').forEach(c => {
        c.classList.toggle('active', c.dataset.filter === 'all');
    });
    const groupSelectEl = document.getElementById('results-group-select');
    if (groupSelectEl) groupSelectEl.value = 'none';

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

        const isActuallyRunning = job.status === 'running' || job.is_running;
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

    const progressFillEl = el('job-progress-fill');
    const progressTextEl = el('job-progress-text');
    if (progressFillEl) progressFillEl.style.width = pct + '%';
    if (progressTextEl) progressTextEl.textContent = `${pct}% (${done} / ${total})`;

    setTextContent('stat-total', total);
    setTextContent('stat-completed', progress.completed || 0);
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
        const confirmed = await showConfirm('重試失敗項目', '確定要將爬取失敗的內部網頁重新加入佇列並重試嗎？\n（註：此操作不會影響或重試已經紀錄為無效的外部連結）', '確定重試');
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

                    wrapper.appendChild(createSection('🌐 網域設定', [
                        { label: '目標網域', value: el => formatList(c.target_domains, el) },
                        { label: '信任網域', value: el => formatList(c.trusted_domains, el) }
                    ]));

                    wrapper.appendChild(createSection('⚙️ 資源與限制', [
                        { label: '最大爬取深度', value: c.max_depth === null ? '不限制' : c.max_depth },
                        { label: '最大抓取頁數', value: c.max_pages === null ? '不限制' : c.max_pages },
                        { label: '請求延遲', value: `${c.delay ?? '-'} 秒` },
                        { label: '連線逾時', value: `${c.timeout ?? '-'} 秒` },
                        { label: 'TCP連線逾時', value: `${c.connect_timeout ?? '-'} 秒` },
                        { label: '外連探測逾時', value: `${c.external_check_timeout ?? '-'} 秒` },
                        { label: '失敗重試', value: `${c.retries ?? '-'} 次` },
                        c.proxy_url !== undefined ? { label: '代理伺服器', value: c.proxy_url || '-', valClass: 'font-mono text-xs', valStyle: { wordBreak: 'break-all' } } : null
                    ]));

                    wrapper.appendChild(createSection('🛡️ 過濾與排除', [
                        { label: '忽略路徑規則', value: el => formatList(c.ignore_regexes, el) },
                        { label: '忽略副檔名', value: el => formatList(c.ignore_extensions, el), valStyle: { maxHeight: '160px', overflowY: 'auto', paddingRight: '4px' } }
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

    await loadResultsPage(jobId);
}

async function loadResultsPage(jobId) {
    const containerEl = document.getElementById('results-container');
    if (!containerEl) return;

    containerEl.replaceChildren();
    const skeletonEl = document.createElement('div');
    skeletonEl.className = 'skeleton';
    skeletonEl.style.height = '200px';
    skeletonEl.style.borderRadius = '0.5rem';
    containerEl.appendChild(skeletonEl);

    try {
        const params = {
            filter: _currentFilter || undefined,
            exclude: (_currentExcludeEnabled && _currentExclude) ? _currentExclude : undefined,
            group_by: _currentGroupBy,
            page: _currentPage,
            page_size: 50,
        };
        const res = await api.get(`/api/jobs/${jobId}/results`, params);
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
        titleEl.textContent = '無結果';
        const descEl = document.createElement('div');
        descEl.className = 'empty-state-desc';
        descEl.textContent = '目前沒有符合條件的外連結果';
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
        _currentDetailHeaders = [{ label: '目標 URL', key: 'target_url' }, { label: 'IP 位址', key: 'ip_address' }, { label: '安全', key: 'is_secure' }, { label: 'HTTP 狀態', key: 'http_status_code' }, { label: '來源數', key: 'occurrence_count' }, { label: '錯誤訊息', key: 'error_message' }];
    } else if (isGroupSource) {
        _currentDetailHeaders = [{ label: '來源頁面', key: 'source_url' }, { label: '外連數量', key: 'occurrence_count' }, { label: '詳細連結清單', key: 'targets', sortable: false, filterable: false }];
    } else if (isGroupDomain) {
        _currentDetailHeaders = [{ label: '外部網域', key: 'domain' }, { label: '總出現次數', key: 'occurrence_count' }, { label: '不重複網址數', key: 'unique_urls_count' }, { label: '包含網址清單', key: 'unique_urls', sortable: false, filterable: false }];
    } else {
        _currentDetailHeaders = [{ label: '來源頁面', key: 'source_url' }, { label: '目標 URL', key: 'target_url' }, { label: 'IP 位址', key: 'ip_address' }, { label: '安全', key: 'is_secure' }, { label: 'HTTP 狀態', key: 'http_status_code' }, { label: '錯誤訊息', key: 'error_message' }];
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

                    trHead.querySelectorAll('.sort-icon').forEach(icon => {
                        if (icon.dataset.key === _detailSort.key) {
                            icon.textContent = _detailSort.asc ? '▲' : '▼';
                            icon.style.color = 'var(--color-brand-500)';
                        } else {
                            icon.textContent = '⇅';
                            icon.style.color = 'var(--text-muted)';
                        }
                    });
                    renderResultsTbody(tableEl);
                });
            }
            th.appendChild(headerTop);

            if (h.filterable !== false) {
                const filterInput = document.createElement('input');
                filterInput.type = 'text';
                filterInput.className = 'form-input text-xs';
                filterInput.placeholder = '篩選...';
                filterInput.style.marginTop = '0.5rem';
                filterInput.style.padding = '0.25rem 0.5rem';
                filterInput.style.height = 'auto';
                filterInput.style.fontWeight = 'normal';
                filterInput.value = _detailColFilters[h.key] || '';

                filterInput.addEventListener('input', (e) => {
                    _detailColFilters[h.key] = e.target.value.toLowerCase();
                    renderResultsTbody(tableEl);
                });
                filterInput.addEventListener('click', e => e.stopPropagation());
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

    for (const [k, v] of Object.entries(_detailColFilters)) {
        if (!v) continue;
        data = data.filter(item => {
            let val = item[k];
            if (k === 'is_secure') val = val ? '✓' : '✗';
            return String(val || '').toLowerCase().includes(v);
        });
    }

    if (_detailSort.key) {
        data.sort((a, b) => {
            let valA = a[_detailSort.key];
            let valB = b[_detailSort.key];
            if (_detailSort.key === 'is_secure') {
                valA = valA ? 1 : 0;
                valB = valB ? 1 : 0;
            }
            if (valA === undefined || valA === null) valA = '';
            if (valB === undefined || valB === null) valB = '';
            if (typeof valA === 'number' && typeof valB === 'number') return _detailSort.asc ? valA - valB : valB - valA;
            valA = String(valA).toLowerCase();
            valB = String(valB).toLowerCase();
            if (valA < valB) return _detailSort.asc ? -1 : 1;
            if (valA > valB) return _detailSort.asc ? 1 : -1;
            return 0;
        });
    }

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
                const aU = document.createElement('a');
                aU.href = u;
                aU.target = '_blank';
                aU.rel = 'noopener noreferrer';
                aU.className = 'text-link';
                aU.textContent = u;
                li.appendChild(aU);
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
            const aSource = document.createElement('a');
            aSource.href = item.source_url;
            aSource.target = '_blank';
            aSource.rel = 'noopener noreferrer';
            aSource.className = 'text-link';
            aSource.textContent = item.source_url;
            tdSource.appendChild(aSource);
            tr.appendChild(tdSource);

            const tdCount = document.createElement('td');
            const countBadge = document.createElement('span');
            countBadge.className = 'badge badge-danger';
            countBadge.textContent = item.occurrence_count;
            tdCount.appendChild(countBadge);
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
            const aSource = document.createElement('a');
            aSource.href = item.source_url;
            aSource.target = '_blank';
            aSource.rel = 'noopener noreferrer';
            aSource.style.color = 'inherit';
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
        aTarget.style.color = 'inherit';
        aTarget.textContent = item.target_url;
        tdTarget.appendChild(aTarget);
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
}

function renderPagination(res, jobId) {
    const paginationEl = document.getElementById('results-pagination');
    if (!paginationEl) return;

    paginationEl.replaceChildren();
    const { page, total_pages } = res;
    if (total_pages <= 1) return;

    const paginationDivEl = document.createElement('div');
    paginationDivEl.className = 'pagination';

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

    paginationEl.appendChild(paginationDivEl);
}

function bindResultsControls() {
    document.querySelectorAll('.filter-card[data-filter]').forEach(chip => {
        chip.addEventListener('click', async () => {
            const filter = chip.dataset.filter;
            _currentFilter = (_currentFilter === filter || filter === 'all') ? null : filter;
            _currentPage = 1;
            document.querySelectorAll('.filter-card[data-filter]').forEach(c => {
                const isActive = _currentFilter === c.dataset.filter || (_currentFilter === null && c.dataset.filter === 'all');
                c.classList.toggle('active', isActive);
            });
            await loadResultsPage(_currentJobId);
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
