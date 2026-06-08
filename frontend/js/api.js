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
    const message = (data && data.detail) ? data.detail : (typeof data === 'string' && data.trim() ? data.trim() : `HTTP ${response.status} ${response.statusText}`);
    const err = new Error(message);
    err.status = response.status;
    err.data = data;
    throw err;
  }

  return data;
}

// ── Public API ────────────────────────────────────────────────

/** GET 請求 */
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

/** POST 請求（JSON body）*/
export function post(path, body) {
  return request(path, {
    method: 'POST',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/** PATCH 請求（JSON body）*/
export function patch(path, body) {
  return request(path, {
    method: 'PATCH',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/** DELETE 請求 */
export function del(path) {
  return request(path, { method: 'DELETE' });
}

/**
 * 下載請求（用於 CSV/JSON 匯出，觸發瀏覽器下載）
 * @param {string} path - 下載路徑
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
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
