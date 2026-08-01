/**
 * compare-store.js — 任務比對狀態與資料管理層 (ESM Store)
 * 
 * 負責維護比對頁面的狀態（包含差異資料、目前頁籤、排序選項、欄位篩選器），
 * 並提供對應的 API 請求與本地端資料處理邏輯。
 */

import * as api from '../api.js';

export class CompareStore {
    /**
     * 初始化 CompareStore 實例
     */
    constructor() {
        this.reset();
    }

    /**
     * 重置所有狀態至初始預設值
     * @returns {void}
     */
    reset() {
        /** @type {Object|null} 目前比對的差異資料 */
        this.currentDiffData = null;
        this.baseId = null;
        this.targetId = null;
        /** @type {string} 目前選取的差異頁籤 */
        this.currentTab = 'ip_changed';
        /** @type {{key: string|null, asc: boolean}} 差異表格的排序狀態 */
        this.compareSort = { key: null, asc: true };
        /** @type {Object<string, string>} 差異表格的各欄位篩選條件 */
        this.compareColFilters = {};
        /** @type {Array<Object>} 目前差異表格的表頭設定 */
        this.currentCompareHeaders = [];
        /** @type {number} 當前頁碼 (1-indexed) */
        this.currentPage = 1;
        /** @type {number} 每頁筆數（與任務詳情表格保持一致 50 筆） */
        this.pageSize = 50;
        this.totalItems = 0;
        this.pagedData = [];
    }

    /**
     * 向後端 API 取得任務比對差異資料
     * @param {string} baseId - 基準任務 ID
     * @param {string} targetId - 對照任務 ID
     * @returns {Promise<Object>} 回傳比對結果資料
     */
    async fetchDiff(baseId, targetId) {
        const excludeDomains = localStorage.getItem('link-checker-exclude-domains') || '';
        const excludeEnabled = localStorage.getItem('link-checker-exclude-enabled') !== 'false';
        
        let url = `/api/jobs/${baseId}/diff?compare_with=${targetId}`;
        if (excludeEnabled && excludeDomains) {
            url += `&exclude=${encodeURIComponent(excludeDomains)}`;
        }
        
        const res = await api.get(url);
        this.currentDiffData = res;
        this.baseId = baseId;
        this.targetId = targetId;
        this.currentPage = 1;
        return res;
    }

    async fetchItems() {
        if (!this.currentDiffData || !this.baseId || !this.targetId) return [];
        let cat = this.currentTab;
        // The backend expects "ext_ip_changed", "int_degraded", etc.
        // We know that in diff.py we saved it as:
        // ext_{category} or int_{category}
        // If currentTab starts with internal_, we map it to int_{category}
        // Otherwise, we map it to ext_{category}
        if (cat.startsWith('internal_')) {
            cat = cat.replace('internal_', 'int_');
        } else {
            cat = 'ext_' + cat;
        }

        let url = `/api/jobs/${this.baseId}/diff/items?compare_with=${this.targetId}&category=${cat}&page=${this.currentPage}&page_size=${this.pageSize}`;

        if (this.compareSort && this.compareSort.key) {
            url += `&sort_by=${encodeURIComponent(this.compareSort.key)}&sort_asc=${this.compareSort.asc}`;
        }
        
        if (this.compareColFilters) {
            const activeFilters = Object.fromEntries(Object.entries(this.compareColFilters).filter(([_, v]) => v.trim() !== ''));
            if (Object.keys(activeFilters).length > 0) {
                url += `&col_filters=${encodeURIComponent(JSON.stringify(activeFilters))}`;
            }
        }

        const res = await api.get(url);
        this.totalItems = res.total;
        this.pagedData = res.items;
        return this.pagedData;
    }

    /**
     * 設定排序狀態
     * @param {{key: string|null, asc: boolean}} sortOption - 排序設定物件
     * @returns {void}
     */
    setSort(sortOption) {
        this.compareSort = sortOption;
        this.currentPage = 1;
    }

    /**
     * 設定單一欄位的過濾條件
     * @param {string} key - 欄位名稱
     * @param {string} value - 篩選數值
     * @returns {void}
     */
    setFilter(key, value) {
        this.compareColFilters[key] = value;
        this.currentPage = 1;
    }

    /**
     * 設定目前頁籤
     * @param {string} tabName - 頁籤名稱
     * @returns {void}
     */
    setTab(tabName) {
        if (this.currentTab !== tabName) {
            this.currentTab = tabName;
            this.currentPage = 1;
        }
    }

    /**
     * 設定當前頁碼
     * @param {number} page - 頁碼
     * @returns {void}
     */
    setPage(page) {
        this.currentPage = page;
    }

    /**
     * 計算目前總頁數
     * @returns {number} 總頁數（至少為 1）
     */
    getTotalPages() {
        return Math.ceil(this.totalItems / this.pageSize) || 1;
    }
}
