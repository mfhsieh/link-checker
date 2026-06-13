/**
 * duplicate.js — 複製任務專屬頁面邏輯（ESM）
 */

import * as api from './api.js';

let _eventsBound = false;

function bindDuplicateEvents() {
    const formEl = document.getElementById('duplicate-view-form');
    if (!formEl) return;

    formEl.addEventListener('submit', (e) => {
        e.preventDefault();
        const jobSelectEl = document.getElementById('duplicate-job-select');
        const jobId = jobSelectEl.value;

        if (!jobId) return;

        // 跳轉至新增任務頁面並帶入 clone 參數
        window.location.hash = `#/new?clone=${jobId}`;
    });
}

/**
 * 初始化任務複製頁面
 * @returns {Promise<void>} 無回傳值
 */
export async function initDuplicatePage() {
    if (!_eventsBound) {
        bindDuplicateEvents();
        _eventsBound = true;
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