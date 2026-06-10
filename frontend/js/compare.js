/**
 * compare.js — 任務比對專屬頁面邏輯（ESM）
 */

import * as api from './api.js';
import { toast } from './toast.js';

let _currentDiffData = null;
let _eventsBound = false;
let _compareSearch = '';
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
            let url = `/api/jobs/${baseId}/diff?compare_with=${targetId}`;
            if (excludeDomains) {
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

    const searchInput = document.getElementById('compare-search');
    if (searchInput) {
        let debounceTimer;
        searchInput.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                _compareSearch = searchInput.value.trim().toLowerCase();
                if (_currentDiffData) {
                    renderCompareTab(_currentTab);
                }
            }, 300);
        });
    }

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
    const excludeSubmitBtn = document.getElementById('exclude-domains-submit');
    const excludeCloseBtn = document.getElementById('exclude-domains-close');
    const excludeCancelBtn = document.getElementById('exclude-domains-cancel');

    if (openExcludeBtn && excludeModalEl) {
        const closeExcludeModal = () => { excludeModalEl.style.display = 'none'; };

        openExcludeBtn.addEventListener('click', () => {
            const currentExclude = localStorage.getItem('ext-link-checker-exclude-domains') || '';
            excludeTextareaInput.value = currentExclude.split(',').filter(Boolean).join('\n');
            excludeModalEl.style.display = 'flex';
            setTimeout(() => excludeTextareaInput.focus(), 50);
        });

        excludeCloseBtn.addEventListener('click', closeExcludeModal);
        excludeCancelBtn.addEventListener('click', closeExcludeModal);

        excludeSubmitBtn.addEventListener('click', async () => {
            if (document.getElementById('view-compare').style.display === 'none') return;

            const lines = excludeTextareaInput.value.split('\n').map(s => s.trim()).filter(Boolean);
            const newExclude = lines.join(',');
            localStorage.setItem('ext-link-checker-exclude-domains', newExclude);

            openExcludeBtn.style.color = newExclude ? 'var(--color-brand-500)' : '';
            openExcludeBtn.style.borderColor = newExclude ? 'var(--color-brand-500)' : '';
            openExcludeBtn.style.background = newExclude ? 'hsla(221, 83%, 53%, 0.1)' : '';

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

    const descEl = document.getElementById('compare-tab-description');
    if (descEl) {
        const descMap = {
            ip_changed: '🚨 IP 異動：目標 IP 改變，需防範網域遭搶註或劫持',
            degraded: '⚠️ 狀態劣化：原本正常的連結變成失效或發生連線錯誤',
            recovered: '🟢 狀態復原：原本失效的連結已修復或恢復正常連線',
            security_downgraded: '🔓 安全降級：連線從安全的 HTTPS 降級為明文 HTTP 傳輸',
            new_links: '➕ 新增外連：新出現的外部連結，需防範未經授權之植入',
            removed_links: '➖ 消失外連：過去存在但本次掃描已移除的外部連結'
        };
        descEl.textContent = descMap[tabName] || '';
    }

    const containerEl = document.getElementById('compare-details-container');
    if (!_currentDiffData || !_currentDiffData.details[tabName]) return;

    let data = _currentDiffData.details[tabName];

    if (_compareSearch) {
        data = data.filter(item => {
            const tgt = (item.target_url || '').toLowerCase();
            const srcStr = (item.sources || []).join(' ').toLowerCase();
            return tgt.includes(_compareSearch) || srcStr.includes(_compareSearch);
        });
    }

    if (data.length === 0) {
        containerEl.innerHTML = '<div class="empty-state"><div class="empty-state-desc">此項目無差異或查無結果</div></div>';
        return;
    }

    let headers = [];
    if (tabName === 'ip_changed') headers = ['目標 URL', '舊 IP 位址', '新 IP 位址', '來源頁面'];
    else if (tabName === 'degraded' || tabName === 'recovered') headers = ['目標 URL', '原狀態', '新狀態', '新錯誤訊息', '來源頁面'];
    else if (tabName === 'security_downgraded') headers = ['目標 URL', '安全狀態變化', '來源頁面'];
    else if (tabName === 'new_links') headers = ['目標 URL', 'IP 位址', 'HTTP 狀態', '錯誤訊息', '來源頁面'];
    else if (tabName === 'removed_links') headers = ['目標 URL', '原 IP 位址', '原 HTTP 狀態', '原錯誤訊息', '來源頁面'];

    const wrapperEl = document.createElement('div');
    wrapperEl.className = 'table-wrapper';

    const tableEl = document.createElement('table');
    tableEl.className = 'table';

    const theadEl = document.createElement('thead');
    const trHeadEl = document.createElement('tr');
    headers.forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        trHeadEl.appendChild(th);
    });
    theadEl.appendChild(trHeadEl);
    tableEl.appendChild(theadEl);

    const tbodyEl = document.createElement('tbody');
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
            const tdOld = document.createElement('td');
            tdOld.className = 'font-mono text-muted';
            tdOld.textContent = item.old_status || '連線失敗';
            tr.appendChild(tdOld);

            const tdNew = document.createElement('td');
            tdNew.className = tabName === 'degraded' ? 'font-mono text-danger' : 'font-mono text-success';
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

            const tdStatus = document.createElement('td');
            tdStatus.className = !item.status_code ? 'text-muted' : (item.status_code >= 400 ? 'text-danger' : 'text-success');
            tdStatus.textContent = item.status_code || '-';
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

        tbodyEl.appendChild(tr);
    });

    tableEl.appendChild(tbodyEl);
    wrapperEl.appendChild(tableEl);

    containerEl.replaceChildren();
    containerEl.appendChild(wrapperEl);
}

function _getFilteredData() {
    if (!_currentDiffData || !_currentDiffData.details[_currentTab]) return [];
    let data = _currentDiffData.details[_currentTab];
    if (_compareSearch) {
        data = data.filter(item => {
            const tgt = (item.target_url || '').toLowerCase();
            const srcStr = (item.sources || []).join(' ').toLowerCase();
            return tgt.includes(_compareSearch) || srcStr.includes(_compareSearch);
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
    const searchInput = document.getElementById('compare-search');

    if (!baseSelectEl || !targetSelectEl) return;

    resultsAreaEl.style.display = 'none';
    errorEl.textContent = '';
    _currentDiffData = null;
    _compareSearch = '';
    if (searchInput) {
        searchInput.value = '';
    }

    baseSelectEl.innerHTML = '<option value="">載入中...</option>';
    targetSelectEl.innerHTML = '<option value="">載入中...</option>';
    runBtn.disabled = true;

    try {
        const jobs = await api.get('/api/jobs?status=completed');
        if (jobs.length === 0) {
            baseSelectEl.innerHTML = '<option value="">無已完成任務</option>';
            targetSelectEl.innerHTML = '<option value="">無已完成任務</option>';
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
            openExcludeBtn.style.color = currentExclude ? 'var(--color-brand-500)' : '';
            openExcludeBtn.style.borderColor = currentExclude ? 'var(--color-brand-500)' : '';
            openExcludeBtn.style.background = currentExclude ? 'hsla(221, 83%, 53%, 0.1)' : '';
        }
    } catch (err) {
        errorEl.textContent = '無法載入歷史任務：' + err.message;
    }
}