# 網站連結檢查系統 (Link Checker) - 核心重構 Code Review 報告

針對近期進行的大規模程式重構（涵蓋前端模組化與爬蟲核心 `curl_cffi` 降級防護等），依據 `doc/architecture.md` 與 `doc/requirements.md` 的規範，進行了全面的程式碼審查。

以下為各面向的詳細審查結果與建議：

## 1. 程式邏輯與架構設計 (Logic & Architecture)

* **前端模組化重構未徹底落實 (TODO 15)**
  * **現狀**：雖然已抽離出多個 Web Components（如 `<link-table>`），但主控頁面 `frontend/js/job-detail.js` 與 `frontend/js/jobs.js` 仍停留在「義大利麵條式」的過渡期。檔案內部依然依賴大量模組級全域變數（如 `_currentJobId`, `_eventSource`, `_extSelectedUrls`）與扁平化的函數呼叫。
  * **建議**：這與要求中的 MVC 或嚴格封裝架構不符。建議將這兩個檔案的邏輯包裝為 Controller 類別（例如 `class JobDetailController`），將狀態封裝為實例屬性，並實作完整的 `mount()` 與 `unmount()` 生命週期方法，以便於未來擴充與避免 SPA 切換時的狀態污染。
* **事件監聽器的生命週期管理**
  * **現狀**：在 `job-detail.js` 頂層使用了 `document.addEventListener('click', ...)` 來處理按鈕點擊。雖然有利用 Event Delegation，但當網頁切換至其他模組時，這些全域監聽器並未被移除。
  * **建議**：在模組化重構時，應將事件監聽器綁定在該頁面的主要容器 DOM 上，並在離開頁面時明確解除綁定，以免造成 Memory Leak 或非預期的觸發。

## 2. 一般的爬蟲運作習慣 (Crawler Operation Habits)

* **遺漏響應式圖片與多媒體連結 (`srcset`, `<source>`)**
  * **現狀**：`crawler/core.py` 中的 `_collect_raw_links` 雖然涵蓋了 `img`, `script`, `iframe` 等標籤的 `src` 屬性，但忽略了 HTML5 響應式圖片的 `srcset` 屬性，以及 `<picture>` 或 `<video>` 內的 `<source>` 標籤。
  * **建議**：這會導致高解析度圖片或替代格式的多媒體外連成為資安稽核的漏網之魚。應擴充解析邏輯，針對 `srcset` 屬性進行字串分割（依據逗號與空格）來擷取有效網址。
* **CSS 內嵌外部資源解析**
  * **現狀**：目前的 `BeautifulSoup` 遍歷並未處理 `<style>` 標籤內的 `@import` 或行內樣式 `style="background-image: url(...)"` 中的連結。
  * **建議**：視效能與需求平衡，考慮加入輕量級的正則表達式來掃描 `url(...)` 內的外部字體或圖片連結，以提升防範失效連結劫持 (Broken Link Hijacking) 的全面性。
* **`curl_cffi` 降級機制的 Cookie 綁定**
  * **現狀**：`curl_cffi` 備援探測中，雖然成功地進行了重導向與 Cookie 收集，但 `requests.get` 回傳的 Cookie 缺乏原本 httpx 那樣精確的 Domain 屬性（代碼註解有提到 `c_dom = domain`）。
  * **影響**：這在跨子網域跳轉時可能會使 Cookie 綁定範圍縮限。雖然可以接受，但應注意這屬於底層套件差異帶來的妥協。

## 3. 一般的使用習慣與 UX (User Experience)

* **狀態過濾器的儲存機制過於僵化**
  * **現狀**：在 `job-detail.js` 中，「排除網域」的設定 (`_currentExclude`) 被保存在全域的 `localStorage` 中。這表示當使用者切換查看「任務 A」和「任務 B」時，會共用同一套排除規則。
  * **建議**：從 UX 角度來看，清單的過濾、排序狀態綁定在 URL Query String (例如 `#/jobs/123?exclude=xxx`) 會更符合使用習慣。這樣不僅能在不同任務間保持獨立，也支援使用者將當下的「篩選結果」以網址形式分享給其他團隊成員。
* **前端排序機制的數值處理**
  * **現狀**：`jobs.js` 的 `data.sort` 預設將所有內容轉為字串比較 (`String(valA).toLowerCase()`)。
  * **建議**：若未來列表中出現數值型欄位（例如：連結總數、錯誤數量），純字串比較會導致 `10` 排在 `2` 的前面。建議引入依據變數型別（數值、字串、日期）動態判斷的排序邏輯。

## 4. 資安疑慮與防護 (Security Concerns)

* **✅ SSRF 防禦與 DNS Rebinding 防護非常優秀**
  * **現狀**：`crawler/core.py` 中的 `_resolve_and_check_ssrf` 結合執行緒安全的 Monkey Patch (`socket.getaddrinfo`) 與 `curl_cffi` 的 `CurlOpt.RESOLVE`，無死角地防堵了 DNS 重綁定與內網 IP 探測攻擊。**這部分的重構完全符合最高資安標準。**
* **✅ XSS 防禦落實確實**
  * **現狀**：前端 Vanilla JS 中，如 `renderUrlNode` 和 `renderErrorMessage` 皆使用 `document.createElement` 搭配 `textContent` 進行 DOM 節點組裝，徹底阻絕了透過惡意 URL 或錯誤訊息注入腳本的風險。
* **⚠️ API 全局限速 (Rate Limiting) 仍未實作**
  * **現狀**：根據 `doc/todo.md` 項目 11，目前系統仍缺乏全局的 API 限速保護。
  * **風險**：惡意使用者若頻繁觸發 `POST /api/jobs/{id}/reprobe` 或大量請求報表匯出，將會迅速耗盡後端的執行緒池與 CPU 資源。建議在上線前務必在 FastAPI 層或反向代理層 (Nginx) 加上 Rate Limit 防護。

## 5. 註釋與文件一致性 (Comments & Documentation)

* **✅ 文件與程式碼同步良好**
  * 程式碼中包含了極高密度的 Docstrings，尤其針對 WAF 繞過機制（自動升級 HTTPS、拔除 Sec-Headers、終極 TLS 偽裝）的註釋非常詳盡，降低了未來接手開發者的維護門檻。
* **📝 TODO 清單狀態建議更新**
  * **第 13 項** (`curl_cffi` 降級破口)：程式碼確實已嚴格套用 `max_content_length` 記憶體保護、MIME 驗證與 SSRF 防護，狀態可保持 **已解決（Resolved）**。
  * **第 15 項** (導入 MVC)：目前進度僅為「UI 元件抽取」，控制層仍未模組化，建議將狀態維持在 **部分完成（Partially Completed）**，並明確標記需對 `job-detail.js` 與 `jobs.js` 進行 Class 封裝。

---

### 💡 總結

本次重構在**爬蟲核心的穩定性與資安防護上取得了卓越的成果**，妥善解決了複雜的 WAF 繞過與潛在的 SSRF 漏洞。然而，**前端架構的重構只進行了一半**，狀態管理的耦合與 SPA 的生命週期管理仍是未來的隱患。

**下一步建議優先行動**：
1. 將 `jobs.js` 與 `job-detail.js` 改寫為嚴格的 Class 架構，徹底消滅全域狀態，並妥善管理 Event Listener 的生命週期。
2. 擴充爬蟲核心，以支援解析 HTML5 的 `srcset` 屬性與 `<source>` 標籤。
3. 實作後端 API 全域限速機制 (Rate Limiting) 以防範 DoS 攻擊。
