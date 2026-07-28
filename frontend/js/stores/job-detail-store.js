/**
 * job-detail-store.js — 任務詳情頁面集中式狀態庫 (ESM Store)
 *
 * 集中管理任務詳情頁面的所有狀態變數，包含：當前任務資料、頁籤、
 * 外部/內部連結的排序、篩選、分頁、請求記號、選取 URL 集合與快取。
 */

export class JobDetailStore {
    /**
     * 初始化 JobDetailStore 實例
     */
    constructor() {
        this.reset();
    }

    /**
     * 重置所有狀態至初始預設值
     * @param {string|null} [jobId=null] - 任務 ID
     * @returns {void}
     */
    reset(jobId = null) {
        /** @type {string|null} 當前任務 ID */
        this.currentJobId = jobId;
        /** @type {string|null} 當前任務狀態 */
        this.currentJobStatus = null;
        /** @type {Object|null} 當前任務完整資料 */
        this.currentJobData = null;

        /** @type {'external'|'internal'} 當前選擇的頁籤 */
        this.currentTab = 'external';

        // 外部連結狀態
        /** @type {string|null} 外部連結狀態篩選條件 */
        this.currentFilter = null;
        /** @type {string} 排除網域清單 (逗號分隔) */
        this.currentExclude = localStorage.getItem('link-checker-exclude-domains') || '';
        /** @type {boolean} 是否啟用排除網域 */
        this.currentExcludeEnabled = localStorage.getItem('link-checker-exclude-enabled') !== 'false';
        /** @type {string} 外部連結分組方式 ('none'|'target'|'source'|'domain') */
        this.currentGroupBy = 'none';
        /** @type {number} 外部連結當前頁碼 */
        this.currentPage = 1;
        /** @type {{key: string|null, asc: boolean}} 外部連結排序選項 */
        this.detailSort = { key: null, asc: true };
        /** @type {Object<string, string>} 外部連結欄位篩選器 */
        this.detailColFilters = {};
        /** @type {Set<string>} 勾選的外部連結網址集合 */
        this.extSelectedUrls = new Set();

        // 內部連結狀態
        /** @type {number} 內部連結當前頁碼 */
        this.internalCurrentPage = 1;
        /** @type {string|null} 內部連結狀態篩選條件 */
        this.internalFilter = null;
        /** @type {string} 內部連結分組方式 ('none'|'source') */
        this.internalGroupBy = 'none';
        /** @type {{key: string|null, asc: boolean}} 內部連結排序選項 */
        this.internalSort = { key: null, asc: true };
        /** @type {Object<string, string>} 內部連結欄位篩選器 */
        this.internalColFilters = {};
        /** @type {Set<string>} 勾選的內部連結網址集合 */
        this.intSelectedUrls = new Set();

        // Request ID 防競態記號
        /** @type {number} 外部連結請求 ID */
        this.currentExtReqId = 0;
        /** @type {number} 內部連結請求 ID */
        this.currentIntReqId = 0;
        /** @type {number} 外部連結統計摘要請求 ID */
        this.currentExtSummaryReqId = 0;
        /** @type {number} 內部連結統計摘要請求 ID */
        this.currentIntSummaryReqId = 0;

        // 統計資料快取
        /** @type {{key: string|null, data: Object|null}} 外部連結統計快取 */
        this.extSummaryCache = { key: null, data: null };
        /** @type {{key: string|null, data: Object|null}} 內部連結統計快取 */
        this.intSummaryCache = { key: null, data: null };

        // Timeout 句柄
        /** @type {number|null} 外部連結防抖計時器 */
        this.extFilterTimeout = null;
        /** @type {number|null} 內部連結防抖計時器 */
        this.intFilterTimeout = null;
    }

    /**
     * 清除勾選的 URL 項目集合
     * @returns {void}
     */
    clearSelections() {
        this.extSelectedUrls.clear();
        this.intSelectedUrls.clear();
    }

    /**
     * 使外連與內連統計快取無效化
     * @returns {void}
     */
    invalidateCaches() {
        this.extSummaryCache = { key: null, data: null };
        this.intSummaryCache = { key: null, data: null };
    }
}
