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
        this.currentPage = 1;
        return res;
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
     * 進行 Client-side 的過濾與排序計算
     * @returns {Array<Object>} 回傳處理後的差異清單
     */
    getFilteredData() {
        if (!this.currentDiffData) return [];

        let detailsObj = null;
        if (this.currentTab.startsWith('internal_')) {
            if (this.currentDiffData.internal && this.currentDiffData.internal.details) {
                const internalKey = this.currentTab.replace(/^internal_/, '');
                detailsObj = this.currentDiffData.internal.details[internalKey];
            }
        } else {
            if (this.currentDiffData.details && this.currentDiffData.details[this.currentTab]) {
                detailsObj = this.currentDiffData.details[this.currentTab];
            }
        }

        if (!detailsObj) return [];
        let data = [...detailsObj];

        for (const [k, v] of Object.entries(this.compareColFilters)) {
            if (!v) continue;
            data = data.filter(item => {
                let val = item[k];
                return String(val || '').toLowerCase().includes(v.toLowerCase());
            });
        }

        if (this.compareSort.key) {
            const { key, asc } = this.compareSort;
            data.sort((a, b) => {
                let valA = a[key];
                let valB = b[key];
                if (valA === valB) return 0;
                if (valA === null || valA === undefined) return 1;
                if (valB === null || valB === undefined) return -1;
                if (typeof valA === 'number' && typeof valB === 'number') {
                    return asc ? valA - valB : valB - valA;
                }
                return asc
                    ? String(valA).localeCompare(String(valB))
                    : String(valB).localeCompare(String(valA));
            });
        } else if (this.currentTab === 'ip_changed') {
            data.sort((a, b) => b.url_count - a.url_count);
        }

        return data;
    }

    /**
     * 取得當前頁碼切片後的資料
     * @returns {Array<Object>} 當前頁碼筆數清單
     */
    getPagedData() {
        const data = this.getFilteredData();
        const start = (this.currentPage - 1) * this.pageSize;
        return data.slice(start, start + this.pageSize);
    }

    /**
     * 計算目前總頁數
     * @returns {number} 總頁數（至少為 1）
     */
    getTotalPages() {
        const data = this.getFilteredData();
        return Math.ceil(data.length / this.pageSize) || 1;
    }
}
