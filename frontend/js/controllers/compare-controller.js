/**
 * compare-controller.js — 任務比對頁面控制器（ESM Controller）
 *
 * 協調 CompareStore 與 UI 互動，處理任務比對頁面之動態渲染、
 * 表格更新、頁籤切換與 CSV/JSON 匯出。
 */

import * as api from '../api.js';
import { toast } from '../components/toast.js';
import { CompareStore } from '../stores/compare-store.js';

/**
 * 建立一個文字節點或帶有 className 的 span
 * @param {string|number|null} text - 文字內容
 * @param {string} [className=''] - 附加的 CSS 類別
 * @returns {Text|HTMLSpanElement}
 */
function createTextNode(text, className = '') {
    if (!className) return document.createTextNode(text || '-');
    const span = document.createElement('span');
    span.className = className;
    span.textContent = text || '-';
    return span;
}

/**
 * 建立一個帶有 className 的 span 元素
 * @param {string|number|null} text - 內容
 * @param {string} [className=''] - 附加 CSS 類別
 * @returns {HTMLSpanElement|Text}
 */
function createCell(text, className = '') {
    return createTextNode(text, className);
}

/**
 * 渲染網址清單 (List)
 * @param {Array<string>} urls - URL 清單
 * @param {string} [className='truncate font-mono text-link'] - 附加的 CSS 類別
 * @returns {HTMLDivElement|Text}
 */
function renderUrlArrayNode(urls, className = 'truncate font-mono text-link') {
    if (!urls || urls.length === 0) return createTextNode('-');
    const div = document.createElement('div');
    div.style.display = 'flex';
    div.style.flexDirection = 'column';
    div.style.gap = '0.25rem';
    const displayLimit = 5;
    const displayList = urls.slice(0, displayLimit);
    displayList.forEach(u => {
        const a = document.createElement('a');
        a.href = u;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.className = className;
        a.style.maxWidth = '250px';
        a.style.display = 'inline-block';
        a.textContent = u;
        a.title = u;
        div.appendChild(a);
    });
    if (urls.length > displayLimit) {
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.style.alignSelf = 'flex-start';
        badge.textContent = '及其它';
        div.appendChild(badge);
    }
    return div;
}

/**
 * 渲染單一網址
 * @param {string|null} url - 網址
 * @param {string} [className='truncate font-mono text-link'] - 附加的 CSS 類別
 * @returns {HTMLAnchorElement|Text}
 */
function renderSingleUrlNode(url, className = 'truncate font-mono text-link') {
    if (!url) return createTextNode('-');
    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = className;
    a.style.display = 'inline-block';
    a.style.verticalAlign = 'middle';
    a.textContent = url;
    a.title = url;
    return a;
}

/**
 * 渲染網域 (Domain) 節點（完全對齊任務詳情風格）
 * @param {string|null} domain - 網域字串
 * @returns {HTMLAnchorElement|Text}
 */
function renderDomainNode(domain) {
    if (!domain) return createTextNode('-');
    const url = domain.startsWith('http://') || domain.startsWith('https://') ? domain : `http://${domain}`;
    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'truncate font-mono text-link';
    a.style.maxWidth = '200px';
    a.style.display = 'inline-block';
    a.style.verticalAlign = 'middle';
    a.textContent = domain;
    a.title = url;
    return a;
}

/**
 * 渲染 HTTP 狀態碼節點（對齊任務詳情色彩）
 * @param {number|string|null} code - HTTP 狀態碼
 * @returns {HTMLSpanElement|Text}
 */
function renderHttpStatusCode(code) {
    if (code === null || code === undefined || code === '') return createTextNode('-', 'text-muted');
    const span = document.createElement('span');
    span.style.display = 'inline-block';
    span.textContent = code;
    const numCode = Number(code);
    if (numCode >= 200 && numCode < 300) span.className = 'text-success font-mono font-semibold';
    else if (numCode >= 300 && numCode < 400) span.className = 'text-warning font-mono font-semibold';
    else if (numCode >= 400) span.className = 'text-danger font-mono font-semibold';
    else span.className = 'text-muted font-mono';
    return span;
}

/**
 * 渲染錯誤訊息節點
 * @param {string|null} msg - 錯誤訊息
 * @param {string} [maxWidth='180px'] - 最大寬度
 * @returns {HTMLSpanElement|Text}
 */
function renderErrorMessage(msg, maxWidth = '180px') {
    if (!msg) return createTextNode('-', 'text-muted');
    const span = document.createElement('span');
    span.className = 'truncate text-danger text-xs';
    span.style.maxWidth = maxWidth;
    span.style.display = 'inline-block';
    span.style.verticalAlign = 'middle';
    span.title = msg;
    span.textContent = msg;
    return span;
}

/**
 * 淨化 CSV 欄位數值以防範注入攻擊
 * @param {any} val - 欲淨化的數值
 * @returns {any} 淨化後的數值
 */
function _sanitizeCsv(val) {
    if (typeof val === 'string' && /^[=+\-@]/.test(val)) return "'" + val;
    return val;
}

/**
 * 比對任務頁面的控制器 (Controller)
 * 負責綁定 DOM 事件、發送 API 請求、與 `<link-table>` 互動，以及觸發 Store 更新。
 */
export class CompareController {
    /**
     * 初始化 CompareController 實例
     * @param {CompareStore} [store=new CompareStore()] - CompareStore 實例
     */
    constructor(store = new CompareStore()) {
        /** @type {CompareStore} 狀態庫實例 */
        this.store = store;
        /** @type {boolean} 是否已綁定事件 */
        this.eventsBound = false;
    }

    /**
     * 綁定比對頁面的事件監聽器
     * @returns {void}
     */
    bindCompareEvents() {
        const runBtn = document.getElementById('btn-run-compare');
        if (!runBtn) return;

        runBtn.addEventListener('click', async () => {
            const baseSelectEl = document.getElementById('compare-base-select');
            const targetSelectEl = document.getElementById('compare-target-select');
            const errorEl = document.getElementById('compare-error');
            const resultsAreaEl = document.getElementById('compare-results-area');

            const baseId = baseSelectEl.value;
            const targetId = targetSelectEl.value;

            if (!baseId || !targetId) {
                errorEl.textContent = '請完整選擇基準任務與對照任務。';
                return;
            }

            if (baseId === targetId) {
                errorEl.textContent = '基準任務與對照任務不能為同一個。';
                return;
            }

            runBtn.classList.add('loading');
            runBtn.disabled = true;
            errorEl.textContent = '';

            try {
                const res = await this.store.fetchDiff(baseId, targetId);

                const extStatsEl = document.getElementById('compare-ext-stats');
                const intStatsEl = document.getElementById('compare-int-stats');

                if (extStatsEl && res.summary) {
                    extStatsEl.updateView(res.summary);
                }
                if (intStatsEl && res.internal && res.internal.summary) {
                    intStatsEl.updateView({
                        internal_degraded: res.internal.summary.degraded,
                        internal_recovered: res.internal.summary.recovered,
                        internal_persistently_failed: res.internal.summary.persistently_failed,
                        internal_new_pages: res.internal.summary.new_pages,
                        internal_removed_pages: res.internal.summary.removed_pages,
                    });
                }

                resultsAreaEl.style.display = 'flex';

                // 預設選擇外部連結比對
                const extScopeBtn = document.querySelector('#compare-scope-tabs .tab-btn[data-scope="external"]');
                if (extScopeBtn) extScopeBtn.click();
            } catch (err) {
                errorEl.textContent = err.message || '比對失敗';
            } finally {
                runBtn.classList.remove('loading');
                runBtn.disabled = false;
            }
        });

        // ── 比對範疇頁籤切換 (Scope Tabs: External vs Internal) ────────────────
        document.querySelectorAll('#compare-scope-tabs .tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#compare-scope-tabs .tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                const scope = btn.dataset.scope;
                const extStatsEl = document.getElementById('compare-ext-stats');
                const intStatsEl = document.getElementById('compare-int-stats');

                if (scope === 'external') {
                    if (extStatsEl) {
                        extStatsEl.style.display = 'block';
                        extStatsEl.activeFilter = 'ip_changed';
                    }
                    if (intStatsEl) intStatsEl.style.display = 'none';
                    this.store.setSort({ key: null, asc: true });
                    this.store.compareColFilters = {};
                    this.renderCompareTab('ip_changed');
                } else {
                    if (extStatsEl) extStatsEl.style.display = 'none';
                    if (intStatsEl) {
                        intStatsEl.style.display = 'block';
                        intStatsEl.activeFilter = 'internal_degraded';
                    }
                    this.store.setSort({ key: null, asc: true });
                    this.store.compareColFilters = {};
                    this.renderCompareTab('internal_degraded');
                }
            });
        });

        // ── 監聽比對 Web Component 的 filter-change 事件 ──────────────────────────
        const extStatsEl = document.getElementById('compare-ext-stats');
        const intStatsEl = document.getElementById('compare-int-stats');

        [extStatsEl, intStatsEl].forEach(statsEl => {
            if (statsEl) {
                statsEl.addEventListener('filter-change', (e) => {
                    const filterId = e.detail.filter;
                    this.store.setSort({ key: null, asc: true });
                    this.store.compareColFilters = {};
                    this.renderCompareTab(filterId);
                });
            }
        });

        const btnExportCsv = document.getElementById('btn-compare-export-csv');
        if (btnExportCsv) {
            btnExportCsv.addEventListener('click', () => this.exportCompareCsv());
        }

        const btnExportJson = document.getElementById('btn-compare-export-json');
        if (btnExportJson) {
            btnExportJson.addEventListener('click', () => this.exportCompareJson());
        }

        // ── 綁定排除網域 Modal 邏輯 (Compare) ─────────────────────────────────
        const openExcludeBtn = document.getElementById('btn-compare-exclude-modal');
        const excludeModalEl = document.getElementById('exclude-domains-modal');
        const excludeTextareaInput = document.getElementById('exclude-domains-textarea');
        const excludeEnabledCheckbox = document.getElementById('exclude-domains-enabled');
        const excludeSubmitBtn = document.getElementById('exclude-domains-submit');
        const excludeCloseBtn = document.getElementById('exclude-domains-close');
        const excludeCancelBtn = document.getElementById('exclude-domains-cancel');

        if (openExcludeBtn && excludeModalEl) {
            const closeExcludeModal = () => { excludeModalEl.style.display = 'none'; };

            openExcludeBtn.addEventListener('click', () => {
                const currentExclude = localStorage.getItem('link-checker-exclude-domains') || '';
                const isEnabled = localStorage.getItem('link-checker-exclude-enabled') !== 'false';
                if (excludeEnabledCheckbox) excludeEnabledCheckbox.checked = isEnabled;
                excludeTextareaInput.value = currentExclude.split(',').filter(Boolean).join('\n');
                excludeModalEl.style.display = 'flex';
                setTimeout(() => excludeTextareaInput.focus(), 50);
            });

            if (excludeCloseBtn) excludeCloseBtn.addEventListener('click', closeExcludeModal);
            if (excludeCancelBtn) excludeCancelBtn.addEventListener('click', closeExcludeModal);

            if (excludeSubmitBtn) {
                excludeSubmitBtn.addEventListener('click', () => {
                    if (document.getElementById('view-compare').style.display === 'none') return;

                    const isEnabled = excludeEnabledCheckbox ? excludeEnabledCheckbox.checked : true;
                    const lines = excludeTextareaInput.value.split('\n').map(s => s.trim()).filter(Boolean);
                    const newExclude = lines.join(',');

                    localStorage.setItem('link-checker-exclude-enabled', isEnabled);
                    localStorage.setItem('link-checker-exclude-domains', newExclude);

                    const isActive = isEnabled && newExclude;
                    openExcludeBtn.style.color = isActive ? 'var(--color-brand-500)' : '';
                    openExcludeBtn.style.borderColor = isActive ? 'var(--color-brand-500)' : '';
                    openExcludeBtn.style.background = isActive ? 'hsla(221, 83%, 53%, 0.1)' : '';

                    closeExcludeModal();

                    if (!runBtn.disabled && this.store.currentDiffData) {
                        runBtn.click();
                    }
                });
            }
        }
    }

    /**
     * 渲染指定的差異頁籤內容
     * @param {string} tabName - 頁籤名稱
     * @returns {Promise<void>}
     */
    async renderCompareTab(tabName) {
        this.store.setTab(tabName);

        const containerEl = document.getElementById('compare-details-container');
        if (!this.store.currentDiffData) return;
        
        let linkTable = containerEl.querySelector('link-table');
        if (linkTable) {
            linkTable.config = { ...linkTable.config, loading: true };
        } else {
            containerEl.replaceChildren();
            linkTable = document.createElement('link-table');
            linkTable.id = 'compare-data-table';
            containerEl.appendChild(linkTable);
            linkTable.config = { loading: true };
        }

        const data = await this.store.fetchItems();
        
        if (this.store.totalItems === 0) {
            containerEl.replaceChildren();
            const emptyDiv = document.createElement('div');
            emptyDiv.className = 'empty-state';
            const descDiv = document.createElement('div');
            descDiv.className = 'empty-state-desc';
            descDiv.textContent = '此項目無差異或查無結果';
            emptyDiv.appendChild(descDiv);
            containerEl.appendChild(emptyDiv);
            delete containerEl.dataset.renderedTab;
            return;
        }

        if (tabName === 'ip_changed') {
            this.store.currentCompareHeaders = [
                { label: '外部網域', key: 'domain', truncate: '200px', render: v => renderDomainNode(v) },
                { label: '舊 IP 位址', key: 'old_ip', className: 'font-mono text-sm text-muted', render: v => createTextNode(v) },
                { label: '新 IP 位址', key: 'new_ip', className: 'font-mono text-sm text-danger', render: v => createTextNode(v) },
                { label: '目標數量', key: 'url_count', className: 'font-semibold', align: 'center', render: v => createTextNode(v) },
                { label: '目標頁面', key: 'target_urls', sortable: false, filterable: false, render: v => renderUrlArrayNode(v) },
                { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v) }
            ];
        } else if (tabName === 'degraded' || tabName === 'recovered') {
            const isDeg = tabName === 'degraded';
            this.store.currentCompareHeaders = [
                { label: '目標頁面', key: 'target_url', truncate: '260px', render: v => renderSingleUrlNode(v) },
                { label: '原狀態', key: 'old_status', className: isDeg ? 'text-success' : 'text-danger', render: v => createTextNode(v || '連線失敗') },
                { label: '新狀態', key: 'new_status', className: isDeg ? 'text-danger' : 'text-success', render: v => createTextNode(v || '連線失敗') },
                { label: '新錯誤訊息 / 協定變遷', key: 'new_error', truncate: '180px', render: v => renderErrorMessage(v, '180px') },
                { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v) }
            ];
        } else if (tabName === 'new_links') {
            this.store.currentCompareHeaders = [
                { label: '目標頁面', key: 'target_url', truncate: '260px', render: v => renderSingleUrlNode(v) },
                { label: 'IP 位址', key: 'ip', className: 'font-mono text-sm', render: v => createTextNode(v) },
                { label: 'HTTPS', key: 'is_secure', align: 'center', render: v => v ? createCell('✓', 'text-success') : createCell('✗', 'text-danger') },
                { label: 'HTTP 狀態', key: 'status_code', align: 'center', render: v => renderHttpStatusCode(v) },
                { label: '錯誤訊息', key: 'error', truncate: '180px', render: v => renderErrorMessage(v, '180px') },
                { label: '來源數量', key: 'sources_count', className: 'font-semibold', align: 'center', render: (v, item) => createTextNode(v ?? (item.sources ? item.sources.length : 0)) },
                { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v) }
            ];
        } else if (tabName === 'removed_links') {
            this.store.currentCompareHeaders = [
                { label: '目標頁面', key: 'target_url', truncate: '260px', render: v => renderSingleUrlNode(v) },
                { label: '原 IP 位址', key: 'old_ip', className: 'font-mono text-sm text-muted', render: v => createTextNode(v) },
                { label: '原 HTTPS', key: 'old_is_secure', align: 'center', render: v => v ? createCell('✓', 'text-success') : createCell('✗', 'text-danger') },
                { label: '原 HTTP 狀態', key: 'old_status_code', align: 'center', render: v => renderHttpStatusCode(v) },
                { label: '原錯誤訊息', key: 'old_error', truncate: '180px', render: v => renderErrorMessage(v, '180px') },
                { label: '來源數量', key: 'sources_count', className: 'font-semibold', align: 'center', render: (v, item) => createTextNode(v ?? (item.sources ? item.sources.length : 0)) },
                { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v) }
            ];
        } else if (tabName.startsWith('internal_')) {
            const isDeg = tabName === 'internal_degraded';

            if (tabName === 'internal_new_pages') {
                this.store.currentCompareHeaders = [
                    { label: '目標頁面', key: 'url', truncate: '260px', render: v => renderSingleUrlNode(v) },
                    { label: 'HTTPS', key: 'is_secure', align: 'center', render: v => v ? createCell('✓', 'text-success') : createCell('✗', 'text-danger') },
                    { label: 'HTTP 狀態', key: 'status_code', align: 'center', render: v => renderHttpStatusCode(v) },
                    { label: '錯誤訊息', key: 'error', truncate: '180px', render: v => renderErrorMessage(v, '180px') },
                    { label: '探索深度', key: 'depth', className: 'font-mono text-sm', align: 'center', render: v => createTextNode(v) }
                ];
            } else if (tabName === 'internal_removed_pages') {
                this.store.currentCompareHeaders = [
                    { label: '目標頁面', key: 'url', truncate: '260px', render: v => renderSingleUrlNode(v) },
                    { label: '原 HTTPS', key: 'old_is_secure', align: 'center', render: v => v ? createCell('✓', 'text-success') : createCell('✗', 'text-danger') },
                    { label: '原 HTTP 狀態', key: 'old_status_code', align: 'center', render: v => renderHttpStatusCode(v) },
                    { label: '原錯誤訊息', key: 'old_error', truncate: '180px', render: v => renderErrorMessage(v, '180px') },
                    { label: '探索深度', key: 'depth', className: 'font-mono text-sm', align: 'center', render: v => createTextNode(v) }
                ];
            } else {
                this.store.currentCompareHeaders = [
                    { label: '目標頁面', key: 'url', truncate: '260px', render: v => renderSingleUrlNode(v) },
                    { label: '原狀態', key: 'old_status', className: isDeg ? 'text-success' : 'text-danger', render: v => createTextNode(v || '連線失敗') },
                    { label: '新狀態', key: 'new_status', className: isDeg ? 'text-danger' : 'text-success', render: v => createTextNode(v || '連線失敗') },
                    { label: '新錯誤訊息 / 協定變遷', key: 'new_error', truncate: '180px', render: v => renderErrorMessage(v, '180px') },
                    { label: '探索深度', key: 'depth', className: 'font-mono text-sm', render: v => createTextNode(v) }
                ];
            }
        }

        let tableEl = containerEl.querySelector('link-table');
        if (!tableEl) {
            containerEl.replaceChildren();
            tableEl = document.createElement('link-table');
            tableEl.id = 'compare-data-table';

            tableEl.addEventListener('sort-change', (e) => {
                this.store.setSort(e.detail);
                this.renderCompareTab(this.store.currentTab);
            });
            tableEl.addEventListener('filter-change', (e) => {
                this.store.setFilter(e.detail.key, e.detail.value);
                this.renderCompareTab(this.store.currentTab);
            });
            tableEl.addEventListener('page-change', (e) => {
                this.store.setPage(e.detail.page);
                this.renderCompareTab(this.store.currentTab);
            });

            containerEl.appendChild(tableEl);
        }
        containerEl.dataset.renderedTab = tabName;

        tableEl.config = {
            headers: this.store.currentCompareHeaders,
            data: data,
            sort: this.store.compareSort,
            colFilters: this.store.compareColFilters,
            pagination: { current: this.store.currentPage, total: this.store.getTotalPages() },
            loading: false
        };
    }

    /**
     * 匯出差異資料為 JSON 格式
     * @returns {void}
     */
    exportCompareJson() {
        if (!this.store.baseId || !this.store.targetId) return;
        let cat = this.store.currentTab;
        if (cat.startsWith('internal_')) cat = cat.replace('internal_', 'int_');
        else cat = 'ext_' + cat;
        
        const url = `/api/jobs/${this.store.baseId}/diff/export?compare_with=${this.store.targetId}&category=${cat}&format=json`;
        window.open(url, '_blank');
    }

    /**
     * 匯出差異資料為 CSV 格式
     * @returns {void}
     */
    exportCompareCsv() {
        if (!this.store.baseId || !this.store.targetId) return;
        let cat = this.store.currentTab;
        if (cat.startsWith('internal_')) cat = cat.replace('internal_', 'int_');
        else cat = 'ext_' + cat;
        
        const url = `/api/jobs/${this.store.baseId}/diff/export?compare_with=${this.store.targetId}&category=${cat}&format=csv`;
        window.open(url, '_blank');
    }

    /**
     * 銷毀比對頁面資源
     * @returns {void}
     */
    destroy() {
        this.store.reset();
        const resultsAreaEl = document.getElementById('compare-results-area');
        if (resultsAreaEl) resultsAreaEl.style.display = 'none';
    }

    /**
     * 初始化任務比對頁面
     * @param {string|null} baseJobId - (可選) 欲預設選取的基準任務 ID
     * @param {string|null} targetJobId - (可選) 欲預設選取的對照任務 ID
     * @returns {Promise<void>}
     */
    async init(baseJobId = null, targetJobId = null) {
        if (!this.eventsBound) {
            this.bindCompareEvents();
            this.eventsBound = true;
        }

        this.destroy(); // 重置狀態

        const baseSelectEl = document.getElementById('compare-base-select');
        const targetSelectEl = document.getElementById('compare-target-select');
        const runBtn = document.getElementById('btn-run-compare');
        const errorEl = document.getElementById('compare-error');

        if (!baseSelectEl || !targetSelectEl) return;

        errorEl.textContent = '';

        baseSelectEl.options.length = 0;
        baseSelectEl.options.add(new Option('載入中...', ''));
        targetSelectEl.options.length = 0;
        targetSelectEl.options.add(new Option('載入中...', ''));
        runBtn.disabled = true;

        try {
            const jobs = await api.get('/api/jobs?status=completed');
            if (jobs.length === 0) {
                baseSelectEl.options.length = 0;
                baseSelectEl.options.add(new Option('無已完成任務', ''));
                targetSelectEl.options.length = 0;
                targetSelectEl.options.add(new Option('無已完成任務', ''));
                return;
            }

            const groups = {};
            jobs.forEach(j => {
                if (!groups[j.start_url]) groups[j.start_url] = [];
                groups[j.start_url].push(j);
            });

            baseSelectEl.replaceChildren();
            targetSelectEl.replaceChildren();

            const createDefaultOption = () => {
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = '-- 請選擇任務 --';
                return opt;
            };
            baseSelectEl.appendChild(createDefaultOption());
            targetSelectEl.appendChild(createDefaultOption());

            for (const [url, groupJobs] of Object.entries(groups)) {
                const optgroupBase = document.createElement('optgroup');
                optgroupBase.label = url;
                const optgroupTarget = document.createElement('optgroup');
                optgroupTarget.label = url;

                groupJobs.forEach(j => {
                    const optText = `${api.formatShortUuid(j.id)} (${api.formatLocalTime(j.created_at)})`;

                    const optBase = document.createElement('option');
                    optBase.value = j.id;
                    optBase.textContent = optText;
                    optgroupBase.appendChild(optBase);

                    const optTarget = document.createElement('option');
                    optTarget.value = j.id;
                    optTarget.textContent = optText;
                    optgroupTarget.appendChild(optTarget);
                });
                baseSelectEl.appendChild(optgroupBase);
                targetSelectEl.appendChild(optgroupTarget);
            }
            runBtn.disabled = false;

            if (baseJobId) {
                baseSelectEl.value = baseJobId;
            }

            if (targetJobId) {
                targetSelectEl.value = targetJobId;
            }

            const openExcludeBtn = document.getElementById('btn-compare-exclude-modal');
            if (openExcludeBtn) {
                const currentExclude = localStorage.getItem('link-checker-exclude-domains') || '';
                const isEnabled = localStorage.getItem('link-checker-exclude-enabled') !== 'false';
                const isActive = isEnabled && currentExclude;
                openExcludeBtn.style.color = isActive ? 'var(--color-brand-500)' : '';
                openExcludeBtn.style.borderColor = isActive ? 'var(--color-brand-500)' : '';
                openExcludeBtn.style.background = isActive ? 'hsla(221, 83%, 53%, 0.1)' : '';
            }
        } catch (err) {
            errorEl.textContent = '無法載入歷史任務：' + err.message;
        }
    }
}
