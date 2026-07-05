import * as api from "/static/js/api.js";
import { toast } from "/static/js/components/toast.js";
import { getCurrentUser } from "/static/js/auth.js";
import { renderJobList } from "/static/js/jobs.js";
import {
    initJobDetailPage,
    destroyJobDetailPage,
} from "/static/js/job-detail.js";
import { initComparePage } from "/static/js/compare.js";
import { initTransferPage } from "/static/js/transfer.js";
import { initDuplicatePage } from "/static/js/duplicate.js";
import * as jobService from "/static/js/services/job-service.js";

// ── 初始化使用者資訊 ──────────────────────────────────────
/**
 * 載入當前登入的使用者資訊，若未登入則重導向至登入頁面。
 * 若使用者為管理員角色，則在側邊欄啟用管理員模式。
 * @returns {Promise<void>} 無回傳值
 */
async function initUser() {
    const user = await getCurrentUser();
    if (!user) {
        window.location.replace("/");
        return;
    }

    if (appSidebar && user.role === "admin") {
        appSidebar.setAttribute("is-admin", "true");
    }
}

// ── Hash-based SPA Router ─────────────────────────────────
const viewJobs = document.getElementById("view-jobs");
const viewDetail = document.getElementById("view-job-detail");
const viewCreate = document.getElementById("view-create-job");
const viewHelp = document.getElementById("view-help");
const viewCompare = document.getElementById("view-compare");
const viewTransfer = document.getElementById("view-transfer");
const viewDuplicate = document.getElementById("view-duplicate");
const appSidebar = document.querySelector("app-sidebar");

let _hasCheckedInitialJobs = false;

/**
 * 透過 API 取得任務列表，並呼叫 jobs.js 的 renderJobList 進行渲染。
 * 若為首次載入且無任何任務，則自動跳轉至說明與教學頁面。
 * @returns {Promise<void>} 無回傳值
 */
async function loadJobsList() {
    try {
        const jobs = await api.get("/api/jobs");

        if (!_hasCheckedInitialJobs) {
            _hasCheckedInitialJobs = true;
            if (
                jobs.length === 0 &&
                (!window.location.hash ||
                    window.location.hash === "#/jobs" ||
                    window.location.hash === "#")
            ) {
                window.location.href = "/help.html";
                return;
            }
        }

        renderJobList(jobs, document.getElementById("jobs-list-container"));
    } catch (err) {
        toast.error("無法載入任務列表：" + err.message);
    }
}

// ── 預設清單 Modal 邏輯 ───────────────────────────────────
const defaultListModal = document.getElementById("default-list-modal");
/**
 * 顯示唯讀的清單彈出視窗 (Modal)
 * @param {string} title - 彈出視窗的標題
 * @param {string} content - 欲顯示的多行文字內容
 * @returns {void} 無回傳值
 */
function showDefaultListModal(title, content) {
    if (!defaultListModal) return;
    document.getElementById("default-list-title").textContent = title;
    document.getElementById("default-list-display").value = content;
    defaultListModal.style.display = "flex";
}
document
    .getElementById("default-list-close")
    ?.addEventListener("click", () => (defaultListModal.style.display = "none"));
document
    .getElementById("default-list-ok")
    ?.addEventListener("click", () => (defaultListModal.style.display = "none"));

let _globalDefaultConfig = null;
let _isDefaultsLoaded = false;
/**
 * 載入全域預設配置，並填充至新建任務表單中的對應欄位，
 * 同時設定輸入框的 placeholder 與範圍限制。
 * @returns {Promise<void>} 無回傳值
 */
async function loadJobDefaults() {
    if (_isDefaultsLoaded) return;
    try {
        // 加上時間戳記強迫瀏覽器不使用快取
        const config = await jobService.getDefaultConfig();
        if (!config) return;
        _globalDefaultConfig = config;

        const setField = (id, val, min, max) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (val !== undefined && val !== null) {
                el.value = Array.isArray(val) ? val.join("\n") : val;
                el.defaultValue = el.value;
            } else {
                el.value = "";
                el.defaultValue = "";
            }
            if (min !== undefined && min !== null) el.min = min;
            if (max !== undefined && max !== null) el.max = max;
            if (
                min !== undefined &&
                min !== null &&
                max !== undefined &&
                max !== null
            ) {
                el.placeholder = `${min} ~ ${max}`;
            } else if (min !== undefined && min !== null) {
                el.placeholder = `${min} ~ 無限制`;
            }
        };

        const extEl = document.getElementById("job-ignore-exts");
        if (extEl) extEl.placeholder = ".pdf\n.zip";
        const btnViewExts = document.getElementById("btn-view-exts");
        if (btnViewExts && config.ignore_extensions?.length) {
            btnViewExts.style.display = "inline-block";
            btnViewExts.addEventListener("click", () => {
                showDefaultListModal(
                    "預設忽略的副檔名 (唯讀)",
                    config.ignore_extensions.join("\n"),
                );
            });
        }

        const regexEl = document.getElementById("job-ignore-regexes");
        if (regexEl) regexEl.placeholder = "^https://example\\.com/logout";
        const btnViewRegexes = document.getElementById("btn-view-regexes");
        if (btnViewRegexes && config.ignore_regexes?.length) {
            btnViewRegexes.style.display = "inline-block";
            btnViewRegexes.addEventListener("click", () => {
                showDefaultListModal(
                    "預設攔截路徑規則 (唯讀)",
                    config.ignore_regexes.join("\n"),
                );
            });
        }

        const uaEl = document.getElementById("job-user-agent");
        if (uaEl) {
            uaEl.value = "";
            uaEl.defaultValue = "";
            uaEl.placeholder = config.user_agent
                ? config.user_agent
                : "預設啟動 fake-useragent 隨機輪替";
        }

        const sslEl = document.getElementById("job-ssl-exempt");
        if (sslEl) sslEl.placeholder = "example.com";
        const btnViewSsl = document.getElementById("btn-view-ssl");
        if (btnViewSsl && config.ssl_exempt_domains?.length) {
            btnViewSsl.style.display = "inline-block";
            btnViewSsl.addEventListener("click", () => {
                showDefaultListModal(
                    "預設自簽憑證豁免網域 (唯讀)",
                    config.ssl_exempt_domains.join("\n"),
                );
            });
        }

        const socialEl = document.getElementById("job-social-domains");
        if (socialEl) socialEl.placeholder = "facebook.com";
        const btnViewSocial = document.getElementById("btn-view-social");
        if (btnViewSocial && config.social_domains?.length) {
            btnViewSocial.style.display = "inline-block";
            btnViewSocial.addEventListener("click", () => {
                showDefaultListModal(
                    "預設社群與反爬蟲網域 (唯讀)",
                    config.social_domains.join("\n"),
                );
            });
        }

        const dd = config.domain_delays || {};
        const ddLines = Object.entries(dd).map(([k, v]) => `${k}: ${v}`);
        const ddEl = document.getElementById("job-domain-delays");
        if (ddEl) {
            ddEl.value = "";
            ddEl.defaultValue = "";
        }
        const btnViewDd = document.getElementById("btn-view-dd");
        if (btnViewDd && ddLines.length) {
            btnViewDd.style.display = "inline-block";
            btnViewDd.addEventListener("click", () => {
                showDefaultListModal("預設特定網域延遲 (唯讀)", ddLines.join("\n"));
            });
        }

        setField("job-delay", config.delay, config.min_delay, config.max_delay);
        setField(
            "job-timeout",
            config.timeout,
            config.min_timeout,
            config.max_timeout,
        );
        setField(
            "job-connect-timeout",
            config.connect_timeout,
            config.min_connect_timeout,
            config.max_connect_timeout,
        );
        setField(
            "job-ext-check-timeout",
            config.external_check_timeout,
            config.min_external_check_timeout,
            config.max_external_check_timeout,
        );
        setField(
            "job-retries",
            config.retries,
            config.min_retries,
            config.max_retries,
        );
        setField("job-max-depth", config.max_depth, 1, config.max_max_depth);
        setField("job-max-pages", config.max_pages, 1, config.max_max_pages);
        setField("job-proxy-url", config.proxy_url);

        _isDefaultsLoaded = true;
    } catch (err) {
        console.error("無法載入全域預設配置:", err);
    }
}

let _currentView = null;

/**
 * 處理 Hash Router 路由變更事件。
 * 根據 window.location.hash 切換不同的視圖 (View) 與側邊欄啟用狀態。
 * @returns {Promise<void>} 無回傳值
 */
async function route() {
    const hash = window.location.hash || "#/jobs";
    const jobMatch = hash.match(/^#\/jobs\/([^/]+)$/);

    viewJobs.style.display = "none";
    viewDetail.style.display = "none";
    if (viewCreate) viewCreate.style.display = "none";
    if (viewHelp) viewHelp.style.display = "none";
    if (viewCompare) viewCompare.style.display = "none";
    if (viewTransfer) viewTransfer.style.display = "none";
    if (viewDuplicate) viewDuplicate.style.display = "none";
    if (appSidebar) appSidebar.setAttribute("active-id", "");

    if (hash === "#/help") {
        if (viewHelp) viewHelp.style.display = "";
        if (appSidebar) appSidebar.setAttribute("active-id", "nav-help");
        _currentView = "help";
        destroyJobDetailPage();
    } else if (hash.startsWith("#/compare")) {
        if (viewCompare) viewCompare.style.display = "";
        if (appSidebar) appSidebar.setAttribute("active-id", "nav-compare");
        _currentView = "compare";
        destroyJobDetailPage();

        const params = new URLSearchParams(hash.split("?")[1] || "");
        const baseId = params.get("base");
        const targetId = params.get("target");

        await initComparePage(baseId, targetId);
    } else if (hash.startsWith("#/transfer")) {
        if (viewTransfer) viewTransfer.style.display = "";
        if (appSidebar) appSidebar.setAttribute("active-id", "nav-transfer");
        _currentView = "transfer";
        destroyJobDetailPage();

        const params = new URLSearchParams(hash.split("?")[1] || "");
        const jobId = params.get("job");

        await initTransferPage(jobId);
    } else if (hash.startsWith("#/duplicate")) {
        if (viewDuplicate) viewDuplicate.style.display = "";
        if (appSidebar) appSidebar.setAttribute("active-id", "nav-duplicate");
        _currentView = "duplicate";
        destroyJobDetailPage();

        await initDuplicatePage();
    } else if (hash.startsWith("#/new")) {
        if (viewCreate) viewCreate.style.display = "";
        if (appSidebar) appSidebar.setAttribute("active-id", "nav-new-job");
        _currentView = "new";
        destroyJobDetailPage();
        await loadJobDefaults();

        // 每次進入新建/複製頁面，都先重置表單以避免舊有狀態殘留
        const form = document.getElementById("create-job-form");
        if (form) form.reset();

        const params = new URLSearchParams(hash.split("?")[1] || "");
        const cloneId = params.get("clone");
        if (cloneId) {
            try {
                const job = await api.get(`/api/jobs/${cloneId}`);
                const c = job.config || {};

                const isEquivalent = (a, b) => {
                    if (a === b) return true;
                    if (a == null || b == null) return false;

                    // 容錯處理：若兩者皆能轉為非空數字，則以數值大小進行比對，相容字串數字與數值型態
                    if (a !== "" && b !== "" && !isNaN(Number(a)) && !isNaN(Number(b))) {
                        if (Number(a) === Number(b)) return true;
                    }

                    if (Array.isArray(a) && Array.isArray(b)) {
                        if (a.length !== b.length) return false;
                        const sortedA = [...a].sort();
                        const sortedB = [...b].sort();
                        return sortedA.every((val, index) => val === sortedB[index]);
                    }
                    if (typeof a === "object" && typeof b === "object") {
                        const keysA = Object.keys(a);
                        const keysB = Object.keys(b);
                        if (keysA.length !== keysB.length) return false;
                        return keysA.every((k) => isEquivalent(a[k], b[k]));
                    }
                    return false;
                };

                const getFilteredValue = (key, val) => {
                    if (!_globalDefaultConfig) return val;
                    const defaultVal = _globalDefaultConfig[key];

                    // 針對聯集/合併類型的參數 (陣列與字典)，進行差集過濾，只留下使用者自訂的部分
                    if (Array.isArray(val) && Array.isArray(defaultVal)) {
                        const filtered = val.filter((item) => !defaultVal.includes(item));
                        return filtered.length > 0 ? filtered : "";
                    } else if (
                        val !== null &&
                        typeof val === "object" &&
                        defaultVal !== null &&
                        typeof defaultVal === "object" &&
                        !Array.isArray(val)
                    ) {
                        const filtered = {};
                        for (const [k, v] of Object.entries(val)) {
                            if (defaultVal[k] !== v) {
                                filtered[k] = v;
                            }
                        }
                        return Object.keys(filtered).length > 0 ? filtered : "";
                    }

                    if (isEquivalent(val, defaultVal)) {
                        return ""; // 與預設值相同，濾除，維持空值讓 placeholder 顯示預設值
                    }
                    return val;
                };

                const setVal = (id, val) => {
                    const el = document.getElementById(id);
                    if (el) {
                        if (val !== undefined && val !== null) {
                            el.value = Array.isArray(val) ? val.join("\n") : val;
                        } else {
                            el.value = "";
                        }
                    }
                };

                setVal("job-url", job.start_url);
                setVal("job-target-domains", c.target_domains);
                setVal("job-trusted-domains", c.trusted_domains);
                setVal(
                    "job-ignore-exts",
                    getFilteredValue("ignore_extensions", c.ignore_extensions),
                );
                setVal(
                    "job-ignore-regexes",
                    getFilteredValue("ignore_regexes", c.ignore_regexes),
                );
                setVal(
                    "job-ssl-exempt",
                    getFilteredValue("ssl_exempt_domains", c.ssl_exempt_domains),
                );
                setVal(
                    "job-social-domains",
                    getFilteredValue("social_domains", c.social_domains),
                );

                // 單一覆寫型欄位，複製時直接填入原始快照值，不再進行全域濾除
                setVal("job-user-agent", c.user_agent);

                if (c.proxy_url && !c.proxy_url.includes("***")) {
                    setVal("job-proxy-url", c.proxy_url);
                } else if (c.proxy_url && c.proxy_url.includes("***")) {
                    setVal("job-proxy-url", "");
                    toast.warning(
                        "已隱藏原始任務的 Proxy 密碼，請重新輸入代理伺服器位址 (若需要)。",
                    );
                } else {
                    setVal("job-proxy-url", "");
                }

                setVal("job-timeout", c.timeout);
                setVal("job-connect-timeout", c.connect_timeout);
                setVal("job-ext-check-timeout", c.external_check_timeout);
                setVal("job-delay", c.delay);
                setVal("job-retries", c.retries);
                setVal("job-max-depth", c.max_depth);
                setVal("job-max-pages", c.max_pages);

                // domain_delays 屬於字典合併，依然需要進行過濾，防止全域網域延遲被寫死回表單
                const filteredDomainDelays = getFilteredValue(
                    "domain_delays",
                    c.domain_delays,
                );
                if (filteredDomainDelays) {
                    const ddLines = Object.entries(filteredDomainDelays).map(
                        ([k, v]) => `${k}: ${v}`,
                    );
                    setVal("job-domain-delays", ddLines);
                } else {
                    setVal("job-domain-delays", "");
                }
            } catch (err) {
                toast.error("無法載入欲複製的任務：" + err.message);
            }
        }
    } else if (jobMatch) {
        const jobId = jobMatch[1];
        viewDetail.style.display = "";
        document.getElementById("job-id-display").textContent = jobId;
        _currentView = "detail";
        destroyJobDetailPage();
        await initJobDetailPage(jobId);
    } else {
        viewJobs.style.display = "";
        if (appSidebar) appSidebar.setAttribute("active-id", "nav-jobs");
        _currentView = "list";
        destroyJobDetailPage();
        await loadJobsList();
    }
}

// 初始化
await initUser();
await route();
window.addEventListener("hashchange", route);

// ── 建立任務邏輯 ───────────────────────────────────────────
const createJobForm = document.getElementById("create-job-form");
if (createJobForm) {
    const jobUrlInput = document.getElementById("job-url");
    const targetDomainsInput = document.getElementById("job-target-domains");
    const trustedDomainsInput = document.getElementById("job-trusted-domains");

    // 自動填寫網域防呆：當網址輸入完畢時，自動提取 hostname 填入目標網域與信任網域
    if (jobUrlInput && targetDomainsInput) {
        jobUrlInput.addEventListener("blur", () => {
            if (jobUrlInput.value.trim()) {
                try {
                    const url = new URL(jobUrlInput.value.trim());
                    if (!targetDomainsInput.value.trim()) {
                        targetDomainsInput.value = url.hostname;
                    }
                    if (trustedDomainsInput && !trustedDomainsInput.value.trim()) {
                        trustedDomainsInput.value = url.hostname;
                    }
                } catch (e) { }
            }
        });
    }

    createJobForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const submitBtn = document.getElementById("btn-submit-job");
        const errorEl = document.getElementById("create-job-error");
        errorEl.textContent = "";

        const startUrl = jobUrlInput.value.trim();
        const targetDomainsRaw = targetDomainsInput.value;
        const trustedDomainsRaw = document.getElementById(
            "job-trusted-domains",
        ).value;
        const ignoreExtsRaw = document.getElementById("job-ignore-exts").value;
        const ignoreRegexesRaw =
            document.getElementById("job-ignore-regexes").value;

        if (!targetDomainsRaw.trim()) {
            errorEl.textContent = "請填寫至少一個目標網域。";
            return;
        }

        submitBtn.classList.add("loading");
        submitBtn.disabled = true;

        try {
            const body = {
                start_url: startUrl,
                target_domains: targetDomainsRaw
                    .split("\n")
                    .map((s) => s.trim())
                    .filter(Boolean),
                trusted_domains: trustedDomainsRaw
                    .split("\n")
                    .map((s) => s.trim())
                    .filter(Boolean),
            };

            const depth = document.getElementById("job-max-depth").value;
            if (depth) body.max_depth = parseInt(depth, 10);

            const pages = document.getElementById("job-max-pages").value;
            if (pages) body.max_pages = parseInt(pages, 10);

            const delay = document.getElementById("job-delay").value;
            if (delay) body.delay = parseFloat(delay);

            const timeout = document.getElementById("job-timeout").value;
            if (timeout) body.timeout = parseFloat(timeout);

            const connectTimeout = document.getElementById(
                "job-connect-timeout",
            ).value;
            if (connectTimeout) body.connect_timeout = parseFloat(connectTimeout);

            const extCheckTimeout = document.getElementById(
                "job-ext-check-timeout",
            ).value;
            if (extCheckTimeout)
                body.external_check_timeout = parseFloat(extCheckTimeout);

            const retries = document.getElementById("job-retries").value;
            if (retries) body.retries = parseInt(retries, 10);

            const proxyUrl = document.getElementById("job-proxy-url").value.trim();
            if (proxyUrl) body.proxy_url = proxyUrl;

            const ignoreExts = ignoreExtsRaw
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean);
            if (ignoreExts.length) body.ignore_extensions = ignoreExts;

            const ignoreRegexes = ignoreRegexesRaw
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean);
            if (ignoreRegexes.length) body.ignore_regexes = ignoreRegexes;

            const userAgent = document.getElementById("job-user-agent").value.trim();
            if (userAgent) body.user_agent = userAgent;

            const sslExemptRaw = document.getElementById("job-ssl-exempt").value;
            const sslExempt = sslExemptRaw
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean);
            if (sslExempt.length) body.ssl_exempt_domains = sslExempt;

            const socialDomainsRaw =
                document.getElementById("job-social-domains").value;
            const socialDomains = socialDomainsRaw
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean);
            if (socialDomains.length) body.social_domains = socialDomains;

            const ddLines = document
                .getElementById("job-domain-delays")
                .value.split("\n")
                .map((s) => s.trim())
                .filter(Boolean);
            if (ddLines.length > 0) {
                const domain_delays = {};
                for (const line of ddLines) {
                    const parts = line.split(":");
                    if (parts.length !== 2)
                        throw new Error('特定網域延遲格式錯誤，必須為 "網域: 延遲秒數"');
                    const domain = parts[0].trim();
                    const delayVal = parseFloat(parts[1].trim());
                    if (isNaN(delayVal) || delayVal < 0)
                        throw new Error(`特定網域延遲秒數無效: ${parts[1]}`);
                    domain_delays[domain] = delayVal;
                }
                body.domain_delays = domain_delays;
            }

            const res = await jobService.createJob(body);
            toast.success("任務已建立成功！");
            window.location.hash = `#/jobs/${res.job_id}`;
            createJobForm.reset();
        } catch (err) {
            errorEl.textContent = err.message || "建立任務失敗。";
        } finally {
            submitBtn.classList.remove("loading");
            submitBtn.disabled = false;
        }
    });
}
