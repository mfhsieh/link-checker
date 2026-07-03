/**
 * job-progress.js
 * 封裝任務爬取進度與統計數據的 Web Component
 */

/**
 * 任務爬取進度卡片元件 (Web Component)
 * 負責渲染任務的整體進度條以及各項處理狀態（如：完成、失敗、略過等）的統計數量。
 *
 * @extends HTMLElement
 *
 * @fires export-full - 點擊「完整報表」按鈕時觸發，detail: `{ job: Object }`
 *
 * @example
 * <job-progress></job-progress>
 * // 透過 JS 注入資料：
 * document.querySelector('job-progress').job = jobData;
 */
export class JobProgressCard extends HTMLElement {
    /**
     * 建立 JobProgressCard 元件實例，初始化私有狀態與快取參考。
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });

        /**
         * 當前綁定的任務資料物件；為 null 時元件顯示初始佔位符狀態
         * @type {Object|null}
         * @private
         */
        this._job = null;

        /**
         * 顯示進度百分比文字的 `<span>` 元素（在 render() 後快取）
         * @type {HTMLElement|null}
         * @private
         */
        this._progressTextEl = null;

        /**
         * 進度條填充的 `<div>` 元素（在 render() 後快取）
         * @type {HTMLElement|null}
         * @private
         */
        this._progressFillEl = null;

        /**
         * 「匯出完整報表」按鈕元素（在 render() 後快取）
         * @type {HTMLButtonElement|null}
         * @private
         */
        this._btnExportEl = null;

        /** @type {HTMLElement|null} @private */ this._statTotalEl = null;
        /** @type {HTMLElement|null} @private */ this._statCompletedEl = null;
        /** @type {HTMLElement|null} @private */ this._statFailedEl = null;
        /** @type {HTMLElement|null} @private */ this._statWarningEl = null;
        /** @type {HTMLElement|null} @private */ this._statSkippedEl = null;
        /** @type {HTMLElement|null} @private */ this._statPendingEl = null;
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
     * @param {string}         [data.status]   - 任務狀態字串（如 'completed', 'error'）
     * @param {Object}         [data.progress] - 進度統計物件
     * @param {number}         [data.progress.total]     - 總頁數
     * @param {number}         [data.progress.completed] - 已完成頁數
     * @param {number}         [data.progress.failed]    - 失敗頁數
     * @param {number}         [data.progress.warning]   - 截斷頁數
     * @param {number}         [data.progress.skipped]   - 略過頁數
     * @param {number}         [data.progress.pending]   - 等待中頁數
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
     * 建立獨立的數據卡片 DOM 結構。
     * @param {string} labelText  - 卡片標題文字
     * @param {string} theme      - 卡片主題顏色 ('brand'|'success'|'warning'|'danger'|'info'|'muted')
     * @param {string} descString - 卡片底部說明文字
     * @returns {{ cardEl: HTMLDivElement, valueEl: HTMLDivElement }} 包含卡片容器與數字節點的物件
     * @private
     */
    _createStatCard(labelText, theme, descString) {
        const themeClass = theme ? `text-${theme}` : '';

        const cardEl = document.createElement('div');
        cardEl.className = 'stat-card';
        if (theme) {
            cardEl.classList.add(`border-${theme}`);
        }

        const labelEl = document.createElement('div');
        labelEl.className = `stat-label ${themeClass}`.trim();
        labelEl.textContent = labelText;

        const valueEl = document.createElement('div');
        valueEl.className = `stat-value ${themeClass}`.trim();
        valueEl.textContent = '-';

        const descEl = document.createElement('div');
        descEl.className = 'stat-desc';
        descEl.textContent = descString;

        cardEl.appendChild(labelEl);
        cardEl.appendChild(valueEl);
        cardEl.appendChild(descEl);

        return { cardEl, valueEl };
    }

    /**
     * 渲染元件整體的 HTML 結構與 Shadow DOM 樣式。
     * 包含進度條、狀態統計網格以及匯出報表按鈕。
     * 同時將需要動態更新的 DOM 節點快取為 instance 私有變數，
     * 避免 updateView() 與 setupEventListeners() 呼叫時重複查詢 Shadow DOM。
     */
    render() {
        const linkBaseEl = document.createElement('link');
        linkBaseEl.rel = 'stylesheet';
        linkBaseEl.href = '/static/css/base.css';
        this.shadowRoot.appendChild(linkBaseEl);

        const styleEl = document.createElement('style');
        styleEl.textContent = `
            :host { display: block; flex: 3 1 600px; }
            .card { height: 100%; }
            .header-right { display: flex; gap: 0.75rem; align-items: center; }
            .icon-download {
                mask: url(/static/image/icon-download.svg) no-repeat center / contain;
                -webkit-mask: url(/static/image/icon-download.svg) no-repeat center / contain;
            }
            .progress-bar { margin-bottom: 1.25rem; }
        `;
        this.shadowRoot.appendChild(styleEl);

        const cardEl = document.createElement('div');
        cardEl.className = 'card';

        // ── Header ────────────────────────────────────────────────────────
        const headerEl = document.createElement('div');
        headerEl.className = 'card-header';

        const titleEl = document.createElement('span');
        titleEl.className = 'card-title';
        titleEl.textContent = '爬取進度';

        const headerRightEl = document.createElement('div');
        headerRightEl.className = 'header-right';

        this._progressTextEl = document.createElement('span');
        this._progressTextEl.className = 'text-sm font-mono text-muted';
        this._progressTextEl.id = 'job-progress-text';
        this._progressTextEl.textContent = '0%';

        this._btnExportEl = document.createElement('button');
        this._btnExportEl.className = 'btn btn-secondary btn-sm';
        this._btnExportEl.id = 'btn-export-full';
        this._btnExportEl.title = '匯出完整報表 (ZIP 壓縮檔)';

        const exportIconEl = document.createElement('div');
        exportIconEl.className = 'mask-icon mask-icon-btn icon-download';

        this._btnExportEl.appendChild(exportIconEl);
        this._btnExportEl.appendChild(document.createTextNode(' 完整報表'));

        headerRightEl.appendChild(this._progressTextEl);
        headerRightEl.appendChild(this._btnExportEl);
        headerEl.appendChild(titleEl);
        headerEl.appendChild(headerRightEl);
        cardEl.appendChild(headerEl);

        // ── Progress Bar ──────────────────────────────────────────────────
        const progressContainerEl = document.createElement('div');
        progressContainerEl.className = 'progress-bar';

        this._progressFillEl = document.createElement('div');
        this._progressFillEl.className = 'progress-fill';
        this._progressFillEl.id = 'job-progress-fill';
        this._progressFillEl.style.width = '0%';

        progressContainerEl.appendChild(this._progressFillEl);
        cardEl.appendChild(progressContainerEl);

        // ── Stats Grid ────────────────────────────────────────────────────
        const statsGridEl = document.createElement('div');
        statsGridEl.className = 'grid-stats';

        const totalStat = this._createStatCard('總計', 'brand', '累計總數');
        const compStat = this._createStatCard('完成', 'success', '成功解析');
        const failStat = this._createStatCard('失敗', 'danger', '異常網頁');
        const warnStat = this._createStatCard('截斷', 'warning', '過長網頁');
        const skipStat = this._createStatCard('略過', 'muted', '忽略不解析');
        const pendStat = this._createStatCard('等待', 'info', '等待處理');

        this._statTotalEl = totalStat.valueEl;
        this._statCompletedEl = compStat.valueEl;
        this._statFailedEl = failStat.valueEl;
        this._statWarningEl = warnStat.valueEl;
        this._statSkippedEl = skipStat.valueEl;
        this._statPendingEl = pendStat.valueEl;

        statsGridEl.appendChild(totalStat.cardEl);
        statsGridEl.appendChild(compStat.cardEl);
        statsGridEl.appendChild(failStat.cardEl);
        statsGridEl.appendChild(warnStat.cardEl);
        statsGridEl.appendChild(skipStat.cardEl);
        statsGridEl.appendChild(pendStat.cardEl);

        cardEl.appendChild(statsGridEl);
        this.shadowRoot.appendChild(cardEl);
    }

    /**
     * 依據當前的任務資料 (`this._job`) 計算並更新畫面上的進度百分比與各項數據。
     * 進度百分比的計算方式為：已處理數（total - pending）佔 total 的比例；
     * 若任務已進入終止狀態（completed / error）且無進度資料，則固定顯示 100%。
     * 若任務資料或 DOM 尚未就緒則直接返回，不做任何操作。
     */
    updateView() {
        if (!this._job || !this._progressFillEl) return;

        const progress = this._job.progress || {};
        const total = progress.total || 0;
        const pending = progress.pending || 0;

        let percentage = 0;
        if (total > 0) {
            percentage = Math.floor(((total - pending) / total) * 100);
        } else if (['completed', 'error'].includes(this._job.status)) {
            percentage = 100;
        }

        this._progressFillEl.style.width = `${percentage}%`;
        this._progressTextEl.textContent = `${percentage}%`;

        this._statTotalEl.textContent = total;
        this._statCompletedEl.textContent = progress.completed || 0;
        this._statWarningEl.textContent = progress.warning || 0;
        this._statSkippedEl.textContent = progress.skipped || 0;
        this._statFailedEl.textContent = progress.failed || 0;
        this._statPendingEl.textContent = pending;
    }

    /**
     * 綁定元件內的按鈕點擊事件。
     * 點擊「完整報表」時，對外派送 `export-full` 自訂事件，
     * 由外部（job-detail.js）負責處理報表的匯出邏輯。
     *
     * @fires export-full
     */
    setupEventListeners() {
        this._btnExportEl.addEventListener('click', () => {
            this.dispatchEvent(new CustomEvent('export-full', {
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

customElements.define('job-progress', JobProgressCard);
