/**
 * job-stats.js
 * 封裝外部連結與內部連結的狀態篩選統計卡片 Web Component
 */

/**
 * 任務統計狀態卡片元件 (Web Component)
 * 負責渲染任務執行結果的統計數據，並提供點擊卡片進行篩選的功能。
 *
 * 透過 HTML `type` 屬性決定顯示模式：
 * - `type="internal"` → 內部連結診斷統計
 * - 其他（預設）→ 外部連結狀態統計
 *
 * @extends HTMLElement
 *
 * @fires filter-change - 使用者點擊卡片時觸發，detail: `{ filter: string }`
 *
 * @example
 * <job-stats type="external"></job-stats>
 * <job-stats type="internal"></job-stats>
 */
export class JobStats extends HTMLElement {
    /**
     * 建立 JobStats 元件實例，初始化私有狀態。
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });

        /**
         * 各狀態卡片數字 DOM 節點的對照表
         * @type {Object<string, HTMLElement>}
         * @private
         */
        this._statValues = {};

        /**
         * 各狀態卡片整體 DOM 節點的對照表
         * @type {Object<string, HTMLElement>}
         * @private
         */
        this._statCards = {};

        /**
         * 目前啟用的篩選條件 ID，預設為 'all'
         * @type {string}
         * @private
         */
        this._currentFilter = 'all';

        /**
         * 是否為內部連結診斷模式（由 `type` attribute 決定）
         * @type {boolean}
         * @private
         */
        this._isInternal = false;

        /**
         * 說明文字的容器元素（描述當前篩選條件）
         * @type {HTMLElement|null}
         * @private
         */
        this._descBox = null;

        /**
         * 說明文字的文字節點容器
         * @type {HTMLElement|null}
         * @private
         */
        this._descTextEl = null;
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
     * 接收並更新外部或內部連結的摘要統計資料。
     * @param {Object} stats - 從 API 取得的摘要統計資料物件
     */
    set stats(stats) {
        this.updateView(stats || null);
    }

    /**
     * 設定並啟用指定的篩選器，同步更新卡片 UI 與說明文字。
     * 此 setter 為公開 API，可由外部元件呼叫。
     * @param {string} filterId - 欲啟用的篩選器 ID (例如 'all', 'dead', 'server_error')
     */
    set activeFilter(filterId) {
        this._currentFilter = filterId;
        if (this._statCards[filterId] && this._descTextEl) {
            this._descTextEl.textContent = this._statCards[filterId].dataset.desc;
        }
        this._updateActiveCardUI(filterId);
    }

    /**
     * 動態建立個別統計卡片的 DOM 結構，並將其加入內部索引。
     * @param {string} filterId    - 篩選器 ID，用以識別此卡片代表的狀態
     * @param {string} labelText   - 卡片顯示的標題文字
     * @param {string} theme       - 卡片的主題顏色 ('brand'|'success'|'warning'|'danger'|'info'|'muted')
     * @param {string} bottomDesc  - 卡片下方顯示的簡短描述
     * @param {string} clickedDesc - 點擊卡片後，顯示在說明區塊的詳細描述
     * @returns {HTMLDivElement} 建立完成的統計卡片 DOM 元素
     * @private
     */
    _createStatCard(filterId, labelText, theme, bottomDesc, clickedDesc) {
        const themeClass = theme ? `text-${theme}` : '';

        const cardEl = document.createElement('div');
        cardEl.className = 'stat-card filter-card interactive';
        cardEl.dataset.filter = filterId;
        cardEl.dataset.desc = clickedDesc;
        cardEl.dataset.theme = theme || 'brand';

        const labelEl = document.createElement('div');
        labelEl.className = `stat-label ${themeClass}`.trim();
        labelEl.textContent = labelText;

        const valueEl = document.createElement('div');
        valueEl.className = `stat-value ${themeClass}`.trim();
        valueEl.id = `summary-${filterId}`;
        valueEl.textContent = '0';

        const descEl = document.createElement('div');
        descEl.className = 'stat-desc';
        descEl.textContent = bottomDesc;

        cardEl.appendChild(labelEl);
        cardEl.appendChild(valueEl);
        cardEl.appendChild(descEl);

        this._statCards[filterId] = cardEl;
        this._statValues[filterId] = valueEl;

        return cardEl;
    }

    /**
     * 渲染元件整體的 HTML 結構與樣式 (CSS)。
     * 依據 `type` attribute 決定產生內部連結 (`type="internal"`) 或外部連結（預設）專屬的卡片配置。
     */
    render() {
        const linkBaseEl = document.createElement('link');
        linkBaseEl.rel = 'stylesheet';
        linkBaseEl.href = '/static/css/base.css';
        this.shadowRoot.appendChild(linkBaseEl);

        const styleEl = document.createElement('style');
        styleEl.textContent = `
            :host { display: block; margin-bottom: 0.75rem; }
            .icon-info {
                width: 16px;
                height: 16px;
                mask: url(/static/image/icon-info.svg) no-repeat center / contain;
                -webkit-mask: url(/static/image/icon-info.svg) no-repeat center / contain;
            }
        `;
        this.shadowRoot.appendChild(styleEl);

        const gridEl = document.createElement('div');
        gridEl.className = 'grid-stats';

        this._isInternal = this.getAttribute('type') === 'internal';

        if (this._isInternal) {
            gridEl.appendChild(this._createStatCard('all', '診斷總數', 'brand', '包含失敗與截斷的總數量', '此任務在您的網站內部爬行時，遭遇的所有異常、警告與抓取失敗事件。'));
            gridEl.appendChild(this._createStatCard('server_error', '伺服器異常', 'danger', '伺服器無法完成請求', '目標伺服器發生崩潰或過載 (回傳 5XX 狀態碼)，若非防禦機制或停機維護，則為嚴重的系統異常，需請工程師立刻處理。'));
            gridEl.appendChild(this._createStatCard('connection_error', '底層異常', 'danger', 'DNS、憑證或連線有問題', 'DNS 解析失敗、SSL 憑證異常或連線被目標主機拒絕。這通常代表基礎網路設施或防火牆設定有誤。'));
            gridEl.appendChild(this._createStatCard('not_found', '資源遺失', 'danger', '資源請求失敗或已刪除', '目標伺服器運作正常，但找不到對應的資源 (404) 或該資源已刪除 (410)。通常是因為網址打錯或資源已被刪除，需編輯修正。'));
            gridEl.appendChild(this._createStatCard('timeout', '連線逾時', 'warning', '伺服器無法於時限內回復', '伺服器未能在指定的時間內回應。這通常代表伺服器效能瓶頸或網路嚴重壅塞。'));
            gridEl.appendChild(this._createStatCard('warning', '網頁截斷', 'warning', '網頁容量過大被提早截斷', '網頁超過系統設定的最大下載上限，已被提早截斷。該網頁可能遺漏部分未被解析的外部連結。'));
            gridEl.appendChild(this._createStatCard('other_error', '其他異常', 'warning', '未預期的例外錯誤', '其他未歸類的 HTTP 異常狀況 (例如：請求錯誤 400)。'));
            gridEl.appendChild(this._createStatCard('blocked', '權限阻擋', 'muted', '未獲授權或遭封鎖', '未獲授權、拒絕存取、不允許的請求、不接受的請求、請求過多等狀態碼 (401, 403, 405, 406, 429)。這多數是正常的防禦行為，而非連結失效。'));
            gridEl.appendChild(this._createStatCard('insecure', '非 HTTPS', 'info', '使用明文 HTTP 傳輸', '連結仍使用未加密的 HTTP 協定進行傳輸，容易遭到中間人監聽或劫持，建議將其升級為 HTTPS。'));
        } else {
            gridEl.appendChild(this._createStatCard('all', '診斷總數', 'brand', '不重複的外部連結總數量', '此任務探索到的所有不重複外部連結總數，包含正常與失效的連結。'));
            gridEl.appendChild(this._createStatCard('healthy', '正常連結', 'success', '成功連線且回應正常', '外部目標主機可正常解析，且回傳 2XX 或 3XX 狀態碼，代表連結可正常存取。'));
            gridEl.appendChild(this._createStatCard('dead', 'DNS 錯誤', 'danger', 'DNS 解析失敗', '找不到主機網域的 IP。可能是網址誤植或網域廢棄；也有可能是高風險的無主網域，會遭他人惡意註冊。建議儘速修正或移除該失效連結。'));
            gridEl.appendChild(this._createStatCard('not_found', '資源遺失', 'danger', '資源請求失敗或已刪除', '目標伺服器運作正常，但找不到對應的資源 (404) 或該資源已刪除 (410)。建議確認非因網站防禦機制後，修正或移除該失效連結。'));
            gridEl.appendChild(this._createStatCard('server_error', '伺服器異常', 'warning', '伺服器無法完成請求', '伺服器錯誤 (回傳 5XX 狀態碼)。這通常是暫時性異常，或對方設定了嚴格的防禦機制。可過幾日後再次檢驗。'));
            gridEl.appendChild(this._createStatCard('connection_error', '底層異常', 'warning', '憑證或連線有問題', '連線逾時、SSL 憑證異常或連線被目標主機拒絕。這通常代表底層網路異常、目標主機的憑證異常或防禦機制。'));
            gridEl.appendChild(this._createStatCard('other_error', '其他異常', 'warning', '未預期的例外錯誤', '其他未歸類的 HTTP 異常狀況 (例如：請求錯誤 400)。'));
            gridEl.appendChild(this._createStatCard('blocked', '權限阻擋', 'muted', '未獲授權或遭封鎖', '未獲授權、拒絕存取、不允許的請求、不接受的請求、請求過多等狀態碼 (401, 403, 405, 406, 429)。這多數是正常的防禦行為，而非連結失效。'));
            gridEl.appendChild(this._createStatCard('insecure', '非 HTTPS', 'info', '使用明文 HTTP 傳輸', '連結仍使用未加密的 HTTP 協定進行傳輸，容易遭到中間人監聽或劫持，建議將其升級為 HTTPS。'));
        }

        this.shadowRoot.appendChild(gridEl);

        // 說明文字區塊：顯示當前選中篩選條件的詳細描述
        this._descBox = document.createElement('div');
        this._descBox.className = 'desc-box text-sm';

        const descIconEl = document.createElement('div');
        descIconEl.className = 'mask-icon icon-info';

        this._descTextEl = document.createElement('span');
        this._descTextEl.textContent = this._statCards['all'].dataset.desc;

        this._descBox.appendChild(descIconEl);
        this._descBox.appendChild(this._descTextEl);

        this.shadowRoot.appendChild(this._descBox);

        // 初始化預設選中狀態
        this.activeFilter = 'all';
    }

    /**
     * 更新當前選中狀態卡片的視覺樣式（active class、主題邊框色、說明區塊顏色）。
     * 此為私有方法，應透過 `set activeFilter` 統一呼叫。
     * @param {string} filterId - 欲啟用的狀態篩選器 ID
     * @private
     */
    _updateActiveCardUI(filterId) {
        Object.values(this._statCards).forEach(card => {
            const theme = card.dataset.theme;
            if (card.dataset.filter === filterId) {
                card.classList.add('active');
                if (theme) {
                    card.classList.add(`border-${theme}`);
                    this._descBox.style.setProperty('--desc-theme', `var(--color-${theme}-400)`);
                }
            } else {
                card.classList.remove('active');
                if (theme) card.classList.remove(`border-${theme}`);
            }
        });
    }

    /**
     * 根據傳入的統計資料更新各卡片上顯示的數字。
     * 各欄位名稱使用雙重 fallback（`xxx_count` → `xxx`）以相容不同版本的 API 回應格式。
     * @param {Object} stats - 各種狀態的數量統計物件
     * @param {number} [stats.total_external_links]   - 外部連結總數
     * @param {number} [stats.total]                  - 診斷總數（內部連結模式）
     * @param {number} [stats.healthy_count]          - 正常連結數（外部模式專用）
     * @param {number} [stats.dns_failed_count]       - DNS 錯誤數
     * @param {number} [stats.not_found_count]        - 資源遺失數
     * @param {number} [stats.server_error_count]     - 伺服器異常數
     * @param {number} [stats.connection_error_count] - 底層連線異常數
     * @param {number} [stats.other_error_count]      - 其他異常數
     * @param {number} [stats.blocked_count]          - 權限阻擋數
     * @param {number} [stats.insecure_count]         - 非 HTTPS 數
     * @param {number} [stats.timeout]                - 連線逾時數（內部模式專用）
     * @param {number} [stats.warning]                - 網頁截斷數（內部模式專用）
     */
    updateView(stats) {
        const s = stats || {};
        if (this._statValues['all']) this._statValues['all'].textContent = s.total_external_links ?? s.total ?? 0;
        if (!this._isInternal && this._statValues['healthy']) this._statValues['healthy'].textContent = s.healthy_count ?? s.healthy ?? 0;
        if (this._statValues['dead']) this._statValues['dead'].textContent = s.dns_failed_count ?? s.dns_failed ?? 0;
        if (this._statValues['not_found']) this._statValues['not_found'].textContent = s.not_found_count ?? s.not_found ?? 0;
        if (this._statValues['server_error']) this._statValues['server_error'].textContent = s.server_error_count ?? s.server_error ?? 0;
        if (this._statValues['connection_error']) this._statValues['connection_error'].textContent = s.connection_error_count ?? s.connection_error ?? 0;
        if (this._statValues['other_error']) this._statValues['other_error'].textContent = s.other_error_count ?? s.other_error ?? 0;
        if (this._statValues['blocked']) this._statValues['blocked'].textContent = s.blocked_count ?? s.blocked ?? 0;
        if (this._statValues['timeout']) this._statValues['timeout'].textContent = s.timeout ?? 0;
        if (this._statValues['warning']) this._statValues['warning'].textContent = s.warning ?? 0;
        if (this._statValues['insecure']) this._statValues['insecure'].textContent = s.insecure_count ?? s.insecure ?? 0;
    }

    /**
     * 綁定卡片的點擊事件。
     * 點擊已選中的卡片時不做任何動作；
     * 點擊其他卡片則啟用對應的篩選器，並對外派送 `filter-change` 自訂事件。
     */
    setupEventListeners() {
        Object.entries(this._statCards).forEach(([filterId, card]) => {
            card.addEventListener('click', () => {
                // 點擊已選中的卡片 → 忽略
                if (this._currentFilter === filterId) return;
                this.activeFilter = filterId;
                this.dispatchEvent(new CustomEvent('filter-change', {
                    detail: { filter: filterId },
                    bubbles: true,
                    composed: true,
                }));
            });
        });
    }

    /**
     * 移除事件監聽器。
     * 由於事件均掛載於 Shadow DOM 的子節點上，當元件從 DOM 移除時
     * 瀏覽器會自動回收，此處無需手動解除。
     */
    teardownEventListeners() { }
}

customElements.define('job-stats', JobStats);
