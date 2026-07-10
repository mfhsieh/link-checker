import { getCurrentUser } from '../auth.js';
import { formatLocalTime } from '../api.js';
import { showConfirm } from './confirm-modal.js';

/**
 * 頂部導覽列使用者資訊元件
 * 
 * 負責透過 `getCurrentUser()` 從後端載入使用者資訊（Email、角色）。
 * 並且將這些資訊渲染為圓形頭像與文字敘述。支援響應式排版。
 * 
 * @class TopbarUser
 * @extends {HTMLElement}
 * @property {string} [layout] - 若設定為 "compact"，則隱藏文字資訊只保留頭像
 */
class TopbarUser extends HTMLElement {
    /**
     * 建立元件實例並附加 Shadow DOM
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }

    /**
     * 元件掛載到 DOM 樹時觸發
     * 負責初始化渲染並載入使用者資訊
     * @returns {Promise<void>}
     */
    async connectedCallback() {
        this.render();
        await this.loadUser();
    }

    /**
     * 載入當前登入的使用者資訊並更新 DOM
     * @returns {Promise<void>}
     * @private
     */
    async loadUser() {
        try {
            const user = await getCurrentUser();
            if (!user) return;

            this._currentUser = user;

            const emailEl = this.shadowRoot.getElementById('email');
            const roleEl = this.shadowRoot.getElementById('role');
            const avatarEl = this.shadowRoot.getElementById('avatar');

            if (emailEl) emailEl.textContent = user.email;
            if (roleEl) roleEl.textContent = user.role === 'admin' ? '管理員' : '使用者';
            if (avatarEl) avatarEl.textContent = user.email.charAt(0).toUpperCase();
        } catch (err) {
            console.error('Failed to load user info:', err);
        }
    }

    /**
     * 渲染內部 DOM 結構與樣式
     */
    render() {
        const styleEl = document.createElement('style');
        styleEl.textContent = `
            .topbar-user {
                display: flex;
                align-items: center;
                gap: .5rem;
                padding: .5rem .5rem;
                border-radius: 3rem;
                cursor: pointer;
                transition: background-color 0.2s;
            }

            .topbar-user:hover {
                background-color: var(--surface-hover, rgba(255, 255, 255, 0.1));
            }

            .topbar-avatar {
                width: 2rem;
                height: 2rem;
                border-radius: 2rem;
                background: linear-gradient(135deg, var(--color-brand-400), var(--color-brand-600));
                color: #ffffff;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: 600;
                font-size: 1rem;
                text-transform: uppercase;
            }

            .topbar-user-info {
                display: flex;
                flex-direction: column;
                line-height: 1.2;
            }

            .topbar-user-name {
                font-size: .875rem;
                font-weight: 500;
                color: var(--text-primary);
            }

            .topbar-user-role {
                font-size: .75rem;
                color: var(--text-muted);
            }

            :host([layout="compact"]) .topbar-user-info {
                display: none;
            }

            @media (max-width: 640px) {
                .topbar-user-info {
                    display: none;
                }
                .topbar-user, .topbar-user:hover {
                    background: transparent;
                }
            }
        `;

        const userDivEl = document.createElement('div');
        userDivEl.className = 'topbar-user';
        userDivEl.setAttribute('role', 'button');
        userDivEl.tabIndex = 0;
        userDivEl.title = '帳號選單';

        const avatarEl = document.createElement('div');
        avatarEl.className = 'topbar-avatar';
        avatarEl.id = 'avatar';
        avatarEl.textContent = '-';

        const infoDivEl = document.createElement('div');
        infoDivEl.className = 'topbar-user-info';

        const emailSpanEl = document.createElement('span');
        emailSpanEl.className = 'topbar-user-name';
        emailSpanEl.id = 'email';
        emailSpanEl.textContent = '載入中...';

        const roleSpanEl = document.createElement('span');
        roleSpanEl.className = 'topbar-user-role';
        roleSpanEl.id = 'role';
        avatarEl.textContent = '-';

        infoDivEl.appendChild(emailSpanEl);
        infoDivEl.appendChild(roleSpanEl);

        userDivEl.appendChild(avatarEl);
        userDivEl.appendChild(infoDivEl);

        // 綁定點擊與鍵盤事件
        const showInfoModal = () => {
            if (!this._currentUser) return;
            const u = this._currentUser;
            const statusMap = { 'active': '啟用', 'pending': '待開通', 'disabled': '停用' };
            const roleStr = u.role === 'admin' ? '管理員' : '使用者';
            const statusStr = statusMap[u.status] || u.status;
            const loginStr = u.last_login_at ? formatLocalTime(u.last_login_at) : '從未登入';

            const msg = `電子郵件：${u.email}\n角色權限：${roleStr}\n帳號狀態：${statusStr}\n最後登入：${loginStr}`;

            if (typeof showConfirm === 'function') {
                showConfirm('帳號資訊', msg, '關閉', false, true);
            }
        };

        userDivEl.addEventListener('click', showInfoModal);
        userDivEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                showInfoModal();
            }
        });

        this.shadowRoot.appendChild(styleEl);
        this.shadowRoot.appendChild(userDivEl);
    }
}

customElements.define('topbar-user', TopbarUser);
