import * as api from "../api.js";
import { logout, initPasswordStrength } from "../auth.js";

/**
 * 頂部導覽列修改密碼元件
 *
 * 包含一個「修改密碼」按鈕，以及對應的 Modal 表單。
 * 負責處理原密碼與新密碼的表單驗證，並發送 API 請求以完成密碼變更。
 * 成功變更後，會自動呼叫登出邏輯。
 *
 * @property {string} [layout="compact"] - 若設定為 "compact"，則隱藏按鈕旁文字，只顯示圖示。
 */
class TopbarPassword extends HTMLElement {
  /**
   * 建立 TopbarPassword 元件，並初始化 Shadow DOM
   */
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  /**
   * 當元件被加入到 DOM 時觸發，進行畫面渲染與事件綁定
   */
  connectedCallback() {
    this.render();
    this.setupEvents();
  }

  /**
   * 渲染元件的 HTML 結構與局部樣式 (Shadow DOM)
   */
  render() {
    const baseStyle = document.createElement("link");
    baseStyle.rel = "stylesheet";
    baseStyle.href = "/static/css/base.css";

    const styleEl = document.createElement("style");
    styleEl.textContent = `
            .icon-password {
                mask: url(/static/image/icon-password.svg) no-repeat center / contain;
                -webkit-mask: url(/static/image/icon-password.svg) no-repeat center / contain;
            }
       
            :host([layout="compact"]) .btn-text { display: none; }

            @media (max-width: 640px) {
                .btn-text {
                    display: none;
                }
                .btn {
                    padding: 0.5rem;
                }
            }
        `;

    // Trigger Button
    const triggerBtn = document.createElement("button");
    triggerBtn.className = "btn btn-ghost btn-sm";
    triggerBtn.id = "password-btn";
    triggerBtn.title = "修改密碼";

    const triggerIcon = document.createElement("span");
    triggerIcon.className = "mask-icon mask-icon-btn icon-password";

    const textSpan = document.createElement("span");
    textSpan.className = "btn-text";
    textSpan.textContent = "修改密碼";

    triggerBtn.appendChild(triggerIcon);
    triggerBtn.appendChild(textSpan);

    // Modal
    const modalBackdrop = document.createElement("div");
    modalBackdrop.className = "modal-backdrop";
    modalBackdrop.id = "password-modal";
    modalBackdrop.style.display = "none";

    const modalContent = document.createElement("div");
    modalContent.className = "modal";
    modalContent.style.maxWidth = "28rem";

    const modalHeader = document.createElement("div");
    modalHeader.className = "modal-header";

    const modalTitle = document.createElement("h2");
    modalTitle.className = "modal-title";
    modalTitle.textContent = "修改密碼";

    const closeBtn = document.createElement("button");
    closeBtn.className = "modal-close-btn";
    closeBtn.id = "password-close";
    closeBtn.innerHTML = '<span class="modal-close-icon"></span>';

    modalHeader.appendChild(modalTitle);
    modalHeader.appendChild(closeBtn);

    const form = document.createElement("form");
    form.id = "password-form";

    const formBody = document.createElement("div");
    formBody.className = "modal-body";

    const createInputGroup = (id, labelText, type = "password") => {
      const group = document.createElement("div");
      group.className = "form-group mb-2";
      const label = document.createElement("label");
      label.className = "form-label";
      label.setAttribute("for", id);
      label.textContent = labelText + " ";
      const req = document.createElement("span");
      req.className = "required";
      req.textContent = "*";
      label.appendChild(req);

      const input = document.createElement("input");
      input.className = "form-input";
      input.type = type;
      input.id = id;
      input.required = true;
      group.appendChild(label);
      group.appendChild(input);
      return { group, input };
    };

    const { group: currentPwdGroup } = createInputGroup(
      "current-password",
      "現有密碼",
    );

    const { group: newPwdGroup } = createInputGroup("new-password", "新密碼");
    const pwdStrengthContainer = document.createElement("div");
    pwdStrengthContainer.style.marginTop = "0.5rem";

    const progressBar = document.createElement("div");
    progressBar.className = "progress-bar";
    const pwdStrengthBar = document.createElement("div");
    pwdStrengthBar.className = "progress-fill";
    pwdStrengthBar.id = "pwd-strength-bar";
    pwdStrengthBar.style.width = "0%";
    pwdStrengthBar.style.transition = "width 0.3s, background 0.3s";
    progressBar.appendChild(pwdStrengthBar);

    const strengthLabelContainer = document.createElement("div");
    strengthLabelContainer.style.display = "flex";
    strengthLabelContainer.style.justifyContent = "space-between";
    strengthLabelContainer.style.marginTop = "0.25rem";
    const strengthHint = document.createElement("span");
    strengthHint.className = "form-hint";
    strengthHint.textContent = "密碼強度";
    const pwdStrengthLabel = document.createElement("span");
    pwdStrengthLabel.className = "form-hint";
    pwdStrengthLabel.style.fontWeight = "500";
    pwdStrengthLabel.id = "pwd-strength-label";
    pwdStrengthLabel.style.transition = "color 0.3s";

    strengthLabelContainer.appendChild(strengthHint);
    strengthLabelContainer.appendChild(pwdStrengthLabel);

    pwdStrengthContainer.appendChild(progressBar);
    pwdStrengthContainer.appendChild(strengthLabelContainer);
    newPwdGroup.appendChild(pwdStrengthContainer);

    const { group: confirmPwdGroup } = createInputGroup(
      "confirm-password",
      "確認新密碼",
    );

    const infoBox = document.createElement("div");
    infoBox.className = "pwd-rules-box";
    const infoTitle = document.createElement("div");
    infoTitle.className = "pwd-rules-title";
    infoTitle.textContent = "密碼安全要求";
    const infoList = document.createElement("ul");
    infoList.className = "pwd-rules-list";
    [
      "至少 12 個字元。",
      "至少包含大寫、小寫、數字、特殊符號中的 3 類。",
      "不得包含電子郵件帳號名稱 (@ 之前的字串) 或被包含於其中。",
    ].forEach((text) => {
      const li = document.createElement("li");
      li.textContent = text;
      infoList.appendChild(li);
    });
    infoBox.appendChild(infoTitle);
    infoBox.appendChild(infoList);

    const errorMsg = document.createElement("div");
    errorMsg.className = "form-error mt-4";
    errorMsg.id = "change-pwd-error";

    formBody.appendChild(currentPwdGroup);
    formBody.appendChild(newPwdGroup);
    formBody.appendChild(confirmPwdGroup);
    formBody.appendChild(infoBox);
    formBody.appendChild(errorMsg);

    const formFooter = document.createElement("div");
    formFooter.className = "modal-footer";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "btn btn-secondary";
    cancelBtn.id = "password-cancel";
    cancelBtn.textContent = "取消";

    const submitBtn = document.createElement("button");
    submitBtn.type = "submit";
    submitBtn.className = "btn btn-primary";
    submitBtn.id = "change-pwd-submit";
    submitBtn.textContent = "儲存修改";
    formFooter.appendChild(cancelBtn);
    formFooter.appendChild(submitBtn);

    form.appendChild(formBody);
    form.appendChild(formFooter);
    modalContent.appendChild(modalHeader);
    modalContent.appendChild(form);
    modalBackdrop.appendChild(modalContent);

    this.shadowRoot.appendChild(baseStyle);

    this.shadowRoot.appendChild(styleEl);
    this.shadowRoot.appendChild(triggerBtn);
    this.shadowRoot.appendChild(modalBackdrop);
  }

  /**
   * 綁定元件內的各項使用者互動事件與表單送出邏輯
   */
  setupEvents() {
    const btn = this.shadowRoot.getElementById("password-btn");
    const modal = this.shadowRoot.getElementById("password-modal");
    const closeBtn = this.shadowRoot.getElementById("password-close");
    const cancelBtn = this.shadowRoot.getElementById("password-cancel");
    const form = this.shadowRoot.getElementById("password-form");

    const newPwdInput = this.shadowRoot.getElementById("new-password");
    const pwdStrengthBar = this.shadowRoot.getElementById("pwd-strength-bar");
    const pwdStrengthLabel =
      this.shadowRoot.getElementById("pwd-strength-label");
    const errorEl = this.shadowRoot.getElementById("change-pwd-error");
    const submitBtn = this.shadowRoot.getElementById("change-pwd-submit");

    initPasswordStrength(newPwdInput, pwdStrengthBar, pwdStrengthLabel);

    const openModal = () => {
      modal.style.display = "flex";
      document.dispatchEvent(new CustomEvent("modal-opened"));
      form.reset();
      errorEl.textContent = "";
      pwdStrengthBar.style.width = "0%";
      pwdStrengthBar.style.background = "";
      pwdStrengthLabel.textContent = "";
    };

    const closeModal = () => {
      modal.style.display = "none";
      document.dispatchEvent(new CustomEvent("modal-closed"));
    };

    btn.addEventListener("click", openModal);
    closeBtn.addEventListener("click", closeModal);
    cancelBtn.addEventListener("click", closeModal);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const currentPwd =
        this.shadowRoot.getElementById("current-password").value;
      const newPwd = newPwdInput.value;
      const confirmPwd =
        this.shadowRoot.getElementById("confirm-password").value;

      errorEl.textContent = "";

      if (newPwd !== confirmPwd) {
        errorEl.textContent = "新密碼與確認密碼不一致。";
        return;
      }

      if (currentPwd === newPwd) {
        errorEl.textContent = "新密碼不得與現有密碼相同。";
        return;
      }

      submitBtn.classList.add("loading");
      submitBtn.disabled = true;

      try {
        await api.patch("/api/auth/password", {
          current_password: currentPwd,
          new_password: newPwd,
        });
        closeModal();
        await window.showConfirm(
          "密碼已修改",
          "密碼已修改，請使用新密碼重新登入。",
          "確定",
          false,
          true,
        );
        logout();
      } catch (err) {
        errorEl.textContent = err.message || "修改密碼失敗。";
      } finally {
        submitBtn.classList.remove("loading");
        submitBtn.disabled = false;
      }
    });
  }
}

customElements.define("topbar-password", TopbarPassword);
