/**
 * jobs.js — 任務列表與新增任務頁面邏輯（ESM）
 */

import * as api from './api.js';
import { toast } from './toast.js';



/** @type {Array<Object>} 目前載入的所有任務列表 */
let _currentJobs = [];
/** @type {{key: string|null, asc: boolean}} 目前的排序狀態 */
let _jobSort = { key: 'created_at', asc: false };
/** @type {Object<string, string>} 各欄位的篩選條件 */
let _jobColFilters = {};
/** @type {HTMLElement|null} 列表容器元素 */
let _listContainerEl = null;

/**
 * 渲染任務列表表格
 * @param {Array<Object>|null} jobs - 任務資料陣列
 * @param {HTMLElement} [containerEl] - 欲渲染的容器元素
 * @returns {void} 無回傳值
 */
export function renderJobList(jobs, containerEl) {
  if (containerEl) _listContainerEl = containerEl;
  if (!_listContainerEl) return;

  if (jobs !== undefined && jobs !== null) {
    _currentJobs = [...jobs];
  }

  if (_currentJobs.length === 0) {
    _listContainerEl.replaceChildren();
    const emptyStateEl = document.createElement('div');
    emptyStateEl.className = 'empty-state';

    const svgDoc = new DOMParser().parseFromString(
      '<svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" /></svg>',
      'image/svg+xml'
    );
    emptyStateEl.appendChild(svgDoc.documentElement);

    const titleEl = document.createElement('div');
    titleEl.className = 'empty-state-title';
    titleEl.textContent = '尚無任務';
    emptyStateEl.appendChild(titleEl);

    const descEl = document.createElement('div');
    descEl.className = 'empty-state-desc';
    descEl.textContent = '點擊左側選單「新增任務」開始建立您的第一個外連掃描任務';
    emptyStateEl.appendChild(descEl);

    _listContainerEl.appendChild(emptyStateEl);
    return;
  }

  let data = [..._currentJobs];

  for (const [k, v] of Object.entries(_jobColFilters)) {
    if (!v) continue;
    data = data.filter(item => {
      let val = item[k];
      if (k === 'status') val = api.formatStatus(val);
      else if (k === 'created_at') val = api.formatLocalTime(val);
      return String(val || '').toLowerCase().includes(v);
    });
  }

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

  let tableEl = _listContainerEl.querySelector('.table');
  let tbodyEl = tableEl ? tableEl.querySelector('tbody') : null;

  if (!tableEl) {
    _listContainerEl.replaceChildren();

    const wrapperEl = document.createElement('div');
    wrapperEl.className = 'table-wrapper';

    tableEl = document.createElement('table');
    tableEl.className = 'table';
    tableEl.id = 'jobs-table';

    const theadEl = document.createElement('thead');
    const headRowEl = document.createElement('tr');

    const headers = [
      { label: '任務 ID', key: 'id' },
      { label: '起始 URL', key: 'start_url' },
      { label: '狀態', key: 'status' },
      { label: '建立時間', key: 'created_at' },
      { label: '操作', key: null, filterable: false }
    ];

    headers.forEach(h => {
      const th = document.createElement('th');
      th.style.verticalAlign = 'top';

      if (!h.key) {
        th.textContent = h.label;
      } else {
        const headerTop = document.createElement('div');
        headerTop.style.display = 'flex';
        headerTop.style.justifyContent = 'space-between';
        headerTop.style.alignItems = 'center';
        headerTop.style.cursor = 'pointer';

        const labelSpan = document.createElement('span');
        labelSpan.textContent = h.label;
        headerTop.appendChild(labelSpan);

        const icon = document.createElement('span');
        icon.className = 'sort-icon';
        icon.dataset.key = h.key;
        icon.style.fontSize = '0.75rem';
        icon.style.marginLeft = '0.25rem';
        if (_jobSort.key === h.key) {
          icon.textContent = _jobSort.asc ? '▲' : '▼';
          icon.style.color = 'var(--color-brand-500)';
        } else {
          icon.textContent = '⇅';
          icon.style.color = 'var(--text-muted)';
        }
        headerTop.appendChild(icon);

        headerTop.addEventListener('click', () => {
          if (_jobSort.key === h.key) {
            _jobSort.asc = !_jobSort.asc;
          } else {
            _jobSort.key = h.key;
            _jobSort.asc = true;
          }
          api.updateSortIcons(headRowEl, _jobSort.key, _jobSort.asc);
          renderJobList(null, _listContainerEl);
        });
        th.appendChild(headerTop);

        if (h.filterable !== false) {
          const filterInput = api.createFilterInput(_jobColFilters[h.key], (newVal) => {
            _jobColFilters[h.key] = newVal;
            renderJobList(null, _listContainerEl);
          });
          th.appendChild(filterInput);
        }
      }
      headRowEl.appendChild(th);
    });
    theadEl.appendChild(headRowEl);
    tableEl.appendChild(theadEl);

    tbodyEl = document.createElement('tbody');
    tableEl.appendChild(tbodyEl);
    wrapperEl.appendChild(tableEl);
    _listContainerEl.appendChild(wrapperEl);
  }

  tbodyEl.replaceChildren();
  if (data.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'text-center text-muted';
    td.style.padding = '1rem';
    td.textContent = '本頁無符合篩選條件的結果';
    tr.appendChild(td);
    tbodyEl.appendChild(tr);
  } else {
    data.forEach(job => {
      tbodyEl.appendChild(renderJobRow(job));
    });
  }
}

/**
 * 渲染任務列表的單一行
 * @param {Object} job - 任務資料
 * @returns {HTMLTableRowElement} 表格的行元素
 */
function renderJobRow(job) {
  const statusClass = `badge-${job.status}`;
  const label = api.formatStatus(job.status);
  const createdAt = api.formatLocalTime(job.created_at);
  const jobId = job.id || '-';
  const truncatedUrl = job.start_url || '-';

  const tr = document.createElement('tr');
  tr.className = 'job-row';
  tr.dataset.jobId = job.id;
  tr.style.cursor = 'pointer';
  tr.addEventListener('click', (e) => {
    if (e.target.closest('.job-actions')) return;
    window.location.hash = `#/jobs/${job.id}`;
  });

  const td1 = document.createElement('td');
  const span1 = document.createElement('span');
  span1.className = 'font-mono text-xs';
  span1.title = job.id;
  span1.textContent = jobId;
  td1.appendChild(span1);
  tr.appendChild(td1);

  const td2 = document.createElement('td');
  const span2 = api.createTruncatedSpan(truncatedUrl, '280px');
  td2.appendChild(span2);
  tr.appendChild(td2);

  const td3 = document.createElement('td');
  const span3 = document.createElement('span');
  span3.className = `badge ${statusClass}`;
  span3.textContent = label;
  td3.appendChild(span3);
  tr.appendChild(td3);

  const td4 = document.createElement('td');
  td4.className = 'text-muted text-sm';
  td4.textContent = createdAt;
  tr.appendChild(td4);

  const td5 = document.createElement('td');
  const divActions = document.createElement('div');
  divActions.className = 'job-actions';
  divActions.style.display = 'flex';
  divActions.style.gap = '8px';
  const btn = document.createElement('button');
  btn.className = 'btn btn-sm btn-secondary';
  btn.textContent = '詳情';
  btn.addEventListener('click', () => { window.viewJob(job.id); });
  divActions.appendChild(btn);

  const btnDup = document.createElement('button');
  btnDup.className = 'btn btn-sm btn-secondary';
  btnDup.textContent = '複製';
  btnDup.onclick = (e) => { e.stopPropagation(); window.location.hash = `#/new?clone=${job.id}`; };
  divActions.appendChild(btnDup);

  td5.appendChild(divActions);
  tr.appendChild(td5);

  return tr;
}

/**
 * 導覽至任務詳情頁面 (附加於 window 物件供行內點擊事件呼叫)
 * @param {string} jobId - 任務 ID
 * @returns {void}
 */
window.viewJob = (jobId) => {
  window.location.hash = `#/jobs/${jobId}`;
};
