import * as api from "/static/js/api.js";
import { toast } from "/static/js/components/toast.js";
import { getCurrentUser } from "/static/js/auth.js";
import * as adminService from "/static/js/services/admin-service.js";
import { showConfirm } from "/static/js/components/confirm-modal.js";

// ── 權限驗證 ──────────────────────────────────────────────
const user = await getCurrentUser();
if (!user || user.role !== "admin") {
    window.location.replace("/app.html");
    throw new Error("Non-admin access");
}

// ── 使用者管理 ────────────────────────────────────────────
let _userSort = { key: "created_at", asc: false };
let _userColFilters = {};
let _currentUsers = [];

/**
 * 渲染使用者管理表格
 * @param {HTMLElement} container - 表格容器元素
 * @returns {void} 無回傳值
 */
function renderUsersTable(container) {
    let linkTable = container.querySelector("link-table");
    if (!linkTable) {
        container.replaceChildren();
        linkTable = document.createElement("link-table");
        linkTable.id = "admin-users-table";

        linkTable.addEventListener("sort-change", (e) => {
            _userSort = e.detail;
            renderUsersTable(container);
        });

        linkTable.addEventListener("filter-change", (e) => {
            _userColFilters[e.detail.key] = e.detail.value;
            renderUsersTable(container);
        });

        container.appendChild(linkTable);
    }

    const statusMap = {
        pending: "待設密",
        active: "正常",
        suspended: "已停用",
        expired: "已過期",
    };

    let data = [..._currentUsers];
    for (const [k, v] of Object.entries(_userColFilters)) {
        if (!v) continue;
        data = data.filter((item) => {
            let val = item[k];
            const lowerV = String(v).toLowerCase();
            if (k === "role") val = val === "admin" ? "管理員" : "使用者";
            else if (k === "status") val = statusMap[val] || val;
            else if (k === "created_at" || k === "last_login_at")
                val = api.formatLocalTime(val);
            return String(val || "")
                .toLowerCase()
                .includes(lowerV);
        });
    }

    data.sort((a, b) => {
        let valA = a[_userSort.key];
        let valB = b[_userSort.key];
        if (valA === undefined || valA === null) valA = "";
        if (valB === undefined || valB === null) valB = "";

        if (_userSort.key === "created_at" || _userSort.key === "last_login_at") {
            valA = new Date(valA).getTime() || 0;
            valB = new Date(valB).getTime() || 0;
            return _userSort.asc ? valA - valB : valB - valA;
        }
        valA = String(valA).toLowerCase();
        valB = String(valB).toLowerCase();
        if (valA < valB) return _userSort.asc ? -1 : 1;
        if (valA > valB) return _userSort.asc ? 1 : -1;
        return 0;
    });

    const headers = [
        {
            label: "電子郵件",
            key: "email",
            render: (v) => {
                const span = document.createElement("span");
                span.textContent = v;
                return span;
            },
        },
        {
            label: "角色",
            key: "role",
            render: (v) => {
                const span = document.createElement("span");
                span.className = `badge badge-${v === "admin" ? "admin" : "pending"}`;
                span.textContent = v === "admin" ? "管理員" : "使用者";
                return span;
            },
        },
        {
            label: "狀態",
            key: "status",
            render: (v) => {
                const span = document.createElement("span");
                span.className = `badge badge-${v}`;
                span.textContent = statusMap[v] || v;
                return span;
            },
        },
        {
            label: "建立時間",
            key: "created_at",
            className: "text-sm text-muted",
            render: (v) => {
                const span = document.createElement("span");
                span.textContent = api.formatLocalTime(v);
                return span;
            },
        },
        {
            label: "最後登入",
            key: "last_login_at",
            className: "text-sm text-muted",
            render: (v) => {
                const span = document.createElement("span");
                span.textContent = api.formatLocalTime(v);
                return span;
            },
        },
        {
            label: "操作",
            key: "actions",
            filterable: false,
            sortable: false,
            render: (_, u) => {
                const actionDiv = document.createElement("div");
                actionDiv.style.display = "flex";
                actionDiv.style.gap = "0.5rem";
                actionDiv.style.flexWrap = "wrap";
                const addBtn = (text, btnClass, action) => {
                    const btn = document.createElement("button");
                    btn.className = `btn btn-sm ${btnClass}`;
                    btn.textContent = text;
                    btn.dataset.action = action;
                    btn.addEventListener("click", async (e) => {
                        e.stopPropagation();
                        if (action === "promote")
                            await changeUserRole(u.id, u.email, "admin");
                        if (action === "demote")
                            await changeUserRole(u.id, u.email, "user");
                        if (action === "suspend") await suspendUser(u.id);
                        if (action === "activate") await activateUser(u.id, u.email);
                        if (action === "resend") await resendInvite(u.id, u.email);
                        if (action === "delete") await deleteUser(u.id, u.email);
                    });
                    actionDiv.appendChild(btn);
                };
                if (u.id !== user.id && u.role === "user" && u.status !== "suspended")
                    addBtn("設為管理員", "btn-secondary", "promote");
                if (u.id !== user.id && u.role === "admin")
                    addBtn("取消管理員", "btn-danger", "demote");
                if (u.status !== "suspended" && u.id !== user.id && u.role !== "admin")
                    addBtn("停用", "btn-danger", "suspend");
                if (u.status === "suspended")
                    addBtn("啟用", "btn-secondary", "activate");
                if (["pending", "expired"].includes(u.status))
                    addBtn("重寄邀請", "btn-secondary", "resend");
                if (u.id !== user.id && u.role !== "admin")
                    addBtn("刪除", "btn-danger", "delete");
                return actionDiv;
            },
        },
    ];

    linkTable.config = {
        headers,
        data,
        sort: _userSort,
        colFilters: _userColFilters,
        pagination: { current: 1, total: 1 },
        loading: false,
    };
}

/**
 * 透過 API 取得使用者列表並渲染表格，若無資料則顯示空狀態提示。
 * @returns {Promise<void>} 無回傳值
 */
async function loadUsers() {
    const container = document.getElementById("users-table-container");
    try {
        const users = await adminService.getUsers();
        if (!users || users.length === 0) {
            container.replaceChildren();
            const empty = document.createElement("div");
            empty.className = "empty-state";
            const title = document.createElement("div");
            title.className = "empty-state-title";
            title.textContent = "尚無使用者";
            empty.appendChild(title);
            container.appendChild(empty);
            return;
        }
        _currentUsers = users;
        renderUsersTable(container);
    } catch (err) {
        container.replaceChildren();
        const empty = document.createElement("div");
        empty.className = "empty-state";
        const desc = document.createElement("div");
        desc.className = "empty-state-desc text-danger";
        desc.textContent = err.message;
        empty.appendChild(desc);
        container.appendChild(empty);
    }
}

/**
 * 停用指定使用者帳號，確認後呼叫 API 並重新載入列表。
 * @param {string} userId - 使用者 ID
 * @returns {Promise<void>} 無回傳值
 */
async function suspendUser(userId) {
    const confirmed = await showConfirm(
        "⚠️ 停用帳號",
        "確定要停用此帳號？該使用者的所有 Session 將立即失效。",
        "停用",
        true,
    );
    if (!confirmed) return;
    try {
        await adminService.suspendUser(userId);
        toast.success("帳號已停用。");
        await loadUsers();
    } catch (err) {
        toast.error(err.message);
    }
}

/**
 * 啟用指定使用者帳號，確認後呼叫 API 並重新載入列表。
 * @param {string} userId - 使用者 ID
 * @param {string} email - 使用者 Email (用於顯示提示訊息)
 * @returns {Promise<void>} 無回傳值
 */
async function activateUser(userId, email) {
    const confirmed = await showConfirm(
        "⚠️ 啟用帳號",
        `確定要重新啟用帳號 ${api.escapeHtml(email)}？啟用後該使用者將可正常登入。`,
        "啟用",
        true,
    );
    if (!confirmed) return;
    try {
        await adminService.activateUser(userId);
        toast.success("帳號已重新啟用。");
        await loadUsers();
    } catch (err) {
        toast.error(err.message);
    }
}

/**
 * 變更指定使用者的權限角色，確認後呼叫 API 並重新載入列表。
 * @param {string} userId - 使用者 ID
 * @param {string} email - 使用者 Email
 * @param {'admin'|'user'} newRole - 新的角色
 * @returns {Promise<void>} 無回傳值
 */
async function changeUserRole(userId, email, newRole) {
    const isPromote = newRole === "admin";
    const roleName = isPromote ? "管理員" : "一般使用者";
    const title = isPromote ? "⚠️ 設為管理員" : "⚠️ 取消管理員";
    const msg = isPromote
        ? `確定要將帳號 ${api.escapeHtml(email)} 提權為「管理員」？這將允許其存取所有後台系統設定與操作。`
        : `確定要將帳號 ${api.escapeHtml(email)} 降權為「一般使用者」？其將立即失去後台存取權限。`;

    const confirmed = await showConfirm(title, msg, "確定變更", true);
    if (!confirmed) return;
    try {
        await adminService.changeUserRole(userId, newRole);
        toast.success(`帳號角色已變更為${roleName}。`);
        await loadUsers();
    } catch (err) {
        toast.error(err.message);
    }
}

/**
 * 重新寄送邀請信至指定使用者的 Email
 * @param {string} userId - 使用者 ID
 * @param {string} email - 使用者 Email
 * @returns {Promise<void>} 無回傳值
 */
async function resendInvite(userId, email) {
    const confirmed = await showConfirm(
        "重新寄送邀請",
        `確定要重新寄送邀請信至 ${api.escapeHtml(email)}？原本未使用的邀請碼將會立即失效。`,
        "重新寄送",
    );
    if (!confirmed) return;
    try {
        await adminService.resendInvite(userId);
        toast.success("邀請已重新寄送。");
    } catch (err) {
        toast.error(err.message);
    }
}

/**
 * 刪除指定使用者帳號及其所有關聯資料，確認後呼叫 API 並重新載入列表。
 * @param {string} userId - 使用者 ID
 * @param {string} email - 使用者 Email
 * @returns {Promise<void>} 無回傳值
 */
async function deleteUser(userId, email) {
    const confirmed = await showConfirm(
        "🚨 刪除帳號",
        `確定要刪除帳號 ${api.escapeHtml(email)}？此操作將一併刪除其所有任務資料，且無法復原。`,
        "永久刪除",
        true,
    );
    if (!confirmed) return;
    try {
        await adminService.deleteUser(userId);
        toast.success("帳號已進入刪除排程，資料將於背景清理。");
        await loadUsers();
    } catch (err) {
        toast.error(err.message);
    }
}

// 邀請新使用者
const inviteModal = document.getElementById("invite-user-modal");
const inviteForm = document.getElementById("invite-user-form");
const inviteError = document.getElementById("invite-user-error");
const inviteSubmitBtn = document.getElementById("invite-user-submit");

/**
 * 關閉邀請使用者彈出視窗，並重置表單。
 * @returns {void} 無回傳值
 */
function closeInviteModal() {
    inviteModal.style.display = "none";
    inviteForm.reset();
    inviteError.textContent = "";
}

document.getElementById("invite-user-btn").addEventListener("click", () => {
    inviteModal.style.display = "flex";
    setTimeout(() => document.getElementById("invite-email").focus(), 50);
});
document
    .getElementById("invite-user-close")
    .addEventListener("click", closeInviteModal);
document
    .getElementById("invite-user-cancel")
    .addEventListener("click", closeInviteModal);

inviteForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document
        .getElementById("invite-email")
        .value.trim()
        .toLowerCase();
    if (!email) return;

    inviteError.textContent = "";
    inviteSubmitBtn.classList.add("loading");
    inviteSubmitBtn.disabled = true;

    try {
        await adminService.inviteUser(email);
        toast.success(`邀請已寄送至 ${api.escapeHtml(email)}。`);
        closeInviteModal();
        await loadUsers();
    } catch (err) {
        inviteError.textContent = err.message || "邀請失敗。";
    } finally {
        inviteSubmitBtn.classList.remove("loading");
        inviteSubmitBtn.disabled = false;
    }
});

// ── 系統配置 ─────────────────────────────────────────────

/**
 * 載入並渲染全域爬蟲配置至表單
 * @returns {Promise<void>} 無回傳值
 */
async function loadConfig() {
    try {
        const fullConfig = await adminService.getConfig();
        const c = fullConfig.crawler || {};

        document.getElementById("cfg-timeout").value = c.timeout ?? "";
        document.getElementById("cfg-connect-timeout").value =
            c.connect_timeout ?? "";
        document.getElementById("cfg-ext-check-timeout").value =
            c.external_check_timeout ?? "";
        document.getElementById("cfg-delay").value = c.delay ?? "";
        document.getElementById("cfg-jitter-ratio").value = c.jitter_ratio ?? "";
        document.getElementById("cfg-retries").value = c.retries ?? "";
        document.getElementById("cfg-max-depth").value = c.max_depth ?? "";
        document.getElementById("cfg-max-pages").value = c.max_pages ?? "";
        document.getElementById("cfg-max-content-length").value =
            c.max_content_length ?? "";
        document.getElementById("cfg-max-redirects").value = c.max_redirects ?? "";
        const cfgUaEl = document.getElementById("cfg-user-agent");
        cfgUaEl.value = c.user_agent ?? "";
        cfgUaEl.placeholder = "預設啟動 fake-useragent 隨機輪替";
        document.getElementById("cfg-proxy-url").value = c.proxy_url ?? "";

        document.getElementById("cfg-min-timeout").value = c.min_timeout ?? "";
        document.getElementById("cfg-max-timeout").value = c.max_timeout ?? "";
        document.getElementById("cfg-min-connect-timeout").value =
            c.min_connect_timeout ?? "";
        document.getElementById("cfg-max-connect-timeout").value =
            c.max_connect_timeout ?? "";
        document.getElementById("cfg-min-ext-check-timeout").value =
            c.min_external_check_timeout ?? "";
        document.getElementById("cfg-max-ext-check-timeout").value =
            c.max_external_check_timeout ?? "";
        document.getElementById("cfg-min-delay").value = c.min_delay ?? "";
        document.getElementById("cfg-max-delay").value = c.max_delay ?? "";
        document.getElementById("cfg-min-retries").value = c.min_retries ?? "";
        document.getElementById("cfg-max-retries").value = c.max_retries ?? "";
        document.getElementById("cfg-max-max-depth").value = c.max_max_depth ?? "";
        document.getElementById("cfg-max-max-pages").value = c.max_max_pages ?? "";

        [
            "cfg-timeout",
            "cfg-connect-timeout",
            "cfg-ext-check-timeout",
            "cfg-delay",
            "cfg-jitter-ratio",
            "cfg-retries",
            "cfg-min-timeout",
            "cfg-max-timeout",
            "cfg-min-connect-timeout",
            "cfg-max-connect-timeout",
            "cfg-min-ext-check-timeout",
            "cfg-max-ext-check-timeout",
            "cfg-min-delay",
            "cfg-max-delay",
            "cfg-min-retries",
            "cfg-max-retries",
            "cfg-max-content-length",
        ].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.placeholder = "";
        });

        [
            "cfg-max-depth",
            "cfg-max-pages",
            "cfg-max-max-depth",
            "cfg-max-max-pages",
        ].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.placeholder = "無限制";
        });

        document.getElementById("cfg-ssl-exempt").value = (
            c.ssl_exempt_domains || []
        ).join("\n");
        document.getElementById("cfg-social-domains").value = (
            c.social_domains || []
        ).join("\n");
        document.getElementById("cfg-ignore-exts").value = (
            c.ignore_extensions || []
        ).join("\n");
        document.getElementById("cfg-ignore-regexes").value = (
            c.ignore_regexes || []
        ).join("\n");

        const dd = c.domain_delays || {};
        const ddLines = Object.entries(dd).map(([k, v]) => `${k}: ${v}`);
        document.getElementById("cfg-domain-delays").value = ddLines.join("\n");

        const mime = c.mime_type_filter || { enabled: true, allowed_types: [] };
        document.getElementById("cfg-mime-enabled").checked = mime.enabled;
        document.getElementById("cfg-mime-types").value = (
            mime.allowed_types || []
        ).join("\n");
    } catch (err) {
        toast.error("載入配置失敗：" + err.message);
    }
}

document
    .getElementById("config-form")
    ?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const errorEl = document.getElementById("config-error");
        errorEl.textContent = "";
        try {
            const getInt = (id) => {
                const v = document.getElementById(id).value;
                return v === "" ? null : parseInt(v, 10);
            };
            const getFloat = (id) => {
                const v = document.getElementById(id).value;
                return v === "" ? null : parseFloat(v);
            };
            const getStr = (id) => document.getElementById(id).value.trim() || null;
            const getList = (id) =>
                document
                    .getElementById(id)
                    .value.split("\n")
                    .map((s) => s.trim())
                    .filter(Boolean);

            const ddLines = getList("cfg-domain-delays");
            const domain_delays = {};
            for (const line of ddLines) {
                const parts = line.split(":");
                if (parts.length !== 2)
                    throw new Error('網域特定延遲格式錯誤，必須為 "網域: 延遲秒數"');
                const domain = parts[0].trim();
                const delay = parseFloat(parts[1].trim());
                if (isNaN(delay)) throw new Error(`網域特定延遲秒數無效: ${parts[1]}`);
                domain_delays[domain] = delay;
            }

            const crawlerConfig = {
                timeout: getInt("cfg-timeout"),
                connect_timeout: getFloat("cfg-connect-timeout"),
                external_check_timeout: getFloat("cfg-ext-check-timeout"),
                delay: getFloat("cfg-delay"),
                jitter_ratio: getFloat("cfg-jitter-ratio"),
                retries: getInt("cfg-retries"),
                max_depth: getInt("cfg-max-depth"),
                max_pages: getInt("cfg-max-pages"),
                max_content_length: getInt("cfg-max-content-length"),
                max_redirects: getInt("cfg-max-redirects"),
                user_agent: getStr("cfg-user-agent"),
                proxy_url: getStr("cfg-proxy-url"),

                min_timeout: getInt("cfg-min-timeout"),
                max_timeout: getInt("cfg-max-timeout"),
                min_connect_timeout: getFloat("cfg-min-connect-timeout"),
                max_connect_timeout: getFloat("cfg-max-connect-timeout"),
                min_external_check_timeout: getFloat("cfg-min-ext-check-timeout"),
                max_external_check_timeout: getFloat("cfg-max-ext-check-timeout"),
                min_delay: getFloat("cfg-min-delay"),
                max_delay: getFloat("cfg-max-delay"),
                min_retries: getInt("cfg-min-retries"),
                max_retries: getInt("cfg-max-retries"),
                max_max_depth: getInt("cfg-max-max-depth"),
                max_max_pages: getInt("cfg-max-max-pages"),

                ssl_exempt_domains: getList("cfg-ssl-exempt"),
                social_domains: getList("cfg-social-domains"),
                ignore_extensions: getList("cfg-ignore-exts"),
                ignore_regexes: getList("cfg-ignore-regexes"),
                domain_delays: domain_delays,

                mime_type_filter: {
                    enabled: document.getElementById("cfg-mime-enabled").checked,
                    allowed_types: getList("cfg-mime-types"),
                },
            };

            const payload = { crawler: crawlerConfig };

            const confirmed = await showConfirm(
                "⚠️ 儲存爬蟲配置",
                "確定要覆寫全域爬蟲配置嗎？這將影響所有後續建立的爬蟲任務與安全限制。",
                "確定儲存",
                true,
            );
            if (!confirmed) return;

            const btn = document.getElementById("save-config-btn");
            btn.classList.add("loading");
            btn.disabled = true;

            try {
                await adminService.saveConfig(payload);
                toast.success("配置已儲存。");

                btn.classList.remove("loading");
                btn.disabled = false;
            } catch (err) {
                errorEl.textContent = err.message;
                btn.classList.remove("loading");
                btn.disabled = false;
            }
        } catch (err) {
            errorEl.textContent = err.message;
        }
    });

// ── SMTP ─────────────────────────────────────────────────

/**
 * 載入並顯示目前 SMTP 伺服器設定狀態
 * @returns {Promise<void>} 無回傳值
 */
async function loadSmtp() {
    try {
        const smtp = await adminService.getSmtp();
        const container = document.getElementById("smtp-info-container");
        container.replaceChildren();

        const grid = document.createElement("div");
        grid.style.display = "grid";
        grid.style.gridTemplateColumns = "repeat(auto-fit,minmax(200px,1fr))";
        grid.style.gap = "1rem";

        const items = [
            ["Host", smtp.host],
            ["Port", smtp.port],
            ["TLS", smtp.use_tls ? "✓ 啟用" : "✗ 停用"],
            ["Username", smtp.username || "(未設定)"],
            ["From Name", smtp.from_name],
            ["From Email", smtp.from_email],
        ];

        items.forEach(([k, v]) => {
            const div = document.createElement("div");
            const lbl = document.createElement("div");
            lbl.className = "text-xs text-muted";
            lbl.textContent = k;
            const val = document.createElement("div");
            val.className = "text-sm font-mono";
            val.textContent = String(v);
            div.appendChild(lbl);
            div.appendChild(val);
            grid.appendChild(div);
        });

        const note = document.createElement("div");
        note.style.marginTop = "1rem";
        note.style.padding = "0.75rem";
        note.style.background = "var(--surface-overlay)";
        note.style.borderRadius = "0.375rem";
        note.style.fontSize = "0.8125rem";
        note.style.color = "var(--text-muted)";
        note.textContent = `💡 ${smtp.note}`;

        container.appendChild(grid);
        container.appendChild(note);
    } catch (err) {
        toast.error("載入 SMTP 設定失敗。");
    }
}

document
    .getElementById("smtp-test-btn")
    ?.addEventListener("click", async () => {
        const email = document.getElementById("smtp-test-email").value.trim();
        if (!email) {
            toast.warning("請填寫測試收件者 Email。");
            return;
        }

        const confirmed = await showConfirm(
            "發送測試郵件",
            `確定要發送 SMTP 測試郵件至 ${api.escapeHtml(email)} 嗎？`,
            "確定發送",
        );
        if (!confirmed) return;

        const btn = document.getElementById("smtp-test-btn");
        btn.classList.add("loading");
        btn.disabled = true;

        try {
            await adminService.testSmtp(email);
            toast.success("測試郵件已寄送成功！");
        } catch (err) {
            toast.error(err.message);
        } finally {
            btn.classList.remove("loading");
            btn.disabled = false;
        }
    });

// ── 操作日誌 ─────────────────────────────────────────────

let _logPage = 1;
let _logSort = { key: "created_at", asc: false };
let _logColFilters = {};
let _currentLogs = [];

/**
 * 渲染系統操作日誌表格
 * @param {HTMLElement} container - 表格容器元素
 * @param {Object} res - 包含 items, page, total_pages 的分頁結果
 * @returns {void} 無回傳值
 */
function renderLogsTable(container, res) {
    let linkTable = container.querySelector("link-table");
    if (!linkTable) {
        container.replaceChildren();
        linkTable = document.createElement("link-table");
        linkTable.id = "admin-logs-table";

        linkTable.addEventListener("sort-change", (e) => {
            _logSort = e.detail;
            renderLogsTable(container, res);
        });

        linkTable.addEventListener("filter-change", (e) => {
            _logColFilters[e.detail.key] = e.detail.value;
            loadLogs(1);
        });

        linkTable.addEventListener("page-change", (e) => {
            loadLogs(e.detail.page);
        });

        container.appendChild(linkTable);
    }

    let data = [..._currentLogs];
    data.sort((a, b) => {
        let valA = a[_logSort.key];
        let valB = b[_logSort.key];
        if (valA === undefined || valA === null) valA = "";
        if (valB === undefined || valB === null) valB = "";

        if (_logSort.key === "created_at") {
            valA = new Date(valA).getTime() || 0;
            valB = new Date(valB).getTime() || 0;
            return _logSort.asc ? valA - valB : valB - valA;
        }

        valA = String(valA).toLowerCase();
        valB = String(valB).toLowerCase();
        if (valA < valB) return _logSort.asc ? -1 : 1;
        if (valA > valB) return _logSort.asc ? 1 : -1;
        return 0;
    });

    const headers = [
        {
            label: "時間",
            key: "created_at",
            filterable: false,
            className: "text-xs font-mono text-muted",
            render: (v) => {
                const span = document.createElement("span");
                span.textContent = api.formatLocalTime(v);
                return span;
            },
        },
        {
            label: "事件類型",
            key: "event_type",
            render: (v) => {
                const code = document.createElement("code");
                code.style.fontSize = "0.75rem";
                code.style.color = "var(--color-brand-400)";
                code.textContent = v;
                return code;
            },
        },
        {
            label: "使用者 ID",
            key: "user_id",
            className: "text-xs font-mono text-muted",
            render: (v) => {
                const span = document.createElement("span");
                span.textContent = v || "-";
                return span;
            },
        },
        {
            label: "IP",
            key: "ip_address",
            className: "text-xs font-mono",
            render: (v) => {
                const span = document.createElement("span");
                span.textContent = v || "-";
                return span;
            },
        },
        {
            label: "詳情",
            key: "detail",
            filterable: false,
            className: "text-xs text-muted",
            render: (v) => {
                const span = document.createElement("span");
                span.textContent = v || "-";
                return span;
            },
        },
    ];

    linkTable.config = {
        headers,
        data,
        sort: _logSort,
        colFilters: _logColFilters,
        pagination: { current: res.page, total: res.total_pages },
        loading: false,
    };
}

/**
 * 透過 API 取得特定頁碼的操作日誌並進行渲染。
 * @param {number} [page=1] - 頁碼
 * @returns {Promise<void>} 無回傳值
 */
async function loadLogs(page = 1) {
    _logPage = page;
    const container = document.getElementById("logs-container");
    try {
        const res = await adminService.getLogs(page, 50, _logColFilters);
        const items = res.items || [];
        if (!items.length) {
            container.replaceChildren();
            const empty = document.createElement("div");
            empty.className = "empty-state";
            const title = document.createElement("div");
            title.className = "empty-state-title";
            title.textContent = "無日誌記錄";
            empty.appendChild(title);
            container.appendChild(empty);
            return;
        }
        _currentLogs = items;
        renderLogsTable(container, res);
    } catch (err) {
        toast.error("載入日誌失敗：" + err.message);
    }
}

// ── 任務監控 ─────────────────────────────────────────────

let _allJobSort = { key: "created_at", asc: false };
let _allJobColFilters = {};
let _currentAllJobs = [];

/**
 * 渲染系統任務監控表格（包含所有使用者的任務）
 * @param {HTMLElement} container - 表格容器元素
 * @returns {void} 無回傳值
 */
function renderAllJobsTable(container) {
    let linkTable = container.querySelector("link-table");
    if (!linkTable) {
        container.replaceChildren();
        linkTable = document.createElement("link-table");
        linkTable.id = "admin-alljobs-table";

        linkTable.addEventListener("sort-change", (e) => {
            _allJobSort = e.detail;
            renderAllJobsTable(container);
        });

        linkTable.addEventListener("filter-change", (e) => {
            _allJobColFilters[e.detail.key] = e.detail.value;
            renderAllJobsTable(container);
        });

        container.appendChild(linkTable);
    }

    const statusMap = {
        pending: "等待中",
        queued: "排隊中",
        starting: "啟動中",
        running: "執行中",
        paused: "已暫停",
        completed: "已完成",
        error: "異常",
    };

    let data = [..._currentAllJobs];
    for (const [k, v] of Object.entries(_allJobColFilters)) {
        if (!v) continue;
        data = data.filter((item) => {
            let val = item[k];
            const lowerV = String(v).toLowerCase();
            if (k === "id") {
                const ownerId = item.user_id || "匿名";
                if (
                    String(val).toLowerCase().includes(lowerV) ||
                    ownerId.toLowerCase().includes(lowerV)
                )
                    return true;
                return false;
            } else if (k === "status") val = statusMap[val] || val;
            else if (k === "created_at") val = api.formatLocalTime(val);
            return String(val || "")
                .toLowerCase()
                .includes(lowerV);
        });
    }

    data.sort((a, b) => {
        let valA = a[_allJobSort.key];
        let valB = b[_allJobSort.key];
        if (valA === undefined || valA === null) valA = "";
        if (valB === undefined || valB === null) valB = "";

        if (_allJobSort.key === "created_at") {
            valA = new Date(valA).getTime() || 0;
            valB = new Date(valB).getTime() || 0;
            return _allJobSort.asc ? valA - valB : valB - valA;
        }

        valA = String(valA).toLowerCase();
        valB = String(valB).toLowerCase();
        if (valA < valB) return _allJobSort.asc ? -1 : 1;
        if (valA > valB) return _allJobSort.asc ? 1 : -1;
        return 0;
    });

    const headers = [
        {
            label: "任務 ID / 擁有者",
            key: "id",
            render: (_, j) => {
                const divWrap = document.createElement("div");
                const divId = document.createElement("div");
                divId.style.fontWeight = "500";
                divId.style.fontSize = "0.875rem";
                divId.textContent = j.id;
                const divOwner = document.createElement("div");
                divOwner.className = "text-xs text-muted";
                divOwner.style.marginTop = "0.25rem";
                divOwner.textContent = `擁有者 ID: ${j.user_id || "匿名"}`;
                divWrap.appendChild(divId);
                divWrap.appendChild(divOwner);
                return divWrap;
            },
        },
        {
            label: "起始網址",
            key: "start_url",
            render: (_, j) => {
                if (j.user_id === user.id) {
                    const aUrl = document.createElement("a");
                    aUrl.href = `/app.html#/jobs/${j.id}`;
                    aUrl.className = "text-link";
                    aUrl.style.wordBreak = "break-all";
                    aUrl.title = "查看任務詳情";
                    aUrl.textContent = j.start_url;
                    aUrl.addEventListener("click", () => {
                        sessionStorage.setItem("jobBackPath", "/admin.html#/admin/jobs");
                    });
                    return aUrl;
                } else {
                    const divUrl = document.createElement("div");
                    divUrl.style.wordBreak = "break-all";
                    divUrl.textContent = j.start_url;
                    return divUrl;
                }
            },
        },
        {
            label: "狀態",
            key: "status",
            render: (v) => {
                const spanStatus = document.createElement("span");
                spanStatus.className = `badge badge-${v}`;
                spanStatus.textContent = statusMap[v] || v;
                return spanStatus;
            },
        },
        {
            label: "建立時間",
            key: "created_at",
            className: "text-sm text-muted",
            render: (v) => {
                const span = document.createElement("span");
                span.textContent = api.formatLocalTime(v);
                return span;
            },
        },
        {
            label: "操作",
            key: "actions",
            filterable: false,
            sortable: false,
            render: (_, j) => {
                const divActions = document.createElement("div");
                divActions.style.display = "flex";
                divActions.style.gap = "0.5rem";
                if (["running", "starting"].includes(j.status)) {
                    const btnTakeover = document.createElement("button");
                    btnTakeover.className = "btn btn-sm btn-secondary";
                    btnTakeover.textContent = "強制暫停";
                    btnTakeover.addEventListener("click", async (e) => {
                        e.stopPropagation();
                        await takeoverJob(j.id);
                    });
                    divActions.appendChild(btnTakeover);
                }
                if (["paused", "error"].includes(j.status)) {
                    const btnResume = document.createElement("button");
                    btnResume.className = "btn btn-sm btn-secondary";
                    btnResume.textContent = "強制恢復";
                    btnResume.addEventListener("click", async (e) => {
                        e.stopPropagation();
                        await resumeJob(j.id);
                    });
                    divActions.appendChild(btnResume);
                }
                if (j.user_id !== user.id) {
                    const btnRetrieve = document.createElement("button");
                    btnRetrieve.className = "btn btn-sm btn-secondary";
                    btnRetrieve.textContent = "強制取回";
                    btnRetrieve.addEventListener("click", async (e) => {
                        e.stopPropagation();
                        try {
                            await api.post(`/api/admin/jobs/${j.id}/transfer`);
                            toast.success("任務轉移成功");
                            await loadAllJobs();
                        } catch (err) {
                            toast.error("轉移失敗：" + err.message);
                        }
                    });
                    divActions.appendChild(btnRetrieve);
                }
                const btnExport = document.createElement("button");
                btnExport.className = "btn btn-sm btn-secondary";
                btnExport.textContent = "匯出備份";
                btnExport.addEventListener("click", (e) => {
                    e.stopPropagation();
                    window.location.href = `/api/admin/jobs/${j.id}/export`;
                });
                divActions.appendChild(btnExport);

                const btnDel = document.createElement("button");
                btnDel.className = "btn btn-sm btn-danger";
                btnDel.textContent = "刪除";
                btnDel.addEventListener("click", async (e) => {
                    e.stopPropagation();
                    await deleteJob(j.id);
                });
                divActions.appendChild(btnDel);
                return divActions;
            },
        },
    ];

    linkTable.config = {
        headers,
        data,
        sort: _allJobSort,
        colFilters: _allJobColFilters,
        pagination: { current: 1, total: 1 },
        loading: false,
    };
}

/**
 * 透過 API 取得系統所有任務列表並渲染，若無任務則顯示空狀態。
 * @returns {Promise<void>} 無回傳值
 */
async function loadAllJobs() {
    const container = document.getElementById("jobs-table-container");
    try {
        const jobs = await adminService.getAllJobs();
        if (!jobs || jobs.length === 0) {
            container.replaceChildren();
            const empty = document.createElement("div");
            empty.className = "empty-state";
            const title = document.createElement("div");
            title.className = "empty-state-title";
            title.textContent = "目前無任何任務";
            empty.appendChild(title);
            container.appendChild(empty);
            return;
        }
        _currentAllJobs = jobs;
        renderAllJobsTable(container);
    } catch (err) {
        container.replaceChildren();
        const empty = document.createElement("div");
        empty.className = "empty-state";
        const desc = document.createElement("div");
        desc.className = "empty-state-desc text-danger";
        desc.textContent = err.message;
        empty.appendChild(desc);
        container.appendChild(empty);
    }
}

/**
 * 強制暫停/接管指定的任務，確認後呼叫 API。
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>} 無回傳值
 */
async function takeoverJob(jobId) {
    const confirmed = await showConfirm(
        "⚠️ 強制暫停任務",
        "確定要強制暫停該任務嗎？",
        "強制暫停",
        true,
    );
    if (!confirmed) return;
    try {
        await adminService.takeoverJob(jobId);
        toast.success("任務已強制暫停。");
        await loadAllJobs();
    } catch (err) {
        toast.error(err.message);
    }
}

/**
 * 強制恢復指定的任務，確認後呼叫 API。
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>} 無回傳值
 */
async function resumeJob(jobId) {
    const confirmed = await showConfirm(
        "強制恢復任務",
        "確定要強制恢復該任務執行嗎？",
        "強制恢復",
    );
    if (!confirmed) return;
    try {
        await adminService.resumeJob(jobId);
        toast.success("任務已強制恢復執行。");
        await loadAllJobs();
    } catch (err) {
        toast.error(err.message);
    }
}

/**
 * 強制刪除指定的任務及所有關聯資料，確認後呼叫 API。
 * @param {string} jobId - 任務 ID
 * @returns {Promise<void>} 無回傳值
 */
async function deleteJob(jobId) {
    const confirmed = await showConfirm(
        "強制刪除任務",
        "確定要強制刪除該任務？此操作將清除所有關聯之佇列與外連資料，且無法復原。",
        "永久刪除",
        true,
    );
    if (!confirmed) return;
    try {
        await adminService.deleteJob(jobId);
        toast.success("任務已強制刪除。");
        await loadAllJobs();
    } catch (err) {
        toast.error(err.message);
    }
}

// ── Hash Router ───────────────────────────────────────────

const views = {
    users: "view-users",
    jobs: "view-jobs",
    config: "view-config",
    smtp: "view-smtp",
    logs: "view-logs",
};
const navItems = {
    users: "nav-users",
    jobs: "nav-jobs",
    config: "nav-config",
    smtp: "nav-smtp",
    logs: "nav-logs",
};
const loaders = {
    users: loadUsers,
    jobs: loadAllJobs,
    config: loadConfig,
    smtp: loadSmtp,
    logs: () => loadLogs(1),
};

/**
 * 處理後台 Hash Router 路由變更事件。
 * 根據 window.location.hash 切換不同的管理員視圖 (View)。
 * @returns {Promise<void>} 無回傳值
 */
async function adminRoute() {
    const hash = window.location.hash || "#/admin/users";
    const match = hash.match(/^#\/admin\/(\w+)/);
    const view = match ? match[1] : "users";

    Object.entries(views).forEach(([k, v]) => {
        document.getElementById(v).style.display = k === view ? "" : "none";
    });
    const appSidebar = document.querySelector("app-sidebar");
    if (appSidebar) {
        appSidebar.setAttribute("active-id", navItems[view] || "");
    }

    if (loaders[view]) await loaders[view]();
}

const btnImportJob = document.getElementById("btn-import-job");
const importInput = document.getElementById("import-job-input");

if (btnImportJob && importInput) {
    btnImportJob.addEventListener("click", () => {
        importInput.click();
    });
}

if (importInput) {
    importInput.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const originalText = btnImportJob.textContent;
        btnImportJob.disabled = true;
        btnImportJob.textContent = "匯入中...";

        const warnUnload = (event) => {
            event.preventDefault();
            event.returnValue = "上傳作業仍在進行中，離開此頁面將會中斷上傳。確定要離開嗎？";
            return event.returnValue;
        };
        window.addEventListener("beforeunload", warnUnload);

        const linkInterceptor = async (event) => {
            const path = event.composedPath ? event.composedPath() : [];
            const a = path.find(el => el.tagName === "A") || event.target.closest("a");
            if (!a || !a.href) return;
            // 判斷是否為換頁導航 (如果只是切換 # hash，則不攔截)
            const currentPath = window.location.origin + window.location.pathname;
            if (!a.href.startsWith(currentPath + '#') && a.href !== currentPath) {
                event.preventDefault();
                event.stopPropagation();
                const confirmed = await showConfirm(
                    "確定要離開嗎？",
                    "上傳作業仍在進行中，離開此頁面將會中斷上傳。",
                    "強制離開",
                    true
                );
                if (confirmed) {
                    window.removeEventListener("beforeunload", warnUnload);
                    document.removeEventListener("click", linkInterceptor, { capture: true });
                    window.location.href = a.href;
                }
            }
        };
        document.addEventListener("click", linkInterceptor, { capture: true });

        const formData = new FormData();
        formData.append("file", file);
        try {
            await api.upload("/api/admin/jobs/import", formData);
            toast.success("任務匯入成功");
            await loadAllJobs();
        } catch (err) {
            toast.error("任務匯入失敗：" + err.message);
        } finally {
            importInput.value = "";
            btnImportJob.disabled = false;
            btnImportJob.textContent = originalText;
            window.removeEventListener("beforeunload", warnUnload);
            document.removeEventListener("click", linkInterceptor, { capture: true });
        }
    });
}

window.addEventListener("hashchange", adminRoute);
await adminRoute();
