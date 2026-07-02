/**
 * job-progress.js
 * 封裝任務爬取進度與統計數據的 Web Component
 */

/**
 * 任務爬取進度卡片元件 (Web Component)
 * 負責渲染任務的整體進度條以及各項處理狀態（如：完成、失敗、略過等）的統計數量。
 *
 * @extends HTMLElement
 */
export class JobProgressCard extends HTMLElement {
    /**
     * 建立 JobProgressCard 元件實例
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
     * 渲染元件整體的 HTML 結構與樣式 (CSS)
     * 包含進度條、狀態統計網格以及匯出報表按鈕
     */
    render() {
        const linkBase = document.createElement('link');
        linkBase.rel = 'stylesheet';
        linkBase.href = '/static/css/base.css';
        this.shadowRoot.appendChild(linkBase);

        const style = document.createElement('style');
        style.textContent = `
            :host { display: block; flex: 2 1 500px; }
        `;
        this.shadowRoot.appendChild(style);

        const card = document.createElement('div');
        card.className = 'card';
        card.style.height = '100%';
        card.style.boxSizing = 'border-box';

        // Header
        const header = document.createElement('div');
        header.className = 'card-header';
        header.style.display = 'flex';
        header.style.justifyContent = 'space-between';
        header.style.alignItems = 'center';

        const title = document.createElement('span');
        title.className = 'card-title';
        title.textContent = '爬取進度';

        const headerRight = document.createElement('div');
        headerRight.style.display = 'flex';
        headerRight.style.gap = '0.75rem';
        headerRight.style.alignItems = 'center';

        this.progressTextEl = document.createElement('span');
        this.progressTextEl.className = 'text-sm font-mono text-muted';
        this.progressTextEl.id = 'job-progress-text';
        this.progressTextEl.textContent = '0%';

        const btnExport = document.createElement('button');
        btnExport.className = 'btn btn-secondary btn-sm';
        btnExport.id = 'btn-export-full';
        btnExport.title = '匯出完整報表 (ZIP 壓縮檔)';

        // Icon for export button (created safely without innerHTML)
        const svgIcon = document.createElement('div');
        svgIcon.style.width = "14px";
        svgIcon.style.height = "14px";
        svgIcon.style.marginRight = "0.25rem";
        svgIcon.style.verticalAlign = "text-bottom";
        svgIcon.style.display = "inline-block";
        svgIcon.style.backgroundColor = "currentColor";
        svgIcon.style.mask = "url(/static/image/download.svg) no-repeat center / contain";
        svgIcon.style.webkitMask = "url(/static/image/download.svg) no-repeat center / contain";

        btnExport.appendChild(svgIcon);
        const exportText = document.createTextNode(' 完整報表');
        btnExport.appendChild(exportText);

        headerRight.appendChild(this.progressTextEl);
        headerRight.appendChild(btnExport);
        header.appendChild(title);
        header.appendChild(headerRight);
        card.appendChild(header);

        // Progress Bar
        const progressContainer = document.createElement('div');
        progressContainer.className = 'progress-bar';
        progressContainer.style.marginBottom = '1.25rem';

        this.progressFillEl = document.createElement('div');
        this.progressFillEl.className = 'progress-fill';
        this.progressFillEl.id = 'job-progress-fill';
        this.progressFillEl.style.width = '0%';

        progressContainer.appendChild(this.progressFillEl);
        card.appendChild(progressContainer);

        // Stats Grid
        const statsGrid = document.createElement('div');
        statsGrid.className = 'grid-stats';

        /**
         * 建立獨立的數據卡片 DOM
         * @param {string} labelText - 卡片標題
         * @param {string} labelClass - 標題 CSS 類別 (包含主題顏色)
         * @param {string} valueClass - 數字 CSS 類別 (包含主題顏色)
         * @param {string} descString - 卡片底部說明文字
         * @returns {Object} 包含 card (卡片 DOM) 與 valueEl (數字 DOM) 的物件
         */
        const createStatNode = (labelText, labelClass, valueClass, descString) => {
            const statCard = document.createElement('div');
            statCard.className = 'stat-card';

            const themeMatch = labelClass.match(/text-(.*)/);
            if (themeMatch) {
                statCard.classList.add(`border-${themeMatch[1]}`);
            }

            const label = document.createElement('div');
            label.className = 'stat-label ' + labelClass;
            label.textContent = labelText;

            const value = document.createElement('div');
            value.className = 'stat-value text-xl ' + valueClass;
            value.textContent = '0';

            const desc = document.createElement('div');
            desc.className = 'stat-desc';
            desc.textContent = descString;

            statCard.appendChild(label);
            statCard.appendChild(value);
            statCard.appendChild(desc);
            return { card: statCard, valueEl: value };
        };

        const totalStat = createStatNode('總計', 'text-brand', 'text-brand', '累計總數');
        this.statTotalEl = totalStat.valueEl;

        const compStat = createStatNode('完成', 'text-success', 'text-success', '成功解析');
        this.statCompletedEl = compStat.valueEl;

        const failStat = createStatNode('失敗', 'text-danger', 'text-danger', '異常網頁');
        this.statFailedEl = failStat.valueEl;

        const warnStat = createStatNode('截斷', 'text-warning', 'text-warning', '過長網頁');
        this.statWarningEl = warnStat.valueEl;

        const skipStat = createStatNode('略過', 'text-muted', 'text-muted', '忽略不解析');
        this.statSkippedEl = skipStat.valueEl;

        const pendStat = createStatNode('等待', 'text-info', 'text-info', '等待處理');
        this.statPendingEl = pendStat.valueEl;

        statsGrid.appendChild(totalStat.card);
        statsGrid.appendChild(compStat.card);
        statsGrid.appendChild(failStat.card);
        statsGrid.appendChild(warnStat.card);
        statsGrid.appendChild(skipStat.card);
        statsGrid.appendChild(pendStat.card);

        card.appendChild(statsGrid);
        this.shadowRoot.appendChild(card);
    }

    /**
     * 依據當前的任務資料 (_job)，計算並更新畫面上的進度百分比與各項數據
     */
    updateView() {
        if (!this._job) return;

        const progress = this._job.progress || {};
        const total = progress.total || 0;
        const processed = progress.completed || 0;

        let percentage = 0;
        if (total > 0) {
            percentage = Math.floor(((total - (progress.pending || 0)) / total) * 100);
        } else if (['completed', 'error'].includes(this._job.status)) {
            percentage = 100;
        }

        this.progressFillEl.style.width = percentage + '%';
        this.progressTextEl.textContent = percentage + '%';

        this.statTotalEl.textContent = total;
        this.statCompletedEl.textContent = progress.completed || 0;
        this.statWarningEl.textContent = progress.warning || 0;
        this.statSkippedEl.textContent = progress.skipped || 0;
        this.statFailedEl.textContent = progress.failed || 0;
        this.statPendingEl.textContent = progress.pending || 0;
    }

    /**
     * 綁定元件內的按鈕點擊事件，如「匯出完整報表」
     */
    setupEventListeners() {
        const btnExport = this.shadowRoot.getElementById('btn-export-full');
        btnExport.addEventListener('click', () => {
            this.dispatchEvent(new CustomEvent('export-full', {
                detail: { job: this._job },
                bubbles: true,
                composed: true
            }));
        });
    }

    /**
     * 移除事件監聽器（目前為空實作）
     */
    teardownEventListeners() { }
}

customElements.define('job-progress', JobProgressCard);
