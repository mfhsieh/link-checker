/**
 * jobs-store.js — 任務列表狀態與 API 資料管理層 (ESM Store)
 * 
 * 負責維護任務列表頁面的狀態（包含資料快取、排序選項、欄位篩選器），
 * 並提供對應的 API 請求與本地端排序/篩選計算邏輯。
 */

import * as api from '../api.js';

export class JobsStore {
    /**
     * 初始化 JobsStore 實例
     */
    constructor() {
        /** @type {Array<Object>} 快取當前載入的任務清單 */
        this.currentJobs = [];
        /** @type {{key: string, asc: boolean}} 目前的排序設定 */
        this.sort = { key: 'created_at', asc: false };
        /** @type {Object<string, string>} 欄位過濾器條件 */
        this.colFilters = {};
    }

    /**
     * 重置或批量更新過濾器條件
     * @param {Object|null} filters - 欲合併的篩選條件字典
     * @returns {void}
     */
    setFilters(filters) {
        if (filters) {
            Object.assign(this.colFilters, filters);
        }
    }

    /**
     * 設定單一欄位的過濾條件
     * @param {string} key - 欄位名稱
     * @param {string} value - 篩選數值
     * @returns {void}
     */
    setFilter(key, value) {
        this.colFilters[key] = value;
    }

    /**
     * 設定排序狀態
     * @param {{key: string, asc: boolean}} sortOption - 排序設定物件
     * @returns {void}
     */
    setSort(sortOption) {
        this.sort = sortOption;
    }

    /**
     * 向後端 API 取得任務清單資料
     * @param {Object} [pagination={}] - (選填) 分頁參數物件
     * @param {number} [pagination.limit] - 限制回傳筆數
     * @param {number} [pagination.offset] - 跳過筆數
     * @returns {Promise<Array<Object>>} 回傳任務列表資料陣列
     */
    async fetchJobs(pagination = {}) {
        const params = {
            sort_by: this.sort.key,
            order: this.sort.asc ? 'asc' : 'desc',
            ...this.colFilters
        };

        if (pagination.limit !== undefined && pagination.limit !== null) {
            params.limit = pagination.limit;
        }
        if (pagination.offset !== undefined && pagination.offset !== null) {
            params.offset = pagination.offset;
        }

        if (this.colFilters.status === 'ALL' || !this.colFilters.status) {
            delete params.status;
        }

        const data = await api.get('/api/jobs', params);
        this.currentJobs = data || [];
        return this.currentJobs;
    }

    /**
     * 進行 Client-side 的過濾與排序計算
     * @returns {Array<Object>} 回傳處理後的任務清單
     */
    getFilteredAndSortedJobs() {
        let data = [...this.currentJobs];

        // Client-side filtering (除 status 由 API 處理外)
        for (const [k, v] of Object.entries(this.colFilters)) {
            if (!v || k === 'status') continue;
            data = data.filter(item => {
                let val = item[k];
                if (k === 'created_at') val = api.formatLocalTime(val);
                return String(val || '').toLowerCase().includes(v.toLowerCase());
            });
        }

        // Client-side sorting
        data.sort((a, b) => {
            let valA = a[this.sort.key];
            let valB = b[this.sort.key];
            if (valA === undefined || valA === null) valA = '';
            if (valB === undefined || valB === null) valB = '';

            if (this.sort.key === 'created_at') {
                valA = new Date(valA).getTime() || 0;
                valB = new Date(valB).getTime() || 0;
                return this.sort.asc ? valA - valB : valB - valA;
            }

            valA = String(valA).toLowerCase();
            valB = String(valB).toLowerCase();
            if (valA < valB) return this.sort.asc ? -1 : 1;
            if (valA > valB) return this.sort.asc ? 1 : -1;
            return 0;
        });

        return data;
    }
}
