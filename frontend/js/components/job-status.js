/**
 * job-status.js
 * 封裝任務基本資訊的 Web Component
 */

import { formatLocalTime } from '../api.js';

/**
 * 任務狀態資訊卡片元件 (Web Component)
 * 負責渲染任務的基本屬性資訊，包含起始 URL、建立時間、更新時間，
 * 以及提供「檢視設定」按鈕供使用者查看完整爬蟲設定參數。
 *
 * @extends HTMLElement
 *
 * @fires view-config - 點擊「檢視設定」按鈕時觸發，detail: `{ job: Object }`
 *
 * @example
 * <job-status></job-status>
 * // 透過 JS 注入資料：
 * document.querySelector('job-status').job = jobData;
 */
export class JobStatusCard extends HTMLElement {
    /**
     * 建立 JobStatusCard 元件實例，初始化私有狀態與快取參考。
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });

        /**
         * 當前綁定的任務資料物件；為 null 時元件顯示初始佔位符
         * @type {Object|null}
         * @private
         */
        this._job = null;

        /**
         * 顯示起始 URL 的 `<a>` 元素（在 render() 後快取）
         * @type {HTMLAnchorElement|null}
         * @private
         */
        this._startUrlEl = null;

        /**
         * 顯示建立時間的 `<div>` 元素（在 render() 後快取）
         * @type {HTMLElement|null}
         * @private
         */
        this._createdAtEl = null;

        /**
         * 顯示最後更新時間的 `<div>` 元素（在 render() 後快取）
         * @type {HTMLElement|null}
         * @private
         */
        this._updatedAtEl = null;

        /**
         * 「檢視設定」按鈕元素（在 render() 後快取）
         * @type {HTMLButtonElement|null}
         * @private
         */
        this._btnConfigEl = null;
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
     * 接收並更新任務資料，同時觸發畫面更新。
     * 傳入 null 或 undefined 時，畫面維持初始佔位符狀態不變。
     * @param {Object|null} data - 從 API 取得的任務詳細資料物件
     * @param {string} [data.start_url]  - 任務的起始爬取 URL
     * @param {string} [data.created_at] - 任務建立時間 (ISO 8601)
     * @param {string} [data.updated_at] - 任務最後更新時間 (ISO 8601)
     * @param {Object} [data.config]     - 任務完整設定物件（供 view-config 事件使用）
     */
    set job(data) {
        if (!data) return;
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
     * 渲染元件整體的 HTML 結構與 Shadow DOM 樣式。
     * 同時將需要動態更新的 DOM 節點快取為 instance 私有變數，
     * 避免 updateView() 呼叫時重複查詢 Shadow DOM。
     */
    render() {
        const linkBaseEl = document.createElement('link');
        linkBaseEl.rel = 'stylesheet';
        linkBaseEl.href = '/static/css/base.css';
        this.shadowRoot.appendChild(linkBaseEl);

        const styleEl = document.createElement('style');
        styleEl.textContent = `
            :host { display: block; flex: 1 1 200px; }
            .card { height: 100%; }
            .icon-info {
                mask: url(/static/image/icon-info.svg) no-repeat center / contain;
                -webkit-mask: url(/static/image/icon-info.svg) no-repeat center / contain;
            }
            .card-content { display: flex; flex-direction: column; gap: 1rem; }
            .card-time-grid { display: flex; flex-direction: column; gap: .5rem; }
            #job-start-url { max-width: 100%; display: block; color: inherit; }
        `;
        this.shadowRoot.appendChild(styleEl);

        // ── Card Shell ────────────────────────────────────────────────────
        const cardEl = document.createElement('div');
        cardEl.className = 'card';

        // ── Header ────────────────────────────────────────────────────────
        const headerEl = document.createElement('div');
        headerEl.className = 'card-header';

        const titleEl = document.createElement('span');
        titleEl.className = 'card-title';
        titleEl.textContent = '任務資訊';

        this._btnConfigEl = document.createElement('button');
        this._btnConfigEl.className = 'btn btn-secondary btn-sm';
        this._btnConfigEl.id = 'btn-view-config';
        this._btnConfigEl.title = '檢視此任務的完整設定';

        const configIconEl = document.createElement('div');
        configIconEl.className = 'mask-icon mask-icon-btn icon-info';

        this._btnConfigEl.appendChild(configIconEl);
        this._btnConfigEl.appendChild(document.createTextNode(' 檢視設定'));

        headerEl.appendChild(titleEl);
        headerEl.appendChild(this._btnConfigEl);
        cardEl.appendChild(headerEl);

        // ── Content ───────────────────────────────────────────────────────
        const contentEl = document.createElement('div');
        contentEl.className = 'card-content';

        // 起始 URL 區塊
        const urlWrapperEl = document.createElement('div');
        const urlLabelEl = document.createElement('div');
        urlLabelEl.className = 'text-xs text-muted';
        urlLabelEl.textContent = '起始 URL';

        this._startUrlEl = document.createElement('a');
        this._startUrlEl.className = 'font-mono text-sm truncate';
        this._startUrlEl.id = 'job-start-url';
        this._startUrlEl.target = '_blank';
        this._startUrlEl.rel = 'noopener noreferrer';
        this._startUrlEl.textContent = '-';

        urlWrapperEl.appendChild(urlLabelEl);
        urlWrapperEl.appendChild(this._startUrlEl);
        contentEl.appendChild(urlWrapperEl);

        // 時間區塊（建立時間 / 最後更新，上下排列）
        const timeGridEl = document.createElement('div');
        timeGridEl.className = 'card-time-grid';

        const createWrapperEl = document.createElement('div');
        const createLabelEl = document.createElement('div');
        createLabelEl.className = 'text-xs text-muted';
        createLabelEl.textContent = '建立時間';
        this._createdAtEl = document.createElement('div');
        this._createdAtEl.className = 'text-sm';
        this._createdAtEl.id = 'job-created-at';
        this._createdAtEl.textContent = '-';
        createWrapperEl.appendChild(createLabelEl);
        createWrapperEl.appendChild(this._createdAtEl);

        const updateWrapperEl = document.createElement('div');
        const updateLabelEl = document.createElement('div');
        updateLabelEl.className = 'text-xs text-muted';
        updateLabelEl.textContent = '最後更新';
        this._updatedAtEl = document.createElement('div');
        this._updatedAtEl.className = 'text-sm';
        this._updatedAtEl.id = 'job-updated-at';
        this._updatedAtEl.textContent = '-';
        updateWrapperEl.appendChild(updateLabelEl);
        updateWrapperEl.appendChild(this._updatedAtEl);

        timeGridEl.appendChild(createWrapperEl);
        timeGridEl.appendChild(updateWrapperEl);
        contentEl.appendChild(timeGridEl);

        cardEl.appendChild(contentEl);
        this.shadowRoot.appendChild(cardEl);
    }

    /**
     * 依據當前的任務資料 (`this._job`) 更新畫面上的起始網址與時間字串。
     * 若任務資料或 DOM 尚未就緒則直接返回，不做任何操作。
     */
    updateView() {
        if (!this._job || !this._startUrlEl) return;

        this._startUrlEl.textContent = this._job.start_url || '-';
        if (this._job.start_url) {
            this._startUrlEl.href = this._job.start_url;
        } else {
            this._startUrlEl.removeAttribute('href');
        }

        this._createdAtEl.textContent = formatLocalTime(this._job.created_at);
        this._updatedAtEl.textContent = formatLocalTime(this._job.updated_at);
    }

    /**
     * 綁定元件內的按鈕點擊事件。
     * 點擊「檢視設定」時，對外派送 `view-config` 自訂事件，
     * 由外部（job-detail.js）負責開啟對應的設定 Modal。
     *
     * @fires view-config
     */
    setupEventListeners() {
        this._btnConfigEl.addEventListener('click', () => {
            this.dispatchEvent(new CustomEvent('view-config', {
                detail: { job: this._job },
                bubbles: true,
                composed: true,
            }));
        });
    }

    /**
     * 移除事件監聽器。
     * 由於事件均掛載於 Shadow DOM 的子節點上，當元件從 DOM 移除時
     * 瀏覽器會自動回收，此處無需手動解除。
     */
    teardownEventListeners() { }
}

customElements.define('job-status', JobStatusCard);
