# 前端 JavaScript 程式風格與開發規範 (JS Coding Style Guide)

為了確保「外部連結檢查系統」前台與後台網頁介面的安全性、效能與可維護性，本專案前端程式碼必須嚴格遵守以下基於 Vanilla JS 的開發規範。

## 1. 核心技術選型與模組化 (Vanilla JS & ESM)

* **純原生技術棧**：全站強制使用 **Vanilla JS** 與 **Vanilla CSS**，嚴禁引入 React、Vue、Angular、jQuery 等任何前端框架或 DOM 操作函式庫。
* **ES Modules (ESM)**：所有 JavaScript 檔案必須以 ES6 模組標準撰寫，並在 HTML 中以 `<script type="module">` 載入。
* **獨立檔案拆分**：各個功能區塊（如 `auth.js`, `api.js`, `jobs.js`）應拆分為獨立檔案，透過 `import` / `export` 互相引用，無需使用 Webpack 或 Vite 等打包工具 (Bundler)。

## 2. DOM 操作與 XSS 防禦安全規範 (DOM & XSS Prevention)

前端負責將後端 API 回傳的資料渲染至畫面上，防範跨網站指令碼攻擊 (XSS) 是最高指導原則：

* **禁止使用 `innerHTML` 渲染未受信任資料**：絕對禁止將任何來自 API、使用者輸入、或 URL 參數的資料直接透過 `innerHTML` 或 `insertAdjacentHTML` 寫入 DOM 中。
* **文字渲染**：若僅需顯示文字，必須使用 `element.textContent = data;`。
* **動態 HTML 渲染**：若必須動態產生 HTML 結構（例如表格），必須對所有變數強制呼叫 `escapeHtml()` 進行實體跳脫處理。

**範例：**
```javascript
// ❌ 錯誤示範（具 XSS 風險）
element.innerHTML = `<div>${user.name}</div>`;

// ✅ 正確示範 1：使用 textContent
element.textContent = user.name;

// ✅ 正確示範 2：使用跳脫函式
function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = String(s || '');
    return d.innerHTML;
}
element.innerHTML = `<div>${escapeHtml(user.name)}</div>`;
```

## 3. 網路請求與 API 封裝 (API Calls)

* **統一請求入口**：所有對後端發起的 HTTP 請求（GET, POST, PATCH, DELETE）必須統一透過 `frontend/js/api.js` 中封裝的模組發送，嚴禁在個別頁面直接呼叫原生的 `fetch()`。
* **自動處理憑證與 CSRF**：`api.js` 會自動處理 `X-CSRF-Token` 的附加、JSON 的序列化與反序列化。
* **全域 401 攔截**：若後端回傳 401 Unauthorized，`api.js` 會自動攔截並重導向至登入頁面，各頁面無需重複撰寫驗證失效的處理邏輯。

## 4. 異步處理與錯誤捕捉 (Async/Await & Error Handling)

* **全面採用 `async` / `await`**：禁止使用傳統的 `.then().catch()` 回呼地獄 (Callback Hell)。
* **UI 狀態反饋**：在發送 API 請求前，必須設定按鈕的載入狀態（如 `btn.classList.add('loading')` 與 `disabled = true`）；請求結束後（不論成功或失敗），必須在 `finally` 區塊中解除載入狀態。
* **統一錯誤提示**：所有被捕獲的例外錯誤，應透過 `toast.error(err.message)` 統一顯示給使用者，不應使用原生 `alert()`。

## 5. 變數與函式命名規範 (Naming Conventions)

* **變數與函式**：使用小駝峰式命名 (`camelCase`)。
* **常數**：使用大寫蛇形命名 (`UPPER_SNAKE_CASE`)，例如 `const MAX_RETRY_COUNT = 3;`。
* **私有/內部變數**：不對外 export 或僅限內部狀態使用的變數，應以底線開頭 (`_privateVar`)。
* **DOM 元素選取**：儲存 DOM 元素的變數建議以 `El` (Element) 或 `Btn` / `Input` 等明確後綴結尾，例如 `const submitBtn = document.getElementById('submit');`。

## 6. 註解與 JSDoc 規範 (Comments & JSDoc)

* **JSDoc 註解**：所有的重要函式（特別是對外 `export` 的 API、工具函式或共用邏輯），都必須加上符合 JSDoc 標準的註解塊。
* **型別標註**：透過 `@param` 與 `@returns` 明確標示傳入參數與回傳值的資料型別與用途，以彌補 Vanilla JS 缺乏靜態型別檢查的不足，並大幅提升編輯器（如 VSCode）的 IntelliSense 自動完成提示體驗。

**範例：**
```javascript
/**
 * 顯示 Toast 通知
 * @param {string} message - 訊息內容
 * @param {'success'|'warning'|'error'|'info'} [type='info'] - 通知類型
 * @param {number} [duration=4000] - 自動消失時間（毫秒），0 表示不自動消失
 */
export function showToast(message, type = 'info', duration = 4000) {
    // ...
}
```

## 7. 第三方套件引入原則

* 原則上**不引入任何第三方前端套件**。
* 若確有業務需求（如複雜圖表渲染），必須經架構審查同意，且禁止透過公共 CDN 動態載入未鎖定版本之資源，以防堵供應鏈攻擊。若要使用 CDN，必須明確綁定版本號並加入 `integrity` (SRI Hash) 屬性。