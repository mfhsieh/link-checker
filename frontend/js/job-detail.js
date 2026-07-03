
// ── 全域事件監聽 (Top-level) ──────────────────────────────────────────

// 任務詳情返回列表按鈕 (使用 Event Delegation)
document.addEventListener('click', (e) => {
    if (e.target.closest('#btn-back-jobs')) {
        window.location.hash = '#/jobs';
    }

    // Config modal close buttons
    if (e.target.closest('#job-config-close') || e.target.closest('#job-config-ok')) {
        const configModalEl = document.getElementById('job-config-modal');
        if (configModalEl) configModalEl.style.display = 'none';
    }
});


import * as api from './api.js';
import { toast } from './toast.js';

let _eventSource = null;
let _currentJobId = null;
let _currentJobStatus = null;

let _currentFilter = null;
let _currentExclude = '';
let _currentExcludeEnabled = true;
let _currentGroupBy = 'none';
let _currentPage = 1;
let _eventsBound = false;
let _currentTab = 'external';

let _internalCurrentPage = 1;
let _internalFilter = null;
let _internalGroupBy = 'none';

let _detailSort = { key: null, asc: true };
let _internalSort = { key: null, asc: true };

let _detailColFilters = {};
let _internalColFilters = {};

let _currentExtReqId = 0;
let _currentIntReqId = 0;
let _currentExtSummaryReqId = 0;
let _currentIntSummaryReqId = 0;

let _extFilterTimeout = null;
let _intFilterTimeout = null;

let _extSummaryCache = { key: null, data: null };
let _intSummaryCache = { key: null, data: null };

let _extSelectedUrls = new Set();
let _intSelectedUrls = new Set();

// Components references
const jobControls = document.getElementById('job-controls');
const jobStatusCard = document.getElementById('job-status-card');
const jobProgressCard = document.getElementById('job-progress');
const jobExtStats = document.getElementById('job-ext-stats');
const jobIntStats = document.getElementById('job-int-stats');
const extDataTable = document.getElementById('ext-data-table');
const intDataTable = document.getElementById('int-data-table');

function startSseStream(jobId) {
    if (_eventSource) _eventSource.close();
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
}

function stopSseStream() {
    if (_eventSource) {
        _eventSource.close();
        _eventSource = null;
    }
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

function clearJobDetailUI() {
    document.getElementById('job-status').textContent = '載入中...';
    document.getElementById('job-status').className = 'badge badge-pending';
    if (jobStatusCard) jobStatusCard.job = null;
    if (jobProgressCard) jobProgressCard.job = null;
    if (jobControls) jobControls.job = null;
}

export async function initJobDetailPage(jobId) {
    _currentJobId = jobId;
    stopSseStream();

    _currentFilter = null;
    _currentTab = 'external';
    _internalCurrentPage = 1;
    _internalGroupBy = 'none';
    _internalFilter = null;
    _currentExclude = localStorage.getItem('link-checker-exclude-domains') || '';
    _currentExcludeEnabled = localStorage.getItem('link-checker-exclude-enabled') !== 'false';
    _currentGroupBy = 'none';
    _currentPage = 1;
    _detailSort = { key: null, asc: true };
    _internalSort = { key: null, asc: true };

    _extSummaryCache = { key: null, data: null };
    _intSummaryCache = { key: null, data: null };

    const groupSelectEl = document.getElementById('results-group-select');
    if (groupSelectEl) groupSelectEl.value = 'none';
    const intGroupSelectEl = document.getElementById('internal-results-group-select');
    if (intGroupSelectEl) intGroupSelectEl.value = 'none';

    document.querySelectorAll('#job-detail-tabs .tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === 'external');
    });
    document.getElementById('tab-content-external').style.display = 'block';
    document.getElementById('tab-content-internal').style.display = 'none';

    clearJobDetailUI();

    if (!_eventsBound) {
        bindWebComponentEvents();
        _eventsBound = true;
    }

    await refreshJobDetail(jobId);
    await loadResults(jobId);
}

export function destroyJobDetailPage() {
    stopSseStream();
}

async function refreshJobDetail(jobId) {
    try {
        const job = await api.get(`/api/jobs/${jobId}`);
        if (jobId !== _currentJobId) return;
        renderJobInfo(job);

        const isActuallyRunning = ['running', 'starting'].includes(job.status) || job.is_running;
        if (isActuallyRunning) {
            if (!_eventSource) startSseStream(jobId);
        } else {
            stopSseStream();
        }
    } catch (err) {
        toast.error('無法取得任務資訊：' + err.message);
        stopSseStream();
    }
}

function renderJobInfo(job) {
    _currentJobStatus = job.status;
    const isJobRunning = job.is_running;

    const statusEl = document.getElementById('job-status');
    const idEl = document.getElementById('job-id-display');

    let statusText = api.formatStatus(job.status);
    let statusClass = `badge-${job.status}`;

    statusEl.textContent = statusText;
    statusEl.className = `badge ${statusClass}`;
    idEl.textContent = job.id;

    if (jobStatusCard) jobStatusCard.job = job;
    if (jobProgressCard) jobProgressCard.job = job;
    if (jobControls) jobControls.job = job;

    if (['completed', 'error', 'paused'].includes(job.status) && !isJobRunning) {
        _extSummaryCache.key = null;
        _intSummaryCache.key = null;
        loadResults(job.id);
    }
}

async function loadResults(jobId) {
    await Promise.all([
        loadExternalSummary(jobId),
        loadExternalResultsPage(jobId),
        loadInternalSummary(jobId),
        loadInternalResultsPage(jobId)
    ]);
}

async function loadExternalSummary(jobId) {
    const reqId = ++_currentExtSummaryReqId;
    const cacheKey = `${_currentExcludeEnabled ? _currentExclude : ''}|${_currentGroupBy}`;
    if (_extSummaryCache.key === cacheKey && _extSummaryCache.data) {
        if (jobExtStats) jobExtStats.stats = _extSummaryCache.data;
        return;
    }
    try {
        const params = {};
        if (_currentExcludeEnabled && _currentExclude) params.exclude_domains = _currentExclude;
        if (_currentGroupBy !== 'none') params.group_by = _currentGroupBy;

        const res = await api.get(`/api/jobs/${jobId}/results/summary`, params);
        if (jobId !== _currentJobId || reqId !== _currentExtSummaryReqId) return;

        _extSummaryCache = { key: cacheKey, data: res };
        if (jobExtStats) jobExtStats.stats = res;
    } catch (err) {
        console.error('Failed to load external summary', err);
    }
}

async function loadExternalResultsPage(jobId) {
    const reqId = ++_currentExtReqId;
    if (extDataTable) extDataTable.config = { loading: true };
    try {
        const params = { group_by: _currentGroupBy, page: _currentPage, page_size: 50, sort_by: _detailSort.key || undefined, sort_asc: _detailSort.asc };
        if (_currentFilter && _currentFilter !== 'all') params.filter = _currentFilter;
        if (_currentExcludeEnabled && _currentExclude) params.exclude_domains = _currentExclude;

        const activeFilters = Object.fromEntries(Object.entries(_detailColFilters).filter(([_, v]) => v.trim() !== ''));
        if (Object.keys(activeFilters).length > 0) {
            params.col_filters = JSON.stringify(activeFilters);
        }

        const res = await api.get(`/api/jobs/${jobId}/results`, params);
        if (jobId !== _currentJobId || reqId !== _currentExtReqId) return;

        renderExtResultsTable(res);
    } catch (err) {
        if (jobId !== _currentJobId || reqId !== _currentExtReqId) return;
        if (extDataTable) extDataTable.config = { loading: false, data: [] };
        toast.error('無法載入外部連結結果：' + err.message);
    }
}

const createCell = (text, cls = '') => {
    const span = document.createElement('span');
    span.textContent = text;
    if (cls) span.className = cls;
    return span;
};

const renderUrlNode = (url, maxWidth = '300px', displayText = null) => {
    if (!url) return createCell('-', 'text-muted');
    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'truncate font-mono text-link';
    a.style.maxWidth = maxWidth;
    a.style.display = 'inline-block';
    a.style.verticalAlign = 'middle';
    a.title = url;
    a.textContent = displayText || url;
    return a;
};

const renderUrlArrayNode = (val, maxWidth = '300px', extractUrl = (x) => x) => {
    if (!val || !val.length) return createCell('-', 'text-muted');
    const wrapper = document.createElement('div');
    wrapper.style.display = 'flex';
    wrapper.style.flexDirection = 'column';
    wrapper.style.gap = '0.25rem';

    const displayLimit = 5;
    const displayList = val.slice(0, displayLimit);

    displayList.forEach(item => {
        const url = extractUrl(item);
        const a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.className = 'truncate font-mono text-link';
        a.style.maxWidth = maxWidth;
        a.title = url;
        a.textContent = url;
        wrapper.appendChild(a);
    });

    if (val.length > displayLimit) {
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.style.alignSelf = 'flex-start';
        badge.textContent = `及其它 ${val.length - displayLimit} 個`;
        wrapper.appendChild(badge);
    }
    return wrapper;
};

const renderErrorMessage = (msg, maxWidth = '300px') => {
    if (!msg) return createCell('-', 'text-muted');
    const span = document.createElement('span');
    span.className = 'truncate text-danger';
    span.style.maxWidth = maxWidth;
    span.style.display = 'inline-block';
    span.title = msg;
    span.textContent = msg;
    return span;
};

const renderHttpStatusCode = (code) => {
    if (code === null || code === undefined) return createCell('-', 'text-muted');
    const span = document.createElement('span');
    span.style.display = 'inline-block';
    span.textContent = code;
    if (code >= 200 && code < 300) span.className = 'text-success';
    else if (code >= 300 && code < 400) span.className = 'text-warning';
    else if (code >= 400) span.className = 'text-danger';
    return span;
};

function renderExtResultsTable(res) {
    const isJobActive = _currentJobStatus === 'running' || _currentJobStatus === 'starting';
    let headers = [];

    if (_currentGroupBy === 'none') {
        headers = [
            { label: '來源頁面', key: 'source_url', sortable: true, render: (val) => renderUrlNode(val) },
            { label: '目標頁面', key: 'target_url', sortable: true, render: (val) => renderUrlNode(val) },
            { label: 'IP 位址', key: 'ip_address', sortable: true, truncate: '150px', className: 'font-mono text-sm' },
            { label: 'HTTPS', key: 'is_secure', sortable: true, align: 'center', render: val => val ? createCell('✓', 'text-success') : createCell('✗', 'text-danger') },
            { label: 'HTTP 狀態', key: 'http_status_code', sortable: true, align: 'center', render: val => renderHttpStatusCode(val) },
            { label: '錯誤訊息', key: 'error_message', sortable: true, render: (val) => renderErrorMessage(val) }
        ];
    } else if (_currentGroupBy === 'target') {
        headers = [
            { label: '目標頁面', key: 'target_url', sortable: true, render: (val) => renderUrlNode(val) },
            { label: 'IP 位址', key: 'ip_address', sortable: true, truncate: '150px', className: 'font-mono text-sm' },
            { label: 'HTTPS', key: 'is_secure', sortable: true, align: 'center', render: val => val ? createCell('✓', 'text-success') : createCell('✗', 'text-danger') },
            { label: 'HTTP 狀態', key: 'http_status_code', sortable: true, align: 'center', render: val => renderHttpStatusCode(val) },
            { label: '錯誤訊息', key: 'error_message', sortable: true, render: (val) => renderErrorMessage(val) },
            { label: '來源數量', key: 'occurrence_count', sortable: true, align: 'center' },
            { label: '來源頁面', key: 'source_urls', render: (val) => renderUrlArrayNode(val) }
        ];
    } else if (_currentGroupBy === 'source') {
        headers = [
            { label: '來源頁面', key: 'source_url', sortable: true, render: (val) => renderUrlNode(val) },
            { label: '目標數量', key: 'occurrence_count', sortable: true, align: 'center' },
            { label: '目標頁面', key: 'targets', render: (val) => renderUrlArrayNode(val, '300px', t => t.url) }
        ];
    } else if (_currentGroupBy === 'domain') {
        headers = [
            { label: '外部網域', key: 'domain', sortable: true, render: (val) => renderUrlNode('https://' + val, '300px', val) },
            { label: '目標數量', key: 'unique_urls_count', sortable: true, align: 'center' },
            { label: '來源數量', key: 'occurrence_count', sortable: true, align: 'center' },
            { label: '目標頁面', key: 'unique_urls', render: (val) => renderUrlArrayNode(val) },
            { label: '來源頁面', key: 'source_urls', render: (val) => renderUrlArrayNode(val) }
        ];
    }

    if (extDataTable) {
        extDataTable.config = {
            headers,
            data: res.items || [],
            sort: _detailSort,
            colFilters: _detailColFilters,
            pagination: { current: res.page, total: res.total_pages },
            loading: false
        };
    }
}

async function loadInternalSummary(jobId) {
    const reqId = ++_currentIntSummaryReqId;
    const cacheKey = `${_internalGroupBy}`;
    if (_intSummaryCache.key === cacheKey && _intSummaryCache.data) {
        if (jobIntStats) jobIntStats.stats = _intSummaryCache.data;
        return;
    }
    try {
        const params = { group_by: _internalGroupBy };
        const res = await api.get(`/api/jobs/${jobId}/internal-results/summary`, params);
        if (jobId !== _currentJobId || reqId !== _currentIntSummaryReqId) return;

        _intSummaryCache = { key: cacheKey, data: res };
        if (jobIntStats) jobIntStats.stats = res;
    } catch (err) {
        console.error('Failed to load internal summary', err);
    }
}

async function loadInternalResultsPage(jobId) {
    const reqId = ++_currentIntReqId;
    if (intDataTable) intDataTable.config = { loading: true };
    try {
        const params = { group_by: _internalGroupBy, page: _internalCurrentPage, page_size: 50, sort_by: _internalSort.key || undefined, sort_asc: _internalSort.asc };
        if (_internalFilter && _internalFilter !== 'all') params.filter = _internalFilter;

        const activeFilters = Object.fromEntries(Object.entries(_internalColFilters).filter(([_, v]) => v.trim() !== ''));
        if (Object.keys(activeFilters).length > 0) {
            params.col_filters = JSON.stringify(activeFilters);
        }

        const res = await api.get(`/api/jobs/${jobId}/internal-results`, params);
        if (jobId !== _currentJobId || reqId !== _currentIntReqId) return;

        renderInternalResultsTable(res);
    } catch (err) {
        if (jobId !== _currentJobId || reqId !== _currentIntReqId) return;
        if (intDataTable) intDataTable.config = { loading: false, data: [] };
        toast.error('無法載入內部連結結果：' + err.message);
    }
}

function renderInternalResultsTable(res) {
    let headers = [];

    if (_internalGroupBy === 'source') {
        headers = [
            { label: '來源頁面', key: 'source_url', sortable: true, render: (val) => renderUrlNode(val) },
            { label: '目標數量', key: 'occurrence_count', sortable: true, align: 'center' },
            { label: '目標頁面', key: 'targets', render: (val) => renderUrlArrayNode(val, '300px', t => t.url) }
        ];
    } else {
        headers = [
            { label: '來源頁面', key: 'source_url', sortable: true, render: (val) => renderUrlNode(val) },
            { label: '目標頁面', key: 'target_url', sortable: true, render: (val) => renderUrlNode(val) },
            { label: 'HTTPS', key: 'is_secure', sortable: true, align: 'center', render: val => val ? createCell('✓', 'text-success') : createCell('✗', 'text-danger') },
            { label: 'HTTP 狀態', key: 'http_status_code', sortable: true, align: 'center', render: val => renderHttpStatusCode(val) },
            { label: '錯誤訊息', key: 'error_message', sortable: true, render: (val) => renderErrorMessage(val) }
        ];
    }

    if (intDataTable) {
        intDataTable.config = {
            headers,
            data: res.items || [],
            sort: _internalSort,
            colFilters: _internalColFilters,
            pagination: { current: res.page, total: res.total_pages },
            loading: false
        };
    }
}

function bindWebComponentEvents() {
    // 頁籤切換
    document.querySelectorAll('#job-detail-tabs .tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('#job-detail-tabs .tab-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');

            _currentTab = e.target.dataset.tab;
            if (_currentTab === 'external') {
                document.getElementById('tab-content-external').style.display = 'block';
                document.getElementById('tab-content-internal').style.display = 'none';
            } else {
                document.getElementById('tab-content-external').style.display = 'none';
                document.getElementById('tab-content-internal').style.display = 'block';
            }
            loadResults(_currentJobId);
        });
    });

    // 分組選擇
    const extGroupSelect = document.getElementById('results-group-select');
    if (extGroupSelect) {
        extGroupSelect.addEventListener('change', (e) => {
            _currentGroupBy = e.target.value;
            _currentPage = 1;
            _detailSort = { key: null, asc: true };
            _detailColFilters = {};
            loadResults(_currentJobId);
        });
    }

    const intGroupSelect = document.getElementById('internal-results-group-select');
    if (intGroupSelect) {
        intGroupSelect.addEventListener('change', (e) => {
            _internalGroupBy = e.target.value;
            _internalCurrentPage = 1;
            _internalSort = { key: null, asc: true };
            _internalColFilters = {};
            loadResults(_currentJobId);
        });
    }

    // ── 完整報表匯出 (Web Component) ───────────────────────────────────
    document.addEventListener('export-full', async (e) => {
        if (!e.detail || !e.detail.job) return;
        const jobId = e.detail.job.id;
        try {
            await api.download(`/api/jobs/${jobId}/export/full`);
        } catch (err) {
            toast.error('匯出報表失敗：' + err.message);
        }
    });

    // ── 列表 CSV/JSON 匯出按鈕 ───────────────────────────────────
    const buildExportUrl = (basePath, fmt, filter, groupBy) => {
        const params = new URLSearchParams({ fmt });
        if (filter && filter !== 'all') params.append('filter', filter);
        if (groupBy && groupBy !== 'none') params.append('group_by', groupBy);
        return `${basePath}?${params.toString()}`;
    };

    const extExportCsv = document.getElementById('btn-export-csv');
    if (extExportCsv) {
        extExportCsv.addEventListener('click', async () => {
            if (!_currentJobId) return;
            try {
                await api.download(buildExportUrl(`/api/jobs/${_currentJobId}/results/export`, 'csv', _currentFilter, _currentGroupBy));
            } catch (err) { toast.error('匯出 CSV 失敗：' + err.message); }
        });
    }

    const extExportJson = document.getElementById('btn-export-json');
    if (extExportJson) {
        extExportJson.addEventListener('click', async () => {
            if (!_currentJobId) return;
            try {
                await api.download(buildExportUrl(`/api/jobs/${_currentJobId}/results/export`, 'json', _currentFilter, _currentGroupBy));
            } catch (err) { toast.error('匯出 JSON 失敗：' + err.message); }
        });
    }

    const intExportCsv = document.getElementById('btn-int-export-csv');
    if (intExportCsv) {
        intExportCsv.addEventListener('click', async () => {
            if (!_currentJobId) return;
            try {
                await api.download(buildExportUrl(`/api/jobs/${_currentJobId}/internal-results/export`, 'csv', _internalFilter, _internalGroupBy));
            } catch (err) { toast.error('匯出 CSV 失敗：' + err.message); }
        });
    }

    const intExportJson = document.getElementById('btn-int-export-json');
    if (intExportJson) {
        intExportJson.addEventListener('click', async () => {
            if (!_currentJobId) return;
            try {
                await api.download(buildExportUrl(`/api/jobs/${_currentJobId}/internal-results/export`, 'json', _internalFilter, _internalGroupBy));
            } catch (err) { toast.error('匯出 JSON 失敗：' + err.message); }
        });
    }

    // ── 檢視任務設定 (Web Component) ───────────────────────────────────
    const configModalEl = document.getElementById('job-config-modal');
    document.addEventListener('view-config', (e) => {
        if (!e.detail || !e.detail.job) return;
        const job = e.detail.job;
        const c = job.config;
        const container = document.getElementById('job-config-display-container');
        if (container && configModalEl) {
            container.replaceChildren();
            if (!c) {
                const empty = document.createElement('div');
                empty.className = 'text-muted';
                empty.style.textAlign = 'center';
                empty.style.padding = '2rem';
                empty.textContent = '無設定資料';
                container.appendChild(empty);
            } else {
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
                        if (item.valStyle) Object.assign(val.style, item.valStyle);
                        if (item.valClass) val.className = item.valClass;
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
        if (configModalEl) configModalEl.style.display = 'flex';
    });


    // Components Events
    if (jobControls) {
        jobControls.addEventListener('job-start', async () => {
            if (await showConfirm('啟動任務', '確定要開始（或接續）執行此爬蟲任務嗎？', '啟動')) {
                try {
                    await api.post(`/api/jobs/${_currentJobId}/start`);
                    toast.success('任務已啟動！');
                    refreshJobDetail(_currentJobId);
                } catch (err) { toast.error(err.message); }
            }
        });
        jobControls.addEventListener('job-pause', async () => {
            if (await showConfirm('暫停任務', '確定要暫停此爬蟲任務嗎？任務將在完成當前頁面後停止。', '暫停')) {
                try {
                    await api.post(`/api/jobs/${_currentJobId}/pause`);
                    toast.info('暫停指令已送出，任務將在完成當前頁面後停止。');
                    refreshJobDetail(_currentJobId);
                } catch (err) { toast.error(err.message); }
            }
        });
        jobControls.addEventListener('job-reset', async () => {
            if (await showConfirm('確定要重置任務嗎？', '這將清空所有爬取進度與外連結果，並將任務狀態退回初始設定。此操作無法復原。', '確定重置', true)) {
                try {
                    await api.post(`/api/jobs/${_currentJobId}/reset`);
                    toast.success('任務已重置');
                    _extSummaryCache.key = null;
                    _intSummaryCache.key = null;
                    _currentPage = 1;
                    _internalCurrentPage = 1;
                    refreshJobDetail(_currentJobId);
                    loadResults(_currentJobId);
                } catch (err) { toast.error(err.message); }
            }
        });

        jobControls.addEventListener('job-delete', async () => {
            if (await showConfirm('刪除任務', '確定要永久刪除此任務及其所有關聯資料嗎？此操作無法復原。', '確定刪除', true)) {
                try {
                    await api.del(`/api/jobs/${_currentJobId}`);
                    toast.success('任務已刪除');
                    window.location.hash = '#/jobs';
                } catch (err) { toast.error(err.message); }
            }
        });
        jobControls.addEventListener('job-duplicate', () => { window.location.hash = `#/new?clone=${_currentJobId}`; });
        jobControls.addEventListener('job-compare', () => { window.location.hash = `#/compare?target=${_currentJobId}`; });
        jobControls.addEventListener('job-transfer', () => { window.location.hash = `#/transfer?job=${_currentJobId}`; });
        jobControls.addEventListener('job-retry', async () => {
            if (await showConfirm('重試失敗連結？', '這會將狀態碼不是 2xx/3xx 的外部連結重新標記為等待中並繼續爬取。', '確定重試')) {
                try {
                    await api.post(`/api/jobs/${_currentJobId}/retry-failed`);
                    toast.success('失敗連結已重新排隊，任務啟動中...');
                    _extSummaryCache.key = null;
                    _intSummaryCache.key = null;
                    refreshJobDetail(_currentJobId);
                    loadResults(_currentJobId);
                } catch (err) { toast.error(err.message); }
            }
        });
    }



    if (jobExtStats) {
        jobExtStats.addEventListener('filter-change', (e) => {
            _currentFilter = e.detail.filter;
            _currentPage = 1;
            loadExternalResultsPage(_currentJobId);
        });
    }

    if (jobIntStats) {
        jobIntStats.addEventListener('filter-change', (e) => {
            _internalFilter = e.detail.filter;
            _internalCurrentPage = 1;
            loadInternalResultsPage(_currentJobId);
        });
    }

    if (extDataTable) {
        extDataTable.addEventListener('page-change', (e) => {
            _currentPage = e.detail.page;
            loadExternalResultsPage(_currentJobId);
        });
        extDataTable.addEventListener('sort-change', (e) => {
            _detailSort = { key: e.detail.key, asc: e.detail.asc };
            loadExternalResultsPage(_currentJobId);
        });
        extDataTable.addEventListener('filter-change', (e) => {
            _detailColFilters[e.detail.key] = e.detail.value;
            _currentPage = 1;
            clearTimeout(_extFilterTimeout);
            _extFilterTimeout = setTimeout(() => {
                loadExternalResultsPage(_currentJobId);
            }, 300);
        });
    }

    if (intDataTable) {
        intDataTable.addEventListener('page-change', (e) => {
            _internalCurrentPage = e.detail.page;
            loadInternalResultsPage(_currentJobId);
        });
        intDataTable.addEventListener('sort-change', (e) => {
            _internalSort = { key: e.detail.key, asc: e.detail.asc };
            loadInternalResultsPage(_currentJobId);
        });
        intDataTable.addEventListener('filter-change', (e) => {
            _internalColFilters[e.detail.key] = e.detail.value;
            _internalCurrentPage = 1;
            clearTimeout(_intFilterTimeout);
            _intFilterTimeout = setTimeout(() => {
                loadInternalResultsPage(_currentJobId);
            }, 300);
        });
    }
}
