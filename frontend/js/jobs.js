/**
 * jobs.js — 任務列表與新增任務頁面邏輯（ESM Controller）
 * 
 * 負責處理任務列表頁面之 UI 渲染、`<link-table>` 事件監聽與導頁動作。
 */

import * as api from './api.js';
import { JobsStore } from './stores/jobs-store.js';

export class JobsController {
    /**
     * 初始化 JobsController 實例
     * @param {JobsStore} [store=new JobsStore()] - 任務列表 Store 實例
     */
    constructor(store = new JobsStore()) {
        /** @type {JobsStore} 任務列表 Store 實例 */
        this.store = store;
        /** @type {HTMLElement|null} 列表容器 DOM 元素 */
        this.containerEl = null;
    }

    /**
     * 設定或快取列表容器 DOM 元素
     * @param {HTMLElement|null} [containerEl=null] - 欲綁定的容器 DOM 元素
     * @returns {void}
     */
    setContainer(containerEl = null) {
        if (containerEl) {
            this.containerEl = containerEl;
        } else if (!this.containerEl) {
            this.containerEl = document.getElementById('jobs-list-container');
        }
    }

    /**
     * 載入並渲染任務列表
     * @param {Object|null} [filters=null] - 搜尋過濾條件字典
     * @param {HTMLElement|null} [containerEl=null] - 容器 DOM 元素 (預設 #jobs-list-container)
     * @returns {Promise<void>}
     */
    async loadJobs(filters = null, containerEl = null) {
        this.setContainer(containerEl);
        if (!this.containerEl) return;

        this.store.setFilters(filters);

        try {
            await this.store.fetchJobs();
            this.renderJobList();
        } catch (error) {
            console.error('Failed to fetch jobs:', error);
            this.containerEl.replaceChildren();
            const emptyStateEl = document.createElement('div');
            emptyStateEl.className = 'empty-state text-danger';
            emptyStateEl.textContent = '載入失敗：' + error.message;
            this.containerEl.appendChild(emptyStateEl);
        }
    }

    /**
     * 渲染任務列表表格元件 (<link-table>)
     * @param {Array<Object>|null} [jobs=null] - 任務資料陣列，未提供則使用 Store 快取
     * @param {HTMLElement|null} [containerEl=null] - 容器 DOM 元素
     * @returns {void}
     */
    renderJobList(jobs = null, containerEl = null) {
        if (containerEl) this.setContainer(containerEl);
        if (jobs) this.store.currentJobs = jobs;

        if (!this.containerEl) {
            this.setContainer(document.getElementById('jobs-list-container'));
            if (!this.containerEl) return;
        }

        let linkTable = this.containerEl.querySelector('link-table');
        if (!linkTable) {
            this.containerEl.replaceChildren();
            linkTable = document.createElement('link-table');
            linkTable.id = 'jobs-table';

            linkTable.addEventListener('sort-change', (e) => {
                this.store.setSort(e.detail);
                this.renderJobList();
            });

            linkTable.addEventListener('filter-change', (e) => {
                this.store.setFilter(e.detail.key, e.detail.value);
                this.renderJobList();
            });

            linkTable.addEventListener('row-click', (e) => {
                const job = e.detail;
                window.location.hash = `#/jobs/${job.id}`;
            });

            this.containerEl.appendChild(linkTable);
        }

        const data = this.store.getFilteredAndSortedJobs();

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
                filterable: false,
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
                        viewJob(row.id);
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
            sort: this.store.sort,
            colFilters: this.store.colFilters,
            pagination: { current: 1, total: 1 },
            loading: false,
            rowClickable: true
        };
    }
}

/** 全域 JobsController 實例 */
export const jobsController = new JobsController();

/**
 * 向下相容的載入任務列表函式
 * @param {Object|null} [filters=null] - 搜尋過濾條件字典
 * @param {HTMLElement|null} [containerEl=null] - 容器 DOM 元素
 * @returns {Promise<void>}
 */
export async function loadJobs(filters = null, containerEl = null) {
    return jobsController.loadJobs(filters, containerEl);
}

/**
 * 向下相容的渲染任務列表函式
 * @param {Array<Object>|null} [jobs=null] - 任務資料陣列
 * @param {HTMLElement|null} [containerEl=null] - 容器 DOM 元素
 * @returns {void}
 */
export function renderJobList(jobs = null, containerEl = null) {
    return jobsController.renderJobList(jobs, containerEl);
}

/**
 * 導覽至任務詳情頁面
 * @param {string} jobId - 任務 ID
 * @returns {void}
 */
export const viewJob = (jobId) => {
    window.location.hash = `#/jobs/${jobId}`;
};
