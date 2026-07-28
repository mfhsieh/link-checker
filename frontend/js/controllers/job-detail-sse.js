/**
 * job-detail-sse.js — 任務詳情 SSE 即時串流與 30s 輪詢管理器 (ESM Controller)
 *
 * 專責處理 EventSource (SSE) 任務狀態訂閱、自動中斷判定與 30 秒定期輪詢備援機制。
 */

export class JobDetailSSEManager {
    /**
     * 初始化 JobDetailSSEManager 實例
     * @param {Object} options - 初始化配置選項
     * @param {Function} options.onMessage - 當收到 SSE 任務更新動態時的回呼函式，參數為 `jobUpdate` 物件
     * @param {Function} options.onPoll - 每 30 秒輪詢觸發時的回呼函式，參數為 `jobId`
     */
    constructor({ onMessage, onPoll }) {
        /** @type {Function} SSE 訊息處理解析回呼 */
        this.onMessage = onMessage;
        /** @type {Function} 輪詢觸發回呼 */
        this.onPoll = onPoll;
        /** @type {EventSource|null} SSE 連線實例 */
        this.eventSource = null;
        /** @type {number|null} 30 秒輪詢計時器句柄 */
        this.pollingInterval = null;
    }

    /**
     * 啟動 SSE 即時串流與背景輪詢
     * @param {string} jobId - 欲監控的任務 ID
     * @returns {void}
     */
    start(jobId) {
        this.stop();

        this.eventSource = new EventSource(`/api/jobs/${jobId}/stream`);

        if (!this.pollingInterval && typeof this.onPoll === 'function') {
            this.pollingInterval = setInterval(() => {
                this.onPoll(jobId);
            }, 30000);
        }

        this.eventSource.onmessage = (event) => {
            try {
                const jobUpdate = JSON.parse(event.data);
                if (typeof this.onMessage === 'function') {
                    this.onMessage(jobUpdate);
                }
                if (['completed', 'error', 'paused', 'pending'].includes(jobUpdate.status) && !jobUpdate.is_running) {
                    this.stop();
                }
            } catch (e) {
                console.error('Error parsing SSE data:', e);
            }
        };

        this.eventSource.onerror = (err) => {
            // console.warn('SSE connection error:', err);
        };
    }

    /**
     * 停止並關閉 SSE 串流連線與背景輪詢
     * @returns {void}
     */
    stop() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
    }
}
