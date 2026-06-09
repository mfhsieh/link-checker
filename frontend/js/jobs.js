/**
 * jobs.js — 任務列表與新增任務頁面邏輯（ESM）
 */

import * as api from './api.js';
import { toast } from './toast.js';

const STATUS_LABELS = {
  pending: '等待中',
  running: '執行中',
  paused: '已暫停',
  completed: '已完成',
  error: '錯誤',
};

export function renderJobList(jobs, container) {
  container.replaceChildren();
  if (!jobs || jobs.length === 0) {
    const emptyState = document.createElement('div');
    emptyState.className = 'empty-state';

    const svgDoc = new DOMParser().parseFromString(
      '<svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" /></svg>',
      'image/svg+xml'
    );
    emptyState.appendChild(svgDoc.documentElement);

    const titleEl = document.createElement('div');
    titleEl.className = 'empty-state-title';
    titleEl.textContent = '尚無任務';
    emptyState.appendChild(titleEl);

    const descEl = document.createElement('div');
    descEl.className = 'empty-state-desc';
    descEl.textContent = '點擊右上角「新增任務」開始建立您的第一個外連掃描任務';
    emptyState.appendChild(descEl);

    container.appendChild(emptyState);
    return;
  }

  const wrapperEl = document.createElement('div');
  wrapperEl.className = 'table-wrapper';

  const tableEl = document.createElement('table');
  tableEl.className = 'table';
  tableEl.id = 'jobs-table';

  const theadEl = document.createElement('thead');
  const headRowEl = document.createElement('tr');
  ['任務 ID', '起始 URL', '狀態', '建立時間', '操作'].forEach(text => {
    const th = document.createElement('th');
    th.textContent = text;
    headRowEl.appendChild(th);
  });
  theadEl.appendChild(headRowEl);
  tableEl.appendChild(theadEl);

  const tbodyEl = document.createElement('tbody');
  jobs.forEach(job => {
    tbodyEl.appendChild(renderJobRow(job));
  });
  tableEl.appendChild(tbodyEl);
  wrapperEl.appendChild(tableEl);
  container.appendChild(wrapperEl);
}

function renderJobRow(job) {
  const statusClass = `badge-${job.status}`;
  const label = STATUS_LABELS[job.status] || job.status;
  const createdAt = job.created_at ? new Date(job.created_at).toLocaleString('zh-TW') : '-';
  const shortId = job.id ? job.id.substring(0, 8) + '...' : '-';
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
  span1.textContent = shortId;
  td1.appendChild(span1);
  tr.appendChild(td1);

  const td2 = document.createElement('td');
  const span2 = document.createElement('span');
  span2.className = 'truncate';
  span2.style.maxWidth = '280px';
  span2.style.display = 'block';
  span2.title = truncatedUrl;
  span2.textContent = truncatedUrl;
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
  td5.appendChild(divActions);
  tr.appendChild(td5);

  return tr;
}

window.viewJob = (jobId) => {
  window.location.hash = `#/jobs/${jobId}`;
};
