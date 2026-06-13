# 爬蟲引擎參數設定指南 (Crawler Parameters Guide)

本系統的爬蟲引擎設計具備高度彈性，共提供 **21 個** 可供配置的參數。其中 19 個參數能在建立「個別爬蟲任務 (`job/*.yaml`)」時精確指定，另外 2 個為系統級核心防護限制，僅能於「全域設定檔 (`config/config_global.yaml`)」中配置。

---

## 1. 核心任務定義 (建立任務必填)

這三個參數定義了爬蟲「從哪裡開始」以及「該往哪裡走」。

* **`start_url`** (字串)：爬蟲的起始網址。
* **`target_domains`** (字串陣列)：允許爬蟲深入遍歷的目標網域清單。例如：`["example.com", "blog.example.com"]`。
* **`trusted_domains`** (字串陣列)：被視為自家系統或可信任的網域清單。用來判斷抓到的連結是不是「外部連結」。

---

## 2. 連線與超時控制 (防護與禮貌機制)

這組參數用來控制爬蟲的請求頻率，並防止被惡意伺服器 (Tarpit 焦油坑) 卡死。

* **`timeout`** (整數)：抓取完整網頁的總超時時間 (預設 30 秒)。
* **`connect_timeout`** (浮點數)：建立 TCP 連線的超時時間，專門防禦惡意不回應的伺服器 (預設 5.0 秒)。
* **`external_check_timeout`** (浮點數)：外部連結存活探測 (HEAD/GET) 的總超時時間 (預設 10.0 秒)。
* **`delay`** (浮點數)：每次發送 HTTP 請求前的等待延遲時間，避免對目標伺服器造成 DDoS (預設 3.0 秒)。
* **`jitter_ratio`** (浮點數)：請求延遲與退避的隨機抖動比例，用以防範行為分析 (預設 0.2，代表 ±20% 抖動)。
* **`domain_delays`** (字典)：針對「特定網域」客製化的專屬延遲時間。支援最長匹配優先原則 (例如要求遇到 `google.com` 時延遲 5 秒)。
* **`retries`** (整數)：遇到暫時性錯誤 (如 HTTP 503 或 Timeout) 時的最大重試次數，內建指數退避演算法 (預設 3 次)。

---

## 3. 資源與限制 (防禦死循環陷阱)

防止爬蟲陷入無限迴圈 (Crawl Trap) 的硬性限制。

* **`max_depth`** (整數 | null)：最大爬取深度。例如設為 2，代表只爬起始頁，以及起始頁點進去的第一層連結。預設為 `null` (無限制)。
* **`max_pages`** (整數 | null)：最大抓取頁數。當實質下載的網頁數量達到此上限時，任務會強制且優雅地結束。預設為 `null` (無限制)。
* **`max_content_length`** (整數)：最大允許下載的網頁容量 (Bytes)。這是保護系統記憶體的硬性限制 (防禦 OOM 崩潰)，**僅限全域設定配置**，個別任務無法覆寫 (預設 10MB)。
* **`max_redirects`** (整數)：HTTP 重導向追蹤次數上限。避免陷入惡意轉址迴圈，**僅限全域設定配置**，個別任務無法覆寫 (預設 10 次)。

---

## 4. 過濾與排除 (節省頻寬與時間)

告訴爬蟲什麼連結與檔案「不要」碰。

* **`ignore_extensions`** (字串陣列)：略過不抓取的副檔名清單 (預設包含 `.pdf`, `.zip`, `.jpg`, `.mp4` 等非網頁檔案)。
* **`ignore_regexes`** (字串陣列)：略過不抓取的路徑正規表示式 (Regex)。例如設定 `^https://example\.com/logout` 以避免爬蟲觸發登出連結。
* **`mime_type_filter`** (字典)：MIME 類型過濾器。爬蟲發送請求後會先檢查回應標頭 (Content-Type)，預設只下載 `text/html` 與 `application/xhtml+xml`，若為其他媒體檔案則直接中斷下載以節省頻寬。

---

## 5. 偽裝與網路穿透 (防禦反爬蟲機制)

提高爬蟲存活率與降低被目標網站的 WAF (網頁應用程式防火牆) 阻擋的機率。

* **`user_agent`** (字串 | null)：自訂 HTTP 請求的 User-Agent 標頭。若未設定 (null)，系統將自動啟用高擬真動態瀏覽器特徵產生器，隨機配置真實的現代 User-Agent 與專屬 HTTP 標頭。
* **`proxy_url`** (字串 | null)：代理伺服器網址 (例如 `http://user:pass@proxy.example.com:8080`)。若需隱藏爬蟲真實 IP 時設定。基於機密保護，強烈建議將此帶有密碼之設定置於環境變數 `CRAWLER_PROXY_URL` 中。
* **`ssl_exempt_domains`** (字串陣列)：豁免 SSL 憑證驗證的網域清單。對於使用「自簽憑證」的內部測試網域，加入此清單可避免因憑證無效而誤判為失效連結。
* **`social_domains`** (字串陣列)：允許降級為帶有 Range 標頭之 GET 請求的社群或反爬蟲網域清單。用以避免大型社群平台誤判為失效連結 (預設包含 facebook.com, youtube.com 等)。

---

## 💡 進階知識：全域防呆限制 (Global Limits)

除了在建立個別任務時設定這些參數外，系統管理員可以在全域設定檔 (`config/config_global.yaml`) 中設定**全域預設值**以及**安全上下限**，例如：

* `min_timeout` / `max_timeout`
* `min_connect_timeout` / `max_connect_timeout`
* `min_external_check_timeout` / `max_external_check_timeout`
* `min_delay` / `max_delay`
* `min_retries` / `max_retries`
* `max_max_depth` (當任務的深度設為無限制時，強制套用此最大深度)
* `max_max_pages` (當任務的頁數設為無限制時，強制套用此最大頁數)

**防禦機制運作方式**：
如果使用者在建立個別任務時，設定的 `delay` 為 `0.1` 秒，但全域設定的 `min_delay` 為 `1.0` 秒，系統會在任務啟動前，自動將該任務的 `delay` 強制修正回 `1.0` 秒。此機制可有效保障系統與目標伺服器的整體安全！