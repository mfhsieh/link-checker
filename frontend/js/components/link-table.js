/**
 * link-table.js
 * 封裝資料表格，包含分頁、排序標頭與渲染邏輯 (嚴格禁止 innerHTML)
 */

export class LinkDataTable extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        
        this._headers = [];
        this._data = [];
        this._sort = { key: null, asc: true };
        this._colFilters = {};
        this._pagination = { current: 1, total: 1 };
        
        this._loading = false;
        
        // Element references
        this.tableHead = null;
        this.tableBody = null;
        this.paginationContainer = null;
        this.loadingOverlay = null;
    }

    connectedCallback() {
        this.render();
        this.setupEventListeners();
    }

    disconnectedCallback() {
        this.teardownEventListeners();
    }

    set config(cfg) {
        if (cfg.headers) this._headers = cfg.headers;
        if (cfg.data) this._data = cfg.data;
        if (cfg.sort) this._sort = cfg.sort;
        if (cfg.colFilters) this._colFilters = cfg.colFilters;
        if (cfg.pagination) this._pagination = cfg.pagination;
        if (typeof cfg.loading === 'boolean') this._loading = cfg.loading;
        
        this.updateView();
    }

    render() {
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
            .truncate {
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            th {
                background: var(--surface-raised);
                padding: 0.75rem 1rem;
                border-bottom: 2px solid var(--border-color);
                font-weight: 600;
                color: var(--text-secondary);
                white-space: nowrap;
                user-select: none;
            }
            th.sortable { cursor: pointer; transition: background 0.15s ease; }
            th.sortable:hover { background: var(--surface-elevated); }
            td {
                padding: 0.75rem 1rem;
                border-bottom: 1px solid var(--border-color);
                color: var(--text-primary);
                vertical-align: top;
            }
            tr:hover td { background: var(--surface-raised); }
            
            .sort-icon { display: inline-block; margin-left: 0.25rem; font-size: 0.75rem; color: var(--text-muted); }
            
            /* Pagination */
            .pagination {
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 1rem;
                gap: 0.5rem;
                border-top: 1px solid var(--border-color);
                background: var(--surface-color);
            }
            .page-btn {
                padding: 0.25rem 0.75rem;
                border: 1px solid var(--border-color);
                background: var(--surface-raised);
                border-radius: var(--radius-sm);
                cursor: pointer;
                transition: all 0.15s ease;
            }
            .page-btn:hover:not(:disabled) {
                background: var(--surface-elevated);
                border-color: var(--color-brand-400);
            }
            .page-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .page-info { font-size: 0.875rem; color: var(--text-secondary); margin: 0 0.5rem; }
            
            .loading-overlay {
                position: absolute;
                top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(var(--surface-color-rgb, 255, 255, 255), 0.7);
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
                border: 3px solid var(--border-color);
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
        this.shadowRoot.appendChild(style);

        const container = document.createElement('div');
        container.className = 'table-container';

        const table = document.createElement('table');
        this.tableHead = document.createElement('thead');
        this.tableBody = document.createElement('tbody');
        
        table.appendChild(this.tableHead);
        table.appendChild(this.tableBody);
        container.appendChild(table);

        this.loadingOverlay = document.createElement('div');
        this.loadingOverlay.className = 'loading-overlay';
        const spinner = document.createElement('div');
        spinner.className = 'spinner';
        this.loadingOverlay.appendChild(spinner);
        container.appendChild(this.loadingOverlay);

        this.shadowRoot.appendChild(container);

        this.paginationContainer = document.createElement('div');
        this.paginationContainer.className = 'pagination';
        this.shadowRoot.appendChild(this.paginationContainer);
    }

    updateView() {
        if (this._loading) {
            this.loadingOverlay.classList.add('active');
        } else {
            this.loadingOverlay.classList.remove('active');
        }

        this.renderHeaders();
        this.renderBody();
        this.renderPagination();
    }

    renderHeaders() {
        this.tableHead.innerHTML = ''; // 針對 tbody/thead 的清空可以安全使用 innerHTML = '' (沒有注入風險) 或 replaceChildren()
        this.tableHead.replaceChildren();

        const tr = document.createElement('tr');
        
        this._headers.forEach(h => {
            const th = document.createElement('th');
            
            const headerTop = document.createElement('div');
            headerTop.textContent = h.label;
            headerTop.style.display = 'flex';
            headerTop.style.alignItems = 'center';
            headerTop.style.gap = '4px';
            
            if (h.sortable && h.key) {
                th.classList.add('sortable');
                th.dataset.key = h.key;
                
                const icon = document.createElement('span');
                icon.className = 'sort-icon';
                
                if (this._sort.key === h.key) {
                    icon.textContent = this._sort.asc ? '▲' : '▼';
                    icon.style.color = 'var(--text-primary)';
                } else {
                    icon.textContent = '⇅';
                }
                headerTop.appendChild(icon);
                
                th.addEventListener('click', (e) => {
                    // Do not sort when clicking on filter input
                    if (e.target.tagName === 'INPUT') return;
                    const newAsc = this._sort.key === h.key ? !this._sort.asc : true;
                    this.dispatchEvent(new CustomEvent('sort-change', {
                        detail: { key: h.key, asc: newAsc },
                        bubbles: true,
                        composed: true
                    }));
                });
            }
            
            th.appendChild(headerTop);

            if (h.filterable !== false && h.key && !['_select', 'targets', 'source_urls', 'unique_urls'].includes(h.key)) {
                const filterInput = document.createElement('input');
                filterInput.type = 'text';
                filterInput.className = 'form-input text-xs';
                filterInput.placeholder = '篩選...';
                filterInput.style.marginTop = '0.5rem';
                filterInput.style.padding = '0.25rem 0.5rem';
                filterInput.style.height = 'auto';
                filterInput.style.fontWeight = 'normal';
                filterInput.style.width = '100%';
                filterInput.style.boxSizing = 'border-box';
                filterInput.value = this._colFilters[h.key] || '';

                filterInput.addEventListener('input', (e) => {
                    const newVal = e.target.value.toLowerCase();
                    this.dispatchEvent(new CustomEvent('filter-change', {
                        detail: { key: h.key, value: newVal },
                        bubbles: true,
                        composed: true
                    }));
                });
                filterInput.addEventListener('click', e => e.stopPropagation());
                th.appendChild(filterInput);
            }
            
            if (h.width) th.style.width = h.width;
            if (h.align) th.style.textAlign = h.align;
            
            tr.appendChild(th);
        });
        
        this.tableHead.appendChild(tr);
    }

    renderBody() {
        this.tableBody.replaceChildren();

        if (this._data.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = this._headers.length || 1;
            td.className = 'empty-state';
            td.textContent = '暫無資料';
            tr.appendChild(td);
            this.tableBody.appendChild(tr);
            return;
        }

        this._data.forEach(row => {
            const tr = document.createElement('tr');
            
            this._headers.forEach(h => {
                const td = document.createElement('td');
                if (h.align) td.style.textAlign = h.align;
                if (h.truncate) {
                    td.classList.add('truncate');
                    td.style.maxWidth = typeof h.truncate === 'string' ? h.truncate : '300px';
                }
                if (h.className) {
                    td.className = td.className ? td.className + ' ' + h.className : h.className;
                }
                
                if (h.render) {
                    // render function should return a DOM Node (since innerHTML is banned)
                    const node = h.render(row[h.key], row);
                    if (node instanceof Node) {
                        td.appendChild(node);
                    } else {
                        td.textContent = String(node); // fallback text
                    }
                } else {
                    td.textContent = row[h.key] !== undefined ? row[h.key] : '-';
                }
                
                tr.appendChild(td);
            });
            
            this.tableBody.appendChild(tr);
        });
    }

    renderPagination() {
        this.paginationContainer.replaceChildren();

        const { current, total } = this._pagination;
        if (total <= 1) {
            this.paginationContainer.style.display = 'none';
            return;
        }
        this.paginationContainer.style.display = 'flex';

        const btnPrev = document.createElement('button');
        btnPrev.className = 'page-btn';
        btnPrev.textContent = '上一頁';
        btnPrev.disabled = current <= 1;
        btnPrev.addEventListener('click', () => {
            if (current > 1) this.dispatchPageChange(current - 1);
        });

        const info = document.createElement('div');
        info.className = 'page-info';
        info.textContent = `第 ${current} 頁 / 共 ${total} 頁`;

        const btnNext = document.createElement('button');
        btnNext.className = 'page-btn';
        btnNext.textContent = '下一頁';
        btnNext.disabled = current >= total;
        btnNext.addEventListener('click', () => {
            if (current < total) this.dispatchPageChange(current + 1);
        });

        this.paginationContainer.appendChild(btnPrev);
        this.paginationContainer.appendChild(info);
        this.paginationContainer.appendChild(btnNext);
    }

    dispatchPageChange(page) {
        this.dispatchEvent(new CustomEvent('page-change', {
            detail: { page },
            bubbles: true,
            composed: true
        }));
    }

    setupEventListeners() {}
    teardownEventListeners() {}
}
customElements.define('link-table', LinkDataTable);
