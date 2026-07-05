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
            }
        `;

        const brandEl = document.createElement('topbar-brand');
        brandEl.setAttribute('href', href);
        brandEl.setAttribute('title-text', titleText);
        if (badgeText) {
            brandEl.setAttribute('badge-text', badgeText);
        }

        const menuEl = document.createElement('topbar-menu');

        this.shadowRoot.appendChild(styleEl);
        this.shadowRoot.appendChild(brandEl);
        this.shadowRoot.appendChild(menuEl);
    }
}

customElements.define('app-topbar', AppTopbar);
