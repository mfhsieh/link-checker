/**
 * job-service.js — 任務相關的 API 業務邏輯封裝
 *
 * 負責處理任務建立與全域預設值獲取的 API 呼叫。
 */
import * as api from "../api.js";

/**
 * 建立新任務
 * @param {Object} payload - 任務配置參數字典
 * @returns {Promise<Object>} 回傳建立的任務結果物件，包含任務 ID
 */
export async function createJob(payload) {
  return api.post("/api/jobs", payload);
}

/**
 * 取得全域預設設定，並加上時間戳記以避免快取
 * @returns {Promise<Object>} 回傳包含系統預設任務參數的物件
 */
export async function getDefaultConfig() {
  return api.get("/api/jobs/default-config?_t=" + Date.now());
}
