/**
 * admin-service.js — 後台管理相關的 API 業務邏輯封裝
 *
 * 負責處理使用者管理、任務監控、全域設定、SMTP 配置與操作日誌等管理員專屬的 API 呼叫。
 */
import * as api from "../api.js";

// ── 使用者管理 ──────────────────────────────────────────────

/**
 * 取得所有使用者列表
 * @returns {Promise<Array<Object>>} 回傳使用者物件陣列
 */
export async function getUsers() {
  return api.get("/api/admin/users");
}

/**
 * 邀請新使用者
 * @param {string} email - 欲邀請的電子郵件地址
 * @returns {Promise<Object>} API 回應結果
 */
export async function inviteUser(email) {
  return api.post("/api/admin/users", { email });
}

/**
 * 停用指定使用者帳號
 * @param {string} userId - 使用者 ID
 * @returns {Promise<Object>} API 回應結果
 */
export async function suspendUser(userId) {
  return api.patch(`/api/admin/users/${userId}`, { status: "suspended" });
}

/**
 * 啟用指定使用者帳號
 * @param {string} userId - 使用者 ID
 * @returns {Promise<Object>} API 回應結果
 */
export async function activateUser(userId) {
  return api.patch(`/api/admin/users/${userId}`, { status: "active" });
}

/**
 * 變更使用者角色
 * @param {string} userId - 使用者 ID
 * @param {'admin'|'user'} newRole - 新的角色
 * @returns {Promise<Object>} API 回應結果
 */
export async function changeUserRole(userId, newRole) {
  return api.patch(`/api/admin/users/${userId}`, { role: newRole });
}

/**
 * 重新寄送邀請信
 * @param {string} userId - 使用者 ID
 * @returns {Promise<Object>} API 回應結果
 */
export async function resendInvite(userId) {
  return api.post(`/api/admin/users/${userId}/resend-invite`);
}

/**
 * 刪除指定使用者帳號
 * @param {string} userId - 使用者 ID
 * @returns {Promise<Object>} API 回應結果
 */
export async function deleteUser(userId) {
  return api.del(`/api/admin/users/${userId}`);
}

// ── 任務監控 ──────────────────────────────────────────────

/**
 * 取得系統內所有任務（包含其他使用者的任務）
 * @returns {Promise<Array<Object>>} 回傳任務物件陣列
 */
export async function getAllJobs() {
  return api.get("/api/admin/jobs");
}

/**
 * 強制暫停/接管指定任務
 * @param {string} jobId - 任務 ID
 * @returns {Promise<Object>} API 回應結果
 */
export async function takeoverJob(jobId) {
  return api.post(`/api/admin/jobs/${jobId}/takeover`);
}

/**
 * 強制刪除指定任務
 * @param {string} jobId - 任務 ID
 * @returns {Promise<Object>} API 回應結果
 */
export async function deleteJob(jobId) {
  return api.del(`/api/admin/jobs/${jobId}`);
}

// ── 全域設定 ──────────────────────────────────────────────

/**
 * 取得全域爬蟲配置
 * @returns {Promise<Object>} 回傳配置物件
 */
export async function getConfig() {
  return api.get("/api/admin/config");
}

/**
 * 儲存/更新全域爬蟲配置
 * @param {Object} payload - 欲更新的配置資料
 * @returns {Promise<Object>} API 回應結果
 */
export async function saveConfig(payload) {
  return api.patch("/api/admin/config", payload);
}

// ── SMTP ──────────────────────────────────────────────

/**
 * 取得目前 SMTP 伺服器配置狀態
 * @returns {Promise<Object>} 回傳 SMTP 配置物件
 */
export async function getSmtp() {
  return api.get("/api/admin/smtp");
}

/**
 * 發送測試郵件以驗證 SMTP 配置
 * @param {string} email - 測試收件者信箱
 * @returns {Promise<Object>} API 回應結果
 */
export async function testSmtp(email) {
  return api.post("/api/admin/smtp/test", { to_email: email });
}

// ── 操作日誌 ──────────────────────────────────────────────

/**
 * 取得系統操作日誌
 * @param {number} [page=1] - 頁碼
 * @param {number} [pageSize=50] - 每頁筆數
 * @returns {Promise<Object>} 回傳包含日誌陣列與分頁資訊的物件
 */
export async function getLogs(page = 1, pageSize = 50, filters = {}) {
  const params = { page, page_size: pageSize };
  if (filters.user_id) params.user_id = filters.user_id;
  if (filters.event_type) params.event_type = filters.event_type;
  if (filters.ip_address) params.ip_address = filters.ip_address;
  return api.get("/api/admin/logs", params);
}
