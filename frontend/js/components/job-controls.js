/**
 * job-controls.js
 * 封裝任務操作按鈕的 Web Component (啟動、暫停、刪除等)
 */

export class JobControls extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._jobStatus = null;
        this._jobIsRunning = false;
        
        // Dictionary to store button references
        this.buttons = {};
    }

    connectedCallback() {
        this.render();
        this.setupEventListeners();
    }

    disconnectedCallback() {
        this.teardownEventListeners();
    }

    /**
     * @param {Object} job 任務資料 (主要需要 status 和 is_running)
     */
    set job(job) {
        if (!job) return;
        this._jobStatus = job.status;
        this._jobIsRunning = job.is_running;
        this.updateView();
    }

    /**
     * 輔助函式：建立 SVG Icon
     */
    createSVGIcon(viewBox, paths, extraStyle = {}) {
        const svgNS = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(svgNS, "svg");
        svg.setAttribute("viewBox", viewBox);
        svg.setAttribute("fill", "none");
        svg.setAttribute("stroke", "currentColor");
        svg.setAttribute("stroke-width", "2");
        
        Object.assign(svg.style, {
            width: "14px",
            height: "14px",
            marginRight: "0.25rem",
            verticalAlign: "text-bottom"
        }, extraStyle);

        paths.forEach(p => {
            const pathNode = document.createElementNS(svgNS, "path");
            Object.entries(p).forEach(([key, val]) => {
                pathNode.setAttribute(key, val);
            });
            svg.appendChild(pathNode);
        });

        return svg;
    }

    /**
     * 輔助函式：建立按鈕
     */
    createButton(id, className, title, text, svgIcon) {
        const btn = document.createElement('button');
        btn.id = id;
        btn.className = className;
        btn.title = title;
        btn.style.display = 'none'; // Default hidden until status is evaluated

        if (svgIcon) {
            btn.appendChild(svgIcon);
        }
        btn.appendChild(document.createTextNode(text));
        
        this.buttons[id] = btn;
        return btn;
    }

    render() {
        // 嚴格遵守資安規範：禁止使用 innerHTML，全面改用 document.createElement
        const linkBase = document.createElement('link');
        linkBase.rel = 'stylesheet';
        linkBase.href = '/static/css/base.css';
        
        const linkComponents = document.createElement('link');
        linkComponents.rel = 'stylesheet';
        linkComponents.href = '/static/css/components.css';

        this.shadowRoot.appendChild(linkBase);
        this.shadowRoot.appendChild(linkComponents);

        const style = document.createElement('style');
        style.textContent = `
            :host { display: flex; gap: 0.75rem; flex-wrap: wrap; }
        `;
        this.shadowRoot.appendChild(style);

        const container = document.createElement('div');
        container.style.display = 'flex';
        container.style.gap = '0.75rem';
        container.style.flexWrap = 'wrap';

        // Duplicate
        container.appendChild(this.createButton('btn-duplicate-job', 'btn btn-secondary btn-sm', '複製此任務的設定並建立新任務', '複製', 
            this.createSVGIcon('0 0 24 24', [
                { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'd': 'M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2' }
            ])
        ));

        // Compare
        container.appendChild(this.createButton('btn-goto-compare', 'btn btn-secondary btn-sm', '跳轉至比對視圖，並將此任務設為基準', '比對', 
            this.createSVGIcon('0 0 24 24', [
                { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'd': 'M12 3v17.25m0 0c-1.472 0-2.882.265-4.185.75M12 20.25c1.472 0 2.882.265 4.185.75M18.75 4.97A48.416 48.416 0 0012 4.5c-2.291 0-4.545.16-6.75.47m13.5 0c1.01.143 2.01.317 3 .52m-3-.52l2.62 10.726c.122.499-.106 1.028-.589 1.202a5.988 5.988 0 01-2.031.352 5.988 5.988 0 01-2.031-.352c-.483-.174-.711-.703-.59-1.202L18.75 4.971zm-16.5.52c.99-.203 1.99-.377 3-.52m0 0l2.62 10.726c.122.499-.106 1.028-.589 1.202a5.989 5.989 0 01-2.031.352 5.989 5.989 0 01-2.031-.352c-.483-.174-.711-.703-.59-1.202L5.25 4.971z' }
            ])
        ));

        // Transfer
        container.appendChild(this.createButton('btn-transfer-job', 'btn btn-secondary btn-sm', '將此任務移交給其他帳號', '移交', 
            this.createSVGIcon('0 0 24 24', [
                { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'd': 'M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5' }
            ])
        ));

        // Start
        const svgStart = this.createSVGIcon('0 0 20 20', [
            { 'd': 'M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z' }
        ], { fill: 'currentColor', stroke: 'none' });
        container.appendChild(this.createButton('btn-start-job', 'btn btn-primary btn-sm', '開始或繼續執行爬蟲任務', '啟動', svgStart));

        // Pause
        const svgPause = this.createSVGIcon('0 0 20 20', [
            { 'd': 'M5.75 3a.75.75 0 00-.75.75v12.5c0 .414.336.75.75.75h1.5a.75.75 0 00.75-.75V3.75A.75.75 0 007.25 3h-1.5zM12.75 3a.75.75 0 00-.75.75v12.5c0 .414.336.75.75.75h1.5a.75.75 0 00.75-.75V3.75a.75.75 0 00-.75-.75h-1.5z' }
        ], { fill: 'currentColor', stroke: 'none' });
        container.appendChild(this.createButton('btn-pause-job', 'btn btn-secondary btn-sm', '暫停執行中的任務', '暫停', svgPause));

        // Reset
        container.appendChild(this.createButton('btn-reset-job', 'btn btn-secondary btn-sm', '清除所有紀錄與外連結果，將任務退回初始狀態', '重置', 
            this.createSVGIcon('0 0 24 24', [
                { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'd': 'M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3' }
            ])
        ));

        // Retry Failed
        container.appendChild(this.createButton('btn-retry-failed-job', 'btn btn-secondary btn-sm', '重試爬取失敗連結', '重試', 
            this.createSVGIcon('0 0 24 24', [
                { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'd': 'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99' }
            ])
        ));

        // Delete
        container.appendChild(this.createButton('btn-delete-job', 'btn btn-danger btn-sm', '永久刪除此任務及其所有關聯資料', '刪除', 
            this.createSVGIcon('0 0 24 24', [
                { 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'd': 'M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0' }
            ])
        ));

        this.shadowRoot.appendChild(container);
    }

    updateView() {
        if (!this._jobStatus) return;
        
        // Hide all first
        Object.values(this.buttons).forEach(btn => btn.style.display = 'none');

        // Always show duplicate, transfer, delete
        this.buttons['btn-duplicate-job'].style.display = 'inline-flex';
        this.buttons['btn-transfer-job'].style.display = 'inline-flex';
        this.buttons['btn-delete-job'].style.display = 'inline-flex';

        // Compare button logic
        if (this._jobStatus === 'completed') {
            this.buttons['btn-goto-compare'].style.display = 'inline-flex';
        }

        // Execution control logic
        if (this._jobIsRunning) {
            this.buttons['btn-pause-job'].style.display = 'inline-flex';
        } else {
            if (['pending', 'paused', 'error'].includes(this._jobStatus)) {
                this.buttons['btn-start-job'].style.display = 'inline-flex';
                
                // Change text contextually
                if (this._jobStatus === 'paused') {
                    this.buttons['btn-start-job'].childNodes.forEach(n => {
                        if (n.nodeType === Node.TEXT_NODE) n.textContent = ' 恢復';
                    });
                } else {
                    this.buttons['btn-start-job'].childNodes.forEach(n => {
                        if (n.nodeType === Node.TEXT_NODE) n.textContent = ' 啟動';
                    });
                }
            }

            if (this._jobStatus === 'completed') {
                this.buttons['btn-retry-failed-job'].style.display = 'inline-flex';
            }

            if (['completed', 'error', 'paused'].includes(this._jobStatus)) {
                this.buttons['btn-reset-job'].style.display = 'inline-flex';
            }
        }
    }

    setupEventListeners() {
        this.buttons['btn-start-job'].addEventListener('click', () => this.dispatchEvent(new CustomEvent('job-start', { bubbles: true, composed: true })));
        this.buttons['btn-pause-job'].addEventListener('click', () => this.dispatchEvent(new CustomEvent('job-pause', { bubbles: true, composed: true })));
        this.buttons['btn-reset-job'].addEventListener('click', () => this.dispatchEvent(new CustomEvent('job-reset', { bubbles: true, composed: true })));
        this.buttons['btn-retry-failed-job'].addEventListener('click', () => this.dispatchEvent(new CustomEvent('job-retry', { bubbles: true, composed: true })));
        this.buttons['btn-delete-job'].addEventListener('click', () => this.dispatchEvent(new CustomEvent('job-delete', { bubbles: true, composed: true })));
        this.buttons['btn-duplicate-job'].addEventListener('click', () => this.dispatchEvent(new CustomEvent('job-duplicate', { bubbles: true, composed: true })));
        this.buttons['btn-goto-compare'].addEventListener('click', () => this.dispatchEvent(new CustomEvent('job-compare', { bubbles: true, composed: true })));
        this.buttons['btn-transfer-job'].addEventListener('click', () => this.dispatchEvent(new CustomEvent('job-transfer', { bubbles: true, composed: true })));
    }

    teardownEventListeners() {
        // Events are attached to elements which will be garbage collected if node is removed
    }
}

customElements.define('job-controls', JobControls);
