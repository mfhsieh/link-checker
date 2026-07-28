/**
 * compare.js — 任務比對模組進入點（ESM）
 */

import { CompareController } from './controllers/compare-controller.js';
import { CompareStore } from './stores/compare-store.js';

/** @type {CompareController|null} 單一控制器實例 */
let compareController = null;

/**
 * 初始化任務比對頁面
 * @param {string|null} baseJobId - (可選) 欲預設選取的基準任務 ID
 * @param {string|null} targetJobId - (可選) 欲預設選取的對照任務 ID
 * @returns {Promise<void>}
 */
export async function initComparePage(baseJobId = null, targetJobId = null) {
    if (!compareController) {
        compareController = new CompareController(new CompareStore());
    }
    await compareController.init(baseJobId, targetJobId);
}

/**
 * 銷毀並清理比對頁面資源
 * @returns {void}
 */
export function destroyComparePage() {
    if (compareController) {
        compareController.destroy();
    }
}