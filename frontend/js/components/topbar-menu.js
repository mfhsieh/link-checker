import './topbar-user.js';
import './topbar-password.js';
import './topbar-logout.js';

/**
 * 頂部導覽列使用者選單元件
 * 
 * 這是一個將 `<topbar-user>`、`<topbar-password>` 以及 `<topbar-logout>` 
 * 合組在一起的便利複合元件，通常放置於頁面右上方。
 * 
 * @class TopbarUserMenu
 * @extends {HTMLElement}
 */
class TopbarUserMenu extends HTMLElement {
    /**
     * 建立元件實例並附加 Shadow DOM
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }

    /**
     * 元件掛載到 DOM 樹時觸發
     */
    connectedCallback() {
        this.render();
    }

    /**
     * 渲染內部 DOM 結構與樣式
     */
    render() {
        const styleEl = document.createElement('style');
        styleEl.textContent = `
            .topbar-menu {
                display: flex;
                align-items: center;
                gap: .5rem;
            }

            @media (max-width: 640px) {
                .topbar-menu {
                    gap: 0;
                }
            }
        `;

        const containerEl = document.createElement('div');
        containerEl.className = 'topbar-menu';

        const userEl = document.createElement('topbar-user');
        const passwordEl = document.createElement('topbar-password');
        const logoutEl = document.createElement('topbar-logout');

        containerEl.appendChild(userEl);
        containerEl.appendChild(passwordEl);
        containerEl.appendChild(logoutEl);

        this.shadowRoot.appendChild(styleEl);
        this.shadowRoot.appendChild(containerEl);
    }
}

customElements.define('topbar-menu', TopbarUserMenu);
