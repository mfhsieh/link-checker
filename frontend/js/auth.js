/**
 * auth.js — 登入、登出、首次設密頁面邏輯（ESM）
 */

import * as api from './api.js';
import { toast } from './toast.js';

// ── 密碼強度顯示 ──────────────────────────────────────────────

/** 計算密碼強度等級（0–4）*/
function calcPasswordStrength(password) {
    let score = 0;
    if (password.length >= 12) score++;
    if (/[A-Z]/.test(password)) score++;
    if (/[a-z]/.test(password)) score++;
    if (/[0-9]/.test(password)) score++;
    if (/[^A-Za-z0-9]/.test(password)) score++;
    return Math.min(score, 4);
}

function renderPasswordStrength(score) {
    const labels = ['', '弱', '普通', '良好', '強'];
    const colors = ['', '#ef4444', '#f59e0b', '#3b82f6', '#22c55e'];
    return { label: labels[score] || '', color: colors[score] || '' };
}

/**
 * 初始化密碼強度指示器
 * @param {HTMLInputElement} input - 密碼輸入框
 * @param {HTMLElement} barEl - 進度條元素
 * @param {HTMLElement} labelEl - 文字標籤元素
 */
export function initPasswordStrength(input, barEl, labelEl) {
    input.addEventListener('input', () => {
        const score = calcPasswordStrength(input.value);
        const pct = (score / 4) * 100;
        const { label, color } = renderPasswordStrength(score);

        barEl.style.width = pct + '%';
        barEl.style.background = color;
        labelEl.textContent = label;
        labelEl.style.color = color;
    });
}

// ── 登入頁面 ─────────────────────────────────────────────────

/**
 * 初始化登入頁面邏輯
 * 從 URL query params 解析首次登入用的 email + token
 */
export async function initLoginPage() {
    // 若已登入，直接跳轉主頁
    try {
        const me = await api.get('/api/auth/me', { _t: Date.now() });
        if (me && me.status === 'active') {
            window.location.replace('/app.html');
            return;
        }
        if (me && me.status === 'pending') {
            window.location.replace('/set-password.html');
            return;
        }
    } catch (_) {
        // 未登入，繼續顯示登入頁
    }

    const params = new URLSearchParams(window.location.search);
    const prefilledEmail = params.get('email') || '';
    const inviteToken = params.get('token') || '';
    const action = params.get('action') || '';

    const emailInput = document.getElementById('login-email');
    const passwordInput = document.getElementById('login-password');
    const tokenInput = document.getElementById('login-token');
    const passwordGroup = document.getElementById('password-group');
    const tokenGroup = document.getElementById('token-group');
    const loginBtn = document.getElementById('login-btn');
    const loginForm = document.getElementById('login-form');
    const errorEl = document.getElementById('login-error');
    const toggleModeBtn = document.getElementById('toggle-mode-btn');

    if (!loginForm) return;

    let isInviteMode = (action === 'invite') || (inviteToken !== '');

    if (prefilledEmail) emailInput.value = prefilledEmail;
    if (inviteToken) tokenInput.value = inviteToken;

    function renderMode() {
        errorEl.textContent = '';
        if (isInviteMode) {
            passwordGroup.style.display = 'none';
            tokenGroup.style.display = 'block';
            document.getElementById('login-mode-label').textContent = '首次登入 — 請輸入電子郵件與邀請碼';
            loginBtn.textContent = '驗證邀請並繼續';
            if (toggleModeBtn) toggleModeBtn.textContent = '已有密碼？改以密碼登入';
        } else {
            passwordGroup.style.display = 'block';
            tokenGroup.style.display = 'none';
            document.getElementById('login-mode-label').textContent = '請輸入您的帳號與密碼登入';
            loginBtn.textContent = '登入';
            if (toggleModeBtn) toggleModeBtn.textContent = '首次使用？改以邀請碼登入';
        }
    }

    renderMode();

    if (toggleModeBtn) {
        toggleModeBtn.addEventListener('click', () => {
            isInviteMode = !isInviteMode;
            renderMode();
        });
    }

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorEl.textContent = '';

        const email = emailInput.value.trim();
        const body = { email };

        if (isInviteMode) {
            const tokenVal = tokenInput.value.trim();
            if (!tokenVal) {
                errorEl.textContent = '請輸入邀請碼。';
                return;
            }
            body.token = tokenVal;
        } else {
            body.password = passwordInput.value;
        }

        loginBtn.classList.add('loading');
        loginBtn.disabled = true;

        try {
            const res = await api.post('/api/auth/login', body);
            if (res.is_first_login) {
                window.location.replace('/set-password.html');
            } else {
                window.location.replace('/app.html');
            }
        } catch (err) {
            errorEl.textContent = err.message || '登入失敗，請稍後再試。';
        } finally {
            loginBtn.classList.remove('loading');
            loginBtn.disabled = false;
        }
    });
}

// ── 首次設密頁面 ──────────────────────────────────────────────

export async function initSetPasswordPage() {
    // 確認是首次登入 Session
    try {
        const me = await api.get('/api/auth/me', { _t: Date.now() });
        // me 端點對 is_first_login Session 回傳 403
        // 若能正常取得且 status=active，說明已完成設密
        if (me && me.status === 'active') {
            window.location.replace('/app.html');
            return;
        }
    } catch (err) {
        if (err.status === 403) {
            // 正常：首次登入 Session，允許繼續
        } else {
            // 未登入
            window.location.replace('/');
            return;
        }
    }

    const form = document.getElementById('set-password-form');
    const newPwdInput = document.getElementById('new-password');
    const confirmPwdInput = document.getElementById('confirm-password');
    const submitBtn = document.getElementById('set-password-btn');
    const errorEl = document.getElementById('set-password-error');
    const strengthBar = document.getElementById('strength-bar');
    const strengthLabel = document.getElementById('strength-label');

    if (!form) return;

    if (newPwdInput && strengthBar && strengthLabel) {
        initPasswordStrength(newPwdInput, strengthBar, strengthLabel);
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorEl.textContent = '';

        if (newPwdInput.value !== confirmPwdInput.value) {
            errorEl.textContent = '兩次輸入的密碼不一致。';
            return;
        }

        submitBtn.classList.add('loading');
        submitBtn.disabled = true;

        try {
            await api.post('/api/auth/set-password', { new_password: newPwdInput.value });
            toast.success('密碼設定成功！正在跳轉...');
            setTimeout(() => window.location.replace('/app.html'), 1200);
        } catch (err) {
            errorEl.textContent = err.message || '設定密碼失敗，請重試。';
        } finally {
            submitBtn.classList.remove('loading');
            submitBtn.disabled = false;
        }
    });
}

// ── 登出 ───────────────────────────────────────────────────────

export async function logout() {
    try {
        await api.post('/api/auth/logout');
    } catch (_) {
        // 即使 API 失敗也強制跳轉
    }
    window.location.replace('/');
}

// ── 使用者狀態工具 ─────────────────────────────────────────────

/** 取得當前使用者資訊（快取版本）*/
let _cachedUser = null;

export async function getCurrentUser(forceRefresh = false) {
    if (_cachedUser && !forceRefresh) return _cachedUser;
    try {
        _cachedUser = await api.get('/api/auth/me', { _t: Date.now() });
        return _cachedUser;
    } catch (_) {
        return null;
    }
}

export function clearUserCache() {
    _cachedUser = null;
}
