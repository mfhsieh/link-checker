/**
 * jobs.js — 任務列表與新增任務頁面邏輯（ESM）
 */

import * as api from './api.js';
import { toast } from './toast.js';

// ── 狀態 → 中文標籤 ───────────────────────────────────────────
const STATUS_LABELS = {
  pending:   '等待中',
  running:   '執行中',
  paused:    '已暫停',
  completed: '已完成',
  error:     '錯誤',
};

// ── 任務列表 ──────────────────────────────────────────────────

/**
 * 渲染任務列表
 * @param {Array} jobs - 任務資料陣列
 * @param {HTMLElement} container - 容器元素
 */
export function renderJobList(jobs, container) {
  if (!jobs || jobs.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round"
            d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
        </svg>
        <div class="empty-state-title">尚無任務</div>
        <div class="empty-state-desc">點擊右上角「新增任務」開始建立您的第一個外連掃描任務</div>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="table-wrapper">
      <table class="table" id="jobs-table">
        <thead>
          <tr>
            <th>任務 ID</th>
            <th>起始 URL</th>
            <th>狀態</th>
            <th>建立時間</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          ${jobs.map(job => renderJobRow(job)).join('')}
        </tbody>
      </table>
    </div>
  `;

  // 綁定行點擊事件（查看詳情）
  container.querySelectorAll('.job-row').forEach(row => {
    row.style.cursor = 'pointer';
    row.addEventListener('click', (e) => {
      if (e.target.closest('.job-actions')) return;  // 不觸發操作按鈕點擊
      const jobId = row.dataset.jobId;
      window.location.hash = `#/jobs/${jobId}`;
    });
  });
}

function renderJobRow(job) {
  const statusClass = `badge-${job.status}`;
  const label = STATUS_LABELS[job.status] || job.status;
  const createdAt = job.created_at ? new Date(job.created_at).toLocaleString('zh-TW') : '-';
  const shortId = job.id ? job.id.substring(0, 8) + '...' : '-';
  const truncatedUrl = job.start_url || '-';

  return `
    <tr class="job-row" data-job-id="${escapeAttr(job.id)}">
      <td>
        <span class="font-mono text-xs" title="${escapeHtml(job.id)}">${escapeHtml(shortId)}</span>
      </td>
      <td>
        <span class="truncate" style="max-width:280px;display:block" title="${escapeHtml(truncatedUrl)}">
          ${escapeHtml(truncatedUrl)}
        </span>
      </td>
      <td><span class="badge ${escapeHtml(statusClass)}">${escapeHtml(label)}</span></td>
      <td class="text-muted text-sm">${escapeHtml(createdAt)}</td>
      <td>
        <div class="job-actions" style="display:flex;gap:8px">
          <button class="btn btn-sm btn-secondary" onclick="viewJob('${escapeAttr(job.id)}')">詳情</button>
        </div>
      </td>
    </tr>
  `;
}

// ── 新增任務 Modal ────────────────────────────────────────────

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
  backdrop.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div class="modal-header">
        <h2 class="modal-title" id="modal-title">建立新任務</h2>
        <button class="btn btn-ghost btn-icon" id="modal-close-btn" aria-label="關閉">✕</button>
      </div>
      <div class="modal-body">
        <form id="create-job-form" novalidate>
          <div class="form-group" style="margin-bottom:1rem">
            <label class="form-label" for="cj-start-url">起始 URL <span class="required">*</span></label>
            <input class="form-input" type="url" id="cj-start-url"
              placeholder="https://example.com" autocomplete="off" required />
          </div>
          <div class="form-group" style="margin-bottom:1rem">
            <label class="form-label" for="cj-target-domains">
              目標網域 <span class="required">*</span>
              <span class="form-hint">（每行一個，爬蟲僅深入這些網域）</span>
            </label>
            <textarea class="form-textarea" id="cj-target-domains"
              placeholder="example.com&#10;www.example.com" rows="3" required></textarea>
          </div>
          <div class="form-group" style="margin-bottom:1rem">
            <label class="form-label" for="cj-internal-domains">
              內部網域
              <span class="form-hint">（每行一個，這些網域的外連不會被記錄）</span>
            </label>
            <textarea class="form-textarea" id="cj-internal-domains"
              placeholder="（選填）" rows="2"></textarea>
          </div>
          <div class="form-group" style="margin-bottom:1rem">
            <label class="form-label" for="cj-ignore-regexes">
              排除的正則表達式
              <span class="form-hint">（每行一個，符合的 URL 將不會被爬取與探測）</span>
            </label>
            <textarea class="form-textarea" id="cj-ignore-regexes"
              placeholder="^https://example\.com/download/.*&#10;（選填）" rows="2"></textarea>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
            <div class="form-group">
              <label class="form-label" for="cj-max-depth">最大爬取深度</label>
              <input class="form-input" type="number" id="cj-max-depth"
                placeholder="不限制" min="1" max="20" />
            </div>
            <div class="form-group">
              <label class="form-label" for="cj-max-pages">最大抓取頁數</label>
              <input class="form-input" type="number" id="cj-max-pages"
                placeholder="不限制" min="1" />
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
    const maxDepth = document.getElementById('cj-max-depth').value;
    const maxPages = document.getElementById('cj-max-pages').value;
    const errorEl = document.getElementById('create-job-error');

    errorEl.textContent = '';

    if (!startUrl) { errorEl.textContent = '請填寫起始 URL。'; return; }
    if (!targetDomainsRaw.trim()) { errorEl.textContent = '請填寫至少一個目標網域。'; return; }

    const targetDomains = targetDomainsRaw.split('\n').map(s => s.trim()).filter(Boolean);
    const internalDomains = internalDomainsRaw.split('\n').map(s => s.trim()).filter(Boolean);
    const ignoreRegexes = ignoreRegexesRaw.split('\n').map(s => s.trim()).filter(Boolean);

    const body = { start_url: startUrl, target_domains: targetDomains, internal_domains: internalDomains, ignore_regexes: ignoreRegexes };
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

// ── 全域輔助 ───────────────────────────────────────────────────

window.viewJob = (jobId) => {
  window.location.hash = `#/jobs/${jobId}`;
};

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = String(str || '');
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str || '').replace(/"/g, '&quot;');
}
