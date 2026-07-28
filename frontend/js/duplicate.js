/**
 * duplicate.js — 複製任務模組進入點（ESM）
 */

import { DuplicateController } from './controllers/duplicate-controller.js';

/** @type {DuplicateController|null} 單一控制器實例 */
let duplicateController = null;

/**
 * 初始化任務複製頁面
 * @returns {Promise<void>}
 */
export async function initDuplicatePage() {
    if (!duplicateController) {
        duplicateController = new DuplicateController();
    }
    await duplicateController.init();
}

/**
 * 銷毀並清理複製頁面資源
 * @returns {void}
 */
export function destroyDuplicatePage() {
    if (duplicateController) {
        duplicateController.destroy();
    }
}