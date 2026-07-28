/**
 * duplicate-controller.js — 複製任務頁面控制器（ESM Controller）
 *
 * 封裝複製任務頁面的 API 請求與 DOM 事件互動邏輯。
 */

import * as api from '../api.js';

export class DuplicateController {
    /**
     * 初始化 DuplicateController 實例
     */
    constructor() {
        /** @type {boolean} 是否已綁定事件 */
        this.eventsBound = false;

        // 綁定 this 參考，以便在 addEventListener 與 removeEventListener 使用同一參照
        this.handleFormSubmit = this.handleFormSubmit.bind(this);
    }

    /**
     * 綁定複製任務相關事件
     * @returns {void}
     */
    bindDuplicateEvents() {
        const formEl = document.getElementById('duplicate-view-form');
        if (!formEl) return;

        formEl.addEventListener('submit', this.handleFormSubmit);
    }

    /**
     * 處理表單送出事件
     * @param {Event} e - 提交事件
     * @returns {void}
     */
    handleFormSubmit(e) {
        e.preventDefault();
        const jobSelectEl = document.getElementById('duplicate-job-select');
        const jobId = jobSelectEl.value;

        if (!jobId) return;

        // 跳轉至新增任務頁面並帶入 clone 參數
        window.location.hash = `#/new?clone=${jobId}`;
    }

    /**
     * 銷毀並清理資源，移除事件監聽器
     * @returns {void}
     */
    destroy() {
        const formEl = document.getElementById('duplicate-view-form');
        if (formEl) {
            formEl.removeEventListener('submit', this.handleFormSubmit);
        }
        this.eventsBound = false;
    }

    /**
     * 初始化任務複製頁面
     * @returns {Promise<void>}
     */
    async init() {
        if (!this.eventsBound) {
            this.bindDuplicateEvents();
            this.eventsBound = true;
        }

        const jobSelectEl = document.getElementById('duplicate-job-select');
        const runBtn = document.getElementById('btn-run-duplicate');

        if (!jobSelectEl) return;

        jobSelectEl.options.length = 0;
        jobSelectEl.options.add(new Option('載入中...', ''));
        runBtn.disabled = true;

        try {
            const jobs = await api.get('/api/jobs');

            if (jobs.length === 0) {
                jobSelectEl.options.length = 0;
                jobSelectEl.options.add(new Option('無歷史任務可複製', ''));
                return;
            }

            jobSelectEl.replaceChildren();
            jobSelectEl.appendChild(new Option('-- 請選擇欲複製的任務 --', ''));

            jobs.forEach(j => {
                const statusStr = api.formatStatus(j.status);
                jobSelectEl.appendChild(new Option(`${api.formatShortUuid(j.id)} - ${j.start_url} [${statusStr}]`, j.id));
            });
            runBtn.disabled = false;
        } catch (err) {
            jobSelectEl.options.length = 0;
            jobSelectEl.options.add(new Option('無法載入任務列表', ''));
        }
    }
}
