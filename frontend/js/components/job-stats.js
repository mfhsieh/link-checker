/**
 * job-stats.js
 * 封裝外部連結與內部連結的狀態篩選統計卡片 Web Component
 */

/**
 * 任務統計狀態卡片元件 (Web Component)
 * 負責渲染任務執行結果的統計數據，並提供點擊卡片進行篩選的功能。
 *
 * @extends HTMLElement
 */
export class JobStats extends HTMLElement {
    /**
     * 建立 JobStats 元件實例
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });

        /**
         * @type {Object<string, HTMLElement>} 儲存各狀態卡片數字 DOM 節點的對照表
         */
        this.statValues = {};

        /**
         * @type {Object<string, HTMLElement>} 儲存各狀態卡片整體 DOM 節點的對照表
         */
        this.statCards = {};

        /**
         * @type {string} 目前啟用的篩選條件 ID，預設為 'all'
         * @private
         */
        this._currentFilter = 'all';
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
     * 接收並更新外部或內部連結的摘要統計資料
     * @param {Object} stats - 從 API 取得的摘要統計資料物件
     */
    set stats(stats) {
        if (!stats) return;
        this.updateView(stats);
    }

    /**
     * 設定當前被選取的過濾器 (Filter)
     * @param {string} filterName - 欲啟用的篩選器 ID (例如 'all', 'dead', 'server_error')
     */
    set activeFilter(filterName) {
        this._currentFilter = filterName;
        Object.keys(this.statCards).forEach(key => {
            if (key === filterName) {
                this.statCards[key].classList.add('active');
            } else {
                this.statCards[key].classList.remove('active');
            }
        });
    }

    /**
     * 動態建立個別統計卡片的 DOM 結構
     * @param {string} filterId - 篩選器 ID，用以識別此卡片代表的狀態
     * @param {string} labelText - 卡片顯示的標題文字
     * @param {string} theme - 卡片的主題顏色 (如 'brand', 'success', 'warning', 'danger', 'info', 'muted')
     * @param {string} bottomDesc - 卡片下方顯示的簡短描述
     * @param {string} clickedDesc - 點擊卡片後，顯示在說明區塊的詳細描述
     * @returns {HTMLDivElement} 建立完成的統計卡片 DOM 元素
     */
    createStatCard(filterId, labelText, theme, bottomDesc, clickedDesc) {
        const themeClass = theme ? `text-${theme}` : '';

        const card = document.createElement('div');
        card.className = 'stat-card filter-card interactive';
        card.dataset.filter = filterId;
        card.dataset.desc = clickedDesc;
        card.dataset.theme = theme || 'brand';

        const label = document.createElement('div');
        label.className = `stat-label ${themeClass}`.trim();
        label.textContent = labelText;

        const value = document.createElement('div');
        value.className = `stat-value ${themeClass}`.trim();
        value.id = `summary-${filterId}`;
        value.textContent = '0';

        const descText = document.createElement('div');
        descText.className = 'stat-desc';

        descText.textContent = bottomDesc;

        card.appendChild(label);
        card.appendChild(value);
        card.appendChild(descText);

        this.statCards[filterId] = card;
        this.statValues[filterId] = value;

        return card;
    }

    /**
     * 渲染元件整體的 HTML 結構與樣式 (CSS)
     * 依據 `type` 屬性決定產生內部連結 (internal) 或外部連結 (external) 專屬的卡片
     */
    render() {
        const linkBase = document.createElement('link');
        linkBase.rel = 'stylesheet';
        linkBase.href = '/static/css/base.css';
        this.shadowRoot.appendChild(linkBase);

        const style = document.createElement('style');
        style.textContent = `
            :host { display: block; margin-bottom: 0.75rem; }
            .desc-box {
                margin-bottom: 1.5rem;
                padding: 0.625rem 0.875rem;
                background: var(--surface-raised);
                border-radius: var(--radius-md);
                border-left: 3px solid var(--color-brand-400);
                display: flex;
                align-items: center;
                gap: 0.5rem;
                transition: border-color var(--transition-base);
                font-size: 0.875rem;
                color: var(--text-muted);
            }
        `;
        this.shadowRoot.appendChild(style);

        const grid = document.createElement('div');
        grid.className = 'grid-stats';

        this.isInternal = this.getAttribute('type') === 'internal';

        if (this.isInternal) {
            grid.appendChild(this.createStatCard('all', '診斷總數', 'brand', '包含失敗與截斷的總數量', '此任務在您的網站內部爬行時，遭遇的所有異常、警告與抓取失敗事件。'));
            grid.appendChild(this.createStatCard('server_error', '伺服器異常', 'danger', '伺服器無法完成請求', '目標伺服器發生崩潰或過載 (回傳 5XX 狀態碼)，若非防禦機制或停機維護，則為嚴重的系統異常，需請工程師立刻處理。'));
            grid.appendChild(this.createStatCard('connection_error', '底層異常', 'danger', 'DNS、憑證或連線有問題', 'DNS 解析失敗、SSL 憑證異常或連線被目標主機拒絕。這通常代表基礎網路設施或防火牆設定有誤。'));
            grid.appendChild(this.createStatCard('not_found', '資源遺失', 'danger', '資源請求失敗或已刪除', '目標伺服器運作正常，但找不到對應的資源 (404) 或該資源已刪除 (410)。通常是因為網址打錯或資源已被刪除，需編輯修正。'));
            grid.appendChild(this.createStatCard('timeout', '連線逾時', 'warning', '伺服器無法於時限內回復', '伺服器未能在指定的時間內回應。這通常代表伺服器效能瓶頸或網路嚴重壅塞。'));
            grid.appendChild(this.createStatCard('warning', '網頁截斷', 'warning', '網頁容量過大被提早截斷', '網頁超過系統設定的最大下載上限，已被提早截斷。該網頁可能遺漏部分未被解析的外部連結。'));
            grid.appendChild(this.createStatCard('other_error', '其他異常', 'warning', '未預期的例外錯誤', '其他未歸類的 HTTP 異常狀況 (例如：請求錯誤 400)。'));
            grid.appendChild(this.createStatCard('blocked', '權限阻擋', 'muted', '未獲授權或遭封鎖', '未獲授權、拒絕存取、不允許的請求、不接受的請求、請求過多等狀態碼 (401, 403, 405, 406, 429)。這多數是正常的防禦行為，而非連結失效。'));
            grid.appendChild(this.createStatCard('insecure', '非 HTTPS', 'info', '使用明文 HTTP 傳輸', '連結仍使用未加密的 HTTP 協定進行傳輸，容易遭到中間人監聽或劫持，建議將其升級為 HTTPS。'));
        } else {
            grid.appendChild(this.createStatCard('all', '診斷總數', 'brand', '不重複的外部連結總數量', '此任務探索到的所有不重複外部連結總數，包含正常與失效的連結。'));
            grid.appendChild(this.createStatCard('healthy', '正常連結', 'success', '成功連線且回應正常', '外部目標主機可正常解析，且回傳 2XX 或 3XX 狀態碼，代表連結可正常存取。'));
            grid.appendChild(this.createStatCard('dead', 'DNS 錯誤', 'danger', 'DNS 解析失敗', '找不到主機網域的 IP。可能是網址誤植或網域廢棄；也有可能是高風險的無主網域，會遭他人惡意註冊。建議儘速修正或移除該失效連結。'));
            grid.appendChild(this.createStatCard('not_found', '資源遺失', 'danger', '資源請求失敗或已刪除', '目標伺服器運作正常，但找不到對應的資源 (404) 或該資源已刪除 (410)。建議確認非因網站防禦機制後，修正或移除該失效連結。'));
            grid.appendChild(this.createStatCard('server_error', '伺服器異常', 'warning', '伺服器無法完成請求', '伺服器錯誤 (回傳 5XX 狀態碼)。這通常是暫時性異常，或對方設定了嚴格的防禦機制。可過幾日後再次檢驗。'));
            grid.appendChild(this.createStatCard('connection_error', '底層異常', 'warning', '憑證或連線有問題', '連線逾時、SSL 憑證異常或連線被目標主機拒絕。這通常代表底層網路異常，或對方設定了嚴格的防禦機制。'));
            grid.appendChild(this.createStatCard('other_error', '其他異常', 'warning', '未預期的例外錯誤', '其他未歸類的 HTTP 異常狀況 (例如：請求錯誤 400)。'));
            grid.appendChild(this.createStatCard('blocked', '權限阻擋', 'muted', '未獲授權或遭封鎖', '未獲授權、拒絕存取、不允許的請求、不接受的請求、請求過多等狀態碼 (401, 403, 405, 406, 429)。這多數是正常的防禦行為，而非連結失效。'));
            grid.appendChild(this.createStatCard('insecure', '非 HTTPS', 'info', '使用明文 HTTP 傳輸', '連結仍使用未加密的 HTTP 協定進行傳輸，容易遭到中間人監聽或劫持，建議將其升級為 HTTPS。'));
        }

        this.shadowRoot.appendChild(grid);

        // Description Box
        this.descBox = document.createElement('div');
        this.descBox.className = 'desc-box text-sm text-muted';

        const svgIcon = document.createElement('div');
        svgIcon.style.width = "16px";
        svgIcon.style.height = "16px";
        svgIcon.style.flexShrink = "0";
        svgIcon.style.backgroundColor = "currentColor";
        svgIcon.style.mask = "url(/static/image/info-circle.svg) no-repeat center / contain";
        svgIcon.style.webkitMask = "url(/static/image/info-circle.svg) no-repeat center / contain";

        this.descTextNode = document.createElement('span');
        this.descTextNode.textContent = this.statCards['all'].dataset.desc;

        this.descBox.appendChild(svgIcon);
        this.descBox.appendChild(this.descTextNode);

        this.shadowRoot.appendChild(this.descBox);

        // Initialize default active state
        this.activeFilter = 'all';
        this.updateActiveCardUI('all');
    }

    /**
     * 更新當前選中狀態卡片的 UI 樣式
     * @param {string} filterId - 欲啟用的狀態篩選器 ID
     */
    updateActiveCardUI(filterId) {
        this.shadowRoot.querySelectorAll('.filter-card').forEach(card => {
            const theme = card.dataset.theme;
            if (card.dataset.filter === filterId) {
                card.classList.add('active');
                if (theme) card.classList.add(`border-${theme}`);

                this.descBox.className = `desc-box text-${theme} border-${theme}`;
            } else {
                card.classList.remove('active');
                if (theme) card.classList.remove(`border-${theme}`);
            }
        });
    }

    /**
     * 根據傳入的統計資料更新各卡片上顯示的數字
     * @param {Object} stats - 各種狀態的數量統計物件
     */
    updateView(stats) {
        if (this.statValues['all']) this.statValues['all'].textContent = stats.total_external_links ?? stats.total ?? 0;
        if (!this.isInternal && this.statValues['healthy']) {
            this.statValues['healthy'].textContent = stats.healthy_count ?? stats.healthy ?? 0;
        }
        if (this.statValues['dead']) this.statValues['dead'].textContent = stats.dns_failed_count ?? stats.timeout ?? 0;
        if (this.statValues['not_found']) this.statValues['not_found'].textContent = stats.not_found_count ?? stats.not_found ?? 0;
        if (this.statValues['server_error']) this.statValues['server_error'].textContent = stats.server_error_count ?? stats.server_error ?? 0;
        if (this.statValues['connection_error']) this.statValues['connection_error'].textContent = stats.connection_error_count ?? stats.connection_error ?? 0;
        if (this.statValues['other_error']) this.statValues['other_error'].textContent = stats.other_error_count ?? stats.other_error ?? 0;
        if (this.statValues['blocked']) this.statValues['blocked'].textContent = stats.blocked_count ?? stats.blocked ?? 0;
        if (this.statValues['timeout']) this.statValues['timeout'].textContent = stats.timeout ?? 0;
        if (this.statValues['warning']) this.statValues['warning'].textContent = stats.warning ?? 0;
        if (this.statValues['insecure']) this.statValues['insecure'].textContent = stats.insecure_count ?? stats.insecure ?? 0;
    }

    /**
     * 綁定卡片的點擊事件，發送篩選變更的自訂事件
     */
    setupEventListeners() {
        Object.entries(this.statCards).forEach(([filterId, card]) => {
            card.addEventListener('click', () => {
                if (this._currentFilter === filterId && filterId !== 'all') {
                    // Toggle back to 'all'
                    this.activeFilter = 'all';
                    this.descTextNode.textContent = this.statCards['all'].dataset.desc;
                    this.updateActiveCardUI('all');
                    this.dispatchEvent(new CustomEvent('filter-change', {
                        detail: { filter: 'all' },
                        bubbles: true,
                        composed: true
                    }));
                } else {
                    this.activeFilter = filterId;
                    this.descTextNode.textContent = card.dataset.desc;
                    this.updateActiveCardUI(filterId);

                    this.dispatchEvent(new CustomEvent('filter-change', {
                        detail: { filter: filterId },
                        bubbles: true,
                        composed: true
                    }));
                }
            });
        });
    }

    /**
     * 移除事件監聽器（目前為空實作）
     */
    teardownEventListeners() { }
}

customElements.define('job-stats', JobStats);
