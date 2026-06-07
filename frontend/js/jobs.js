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

    const title = document.createElement('div');
    title.className = 'empty-state-title';
    title.textContent = '尚無任務';
    emptyState.appendChild(title);

    const desc = document.createElement('div');
    desc.className = 'empty-state-desc';
    desc.textContent = '點擊右上角「新增任務」開始建立您的第一個外連掃描任務';
    emptyState.appendChild(desc);

    container.appendChild(emptyState);
    return;
  }

  const wrapper = document.createElement('div');
  wrapper.className = 'table-wrapper';

  const table = document.createElement('table');
  table.className = 'table';
  table.id = 'jobs-table';

  const thead = document.createElement('thead');
  const trHead = document.createElement('tr');
  ['任務 ID', '起始 URL', '狀態', '建立時間', '操作'].forEach(text => {
    const th = document.createElement('th');
    th.textContent = text;
    trHead.appendChild(th);
  });
  thead.appendChild(trHead);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  jobs.forEach(job => {
    tbody.appendChild(renderJobRow(job));
  });
  table.appendChild(tbody);
  wrapper.appendChild(table);
  container.appendChild(wrapper);
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

let _onJobCreated = null;

export function initCreateJobModal(onJobCreated) {
  _onJobCreated = onJobCreated;
  const createBtn = document.getElementById('create-job-btn');
  if (createBtn) {
    createBtn.addEventListener('click', openCreateJobModal);
  }
}

function openCreateJobModal() {
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.id = 'create-job-modal';

  const modalHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div class="modal-header">
        <h2 class="modal-title" id="modal-title">建立新任務</h2>
        <button class="btn btn-ghost btn-icon" id="modal-close-btn" aria-label="關閉">✕</button>
      </div>
      <div class="modal-body">
        <form id="create-job-form" novalidate>
          <div class="form-group" style="margin-bottom:1rem">
            <label class="form-label" for="cj-start-url">起始 URL <span class="required">*</span></label>
            <input class="form-input" type="url" id="cj-start-url" placeholder="https://example.com" autocomplete="off" required />
          </div>
          <div class="form-group" style="margin-bottom:1rem">
            <label class="form-label" for="cj-target-domains">目標網域 <span class="required">*</span> <span class="form-hint">（每行一個，爬蟲僅深入這些網域）</span></label>
            <textarea class="form-textarea" id="cj-target-domains" placeholder="example.com\nwww.example.com" rows="3" required></textarea>
          </div>
          <div class="form-group" style="margin-bottom:1rem">
            <label class="form-label" for="cj-internal-domains">內部網域 <span class="form-hint">（每行一個，這些網域的外連不會被記錄）</span></label>
            <textarea class="form-textarea" id="cj-internal-domains" placeholder="（選填）" rows="2"></textarea>
          </div>
          <div class="form-group" style="margin-bottom:1rem">
            <label class="form-label" for="cj-ignore-regexes">排除的正則表達式 <span class="form-hint">（每行一個，符合的 URL 將不會被爬取與探測）</span></label>
            <textarea class="form-textarea" id="cj-ignore-regexes" placeholder="^https://example\\.com/download/.*&#10;（選填）" rows="2"></textarea>
          </div>
          <div class="form-group" style="margin-bottom:1rem">
            <label class="form-label" for="cj-approved-domains">信任的外部網域白名單 <span class="form-hint">（每行一個）</span></label>
            <textarea class="form-textarea" id="cj-approved-domains" placeholder="www.google.com&#10;（選填）" rows="2"></textarea>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
            <div class="form-group">
              <label class="form-label" for="cj-max-depth">最大爬取深度</label>
              <input class="form-input" type="number" id="cj-max-depth" placeholder="不限制" min="1" max="20" />
            </div>
            <div class="form-group">
              <label class="form-label" for="cj-max-pages">最大抓取頁數</label>
              <input class="form-input" type="number" id="cj-max-pages" placeholder="不限制" min="1" />
            </div>
          </div>
          <div id="create-job-error" style="color:var(--color-danger-400);font-size:0.875rem;min-height:1.25rem"></div>
        </form>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" id="modal-cancel-btn">取消</button>
        <button class="btn btn-primary" id="modal-submit-btn">建立任務</button>
      </div>
    </div>
  `;
  const doc = new DOMParser().parseFromString(modalHTML, 'text/html');
  while (doc.body.firstChild) {
    backdrop.appendChild(doc.body.firstChild);
  }

  document.body.appendChild(backdrop);

  const closeModal = () => backdrop.remove();

  backdrop.getElementById = (id) => backdrop.querySelector('#' + id);
  document.getElementById('modal-close-btn').addEventListener('click', closeModal);
  document.getElementById('modal-cancel-btn').addEventListener('click', closeModal);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeModal(); });

  document.getElementById('modal-submit-btn').addEventListener('click', async () => {
    const startUrl = document.getElementById('cj-start-url').value.trim();
    const targetDomainsRaw = document.getElementById('cj-target-domains').value;
    const internalDomainsRaw = document.getElementById('cj-internal-domains').value;
    const ignoreRegexesRaw = document.getElementById('cj-ignore-regexes').value;
    const approvedDomainsRaw = document.getElementById('cj-approved-domains').value;
    const maxDepth = document.getElementById('cj-max-depth').value;
    const maxPages = document.getElementById('cj-max-pages').value;
    const errorEl = document.getElementById('create-job-error');

    errorEl.textContent = '';

    if (!startUrl) { errorEl.textContent = '請填寫起始 URL。'; return; }
    if (!targetDomainsRaw.trim()) { errorEl.textContent = '請填寫至少一個目標網域。'; return; }

    const targetDomains = targetDomainsRaw.split('\n').map(s => s.trim()).filter(Boolean);
    const internalDomains = internalDomainsRaw.split('\n').map(s => s.trim()).filter(Boolean);
    const ignoreRegexes = ignoreRegexesRaw.split('\n').map(s => s.trim()).filter(Boolean);
    const approvedDomains = approvedDomainsRaw.split('\n').map(s => s.trim()).filter(Boolean);

    const body = { start_url: startUrl, target_domains: targetDomains, internal_domains: internalDomains, ignore_regexes: ignoreRegexes, approved_domains: approvedDomains };
    if (maxDepth) body.max_depth = parseInt(maxDepth);
    if (maxPages) body.max_pages = parseInt(maxPages);

    const submitBtn = document.getElementById('modal-submit-btn');
    submitBtn.classList.add('loading');
    submitBtn.disabled = true;

    try {
      const res = await api.post('/api/jobs', body);
      toast.success('任務已建立！');
      closeModal();
      if (_onJobCreated) _onJobCreated(res.job_id);
    } catch (err) {
      errorEl.textContent = err.message || '建立失敗，請稍後再試。';
    } finally {
      submitBtn.classList.remove('loading');
      submitBtn.disabled = false;
    }
  });
}

window.viewJob = (jobId) => {
  window.location.hash = `#/jobs/${jobId}`;
};
