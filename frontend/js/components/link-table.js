/**
 * link-table.js
 * 封裝資料表格，包含分頁、排序標頭與欄位篩選渲染邏輯
 */

/**
 * 通用資料表格元件 (Web Component)
 * 負責渲染分頁式資料表格，支援欄位排序（點擊標頭）與欄位篩選（輸入框）功能。
 *
 * @extends HTMLElement
 *
 * @fires sort-change   - 點擊可排序欄位標頭時觸發，detail: `{ key: string, asc: boolean }`
 * @fires filter-change - 欄位篩選輸入框內容變更時觸發，detail: `{ key: string, value: string }`
 * @fires page-change   - 點擊分頁按鈕時觸發，detail: `{ page: number }`
 *
 * @example
 * <link-table></link-table>
 * // 透過 JS 注入設定：
 * document.querySelector('link-table').config = { headers, data, sort, colFilters, pagination, loading };
 */
export class LinkDataTable extends HTMLElement {
    /**
     * 建立 LinkDataTable 元件實例，初始化私有狀態與 DOM 快取參考。
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });

        /** @type {Array<Object>} @private */
        this._headers = [];
        /** @type {Array<Object>} @private */
        this._data = [];
        /** @type {{ key: string|null, asc: boolean }} @private */
        this._sort = { key: null, asc: true };
        /** @type {Object<string, string>} @private */
        this._colFilters = {};
        /** @type {{ current: number, total: number }} @private */
        this._pagination = { current: 1, total: 1 };
        /**
         * 是否顯示分頁載入中的遮罩
         * @type {boolean}
         * @private
         */
        this._loading = false;

        /**
         * 是否開啟多選 (Checkbox) 欄位
         * @type {boolean}
         * @private
         */
        this._selectable = false;

        /**
         * 作為選項識別碼的資料屬性名稱，預設為 'url', 'URL', 或 'domain' (向下相容)
         * @type {string|null}
         * @private
         */
        this._rowKey = null;

        /**
         * 存放目前已選取的 row key 集合
         * @type {Set<string>}
         * @private
         */
        this._selectedKeys = new Set();

        /**
         * 是否開啟整列點擊事件 (row-click)
         * @type {boolean}
         * @private
         */
        this._rowClickable = false;

        // DOM 快取（在 render() 後初始化）
        /** @type {HTMLTableSectionElement|null} @private */ this._tableHeadEl = null;
        /** @type {HTMLTableSectionElement|null} @private */ this._tableBodyEl = null;
        /** @type {HTMLElement|null}             @private */ this._paginationEl = null;
        /** @type {HTMLElement|null}             @private */ this._loadingOverlayEl = null;
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
     * 接收並套用表格設定，觸發畫面重繪。
     * 傳入 null 或 undefined 時直接返回，不做任何操作。
     * @param {Object}         [config.headers]    - 欄位定義陣列
     * @param {Array<Object>}  [config.data]       - 表格資料陣列
     * @param {Object}         [config.sort]       - 排序狀態物件 `{ key: string, asc: boolean }`
     * @param {Object}         [config.colFilters] - 欄位篩選物件 `{ key: value }`
     * @param {Object}         [config.pagination] - 分頁資訊物件 `{ current: 1, total: 1 }`
     * @param {boolean}        [config.loading]    - 是否顯示載入中遮罩
     * @param {boolean}        [config.selectable] - 是否開啟第一欄的 Checkbox 選取功能
     * @param {string}         [config.rowKey]     - 用來識別選取列的唯一鍵值屬性名（未設定則依序找 'url', 'URL', 'domain'）
     * @param {boolean}        [config.rowClickable] - 是否整列可點擊並觸發事件
     */
    set config(config) {
        if (!config) return;
        this._headers = config.headers || this._headers;
        this._data = config.data || [];
        this._sort = config.sort || { key: null, asc: true };
        this._colFilters = config.colFilters || {};
        this._pagination = config.pagination || { current: 1, total: 1 };
        this._loading = config.loading || false;
        
        if (config.selectable !== undefined) {
            this._selectable = config.selectable;
        }
        if (config.rowKey !== undefined) {
            this._rowKey = config.rowKey;
        }
        if (config.rowClickable !== undefined) {
            this._rowClickable = config.rowClickable;
        }
        // 如果資料更新（例如換頁），我們選擇保留勾選狀態，讓使用者可跨頁勾選
        // 若外部需清空，可傳遞選取的 keys 或由外部重新實例化
        
        this.updateView();
    }

    /**
     * 渲染元件的 HTML 結構與 Shadow DOM 樣式。
     * 同時將需要動態更新的 DOM 節點快取為 instance 私有變數，
     * 避免 updateView() 及子渲染方法重複查詢 Shadow DOM。
     */
    render() {
        const linkBaseEl = document.createElement('link');
        linkBaseEl.rel = 'stylesheet';
        linkBaseEl.href = '/static/css/base.css';
        this.shadowRoot.appendChild(linkBaseEl);

        const styleEl = document.createElement('style');
        styleEl.textContent = `
            :host { display: block; position: relative; }
            .table-container {
                overflow-x: auto;
                position: relative;
                min-height: 200px;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                font-size: 0.875rem;
                text-align: left;
            }
            th {
                background: var(--surface-raised);
                padding: 0.75rem 1rem;
                border-bottom: 2px solid var(--surface-border);
                font-weight: 600;
                color: var(--text-secondary);
                white-space: nowrap;
                user-select: none;
            }
            th.sortable { 
                cursor: pointer; 
                transition: 
                background 0.15s ease; 
            }
            th.sortable:hover { 
                background: var(--color-neutral-700); 
            }
            td {
                padding: 0.75rem 1rem;
                border-bottom: 1px solid var(--surface-border);
                color: var(--text-primary);
                vertical-align: top;
            }
            tr:hover td { 
                background: var(--surface-raised); 
            }
            .th-header { 
                display: flex; 
                align-items: center; 
                gap: 4px;
                justify-content: space-between;
            }
            .sort-icon { 
                display: inline-block; 
                margin-left: 0.25rem; 
                font-size: 0.75rem; 
                color: var(--text-muted); 
            }
            /* 欄位篩選輸入框（替代 form-input，避免引入 components.css 依賴） */
            .col-filter {
                margin-top: 0.5rem;
                padding: 0.25rem 0.5rem;
                width: 100%;
                box-sizing: border-box;
                font-size: var(--text-xs);
                font-weight: normal;
                background: var(--surface-overlay);
                border: 1px solid var(--surface-border);
                border-radius: var(--radius-sm);
                color: var(--text-primary);
                outline: none;
                appearance: none;
                transition: border-color var(--transition-fast);
            }
            .col-filter:focus { 
                border-color: var(--color-brand-500); 
            }
            .col-filter::placeholder { 
                color: var(--text-muted); 
            }
            /* Pagination */
            .pagination {
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 1rem;
                gap: 0.5rem;
                border-top: 1px solid var(--surface-border);
                background: var(--surface-base);
            }
            .page-info { 
                font-size: 0.875rem; 
                color: var(--text-secondary); 
                margin: 0 0.5rem; 
            }
            .loading-overlay {
                position: absolute;
                top: 0; left: 0; right: 0; bottom: 0;
                background: hsla(222, 47%, 5%, 0.85);
                display: flex;
                justify-content: center;
                align-items: center;
                z-index: 10;
                visibility: hidden;
                opacity: 0;
                transition: opacity 0.2s ease;
            }
            .loading-overlay.active {
                visibility: visible;
                opacity: 1;
            }
            .spinner {
                width: 2rem; height: 2rem;
                border: 3px solid var(--surface-border);
                border-top-color: var(--color-brand-500);
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }
            @keyframes spin { to { transform: rotate(360deg); } }
            .empty-state {
                padding: 3rem;
                text-align: center;
                color: var(--text-muted);
            }
        `;
        this.shadowRoot.appendChild(styleEl);

        const containerEl = document.createElement('div');
        containerEl.className = 'table-container';

        const tableEl = document.createElement('table');
        this._tableHeadEl = document.createElement('thead');
        this._tableBodyEl = document.createElement('tbody');

        tableEl.appendChild(this._tableHeadEl);
        tableEl.appendChild(this._tableBodyEl);
        containerEl.appendChild(tableEl);

        this._loadingOverlayEl = document.createElement('div');
        this._loadingOverlayEl.className = 'loading-overlay';
        const spinnerEl = document.createElement('div');
        spinnerEl.className = 'spinner';
        this._loadingOverlayEl.appendChild(spinnerEl);
        containerEl.appendChild(this._loadingOverlayEl);

        this.shadowRoot.appendChild(containerEl);

        this._paginationEl = document.createElement('div');
        this._paginationEl.className = 'pagination';
        this.shadowRoot.appendChild(this._paginationEl);
    }

    /**
     * 依據當前狀態更新畫面：載入遮罩、表頭、表格內容、分頁列。
     */
    updateView() {
        this._loadingOverlayEl.classList.toggle('active', this._loading);
        this._renderHeaders();
        this._renderBody();
        this._renderPagination();
    }

    /**
     * 重新渲染表格標頭列，包含排序圖示與欄位篩選輸入框。
     * @private
     */
    _renderHeaders() {
        this._tableHeadEl.replaceChildren();

        const trEl = document.createElement('tr');

        // 如果開啟選取功能，加入表頭 Checkbox
        if (this._selectable) {
            const thCb = document.createElement('th');
            thCb.style.width = '40px';
            thCb.style.textAlign = 'center';
            
            const cbAll = document.createElement('input');
            cbAll.type = 'checkbox';
            cbAll.style.cursor = 'pointer';
            
            // 計算目前頁面所有有效的 key
            const pageKeys = this._data.map(row => this._getRowKey(row)).filter(k => k !== undefined);
            
            if (pageKeys.length > 0) {
                const allSelected = pageKeys.every(k => this._selectedKeys.has(k));
                const someSelected = pageKeys.some(k => this._selectedKeys.has(k));
                cbAll.checked = allSelected;
                cbAll.indeterminate = someSelected && !allSelected;
            }
            
            cbAll.addEventListener('change', (e) => {
                const isChecked = e.target.checked;
                pageKeys.forEach(k => {
                    if (isChecked) this._selectedKeys.add(k);
                    else this._selectedKeys.delete(k);
                });
                this._dispatchSelectionChange();
                this.updateView(); // 重新渲染更新勾選狀態
            });
            
            thCb.appendChild(cbAll);
            trEl.appendChild(thCb);
        }

        this._headers.forEach(col => {
            const thEl = document.createElement('th');

            const headerTopEl = document.createElement('div');
            headerTopEl.className = 'th-header';
            headerTopEl.textContent = col.label;

            if (col.sortable && col.key) {
                thEl.classList.add('sortable');
                thEl.dataset.key = col.key;

                const sortIconEl = document.createElement('span');
                sortIconEl.className = 'sort-icon';

                if (this._sort.key === col.key) {
                    sortIconEl.textContent = this._sort.asc ? '▲' : '▼';
                    sortIconEl.style.color = 'var(--text-primary)';
                } else {
                    sortIconEl.textContent = '⇅';
                }
                headerTopEl.appendChild(sortIconEl);

                thEl.addEventListener('click', (e) => {
                    // 點擊篩選輸入框時不觸發排序
                    if (e.target.tagName === 'INPUT') return;
                    const newAsc = this._sort.key === col.key ? !this._sort.asc : true;
                    this.dispatchEvent(new CustomEvent('sort-change', {
                        detail: { key: col.key, asc: newAsc },
                        bubbles: true,
                        composed: true,
                    }));
                });
            }

            thEl.appendChild(headerTopEl);

            if (col.filterable !== false && col.key && !['_select', 'targets', 'source_urls', 'unique_urls'].includes(col.key)) {
                const filterInputEl = document.createElement('input');
                filterInputEl.type = 'text';
                filterInputEl.className = 'col-filter';
                filterInputEl.placeholder = '篩選...';
                filterInputEl.value = this._colFilters[col.key] || '';

                filterInputEl.addEventListener('input', (e) => {
                    this.dispatchEvent(new CustomEvent('filter-change', {
                        detail: { key: col.key, value: e.target.value.toLowerCase() },
                        bubbles: true,
                        composed: true,
                    }));
                });
                filterInputEl.addEventListener('click', e => e.stopPropagation());
                thEl.appendChild(filterInputEl);
            }

            if (col.width) thEl.style.width = col.width;
            if (col.align) thEl.style.textAlign = col.align;

            trEl.appendChild(thEl);
        });

        this._tableHeadEl.appendChild(trEl);
    }

    /**
     * 重新渲染表格資料列。
     * 若資料為空，顯示「暫無資料」的佔位列。
     * 各欄位可透過 `col.render(value, row)` 自訂 DOM 渲染函式，回傳值必須為 `Node`。
     * @private
     */
    _renderBody() {
        this._tableBodyEl.replaceChildren();

        if (this._data.length === 0) {
            const trEl = document.createElement('tr');
            const tdEl = document.createElement('td');
            tdEl.colSpan = this._headers.length || 1;
            tdEl.className = 'empty-state';
            tdEl.textContent = '暫無資料';
            trEl.appendChild(tdEl);
            this._tableBodyEl.appendChild(trEl);
            return;
        }

        this._data.forEach(row => {
            const trEl = document.createElement('tr');
            
            if (this._rowClickable) {
                trEl.style.cursor = 'pointer';
                trEl.addEventListener('click', (e) => {
                    // 如果點擊的是按鈕或其子元素，或者輸入框等，不觸發 row-click
                    if (e.target.closest('button, a, input, select, textarea, .job-actions')) return;
                    this.dispatchEvent(new CustomEvent('row-click', {
                        detail: row,
                        bubbles: true,
                        composed: true
                    }));
                });
            }

            const rKey = this._getRowKey(row);

            // 如果開啟選取功能，加入該列的 Checkbox
            if (this._selectable) {
                const tdCb = document.createElement('td');
                tdCb.style.textAlign = 'center';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.style.cursor = 'pointer';
                if (rKey !== undefined) {
                    cb.checked = this._selectedKeys.has(rKey);
                    cb.addEventListener('change', (e) => {
                        if (e.target.checked) this._selectedKeys.add(rKey);
                        else this._selectedKeys.delete(rKey);
                        this._dispatchSelectionChange();
                        this._renderHeaders(); // 僅更新表頭的 checkbox 狀態，避免重新渲染整個 body
                    });
                } else {
                    cb.disabled = true;
                }
                tdCb.appendChild(cb);
                trEl.appendChild(tdCb);
            }

            this._headers.forEach(col => {
                const tdEl = document.createElement('td');
                if (col.align) tdEl.style.textAlign = col.align;
                if (col.truncate) {
                    tdEl.classList.add('truncate');
                    tdEl.style.maxWidth = typeof col.truncate === 'string' ? col.truncate : '300px';
                }
                if (col.className) {
                    tdEl.className = tdEl.className ? `${tdEl.className} ${col.className}` : col.className;
                }

                if (col.render) {
                    // render 函式必須回傳 Node（遵守禁用 innerHTML 規範）
                    const node = col.render(row[col.key], row);
                    if (node instanceof Node) {
                        tdEl.appendChild(node);
                    } else {
                        tdEl.textContent = String(node); // 防呆 fallback
                    }
                } else {
                    tdEl.textContent = row[col.key] !== undefined ? row[col.key] : '-';
                }

                trEl.appendChild(tdEl);
            });

            this._tableBodyEl.appendChild(trEl);
        });
    }

    /**
     * 重新渲染分頁列。
     * 若總頁數 ≤ 1 則隱藏分頁列；否則顯示「上一頁」、頁碼資訊與「下一頁」。
     * @private
     */
    _renderPagination() {
        this._paginationEl.replaceChildren();

        const { current, total } = this._pagination;
        if (total <= 1) {
            this._paginationEl.style.display = 'none';
            return;
        }
        this._paginationEl.style.display = 'flex';

        const btnPrevEl = document.createElement('button');
        btnPrevEl.className = 'btn btn-secondary';
        btnPrevEl.textContent = '上一頁';
        btnPrevEl.disabled = current <= 1;
        btnPrevEl.addEventListener('click', () => {
            if (current > 1) this._dispatchPageChange(current - 1);
        });

        const infoEl = document.createElement('div');
        infoEl.className = 'page-info';
        infoEl.textContent = `第 ${current} 頁 / 共 ${total} 頁`;

        const btnNextEl = document.createElement('button');
        btnNextEl.className = 'btn btn-secondary';
        btnNextEl.textContent = '下一頁';
        btnNextEl.disabled = current >= total;
        btnNextEl.addEventListener('click', () => {
            if (current < total) this._dispatchPageChange(current + 1);
        });

        this._paginationEl.appendChild(btnPrevEl);
        this._paginationEl.appendChild(infoEl);
        this._paginationEl.appendChild(btnNextEl);
    }

    /**
     * 派送 `page-change` 自訂事件，通知外部切換至指定頁碼。
     * @param {number} page - 欲切換至的頁碼
     * @fires page-change
     * @private
     */
    _dispatchPageChange(page) {
        this.dispatchEvent(new CustomEvent('page-change', {
            detail: { page },
            bubbles: true,
            composed: true,
        }));
    }

    /**
     * 從 row 取出對應的唯一鍵值 (用於 selection)
     * @param {Object} row 
     * @returns {string|undefined}
     * @private
     */
    _getRowKey(row) {
        if (this._rowKey) return row[this._rowKey];
        return row['url'] || row['URL'] || row['domain'] || row['target_url'];
    }

    /**
     * 派送 `selection-change` 自訂事件，通知外部選取狀態變更。
     * @fires selection-change
     * @private
     */
    _dispatchSelectionChange() {
        this.dispatchEvent(new CustomEvent('selection-change', {
            detail: { selectedKeys: Array.from(this._selectedKeys) },
            bubbles: true,
            composed: true,
        }));
    }

    /**
     * 綁定元件事件監聽器。
     * 目前所有事件均在 _renderHeaders() 與 _renderPagination() 中動態綁定，此處無需額外處理。
     */
    setupEventListeners() { }

    /**
     * 移除事件監聽器。
     * 由於事件均掛載於 Shadow DOM 的子節點上，當元件從 DOM 移除時
     * 瀏覽器會自動回收，此處無需手動解除。
     */
    teardownEventListeners() { }
}

customElements.define('link-table', LinkDataTable);
