/**
 * compare.js — 任務比對專屬頁面邏輯（ESM）
 */

import * as api from './api.js';
import { toast } from './components/toast.js';

/** @type {Object|null} 目前比對的差異資料 */
let _currentDiffData = null;
/** @type {boolean} 是否已綁定比對事件 */
let _eventsBound = false;
/** @type {string} 目前選取的差異頁籤 */
let _currentTab = 'ip_changed';
/** @type {{key: string|null, asc: boolean}} 差異表格的排序狀態 */
let _compareSort = { key: null, asc: true };
/** @type {Object<string, string>} 差異表格的各欄位篩選條件 */
let _compareColFilters = {};
/** @type {Array<{label: string, key: string|null, sortable?: boolean, filterable?: boolean}>} 目前差異表格的表頭設定 */
let _currentCompareHeaders = [];

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
 * 綁定比對頁面的事件監聽器
 * @returns {void} 無回傳值
 */
function bindCompareEvents() {
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
            const excludeDomains = localStorage.getItem('link-checker-exclude-domains') || '';
            const excludeEnabled = localStorage.getItem('link-checker-exclude-enabled') !== 'false';
            let url = `/api/jobs/${baseId}/diff?compare_with=${targetId}`;
            if (excludeEnabled && excludeDomains) {
                url += `&exclude=${encodeURIComponent(excludeDomains)}`;
            }
            const res = await api.get(url);
            _currentDiffData = res;

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

            renderCompareTab('ip_changed');
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
            _compareSort = { key: null, asc: true };
            _compareColFilters = {};
            renderCompareTab(card.dataset.diffTab);
        });
    });

    const btnExportCsv = document.getElementById('btn-compare-export-csv');
    if (btnExportCsv) {
        btnExportCsv.addEventListener('click', exportCompareCsv);
    }

    const btnExportJson = document.getElementById('btn-compare-export-json');
    if (btnExportJson) {
        btnExportJson.addEventListener('click', exportCompareJson);
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

        excludeCloseBtn.addEventListener('click', closeExcludeModal);
        excludeCancelBtn.addEventListener('click', closeExcludeModal);

        excludeSubmitBtn.addEventListener('click', async () => {
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

            if (!runBtn.disabled && _currentDiffData) {
                runBtn.click();
            }
        });
    }
}

/**
 * 渲染指定的差異頁籤內容
 * @param {string} tabName - 頁籤名稱
 * @returns {void} 無回傳值
 */
/**
 * 建立一個文字節點或帶有 className 的 span
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
    urls.forEach(u => {
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
    if (urls.length >= 10) {
        const truncLi = document.createElement('li');
        truncLi.className = 'text-xs text-muted';
        truncLi.style.marginTop = '0.25rem';
        truncLi.textContent = '... (清單過長已截斷)';
        ul.appendChild(truncLi);
    }
    div.appendChild(ul);
    return div;
}

/**
 * 渲染單一網址
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

function renderCompareTab(tabName) {
    _currentTab = tabName;

    const containerEl = document.getElementById('compare-details-container');
    if (!_currentDiffData || !_currentDiffData.details[tabName]) return;

    let data = _currentDiffData.details[tabName];
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
        _currentCompareHeaders = [
            { label: '網域', key: 'domain', truncate: '200px', className: 'font-mono font-medium', render: v => createTextNode(v) },
            { label: '舊 IP 位址', key: 'old_ip', className: 'font-mono text-xs text-muted', render: v => createTextNode(v) },
            { label: '新 IP 位址', key: 'new_ip', className: 'font-mono text-xs text-danger', render: v => createTextNode(v) },
            { label: '影響 URL 數', key: 'url_count', className: 'font-semibold', render: v => createTextNode(v) },
            { label: '目標頁面 清單', key: 'target_urls', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, '') },
            { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, 'text-muted') }
        ];
    } else if (tabName === 'degraded' || tabName === 'recovered') {
        const isDeg = tabName === 'degraded';
        _currentCompareHeaders = [
            { label: '目標頁面', key: 'target_url', truncate: '260px', render: v => renderSingleUrlNode(v, 'text-muted') },
            { label: '原狀態', key: 'old_status', className: isDeg ? 'text-success' : 'text-danger', render: v => createTextNode(v || '連線失敗') },
            { label: '新狀態', key: 'new_status', className: isDeg ? 'text-danger' : 'text-success', render: v => createTextNode(v || '連線失敗') },
            { label: '新錯誤訊息', key: 'new_error', className: 'text-xs text-muted', truncate: '160px', render: v => createTextNode(v) },
            { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, 'text-muted') }
        ];
    } else if (tabName === 'security_downgraded') {
        _currentCompareHeaders = [
            { label: '目標頁面', key: 'target_url', truncate: '260px', render: v => renderSingleUrlNode(v, 'text-muted') },
            { label: '安全狀態變化', key: 'status', sortable: false, filterable: false, render: () => createTextNode('HTTPS ➔ HTTP', 'text-warning text-sm') },
            { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, 'text-muted') }
        ];
    } else if (tabName === 'new_links') {
        _currentCompareHeaders = [
            { label: '目標頁面', key: 'target_url', truncate: '260px', render: v => renderSingleUrlNode(v, 'text-muted') },
            { label: 'IP 位址', key: 'ip', className: 'font-mono text-xs', render: v => createTextNode(v) },
            { label: 'HTTP 狀態', key: 'status_code', render: v => createTextNode(v, !v ? 'text-muted' : (v >= 400 ? 'text-danger' : 'text-success')) },
            { label: '錯誤訊息', key: 'error', className: 'text-xs text-muted', truncate: '160px', render: v => createTextNode(v) },
            { label: '來源頁面', key: 'sources', sortable: false, filterable: false, render: v => renderUrlArrayNode(v, 'text-muted') }
        ];
    } else if (tabName === 'removed_links') {
        _currentCompareHeaders = [
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
        
        // 綁定排序與篩選事件 (前端實作)
        linkTable.addEventListener('sort-change', (e) => {
            _compareSort = e.detail;
            renderCompareTab(_currentTab);
        });
        linkTable.addEventListener('filter-change', (e) => {
            _compareColFilters[e.detail.key] = e.detail.value;
            renderCompareTab(_currentTab);
        });
        
        containerEl.appendChild(linkTable);
    }
    containerEl.dataset.renderedTab = tabName;

    const filteredData = _getFilteredData();
    
    linkTable.config = {
        headers: _currentCompareHeaders,
        data: filteredData,
        sort: _compareSort,
        colFilters: _compareColFilters,
        pagination: { current: 1, total: 1 }, // 比較頁面不作分頁
        loading: false
    };
}



/**
 * 取得經過過濾與排序後的差異資料
 * @returns {Array<Object>} 處理後的資料陣列
 */
function _getFilteredData() {
    if (!_currentDiffData || !_currentDiffData.details[_currentTab]) return [];
    let data = [..._currentDiffData.details[_currentTab]];

    if (_currentTab === 'ip_changed') {
        const grouped = {};
        data.forEach(item => {
            let domain = '';
            try {
                domain = new URL(item.target_url).hostname;
            } catch (e) {
                domain = item.target_url;
            }
            const key = `${domain}|${item.old_ip}|${item.new_ip}`;
            if (!grouped[key]) {
                grouped[key] = {
                    domain: domain,
                    old_ip: item.old_ip,
                    new_ip: item.new_ip,
                    url_count: 0,
                    target_urls: new Set(),
                    sources: new Set()
                };
            }
            grouped[key].url_count += 1;
            if (grouped[key].target_urls.size < 10) {
                grouped[key].target_urls.add(item.target_url);
            }
            if (item.sources) {
                item.sources.forEach(src => {
                    if (grouped[key].sources.size < 10) {
                        grouped[key].sources.add(src);
                    }
                });
            }
        });
        data = Object.values(grouped).map(g => ({
            ...g,
            target_urls: Array.from(g.target_urls).sort(),
            sources: Array.from(g.sources).sort()
        }));
    }

    for (const [k, v] of Object.entries(_compareColFilters)) {
        if (!v) continue;
        data = data.filter(item => {
            let val = item[k];
            return String(val || '').toLowerCase().includes(v);
        });
    }

    if (_compareSort.key) {
        data.sort((a, b) => {
            let valA = a[_compareSort.key];
            let valB = b[_compareSort.key];
            if (valA === undefined || valA === null) valA = '';
            if (valB === undefined || valB === null) valB = '';
            if (typeof valA === 'number' && typeof valB === 'number') return _compareSort.asc ? valA - valB : valB - valA;
            valA = String(valA).toLowerCase();
            valB = String(valB).toLowerCase();
            if (valA < valB) return _compareSort.asc ? -1 : 1;
            if (valA > valB) return _compareSort.asc ? 1 : -1;
            return 0;
        });
    } else if (_currentTab === 'ip_changed') {
        data.sort((a, b) => b.url_count - a.url_count);
    }

    return data;
}

/**
 * 匯出差異資料為 JSON 格式
 * @returns {void}
 */
function exportCompareJson() {
    const data = _getFilteredData();
    if (!data.length) {
        toast.warning('目前無資料可匯出');
        return;
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `compare_${_currentTab}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
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
 * 匯出差異資料為 CSV 格式
 * @returns {void}
 */
function exportCompareCsv() {
    const data = _getFilteredData();
    if (!data.length) {
        toast.warning('目前無資料可匯出');
        return;
    }

    let headers = [];
    const tabName = _currentTab;
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
    a.download = `compare_${_currentTab}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

/**
 * 初始化任務比對頁面
 * @param {string|null} baseJobId - (可選) 欲預設選取的基準任務 ID
 * @returns {Promise<void>} 無回傳值
 */
export async function initComparePage(baseJobId = null, targetJobId = null) {
    if (!_eventsBound) {
        bindCompareEvents();
        _eventsBound = true;
    }

    const baseSelectEl = document.getElementById('compare-base-select');
    const targetSelectEl = document.getElementById('compare-target-select');
    const runBtn = document.getElementById('btn-run-compare');
    const errorEl = document.getElementById('compare-error');
    const resultsAreaEl = document.getElementById('compare-results-area');

    if (!baseSelectEl || !targetSelectEl) return;

    resultsAreaEl.style.display = 'none';
    errorEl.textContent = '';
    _currentDiffData = null;

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

        // 依據起始網址分類至 optgroup，方便使用者查找同網站的歷史紀錄
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