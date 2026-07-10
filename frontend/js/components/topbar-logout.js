import { logout } from "../auth.js";
import { showConfirm } from "./confirm-modal.js";

/**
 * 頂部導覽列登出按鈕元件
 *
 * 點擊後會彈出確認對話框（優先使用 `showConfirm`，降級使用原生的 `confirm()`）。
 * 確認後呼叫 `logout()` 執行登出並清除前端 Token。
 *
 * @property {boolean} [no-confirm] - 若有設定此屬性，點擊後不會彈出確認，直接登出。
 * @property {string} [layout="compact"] - 若設定為 "compact"，則隱藏按鈕旁文字，只顯示圖示。
 */
class TopbarLogout extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  connectedCallback() {
    this.render();
  }

  render() {
    const baseStyle = document.createElement("link");
    baseStyle.rel = "stylesheet";
    baseStyle.href = "/static/css/base.css";

    const styleEl = document.createElement("style");
    styleEl.textContent = `
            .icon-logout {
                mask: url(/static/image/icon-logout.svg) no-repeat center / contain;
                -webkit-mask: url(/static/image/icon-logout.svg) no-repeat center / contain;
            }

            :host([layout="compact"]) .btn-text {
                display: none;
            }

            @media (max-width: 640px) {
                .btn-text {
                    display: none;
                }
                .btn {
                    padding: 0.5rem;
                }
            }
        `;

    const triggerBtn = document.createElement("button");
    triggerBtn.className = "btn btn-ghost btn-sm";
    triggerBtn.id = "logout-btn";
    triggerBtn.title = "登出";

    const triggerIcon = document.createElement("span");
    triggerIcon.className = "mask-icon mask-icon-btn icon-logout";

    const textSpan = document.createElement("span");
    textSpan.className = "btn-text";
    textSpan.textContent = "登出";

    triggerBtn.appendChild(triggerIcon);
    triggerBtn.appendChild(textSpan);

    this.shadowRoot.appendChild(baseStyle);
    this.shadowRoot.appendChild(styleEl);
    this.shadowRoot.appendChild(triggerBtn);

    triggerBtn.addEventListener("click", async () => {
      // 判斷是否需要確認對話框，呼叫 showConfirm
      let confirmed = false;
      const confirmMsg = "確定要登出系統嗎？";

      // 檢查是否要求無確認直接登出
      if (this.hasAttribute("no-confirm")) {
        confirmed = true;
      } else {
        confirmed = await showConfirm("登出", confirmMsg, "登出");
      }

      if (confirmed) {
        logout();
      }
    });
  }
}

customElements.define("topbar-logout", TopbarLogout);
