/**
 * 側邊欄 (Sidebar) Web Component
 * 支援 app 與 admin 兩種模式，並可透過 active-id 屬性設定當前啟用的選單。
 */
class AppSidebar extends HTMLElement {
    /**
     * 建立 AppSidebar 實例並初始化 Shadow DOM
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }

    /**
     * 宣告欲觀察變化的屬性清單
     * @returns {string[]} 需要被觀察的屬性名稱陣列
     */
    static get observedAttributes() {
        return ['mode', 'active-id', 'is-admin', 'open'];
    }

    /**
     * 當觀察的屬性發生變化時被呼叫
     * @param {string} name - 變更的屬性名稱
     * @param {string|null} oldValue - 舊的屬性值
     * @param {string|null} newValue - 新的屬性值
     */
    attributeChangedCallback(name, oldValue, newValue) {
        if (name === 'open') {
            window.dispatchEvent(new CustomEvent('sidebar-state', { 
                detail: { open: newValue !== null } 
            }));
            return; // 不需要觸發 render()
        }
        if (oldValue !== newValue) {
            this.render();
        }
    }

    /**
     * 當元素被加入至 DOM 中時被呼叫
     */
    connectedCallback() {
        if (!this.hasRendered) {
            this.render();
            this.hasRendered = true;
        }
        
        // 監聽全域的 sidebar-toggle 事件
        this._toggleHandler = () => this.toggleAttribute('open');
        window.addEventListener('sidebar-toggle', this._toggleHandler);
    }

    /**
     * 當元素從 DOM 中被移除時被呼叫
     */
    disconnectedCallback() {
        if (this._toggleHandler) {
            window.removeEventListener('sidebar-toggle', this._toggleHandler);
        }
    }

    /**
     * 取得目前的模式設定
     * @returns {string} 模式字串 ('app' 或 'admin')，預設為 'app'
     */
    get mode() {
        return this.getAttribute('mode') || 'app';
    }

    /**
     * 取得目前作用中的選單 ID
     * @returns {string} 作用中的選單 ID
     */
    get activeId() {
        return this.getAttribute('active-id') || '';
    }

    /**
     * 判斷是否具備管理員權限
     * @returns {boolean} 若有 'is-admin' 屬性則回傳 true，否則為 false
     */
    get isAdmin() {
        return this.hasAttribute('is-admin');
    }

    /**
     * 重新渲染側邊欄結構與樣式至 Shadow DOM
     */
    render() {
        const linkBaseEl = document.createElement('link');
        linkBaseEl.rel = 'stylesheet';
        linkBaseEl.href = '/static/css/base.css';

        const linkLayoutEl = document.createElement('link');
        linkLayoutEl.rel = 'stylesheet';
        linkLayoutEl.href = '/static/css/layout.css';

        const styleEl = document.createElement('style');
        styleEl.textContent = `
            :host {
                display: contents; /* 讓內部的 .sidebar 直接參與外部排版 */
            }
            .sidebar {
                opacity: 0; /* 預設隱藏，等待 CSS 載入 */
                transition: opacity 0.15s ease-out;
            }
            .sidebar.ready {
                opacity: 1;
            }
            .sidebar-overlay {
                display: none;
            }
            @media (max-width: 768px) {
                .sidebar-overlay {
                    position: fixed;
                    top: 61px;
                    left: 0;
                    width: 100vw;
                    height: calc(100vh - 61px);
                    background: rgba(0, 0, 0, 0.4);
                    z-index: 1000;
                    opacity: 0;
                    transition: opacity 0.3s;
                    pointer-events: none;
                }
                .sidebar {
                    position: fixed;
                    top: 61px;
                    left: 0;
                    bottom: 0;
                    width: 150px;
                    background: var(--surface-base);
                    z-index: 1001;
                    transform: translateX(-100%);
                    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                    border-right: 1px solid var(--surface-border-subtle);
                    overflow-y: auto;
                }
                :host([open]) .sidebar-overlay {
                    display: block;
                    opacity: 1;
                    pointer-events: auto;
                }
                :host([open]) .sidebar {
                    transform: translateX(0);
                }
            }
        `;

        const overlayEl = document.createElement('div');
        overlayEl.className = 'sidebar-overlay';
        overlayEl.addEventListener('click', () => {
            this.removeAttribute('open');
        });

        const navEl = document.createElement('nav');
        navEl.className = 'sidebar';
        navEl.setAttribute('aria-label', this.mode === 'admin' ? '後台管理' : '前台功能');

        const menus = this.getMenus(this.mode);

        menus.forEach((section, index) => {
            // 管理員專區處理
            if (section.title === '後台管理' && this.mode === 'app' && !this.isAdmin) {
                return; // 不顯示
            }

            if (index > 0) {
                const divider = document.createElement('div');
                divider.className = 'sidebar-divider';
                navEl.appendChild(divider);
            }

            const sectionEl = document.createElement('div');
            sectionEl.className = 'sidebar-section';

            if (section.id) {
                sectionEl.id = section.id;
            }

            const titleEl = document.createElement('div');
            titleEl.className = 'sidebar-section-title';
            titleEl.textContent = section.title;
            sectionEl.appendChild(titleEl);

            const ulEl = document.createElement('ul');
            ulEl.className = 'sidebar-nav';

            section.items.forEach(item => {
                const liEl = document.createElement('li');
                const aEl = document.createElement('a');
                aEl.className = 'sidebar-item';
                if (item.id === this.activeId) {
                    aEl.classList.add('active');
                }
                if (item.id) {
                    aEl.id = item.id;
                }
                aEl.href = item.href;

                // 使用 CSS Mask 來載入外部 SVG 並繼承顏色
                if (item.icon) {
                    const iconSpan = document.createElement('span');
                    iconSpan.className = 'mask-icon sidebar-icon';
                    // sidebar-icon 負責繼承 color (來自 layout.css 的 active/hover)
                    // mask-icon 負責 background-color: currentColor 與 mask-image

                    iconSpan.style.mask = `url(${item.icon}) no-repeat center / contain`;
                    iconSpan.style.webkitMask = `url(${item.icon}) no-repeat center / contain`;
                    aEl.appendChild(iconSpan);
                }
                if (item.text) {
                    aEl.appendChild(document.createTextNode(item.text));
                }

                // 在窄螢幕點擊連結時，自動關閉側邊欄
                aEl.addEventListener('click', () => {
                    if (window.innerWidth <= 768) {
                        this.removeAttribute('open');
                    }
                });

                liEl.appendChild(aEl);
                ulEl.appendChild(liEl);
            });

            sectionEl.appendChild(ulEl);
            navEl.appendChild(sectionEl);
        });

        // 避免 FOUC (Flash of Unstyled Content)
        let cssLoaded = 0;
        const checkCssLoaded = () => {
            cssLoaded++;
            if (cssLoaded >= 2) {
                navEl.classList.add('ready');
            }
        };
        linkBaseEl.addEventListener('load', checkCssLoaded);
        linkLayoutEl.addEventListener('load', checkCssLoaded);
        // Fallback: 如果快取直接套用沒觸發 load，200ms 後強制顯示
        setTimeout(() => navEl.classList.add('ready'), 200);

        this.shadowRoot.replaceChildren();
        this.shadowRoot.appendChild(linkBaseEl);
        this.shadowRoot.appendChild(linkLayoutEl);
        this.shadowRoot.appendChild(styleEl);
        this.shadowRoot.appendChild(overlayEl);
        this.shadowRoot.appendChild(navEl);
    }

    /**
     * 根據模式取得對應的導覽列選單資料
     * @param {string} mode - 當前模式 ('app' 或 'admin')
     * @returns {Array<{title: string, id?: string, items: Array<{id: string, href: string, text: string, icon: string}>}>} 選單結構陣列
     */
    getMenus(mode) {
        const MENUS = {
            "app": [
                {
                    "title": "任務管理",
                    "items": [
                        {
                            "id": "nav-jobs",
                            "href": "/app.html#/jobs",
                            "text": "我的任務",
                            "icon": "/static/image/icon-jobs.svg"
                        },
                        {
                            "id": "nav-duplicate",
                            "href": "/app.html#/duplicate",
                            "text": "複製任務",
                            "icon": "/static/image/icon-duplicate.svg"
                        },
                        {
                            "id": "nav-compare",
                            "href": "/app.html#/compare",
                            "text": "比對任務",
                            "icon": "/static/image/icon-compare.svg"
                        },
                        {
                            "id": "nav-transfer",
                            "href": "/app.html#/transfer",
                            "text": "移交任務",
                            "icon": "/static/image/icon-transfer.svg"
                        },
                        {
                            "id": "nav-new-job",
                            "href": "/app.html#/new",
                            "text": "新增任務",
                            "icon": "/static/image/icon-new.svg"
                        }
                    ]
                },
                {
                    "title": "支援",
                    "items": [
                        {
                            "id": "nav-help",
                            "href": "/help.html",
                            "text": "說明與教學",
                            "icon": "/static/image/icon-help.svg"
                        },
                        {
                            "id": "nav-faq",
                            "href": "/faq.html",
                            "text": "常見問答",
                            "icon": "/static/image/icon-faq.svg"
                        }
                    ]
                },
                {
                    "title": "後台管理",
                    "items": [
                        {
                            "id": "",
                            "href": "/admin.html",
                            "text": "進入後台",
                            "icon": "/static/image/icon-config.svg"
                        }
                    ],
                    "id": "admin-nav-section"
                }
            ],
            "admin": [
                {
                    "title": "後台管理",
                    "items": [
                        {
                            "id": "nav-users",
                            "href": "/admin.html#/admin/users",
                            "text": "使用者管理",
                            "icon": "/static/image/icon-users.svg"
                        },
                        {
                            "id": "nav-jobs",
                            "href": "/admin.html#/admin/jobs",
                            "text": "任務監控",
                            "icon": "/static/image/icon-monitor.svg"
                        },
                        {
                            "id": "nav-config",
                            "href": "/admin.html#/admin/config",
                            "text": "爬蟲配置",
                            "icon": "/static/image/icon-config.svg"
                        },
                        {
                            "id": "nav-smtp",
                            "href": "/admin.html#/admin/smtp",
                            "text": "郵件測試",
                            "icon": "/static/image/icon-smtp.svg"
                        },
                        {
                            "id": "nav-logs",
                            "href": "/admin.html#/admin/logs",
                            "text": "操作日誌",
                            "icon": "/static/image/icon-logs.svg"
                        }
                    ]
                },
                {
                    "title": "任務管理",
                    "items": [
                        {
                            "id": "",
                            "href": "/app.html",
                            "text": "回到前台",
                            "icon": "/static/image/icon-home.svg"
                        }
                    ]
                }
            ]
        };
        return MENUS[mode] || MENUS['app'];
    }
}

customElements.define('app-sidebar', AppSidebar);
