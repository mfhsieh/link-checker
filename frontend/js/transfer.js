/**
 * transfer.js — 任務移交模組進入點（ESM）
 */

import { TransferController } from './controllers/transfer-controller.js';

/** @type {TransferController|null} 單一控制器實例 */
let transferController = null;

/**
 * 初始化任務移交頁面
 * @param {string|null} preselectedJobId - (可選) 欲預設選取的任務 ID
 * @returns {Promise<void>}
 */
export async function initTransferPage(preselectedJobId = null) {
    if (!transferController) {
        transferController = new TransferController();
    }
    await transferController.init(preselectedJobId);
}

/**
 * 銷毀並清理移交頁面資源
 * @returns {void}
 */
export function destroyTransferPage() {
    if (transferController) {
        transferController.destroy();
    }
}