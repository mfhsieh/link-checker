/**
 * api.js — API 通訊工具模組（ESM）
 *
 * 封裝 fetch，統一處理：
 * - 自動附加 X-CSRF-Token（從 csrf_token Cookie 讀取）
 * - 401 → 重導向至登入頁
 * - 錯誤回應解析為一致格式
 * - JSON 序列化 / 反序列化
 */

const BASE_URL = '';  // 同源，不需前綴

/** 從 Cookie 讀取指定名稱的值 */
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

/**
 * 核心 fetch 包裝函式
 * @param {string} path - API 路徑（如 /api/auth/me）
 * @param {RequestInit} options - fetch 選項
 * @returns {Promise<any>} 解析後的 JSON 回應
 */
async function request(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();

  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  // CSRF Token（POST / PATCH / PUT / DELETE 需要）
  if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(method)) {
    const csrfToken = getCookie('csrf_token');
    if (csrfToken) {
      headers['X-CSRF-Token'] = csrfToken;
    }
  }

  const response = await fetch(BASE_URL + path, {
    ...options,
    method,
    headers,
    credentials: 'same-origin',  // 攜帶 Cookie
  });

  // 401 → 清除客戶端狀態並重導向登入頁
  if (response.status === 401) {
    if (window.location.pathname !== '/' && window.location.pathname !== '/index.html') {
      window.location.replace('/');
      return;
    }
  }

  // 嘗試解析 JSON
  let data;
  const contentType = response.headers.get('Content-Type') || '';
  if (contentType.includes('application/json')) {
    data = await response.json();
  } else {
    data = await response.text();
  }

  if (!response.ok) {
    let message = `HTTP ${response.status} ${response.statusText}`;
    if (data && data.detail) {
      if (Array.isArray(data.detail)) {
        message = data.detail.map(e => `[${e.loc && e.loc.length > 0 ? e.loc[e.loc.length - 1] : '參數錯誤'}] ${e.msg}`).join('\n');
      } else {
        message = data.detail;
      }
    } else if (typeof data === 'string' && data.trim()) {
      message = data.trim();
    }
    const err = new Error(message);
    err.status = response.status;
    err.data = data;
    throw err;
  }

  return data;
}

// ── Public API ────────────────────────────────────────────────

/**
 * GET 請求
 * @param {string} path - API 路徑
 * @param {Object} [params] - 查詢參數字典
 * @returns {Promise<any>} 解析後的 JSON 回應
 */
export function get(path, params) {
  let url = path;
  if (params) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== null && v !== undefined)
    ).toString();
    if (qs) url += '?' + qs;
  }
  return request(url, { method: 'GET' });
}

/**
 * POST 請求（JSON body）
 * @param {string} path - API 路徑
 * @param {Object} [body] - 請求主體字典
 * @returns {Promise<any>} 解析後的 JSON 回應
 */
export function post(path, body) {
  return request(path, {
    method: 'POST',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/**
 * PATCH 請求（JSON body）
 * @param {string} path - API 路徑
 * @param {Object} [body] - 請求主體字典
 * @returns {Promise<any>} 解析後的 JSON 回應
 */
export function patch(path, body) {
  return request(path, {
    method: 'PATCH',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/**
 * DELETE 請求
 * @param {string} path - API 路徑
 * @returns {Promise<any>} 解析後的 JSON 回應
 */
export function del(path) {
  return request(path, { method: 'DELETE' });
}

/**
 * 下載請求（用於 CSV/JSON 匯出，觸發瀏覽器下載）
 * @param {string} path - 下載路徑
 * @returns {Promise<void>} 無回傳值
 */
export async function download(path) {
  const response = await fetch(BASE_URL + path, {
    method: 'GET',
    credentials: 'same-origin',
  });

  if (!response.ok) {
    throw new Error(`下載失敗：HTTP ${response.status}`);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  let filename = 'export';
  const match = disposition.match(/filename="?([^"]+)"?/);
  if (match) filename = match[1];

  const url = URL.createObjectURL(blob);
  const linkEl = document.createElement('a');
  linkEl.href = url;
  linkEl.download = filename;
  document.body.appendChild(linkEl);
  linkEl.click();
  linkEl.remove();
  URL.revokeObjectURL(url);
}

/**
 * 格式化時間：將後端回傳的 Naive UTC 字串轉換為瀏覽器當地時間
 */
export function formatLocalTime(dateStr) {
  if (!dateStr) return '-';
  let ds = String(dateStr);
  if (!ds.endsWith('Z') && !ds.includes('+') && !ds.match(/-\d{2}:\d{2}$/)) {
    ds += 'Z';
  }
  const d = new Date(ds);
  if (isNaN(d.getTime())) return '-';

  const yyyy = d.getFullYear();
  const MM = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const HH = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');

  return `${yyyy}/${MM}/${dd} ${HH}:${mm}:${ss}`;
}

/**
 * 格式化 UUID：取前 5 碼與後 5 碼，中間以 ... 連接（例如 ABCDE...FGHIJ）
 */
export function formatShortUuid(uuid) {
  if (!uuid) return '-';
  const u = String(uuid);
  if (u.length <= 10) return u;
  return `${u.substring(0, 5)}...${u.substring(u.length - 5)}`;
}

/**
 * 安全跳脫 HTML 實體字元，防範 XSS 攻擊
 * @param {string} str - 未受信任的字串
 * @returns {string} 跳脫後的安全字串
 */
export function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export const STATUS_LABELS = {
  pending: '等待中',
  starting: '啟動中',
  running: '執行中',
  paused: '已暫停',
  completed: '已完成',
  error: '錯誤',
};

export function formatStatus(status) {
  return STATUS_LABELS[status] || status;
}

export function createFilterInput(initialValue, onInput) {
  const filterInput = document.createElement('input');
  filterInput.type = 'text';
  filterInput.className = 'form-input text-xs';
  filterInput.placeholder = '篩選...';
  filterInput.style.marginTop = '0.5rem';
  filterInput.style.padding = '0.25rem 0.5rem';
  filterInput.style.height = 'auto';
  filterInput.style.fontWeight = 'normal';
  filterInput.value = initialValue || '';

  filterInput.addEventListener('input', (e) => {
    onInput(e.target.value.toLowerCase());
  });
  filterInput.addEventListener('click', e => e.stopPropagation());
  return filterInput;
}

export function createTruncatedSpan(text, maxWidth = '280px') {
  const span = document.createElement('span');
  span.className = 'truncate';
  span.style.maxWidth = maxWidth;
  span.style.display = 'block';
  span.title = text || '-';
  span.textContent = text || '-';
  return span;
}

export function updateSortIcons(containerEl, activeKey, isAsc) {
  if (!containerEl) return;
  containerEl.querySelectorAll('.sort-icon').forEach(icon => {
    if (icon.dataset.key === activeKey) {
      icon.textContent = isAsc ? '▲' : '▼';
      icon.style.color = 'var(--color-brand-500)';
    } else {
      icon.textContent = '⇅';
      icon.style.color = 'var(--text-muted)';
    }
  });
}

// 全域監聽 Modal (modal-overlay) 的開關狀態，防範背景 Scroll Bleed
if (typeof window !== 'undefined') {
  const initModalObserver = () => {
    const modalOverlays = document.querySelectorAll('.modal-overlay');
    if (modalOverlays.length === 0) return;

    const updateBodyScroll = () => {
      let hasVisibleModal = false;
      modalOverlays.forEach(el => {
        if (el.style.display !== 'none' && el.style.visibility !== 'hidden') {
          hasVisibleModal = true;
        }
      });
      if (hasVisibleModal) {
        document.body.classList.add('modal-open');
      } else {
        document.body.classList.remove('modal-open');
      }
    };

    const observer = new MutationObserver((mutations) => {
      mutations.forEach(mutation => {
        if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
          updateBodyScroll();
        }
      });
    });

    modalOverlays.forEach(el => {
      observer.observe(el, { attributes: true, attributeFilter: ['style'] });
    });

    // 初始檢查一次
    updateBodyScroll();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initModalObserver);
  } else {
    initModalObserver();
  }
}
