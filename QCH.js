// name: 七彩虹签到
// cron: 30 10,22 * * *
// 环境变量：QCH_NOTIFY=0 关闭通知；PUSHPLUS_TOKEN 配置后额外走 PushPlus
const axios = require("axios");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

// ====================== 基础常量 ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.log("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识[#备注]，多账号换行分隔）");
    process.exit(1);
}

const BOX_WIDTH = 48;
const BOX_INNER = 46;
const MINI_APP_ID = "wx49018277e65fc3e1";
const PAGE_VERSION = "92";
const API_BASE = "https://interface.skycolorful.com";
const APP_SIGN_ID = "815d8026-9a52-4445-a42c-a5443134232e";
const APP_SIGN_SECRET = "2b5c01fb-7640-401a-8188-43a13190a626";
const LIKE_DAILY_LIMIT = 5;
const BBS_MODULE_ID = "09539c50-6de2-4a0c-adc8-535e488a419e";
const NOTIFY_ON = String(process.env.QCH_NOTIFY ?? "1") !== "0";
const DEBUG = String(process.env.QCH_DEBUG ?? "0") === "1";
// 签到接口在部分版本里改了路由，按顺序探测，命中 404 自动换下一个
const IS_SIGN_PATHS = ["/api/User/IsUserSign", "/api/User/IsSignV2", "/api/User/IsSignV3", "/api/User/IsSign"];
const SIGN_PATHS = ["/api/User/UserSign", "/api/User/SignV2", "/api/User/SignV3", "/api/User/Sign"];
const SIGN_LOG_PATH = "/api/User/SignLog";

const UA_LIST = [
    "Mozilla/5.0 (Linux; Android 16; 2308CPXD0C Build/BP2A.250605.031.A3; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.178 Mobile Safari/537.36 XWEB/1460217 MMWEBSDK/20260202 MMWEBID/6435 MicroMessenger/8.0.70.3060(0x28004652) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49(0x18003121) NetType/WIFI Language/zh_CN miniProgram/wx49018277e65fc3e1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) XWEB/19899",
];

// ====================== 缓存 ======================
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "qch_token_cache.json");

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch (e) { return {}; }
}

function writeTokenCache(cache) {
    try {
        fs.mkdirSync(path.dirname(TOKEN_CACHE_FILE), { recursive: true });
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
    } catch (e) { console.log("   ⚠️ [缓存] 写入失败: " + (e.message || e)); }
}

function cacheKey(server, ref) { return `${server}|${ref}`; }

function legacyRefOf(key) {
    const value = String(key || "").trim();
    if (!value || value.includes("|")) return "";
    let body = value;
    const hashIndex = body.lastIndexOf("#");
    const atIndex = body.lastIndexOf("@");
    if (hashIndex !== -1 && hashIndex > atIndex) body = body.slice(0, hashIndex).trim();
    const at = body.lastIndexOf("@");
    return at === -1 ? body.trim() : body.slice(at + 1).trim();
}

// ====================== 工具 ======================
const _VARIATION = /[\uFE0F\uFE0E\u200D]/g;
function displayWidth(text) {
    return String(text).replace(_VARIATION, "").split("").reduce((n, ch) => n + (ch.codePointAt(0) > 0xFF ? 2 : 1), 0);
}
function padWidth(text, width) {
    let value = String(text);
    while (displayWidth(value) > width) value = value.slice(0, -1);
    return value + " ".repeat(Math.max(0, width - displayWidth(value)));
}
function boxTop(title) {
    console.log("\n╔" + "═".repeat(BOX_WIDTH) + "╗");
    console.log("║  " + padWidth(title, BOX_INNER) + "║");
}
function boxLine(label, value) { console.log("║  " + padWidth(label + ": " + value, BOX_INNER) + "║"); }
function boxBottom() { console.log("╚" + "═".repeat(BOX_WIDTH) + "╝"); }
function accountFrame(index, total, title, source) {
    console.log("\n┌" + "─".repeat(BOX_WIDTH) + "┐");
    console.log("│  " + padWidth("🧩 账号 " + index + " / " + total + "　" + title, BOX_INNER) + "│");
    console.log("│  " + padWidth("🔗 来源: " + source, BOX_INNER) + "│");
    console.log("└" + "─".repeat(BOX_WIDTH) + "┘");
}
function hr() { console.log("\n" + "-".repeat(BOX_WIDTH)); }
function nowText() { return new Date().toLocaleString("zh-CN", { hour12: false }); }
function brief(value, limit = 90) { const text = String(value ?? "").replace(/\n/g, " "); return text.length <= limit ? text : text.slice(0, limit - 1) + "…"; }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
async function randomDelay(minSec, maxSec) { await sleep((Math.random() * (maxSec - minSec) + minSec) * 1000); }
function md5(str) { return crypto.createHash("md5").update(str).digest("hex"); }
function maskPhone(phone = "") { return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2"); }
function shortToken(token = "") {
    const value = String(token || "").replace(/^Bearer\s+/i, "");
    if (!value) return "-";
    return value.length > 16 ? `${value.slice(0, 8)}***${value.slice(-6)}` : `${value.slice(0, 4)}***`;
}
function isSuccess(result) { return Number(result?.Code) === 0 && result?.Success !== false; }
function isAuthError(message) { return /401|403|token|登录|授权|未登录|过期|失效/i.test(String(message || "")); }
function toInt(value) { const n = Number(value); return Number.isFinite(n) ? Math.trunc(n) : null; }

// 积分字段各版本命名不一，递归找最靠前的数值型积分字段
const POINT_KEYS = ["point", "points", "integral", "integralcount", "score", "totalpoint", "availablepoint", "currentpoint", "pointbalance"];
function pickPoints(data, depth = 0) {
    if (!data || depth > 4) return null;
    if (typeof data === "object") {
        for (const [key, value] of Object.entries(data)) {
            if (POINT_KEYS.includes(key.toLowerCase()) && toInt(value) !== null && toInt(value) >= 0) return toInt(value);
        }
        for (const value of Object.values(data)) {
            const found = pickPoints(value, depth + 1);
            if (found !== null) return found;
        }
    }
    return null;
}

function parseYybGoEntry(rawValue) {
    let value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "", note: "" };
    let note = "";
    const hashIndex = value.lastIndexOf("#");
    if (hashIndex > value.lastIndexOf("@") && hashIndex !== -1) {
        note = value.slice(hashIndex + 1).trim();
        value = value.slice(0, hashIndex).trim();
    }
    const atIndex = value.lastIndexOf("@");
    if (atIndex === -1) return { server: "", ref: "", note };
    const server = value.slice(0, atIndex).trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
    const ref = value.slice(atIndex + 1).trim();
    return { server, ref, note };
}

// ====================== YYB 取码 ======================
async function getWxCode(server, ref, type = "code") {
    const apiPath = type === "phone" ? "/wxapp/getPhoneNumber" : "/wxapp/getCode";
    try {
        const { data } = await axios.post(`http://${server}${apiPath}`,
            { ref, app_id: MINI_APP_ID }, { timeout: 20000, proxy: false });
        const code = data?.data?.result?.code;
        if (!data || data.code !== 0 || !code) {
            console.log(`   ❌ [取码] ${type === "phone" ? "手机号 code" : "code"} 获取失败: ${brief(JSON.stringify(data), 80)}`);
            return "";
        }
        console.log(`   ✅ [取码] ${type === "phone" ? "手机号 code" : "code"} 获取成功`);
        return code;
    } catch (e) {
        console.log(`   ❌ [取码] 请求 YYB Go 异常: ${brief(e.message)}`);
        return "";
    }
}

// ====================== 业务客户端 ======================
class Task {
    constructor(entry) {
        const { server, ref, note } = parseYybGoEntry(entry);
        this.entry = String(entry).trim();
        this.server = server;
        this.ref = ref;
        this.note = note;
        this.key = cacheKey(server, ref);
        this.token = "";
        this.refreshToken = "";
        this.openId = "";
        this.userInfo = {};
        this.signStatus = false;
        this.likeCount = 0;
    }

    signedHeaders(auth = true) {
        const requestId = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
        const ticks = Date.now();
        const headers = {
            "User-Agent": UA_LIST[Math.floor(Math.random() * UA_LIST.length)],
            "Referer": `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json",
            charset: "utf-8",
            requestId,
            AppId: APP_SIGN_ID,
            Ticks: String(ticks),
            Sign: md5(APP_SIGN_ID + ticks + requestId + APP_SIGN_SECRET),
            source: "Wx",
            UcSource: "30",
            "User-from": "xcx",
            version: "2.0.0",
            xweb_xhr: "1",
        };
        if (auth) {
            headers.Authorization = this.token ? `Bearer ${this.token}` : "";
            headers["X-Authorization"] = this.refreshToken ? `Bearer ${this.refreshToken}` : "";
        }
        return headers;
    }

    async request(apiPath, { method = "GET", data, params, auth = true } = {}) {
        const options = {
            method,
            url: new URL(apiPath, API_BASE).toString(),
            params,
            headers: this.signedHeaders(auth),
            timeout: 15000,
            validateStatus: () => true,
            proxy: false,
        };
        if (data !== undefined) options.data = data;
        const { data: result, status, headers } = await axios.request(options);
        if (headers?.["access-token"]) this.token = headers["access-token"];
        if (headers?.["x-access-token"]) this.refreshToken = headers["x-access-token"];
        if (status === 401 || status === 403) throw Object.assign(new Error(`HTTP ${status}: ${result?.Message || JSON.stringify(result)}`), { status });
        if (status !== 200) throw Object.assign(new Error(`HTTP ${status}: ${result?.Message || result?.msg || JSON.stringify(result)}`), { status });
        if (DEBUG) console.log(`   🐞 [调试] ${apiPath} → ${brief(JSON.stringify(result), 160)}`);
        if (!isSuccess(result)) throw Object.assign(new Error(`${result?.Code ?? ""} ${result?.Message || result?.msg || JSON.stringify(result)}`.trim()), { status });
        return result;
    }

    // ---- 缓存 ----
    loadCache() {
        const cache = readTokenCache();
        const entry = cache[this.key];
        if (entry && entry.token) return entry;
        const candidates = [];
        for (const [key, value] of Object.entries(cache)) {
            if (key === this.key || !value || !value.token) continue;
            if (legacyRefOf(key) === this.ref) candidates.push([value.updatedAt || "", key, value]);
        }
        if (!candidates.length) return null;
        candidates.sort((a, b) => String(a[0]).localeCompare(String(b[0])));
        const best = candidates[candidates.length - 1][2];
        cache[this.key] = { ...best };
        for (const [, key] of candidates) delete cache[key];
        delete cache[this.entry];
        writeTokenCache(cache);
        console.log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」");
        return cache[this.key];
    }

    saveCache() {
        if (!this.token) return;
        const cache = readTokenCache();
        cache[this.key] = {
            token: this.token,
            refreshToken: this.refreshToken,
            openId: this.openId,
            userInfo: this.userInfo,
            updatedAt: nowText(),
        };
        writeTokenCache(cache);
    }

    dropCache() {
        const cache = readTokenCache();
        delete cache[this.key];
        for (const key of Object.keys(cache)) {
            if (key !== this.key && legacyRefOf(key) === this.ref) delete cache[key];
        }
        writeTokenCache(cache);
        this.token = "";
        this.refreshToken = "";
        this.userInfo = {};
    }

    applyCache(entry) {
        this.token = entry.token || "";
        this.refreshToken = entry.refreshToken || "";
        this.openId = entry.openId || "";
        this.userInfo = entry.userInfo || {};
    }

    // ---- 登录 ----
    async login() {
        const wxCode = await getWxCode(this.server, this.ref, "code");
        if (!wxCode) throw new Error("获取 wx code 失败");
        const loginRes = await this.request("/api/User/OnLogin", { method: "POST", auth: false, data: { Code: wxCode } });
        this.openId = loginRes?.Data?.OpenId || "";
        if (!this.openId) throw new Error("OnLogin 未返回 OpenId");
        await sleep(1000);

        const phoneCode = await getWxCode(this.server, this.ref, "phone");
        if (!phoneCode) throw new Error("获取手机号 code 失败");
        const phoneRes = await this.request("/api/User/DecryptPhoneNumber", {
            method: "POST", auth: false, data: { OpenId: this.openId, Code: phoneCode },
        });
        const token = phoneRes?.Data?.Token || "";
        if (!token) throw new Error("DecryptPhoneNumber 未返回 Token");
        this.token = token;
        this.refreshToken = phoneRes?.Data?.RefreshToken || "";
        this.saveCache();
        console.log(`   ✅ [登录] 新 token 获取成功: ${shortToken(this.token)}`);
    }

    // ---- 只读校验 / 资料 ----
    async fetchUserInfo() {
        const result = await this.request("/api/User/GetUserInfo");
        this.userInfo = result?.Data || this.userInfo;
        if (this.token) this.saveCache();
        return this.userInfo;
    }

    async verify() {
        try {
            await this.fetchUserInfo();
            return { ok: true, msg: "" };
        } catch (e) {
            return { ok: false, msg: brief(e.message || e, 60) };
        }
    }

    async profile() {
        if (!Object.keys(this.userInfo).length) await this.fetchUserInfo();
        const info = this.userInfo || {};
        const name = info.NickName || maskPhone(info.Mobile) || this.ref;
        const points = pickPoints(info);
        return { name: String(name || "未知"), points };
    }

    // ---- 签到 ----
    async tryPaths(paths, { method = "GET", data } = {}) {
        const slot = paths[0];
        this.pathCache = this.pathCache || {};
        const cached = this.pathCache[slot];
        const order = cached && paths.includes(cached)
            ? [cached, ...paths.filter(item => item !== cached)]
            : paths;
        let lastError = null;
        for (const apiPath of order) {
            try {
                const result = await this.request(apiPath, { method, data });
                if (apiPath !== slot) console.log(`   🔧 [接口] 已改用可用路径 ${apiPath}`);
                this.pathCache[slot] = apiPath;
                return result;
            } catch (e) {
                if (e.status === 404) { lastError = e; continue; }
                throw e;
            }
        }
        throw lastError || new Error("未找到可用的签到接口");
    }

    async getSignInfo() {
        try {
            const result = await this.tryPaths(IS_SIGN_PATHS);
            this.signStatus = Boolean(result?.Data?.IsSign ?? result?.Data?.IsSignIn);
        } catch (e) {
            console.log(`   ⚠️ [签到] 查询签到状态失败: ${brief(e.message || e, 60)}`);
        }
    }

    async sign() {
        if (this.signStatus) return { ok: true, text: "今日已签到", quiet: true };
        try {
            const result = await this.tryPaths(SIGN_PATHS, { method: "POST", data: {} });
            return { ok: true, text: result?.Message || "签到成功", quiet: false };
        } catch (e) {
            const message = String(e.message || e);
            if (/已签到|已签|重复|今日已/.test(message)) return { ok: true, text: `今日已签到（${message}）`, quiet: true };
            return { ok: false, text: `签到失败（${brief(message, 60)}）`, quiet: false, auth: isAuthError(message) };
        }
    }

    // ---- 点赞 ----
    async getPostingList(page = 1, size = 10) {
        const result = await this.request("/api/Bbs/GetPostingList", {
            method: "GET",
            params: { Page: page, Size: size, ModuleId: BBS_MODULE_ID, SubClassId: "    ", IsNewest: true, IsEssence: false, SearchValue: "" },
        });
        return result?.Data?.DataList || [];
    }

    async likePost(postId) {
        try {
            const result = await this.request("/api/Bbs/Like", { method: "POST", data: { postId: String(postId), postReplyId: "0" } });
            return { ok: true, text: result?.Message || "点赞成功" };
        } catch (e) {
            const message = String(e.message || e);
            if (/已点赞|重复|已经|不能|今日/.test(message)) return { ok: false, skip: true, text: message };
            return { ok: false, text: message, auth: isAuthError(message) };
        }
    }

    async doLikes() {
        console.log(`   👍 [点赞] 开始社区点赞（上限 ${LIKE_DAILY_LIMIT} 次，每次 2 积分）`);
        const seen = new Set();
        let liked = 0;
        let failed = 0;
        let authFailed = false;
        for (let page = 1; page <= 5 && liked < LIKE_DAILY_LIMIT; page++) {
            const posts = await this.getPostingList(page, 10);
            if (!posts.length) {
                console.log(`   👍 [点赞] 第 ${page} 页无更多帖子，停止`);
                break;
            }
            for (const post of posts) {
                if (liked >= LIKE_DAILY_LIMIT) break;
                const postId = post.Id || "";
                const title = String(post.Title || "未知标题");
                if (!postId || seen.has(postId) || post.IsLike === true) continue;
                seen.add(postId);
                await randomDelay(3, 5);
                const result = await this.likePost(postId);
                if (result.ok) {
                    liked++;
                    console.log(`   👍 [点赞] 成功(${liked}/${LIKE_DAILY_LIMIT})：${brief(title, 26)}`);
                } else if (!result.skip) {
                    failed++;
                    console.log(`   ⚠️ [点赞] 失败：${brief(result.text, 50)}`);
                    if (result.auth) { authFailed = true; break; }
                }
            }
            if (authFailed) break;
        }
        this.likeCount = liked;
        return { liked, failed, gain: liked * 2, authFailed };
    }
}

// ====================== 账号执行 ======================
async function runAccount(index, total, entry) {
    const parsed = parseYybGoEntry(entry);
    const result = {
        index, ref: parsed.ref || "-", note: parsed.note, ok: true, error: "",
        loginSource: "", name: "", pointsBefore: null, pointsAfter: null, delta: 0,
        signText: "", likes: 0, likeGain: 0,
    };
    if (!parsed.server || !parsed.ref) {
        console.log(`   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过: ${brief(entry, 60)}`);
        return { ...result, ok: false, error: "账号格式无效" };
    }
    accountFrame(index, total, `标识 ${parsed.ref}` + (parsed.note ? `（${parsed.note}）` : ""), entry);

    const task = new Task(entry);
    const cached = task.loadCache();
    let usedCache = false;

    if (cached) {
        task.applyCache(cached);
        usedCache = true;
        console.log(`   💾 [缓存] 复用已保存 token: ${shortToken(task.token)}`);
        const verify = await task.verify();
        if (verify.ok) {
            console.log("   ✅ [校验] 缓存 token 有效，直接复用");
            result.loginSource = "缓存";
        } else if (isAuthError(verify.msg)) {
            console.log(`   ⚠️ [校验] 缓存 token 失效（${brief(verify.msg, 50)}），清除后重新登录`);
            task.dropCache();
            usedCache = false;
        } else {
            console.log(`   ❌ [校验] 缓存 token 查询失败（${brief(verify.msg, 50)}），保留缓存`);
            return { ...result, ok: false, error: `查询用户信息失败（${verify.msg}）` };
        }
    }

    if (!usedCache) {
        try {
            await task.login();
            result.loginSource = "新登录";
        } catch (e) {
            console.log(`   ❌ [登录] 登录失败: ${brief(e.message || e, 60)}`);
            return { ...result, ok: false, error: `登录失败（${brief(e.message || e, 60)}）` };
        }
        const verify = await task.verify();
        if (!verify.ok) {
            console.log(`   ⚠️ [校验] 新 token 校验失败（${brief(verify.msg, 50)}），清除后重登`);
            task.dropCache();
            try {
                await task.login();
                result.loginSource = "重登";
            } catch (e) {
                return { ...result, ok: false, error: `重登失败（${brief(e.message || e, 60)}）` };
            }
            const again = await task.verify();
            if (!again.ok) return { ...result, ok: false, error: `重登后校验仍失败（${again.msg}）` };
        }
        console.log("   ✅ [校验] 登录凭证校验通过（用户信息接口）");
    }

    const profile = await task.profile();
    result.name = profile.name;
    result.pointsBefore = profile.points;
    console.log(`   👤 [会员] ${profile.name}`);
    console.log(`   💰 [积分] 当前 ${profile.points ?? "未知"}`);

    await task.getSignInfo();
    const sign = await task.sign();
    result.signText = sign.text;
    console.log(`   ${sign.ok ? (sign.quiet ? "ℹ️" : "✅") : "❌"} [签到] ${sign.text}`);
    if (!sign.ok) {
        result.ok = false;
        result.error = sign.text;
        if (sign.auth) task.dropCache();
    }

    try {
        const likeResult = await task.doLikes();
        result.likes = likeResult.liked;
        result.likeGain = likeResult.gain;
        if (likeResult.authFailed) task.dropCache();
    } catch (e) {
        console.log(`   ⚠️ [点赞] 执行异常: ${brief(e.message || e, 60)}`);
    }

    await sleep(1000);
    try {
        await task.fetchUserInfo();
        const after = pickPoints(task.userInfo);
        result.pointsAfter = after;
        if (after !== null && profile.points !== null) result.delta = after - profile.points;
    } catch (e) {
        console.log(`   ⚠️ [积分] 复查失败: ${brief(e.message || e, 60)}`);
    }
    console.log(`   💰 [积分] ${result.pointsBefore ?? "未知"} → ${result.pointsAfter ?? "未知"}`
        + (result.pointsBefore !== null && result.pointsAfter !== null ? `（${result.delta >= 0 ? "+" : ""}${result.delta}）` : ""));
    console.log(`   ${result.ok ? "✅" : "⚠️"} [完成] ${result.ok ? "该账号任务执行完成" : "该账号存在失败项"}`);
    return result;
}

// ====================== 通知 ======================
async function sendQingLongNotify(title, content) {
    for (const file of ["/ql/data/scripts/notify.js", "/ql/scripts/notify.js", path.join(__dirname, "notify.js"), path.join(__dirname, "SendNotify.js")]) {
        try {
            if (!fs.existsSync(file)) continue;
            const mod = require(file);
            const fn = (typeof mod === "function" && mod) || mod.sendNotify || mod.send;
            if (typeof fn === "function") { await fn(title, content); return true; }
        } catch {}
    }
    return false;
}

async function sendPushPlus(title, content) {
    const token = process.env.PUSHPLUS_TOKEN || process.env.PLUSPLUS_TOKEN || "";
    if (!token) return false;
    try {
        const res = await axios.post("https://www.pushplus.plus/send", { token, title, content, template: "txt" }, { timeout: 15000, proxy: false });
        return res.data?.code === 200;
    } catch { return false; }
}

// ====================== 主流程 ======================
(async () => {
    const entries = SERVERS;
    const valid = [];
    const invalid = [];
    for (const line of entries) {
        const parsed = parseYybGoEntry(line);
        (parsed.server && parsed.ref ? valid : invalid).push(line);
    }
    for (const line of invalid) console.log(`   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过: ${brief(line, 60)}`);
    if (!valid.length) {
        console.log("❌ YYB_SERVER 无有效账号（格式：地址@标识[#备注]）");
        return;
    }

    boxTop("🌈 七彩虹 每日任务");
    boxLine("🕒 启动时间", nowText());
    boxLine("🔢 账号数量", `${valid.length} 个` + (invalid.length ? `（${invalid.length} 行格式无效）` : ""));
    boxLine("💾 缓存", path.basename(TOKEN_CACHE_FILE));
    boxLine("🌐 网络", "直连");
    boxBottom();

    const results = [];
    for (let i = 0; i < valid.length; i++) {
        try {
            results.push(await runAccount(i + 1, valid.length, valid[i]));
        } catch (e) {
            const parsed = parseYybGoEntry(valid[i]);
            console.log(`   ❌ [执行] 账号 ${i + 1} 未捕获异常: ${brief(e.message || e, 80)}`);
            results.push({
                index: i + 1, ref: parsed.ref || "-", note: parsed.note, ok: false, error: String(e.message || e),
                loginSource: "", name: "", pointsBefore: null, pointsAfter: null, delta: 0, signText: "", likes: 0, likeGain: 0,
            });
        }
        hr();
        if (i < valid.length - 1) {
            console.log("   ⏳ 等待2秒后执行下一个账号...");
            await sleep(2000);
        }
    }

    console.log("");
    for (const r of results) {
        console.log(`${r.ok ? "✅" : "❌"} 【账号 ${r.index} · 标识 ${r.ref}】`);
        console.log(`   🔐 登录：${r.loginSource || "-"}`);
        console.log(`   👤 会员：${r.name || "-"}`);
        console.log(`   📅 签到：${r.signText || "-"}`);
        console.log(`   👍 点赞：${r.likes} 次（+${r.likeGain} 积分）`);
        console.log(`   💰 积分：${r.pointsBefore ?? "未知"} → ${r.pointsAfter ?? "未知"}` +
            (r.pointsBefore !== null && r.pointsAfter !== null ? `（${r.delta >= 0 ? "+" : ""}${r.delta}）` : ""));
        if (!r.ok) console.log(`   ⚠️ 失败：${brief(r.error || "见上方日志", 80)}`);
    }

    const ok = results.filter(r => r.ok).length;
    const totalGain = results.reduce((sum, r) => sum + (r.likeGain || 0), 0);
    boxTop("🏁 🌈 七彩虹 执行汇总");
    boxLine("📊 执行结果", `成功 ${ok} / 失败 ${results.length - ok} / 共 ${results.length}`);
    boxLine("👍 点赞总计", `${results.reduce((s, r) => s + (r.likes || 0), 0)} 次（+${totalGain} 积分）`);
    boxLine("🕒 结束时间", nowText());
    boxBottom();

    const content = results.map(r =>
        `${r.ok ? "✅" : "❌"} 账号${r.index} ${r.ref}\n` +
        `会员：${r.name || "-"}\n签到：${r.signText || "-"}\n` +
        `点赞：${r.likes} 次（+${r.likeGain} 积分）\n` +
        `积分：${r.pointsBefore ?? "未知"} → ${r.pointsAfter ?? "未知"}` +
        (r.ok ? "" : `\n失败：${brief(r.error || "", 80)}`)
    ).join("\n\n");

    if (NOTIFY_ON) {
        const sent = await sendQingLongNotify("🌈 七彩虹任务完成", content);
        console.log(sent ? "   📮 [通知] 已通过青龙 notify 推送" : "   ℹ️ [通知] 未找到青龙 notify 脚本");
        if (await sendPushPlus("🌈 七彩虹任务完成", content)) console.log("   📨 [通知] PushPlus 推送成功");
    } else {
        console.log("   ℹ️ [通知] QCH_NOTIFY=0，已关闭通知");
    }
})().catch(e => console.log(`❌ [全局异常] ${e.message}`));
