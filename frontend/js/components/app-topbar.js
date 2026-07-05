import './topbar-brand.js';
import './topbar-menu.js';

/**
 * 應用程式頂部導覽列複合元件
 * 
 * 負責整合左側品牌 Logo (`<topbar-brand>`) 與右側使用者選單 (`<topbar-menu>`)。
 * 支援透過屬性動態設定品牌區塊的連結與文字。
 *
 * @class AppTopbar
 * @extends {HTMLElement}
 * @property {string} [href='/app.html'] - 點擊 Logo 跳轉的目標 URL
 * @property {string} [title-text='網站連結檢查系統'] - 顯示的文字標題
 * @property {string} [badge-text=''] - 顯示於標題旁的徽章文字（例如「管理後台」）
 * 
 * @example
 * <app-topbar href="/admin.html" title-text="網站連結檢查系統" badge-text="管理後台"></app-topbar>
 */
class AppTopbar extends HTMLElement {
    /**
     * 建立元件實例並附加 Shadow DOM
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }

    /**
     * 元件掛載到 DOM 樹時觸發
     * 負責讀取自訂屬性 (Attributes) 並動態建構與渲染內部 DOM 結構
     */
    connectedCallback() {
        const href = this.getAttribute('href') || '/app.html';
        const titleText = this.getAttribute('title-text') || '網站連結檢查系統';
        const badgeText = this.getAttribute('badge-text') || '';

        const styleEl = document.createElement('style');
        styleEl.textContent = `
            :host {
                grid-area: topbar;
                display: flex;
                align-items: center;
                justify-content: space-between;
                background: var(--surface-base);
                border-bottom: 1px solid var(--surface-border-subtle);
                position: sticky;
                top: 0;
                z-index: 100;
                padding-left: var(--space-4);
            }
            .menu-toggle {
                display: none;
                background: transparent;
                border: none;
                cursor: pointer;
                padding: 0;
                margin-left: 0.5rem;
                margin-right: 0.5rem;
                color: var(--text-primary);
                align-items: center;
                justify-content: center;
            }
            .menu-toggle-icon {
                display: inline-block;
                width: 24px;
                height: 24px;
                -webkit-mask: url(/static/image/icon-menu.svg) no-repeat center / contain;
                mask: url(/static/image/icon-menu.svg) no-repeat center / contain;
                background-color: currentColor;
            }
            @media (max-width: 640px) {
                .menu-toggle {
                    display: flex;
                }
            }
        `;

        const brandEl = document.createElement('topbar-brand');
        brandEl.setAttribute('href', href);
        brandEl.setAttribute('title-text', titleText);
        if (badgeText) {
            brandEl.setAttribute('badge-text', badgeText);
        }

        const menuEl = document.createElement('topbar-menu');

        const menuToggleBtn = document.createElement('button');
        menuToggleBtn.className = 'menu-toggle';
        menuToggleBtn.setAttribute('aria-label', '開啟側邊欄');
        const menuIcon = document.createElement('span');
        menuIcon.className = 'menu-toggle-icon';
        menuToggleBtn.appendChild(menuIcon);

        menuToggleBtn.addEventListener('click', () => {
            window.dispatchEvent(new CustomEvent('sidebar-toggle'));
        });

        window.addEventListener('sidebar-state', (e) => {
            if (e.detail.open) {
                menuIcon.style.mask = 'url(/static/image/icon-close.svg) no-repeat center / contain';
                menuIcon.style.webkitMask = 'url(/static/image/icon-close.svg) no-repeat center / contain';
            } else {
                menuIcon.style.mask = 'url(/static/image/icon-menu.svg) no-repeat center / contain';
                menuIcon.style.webkitMask = 'url(/static/image/icon-menu.svg) no-repeat center / contain';
            }
        });

        const leftGroup = document.createElement('div');
        leftGroup.style.display = 'flex';
        leftGroup.style.alignItems = 'center';
        leftGroup.appendChild(menuToggleBtn);
        leftGroup.appendChild(brandEl);

        this.shadowRoot.appendChild(styleEl);
        this.shadowRoot.appendChild(leftGroup);
        this.shadowRoot.appendChild(menuEl);
    }
}

customElements.define('app-topbar', AppTopbar);
