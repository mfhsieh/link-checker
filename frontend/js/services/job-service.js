/**
 * job-service.js — 任務相關的 API 業務邏輯封裝
 *
 * 負責處理任務建立、查詢、控制與全域預設值獲取的 API 呼叫。
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

/**
 * 取得當前使用者的任務列表（支援分頁）
 * @param {Object} [params] - 查詢參數 (limit, offset 等)
 * @returns {Promise<Array<Object>>} 回傳任務物件陣列
 */
export async function getJobs(params) {
  return api.get("/api/jobs", params);
}

/**
 * 取得單一任務詳細資訊
 * @param {string} jobId - 任務 ID
 * @returns {Promise<Object>} 回傳任務詳細資料
 */
export async function getJob(jobId) {
  return api.get(`/api/jobs/${jobId}`);
}

/**
 * 刪除指定任務
 * @param {string} jobId - 任務 ID
 * @returns {Promise<Object>} API 回應結果
 */
export async function deleteJob(jobId) {
  return api.del(`/api/jobs/${jobId}`);
}

/**
 * 暫停指定任務
 * @param {string} jobId - 任務 ID
 * @returns {Promise<Object>} API 回應結果
 */
export async function pauseJob(jobId) {
  return api.post(`/api/jobs/${jobId}/pause`);
}

/**
 * 恢復指定任務
 * @param {string} jobId - 任務 ID
 * @returns {Promise<Object>} API 回應結果
 */
export async function resumeJob(jobId) {
  return api.post(`/api/jobs/${jobId}/resume`);
}
