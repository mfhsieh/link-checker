/**
 * jobs.js — 任務列表與新增任務頁面邏輯（ESM）
 */

import * as api from './api.js';
import { toast } from './components/toast.js';

// ── 任務列表 ─────────────────────────────────────────────

/** @type {Array<Object>} 目前載入的所有任務列表 */
let _currentJobs = [];
/** @type {{key: string|null, asc: boolean}} 目前的排序狀態 */
let _jobSort = { key: 'created_at', asc: false };
/** @type {Object<string, string>} 各欄位的篩選條件 */
let _jobColFilters = {};
/** @type {HTMLElement|null} 列表容器元素 */
let _listContainerEl = null;

/**
 * 載入並渲染任務列表
 * @param {Object} [filters=null] - 搜尋過濾條件
 * @param {HTMLElement} [containerEl=null] - 容器元素 (預設 #jobs-list-container)
 * @returns {Promise<void>}
 */
export async function loadJobs(filters = null, containerEl = null) {
    if (containerEl) {
        _listContainerEl = containerEl;
    } else if (!_listContainerEl) {
        _listContainerEl = document.getElementById('jobs-list-container');
    }

    if (!_listContainerEl) return;

    // 如果有傳入 filters，則更新全域的過濾狀態
    if (filters) {
        Object.assign(_jobColFilters, filters);
    }

    // 整理傳給後端的參數
    const params = {
        sort_by: _jobSort.key,
        order: _jobSort.asc ? 'asc' : 'desc',
        ..._jobColFilters
    };

    // 如果選擇了全部狀態，就不傳 status 參數
    if (_jobColFilters.status === 'ALL' || !_jobColFilters.status) {
        delete params.status;
    }

    try {
        const data = await api.get('/api/jobs', params);
        _currentJobs = data || [];
        renderJobList();
    } catch (error) {
        console.error('Failed to fetch jobs:', error);
        _listContainerEl.replaceChildren();
        const emptyStateEl = document.createElement('div');
        emptyStateEl.className = 'empty-state text-danger';
        emptyStateEl.textContent = '載入失敗：' + error.message;
        _listContainerEl.appendChild(emptyStateEl);
    }
}

/**
 * 渲染任務列表表格
 * @returns {void} 無回傳值
 */
export function renderJobList(jobs = null, containerEl = null) {
    if (containerEl) _listContainerEl = containerEl;
    if (jobs) _currentJobs = jobs;

    if (!_listContainerEl) {
        _listContainerEl = document.getElementById('jobs-list-container');
        if (!_listContainerEl) return;
    }

    let linkTable = _listContainerEl.querySelector('link-table');
    if (!linkTable) {
        _listContainerEl.replaceChildren();
        linkTable = document.createElement('link-table');
        linkTable.id = 'jobs-table';

        linkTable.addEventListener('sort-change', (e) => {
            _jobSort = e.detail;
            renderJobList();
        });

        linkTable.addEventListener('filter-change', (e) => {
            _jobColFilters[e.detail.key] = e.detail.value;
            renderJobList();
        });

        linkTable.addEventListener('row-click', (e) => {
            const job = e.detail;
            window.location.hash = `#/jobs/${job.id}`;
        });

        _listContainerEl.appendChild(linkTable);
    }

    let data = [..._currentJobs];

    // Client-side filtering (if any additional is needed beyond API)
    for (const [k, v] of Object.entries(_jobColFilters)) {
        if (!v || k === 'status') continue; // status is handled by API
        data = data.filter(item => {
            let val = item[k];
            if (k === 'created_at') val = api.formatLocalTime(val);
            return String(val || '').toLowerCase().includes(v.toLowerCase());
        });
    }

    // Client-side sorting
    data.sort((a, b) => {
        let valA = a[_jobSort.key];
        let valB = b[_jobSort.key];
        if (valA === undefined || valA === null) valA = '';
        if (valB === undefined || valB === null) valB = '';

        if (_jobSort.key === 'created_at') {
            valA = new Date(valA).getTime() || 0;
            valB = new Date(valB).getTime() || 0;
            return _jobSort.asc ? valA - valB : valB - valA;
        }

        valA = String(valA).toLowerCase();
        valB = String(valB).toLowerCase();
        if (valA < valB) return _jobSort.asc ? -1 : 1;
        if (valA > valB) return _jobSort.asc ? 1 : -1;
        return 0;
    });

    const headers = [
        {
            label: '任務 ID',
            key: 'id',
            render: (val) => {
                const span = document.createElement('span');
                span.className = 'font-mono text-xs';
                span.title = val;
                span.textContent = val || '-';
                return span;
            }
        },
        {
            label: '起始 URL',
            key: 'start_url',
            render: (val) => api.createTruncatedSpan(val || '-', '280px')
        },
        {
            label: '狀態',
            key: 'status',
            render: (val) => {
                const span = document.createElement('span');
                span.className = `badge badge-${val}`;
                span.textContent = api.formatStatus(val);
                return span;
            }
        },
        {
            label: '建立時間',
            key: 'created_at',
            render: (val) => {
                const span = document.createElement('span');
                span.className = 'text-muted text-sm';
                span.textContent = api.formatLocalTime(val);
                return span;
            }
        },
        {
            label: '操作',
            key: 'actions',
            filterable: false,
            sortable: false,
            render: (_, row) => {
                const divActions = document.createElement('div');
                divActions.className = 'job-actions';
                divActions.style.display = 'flex';
                divActions.style.gap = '8px';

                const btn = document.createElement('button');
                btn.className = 'btn btn-sm btn-secondary';
                btn.textContent = '詳情';
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    window.viewJob(row.id);
                });
                divActions.appendChild(btn);

                const btnDup = document.createElement('button');
                btnDup.className = 'btn btn-sm btn-secondary';
                btnDup.textContent = '複製';
                btnDup.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (typeof window.showJobForm === 'function') {
                        window.showJobForm(row);
                    } else {
                        window.location.hash = `#/new?clone=${row.id}`;
                    }
                });
                divActions.appendChild(btnDup);

                return divActions;
            }
        }
    ];

    linkTable.config = {
        headers: headers,
        data: data,
        sort: _jobSort,
        colFilters: _jobColFilters,
        pagination: { current: 1, total: 1 },
        loading: false,
        rowClickable: true
    };
}

/**
 * 導覽至任務詳情頁面 (附加於 window 物件供行內點擊事件呼叫)
 * @param {string} jobId - 任務 ID
 * @returns {void}
 */
window.viewJob = (jobId) => {
    window.location.hash = `#/jobs/${jobId}`;
};
