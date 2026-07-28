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
 * 渲染網址清單 (List)
 * @param {Array<string>} urls - URL 清單
 * @param {string} [className='text-muted'] - 附加的 CSS 類別
 * @returns {HTMLDivElement|Text}
 */
function renderUrlArrayNode(urls, className = 'text-muted') {
    if (!urls || urls.length === 0) return createTextNode('-');
    const div = document.createElement('div');
    div.style.maxHeight = '150px';
    div.style.overflowY = 'auto';
    div.style.paddingRight = '4px';
    const ul = document.createElement('ul');
    ul.style.margin = '0';
    ul.style.paddingLeft = '0';
    ul.style.listStyle = 'none';
    ul.style.fontSize = '0.8125rem';
    const displayLimit = 5;
    const displayList = urls.slice(0, displayLimit);
    displayList.forEach(u => {
        const li = document.createElement('li');
        li.className = 'truncate ' + className;
        li.style.maxWidth = '250px';
        li.style.marginBottom = '0.25rem';
        li.title = u;
        const a = document.createElement('a');
        a.href = u;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        if (className === 'text-muted') a.style.color = 'inherit';
        else a.className = 'text-link';
        a.textContent = u;
        li.appendChild(a);
        ul.appendChild(li);
    });
    if (urls.length > displayLimit) {
        const truncLi = document.createElement('li');
        truncLi.className = 'text-xs text-muted';
        truncLi.style.marginTop = '0.25rem';
        truncLi.textContent = '及其它';
        ul.appendChild(truncLi);
    }
    div.appendChild(ul);
    return div;
}

/**
 * 渲染單一網址
 * @param {string|null} url - 網址
 * @param {string} [className='text-link'] - 附加的 CSS 類別
 * @returns {HTMLAnchorElement|Text}
 */
function renderSingleUrlNode(url, className = 'text-link') {
    if (!url) return createTextNode('-');
    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = className;
    if (className === 'text-muted') a.style.color = 'inherit';
    a.textContent = url;
    a.title = url;
    return a;
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

                const setTextContent = (id, value) => {
                    const el = document.getElementById(id);
                    if (el) el.textContent = value ?? '-';
                };

                setTextContent('diff-stat-ip', res.summary.ip_changed);
                setTextContent('diff-stat-degraded', res.summary.degraded);
                setTextContent('diff-stat-recovered', res.summary.recovered);
                setTextContent('diff-stat-sec', res.summary.security_downgraded);
                setTextContent('diff-stat-new', res.summary.new_links);
                setTextContent('diff-stat-removed', res.summary.removed_links);

                resultsAreaEl.style.display = 'flex';

                document.querySelectorAll('#view-compare .diff-tab-card').forEach(c => c.classList.remove('active'));
                const firstTab = document.querySelector('#view-compare .diff-tab-card[data-diff-tab="ip_changed"]');
                if (firstTab) firstTab.classList.add('active');

                this.renderCompareTab('ip_changed');
            } catch (err) {
                errorEl.textContent = err.message || '比對失敗';
            } finally {
                runBtn.classList.remove('loading');
                runBtn.disabled = false;
            }
        });

        document.querySelectorAll('#view-compare .diff-tab-card').forEach(card => {
            card.addEventListener('click', () => {
                document.querySelectorAll('#view-compare .diff-tab-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                this.store.setSort({ key: null, asc: true });
                this.store.compareColFilters = {};
                this.renderCompareTab(card.dataset.diffTab);
            });
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
     * @returns {void}
     */
    renderCompareTab(tabName) {
        this.store.setTab(tabName);

        const containerEl = document.getElementById('compare-details-container');
        if (!this.store.currentDiffData || !this.store.currentDiffData.details[tabName]) return;

        let data = this.store.currentDiffData.details[tabName];
        if (data.length === 0) {
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
                { label: '網域', key: 'domain', truncate: '200px', className: 'font-mono font-medium', render: v => createTextNode(v) },
                { label: '舊 IP 位址', key: 'old_ip', className: 'font-mono text-xs text-muted', render: v => createTextNode(v) },
                { label: '新 IP 位址', key: 'new_ip', className: 'font-mono text-xs text-danger', render: v => createTextNode(v) },
                { label: '影響 URL 數', key: 'url_count', className: 'font-semibold', render: v => createTextNode(v) },
                { label: '目標頁面 清單', key: 'target_urls', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, '') },
                { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, 'text-muted') }
            ];
        } else if (tabName === 'degraded' || tabName === 'recovered') {
            const isDeg = tabName === 'degraded';
            this.store.currentCompareHeaders = [
                { label: '目標頁面', key: 'target_url', truncate: '260px', render: v => renderSingleUrlNode(v, 'text-muted') },
                { label: '原狀態', key: 'old_status', className: isDeg ? 'text-success' : 'text-danger', render: v => createTextNode(v || '連線失敗') },
                { label: '新狀態', key: 'new_status', className: isDeg ? 'text-danger' : 'text-success', render: v => createTextNode(v || '連線失敗') },
                { label: '新錯誤訊息', key: 'new_error', className: 'text-xs text-muted', truncate: '160px', render: v => createTextNode(v) },
                { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, 'text-muted') }
            ];
        } else if (tabName === 'security_downgraded') {
            this.store.currentCompareHeaders = [
                { label: '目標頁面', key: 'target_url', truncate: '260px', render: v => renderSingleUrlNode(v, 'text-muted') },
                { label: '安全狀態變化', key: 'status', sortable: false, filterable: false, render: () => createTextNode('HTTPS ➔ HTTP', 'text-warning text-sm') },
                { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, 'text-muted') }
            ];
        } else if (tabName === 'new_links') {
            this.store.currentCompareHeaders = [
                { label: '目標頁面', key: 'target_url', truncate: '260px', render: v => renderSingleUrlNode(v, 'text-muted') },
                { label: 'IP 位址', key: 'ip', className: 'font-mono text-xs', render: v => createTextNode(v) },
                { label: 'HTTP 狀態', key: 'status_code', render: v => createTextNode(v, !v ? 'text-muted' : (v >= 400 ? 'text-danger' : 'text-success')) },
                { label: '錯誤訊息', key: 'error', className: 'text-xs text-muted', truncate: '160px', render: v => createTextNode(v) },
                { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, 'text-muted') }
            ];
        } else if (tabName === 'removed_links') {
            this.store.currentCompareHeaders = [
                { label: '目標頁面', key: 'target_url', truncate: '260px', render: v => renderSingleUrlNode(v, 'text-muted') },
                { label: '原 IP 位址', key: 'old_ip', className: 'font-mono text-xs text-muted', render: v => createTextNode(v) },
                { label: '原 HTTP 狀態', key: 'old_status_code', className: 'text-muted', render: v => createTextNode(v) },
                { label: '原錯誤訊息', key: 'old_error', className: 'text-xs text-muted', truncate: '160px', render: v => createTextNode(v) },
                { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, 'text-muted') }
            ];
        }

        let linkTable = containerEl.querySelector('link-table');
        if (!linkTable) {
            containerEl.replaceChildren();
            linkTable = document.createElement('link-table');
            linkTable.id = 'compare-data-table';
            
            linkTable.addEventListener('sort-change', (e) => {
                this.store.setSort(e.detail);
                this.renderCompareTab(this.store.currentTab);
            });
            linkTable.addEventListener('filter-change', (e) => {
                this.store.setFilter(e.detail.key, e.detail.value);
                this.renderCompareTab(this.store.currentTab);
            });
            
            containerEl.appendChild(linkTable);
        }
        containerEl.dataset.renderedTab = tabName;

        const filteredData = this.store.getFilteredData();
        
        linkTable.config = {
            headers: this.store.currentCompareHeaders,
            data: filteredData,
            sort: this.store.compareSort,
            colFilters: this.store.compareColFilters,
            pagination: { current: 1, total: 1 },
            loading: false
        };
    }

    /**
     * 匯出差異資料為 JSON 格式
     * @returns {void}
     */
    exportCompareJson() {
        const data = this.store.getFilteredData();
        if (!data.length) {
            toast.warning('目前無資料可匯出');
            return;
        }
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `compare_${this.store.currentTab}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    /**
     * 匯出差異資料為 CSV 格式
     * @returns {void}
     */
    exportCompareCsv() {
        const data = this.store.getFilteredData();
        if (!data.length) {
            toast.warning('目前無資料可匯出');
            return;
        }

        let headers = [];
        const tabName = this.store.currentTab;
        if (tabName === 'ip_changed') headers = ['網域', '舊 IP 位址', '新 IP 位址', '影響 URL 數', '目標頁面 清單', '來源頁面'];
        else if (tabName === 'degraded' || tabName === 'recovered') headers = ['目標頁面', '原狀態', '新狀態', '新錯誤訊息', '來源頁面'];
        else if (tabName === 'security_downgraded') headers = ['目標頁面', '安全狀態變化', '來源頁面'];
        else if (tabName === 'new_links') headers = ['目標頁面', 'IP 位址', 'HTTP 狀態', '錯誤訊息', '來源頁面'];
        else if (tabName === 'removed_links') headers = ['目標頁面', '原 IP 位址', '原 HTTP 狀態', '原錯誤訊息', '來源頁面'];

        let csvContent = '\uFEFF'; // BOM
        csvContent += headers.map(h => `"${h}"`).join(',') + '\n';

        data.forEach(item => {
            let row = [];

            if (tabName === 'ip_changed') {
                row.push(_sanitizeCsv(item.domain));
                row.push(_sanitizeCsv(item.old_ip || ''));
                row.push(_sanitizeCsv(item.new_ip || ''));
                row.push(item.url_count);
                row.push(_sanitizeCsv((item.target_urls || []).join('\n')));
                row.push(_sanitizeCsv((item.sources || []).join('\n')));
            } else {
                row.push(_sanitizeCsv(item.target_url));

                if (tabName === 'degraded' || tabName === 'recovered') {
                    row.push(_sanitizeCsv(item.old_status || '連線失敗'));
                    row.push(_sanitizeCsv(item.new_status || '連線失敗'));
                    row.push(_sanitizeCsv(item.new_error || ''));
                } else if (tabName === 'security_downgraded') {
                    row.push('HTTPS ➔ HTTP');
                } else if (tabName === 'new_links') {
                    row.push(_sanitizeCsv(item.ip || ''));
                    row.push(_sanitizeCsv(item.status_code || ''));
                    row.push(_sanitizeCsv(item.error || ''));
                } else if (tabName === 'removed_links') {
                    row.push(_sanitizeCsv(item.old_ip || ''));
                    row.push(_sanitizeCsv(item.old_status_code || ''));
                    row.push(_sanitizeCsv(item.old_error || ''));
                }

                const sourcesStr = (item.sources || []).join('\n');
                row.push(_sanitizeCsv(sourcesStr));
            }

            csvContent += row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',') + '\n';
        });

        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `compare_${this.store.currentTab}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
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
