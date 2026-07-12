/**
 * toast.js — Toast 通知系統（ESM）改寫為 Web Component
 */

/**
 * 應用程式全局 Toast 通知容器
 * 
 * 負責渲染並管理畫面上浮現的提示訊息（如成功、警告、錯誤等）。
 * 會自動常駐於 `document.body` 中，並提供全局單例物件 `toast` 供外部呼叫。
 */
class AppToastContainer extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }

    connectedCallback() {
        const styleEl = document.createElement('style');
        styleEl.textContent = `
            :host {
                position: fixed;
                top: 1.5rem;
                right: 1.5rem;
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                z-index: 500;
                max-width: 400px;
                pointer-events: none; /* Let clicks pass through empty space */
            }

            .toast {
                display: flex;
                align-items: flex-start;
                gap: 0.75rem;
                padding: 1rem 1.25rem;
                background: var(--surface-raised, #ffffff);
                border: 1px solid var(--surface-border, #e2e8f0);
                border-radius: 0.5rem;
                box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
                animation: slideInRight 0.3s ease forwards;
                position: relative;
                overflow: hidden;
                pointer-events: auto; /* Re-enable clicks on the toast itself */
                transition: opacity 0.25s ease, transform 0.25s ease;
            }

            @keyframes slideInRight {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }

            .toast::before {
                content: '';
                position: absolute;
                left: 0;
                top: 0;
                bottom: 0;
                width: 4px;
                border-radius: 0.25rem 0 0 0.25rem;
            }

            .toast-success::before { background: var(--color-success-500, #10b981); }
            .toast-warning::before { background: var(--color-warning-500, #f59e0b); }
            .toast-error::before { background: var(--color-danger-500, #ef4444); }
            .toast-info::before { background: var(--color-info-500, #3b82f6); }

            .toast-message {
                flex: 1;
                font-size: 0.875rem;
                color: var(--text-secondary, #475569);
                line-height: 1.5;
            }

            .toast-close {
                background: none;
                border: none;
                cursor: pointer;
                color: var(--text-muted, #94a3b8);
                padding: 0.125rem;
                border-radius: 0.25rem;
                transition: color 0.2s;
            }

            .toast-close:hover {
                color: var(--text-primary, #0f172a);
            }
        `;

        this.container = document.createElement('div');
        this.container.id = 'container';
        this.container.style.display = 'flex';
        this.container.style.flexDirection = 'column';
        this.container.style.gap = '0.75rem';

        this.shadowRoot.appendChild(styleEl);
        this.shadowRoot.appendChild(this.container);
    }

    showToast(message, type = 'info', duration = 4000) {
        if (!this.container) return; // Not yet connected

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
            setTimeout(() => toastEl.remove(), 250);
        };

        closeBtn.addEventListener('click', remove);
        this.container.appendChild(toastEl);

        if (duration > 0) {
            setTimeout(remove, duration);
        }
    }
}

if (!customElements.get('app-toast-container')) {
    customElements.define('app-toast-container', AppToastContainer);
}

let _toastContainerEl = null;

function getToastContainer() {
    if (!_toastContainerEl) {
        // Try to find it in the DOM first
        _toastContainerEl = document.querySelector('app-toast-container');
        if (!_toastContainerEl) {
            _toastContainerEl = document.createElement('app-toast-container');
            document.body.appendChild(_toastContainerEl);
        }
    }
    return _toastContainerEl;
}

/**
 * 顯示 Toast 通知
 * @param {string} message - 訊息內容
 * @param {'success'|'warning'|'error'|'info'} [type='info'] - 通知類型
 * @param {number} [duration=4000] - 自動消失時間（毫秒），0 表示不自動消失
 */
export function showToast(message, type = 'info', duration = 4000) {
    const container = getToastContainer();
    // Ensure the element is mounted and shadow DOM is ready
    if (container.shadowRoot && container.container) {
        container.showToast(message, type, duration);
    } else {
        // Wait for the next tick if it was just appended
        setTimeout(() => {
            container.showToast(message, type, duration);
        }, 0);
    }
}

/**
 * 全域 Toast 工具物件
 * 包含 `success`, `warning`, `error`, `info` 四個捷徑方法。
 * @type {{
 *   success: (msg: string, d?: number) => void,
 *   warning: (msg: string, d?: number) => void,
 *   error: (msg: string, d?: number) => void,
 *   info: (msg: string, d?: number) => void
 * }}
 */
export const toast = {
    success: (msg, d) => showToast(msg, 'success', d),
    warning: (msg, d) => showToast(msg, 'warning', d),
    error: (msg, d) => showToast(msg, 'error', d),
    info: (msg, d) => showToast(msg, 'info', d),
};
