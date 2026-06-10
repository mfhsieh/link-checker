/**
 * compare.js — 任務比對專屬頁面邏輯（ESM）
 */

import * as api from './api.js';
import { toast } from './toast.js';

let _currentDiffData = null;
let _eventsBound = false;
let _currentTab = 'ip_changed';
let _compareSort = { key: null, asc: true };
let _compareColFilters = {};
let _currentCompareHeaders = [];

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
            const excludeDomains = localStorage.getItem('ext-link-checker-exclude-domains') || '';
            const excludeEnabled = localStorage.getItem('ext-link-checker-exclude-enabled') !== 'false';
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
            const currentExclude = localStorage.getItem('ext-link-checker-exclude-domains') || '';
            const isEnabled = localStorage.getItem('ext-link-checker-exclude-enabled') !== 'false';
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

            localStorage.setItem('ext-link-checker-exclude-enabled', isEnabled);
            localStorage.setItem('ext-link-checker-exclude-domains', newExclude);

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

    if (tabName === 'ip_changed') _currentCompareHeaders = [{ label: '目標 URL', key: 'target_url' }, { label: '舊 IP 位址', key: 'old_ip' }, { label: '新 IP 位址', key: 'new_ip' }, { label: '來源頁面', key: 'sources', sortable: false, filterable: false }];
    else if (tabName === 'degraded' || tabName === 'recovered') _currentCompareHeaders = [{ label: '目標 URL', key: 'target_url' }, { label: '原狀態', key: 'old_status' }, { label: '新狀態', key: 'new_status' }, { label: '新錯誤訊息', key: 'new_error' }, { label: '來源頁面', key: 'sources', sortable: false, filterable: false }];
    else if (tabName === 'security_downgraded') _currentCompareHeaders = [{ label: '目標 URL', key: 'target_url' }, { label: '安全狀態變化', key: 'status', sortable: false, filterable: false }, { label: '來源頁面', key: 'sources', sortable: false, filterable: false }];
    else if (tabName === 'new_links') _currentCompareHeaders = [{ label: '目標 URL', key: 'target_url' }, { label: 'IP 位址', key: 'ip' }, { label: 'HTTP 狀態', key: 'status_code' }, { label: '錯誤訊息', key: 'error' }, { label: '來源頁面', key: 'sources', sortable: false, filterable: false }];
    else if (tabName === 'removed_links') _currentCompareHeaders = [{ label: '目標 URL', key: 'target_url' }, { label: '原 IP 位址', key: 'old_ip' }, { label: '原 HTTP 狀態', key: 'old_status_code' }, { label: '原錯誤訊息', key: 'old_error' }, { label: '來源頁面', key: 'sources', sortable: false, filterable: false }];

    let tableEl = containerEl.querySelector('.table');
    if (!tableEl || containerEl.dataset.renderedTab !== tabName) {
        containerEl.replaceChildren();
        const wrapperEl = document.createElement('div');
        wrapperEl.className = 'table-wrapper';
        tableEl = document.createElement('table');
        tableEl.className = 'table';
        const theadEl = document.createElement('thead');
        const trHeadEl = document.createElement('tr');

        _currentCompareHeaders.forEach(h => {
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
                sortIcon.textContent = _compareSort.key === h.key ? (_compareSort.asc ? '▲' : '▼') : '⇅';
                if (_compareSort.key === h.key) sortIcon.style.color = 'var(--color-brand-500)';
                headerTop.appendChild(sortIcon);

                headerTop.addEventListener('click', () => {
                    if (_compareSort.key === h.key) _compareSort.asc = !_compareSort.asc;
                    else { _compareSort.key = h.key; _compareSort.asc = true; }

                    trHeadEl.querySelectorAll('.sort-icon').forEach(icon => {
                        if (icon.dataset.key === _compareSort.key) {
                            icon.textContent = _compareSort.asc ? '▲' : '▼';
                            icon.style.color = 'var(--color-brand-500)';
                        } else {
                            icon.textContent = '⇅';
                            icon.style.color = 'var(--text-muted)';
                        }
                    });
                    renderCompareTbody(tableEl, tabName);
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
                filterInput.value = _compareColFilters[h.key] || '';

                filterInput.addEventListener('input', (e) => {
                    _compareColFilters[h.key] = e.target.value.toLowerCase();
                    renderCompareTbody(tableEl, tabName);
                });
                filterInput.addEventListener('click', e => e.stopPropagation());
                th.appendChild(filterInput);
            }

            trHeadEl.appendChild(th);
        });

        theadEl.appendChild(trHeadEl);
        tableEl.appendChild(theadEl);
        tableEl.appendChild(document.createElement('tbody'));
        wrapperEl.appendChild(tableEl);
        containerEl.appendChild(wrapperEl);
        containerEl.dataset.renderedTab = tabName;
    }

    renderCompareTbody(tableEl, tabName);
}

function renderCompareTbody(tableEl, tabName) {
    const data = _getFilteredData();
    let tbody = tableEl.querySelector('tbody');
    tbody.replaceChildren();

    if (data.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = _currentCompareHeaders.length;
        td.className = 'text-center text-muted';
        td.style.padding = '1rem';
        td.textContent = '本頁無符合篩選條件的結果';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
    }

    data.forEach(item => {
        const tr = document.createElement('tr');

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

        if (tabName === 'ip_changed') {
            const tdOld = document.createElement('td');
            tdOld.className = 'font-mono text-xs text-muted';
            tdOld.textContent = item.old_ip || '-';
            tr.appendChild(tdOld);

            const tdNew = document.createElement('td');
            tdNew.className = 'font-mono text-xs text-danger';
            tdNew.textContent = item.new_ip || '-';
            tr.appendChild(tdNew);

        } else if (tabName === 'degraded' || tabName === 'recovered') {
            const isDegraded = tabName === 'degraded';

            const tdOld = document.createElement('td');
            tdOld.className = isDegraded ? 'text-success' : 'text-danger';
            tdOld.textContent = item.old_status || '連線失敗';
            tr.appendChild(tdOld);

            const tdNew = document.createElement('td');
            tdNew.className = isDegraded ? 'text-danger' : 'text-success';
            tdNew.textContent = item.new_status || '連線失敗';
            tr.appendChild(tdNew);

            const tdErr = document.createElement('td');
            tdErr.className = 'text-xs text-muted truncate';
            tdErr.style.maxWidth = '160px';
            tdErr.title = item.new_error || '';
            tdErr.textContent = item.new_error || '-';
            tr.appendChild(tdErr);

        } else if (tabName === 'new_links') {
            const tdIp = document.createElement('td');
            tdIp.className = 'font-mono text-xs';
            tdIp.textContent = item.ip || '-';
            tr.appendChild(tdIp);

            const status = item.status_code;
            const tdStatus = document.createElement('td');
            tdStatus.className = !status ? 'text-muted' : (status >= 400 ? 'text-danger' : 'text-success');
            tdStatus.textContent = status || '-';
            tr.appendChild(tdStatus);

            const tdErr = document.createElement('td');
            tdErr.className = 'text-xs text-muted truncate';
            tdErr.style.maxWidth = '160px';
            tdErr.title = item.error || '';
            tdErr.textContent = item.error || '-';
            tr.appendChild(tdErr);

        } else if (tabName === 'removed_links') {
            const tdIp = document.createElement('td');
            tdIp.className = 'font-mono text-xs text-muted';
            tdIp.textContent = item.old_ip || '-';
            tr.appendChild(tdIp);

            const tdStatus = document.createElement('td');
            tdStatus.className = 'text-muted';
            tdStatus.textContent = item.old_status_code || '-';
            tr.appendChild(tdStatus);

            const tdErr = document.createElement('td');
            tdErr.className = 'text-xs text-muted truncate';
            tdErr.style.maxWidth = '160px';
            tdErr.title = item.old_error || '';
            tdErr.textContent = item.old_error || '-';
            tr.appendChild(tdErr);

        } else if (tabName === 'security_downgraded') {
            const tdSec = document.createElement('td');
            tdSec.className = 'text-warning text-sm';
            tdSec.textContent = 'HTTPS ➔ HTTP';
            tr.appendChild(tdSec);
        }

        const tdSources = document.createElement('td');
        if (item.sources && item.sources.length > 0) {
            const divSources = document.createElement('div');
            divSources.style.maxHeight = '150px';
            divSources.style.overflowY = 'auto';
            divSources.style.paddingRight = '4px';
            const ul = document.createElement('ul');
            ul.style.margin = '0';
            ul.style.paddingLeft = '0';
            ul.style.listStyle = 'none';
            ul.style.fontSize = '0.8125rem';
            item.sources.forEach(src => {
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
            divSources.appendChild(ul);
            tdSources.appendChild(divSources);
        } else {
            tdSources.className = 'text-muted';
            tdSources.textContent = '-';
        }
        tr.appendChild(tdSources);

        tbody.appendChild(tr);
    });
}

function _getFilteredData() {
    if (!_currentDiffData || !_currentDiffData.details[_currentTab]) return [];
    let data = [..._currentDiffData.details[_currentTab]];

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
    }

    return data;
}

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

function _sanitizeCsv(val) {
    if (typeof val === 'string' && /^[=+\-@]/.test(val)) return "'" + val;
    return val;
}

function exportCompareCsv() {
    const data = _getFilteredData();
    if (!data.length) {
        toast.warning('目前無資料可匯出');
        return;
    }

    let headers = [];
    const tabName = _currentTab;
    if (tabName === 'ip_changed') headers = ['目標 URL', '舊 IP 位址', '新 IP 位址', '來源頁面'];
    else if (tabName === 'degraded' || tabName === 'recovered') headers = ['目標 URL', '原狀態', '新狀態', '新錯誤訊息', '來源頁面'];
    else if (tabName === 'security_downgraded') headers = ['目標 URL', '安全狀態變化', '來源頁面'];
    else if (tabName === 'new_links') headers = ['目標 URL', 'IP 位址', 'HTTP 狀態', '錯誤訊息', '來源頁面'];
    else if (tabName === 'removed_links') headers = ['目標 URL', '原 IP 位址', '原 HTTP 狀態', '原錯誤訊息', '來源頁面'];

    let csvContent = '\uFEFF'; // BOM
    csvContent += headers.map(h => `"${h}"`).join(',') + '\n';

    data.forEach(item => {
        let row = [];
        row.push(_sanitizeCsv(item.target_url));

        if (tabName === 'ip_changed') {
            row.push(_sanitizeCsv(item.old_ip || ''));
            row.push(_sanitizeCsv(item.new_ip || ''));
        } else if (tabName === 'degraded' || tabName === 'recovered') {
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
export async function initComparePage(baseJobId = null) {
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
                const optText = `${j.id.substring(0, 8)}... (${new Date(j.created_at).toLocaleString('zh-TW')})`;

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

        const openExcludeBtn = document.getElementById('btn-compare-exclude-modal');
        if (openExcludeBtn) {
            const currentExclude = localStorage.getItem('ext-link-checker-exclude-domains') || '';
            const isEnabled = localStorage.getItem('ext-link-checker-exclude-enabled') !== 'false';
            const isActive = isEnabled && currentExclude;
            openExcludeBtn.style.color = isActive ? 'var(--color-brand-500)' : '';
            openExcludeBtn.style.borderColor = isActive ? 'var(--color-brand-500)' : '';
            openExcludeBtn.style.background = isActive ? 'hsla(221, 83%, 53%, 0.1)' : '';
        }
    } catch (err) {
        errorEl.textContent = '無法載入歷史任務：' + err.message;
    }
}