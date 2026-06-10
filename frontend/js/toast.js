/**
 * toast.js — Toast 通知系統（ESM）
 *
 * 全域 Toast 通知工具，提供 success / warning / error / info 四種類型。
 */

let _containerEl = null;

function getContainer() {
    if (!_containerEl) {
        _containerEl = document.createElement('div');
        _containerEl.className = 'toast-container';
        _containerEl.setAttribute('aria-live', 'polite');
        _containerEl.setAttribute('aria-atomic', 'false');
        document.body.appendChild(_containerEl);
    }
    return _containerEl;
}

/**
 * 顯示 Toast 通知
 * @param {string} message - 訊息內容
 * @param {'success'|'warning'|'error'|'info'} type - 類型
 * @param {number} duration - 自動消失時間（毫秒），0 表示不自動消失
 */
export function showToast(message, type = 'info', duration = 4000) {
    const containerEl = getContainer();

    const toastEl = document.createElement('div');
    toastEl.className = `toast toast-${type}`;
    toastEl.setAttribute('role', 'alert');
    const msgEl = document.createElement('div');
    msgEl.className = 'toast-message';
    msgEl.textContent = message;

    const closeBtn = document.createElement('button');
    closeBtn.className = 'toast-close';
    closeBtn.setAttribute('aria-label', '關閉通知');
    closeBtn.textContent = '✕';

    toastEl.appendChild(msgEl);
    toastEl.appendChild(closeBtn);

    const remove = () => {
        toastEl.style.opacity = '0';
        toastEl.style.transform = 'translateX(24px)';
        toastEl.style.transition = 'all 0.25s ease';
        setTimeout(() => toastEl.remove(), 250);
    };

    closeBtn.addEventListener('click', remove);
    containerEl.appendChild(toastEl);

    if (duration > 0) {
        setTimeout(remove, duration);
    }
}

export const toast = {
    success: (msg, d) => showToast(msg, 'success', d),
    warning: (msg, d) => showToast(msg, 'warning', d),
    error: (msg, d) => showToast(msg, 'error', d),
    info: (msg, d) => showToast(msg, 'info', d),
};
