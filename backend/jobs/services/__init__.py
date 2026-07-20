"""
連結檢查工作之核心服務層 (Services Package) 初始化模組。

此套件封裝了外部連結檢查任務背後所有的重度業務邏輯與輔助機制，確保 API 層與底層資料操作分離。
主要包含以下模組：
- backup.py: 提供資料庫與設定檔的備份還原邏輯。
- events.py: 定義與處理任務執行過程中產生的各類系統事件。
- exporter.py: 提供將檢查結果匯出為 CSV 報表與完整 ZIP 壓縮封包的邏輯。
- external_results.py: 處理外部連結探測結果的儲存、狀態判定與歷史差異比對。
- internal_results.py: 處理內部連結抓取結果的儲存與全站統計。
- management.py: 管理工作任務的建立、擁有權轉移與生命週期狀態機。
- notifier.py: 負責任務完成後的 SMTP 郵件通知與報表夾帶發送。
- poller.py: 負責定期輪詢與監控背景處理程序的存活狀態。
- process.py: 提供背景爬蟲處理程序 (Subprocess) 的啟動、中斷與 PID 鎖定機制。
- query_utils.py: 提供共用的 SQLAlchemy 查詢過濾、分頁與排序輔助工具。
- reprobe.py: 實作針對失敗或特定連結的重新探測機制。
- scheduler.py: 處理排程任務的佇列與觸發邏輯。
"""
