/**
 * 頂部導覽列品牌元件
 * 
 * 負責渲染左側的 Logo、標題與狀態徽章。
 *
 * @class TopbarBrand
 * @extends {HTMLElement}
 * @property {string} [href='/app.html'] - 點擊 Logo 跳轉的目標 URL
 * @property {string} [title-text='網站連結檢查系統'] - 顯示的文字標題
 * @property {string} [badge-text=''] - 顯示於標題旁的徽章文字（例如「管理後台」），未提供則不顯示
 */
class TopbarBrand extends HTMLElement {
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
            .topbar-brand {
                display: flex;
                align-items: center;
                gap: .5rem;
                text-decoration: none;
            }

            .topbar-logo {
                background: linear-gradient(135deg, var(--color-brand-400), var(--color-brand-600));
                width: 2rem;
                height: 2rem;
                border-radius: .375rem;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-left: .5rem;
            }

            .topbar-title {
                font-size: 1rem;
                font-weight: 600;
                color: var(--text-primary);
            }

            .topbar-badge {
                font-size: .75rem;
                color: var(--color-danger-400);
                background: var(--color-danger-900);
                border: 1px solid var(--color-danger-400);
                border-radius: 1rem;
                padding: .125rem .5rem;
            }

            @media (max-width: 640px) {
                .topbar-logo {
                    display: none;
                }
            }
        `;

        const brandLinkEl = document.createElement('a');
        brandLinkEl.className = 'topbar-brand';
        brandLinkEl.href = href;

        const logoDivEl = document.createElement('div');
        logoDivEl.className = 'topbar-logo';
        logoDivEl.setAttribute('aria-hidden', 'true');
        logoDivEl.title = 'Link Checker';

        const logoImgEl = document.createElement('img');
        logoImgEl.src = '/static/image/logo.svg';
        logoImgEl.alt = 'Link Checker';
        logoImgEl.style.width = '18px';
        logoImgEl.style.height = '18px';
        logoDivEl.appendChild(logoImgEl);

        const titleEl = document.createElement('span');
        titleEl.className = 'topbar-title';
        titleEl.textContent = titleText;

        brandLinkEl.appendChild(logoDivEl);
        brandLinkEl.appendChild(titleEl);

        if (badgeText) {
            const badgeEl = document.createElement('span');
            badgeEl.className = 'topbar-badge';
            badgeEl.textContent = badgeText;
            brandLinkEl.appendChild(badgeEl);
        }

        this.shadowRoot.appendChild(styleEl);
        this.shadowRoot.appendChild(brandLinkEl);
    }
}

customElements.define('topbar-brand', TopbarBrand);
