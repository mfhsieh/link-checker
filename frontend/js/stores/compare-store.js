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
        return res;
    }

    /**
     * 設定排序狀態
     * @param {{key: string|null, asc: boolean}} sortOption - 排序設定物件
     * @returns {void}
     */
    setSort(sortOption) {
        this.compareSort = sortOption;
    }

    /**
     * 設定單一欄位的過濾條件
     * @param {string} key - 欄位名稱
     * @param {string} value - 篩選數值
     * @returns {void}
     */
    setFilter(key, value) {
        this.compareColFilters[key] = value;
    }

    /**
     * 設定目前頁籤
     * @param {string} tabName - 頁籤名稱
     * @returns {void}
     */
    setTab(tabName) {
        this.currentTab = tabName;
    }

    /**
     * 進行 Client-side 的過濾與排序計算
     * @returns {Array<Object>} 回傳處理後的差異清單
     */
    getFilteredData() {
        if (!this.currentDiffData || !this.currentDiffData.details[this.currentTab]) return [];
        let data = [...this.currentDiffData.details[this.currentTab]];

        if (this.currentTab === 'ip_changed') {
            const grouped = {};
            data.forEach(item => {
                let domain = '';
                try {
                    domain = new URL(item.target_url).hostname;
                } catch (e) {
                    domain = item.target_url;
                }
                const key = `${domain}|${item.old_ip}|${item.new_ip}`;
                if (!grouped[key]) {
                    grouped[key] = {
                        domain: domain,
                        old_ip: item.old_ip,
                        new_ip: item.new_ip,
                        url_count: 0,
                        target_urls: new Set(),
                        sources: new Set()
                    };
                }
                grouped[key].url_count += 1;
                if (grouped[key].target_urls.size < 10) {
                    grouped[key].target_urls.add(item.target_url);
                }
                if (item.sources) {
                    item.sources.forEach(src => {
                        if (grouped[key].sources.size < 10) {
                            grouped[key].sources.add(src);
                        }
                    });
                }
            });
            data = Object.values(grouped).map(g => ({
                ...g,
                target_urls: Array.from(g.target_urls).sort(),
                sources: Array.from(g.sources).sort()
            }));
        }

        for (const [k, v] of Object.entries(this.compareColFilters)) {
            if (!v) continue;
            data = data.filter(item => {
                let val = item[k];
                return String(val || '').toLowerCase().includes(v.toLowerCase());
            });
        }

        if (this.compareSort.key) {
            data.sort((a, b) => {
                let valA = a[this.compareSort.key];
                let valB = b[this.compareSort.key];
                if (valA === undefined || valA === null) valA = '';
                if (valB === undefined || valB === null) valB = '';
                if (typeof valA === 'number' && typeof valB === 'number') return this.compareSort.asc ? valA - valB : valB - valA;
                valA = String(valA).toLowerCase();
                valB = String(valB).toLowerCase();
                if (valA < valB) return this.compareSort.asc ? -1 : 1;
                if (valA > valB) return this.compareSort.asc ? 1 : -1;
                return 0;
            });
        } else if (this.currentTab === 'ip_changed') {
            data.sort((a, b) => b.url_count - a.url_count);
        }

        return data;
    }
}
