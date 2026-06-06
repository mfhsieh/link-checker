# 待辦功能與後續規劃 (TODO List)

以下是已實作之功能以及目前保留給未來審查並決定是否實作的延伸功能點子：

---

## 1. 已實作之功能（已完成）

* **爬取深度限制 (Granular Depth Limit)**：支援在個別任務設定中指定 `max_depth` 限制，防範爬蟲落入無限網頁鏈結的黑洞（已完成）。
* **頁面掃描上限控制 (Max Scanned Pages Control)**：支援在個別任務設定中指定 `max_pages` 上限，防止無限爬行以節約資源與頻寬（已完成）。
* **多標記外連資源與表單目的地掃描**：支援掃描並檢驗 `script`、`css`、`iframe`、`form action`、`img`、`object`、`embed` 等外部靜態資源及表單提交地址，防止 Broken Link Hijacking 供應鏈劫持與敏感個資外洩（已完成）。

---

## 2. 任務完成與異常警報通知 (Alert Notifications / Webhooks)
* **功能描述**：爬蟲執行過程可能耗時數小時，手動輪詢進度效率低。
* **規劃方案**：在全域設定檔中配置 Slack、Discord、Microsoft Teams 或 Email 通訊協議（目前 CLI 已支援載入 `webhook_url` 與環境變數機密覆寫）。任務轉換至 `completed`（完成）或 `error`（嚴重異常崩潰）時，自動發送訊息通報，並附帶尋獲的 `dead` 連結與 `broken` 連結統計。
* **狀態**：已實作機密配置讀取與覆寫邏輯，發送通知之實質功能暫緩（Pending Review）。
