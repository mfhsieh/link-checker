/**
 * auth-reset.js — 忘記密碼與重設密碼邏輯（ESM）
 */

import * as api from './api.js';
import { toast } from './components/toast.js';
import { initPasswordStrength } from './auth.js';

/**
 * 初始化忘記密碼頁面
 * @returns {void}
 */
export function initForgotPasswordPage() {
    const formEl = document.getElementById('forgot-password-form');
    const emailInput = document.getElementById('forgot-email');
    const submitBtn = document.getElementById('forgot-password-btn');
    const errorEl = document.getElementById('forgot-password-error');
    const successEl = document.getElementById('forgot-password-success');

    if (!formEl) return;

    formEl.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorEl.textContent = '';
        successEl.style.display = 'none';

        const email = emailInput.value.trim();
        if (!email) {
            errorEl.textContent = '請輸入電子郵件信箱。';
            return;
        }

        submitBtn.classList.add('loading');
        submitBtn.disabled = true;

        try {
            const res = await api.post('/api/auth/forgot-password', { email });
            successEl.textContent = res.message || '請檢查您的收件匣。';
            successEl.style.display = 'block';
            emailInput.value = '';
        } catch (err) {
            errorEl.textContent = err.message || '發生錯誤，請稍後再試。';
        } finally {
            submitBtn.classList.remove('loading');
            submitBtn.disabled = false;
        }
    });
}

/**
 * 初始化重設密碼頁面
 * @returns {void}
 */
export function initResetPasswordPage() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (!token) {
        window.location.replace('/');
        return;
    }

    const formEl = document.getElementById('reset-password-form');
    const newPwdInput = document.getElementById('new-password');
    const confirmPwdInput = document.getElementById('confirm-password');
    const submitBtn = document.getElementById('reset-password-btn');
    const errorEl = document.getElementById('reset-password-error');
    const strengthBarEl = document.getElementById('strength-bar');
    const strengthLabelEl = document.getElementById('strength-label');

    if (newPwdInput && strengthBarEl && strengthLabelEl) {
        initPasswordStrength(newPwdInput, strengthBarEl, strengthLabelEl);
    }

    formEl.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorEl.textContent = '';
        if (newPwdInput.value !== confirmPwdInput.value) {
            errorEl.textContent = '兩次輸入的密碼不一致。';
            return;
        }
        submitBtn.classList.add('loading');
        submitBtn.disabled = true;

        try {
            await api.post('/api/auth/reset-password', { token, new_password: newPwdInput.value });
            toast.success('密碼重設成功！正在跳轉...');
            setTimeout(() => window.location.replace('/'), 1500);
        } catch (err) {
            errorEl.textContent = err.message || '重設密碼失敗，連結可能已失效。';
        } finally {
            submitBtn.classList.remove('loading');
            submitBtn.disabled = false;
        }
    });
}