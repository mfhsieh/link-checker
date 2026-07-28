/**
 * job-detail.js — 任務詳情頁面控制器（ESM Controller）
 *
 * 協調 JobDetailStore、JobDetailSSEManager 與 JobDetailTableManager，
 * 處理任務詳情頁面之動態渲染、SSE 即時進度更新、頁籤切換與 Web Components 事件觸發。
 */

import * as api from './api.js';
import { toast } from './components/toast.js';
import { showConfirm } from './components/confirm-modal.js';
import { JobDetailStore } from './stores/job-detail-store.js';
import { JobDetailSSEManager } from './controllers/job-detail-sse.js';
import { JobDetailTableManager } from './controllers/job-detail-table.js';

// ── 全域事件監聽 (Top-level) ──────────────────────────────────────────

// 任務詳情返回列表按鈕 (使用 Event Delegation)
document.addEventListener('click', (e) => {
    let target = e.target;
    if (target && target.nodeType === Node.TEXT_NODE) target = target.parentElement;
    const backBtn = target && target.closest ? target.closest('#btn-back-jobs') : null;
    if (backBtn) {
        e.preventDefault();
        const backPath = sessionStorage.getItem('jobBackPath');
        if (backPath) {
            sessionStorage.removeItem('jobBackPath');
            window.location.href = backPath;
        } else {
            window.location.hash = '#/jobs';
        }
    }

    // Config modal close buttons
    if (e.target.closest('#job-config-close') || e.target.closest('#job-config-ok')) {
        const configModalEl = document.getElementById('job-config-modal');
        if (configModalEl) configModalEl.style.display = 'none';
    }
});

/**
 * 任務詳情頁面的主要 Controller
 * 負責串接狀態庫 (Store)、SSE 更新及 DOM UI 操作
 */
export class JobDetailController {
    /**
     * 初始化 JobDetailController 實例
     * @param {JobDetailStore} [store=new JobDetailStore()] - 任務詳情 Store 實例
     * @param {JobDetailTableManager} [tableManager=new JobDetailTableManager()] - 表格視圖控制器實例
     */
    constructor(store = new JobDetailStore(), tableManager = new JobDetailTableManager()) {
        /** @type {JobDetailStore} 狀態庫實例 */
        this.store = store;
        /** @type {JobDetailTableManager} 表格視圖管理器實例 */
        this.tableManager = tableManager;
        /** @type {boolean} 是否已綁定事件 */
        this.eventsBound = false;

        /** @type {JobDetailSSEManager} SSE 與輪詢管理器實例 */
        this.sseManager = new JobDetailSSEManager({
            onMessage: (jobUpdate) => this.handleSseMessage(jobUpdate),
            onPoll: (jobId) => this.handlePolling(jobId)
        });
    }

    // ── Web Component 與 DOM 元素 getter 快取區 ──────────────────────────

    /** @returns {HTMLElement|null} <job-controls> 元件 */
    get jobControls() { return document.getElementById('job-controls'); }

    /** @returns {HTMLElement|null} <job-status-card> 元件 */
    get jobStatusCard() { return document.getElementById('job-status-card'); }

    /** @returns {HTMLElement|null} <job-progress> 元件 */
    get jobProgressCard() { return document.getElementById('job-progress'); }

    /** @returns {HTMLElement|null} <job-stats> 外部連結統計元件 */
    get jobExtStats() { return document.getElementById('job-ext-stats'); }

    /** @returns {HTMLElement|null} <job-stats> 內部連結統計元件 */
    get jobIntStats() { return document.getElementById('job-int-stats'); }

    /** @returns {HTMLElement|null} <link-table> 外部連結表格元件 */
    get extDataTable() { return document.getElementById('ext-data-table'); }

    /** @returns {HTMLElement|null} <link-table> 內部連結表格元件 */
    get intDataTable() { return document.getElementById('int-data-table'); }

    /**
     * SSE 訊息事件處理
     * @param {Object} jobUpdate - 後端 SSE 推送的任務增量更新資料
     * @returns {void}
     */
    handleSseMessage(jobUpdate) {
        if (this.store.currentJobData) {
            Object.assign(this.store.currentJobData, jobUpdate);
            this.renderJobInfo(this.store.currentJobData);
        } else {
            this.store.currentJobData = jobUpdate;
            this.renderJobInfo(this.store.currentJobData);
        }
    }

    /**
     * 30 秒定期輪詢備援處理
     * @param {string} jobId - 任務 ID
     * @returns {void}
     */
    handlePolling(jobId) {
        if (this.store.currentTab === 'external') {
            this.store.extSummaryCache.key = null;
            this.loadExternalSummary(jobId);
        } else if (this.store.currentTab === 'internal') {
            this.store.intSummaryCache.key = null;
            this.loadInternalSummary(jobId);
        }
    }

    /**
     * 清空任務詳情頁面的 UI 狀態與快取
     * @returns {void}
     */
    clearJobDetailUI() {
        this.store.currentJobData = null;
        const statusEl = document.getElementById('job-status');
        if (statusEl) {
            statusEl.textContent = '載入中...';
            statusEl.className = 'badge badge-pending';
        }
        if (this.jobStatusCard) this.jobStatusCard.job = null;
        if (this.jobProgressCard) this.jobProgressCard.job = null;
        if (this.jobControls) this.jobControls.job = null;

        if (this.jobExtStats) {
            this.jobExtStats.stats = null;
            this.jobExtStats.activeFilter = 'all';
        }
        if (this.jobIntStats) {
            this.jobIntStats.stats = null;
            this.jobIntStats.activeFilter = 'all';
        }
        if (this.extDataTable) this.extDataTable.config = { data: [], loading: true };
        if (this.intDataTable) this.intDataTable.config = { data: [], loading: true };
    }

    /**
     * 初始化任務詳情頁面
     * @param {string} jobId - 任務 ID
     * @returns {Promise<void>}
     */
    async init(jobId) {
        this.store.reset(jobId);
        this.sseManager.stop();

        const groupSelectEl = document.getElementById('results-group-select');
        if (groupSelectEl) groupSelectEl.value = 'none';
        const intGroupSelectEl = document.getElementById('internal-results-group-select');
        if (intGroupSelectEl) intGroupSelectEl.value = 'none';

        document.querySelectorAll('#job-detail-tabs .tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === 'external');
        });
        const extTabEl = document.getElementById('tab-content-external');
        const intTabEl = document.getElementById('tab-content-internal');
        if (extTabEl) extTabEl.style.display = 'block';
        if (intTabEl) intTabEl.style.display = 'none';

        this.clearJobDetailUI();

        if (!this.eventsBound) {
            this.bindWebComponentEvents();
            this.eventsBound = true;
        }

        await this.refreshJobDetail(jobId);
        await this.loadResults(jobId);
    }

    /**
     * 銷毀頁面資源並關閉串流與定時器
     * @returns {void}
     */
    destroy() {
        this.sseManager.stop();
        this.store.currentJobId = null;
        if (this.store.extFilterTimeout) clearTimeout(this.store.extFilterTimeout);
        if (this.store.intFilterTimeout) clearTimeout(this.store.intFilterTimeout);
    }

    /**
     * 更新任務詳細資訊，並依任務執行狀態決定是否啟動 SSE
     * @param {string} jobId - 任務 ID
     * @returns {Promise<void>}
     */
    async refreshJobDetail(jobId) {
        try {
            const job = await api.get(`/api/jobs/${jobId}`);
            if (jobId !== this.store.currentJobId) return;
            this.store.currentJobData = job;
            this.renderJobInfo(this.store.currentJobData);

            const isActuallyRunning = ['running', 'starting'].includes(job.status) || job.is_running;
            if (isActuallyRunning) {
                if (!this.sseManager.eventSource) this.sseManager.start(jobId);
            } else {
                this.sseManager.stop();
            }
        } catch (err) {
            toast.error('無法取得任務資訊：' + err.message);
            this.sseManager.stop();
        }
    }

    /**
     * 渲染任務基本資訊至 UI 與 Web Components
     * @param {Object} job - 任務資料物件
     * @returns {void}
     */
    renderJobInfo(job) {
        this.store.currentJobStatus = job.status;
        const isJobRunning = job.is_running;

        const statusEl = document.getElementById('job-status');
        const idEl = document.getElementById('job-id-display');

        let statusText = api.formatStatus(job.status);
        let statusClass = `badge-${job.status}`;

        if (statusEl) {
            statusEl.textContent = statusText;
            statusEl.className = `badge ${statusClass}`;
        }
        if (idEl) {
            idEl.textContent = job.id;
        }

        if (this.jobStatusCard) this.jobStatusCard.job = job;
        if (this.jobProgressCard) this.jobProgressCard.job = job;
        if (this.jobControls) this.jobControls.job = job;

        if (['completed', 'error', 'paused'].includes(job.status) && !isJobRunning) {
            this.store.invalidateCaches();
        }
    }

    /**
     * 依當前選擇的頁籤載入結果與統計摘要
     * @param {string} jobId - 任務 ID
     * @returns {Promise<void>}
     */
    async loadResults(jobId) {
        if (this.store.currentTab === 'external') {
            await this.loadExternalSummary(jobId);
            await this.loadExternalResultsPage(jobId);
        } else if (this.store.currentTab === 'internal') {
            await this.loadInternalSummary(jobId);
            await this.loadInternalResultsPage(jobId);
        }
    }

    /**
     * 載入外部連結統計摘要
     * @param {string} jobId - 任務 ID
     * @returns {Promise<void>}
     */
    async loadExternalSummary(jobId) {
        const reqId = ++this.store.currentExtSummaryReqId;
        const cacheKey = `${this.store.currentExcludeEnabled ? this.store.currentExclude : ''}|${this.store.currentGroupBy}`;
        if (this.store.extSummaryCache.key === cacheKey && this.store.extSummaryCache.data) {
            if (this.jobExtStats) this.jobExtStats.stats = this.store.extSummaryCache.data;
            return;
        }
        try {
            const params = {};
            if (this.store.currentExcludeEnabled && this.store.currentExclude) params.exclude = this.store.currentExclude;
            if (this.store.currentGroupBy !== 'none') params.group_by = this.store.currentGroupBy;

            const res = await api.get(`/api/jobs/${jobId}/results/summary`, params);
            if (jobId !== this.store.currentJobId || reqId !== this.store.currentExtSummaryReqId) return;

            this.store.extSummaryCache = { key: cacheKey, data: res };
            if (this.jobExtStats) this.jobExtStats.stats = res;
        } catch (err) {
            console.error('Failed to load external summary', err);
        }
    }

    /**
     * 載入外部連結分頁結果
     * @param {string} jobId - 任務 ID
     * @returns {Promise<void>}
     */
    async loadExternalResultsPage(jobId) {
        const reqId = ++this.store.currentExtReqId;
        if (this.extDataTable) this.extDataTable.config = { loading: true };
        try {
            const params = {
                group_by: this.store.currentGroupBy,
                page: this.store.currentPage,
                page_size: 50,
                sort_by: this.store.detailSort.key || undefined,
                sort_asc: this.store.detailSort.asc
            };
            if (this.store.currentFilter && this.store.currentFilter !== 'all') params.filter = this.store.currentFilter;
            if (this.store.currentExcludeEnabled && this.store.currentExclude) params.exclude = this.store.currentExclude;

            const activeFilters = Object.fromEntries(Object.entries(this.store.detailColFilters).filter(([_, v]) => v.trim() !== ''));
            if (Object.keys(activeFilters).length > 0) {
                params.col_filters = JSON.stringify(activeFilters);
            }

            const res = await api.get(`/api/jobs/${jobId}/results`, params);
            if (jobId !== this.store.currentJobId || reqId !== this.store.currentExtReqId) return;

            this.tableManager.renderExtResultsTable(res, this.store, this.extDataTable);
            this.tableManager.updateExtToolbarButtons(this.store);
        } catch (err) {
            if (jobId !== this.store.currentJobId || reqId !== this.store.currentExtReqId) return;
            if (this.extDataTable) this.extDataTable.config = { loading: false, data: [] };
            toast.error('無法載入外部連結結果：' + err.message);
        }
    }

    /**
     * 載入內部連結統計摘要
     * @param {string} jobId - 任務 ID
     * @returns {Promise<void>}
     */
    async loadInternalSummary(jobId) {
        const reqId = ++this.store.currentIntSummaryReqId;
        const cacheKey = `${this.store.internalGroupBy}`;
        if (this.store.intSummaryCache.key === cacheKey && this.store.intSummaryCache.data) {
            if (this.jobIntStats) this.jobIntStats.stats = this.store.intSummaryCache.data;
            return;
        }
        try {
            const params = {};
            if (this.store.internalGroupBy !== 'none') params.group_by = this.store.internalGroupBy;
            const res = await api.get(`/api/jobs/${jobId}/internal-results/summary`, params);
            if (jobId !== this.store.currentJobId || reqId !== this.store.currentIntSummaryReqId) return;

            this.store.intSummaryCache = { key: cacheKey, data: res };
            if (this.jobIntStats) this.jobIntStats.stats = res;
        } catch (err) {
            console.error('Failed to load internal summary', err);
        }
    }

    /**
     * 載入內部連結分頁結果
     * @param {string} jobId - 任務 ID
     * @returns {Promise<void>}
     */
    async loadInternalResultsPage(jobId) {
        const reqId = ++this.store.currentIntReqId;
        if (this.intDataTable) this.intDataTable.config = { loading: true };
        try {
            const params = {
                page: this.store.internalCurrentPage,
                page_size: 50,
                sort_by: this.store.internalSort.key || undefined,
                sort_asc: this.store.internalSort.asc
            };
            if (this.store.internalGroupBy !== 'none') params.group_by = this.store.internalGroupBy;
            if (this.store.internalFilter && this.store.internalFilter !== 'all') params.filter = this.store.internalFilter;

            const activeFilters = Object.fromEntries(Object.entries(this.store.internalColFilters).filter(([_, v]) => v.trim() !== ''));
            if (Object.keys(activeFilters).length > 0) {
                params.col_filters = JSON.stringify(activeFilters);
            }

            const res = await api.get(`/api/jobs/${jobId}/internal-results`, params);
            if (jobId !== this.store.currentJobId || reqId !== this.store.currentIntReqId) return;

            this.tableManager.renderInternalResultsTable(res, this.store, this.intDataTable);
            this.tableManager.updateIntToolbarButtons(this.store);
        } catch (err) {
            if (jobId !== this.store.currentJobId || reqId !== this.store.currentIntReqId) return;
            if (this.intDataTable) this.intDataTable.config = { loading: false, data: [] };
            toast.error('無法載入內部連結結果：' + err.message);
        }
    }

    /**
     * 綁定頁面與 Web Components 的自訂與原生事件監聽
     * @returns {void}
     */
    bindWebComponentEvents() {
        // ── 綁定排除網域 Modal 邏輯
        const openExcludeBtn = document.getElementById('btn-open-exclude-modal');
        const excludeModalEl = document.getElementById('exclude-domains-modal');
        const excludeTextareaInput = document.getElementById('exclude-domains-textarea');
        const excludeEnabledCheckbox = document.getElementById('exclude-domains-enabled');
        const excludeSubmitBtn = document.getElementById('exclude-domains-submit');
        const excludeCloseBtn = document.getElementById('exclude-domains-close');
        const excludeCancelBtn = document.getElementById('exclude-domains-cancel');

        if (openExcludeBtn && excludeModalEl) {
            const closeExcludeModal = () => { excludeModalEl.style.display = 'none'; document.body.classList.remove('modal-open'); };

            openExcludeBtn.addEventListener('click', () => {
                excludeTextareaInput.value = this.store.currentExclude.split(',').filter(Boolean).join('\n');
                if (excludeEnabledCheckbox) excludeEnabledCheckbox.checked = this.store.currentExcludeEnabled;
                excludeModalEl.style.display = 'flex';
                document.body.classList.add('modal-open');
                setTimeout(() => excludeTextareaInput.focus(), 50);
            });

            if (excludeCloseBtn) excludeCloseBtn.addEventListener('click', closeExcludeModal);
            if (excludeCancelBtn) excludeCancelBtn.addEventListener('click', closeExcludeModal);

            if (excludeSubmitBtn) {
                excludeSubmitBtn.addEventListener('click', async () => {
                    if (document.getElementById('view-job-detail').style.display === 'none') return;

                    if (excludeEnabledCheckbox) {
                        this.store.currentExcludeEnabled = excludeEnabledCheckbox.checked;
                        localStorage.setItem('link-checker-exclude-enabled', this.store.currentExcludeEnabled);
                    }

                    const lines = excludeTextareaInput.value.split('\n').map(s => s.trim()).filter(Boolean);
                    this.store.currentExclude = lines.join(',');
                    localStorage.setItem('link-checker-exclude-domains', this.store.currentExclude);

                    closeExcludeModal();

                    this.store.currentPage = 1;
                    this.store.extSummaryCache.key = null;
                    await this.loadResults(this.store.currentJobId);
                });
            }
        }

        // 頁籤切換
        document.querySelectorAll('#job-detail-tabs .tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('#job-detail-tabs .tab-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');

                this.store.currentTab = e.target.dataset.tab;
                if (this.store.currentTab === 'external') {
                    document.getElementById('tab-content-external').style.display = 'block';
                    document.getElementById('tab-content-internal').style.display = 'none';
                } else {
                    document.getElementById('tab-content-external').style.display = 'none';
                    document.getElementById('tab-content-internal').style.display = 'block';
                }
                this.loadResults(this.store.currentJobId);
            });
        });

        // 分組選擇
        const extGroupSelect = document.getElementById('results-group-select');
        if (extGroupSelect) {
            extGroupSelect.addEventListener('change', (e) => {
                this.store.currentGroupBy = e.target.value;
                this.store.currentPage = 1;
                this.store.detailSort = { key: null, asc: true };
                this.store.detailColFilters = {};
                this.store.extSelectedUrls.clear();
                if (this.extDataTable) this.extDataTable.clearSelection();
                this.loadResults(this.store.currentJobId);
            });
        }

        const intGroupSelect = document.getElementById('internal-results-group-select');
        if (intGroupSelect) {
            intGroupSelect.addEventListener('change', (e) => {
                this.store.internalGroupBy = e.target.value;
                this.store.internalCurrentPage = 1;
                this.store.internalSort = { key: null, asc: true };
                this.store.internalColFilters = {};
                this.store.intSelectedUrls.clear();
                if (this.intDataTable) this.intDataTable.clearSelection();
                this.loadResults(this.store.currentJobId);
            });
        }

        // 表格選擇變更
        if (this.extDataTable) {
            this.extDataTable.addEventListener('selection-change', (e) => {
                this.store.extSelectedUrls = new Set(e.detail.selectedKeys);
                this.tableManager.updateExtToolbarButtons(this.store);
            });
        }

        if (this.intDataTable) {
            this.intDataTable.addEventListener('selection-change', (e) => {
                this.store.intSelectedUrls = new Set(e.detail.selectedKeys);
                this.tableManager.updateIntToolbarButtons(this.store);
            });
        }

        // ── 重新探測與匯出選取按鈕 ──────────────────────────────────────────
        const btnExtReprobe = document.getElementById('btn-ext-reprobe-selected');
        if (btnExtReprobe) {
            btnExtReprobe.addEventListener('click', async () => {
                if (this.store.extSelectedUrls.size === 0) return;
                const isSourceGroup = this.store.currentGroupBy === 'source';
                const typeLabel = isSourceGroup ? '關聯的自家網頁（內部連結）' : '外部連結';
                const ok = await showConfirm('重新探測', `確定要重新探測選取的 ${this.store.extSelectedUrls.size} 個${typeLabel}嗎？`);
                if (!ok) return;
                try {
                    btnExtReprobe.classList.add('loading');
                    const linkType = isSourceGroup ? 'internal' : 'external';
                    await api.post(`/api/jobs/${this.store.currentJobId}/reprobe`, {
                        link_type: linkType,
                        urls: Array.from(this.store.extSelectedUrls),
                        group_by: this.store.currentGroupBy
                    });
                    if (isSourceGroup) {
                        toast.success('已將關聯的自家網頁加入重新探測佇列');
                        this.store.intSummaryCache = { key: null, data: null };
                        this.loadInternalResultsPage(this.store.currentJobId);
                    } else {
                        toast.success('已將選取的外部連結設為待探測');
                    }
                    this.store.extSelectedUrls.clear();
                    if (this.extDataTable) this.extDataTable.clearSelection();
                    this.tableManager.updateExtToolbarButtons(this.store);
                    this.store.extSummaryCache = { key: null, data: null };
                    this.loadExternalResultsPage(this.store.currentJobId);
                    this.loadExternalSummary(this.store.currentJobId);
                    this.refreshJobDetail(this.store.currentJobId);
                } catch (err) {
                    toast.error(err.message || '探測失敗');
                } finally {
                    btnExtReprobe.classList.remove('loading');
                }
            });
        }

        const btnExtExportPartial = document.getElementById('btn-ext-export-selected');
        if (btnExtExportPartial) {
            btnExtExportPartial.addEventListener('click', async () => {
                if (this.store.extSelectedUrls.size === 0) return;
                try {
                    await api.download(`/api/jobs/${this.store.currentJobId}/export/partial`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            link_type: 'external',
                            urls: Array.from(this.store.extSelectedUrls),
                            group_by: this.store.currentGroupBy
                        })
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
                if (this.store.intSelectedUrls.size === 0) return;
                const ok = await showConfirm('重新探測', `確定要將選取的 ${this.store.intSelectedUrls.size} 個內部連結重新探測嗎？`);
                if (!ok) return;
                try {
                    btnIntReprobe.classList.add('loading');
                    const res = await api.post(`/api/jobs/${this.store.currentJobId}/reprobe`, {
                        link_type: 'internal',
                        urls: Array.from(this.store.intSelectedUrls),
                        group_by: this.store.internalGroupBy
                    });
                    toast.success(res.message || '重新探測已啟動');
                    this.store.intSelectedUrls.clear();
                    if (this.intDataTable) this.intDataTable.clearSelection();
                    this.tableManager.updateIntToolbarButtons(this.store);
                    this.store.intSummaryCache = { key: null, data: null };
                    this.loadInternalResultsPage(this.store.currentJobId);
                    this.loadInternalSummary(this.store.currentJobId);
                    this.refreshJobDetail(this.store.currentJobId);
                } catch (err) {
                    toast.error(err.message || '探測失敗');
                } finally {
                    btnIntReprobe.classList.remove('loading');
                }
            });
        }

        const btnIntExportPartial = document.getElementById('btn-int-export-selected');
        if (btnIntExportPartial) {
            btnIntExportPartial.addEventListener('click', async () => {
                if (this.store.intSelectedUrls.size === 0) return;
                try {
                    await api.download(`/api/jobs/${this.store.currentJobId}/export/partial`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            link_type: 'internal',
                            urls: Array.from(this.store.intSelectedUrls),
                            group_by: this.store.internalGroupBy
                        })
                    });
                    toast.success('匯出成功');
                } catch (err) {
                    toast.error('匯出失敗');
                }
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
            if (this.store.currentExcludeEnabled && this.store.currentExclude) params.append('exclude', this.store.currentExclude);
            return `${basePath}?${params.toString()}`;
        };

        const extExportCsv = document.getElementById('btn-export-csv');
        if (extExportCsv) {
            extExportCsv.addEventListener('click', async () => {
                if (!this.store.currentJobId) return;
                try {
                    await api.download(buildExportUrl(`/api/jobs/${this.store.currentJobId}/results/export`, 'csv', this.store.currentFilter, this.store.currentGroupBy));
                } catch (err) { toast.error('匯出 CSV 失敗：' + err.message); }
            });
        }

        const extExportJson = document.getElementById('btn-export-json');
        if (extExportJson) {
            extExportJson.addEventListener('click', async () => {
                if (!this.store.currentJobId) return;
                try {
                    await api.download(buildExportUrl(`/api/jobs/${this.store.currentJobId}/results/export`, 'json', this.store.currentFilter, this.store.currentGroupBy));
                } catch (err) { toast.error('匯出 JSON 失敗：' + err.message); }
            });
        }

        const intExportCsv = document.getElementById('btn-int-export-csv');
        if (intExportCsv) {
            intExportCsv.addEventListener('click', async () => {
                if (!this.store.currentJobId) return;
                try {
                    await api.download(buildExportUrl(`/api/jobs/${this.store.currentJobId}/internal-results/export`, 'csv', this.store.internalFilter, this.store.internalGroupBy));
                } catch (err) { toast.error('匯出 CSV 失敗：' + err.message); }
            });
        }

        const intExportJson = document.getElementById('btn-int-export-json');
        if (intExportJson) {
            intExportJson.addEventListener('click', async () => {
                if (!this.store.currentJobId) return;
                try {
                    await api.download(buildExportUrl(`/api/jobs/${this.store.currentJobId}/internal-results/export`, 'json', this.store.internalFilter, this.store.internalGroupBy));
                } catch (err) { toast.error('匯出 JSON 失敗：' + err.message); }
            });
        }

        // ── 檢視任務設定 (Web Component) ───────────────────────────────────
        const configModalEl = document.getElementById('job-config-modal');
        document.addEventListener('view-config', (e) => {
            if (!e.detail || !e.detail.job) return;
            const job = e.detail.job;
            const c = job.config;
            const container = document.getElementById('job-config-container');
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
                        { label: '探測略過連結', value: c.check_skipped_links === undefined ? '已停用 [舊任務]' : (c.check_skipped_links ? '已啟用' : '已停用') },
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
        if (this.jobControls) {
            this.jobControls.addEventListener('job-start', async () => {
                if (await showConfirm('啟動任務', '確定要開始執行此爬蟲任務嗎？', '啟動')) {
                    try {
                        await api.post(`/api/jobs/${this.store.currentJobId}/start`);
                        toast.success('任務已啟動！');
                        this.refreshJobDetail(this.store.currentJobId);
                    } catch (err) { toast.error(err.message); }
                }
            });
            this.jobControls.addEventListener('job-resume', async () => {
                if (await showConfirm('恢復任務', '確定要恢復執行此爬蟲任務嗎？', '恢復')) {
                    try {
                        await api.post(`/api/jobs/${this.store.currentJobId}/resume`);
                        toast.success('任務已恢復執行！');
                        this.refreshJobDetail(this.store.currentJobId);
                    } catch (err) { toast.error(err.message); }
                }
            });
            this.jobControls.addEventListener('job-pause', async () => {
                if (await showConfirm('暫停任務', '確定要暫停此爬蟲任務嗎？任務將在完成當前頁面後停止。', '暫停')) {
                    try {
                        await api.post(`/api/jobs/${this.store.currentJobId}/pause`);
                        toast.info('暫停指令已送出，任務將在完成當前頁面後停止。');
                        this.refreshJobDetail(this.store.currentJobId);
                        this.loadResults(this.store.currentJobId);
                    } catch (err) { toast.error(err.message); }
                }
            });
            this.jobControls.addEventListener('job-reset', async () => {
                if (await showConfirm('確定要重置任務嗎？', '這將清空所有爬取進度與外連結果，並將任務狀態退回初始設定。此操作無法復原。', '確定重置', true)) {
                    try {
                        await api.post(`/api/jobs/${this.store.currentJobId}/reset`);
                        toast.success('任務已重置');
                        this.store.invalidateCaches();
                        this.store.currentPage = 1;
                        this.store.internalCurrentPage = 1;
                        this.refreshJobDetail(this.store.currentJobId);
                        this.loadResults(this.store.currentJobId);
                    } catch (err) { toast.error(err.message); }
                }
            });

            this.jobControls.addEventListener('job-delete', async () => {
                if (await showConfirm('刪除任務', '確定要永久刪除此任務及其所有關聯資料嗎？此操作無法復原。', '確定刪除', true)) {
                    try {
                        await api.del(`/api/jobs/${this.store.currentJobId}`);
                        toast.success('任務已刪除');
                        window.location.hash = '#/jobs';
                    } catch (err) { toast.error(err.message); }
                }
            });
            this.jobControls.addEventListener('job-duplicate', () => { window.location.hash = `#/new?clone=${this.store.currentJobId}`; });
            this.jobControls.addEventListener('job-compare', () => { window.location.hash = `#/compare?target=${this.store.currentJobId}`; });
            this.jobControls.addEventListener('job-transfer', () => { window.location.hash = `#/transfer?job=${this.store.currentJobId}`; });
            this.jobControls.addEventListener('job-retry', async () => {
                if (await showConfirm('重試失敗連結？', '這會將狀態碼不是 2xx/3xx 的外部連結重新標記為等待中並繼續爬取。', '確定重試')) {
                    try {
                        await api.post(`/api/jobs/${this.store.currentJobId}/retry-failed`);
                        toast.success('失敗連結已重新排隊，任務啟動中...');
                        this.store.invalidateCaches();
                        this.refreshJobDetail(this.store.currentJobId);
                        this.loadResults(this.store.currentJobId);
                    } catch (err) { toast.error(err.message); }
                }
            });
        }

        if (this.jobExtStats) {
            this.jobExtStats.addEventListener('filter-change', (e) => {
                this.store.currentFilter = e.detail.filter;
                this.store.currentPage = 1;
                this.store.extSelectedUrls.clear();
                if (this.extDataTable) this.extDataTable.clearSelection();
                this.loadExternalResultsPage(this.store.currentJobId);
            });
        }

        if (this.jobIntStats) {
            this.jobIntStats.addEventListener('filter-change', (e) => {
                this.store.internalFilter = e.detail.filter;
                this.store.internalCurrentPage = 1;
                this.store.intSelectedUrls.clear();
                if (this.intDataTable) this.intDataTable.clearSelection();
                this.loadInternalResultsPage(this.store.currentJobId);
            });
        }

        if (this.extDataTable) {
            this.extDataTable.addEventListener('page-change', (e) => {
                this.store.currentPage = e.detail.page;
                this.loadExternalResultsPage(this.store.currentJobId);
            });
            this.extDataTable.addEventListener('sort-change', (e) => {
                this.store.detailSort = { key: e.detail.key, asc: e.detail.asc };
                this.loadExternalResultsPage(this.store.currentJobId);
            });
            this.extDataTable.addEventListener('filter-change', (e) => {
                this.store.detailColFilters[e.detail.key] = e.detail.value;
                this.store.currentPage = 1;
                clearTimeout(this.store.extFilterTimeout);
                this.store.extFilterTimeout = setTimeout(() => {
                    this.loadExternalResultsPage(this.store.currentJobId);
                }, 300);
            });
        }

        if (this.intDataTable) {
            this.intDataTable.addEventListener('page-change', (e) => {
                this.store.internalCurrentPage = e.detail.page;
                this.loadInternalResultsPage(this.store.currentJobId);
            });
            this.intDataTable.addEventListener('sort-change', (e) => {
                this.store.internalSort = { key: e.detail.key, asc: e.detail.asc };
                this.loadInternalResultsPage(this.store.currentJobId);
            });
            this.intDataTable.addEventListener('filter-change', (e) => {
                this.store.internalColFilters[e.detail.key] = e.detail.value;
                this.store.internalCurrentPage = 1;
                clearTimeout(this.store.intFilterTimeout);
                this.store.intFilterTimeout = setTimeout(() => {
                    this.loadInternalResultsPage(this.store.currentJobId);
                }, 300);
            });
        }
    }
}

/** 全域 JobDetailController 實例 */
export const jobDetailController = new JobDetailController();

/**
 * 向下相容的初始化任務詳情頁面函式
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>}
 */
export async function initJobDetailPage(jobId) {
    return jobDetailController.init(jobId);
}

/**
 * 向下相容的銷毀任務詳情頁面資源函式
 * @returns {void}
 */
export function destroyJobDetailPage() {
    return jobDetailController.destroy();
}
