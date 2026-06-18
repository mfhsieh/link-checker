/**
 * transfer.js — 任務移交專屬頁面邏輯（ESM）
 */

import * as api from './api.js';
import { toast } from './toast.js';

/** @type {boolean} 是否已綁定任務移交事件 */
let _eventsBound = false;

/**
 * 綁定任務移交相關事件
 * @returns {void}
 */
function bindTransferEvents() {
    const runBtn = document.getElementById('btn-run-transfer');
    const formEl = document.getElementById('transfer-view-form');
    if (!formEl) return;

    formEl.addEventListener('submit', async (e) => {
        e.preventDefault();

        const jobSelectEl = document.getElementById('transfer-job-select');
        const emailInputEl = document.getElementById('transfer-target-email');
        const errorEl = document.getElementById('transfer-view-error');

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
    });
}

/**
 * 初始化任務移交頁面
 * @param {string|null} preselectedJobId - (可選) 欲預設選取的任務 ID
 * @returns {Promise<void>} 無回傳值
 */
export async function initTransferPage(preselectedJobId = null) {
    if (!_eventsBound) {
        bindTransferEvents();
        _eventsBound = true;
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
        const transferableJobs = jobs.filter(j => j.status !== 'running');

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