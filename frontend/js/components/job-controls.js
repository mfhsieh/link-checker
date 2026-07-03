/**
 * job-controls.js
 * 封裝任務操作按鈕的 Web Component (啟動、暫停、刪除等)
 */

/**
 * 任務操作控制列元件 (Web Component)
 * 根據任務的當前狀態（`status`、`is_running`），動態顯示對應的操作按鈕。
 *
 * @extends HTMLElement
 *
 * @fires job-start     - 點擊「啟動／恢復」按鈕時觸發
 * @fires job-pause     - 點擊「暫停」按鈕時觸發
 * @fires job-reset     - 點擊「重置」按鈕時觸發
 * @fires job-retry     - 點擊「重試」按鈕時觸發
 * @fires job-delete    - 點擊「刪除」按鈕時觸發
 * @fires job-duplicate - 點擊「複製」按鈕時觸發
 * @fires job-compare   - 點擊「比對」按鈕時觸發
 * @fires job-transfer  - 點擊「移交」按鈕時觸發
 *
 * @example
 * <job-controls></job-controls>
 * // 透過 JS 注入資料：
 * document.querySelector('job-controls').job = jobData;
 */
export class JobControls extends HTMLElement {
    /**
     * 建立 JobControls 元件實例，初始化私有狀態與按鈕快取。
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });

        /**
         * 當前任務的狀態字串（如 'pending', 'running', 'completed', 'error', 'paused'）
         * @type {string|null}
         * @private
         */
        this._jobStatus = null;

        /**
         * 當前任務是否正在執行
         * @type {boolean}
         * @private
         */
        this._jobIsRunning = false;

        /**
         * 各操作按鈕的快取對照表，以 ID 為 key
         * @type {Object<string, HTMLButtonElement>}
         * @private
         */
        this._buttons = {};
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
     * 接收任務資料，更新內部狀態並刷新按鈕顯示。
     * 傳入 null 或 undefined 時直接返回，不做任何操作。
     * @param {Object|null} job            - 任務資料物件
     * @param {string}      job.status     - 任務狀態字串
     * @param {boolean}     job.is_running - 任務是否正在執行
     */
    set job(job) {
        if (!job) return;
        this._jobStatus = job.status;
        this._jobIsRunning = job.is_running;
        this.updateView();
    }

    /**
     * 建立圖示元素，使用 mask-image 技術讓圖示顏色繼承按鈕的 `currentColor`。
     * @param {string} name - 圖示名稱（對應 `/static/image/icon-{name}.svg`）
     * @returns {HTMLSpanElement} 圖示 `<span>` 元素
     * @private
     */
    _createIcon(name) {
        const iconEl = document.createElement('span');
        const url = `/static/image/icon-${name}.svg`;
        iconEl.className = 'mask-icon mask-icon-btn';
        iconEl.style.webkitMask = `url('${url}') no-repeat center / contain`;
        iconEl.style.mask = `url('${url}') no-repeat center / contain`;
        return iconEl;
    }

    /**
     * 建立操作按鈕，並將其快取至 `this._buttons`。
     * 按鈕預設隱藏（`display: none`），由 `updateView()` 依狀態控制顯示。
     * @param {string}           id        - 按鈕的 DOM ID（同時作為 `_buttons` 的 key）
     * @param {string}           className - 按鈕的 CSS class 字串
     * @param {string}           title     - 滑鼠懸停時顯示的 tooltip 文字
     * @param {string}           text      - 按鈕的標籤文字
     * @param {HTMLElement|null} [icon]    - 可選的圖示元素，會插入於文字之前
     * @returns {HTMLButtonElement} 建立完成的按鈕元素
     * @private
     */
    _createButton(id, className, title, text, icon = null) {
        const btnEl = document.createElement('button');
        btnEl.id = id;
        btnEl.className = className;
        btnEl.title = title;
        btnEl.style.display = 'none';

        if (icon) {
            btnEl.appendChild(icon);
        }
        btnEl.appendChild(document.createTextNode(text));

        this._buttons[id] = btnEl;
        return btnEl;
    }

    /**
     * 渲染元件的 HTML 結構與 Shadow DOM 樣式。
     * 所有按鈕直接掛於 `shadowRoot`，由 `:host` 的 flex 佈局排列。
     */
    render() {
        const linkBaseEl = document.createElement('link');
        linkBaseEl.rel = 'stylesheet';
        linkBaseEl.href = '/static/css/base.css';
        this.shadowRoot.appendChild(linkBaseEl);

        const styleEl = document.createElement('style');
        styleEl.textContent = `
            :host { display: flex; gap: 0.75rem; flex-wrap: wrap; }
        `;
        this.shadowRoot.appendChild(styleEl);

        // 按鈕直接掛於 shadowRoot，由 :host flex 負責排列
        this.shadowRoot.appendChild(this._createButton('btn-duplicate-job', 'btn btn-secondary btn-sm', '複製此任務的設定並建立新任務', '複製', this._createIcon('duplicate')));
        this.shadowRoot.appendChild(this._createButton('btn-goto-compare', 'btn btn-secondary btn-sm', '跳轉至比對視圖，並將此任務設為基準', '比對', this._createIcon('compare')));
        this.shadowRoot.appendChild(this._createButton('btn-transfer-job', 'btn btn-secondary btn-sm', '將此任務移交給其他帳號', '移交', this._createIcon('transfer')));
        this.shadowRoot.appendChild(this._createButton('btn-start-job', 'btn btn-primary btn-sm', '開始或繼續執行爬蟲任務', '啟動', this._createIcon('start')));
        this.shadowRoot.appendChild(this._createButton('btn-pause-job', 'btn btn-secondary btn-sm', '暫停執行中的任務', '暫停', this._createIcon('pause')));
        this.shadowRoot.appendChild(this._createButton('btn-reset-job', 'btn btn-secondary btn-sm', '清除所有紀錄與外連結果，將任務退回初始狀態', '重置', this._createIcon('reset')));
        this.shadowRoot.appendChild(this._createButton('btn-retry-failed-job', 'btn btn-secondary btn-sm', '重試爬取失敗連結', '重試', this._createIcon('retry')));
        this.shadowRoot.appendChild(this._createButton('btn-delete-job', 'btn btn-danger btn-sm', '永久刪除此任務及其所有關聯資料', '刪除', this._createIcon('delete')));
    }

    /**
     * 依據當前的任務狀態（`_jobStatus`、`_jobIsRunning`）決定哪些按鈕可見，
     * 並動態調整「啟動」按鈕的標籤（暫停中 → 顯示「恢復」，其他 → 顯示「啟動」）。
     */
    updateView() {
        if (!this._jobStatus) return;

        // 先全部隱藏
        Object.values(this._buttons).forEach(btn => { btn.style.display = 'none'; });

        // 固定顯示：複製、移交、刪除
        this._buttons['btn-duplicate-job'].style.display = 'inline-flex';
        this._buttons['btn-transfer-job'].style.display = 'inline-flex';
        this._buttons['btn-delete-job'].style.display = 'inline-flex';

        // 比對：僅任務完成後顯示
        if (this._jobStatus === 'completed') {
            this._buttons['btn-goto-compare'].style.display = 'inline-flex';
        }

        if (this._jobIsRunning) {
            // 執行中：僅顯示暫停
            this._buttons['btn-pause-job'].style.display = 'inline-flex';
        } else {
            // 非執行中：依狀態決定啟動、重置、重試

            if (['pending', 'paused', 'error'].includes(this._jobStatus)) {
                this._buttons['btn-start-job'].style.display = 'inline-flex';
                // 暫停中 → 標籤改為「恢復」，其他 → 保持「啟動」
                this._buttons['btn-start-job'].lastChild.textContent =
                    this._jobStatus === 'paused' ? '恢復' : '啟動';
            }

            if (this._jobStatus === 'completed') {
                this._buttons['btn-retry-failed-job'].style.display = 'inline-flex';
            }

            if (['completed', 'error', 'paused'].includes(this._jobStatus)) {
                this._buttons['btn-reset-job'].style.display = 'inline-flex';
            }
        }
    }

    /**
     * 綁定各按鈕的點擊事件，分別對外派送對應的自訂事件。
     *
     * @fires job-start
     * @fires job-pause
     * @fires job-reset
     * @fires job-retry
     * @fires job-delete
     * @fires job-duplicate
     * @fires job-compare
     * @fires job-transfer
     */
    setupEventListeners() {
        const dispatch = (eventName) =>
            this.dispatchEvent(new CustomEvent(eventName, { bubbles: true, composed: true }));

        this._buttons['btn-start-job'].addEventListener('click', () => dispatch('job-start'));
        this._buttons['btn-pause-job'].addEventListener('click', () => dispatch('job-pause'));
        this._buttons['btn-reset-job'].addEventListener('click', () => dispatch('job-reset'));
        this._buttons['btn-retry-failed-job'].addEventListener('click', () => dispatch('job-retry'));
        this._buttons['btn-delete-job'].addEventListener('click', () => dispatch('job-delete'));
        this._buttons['btn-duplicate-job'].addEventListener('click', () => dispatch('job-duplicate'));
        this._buttons['btn-goto-compare'].addEventListener('click', () => dispatch('job-compare'));
        this._buttons['btn-transfer-job'].addEventListener('click', () => dispatch('job-transfer'));
    }

    /**
     * 移除事件監聽器。
     * 由於事件均掛載於 Shadow DOM 的子節點上，當元件從 DOM 移除時
     * 瀏覽器會自動回收，此處無需手動解除。
     */
    teardownEventListeners() { }
}

customElements.define('job-controls', JobControls);
