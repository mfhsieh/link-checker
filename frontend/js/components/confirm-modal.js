/**
 * 系統共用確認對話框元件 (Web Component)
 * 
 * 顯示帶有標題、訊息、確認與取消按鈕的 Modal。
 * 提供 `show()` 方法回傳 Promise，用於處理非同步的使用者確認邏輯。
 * 
 * @class ConfirmModal
 * @extends {HTMLElement}
 */
class ConfirmModal extends HTMLElement {
    /**
     * 建立元件實例並附加 Shadow DOM
     */
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
    }

    /**
     * 元件掛載到 DOM 樹時觸發，負責初始化渲染
     * @returns {void}
     */
    connectedCallback() {
        this.render();
    }

    /**
     * 渲染 DOM 結構與樣式（使用原生 DOM API 避免 innerHTML）
     * @returns {void}
     */
    render() {
        const linkBaseEl = document.createElement('link');
        linkBaseEl.rel = 'stylesheet';
        linkBaseEl.href = '/static/css/base.css';

        const backdropEl = document.createElement('div');
        backdropEl.className = 'modal-backdrop';
        backdropEl.id = 'backdrop';
        backdropEl.style.display = 'none';

        const contentEl = document.createElement('div');
        contentEl.className = 'modal';

        const headerEl = document.createElement('div');
        headerEl.className = 'modal-header';

        const titleEl = document.createElement('h2');
        titleEl.id = 'title';
        titleEl.className = 'modal-title';
        titleEl.textContent = '-';

        const closeBtn = document.createElement('button');
        closeBtn.className = 'modal-close-btn';
        closeBtn.id = 'close-btn';
        closeBtn.innerHTML = '<span class="modal-close-icon"></span>';

        headerEl.appendChild(titleEl);
        headerEl.appendChild(closeBtn);

        const messageEl = document.createElement('div');
        messageEl.className = 'modal-body';
        messageEl.id = 'message';
        messageEl.textContent = '-';

        const footerEl = document.createElement('div');
        footerEl.className = 'modal-footer';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn btn-secondary';
        cancelBtn.id = 'cancel-btn';
        cancelBtn.textContent = '取消';

        const submitBtn = document.createElement('button');
        submitBtn.type = 'button';
        submitBtn.className = 'btn btn-primary';
        submitBtn.id = 'submit-btn';
        submitBtn.textContent = '確定';

        footerEl.appendChild(cancelBtn);
        footerEl.appendChild(submitBtn);

        contentEl.appendChild(headerEl);
        contentEl.appendChild(messageEl);
        contentEl.appendChild(footerEl);

        backdropEl.appendChild(contentEl);

        this.shadowRoot.appendChild(linkBaseEl);
        this.shadowRoot.appendChild(backdropEl);
    }

    /**
     * 顯示確認對話框
     * @param {string} title - 對話框標題
     * @param {string} message - 對話框訊息內容（支援 `\n` 換行）
     * @param {string} [confirmText='確定'] - 確認按鈕文字
     * @param {boolean} [isDanger=false] - 是否為危險操作（將按鈕變為紅色）
     * @param {boolean} [hideCancel=false] - 是否隱藏取消按鈕
     * @returns {Promise<boolean>} 使用者點擊確認回傳 true，取消或關閉回傳 false
     */
    show(title, message, confirmText = '確定', isDanger = false, hideCancel = false) {
        return new Promise((resolve) => {
            const backdrop = this.shadowRoot.getElementById('backdrop');
            const titleEl = this.shadowRoot.getElementById('title');
            const messageEl = this.shadowRoot.getElementById('message');
            const submitBtn = this.shadowRoot.getElementById('submit-btn');
            const cancelBtn = this.shadowRoot.getElementById('cancel-btn');
            const closeBtn = this.shadowRoot.getElementById('close-btn');

            titleEl.textContent = title;
            // 支援多行訊息，並防範 XSS
            messageEl.textContent = '';
            const lines = message.split('\n');
            lines.forEach((line, index) => {
                messageEl.appendChild(document.createTextNode(line));
                if (index < lines.length - 1) {
                    messageEl.appendChild(document.createElement('br'));
                }
            });

            submitBtn.textContent = confirmText;
            submitBtn.className = isDanger ? 'btn btn-danger' : 'btn btn-primary';
            cancelBtn.style.display = hideCancel ? 'none' : '';

            const cleanup = () => {
                submitBtn.removeEventListener('click', onConfirm);
                cancelBtn.removeEventListener('click', onCancel);
                closeBtn.removeEventListener('click', onCancel);
                backdrop.style.display = 'none';
                document.dispatchEvent(new CustomEvent('modal-closed'));
            };

            const onConfirm = () => { cleanup(); resolve(true); };
            const onCancel = () => { cleanup(); resolve(false); };

            submitBtn.addEventListener('click', onConfirm);
            cancelBtn.addEventListener('click', onCancel);
            closeBtn.addEventListener('click', onCancel);

            backdrop.style.display = 'flex';
            document.dispatchEvent(new CustomEvent('modal-opened'));
        });
    }
}

customElements.define('confirm-modal', ConfirmModal);

/**
 * 全域顯示確認對話框捷徑
 * 自動於 DOM 中尋找或建立 `<confirm-modal>` 元件並呼叫其 `show` 方法。
 * 
 * @param {string} title - 對話框標題
 * @param {string} message - 對話框訊息內容
 * @param {string} [confirmText='確定'] - 確認按鈕文字
 * @param {boolean} [isDanger=false] - 是否為危險操作
 * @param {boolean} [hideCancel=false] - 是否隱藏取消按鈕
 * @returns {Promise<boolean>}
 */
export function showConfirm(title, message, confirmText, isDanger, hideCancel) {
    let modal = document.querySelector('confirm-modal');
    if (!modal) {
        modal = document.createElement('confirm-modal');
        document.body.appendChild(modal);
    }
    return modal.show(title, message, confirmText, isDanger, hideCancel);
};
