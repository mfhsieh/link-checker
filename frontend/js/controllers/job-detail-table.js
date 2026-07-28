/**
 * job-detail-table.js — 任務詳情表格渲染與工具列狀態控制器 (ESM Controller)
 *
 * 專責建立 DOM API 儲存格與超連結節點，並構建外部與內部連結 `<link-table>` 視圖的配置。
 */

/**
 * 建立一個單純的文字表格儲存格
 * @param {string} text - 文字內容
 * @param {string} [cls=''] - 附加的 CSS 類別
 * @returns {HTMLSpanElement} 回傳內含純文字的 <span> 元素
 */
export const createCell = (text, cls = '') => {
    const span = document.createElement('span');
    span.textContent = text;
    if (cls) span.className = cls;
    return span;
};

/**
 * 建立包含 URL 的超連結節點
 * @param {string} url - 網址
 * @param {string} [maxWidth='300px'] - 最大寬度限制
 * @param {string|null} [displayText=null] - 顯示文字，若為 null 則顯示原始網址
 * @returns {HTMLAnchorElement|HTMLSpanElement} 回傳 <a> 元素或純文字 <span> 元素
 */
export const renderUrlNode = (url, maxWidth = '300px', displayText = null) => {
    if (!url) return createCell('-', 'text-muted');
    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'truncate font-mono text-link';
    a.style.maxWidth = maxWidth;
    a.style.display = 'inline-block';
    a.style.verticalAlign = 'middle';
    a.title = url;
    a.textContent = displayText || url;
    return a;
};

/**
 * 建立包含多個 URL 的展開/收合節點
 * @param {Array<Object>|string} val - URL 資料陣列或字串
 * @param {string} [maxWidth='300px'] - 最大寬度限制
 * @param {Function} [extractUrl=(x)=>x] - 提取 URL 的回呼函式
 * @returns {HTMLDivElement|HTMLSpanElement} 回傳包覆網址清單的 <div> 容器元素
 */
export const renderUrlArrayNode = (val, maxWidth = '300px', extractUrl = (x) => x) => {
    if (!val || !val.length) return createCell('-', 'text-muted');
    const wrapper = document.createElement('div');
    wrapper.style.display = 'flex';
    wrapper.style.flexDirection = 'column';
    wrapper.style.gap = '0.25rem';

    const displayLimit = 5;
    const displayList = val.slice(0, displayLimit);

    displayList.forEach(item => {
        const url = extractUrl(item);
        const a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.className = 'truncate font-mono text-link';
        a.style.maxWidth = maxWidth;
        a.title = url;
        a.textContent = url;
        wrapper.appendChild(a);
    });

    if (val.length > displayLimit) {
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.style.alignSelf = 'flex-start';
        badge.textContent = `及其它`;
        wrapper.appendChild(badge);
    }
    return wrapper;
};

/**
 * 建立錯誤訊息樣式節點
 * @param {string} msg - 錯誤訊息字串
 * @param {string} [maxWidth='300px'] - 最大寬度限制
 * @returns {HTMLSpanElement} 回傳內含錯誤訊息的 <span> 元素
 */
export const renderErrorMessage = (msg, maxWidth = '300px') => {
    if (!msg) return createCell('-', 'text-muted');
    const span = document.createElement('span');
    span.className = 'truncate text-danger';
    span.style.maxWidth = maxWidth;
    span.style.display = 'inline-block';
    span.title = msg;
    span.textContent = msg;
    return span;
};

/**
 * 建立 HTTP 狀態碼的樣式節點
 * @param {number|null} code - HTTP 狀態碼
 * @returns {HTMLSpanElement} 回傳帶有不同色彩標示的 <span> 元素
 */
export const renderHttpStatusCode = (code) => {
    if (code === null || code === undefined) return createCell('-', 'text-muted');
    const span = document.createElement('span');
    span.style.display = 'inline-block';
    span.textContent = code;
    if (code >= 200 && code < 300) span.className = 'text-success';
    else if (code >= 300 && code < 400) span.className = 'text-warning';
    else if (code >= 400) span.className = 'text-danger';
    return span;
};

/**
 * 任務詳情表格視圖管理器
 * 負責構建內部連結、外部連結表格的標題 (Headers) 與渲染邏輯
 */
export class JobDetailTableManager {
    /**
     * 渲染外部連結結果表格與構建頭部設定
     * @param {Object} res - API 回傳的分頁結果物件
     * @param {import('../stores/job-detail-store.js').JobDetailStore} store - 任務詳情 Store
     * @param {HTMLElement} extDataTable - <link-table> 自訂元素
     * @returns {void}
     */
    renderExtResultsTable(res, store, extDataTable) {
        if (!extDataTable) return;

        let headers = [];
        const currentGroupBy = store.currentGroupBy;

        if (currentGroupBy === 'none') {
            headers = [
                { label: '來源頁面', key: 'source_url', sortable: true, render: (val) => renderUrlNode(val) },
                { label: '目標頁面', key: 'target_url', sortable: true, render: (val) => renderUrlNode(val) },
                { label: 'IP 位址', key: 'ip_address', sortable: true, truncate: '150px', className: 'font-mono text-sm' },
                { label: 'HTTPS', key: 'is_secure', sortable: true, align: 'center', render: val => val ? createCell('✓', 'text-success') : createCell('✗', 'text-danger') },
                { label: 'HTTP 狀態', key: 'http_status_code', sortable: true, align: 'center', render: val => renderHttpStatusCode(val) },
                { label: '錯誤訊息', key: 'error_message', sortable: true, render: (val) => renderErrorMessage(val) }
            ];
        } else if (currentGroupBy === 'target') {
            headers = [
                { label: '目標頁面', key: 'target_url', sortable: true, render: (val) => renderUrlNode(val) },
                { label: 'IP 位址', key: 'ip_address', sortable: true, truncate: '150px', className: 'font-mono text-sm' },
                { label: 'HTTPS', key: 'is_secure', sortable: true, align: 'center', render: val => val ? createCell('✓', 'text-success') : createCell('✗', 'text-danger') },
                { label: 'HTTP 狀態', key: 'http_status_code', sortable: true, align: 'center', render: val => renderHttpStatusCode(val) },
                { label: '錯誤訊息', key: 'error_message', sortable: true, render: (val) => renderErrorMessage(val) },
                { label: '來源數量', key: 'occurrence_count', sortable: true, align: 'center' },
                { label: '來源頁面', key: 'source_urls', render: (val) => renderUrlArrayNode(val) }
            ];
        } else if (currentGroupBy === 'source') {
            headers = [
                { label: '來源頁面', key: 'source_url', sortable: true, render: (val) => renderUrlNode(val) },
                { label: '目標數量', key: 'occurrence_count', sortable: true, align: 'center' },
                { label: '目標頁面', key: 'targets', render: (val) => renderUrlArrayNode(val, '300px', t => t.url) }
            ];
        } else if (currentGroupBy === 'domain') {
            headers = [
                { label: '外部網域', key: 'domain', sortable: true, render: (val) => renderUrlNode('https://' + val, '300px', val) },
                { label: '目標數量', key: 'unique_urls_count', sortable: true, align: 'center' },
                { label: '來源數量', key: 'occurrence_count', sortable: true, align: 'center' },
                { label: '目標頁面', key: 'unique_urls', render: (val) => renderUrlArrayNode(val) },
                { label: '來源頁面', key: 'source_urls', render: (val) => renderUrlArrayNode(val) }
            ];
        }

        const isJobRunning = ['running', 'starting'].includes(store.currentJobStatus);
        let isExtSelectable = (currentGroupBy === 'target' || currentGroupBy === 'source') && !isJobRunning;
        if (currentGroupBy === 'target' && store.currentFilter === 'insecure') {
            isExtSelectable = false;
        }

        extDataTable.config = {
            headers,
            data: res.items || [],
            sort: store.detailSort,
            colFilters: store.detailColFilters,
            pagination: { current: res.page, total: res.total_pages },
            loading: false,
            selectable: isExtSelectable,
            rowKey: currentGroupBy === 'source' ? 'source_url' : 'target_url'
        };
    }

    /**
     * 渲染內部連結結果表格與構建頭部設定
     * @param {Object} res - API 回傳的分頁結果物件
     * @param {import('../stores/job-detail-store.js').JobDetailStore} store - 任務詳情 Store
     * @param {HTMLElement} intDataTable - <link-table> 自訂元素
     * @returns {void}
     */
    renderInternalResultsTable(res, store, intDataTable) {
        if (!intDataTable) return;

        let headers = [];
        const internalGroupBy = store.internalGroupBy;

        if (internalGroupBy === 'source') {
            headers = [
                { label: '來源頁面', key: 'source_url', sortable: true, render: (val) => renderUrlNode(val) },
                { label: '目標數量', key: 'occurrence_count', sortable: true, align: 'center' },
                { label: '目標頁面', key: 'targets', render: (val) => renderUrlArrayNode(val, '300px', t => t.url) }
            ];
        } else {
            headers = [
                { label: '來源頁面', key: 'source_url', sortable: true, render: (val) => renderUrlNode(val) },
                { label: '目標頁面', key: 'target_url', sortable: true, render: (val) => renderUrlNode(val) },
                { label: 'HTTPS', key: 'is_secure', sortable: true, align: 'center', render: val => val ? createCell('✓', 'text-success') : createCell('✗', 'text-danger') },
                { label: 'HTTP 狀態', key: 'http_status_code', sortable: true, align: 'center', render: val => renderHttpStatusCode(val) },
                { label: '錯誤訊息', key: 'error_message', sortable: true, render: (val) => renderErrorMessage(val) }
            ];
        }

        const isJobRunning = ['running', 'starting'].includes(store.currentJobStatus);
        let isIntSelectable = (internalGroupBy === 'none' || internalGroupBy === 'source') && !isJobRunning;
        if (internalGroupBy === 'none' && store.internalFilter === 'insecure') {
            isIntSelectable = false;
        }

        intDataTable.config = {
            headers,
            data: res.items || [],
            sort: store.internalSort,
            colFilters: store.internalColFilters,
            pagination: { current: res.page, total: res.total_pages },
            loading: false,
            selectable: isIntSelectable,
            rowKey: internalGroupBy === 'source' ? 'source_url' : 'target_url'
        };
    }

    /**
     * 更新外部連結頁籤中的工具列按鈕文字與顯示狀態
     * @param {import('../stores/job-detail-store.js').JobDetailStore} store - 任務詳情 Store
     * @returns {void}
     */
    updateExtToolbarButtons(store) {
        const btnReprobe = document.getElementById('btn-ext-reprobe-selected');
        const btnExport = document.getElementById('btn-ext-export-selected');
        if (store.extSelectedUrls.size > 0) {
            if (btnReprobe) {
                btnReprobe.style.display = 'inline-flex';
                btnReprobe.textContent = `重新探測 (${store.extSelectedUrls.size})`;
            }
            if (btnExport) {
                btnExport.style.display = 'inline-flex';
                btnExport.textContent = `匯出選取 (${store.extSelectedUrls.size})`;
            }
        } else {
            if (btnReprobe) btnReprobe.style.display = 'none';
            if (btnExport) btnExport.style.display = 'none';
        }
    }

    /**
     * 更新內部連結頁籤中的工具列按鈕文字與顯示狀態
     * @param {import('../stores/job-detail-store.js').JobDetailStore} store - 任務詳情 Store
     * @returns {void}
     */
    updateIntToolbarButtons(store) {
        const btnReprobe = document.getElementById('btn-int-reprobe-selected');
        const btnExport = document.getElementById('btn-int-export-selected');
        if (store.intSelectedUrls.size > 0) {
            if (btnReprobe) {
                btnReprobe.style.display = 'inline-flex';
                btnReprobe.textContent = `重新探測 (${store.intSelectedUrls.size})`;
            }
            if (btnExport) {
                btnExport.style.display = 'inline-flex';
                btnExport.textContent = `匯出選取 (${store.intSelectedUrls.size})`;
            }
        } else {
            if (btnReprobe) btnReprobe.style.display = 'none';
            if (btnExport) btnExport.style.display = 'none';
        }
    }
}
