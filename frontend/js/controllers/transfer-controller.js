/**
 * transfer-controller.js — 任務移交頁面控制器（ESM Controller）
 *
 * 封裝任務移交頁面的 API 請求與 DOM 事件互動邏輯。
 */

import * as api from '../api.js';
import { toast } from '../components/toast.js';

export class TransferController {
    /**
     * 初始化 TransferController 實例
     */
    constructor() {
        /** @type {boolean} 是否已綁定事件 */
        this.eventsBound = false;
        
        // 綁定 this 參考，以便在 addEventListener 與 removeEventListener 使用同一參照
        this.handleFormSubmit = this.handleFormSubmit.bind(this);
    }

    /**
     * 綁定任務移交相關事件
     * @returns {void}
     */
    bindTransferEvents() {
        const formEl = document.getElementById('transfer-view-form');
        if (!formEl) return;

        formEl.addEventListener('submit', this.handleFormSubmit);
    }

    /**
     * 處理表單送出事件
     * @param {Event} e - 提交事件
     * @returns {Promise<void>}
     */
    async handleFormSubmit(e) {
        e.preventDefault();

        const jobSelectEl = document.getElementById('transfer-job-select');
        const emailInputEl = document.getElementById('transfer-target-email');
        const errorEl = document.getElementById('transfer-view-error');
        const runBtn = document.getElementById('btn-run-transfer');

        const jobId = jobSelectEl.value;
        const targetEmail = emailInputEl.value.trim();

        if (!jobId || !targetEmail) return;

        runBtn.classList.add('loading');
        runBtn.disabled = true;
        errorEl.textContent = '';

        try {
            const res = await api.post(`/api/jobs/${jobId}/transfer`, { target_email: targetEmail });
            toast.success(res.message || '任務已成功移交。');
            emailInputEl.value = '';

            // 移交成功後跳轉回任務列表
            window.location.hash = '#/jobs';
        } catch (err) {
            errorEl.textContent = err.message || '移交失敗';
        } finally {
            runBtn.classList.remove('loading');
            runBtn.disabled = false;
        }
    }

    /**
     * 銷毀並清理資源，移除事件監聽器
     * @returns {void}
     */
    destroy() {
        const formEl = document.getElementById('transfer-view-form');
        if (formEl) {
            formEl.removeEventListener('submit', this.handleFormSubmit);
        }
        this.eventsBound = false;
    }

    /**
     * 初始化任務移交頁面
     * @param {string|null} preselectedJobId - (可選) 欲預設選取的任務 ID
     * @returns {Promise<void>}
     */
    async init(preselectedJobId = null) {
        if (!this.eventsBound) {
            this.bindTransferEvents();
            this.eventsBound = true;
        }

        const jobSelectEl = document.getElementById('transfer-job-select');
        const errorEl = document.getElementById('transfer-view-error');
        const runBtn = document.getElementById('btn-run-transfer');
        const emailInputEl = document.getElementById('transfer-target-email');

        if (!jobSelectEl) return;

        errorEl.textContent = '';
        emailInputEl.value = '';
        jobSelectEl.options.length = 0;
        jobSelectEl.options.add(new Option('載入中...', ''));
        runBtn.disabled = true;

        try {
            const jobs = await api.get('/api/jobs');
            const transferableJobs = jobs.filter(j => !(j.is_running || ['queued', 'starting', 'running'].includes(j.status)));

            if (transferableJobs.length === 0) {
                jobSelectEl.options.length = 0;
                jobSelectEl.options.add(new Option('無可移交的任務 (執行中的任務無法移交)', ''));
                return;
            }

            jobSelectEl.replaceChildren();
            const defaultOpt = document.createElement('option');
            defaultOpt.value = '';
            defaultOpt.textContent = '-- 請選擇任務 --';
            jobSelectEl.appendChild(defaultOpt);

            transferableJobs.forEach(j => {
                const statusStr = api.formatStatus(j.status);
                const opt = document.createElement('option');
                opt.value = j.id;
                opt.textContent = `${api.formatShortUuid(j.id)} - ${j.start_url} [${statusStr}]`;
                jobSelectEl.appendChild(opt);
            });
            runBtn.disabled = false;

            if (preselectedJobId) {
                jobSelectEl.value = preselectedJobId;
            }
        } catch (err) {
            errorEl.textContent = '無法載入任務列表：' + err.message;
        }
    }
}
