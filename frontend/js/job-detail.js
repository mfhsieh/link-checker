/**
 * job-detail.js — 任務詳情頁面邏輯（ESM）
 */

import * as api from './api.js';
import { download } from './api.js';
import { toast } from './toast.js';

/** @type {EventSource|null} SSE 連線物件 */
let _eventSource = null;
/** @type {string|null} 目前的任務 ID */
let _currentJobId = null;
/** @type {string|null} 目前任務的狀態 */
let _currentJobStatus = null;
/** @type {Object|null} 目前任務的設定快照 */
let _currentJobConfig = null;
/** @type {string|null} 目前外部連結的篩選狀態 (如 'dead', 'healthy' 等) */
let _currentFilter = null;
/** @type {string} 目前排除的網域字串 (以逗號分隔) */
let _currentExclude = '';
/** @type {boolean} 是否啟用排除網域過濾 */
let _currentExcludeEnabled = true;
/** @type {string} 目前外部連結的聚合模式 ('none', 'target', 'source', 'domain') */
let _currentGroupBy = 'none';
/** @type {number} 外部連結列表目前頁碼 */
let _currentPage = 1;
/** @type {boolean} 是否已綁定任務詳情事件 */
let _eventsBound = false;
/** @type {string} 目前任務詳情的頁籤 ('external' 或 'internal') */
let _currentTab = 'external';
/** @type {number} 內部失效連結列表目前頁碼 */
let _internalCurrentPage = 1;
/** @type {string|null} 目前內部失效連結的篩選狀態 */
let _internalFilter = null;
/** @type {string} 目前內部失效連結的聚合模式 ('none', 'source') */
let _internalGroupBy = 'none';
/** @type {Array<Object>} 內部失效連結當頁結果暫存 */
let _internalResultItems = [];
/** @type {{key: string|null, asc: boolean}} 外部連結表格排序狀態 */
let _detailSort = { key: null, asc: true };
/** @type {Object<string, string>} 外部連結表格各欄位篩選條件 */
let _detailColFilters = {};
/** @type {{key: string|null, asc: boolean}} 內部失效連結表格排序狀態 */
let _internalSort = { key: null, asc: true };
/** @type {Object<string, string>} 內部失效連結表格各欄位篩選條件 */
let _internalColFilters = {};
/** @type {Array<{label: string, key: string|null, sortable?: boolean, filterable?: boolean}>} 外部連結當前表頭設定 */
let _currentDetailHeaders = [];
/** @type {Array<Object>} 外部連結當頁結果暫存 */
let _currentResultItems = [];

/** @type {number} 用於防止外部連結載入的 Race Condition */
let _currentExtReqId = 0;
/** @type {number} 用於防止內部連結載入的 Race Condition */
let _currentIntReqId = 0;
/** @type {number} 用於防止外部連結統計載入的 Race Condition */
let _currentExtSummaryReqId = 0;
/** @type {number} 用於防止內部連結統計載入的 Race Condition */
let _currentIntSummaryReqId = 0;

/**
 * 外部連結 Summary 快取。
 * key 為影響 Summary 的參數字串（exclude + groupBy），
 * data 為上次 API 回傳的統計物件。
 * 當資料實際發生變動（重探測、重置、任務狀態轉換）時，設 key=null 以強制失效。
 * @type {{ key: string|null, data: Object|null }}
 */
let _extSummaryCache = { key: null, data: null };

/**
 * 內部連結 Summary 快取。
 * key 為影響 Summary 的參數字串（groupBy），
 * data 為上次 API 回傳的統計物件。
 * @type {{ key: string|null, data: Object|null }}
 */
let _intSummaryCache = { key: null, data: null };

/** @type {Set<string>} 外部連結已選取項目 */
let _extSelectedUrls = new Set();
/** @type {Set<string>} 內部連結已選取項目 */
let _intSelectedUrls = new Set();

/**
 * 啟動 Server-Sent Events (SSE) 串流以接收即時任務更新。
 * @param {string} jobId - 任務 ID
 * @returns {void} 無回傳值
 */
function startSseStream(jobId) {
    if (_eventSource) {
        _eventSource.close();
    }

    _eventSource = new EventSource(`/api/jobs/${jobId}/stream`);

    _eventSource.onmessage = (event) => {
        try {
            const job = JSON.parse(event.data);
            renderJobInfo(job);
            if (['completed', 'error', 'paused', 'pending'].includes(job.status) && !job.is_running) {
                stopSseStream();
            }
        } catch (e) {
            console.error('Error parsing SSE data:', e);
        }
    };

    _eventSource.onerror = () => {
        if (_eventSource && _eventSource.readyState === EventSource.CLOSED) {
            console.log('SSE connection closed by server or due to a network error.');
        }
    };
}

/**
 * 停止 Server-Sent Events (SSE) 串流
 * @returns {void}
 */
function stopSseStream() {
    if (_eventSource) {
        _eventSource.close();
        _eventSource = null;
    }
}

/**
 * 顯示自訂的確認對話框
 * @param {string} title - 對話框標題
 * @param {string} message - 提示訊息
 * @param {string} [confirmText='確定'] - 確認按鈕文字
 * @param {boolean} [isDanger=false] - 是否為危險操作 (紅色按鈕)
 * @returns {Promise<boolean>} 使用者點擊確認回傳 true，取消則回傳 false
 */
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
 * 清除外部結果的統計卡片數字
 * @returns {void}
 */
function clearResultsSummaryUI() {
    const stats = [
        'summary-total', 'summary-healthy', 'summary-dns-failed', 'summary-not-found',
        'summary-server-error', 'summary-connection-error', 'summary-other-error',
        'summary-blocked', 'summary-insecure'
    ];
    stats.forEach(id => setTextContent(id, '-'));
}

/**
 * 清除內部結果的統計卡片數字
 * @returns {void}
 */
function clearInternalSummaryUI() {
    const stats = [
        'int-summary-total', 'int-summary-server-error', 'int-summary-connection-error',
        'int-summary-timeout', 'int-summary-not-found', 'int-summary-other-error',
        'int-summary-warning', 'int-summary-blocked', 'int-summary-insecure'
    ];
    stats.forEach(id => setTextContent(id, '-'));
}

/**
 * 清除上一個任務的 UI 狀態，避免載入新任務時發生舊資料閃爍
 * @returns {void}
 */
function clearJobDetailUI() {
    const el = (id) => document.getElementById(id);

    const statusEl = el('job-status');
    if (statusEl) {
        statusEl.className = 'badge badge-pending';
        statusEl.textContent = '載入中...';
    }

    const startUrlEl = el('job-start-url');
    if (startUrlEl) {
        startUrlEl.textContent = '-';
        startUrlEl.removeAttribute('href');
    }

    setTextContent('job-created-at', '-');
    setTextContent('job-updated-at', '-');
    setTextContent('job-external-count', '-');

    const progressFillEl = el('job-progress-fill');
    const progressTextEl = el('job-progress-text');
    if (progressFillEl) progressFillEl.style.width = '0%';
    if (progressTextEl) progressTextEl.textContent = '0%';

    const stats = [
        'stat-total', 'stat-completed', 'stat-warning', 'stat-pending', 'stat-skipped', 'stat-failed'
    ];
    stats.forEach(id => setTextContent(id, '-'));

    clearResultsSummaryUI();
    clearInternalSummaryUI();

    const extContainer = el('results-container');
    if (extContainer) {
        delete extContainer.dataset.renderedGroup;
        extContainer.replaceChildren();
        const skeleton = document.createElement('div');
        skeleton.className = 'skeleton';
        skeleton.style.height = '200px';
        skeleton.style.borderRadius = '0.5rem';
        extContainer.appendChild(skeleton);
    }

    const intContainer = el('internal-results-container');
    if (intContainer) {
        delete intContainer.dataset.renderedInternalGroup;
        intContainer.replaceChildren();
        const skeleton = document.createElement('div');
        skeleton.className = 'skeleton';
        skeleton.style.height = '200px';
        skeleton.style.borderRadius = '0.5rem';
        intContainer.appendChild(skeleton);
    }

    ['btn-start-job', 'btn-resume-job', 'btn-pause-job', 'btn-goto-compare', 'btn-transfer-job', 'btn-reset-job', 'btn-retry-failed-job'].forEach(id => {
        const btn = el(id);
        if (btn) btn.style.display = 'none';
    });
}

/**
 * 初始化任務詳情頁面邏輯
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>} 無回傳值
 */

function updateExtToolbarButtons() {
    const btnReprobe = document.getElementById('btn-ext-reprobe-selected');
    const btnExport = document.getElementById('btn-ext-export-selected');
    if (_extSelectedUrls.size > 0) {
        if (btnReprobe) {
            btnReprobe.style.display = 'inline-flex';
            btnReprobe.textContent = `重新探測 (${_extSelectedUrls.size})`;
        }
        if (btnExport) {
            btnExport.style.display = 'inline-flex';
            btnExport.textContent = `匯出選取 (${_extSelectedUrls.size})`;
        }
    } else {
        if (btnReprobe) btnReprobe.style.display = 'none';
        if (btnExport) btnExport.style.display = 'none';
    }
}

function updateIntToolbarButtons() {
    const btnReprobe = document.getElementById('btn-int-reprobe-selected');
    const btnExport = document.getElementById('btn-int-export-selected');
    if (_intSelectedUrls.size > 0) {
        if (btnReprobe) {
            btnReprobe.style.display = 'inline-flex';
            btnReprobe.textContent = `重新探測 (${_intSelectedUrls.size})`;
        }
        if (btnExport) {
            btnExport.style.display = 'inline-flex';
            btnExport.textContent = `匯出選取 (${_intSelectedUrls.size})`;
        }
    } else {
        if (btnReprobe) btnReprobe.style.display = 'none';
        if (btnExport) btnExport.style.display = 'none';
    }
}

export async function initJobDetailPage(jobId) {
    _currentJobId = jobId;
    stopSseStream();

    _currentFilter = null;

    _currentTab = 'external';
    _internalCurrentPage = 1;
    _internalGroupBy = 'none';
    _internalFilter = null;
    // 初始化時載入儲存在 localStorage 的排除清單
    _currentExclude = localStorage.getItem('link-checker-exclude-domains') || '';
    _currentExcludeEnabled = localStorage.getItem('link-checker-exclude-enabled') !== 'false';

    _currentGroupBy = 'none';
    _currentPage = 1;
    _detailSort = { key: null, asc: true };
    _detailColFilters = {};
    _internalSort = { key: null, asc: true };
    _internalColFilters = {};

    // 切換任務時，強制清除 Summary 快取
    _extSummaryCache = { key: null, data: null };
    _intSummaryCache = { key: null, data: null };

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

    // 清除舊畫面避免閃爍
    clearJobDetailUI();

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
 */
export function destroyJobDetailPage() {
    stopSseStream();
}

/**
 * 重新載入任務詳情
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>}
 */
async function refreshJobDetail(jobId) {
    try {
        const job = await api.get(`/api/jobs/${jobId}`);
        if (jobId !== _currentJobId) return;
        renderJobInfo(job);

        const isActuallyRunning = ['running', 'starting'].includes(job.status) || job.is_running;
        if (isActuallyRunning) {
            if (!_eventSource) {
                startSseStream(jobId);
            }
        } else {
            stopSseStream();
        }
    } catch (err) {
        toast.error('無法取得任務資訊：' + err.message);
        stopSseStream();
    }
}

/**
 * 載入內部連結結果頁面
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>}
 */
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

    const reqId = ++_currentIntReqId;

    try {
        const params = { group_by: _internalGroupBy, page: _internalCurrentPage, page_size: 50, sort_by: _internalSort.key || undefined, sort_asc: _internalSort.asc };
        if (_internalFilter && _internalFilter !== 'all') params.filter = _internalFilter;
        const activeFilters = Object.fromEntries(Object.entries(_internalColFilters).filter(([_, v]) => v !== ''));
        if (Object.keys(activeFilters).length > 0) {
            params.col_filters = JSON.stringify(activeFilters);
        }
        const res = await api.get(`/api/jobs/${jobId}/internal-results`, params);
        if (jobId !== _currentJobId || reqId !== _currentIntReqId) return;
        if (tableEl) tableEl.style.opacity = '1';
        renderInternalResultsTable(res, containerEl);
        renderInternalPagination(res, jobId);
    } catch (err) {
        if (jobId !== _currentJobId || reqId !== _currentIntReqId) return;
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

/**
 * 渲染內部連結診斷摘要卡片
 * @param {Object} summary - 統計摘要資料
 * @returns {void}
 */
function renderInternalSummary(summary) {
    setTextContent('int-summary-total', summary.total ?? 0);
    setTextContent('int-summary-server-error', summary.server_error ?? 0);
    setTextContent('int-summary-connection-error', summary.connection_error ?? 0);
    setTextContent('int-summary-timeout', summary.timeout ?? 0);
    setTextContent('int-summary-not-found', summary.not_found ?? 0);
    setTextContent('int-summary-other-error', summary.other_error ?? 0);
    setTextContent('int-summary-warning', summary.warning ?? 0);
    setTextContent('int-summary-blocked', summary.blocked ?? 0);
    setTextContent('int-summary-insecure', summary.insecure ?? 0);
}

/**
 * 渲染內部連結診斷結果表格架構
 * @param {Object} res - API 回傳的結果物件
 * @param {HTMLElement} containerEl - 表格容器元素
 * @returns {void}
 */
function renderInternalResultsTable(res, containerEl) {
    _internalResultItems = res.items || [];
    _intSelectedUrls.clear();
    updateIntToolbarButtons();

    if (_internalResultItems.length === 0) {
        containerEl.replaceChildren();
        const emptyStateEl = document.createElement('div');
        emptyStateEl.className = 'empty-state';
        const titleEl = document.createElement('div');
        titleEl.className = 'empty-state-title';
        titleEl.textContent = '太棒了！';
        const descEl = document.createElement('div');
        descEl.className = 'empty-state-desc';
        descEl.textContent = '您的網站內部沒有這類問題。';
        emptyStateEl.appendChild(titleEl);
        emptyStateEl.appendChild(descEl);
        containerEl.appendChild(emptyStateEl);
        return;
    }

    const isJobActive = _currentJobStatus === 'running' || _currentJobStatus === 'starting';
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
            { label: 'HTTPS', key: 'is_secure' },
            { label: 'HTTP 狀態', key: 'HTTP Status Code' },
            { label: '錯誤訊息', key: 'Error Message' }
        ];
    }

    if (!isJobActive && _internalGroupBy === 'none') {
        headers.unshift({ label: '', key: '_select', sortable: false, filterable: false });
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

            if (h.key === '_select') {
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.id = 'int-select-all';
                cb.style.cursor = 'pointer';
                cb.addEventListener('change', (e) => {
                    const isChecked = e.target.checked;
                    if (_internalGroupBy === 'none') {
                        _internalResultItems.forEach(item => {
                            const url = item.URL || item.url;
                            if (isChecked) _intSelectedUrls.add(url);
                            else _intSelectedUrls.delete(url);
                        });
                    } else if (_internalGroupBy === 'source') {
                        _internalResultItems.forEach(item => {
                            if (item.targets) {
                                item.targets.forEach(t => {
                                    if (isChecked) _intSelectedUrls.add(t.url);
                                    else _intSelectedUrls.delete(t.url);
                                });
                            }
                        });
                    }
                    renderInternalTbody(tableEl);
                    updateIntToolbarButtons();
                });
                headerTop.appendChild(cb);
            } else {
                const label = document.createElement('span');
                label.textContent = h.label;
                headerTop.appendChild(label);
            }

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

/**
 * 取得內部連結狀態對應的顏色類別
 * @param {number|string} code - HTTP 狀態碼
 * @param {string} errMsg - 錯誤訊息
 * @returns {string} 顏色類別名稱
 */
function getInternalStatusColorClass(code, errMsg) {
    if (!code || code === '-' || code === 'Error' || code === 'DNS Failed') {
        const msg = String(errMsg || '').toLowerCase();
        if (msg.includes('timeout') || msg.includes('timed out')) return 'text-info';
        return 'text-brand';
    }

    const msg = String(errMsg || '').toLowerCase();
    if (msg.includes('截斷')) return 'text-warning';

    const c = parseInt(code, 10);
    if (c === 401 || c === 403) return 'text-muted';
    if (c === 404 || c === 410) return 'text-warning';
    if (c >= 500 && c < 600) return 'text-danger';
    return 'text-secondary';
}

/**
 * 取得內部連結狀態對應的標籤類別
 * @param {number|string} code - HTTP 狀態碼
 * @param {string} errMsg - 錯誤訊息
 * @returns {string} 標籤類別名稱
 */
function getInternalBadgeClass(code, errMsg) {
    if (!code || code === '-' || code === 'Error' || code === 'DNS Failed') {
        const msg = String(errMsg || '').toLowerCase();
        if (msg.includes('timeout') || msg.includes('timed out')) return 'badge-info';
        return 'badge-admin';
    }

    const msg = String(errMsg || '').toLowerCase();
    if (msg.includes('截斷')) return 'badge-warning';

    const c = parseInt(code, 10);
    if (c === 401 || c === 403) return 'badge-pending';
    if (c === 404 || c === 410) return 'badge-warning';
    if (c >= 500 && c < 600) return 'badge-danger';
    return 'badge-secondary';
}

/**
 * 渲染內部連結診斷表格內容
 * @param {HTMLTableElement} tableEl - 表格元素
 * @returns {void}
 */
function renderInternalTbody(tableEl) {
    let data = [..._internalResultItems];

    let tbody = tableEl.querySelector('tbody');
    tbody.replaceChildren();

    const isJobActive = _currentJobStatus === 'running' || _currentJobStatus === 'starting';

    data.forEach(item => {
        const tr = document.createElement('tr');
        const isIntSelectable = _internalGroupBy === 'none';
        const url = item.URL || item.url;

        if (isIntSelectable && !isJobActive) {
            const tdCb = document.createElement('td');
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.style.cursor = 'pointer';
            cb.checked = _intSelectedUrls.has(url);
            cb.addEventListener('change', (e) => {
                if (e.target.checked) _intSelectedUrls.add(url);
                else _intSelectedUrls.delete(url);
                updateIntToolbarButtons();
                const selectAllCb = document.getElementById('int-select-all');
                if (selectAllCb && _internalResultItems.length > 0) {
                    const allSelected = _internalResultItems.every(i => _intSelectedUrls.has(i.URL || i.url));
                    const someSelected = _internalResultItems.some(i => _intSelectedUrls.has(i.URL || i.url));
                    selectAllCb.checked = allSelected;
                    selectAllCb.indeterminate = someSelected && !allSelected;
                }
            });
            tdCb.appendChild(cb);
            tr.appendChild(tdCb);
        }

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

            const tdSecure = document.createElement('td');
            const spanSecure = document.createElement('span');
            spanSecure.className = item.is_secure ? 'text-success' : 'text-danger';
            spanSecure.textContent = item.is_secure ? '✓' : '✗';
            tdSecure.appendChild(spanSecure);
            tr.appendChild(tdSecure);

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

    const selectAllCb = document.getElementById('int-select-all');
    if (selectAllCb && _internalResultItems.length > 0) {
        let allUrls = [];
        if (_internalGroupBy === 'none') {
            allUrls = _internalResultItems.map(i => i.URL || i.url);
        } else if (_internalGroupBy === 'source') {
            _internalResultItems.forEach(i => {
                if (i.targets) allUrls.push(...i.targets.map(t => t.url));
            });
        }
        
        if (allUrls.length > 0) {
            const allSelected = allUrls.every(u => _intSelectedUrls.has(u));
            const someSelected = allUrls.some(u => _intSelectedUrls.has(u));
            selectAllCb.checked = allSelected;
            selectAllCb.indeterminate = someSelected && !allSelected;
        } else {
            selectAllCb.checked = false;
            selectAllCb.indeterminate = false;
        }
    } else if (selectAllCb) {
        selectAllCb.checked = false;
        selectAllCb.indeterminate = false;
    }
}

/**
 * 渲染內部連結結果分頁列
 * @param {Object} res - API 回傳的分頁結果物件
 * @param {string} jobId - 任務 ID
 * @returns {void}
 */
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

/**
 * 渲染任務基本資訊與進度
 * @param {Object} job - 任務詳細資料
 * @returns {void}
 */
function renderJobInfo(job) {
    const el = (id) => document.getElementById(id);

    const isPausing = job.status === 'paused' && job.is_running;
    const isActuallyRunning = ['running', 'starting'].includes(job.status) || (job.is_running && !['completed', 'error'].includes(job.status));

    _currentJobConfig = job.config;

    const previousJobStatus = _currentJobStatus;
    _currentJobStatus = job.status;

    // 若任務剛完成或暫停，觸發重新載入表格以顯示操作按鈕 (CheckBoxes)
    // 同時使 Summary 快取失效，因為資料已更新
    if (previousJobStatus && ['running', 'starting'].includes(previousJobStatus) && !['running', 'starting'].includes(_currentJobStatus)) {
        _extSummaryCache = { key: null, data: null };
        _intSummaryCache = { key: null, data: null };
        setTimeout(() => loadResults(_currentJobId), 100);
    }

    const statusEl = el('job-status');
    if (statusEl) {
        let displayStatus = job.status;
        if (['completed', 'error'].includes(job.status)) {
            displayStatus = job.status;
        } else if (isPausing) {
            displayStatus = 'paused';
        } else if (job.status === 'starting') {
            displayStatus = 'starting';
        } else if (isActuallyRunning) {
            displayStatus = 'running';
        }

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

    const canStart = ['pending', 'paused', 'error'].includes(job.status) && !job.is_running;
    const canPause = (isActuallyRunning && !isPausing) || job.status === 'queued';
    const canCompare = job.status === 'completed';
    const canTransfer = !isActuallyRunning;
    const canReset = ['completed', 'error', 'paused'].includes(job.status) && !job.is_running;
    const canRetry = job.status === 'completed' && !job.is_running;

    toggleDisplay('btn-start-job', canStart);
    toggleDisplay('btn-resume-job', false);
    toggleDisplay('btn-pause-job', canPause);
    toggleDisplay('btn-goto-compare', canCompare);
    toggleDisplay('btn-transfer-job', canTransfer);
    toggleDisplay('btn-duplicate-job', true);
    toggleDisplay('btn-reset-job', canReset);
    toggleDisplay('btn-retry-failed-job', canRetry);
}

/**
 * 綁定操作任務的控制按鈕事件
 * @returns {void}
 */
function bindControlButtons() {
    bindBtn('btn-start-job', async () => {
        const confirmed = await showConfirm('啟動任務', '確定要開始（或接續）執行此爬蟲任務嗎？', '啟動');
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
        // 資料已全面重置，使快取失效
        _extSummaryCache = { key: null, data: null };
        _intSummaryCache = { key: null, data: null };
        await loadResults(_currentJobId);
    });

    bindBtn('btn-retry-failed-job', async () => {
        const confirmed = await showConfirm('重試失敗項目', '確定要將爬取失敗的內部網頁，以及包含無效外連的網頁重新加入佇列並重試嗎？\n（系統將自動清除失效的外部連結並重新發起探測）', '確定重試');
        if (!confirmed) return;
        await api.post(`/api/jobs/${_currentJobId}/retry-failed`);
        toast.success('失敗項目已重置！您可以點擊啟動繼續任務。');
        await refreshJobDetail(_currentJobId);
        // 資料已變動，使快取失效
        _extSummaryCache = { key: null, data: null };
        _intSummaryCache = { key: null, data: null };
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
                        { label: '忽略路徑規則', value: el => formatList(c.ignore_regexes, el) },
                        { label: '忽略副檔名', value: el => formatList(c.ignore_extensions, el), valStyle: { maxHeight: '160px', overflowY: 'auto', paddingRight: '4px' } },
                        { label: '社群與反爬蟲', value: el => formatList(c.social_domains, el) },
                        { label: '自簽憑證豁免', value: el => formatList(c.ssl_exempt_domains, el) },
                        {
                            label: '特定網域延遲', value: el => formatList(
                                c.domain_delays ? Object.entries(c.domain_delays).map(([k, v]) => `${k}: ${v}s`) : [], el
                            )
                        },
                        { label: '自訂 User-Agent', value: c.user_agent || '系統預設 (自動輪替)', valClass: 'text-xs text-muted' },
                        c.proxy_url !== undefined ? { label: '代理伺服器', value: c.proxy_url || '-', valClass: 'font-mono text-xs', valStyle: { wordBreak: 'break-all' } } : null
                    ]));

                    wrapper.appendChild(createSection('⚙️ 資源與限制', [
                        { label: '總連線逾時', value: `${c.timeout ?? '-'} 秒` },
                        { label: 'TCP 連線逾時', value: `${c.connect_timeout ?? '-'} 秒` },
                        { label: '外連探測逾時', value: `${c.external_check_timeout ?? '-'} 秒` },
                        { label: '請求延遲', value: `${c.delay ?? '-'} 秒` },
                        { label: '失敗重試次數', value: `${c.retries ?? '-'} 次` },
                        { label: '最大爬取深度', value: c.max_depth === null ? '不限制' : c.max_depth },
                        { label: '最大抓取頁數', value: c.max_pages === null ? '不限制' : c.max_pages }
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

/**
 * 載入外部結果主邏輯
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>}
 */
async function loadExternalResults(jobId) {
    const containerEl = document.getElementById('results-container');
    if (!containerEl) return;

    // 計算此次 Summary 的快取 key（由影響 Summary 結果的參數組成）
    const excludeVal = (_currentExcludeEnabled && _currentExclude) ? _currentExclude : '';
    const summaryKey = `${excludeVal}|${_currentGroupBy}`;

    if (_extSummaryCache.key === summaryKey && _extSummaryCache.data) {
        // 快取命中，直接渲染，不發送 API 請求
        renderResultsSummary(_extSummaryCache.data);
    } else {
        // 快取未命中或已失效，發送 API 請求
        const reqId = ++_currentExtSummaryReqId;
        try {
            const params = {};
            if (excludeVal) params.exclude = excludeVal;
            if (_currentGroupBy && _currentGroupBy !== 'none') params.group_by = _currentGroupBy;
            const summary = await api.get(`/api/jobs/${jobId}/results/summary`, Object.keys(params).length > 0 ? params : undefined);
            if (jobId !== _currentJobId || reqId !== _currentExtSummaryReqId) return;
            _extSummaryCache = { key: summaryKey, data: summary };
            renderResultsSummary(summary);
        } catch (_) { /* 忽略 */ }
    }

    // 統計資料載入後，再載入結果列表
    await loadResultsPage(jobId);
}

/**
 * 載入內部結果主邏輯
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>}
 */
async function loadInternalResults(jobId) {
    const containerEl = document.getElementById('internal-results-container');
    if (!containerEl) return;

    // 計算此次 Summary 的快取 key（由影響 Summary 結果的參數組成）
    const summaryKey = _internalGroupBy;

    if (_intSummaryCache.key === summaryKey && _intSummaryCache.data) {
        // 快取命中，直接渲染，不發送 API 請求
        renderInternalSummary(_intSummaryCache.data);
    } else {
        // 快取未命中或已失效，發送 API 請求
        const reqId = ++_currentIntSummaryReqId;
        try {
            const params = {};
            if (_internalGroupBy && _internalGroupBy !== 'none') params.group_by = _internalGroupBy;
            const summary = await api.get(`/api/jobs/${jobId}/internal-results/summary`, Object.keys(params).length > 0 ? params : undefined);
            if (jobId !== _currentJobId || reqId !== _currentIntSummaryReqId) return;
            _intSummaryCache = { key: summaryKey, data: summary };
            renderInternalSummary(summary);
        } catch (_) { /* 忽略 */ }
    }

    // 統計資料載入後，再載入結果列表
    await loadInternalResultsPage(jobId);
}

/**
 * 依據當前 Tab 載入對應的結果主邏輯
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>}
 */
async function loadResults(jobId) {
    if (_currentTab === 'external') {
        await loadExternalResults(jobId);
    } else {
        await loadInternalResults(jobId);
    }
}

/**
 * 載入外部結果頁面
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>}
 */
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

    const reqId = ++_currentExtReqId;

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
        if (jobId !== _currentJobId || reqId !== _currentExtReqId) return;
        if (tableEl) tableEl.style.opacity = '1';
        renderResultsTable(res, containerEl);
        renderPagination(res, jobId);
    } catch (err) {
        if (jobId !== _currentJobId || reqId !== _currentExtReqId) return;
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

/**
 * 渲染外部結果統計摘要卡片
 * @param {Object} summary - 統計摘要資料
 * @returns {void}
 */
function renderResultsSummary(summary) {
    setTextContent('summary-total', summary.total_external_links ?? 0);
    setTextContent('summary-healthy', summary.healthy_count ?? 0);
    setTextContent('summary-dns-failed', summary.dns_failed_count ?? 0);
    setTextContent('summary-not-found', summary.not_found_count ?? 0);
    setTextContent('summary-server-error', summary.server_error_count ?? 0);
    setTextContent('summary-connection-error', summary.connection_error_count ?? 0);
    setTextContent('summary-other-error', summary.other_error_count ?? 0);
    setTextContent('summary-blocked', summary.blocked_count ?? 0);
    setTextContent('summary-insecure', summary.insecure_count ?? 0);
}

/**
 * 渲染外部結果表格架構
 * @param {Object} res - API 回傳的結果物件
 * @param {HTMLElement} containerEl - 表格容器元素
 * @returns {void}
 */
function renderResultsTable(res, containerEl) {
    _currentResultItems = res.items || [];
    _extSelectedUrls.clear();
    updateExtToolbarButtons();

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

    const isJobActive = _currentJobStatus === 'running' || _currentJobStatus === 'starting';

    if (isGroupTarget) {
        _currentDetailHeaders = [{ label: '目標 URL', key: 'target_url' }, { label: 'IP 位址', key: 'ip_address' }, { label: 'HTTPS', key: 'is_secure' }, { label: 'HTTP 狀態', key: 'http_status_code' }, { label: '來源數', key: 'occurrence_count' }, { label: '錯誤訊息', key: 'error_message' }, { label: '來源頁面', key: 'source_urls', sortable: false, filterable: false }];
    } else if (isGroupSource) {
        _currentDetailHeaders = [{ label: '來源頁面', key: 'source_url' }, { label: '外連數量', key: 'occurrence_count' }, { label: '目標 URL', key: 'targets', sortable: false, filterable: false }];
    } else if (isGroupDomain) {
        _currentDetailHeaders = [{ label: '外部網域', key: 'domain' }, { label: '來源數', key: 'occurrence_count' }, { label: '不重複網址數', key: 'unique_urls_count' }, { label: '目標 URL', key: 'unique_urls', sortable: false, filterable: false }, { label: '來源頁面', key: 'source_urls', sortable: false, filterable: false }];
    } else {
        _currentDetailHeaders = [{ label: '來源頁面', key: 'source_url' }, { label: '目標 URL', key: 'target_url' }, { label: 'IP 位址', key: 'ip_address' }, { label: 'HTTPS', key: 'is_secure' }, { label: 'HTTP 狀態', key: 'http_status_code' }, { label: '錯誤訊息', key: 'error_message' }];
    }

    if (!isJobActive && (isGroupTarget || isGroupSource)) {
        _currentDetailHeaders.unshift({ label: '', key: '_select', sortable: false, filterable: false });
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

            if (h.key === '_select') {
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.id = 'ext-select-all';
                cb.style.cursor = 'pointer';
                cb.addEventListener('change', (e) => {
                    const isChecked = e.target.checked;
                    if (_currentTab === 'external') {
                        _currentResultItems.forEach(item => {
                            let urlsToSelect = [];
                            if (_currentGroupBy === 'target') urlsToSelect.push(item.target_url);
                            else if (_currentGroupBy === 'source') {
                                if (item.source_url) urlsToSelect.push(item.source_url);
                            }
                            urlsToSelect.forEach(u => {
                                if (isChecked) _extSelectedUrls.add(u);
                                else _extSelectedUrls.delete(u);
                            });
                        });
                        renderResultsTbody(tableEl);
                        updateExtToolbarButtons();
                    }
                });
                headerTop.appendChild(cb);
            } else {
                const label = document.createElement('span');
                label.textContent = h.label;
                headerTop.appendChild(label);
            }

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

/**
 * 渲染外部結果表格內容
 * @param {HTMLTableElement} tableEl - 表格元素
 * @returns {void}
 */
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

    const isJobActive = _currentJobStatus === 'running' || _currentJobStatus === 'starting';

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

            if (!isJobActive) {
                const tdCb = document.createElement('td');
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.style.cursor = 'pointer';
                const url = item.source_url;
                cb.checked = _extSelectedUrls.has(url);

                cb.addEventListener('change', (e) => {
                    if (e.target.checked) _extSelectedUrls.add(url);
                    else _extSelectedUrls.delete(url);
                    updateExtToolbarButtons();
                    
                    const selectAllCb = document.getElementById('ext-select-all');
                    if (selectAllCb && _currentResultItems.length > 0) {
                        const allSelected = _currentResultItems.every(i => _extSelectedUrls.has(i.source_url));
                        const someSelected = _currentResultItems.some(i => _extSelectedUrls.has(i.source_url));
                        selectAllCb.checked = allSelected;
                        selectAllCb.indeterminate = someSelected && !allSelected;
                    }
                });
                tdCb.appendChild(cb);
                tr.appendChild(tdCb);
            }

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

        const isSelectable = _currentGroupBy === 'target';
        const targetUrl = item.target_url;
        if (isSelectable && !isJobActive) {
            const tdCb = document.createElement('td');
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.style.cursor = 'pointer';
            cb.checked = _extSelectedUrls.has(targetUrl);
            cb.addEventListener('change', (e) => {
                if (e.target.checked) _extSelectedUrls.add(targetUrl);
                else _extSelectedUrls.delete(targetUrl);
                updateExtToolbarButtons();
                const selectAllCb = document.getElementById('ext-select-all');
                if (selectAllCb && _currentResultItems.length > 0) {
                    const allSelected = _currentResultItems.every(i => _extSelectedUrls.has(i.target_url));
                    const someSelected = _currentResultItems.some(i => _extSelectedUrls.has(i.target_url));
                    selectAllCb.checked = allSelected;
                    selectAllCb.indeterminate = someSelected && !allSelected;
                }
            });
            tdCb.appendChild(cb);
            tr.appendChild(tdCb);
        }

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

    const selectAllCb = document.getElementById('ext-select-all');
    if (selectAllCb && _currentResultItems.length > 0) {
        let allUrls = [];
        if (_currentGroupBy === 'target') {
            allUrls = _currentResultItems.map(i => i.target_url);
        } else if (_currentGroupBy === 'source') {
            allUrls = _currentResultItems.map(i => i.source_url);
        }

        if (allUrls.length > 0) {
            const allSelected = allUrls.every(u => _extSelectedUrls.has(u));
            const someSelected = allUrls.some(u => _extSelectedUrls.has(u));
            selectAllCb.checked = allSelected;
            selectAllCb.indeterminate = someSelected && !allSelected;
        } else {
            selectAllCb.checked = false;
            selectAllCb.indeterminate = false;
        }
    } else if (selectAllCb) {
        selectAllCb.checked = false;
        selectAllCb.indeterminate = false;
    }
}

/**
 * 渲染外部結果分頁列
 * @param {Object} res - API 回傳的分頁結果物件
 * @param {string} jobId - 任務 ID
 * @returns {void}
 */
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

/**
 * 綁定結果表格篩選與排序控制項
 * @returns {void}
 */
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


    // === 局部操作綁定 ===
    const btnExtReprobe = document.getElementById('btn-ext-reprobe-selected');
    if (btnExtReprobe) {
        btnExtReprobe.addEventListener('click', async () => {
            if (_extSelectedUrls.size === 0) return;
            const isSourceGroup = _currentGroupBy === 'source';
            const typeLabel = isSourceGroup ? '關聯的自家網頁（內部連結）' : '外部連結';
            const ok = await showConfirm('重新探測', `確定要重新探測選取的 ${_extSelectedUrls.size} 個${typeLabel}嗎？`);
            if (!ok) return;
            try {
                const linkType = isSourceGroup ? 'internal' : 'external';
                const res = await api.post(`/api/jobs/${_currentJobId}/reprobe`, { link_type: linkType, urls: Array.from(_extSelectedUrls) });
                if (isSourceGroup) {
                    toast.success('已將關聯的自家網頁加入重新探測佇列');
                    // 內部資料異動，使快取失效後重新載入
                    _intSummaryCache = { key: null, data: null };
                    loadInternalResults(_currentJobId);
                } else {
                    toast.success('已將選取的外部連結設為待探測');
                }
                _extSelectedUrls.clear();
                updateExtToolbarButtons();
                // 外部資料異動，使快取失效後重新載入
                _extSummaryCache = { key: null, data: null };
                loadExternalResults(_currentJobId);
                refreshJobDetail(_currentJobId);
            } catch (err) {
                toast.error(err.message || '探測失敗');
            }
        });
    }

    const btnExtExport = document.getElementById('btn-ext-export-selected');
    if (btnExtExport) {
        btnExtExport.addEventListener('click', async () => {
            if (_extSelectedUrls.size === 0) return;
            try {
                await api.download(`/api/jobs/${_currentJobId}/export/partial`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ link_type: 'external', urls: Array.from(_extSelectedUrls) })
                });
                toast.success('匯出成功');
            } catch (err) {
                toast.error('匯出失敗');
            }
        });
    }

    const btnIntReprobe = document.getElementById('btn-int-reprobe-selected');
    if (btnIntReprobe) {
        btnIntReprobe.addEventListener('click', async () => {
            if (_intSelectedUrls.size === 0) return;
            const ok = await showConfirm('重新探測', `確定要將選取的 ${_intSelectedUrls.size} 個內部連結重新探測嗎？`);
            if (!ok) return;
            try {
                const res = await api.post(`/api/jobs/${_currentJobId}/reprobe`, { link_type: 'internal', urls: Array.from(_intSelectedUrls) });
                toast.success(res.message || '重置成功');
                _intSelectedUrls.clear();
                updateIntToolbarButtons();
                // 內部資料異動，使快取失效後重新載入
                _intSummaryCache = { key: null, data: null };
                loadInternalResults(_currentJobId);
                refreshJobDetail(_currentJobId);
            } catch (err) {
                toast.error(err.message || '重置失敗');
            }
        });
    }

    const btnIntExport = document.getElementById('btn-int-export-selected');
    if (btnIntExport) {
        btnIntExport.addEventListener('click', async () => {
            if (_intSelectedUrls.size === 0) return;
            try {
                await api.download(`/api/jobs/${_currentJobId}/export/partial`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ link_type: 'internal', urls: Array.from(_intSelectedUrls) })
                });
                toast.success('匯出成功');
            } catch (err) {
                toast.error('匯出失敗');
            }
        });
    }

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
                localStorage.setItem('link-checker-exclude-enabled', _currentExcludeEnabled);
            }

            const lines = excludeTextareaInput.value.split('\n').map(s => s.trim()).filter(Boolean);
            _currentExclude = lines.join(',');
            localStorage.setItem('link-checker-exclude-domains', _currentExclude);

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
            groupSelectEl.disabled = true;
            try {
                _currentGroupBy = groupSelectEl.value;
                _currentPage = 1;
                _detailSort = { key: null, asc: true };
                _detailColFilters = {};
                await loadResults(_currentJobId);
            } finally {
                groupSelectEl.disabled = false;
            }
        });
    }

    const internalGroupSelectEl = document.getElementById('internal-results-group-select');
    if (internalGroupSelectEl) {
        internalGroupSelectEl.addEventListener('change', async () => {
            internalGroupSelectEl.disabled = true;
            try {
                _internalGroupBy = internalGroupSelectEl.value;
                _internalCurrentPage = 1;
                _internalSort = { key: null, asc: true };
                _internalColFilters = {};
                await loadInternalResults(_currentJobId);
            } finally {
                internalGroupSelectEl.disabled = false;
            }
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

/**
 * 設定指定元素的文字內容
 * @param {string} id - 元素 ID
 * @param {string|number} value - 欲設定的文字值
 * @returns {void}
 */
function setTextContent(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? '-';
}

/**
 * 切換元素的顯示狀態
 * @param {string} id - 元素 ID
 * @param {boolean} show - 是否顯示
 * @returns {void}
 */
function toggleDisplay(id, show) {
    const el = document.getElementById(id);
    if (el) el.style.display = show ? '' : 'none';
}

/**
 * 綁定按鈕點擊事件，處理讀取狀態與錯誤捕捉
 * @param {string} id - 按鈕 ID
 * @param {Function} handler - 處理非同步邏輯的函式
 * @returns {void}
 */
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
