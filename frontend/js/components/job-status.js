/**
 * job-status.js
 * 封裝任務基本資訊的 Web Component
 */

/**
 * 任務狀態資訊卡片元件 (Web Component)
 * 負責渲染任務的基本屬性資訊，包含起始 URL、建立時間、更新時間，以及提供檢視設定的按鈕。
 *
 * @extends HTMLElement
 */
export class JobStatusCard extends HTMLElement {
    /**
     * 建立 JobStatusCard 元件實例
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        
        /**
         * @type {Object|null} 當前綁定的任務資料物件
         * @private
         */
        this._job = null;
    }

    /**
     * 當元件被插入到 DOM 時觸發 (Lifecycle hook)
     * 負責渲染初始結構與綁定事件監聽器。
     */
    connectedCallback() {
        this.render();
        this.setupEventListeners();
    }

    /**
     * 當元件從 DOM 中被移除時觸發 (Lifecycle hook)
     * 負責解除事件監聽器以避免記憶體洩漏。
     */
    disconnectedCallback() {
        this.teardownEventListeners();
    }

    /**
     * 接收並更新任務資料，同時觸發畫面更新
     * @param {Object} data - 從 API 取得的任務詳細資料物件
     */
    set job(data) {
        this._job = data;
        this.updateView();
    }

    /**
     * 取得當前綁定的任務資料
     * @returns {Object|null} 當前綁定的任務資料物件
     */
    get job() {
        return this._job;
    }

    /**
     * 日期格式化工具
     * 將 ISO 8601 等標準日期字串格式化為本地時間表示法
     * @param {string|null} dateString - 原始日期字串
     * @returns {string} 格式化後的本地日期時間字串，若無效則回傳 '-'
     */
    formatDate(dateString) {
        if (!dateString) return '-';
        const d = new Date(dateString);
        return isNaN(d.getTime()) ? '-' : d.toLocaleString();
    }

    /**
     * 渲染元件整體的 HTML 結構與樣式 (CSS)
     * 包含起始網址、建立時間、更新時間的呈現版面配置
     */
    render() {
        // 嚴格遵守資安規範：禁止使用 innerHTML，全面改用 document.createElement
        const linkBase = document.createElement('link');
        linkBase.rel = 'stylesheet';
        linkBase.href = '/static/css/base.css';
        
        const linkComponents = document.createElement('link');
        linkComponents.rel = 'stylesheet';
        linkComponents.href = '/static/css/components.css';

        this.shadowRoot.appendChild(linkBase);
        this.shadowRoot.appendChild(linkComponents);

        const style = document.createElement('style');
        style.textContent = `
            :host { display: block; flex: 1 1 300px; }
            .truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        `;
        this.shadowRoot.appendChild(style);

        const card = document.createElement('div');
        card.className = 'card';
        card.style.height = '100%';
        card.style.boxSizing = 'border-box';

        const header = document.createElement('div');
        header.className = 'card-header';
        header.style.display = 'flex';
        header.style.justifyContent = 'space-between';
        header.style.alignItems = 'center';

        const title = document.createElement('span');
        title.className = 'card-title';
        title.textContent = '任務資訊';
        
        const btnConfig = document.createElement('button');
        btnConfig.className = 'btn btn-ghost btn-sm';
        btnConfig.id = 'btn-view-config';
        btnConfig.style.padding = '0.25rem 0.5rem';
        btnConfig.textContent = '檢視設定';
        
        header.appendChild(title);
        header.appendChild(btnConfig);
        card.appendChild(header);

        const content = document.createElement('div');
        content.style.display = 'flex';
        content.style.flexDirection = 'column';
        content.style.gap = '0.75rem';

        // 起始 URL 區塊
        const urlWrapper = document.createElement('div');
        const urlLabel = document.createElement('div');
        urlLabel.className = 'text-xs text-muted';
        urlLabel.textContent = '起始 URL';
        
        const urlLink = document.createElement('a');
        urlLink.className = 'font-mono text-sm truncate';
        urlLink.id = 'job-start-url';
        urlLink.style.maxWidth = '100%';
        urlLink.style.display = 'block';
        urlLink.style.color = 'inherit';
        urlLink.target = '_blank';
        urlLink.rel = 'noopener noreferrer';
        urlLink.textContent = '-';
        
        urlWrapper.appendChild(urlLabel);
        urlWrapper.appendChild(urlLink);
        content.appendChild(urlWrapper);

        // 時間區塊
        const timeGrid = document.createElement('div');
        timeGrid.style.display = 'grid';
        timeGrid.style.gridTemplateColumns = '1fr 1fr';
        timeGrid.style.gap = '0.5rem';

        const createWrapper = document.createElement('div');
        const createLabel = document.createElement('div');
        createLabel.className = 'text-xs text-muted';
        createLabel.textContent = '建立時間';
        const createValue = document.createElement('div');
        createValue.className = 'text-sm';
        createValue.id = 'job-created-at';
        createValue.textContent = '-';
        createWrapper.appendChild(createLabel);
        createWrapper.appendChild(createValue);

        const updateWrapper = document.createElement('div');
        const updateLabel = document.createElement('div');
        updateLabel.className = 'text-xs text-muted';
        updateLabel.textContent = '最後更新';
        const updateValue = document.createElement('div');
        updateValue.className = 'text-sm';
        updateValue.id = 'job-updated-at';
        updateValue.textContent = '-';
        updateWrapper.appendChild(updateLabel);
        updateWrapper.appendChild(updateValue);

        timeGrid.appendChild(createWrapper);
        timeGrid.appendChild(updateWrapper);
        content.appendChild(timeGrid);

        card.appendChild(content);
        this.shadowRoot.appendChild(card);
    }

    /**
     * 依據當前的任務資料 (_job)，更新畫面上的起始網址與日期時間字串
     */
    updateView() {
        if (!this._job) return;
        
        const startUrlEl = this.shadowRoot.getElementById('job-start-url');
        const createdAtEl = this.shadowRoot.getElementById('job-created-at');
        const updatedAtEl = this.shadowRoot.getElementById('job-updated-at');

        startUrlEl.textContent = this._job.start_url || '-';
        if (this._job.start_url) {
            startUrlEl.href = this._job.start_url;
        } else {
            startUrlEl.removeAttribute('href');
        }

        createdAtEl.textContent = this.formatDate(this._job.created_at);
        updatedAtEl.textContent = this.formatDate(this._job.updated_at);
    }

    /**
     * 綁定元件內的按鈕點擊事件，發送「檢視設定」的自訂事件
     */
    setupEventListeners() {
        const btnConfig = this.shadowRoot.getElementById('btn-view-config');
        btnConfig.addEventListener('click', () => {
            // 發送客製化事件供外部 (job-detail.js) 聆聽並處理 Modal
            this.dispatchEvent(new CustomEvent('view-config', {
                detail: { job: this._job },
                bubbles: true,
                composed: true
            }));
        });
    }

    /**
     * 移除事件監聽器
     */
    teardownEventListeners() {
        // Shadow DOM 元素會隨元件銷毀自動回收，但顯式清理是個好習慣
    }
}

customElements.define('job-status', JobStatusCard);
