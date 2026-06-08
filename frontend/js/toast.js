/**
 * toast.js — Toast 通知系統（ESM）
 *
 * 全域 Toast 通知工具，提供 success / warning / error / info 四種類型。
 */

let _container = null;

function getContainer() {
    if (!_container) {
        _container = document.createElement('div');
        _container.className = 'toast-container';
        _container.setAttribute('aria-live', 'polite');
        _container.setAttribute('aria-atomic', 'false');
        document.body.appendChild(_container);
    }
    return _container;
}

/**
 * 顯示 Toast 通知
 * @param {string} message - 訊息內容
 * @param {'success'|'warning'|'error'|'info'} type - 類型
 * @param {number} duration - 自動消失時間（毫秒），0 表示不自動消失
 */
export function showToast(message, type = 'info', duration = 4000) {
    const container = getContainer();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.setAttribute('role', 'alert');
    const msgDiv = document.createElement('div');
    msgDiv.className = 'toast-message';
    msgDiv.textContent = message;

    const closeBtn = document.createElement('button');
    closeBtn.className = 'toast-close';
    closeBtn.setAttribute('aria-label', '關閉通知');
    closeBtn.textContent = '✕';

    toast.appendChild(msgDiv);
    toast.appendChild(closeBtn);

    const remove = () => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(24px)';
        toast.style.transition = 'all 0.25s ease';
        setTimeout(() => toast.remove(), 250);
    };

    closeBtn.addEventListener('click', remove);
    container.appendChild(toast);

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

