// name: 顾家家居会员俱乐部
// cron: 20 8,20 * * *
const axios = require("axios");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const APP = {
    name: "顾家家居",
    appid: "wx0770280d160f09fe",
    pageVersion: "286",
};

const API_BASE = "https://mc.kukahome.com/club-server";
const INTEGRAL_BASE = "https://mc.kukahome.com/integral-server";
const BRAND_CODE = "K001";
const SMALL_APPLICATION_ID = "667516";
const SMALL_CRYPTO = "FH3yRrHG2RfexND8";
const VERSION_NUMBER = "2.8.6";
const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

const BOX_WIDTH = 48;
const BOX_INNER = 46;
const SCRIPT_DIR = __dirname;
const TOKEN_CACHE_DIR = path.join(SCRIPT_DIR, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "gjjj_token_cache.json");

const NOTIFY_ENABLED = String(process.env.GJJJ_NOTIFY ?? "1").trim() !== "0";
const COMMUNITY_ENABLED = String(process.env.GJJJ_COMMUNITY ?? "1").trim() !== "0";

// ====================== 日志版式 ======================
function displayWidth(text) {
    let width = 0;
    for (const ch of String(text)) {
        const code = ch.codePointAt(0);
        if (code === 0xfe0f || code === 0xfe0e || code === 0x200d) continue;
        width += code > 0xff ? 2 : 1;
    }
    return width;
}

function pad(text, width) {
    const chars = Array.from(String(text));
    while (chars.length && displayWidth(chars.join("")) > width) chars.pop();
    const value = chars.join("");
    return value + " ".repeat(Math.max(0, width - displayWidth(value)));
}

function log(msg = "") {
    console.log(msg);
}

function boxTop(title) {
    log();
    log("╔" + "═".repeat(BOX_WIDTH) + "╗");
    log("║  " + pad(title, BOX_INNER) + "║");
}

function boxLine(label, value) {
    log("║  " + pad(`${label}: ${value}`, BOX_INNER) + "║");
}

function boxBottom() {
    log("╚" + "═".repeat(BOX_WIDTH) + "╝");
}

function accountFrame(index, total, title, source) {
    log();
    log("┌" + "─".repeat(BOX_WIDTH) + "┐");
    log("│  " + pad(`🧩 账号 ${index} / ${total}　${title}`, BOX_INNER) + "│");
    log("│  " + pad(`🔗 来源: ${source}`, BOX_INNER) + "│");
    log("└" + "─".repeat(BOX_WIDTH) + "┘");
}

function hr() {
    log();
    log("-".repeat(BOX_WIDTH));
}

function nowText() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function short(value, max = 90) {
    if (value === undefined || value === null) return "";
    let text;
    try {
        text = typeof value === "string" ? value : JSON.stringify(value);
    } catch {
        text = String(value);
    }
    text = text.replace(/\s+/g, " ").trim();
    return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

function maskToken(value) {
    const text = String(value || "");
    return text.length <= 10 ? text : `${text.slice(0, 6)}***${text.slice(-6)}`;
}

function maskPhone(value) {
    const text = String(value || "");
    return /^1\d{10}$/.test(text) ? `${text.slice(0, 3)}****${text.slice(-4)}` : text;
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomDelay(min = 2, max = 4) {
    return sleep((min + Math.random() * (max - min)) * 1000);
}

function toInt(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? Math.trunc(n) : fallback;
}

// ====================== 缓存 ======================
function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf-8")) || {};
    } catch {
        return {};
    }
}

function writeTokenCache(cache) {
    try {
        fs.mkdirSync(TOKEN_CACHE_DIR, { recursive: true });
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf-8");
        return true;
    } catch (e) {
        log(`   ⚠️ [缓存] 写入失败：${short(e.message, 60)}`);
        return false;
    }
}

function cacheKeyOf(server, ref) {
    return `${server}|${ref}`;
}

function cacheMatches(key, server, ref) {
    const k = String(key || "").trim();
    if (k === `${server}|${ref}` || k === ref || k === `${server}@${ref}`) return true;
    if (k.indexOf("|") !== -1) {
        const left = k.slice(0, k.lastIndexOf("|")).trim();
        const right = k.slice(k.lastIndexOf("|") + 1).trim();
        return left === server && right === ref;
    }
    if (k.indexOf("@") !== -1) {
        const tail = k.slice(k.indexOf("@") + 1).split("#")[0].trim();
        return tail === ref;
    }
    return false;
}

function entryValid(value) {
    return !!value && typeof value === "object" && !!(value.accessToken || value.token);
}

function loadCache(server, ref) {
    const cache = readTokenCache();
    const key = cacheKeyOf(server, ref);
    const candidates = [];
    for (const oldKey of Object.keys(cache)) {
        if (!cacheMatches(oldKey, server, ref)) continue;
        const value = cache[oldKey];
        if (!entryValid(value)) continue;
        candidates.push({ oldKey, value, updatedAt: String(value.updatedAt || "") });
    }
    if (!candidates.length) return null;
    candidates.sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1));
    const best = candidates[0];
    if (best.oldKey !== key || candidates.length > 1) {
        cache[key] = Object.assign({}, best.value, { updatedAt: best.updatedAt || nowText() });
        for (const item of candidates) {
            if (item.oldKey !== key) delete cache[item.oldKey];
        }
        writeTokenCache(cache);
        log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」");
        return cache[key];
    }
    return best.value;
}

function saveCache(server, ref, value) {
    const cache = readTokenCache();
    cache[cacheKeyOf(server, ref)] = Object.assign({}, value, { updatedAt: nowText() });
    writeTokenCache(cache);
}

function dropCache(server, ref) {
    const cache = readTokenCache();
    for (const key of Object.keys(cache)) {
        if (cacheMatches(key, server, ref)) delete cache[key];
    }
    writeTokenCache(cache);
}

// ====================== 账号 ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);

function parseYybGoEntry(rawValue) {
    let value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "", note: "" };
    let note = "";
    const atIndex = value.lastIndexOf("@");
    const hashIndex = value.lastIndexOf("#");
    if (atIndex !== -1 && hashIndex > atIndex) {
        note = value.slice(hashIndex + 1).trim();
        value = value.slice(0, hashIndex).trim();
    }
    if (atIndex === -1) {
        log(`   ❌ [账号] 格式应为 地址@标识[#备注]，当前值: ${value}`);
        return { server: "", ref: "", note: "" };
    }
    const server = value
        .slice(0, value.lastIndexOf("@"))
        .trim()
        .replace(/^https?:\/\//, "")
        .replace(/\/+$/, "");
    const ref = value.slice(value.lastIndexOf("@") + 1).trim();
    if (!server || !ref) return { server: "", ref: "", note: "" };
    return { server, ref, note };
}

// ====================== 异常 ======================
class AuthExpired extends Error {
    constructor(message) {
        super(message);
        this.name = "AuthExpired";
        this.auth = true;
    }
}

class ApiError extends Error {
    constructor(message, code, body) {
        super(message);
        this.name = "ApiError";
        this.code = code;
        this.body = body;
    }
}

const AUTH_MESSAGE_RE =
    /401|402|515|登录失效|登录过期|未登录|请重新登录|token失效|token已过期|accessToken无效|登录状态异常/i;

function isAuthError(error) {
    if (!error) return false;
    if (error instanceof AuthExpired || error.auth === true) return true;
    return AUTH_MESSAGE_RE.test(String(error.message || error));
}

function isAlreadyMessage(message) {
    return /今日已签|已经签到|已签到|重复签到|重复|already|今日已领|已领取/.test(String(message || ""));
}

function isTrueValue(value) {
    return value === true || value === 1 || value === "1" || value === "true";
}

function isDoneStatus(value) {
    return value !== null && value !== undefined && (value === 1 || value === "1" || value === true);
}

// ====================== 请求 ======================
function md5(input) {
    return crypto.createHash("md5").update(String(input)).digest("hex");
}

function isObject(val) {
    return Object.prototype.toString.call(val) === "[object Object]";
}

function buildParameterBase(data) {
    if (!data) return null;
    if (Array.isArray(data) || typeof data === "string") return null;
    if (!isObject(data)) return null;
    const keys = Object.keys(data).sort((a, b) => {
        const ac = [...a].map((ch) => ch.charCodeAt(0));
        const bc = [...b].map((ch) => ch.charCodeAt(0));
        for (let i = 0; i < Math.min(ac.length, bc.length); i++) {
            if (ac[i] !== bc[i]) return ac[i] - bc[i];
        }
        return ac.length - bc.length;
    });
    const pairs = [];
    for (const key of keys) {
        const value = data[key];
        if (value === null || value === undefined || value === "") continue;
        if (Array.isArray(value)) continue;
        if (typeof value === "object" && value !== null) {
            pairs.push(`${key}=${JSON.stringify(value)}`);
            continue;
        }
        pairs.push(`${key}=${value}`);
    }
    return pairs.length ? pairs.join("&") : null;
}

function buildParameterSign(data, timestamp) {
    const base = buildParameterBase(data);
    if (!base) return "";
    const salt = String(timestamp).substring(4, 10);
    return md5(md5(base) + salt);
}

async function getWxCode(server, ref) {
    const url = "http://" + server + "/wxapp/getCode";
    let res;
    try {
        res = await axios.request({
            method: "POST",
            url,
            data: { app_id: APP.appid, ref },
            headers: { "Content-Type": "application/json" },
            timeout: 20000,
            proxy: false,
            validateStatus: () => true,
        });
    } catch (e) {
        throw new ApiError(`取码请求失败: ${short(e.message, 70)}`, -1);
    }
    if (res.status !== 200) {
        throw new ApiError(`取码 HTTP ${res.status}: ${short(res.data, 80)}`, res.status, res.data);
    }
    const body = res.data || {};
    if (Number(body.code) !== 0) {
        throw new ApiError(`取码失败: ${short(body.msg || body.message || body, 80)}`, body.code, body);
    }
    const code = body?.data?.result?.code || body?.data?.code;
    if (!code) throw new ApiError(`wx_server 未返回 code: ${short(body, 80)}`, -1, body);
    return code;
}

// ====================== 账号任务 ======================
class Task {
    constructor(serverEntry, index) {
        this.serverEntry = serverEntry;
        this.index = index;
        const parsed = parseYybGoEntry(serverEntry);
        this.server = parsed.server;
        this.ref = parsed.ref;
        this.note = parsed.note;
        this.openid = parsed.ref;
        this.tmpToken = "";
        this.accessToken = "";
        this.memberId = "";
        this.userInfo = {};
        this.userText = "-";
    }

    baseResult() {
        return {
            index: this.index,
            ref: this.ref,
            note: this.note,
            loginSource: "-",
            user: "-",
            pointBefore: null,
            pointAfter: null,
            signStatus: "none",
            signMessage: "-",
            signGain: 0,
            signTotal: null,
            taskCount: 0,
            community: null,
            success: false,
            error: "",
        };
    }

    applyToken(data = {}) {
        this.accessToken = data.accessToken || data.token || this.accessToken;
        this.memberId = String(data.memberId || this.memberId || "");
    }

    async request({ method = "POST", url, data = {}, params = {}, withAuth = true, withTmpToken = true }) {
        const timestamp = Date.now();
        const sign = md5(`${SMALL_APPLICATION_ID}${SMALL_CRYPTO}${timestamp}`).toLowerCase();
        const bodyForSign = method.toUpperCase() === "GET" ? params : data;
        const parameterSign = buildParameterSign(bodyForSign, timestamp);
        const headers = {
            "User-Agent": USER_AGENT,
            Referer: `https://servicewechat.com/${APP.appid}/${APP.pageVersion}/page-frame.html`,
            Accept: "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Customer": this.memberId || "",
            brandCode: BRAND_CODE,
            appid: SMALL_APPLICATION_ID,
            "E-Opera": "",
            "xweb_xhr": "1",
            sign,
            timestamp,
            versionNumber: VERSION_NUMBER,
        };
        if (parameterSign) headers.parameterSign = parameterSign;
        if (withAuth && this.accessToken) headers.AccessToken = this.accessToken;
        if (withTmpToken && this.tmpToken) headers.tmpToken = this.tmpToken;

        const config = {
            method,
            url,
            headers,
            timeout: 20000,
            proxy: false,
            validateStatus: () => true,
        };
        if (params && Object.keys(params).length) config.params = params;
        if (method.toUpperCase() !== "GET") config.data = data;

        let res;
        try {
            res = await axios.request(config);
        } catch (e) {
            throw new ApiError(`请求失败: ${short(e.message, 70)}`, -1);
        }
        if (res.status === 401 || res.status === 403) {
            throw new AuthExpired(`HTTP ${res.status}，登录凭证已失效`);
        }
        if (res.status !== 200) {
            const label = `${method.toUpperCase()} ${url
                .replace(API_BASE, "")
                .replace(INTEGRAL_BASE, "")}`;
            throw new ApiError(`${label} HTTP ${res.status}: ${short(res.data, 120)}`, res.status, res.data);
        }

        const body = res.data || {};
        const code = body.code === undefined ? 0 : Number(body.code);
        const message = body.message || body.msg || short(body, 100);
        if ([401, 402, 515].includes(code) || AUTH_MESSAGE_RE.test(String(message))) {
            throw new AuthExpired(message || `接口返回 code=${code}`);
        }
        if (code !== 0) throw new ApiError(message || `接口返回 code=${code}`, code, body);
        return body;
    }

    async login() {
        const code = await getWxCode(this.server, this.ref);
        let identify;
        try {
            identify = await this.request({
                method: "POST",
                url: `${API_BASE}/api/user/identify`,
                params: { code },
                withAuth: false,
                withTmpToken: false,
            });
        } catch (e) {
            if (isAuthError(e)) throw e;
            if (!/HTTP 400|HTTP 405/.test(e.message || "")) throw e;
            log("   🧾 [登录] identify 改用 body 提交 code");
            identify = await this.request({
                method: "POST",
                url: `${API_BASE}/api/user/identify`,
                data: { code },
                withAuth: false,
                withTmpToken: false,
            });
        }
        if (!identify.data) throw new ApiError(`identify 返回为空: ${short(identify, 80)}`);
        this.tmpToken = identify.data.token || identify.data.tmpToken || "";
        if (!this.tmpToken) throw new ApiError("identify 未返回 tmpToken");
        if (Number(identify.data.status) !== 4) {
            log(`   ⚠️ [登录] identify 状态异常: status=${identify.data.status}，仍尝试继续`);
        }

        const auth = await this.request({
            method: "POST",
            url: `${API_BASE}/api/user/authorizeLogin`,
            data: { source: "顾家小程序", contentName: "" },
            withAuth: false,
            withTmpToken: true,
        });
        const authToken = auth.data?.token || auth.data?.accessToken;
        if (!authToken) throw new ApiError(`authorizeLogin 失败: ${short(auth, 80)}`);
        this.accessToken = authToken;
        this.memberId = String(auth.data.memberId || "");
        this.tmpToken = "";
    }

    async getUserInfo() {
        const info = await this.request({
            method: "POST",
            url: `${API_BASE}/api/user/info`,
            data: {},
            withAuth: true,
            withTmpToken: false,
        });
        if (!info.data) throw new ApiError("user/info 返回为空");
        this.userInfo = info.data;
        this.applyToken(info.data);
        const nick = this.userInfo.nickName || this.userInfo.name || "";
        const mobile = this.userInfo.mobile || "";
        const memberId = this.userInfo.memberId || this.userInfo.id || this.memberId || "";
        this.userText = [
            nick || "未设置昵称",
            mobile ? maskPhone(mobile) : "",
            memberId ? `ID ${memberId}` : "",
        ]
            .filter(Boolean)
            .join(" / ");
        return this.userInfo;
    }

    saveLogin() {
        saveCache(this.server, this.ref, {
            token: this.accessToken,
            accessToken: this.accessToken,
            memberId: this.memberId,
            userInfo: this.userInfo,
            nickname: this.userInfo.nickName || this.userInfo.name || "",
        });
    }

    async ensureLogin(useCache) {
        if (useCache) {
            const cached = loadCache(this.server, this.ref);
            const token = cached && (cached.accessToken || cached.token);
            if (token) {
                this.accessToken = token;
                this.memberId = String(cached.memberId || "");
                log(`   💾 [缓存] 复用已保存 token ${maskToken(token)}`);
                try {
                    await this.getUserInfo();
                    log("   ✅ [校验] 登录凭证校验通过");
                    log(`   👤 [用户] ${this.userText || "-"}`);
                    this.saveLogin();
                    log("   ✅ [登录] 缓存复用成功");
                    return "缓存复用";
                } catch (e) {
                    if (!isAuthError(e)) throw e;
                    log("   ⚠️ [校验] 缓存 token 已失效，重新登录");
                    dropCache(this.server, this.ref);
                    this.accessToken = "";
                    this.memberId = "";
                    this.tmpToken = "";
                }
            }
        }

        log("   🔐 [登录] 新登录");
        await this.login();
        await this.getUserInfo();
        log("   ✅ [校验] 登录凭证校验通过");
        log(`   👤 [用户] ${this.userText || "-"}`);
        this.saveLogin();
        log("   ✅ [登录] 新登录成功");
        return "新登录";
    }

    extractPoint(ret) {
        const candidates = [
            ret && ret.point,
            ret && ret.data && ret.data.point,
            ret && ret.data && ret.data.points,
            ret && ret.data && ret.data.integral,
            ret && ret.data && ret.data.totalPoint,
            ret && ret.data && ret.data.total_point,
            ret && ret.data && ret.data.availablePoint,
            ret && ret.data && ret.data.available_point,
        ];
        for (const value of candidates) {
            if (value !== undefined && value !== null && value !== "") return toInt(value, 0);
        }
        return null;
    }

    async getPoints() {
        const ret = await this.request({
            method: "POST",
            url: `${API_BASE}/front/member/personalCenter`,
            data: { t: Date.now() },
            withAuth: true,
            withTmpToken: false,
        });
        const point = this.extractPoint(ret);
        if (point === null) throw new ApiError("个人中心未返回积分字段");
        return point;
    }

    async getSignCalendar() {
        const ret = await this.request({
            method: "GET",
            url: `${INTEGRAL_BASE}/user/sign/calendar`,
            params: {},
            withAuth: true,
            withTmpToken: false,
        });
        return ret.data || {};
    }

    async sign() {
        try {
            const ret = await this.request({
                method: "POST",
                url: `${INTEGRAL_BASE}/scenePoint/scene/point`,
                data: { scene: "sign", brandCode: BRAND_CODE },
                withAuth: true,
                withTmpToken: false,
            });
            const data = ret.data;
            const gain =
                typeof data === "number" || (typeof data === "string" && /^-?\d+$/.test(data.trim()))
                    ? toInt(data, 0)
                    : data && (data.point ?? data.gain ?? data.integral ?? data.rewardPoint);
            return {
                status: "success",
                gain: gain === undefined ? null : toInt(gain, 0),
                message: ret.message || "",
            };
        } catch (e) {
            if (isAuthError(e)) throw e;
            const msg = e.message || String(e);
            if (isAlreadyMessage(msg)) return { status: "already", gain: null, message: msg };
            throw e;
        }
    }

    async optional(label, fn, fallback = null) {
        try {
            return await fn();
        } catch (e) {
            if (isAuthError(e)) throw e;
            log(`   ⚠️ [${label}] ${short(e.message || e, 70)}`);
            return fallback;
        }
    }

    async safe(label, fn, quiet = false) {
        try {
            return await fn();
        } catch (e) {
            if (isAuthError(e)) throw e;
            if (!quiet) log(`   ⚠️ [${label}] ${short(e.message || e, 70)}`);
            return null;
        }
    }

    async getTaskList() {
        let ret;
        try {
            ret = await this.request({
                method: "POST",
                url: `${API_BASE}/front/member/selectPointTask`,
                data: { brandCode: BRAND_CODE },
                withAuth: true,
                withTmpToken: false,
            });
        } catch (e) {
            if (isAuthError(e)) throw e;
            if (!/HTTP 405/.test(e.message || "")) throw e;
            ret = await this.request({
                method: "GET",
                url: `${API_BASE}/front/member/selectPointTask`,
                params: { brandCode: BRAND_CODE },
                withAuth: true,
                withTmpToken: false,
            });
        }
        const list = Array.isArray(ret.data)
            ? ret.data
            : ret.data && Array.isArray(ret.data.list)
              ? ret.data.list
              : ret.data && Array.isArray(ret.data.records)
                ? ret.data.records
                : [];
        if (list.length) log(`   📋 [任务] 可接任务 ${list.length} 个`);
        else log("   ℹ️ [任务] 暂无可接任务");
        return list;
    }

    async findPost() {
        for (let pageNum = 1; pageNum <= 5; pageNum++) {
            const ret = await this.safe(
                "帖子列表",
                () =>
                    this.request({
                        method: "POST",
                        url: `${API_BASE}/applet/waterfall/newWaterfall`,
                        data: { source: 1, pageNum, pageSize: 6 },
                        withAuth: true,
                        withTmpToken: false,
                    }),
                true
            );
            if (!ret || Number(ret.code) !== 0) break;
            const items = Array.isArray(ret.data) ? ret.data : (ret.data && ret.data.list) || [];
            if (!items.length) break;
            for (const post of items) {
                if (!post || post.id === undefined || post.id === null) continue;
                const detail = await this.safe(
                    "帖子详情",
                    () =>
                        this.request({
                            method: "POST",
                            url: `${API_BASE}/front/postOrder/postOrderDetail`,
                            data: { id: Number(post.id) },
                            withAuth: true,
                            withTmpToken: false,
                        }),
                    true
                );
                if (!detail || Number(detail.code) !== 0 || !detail.data) continue;
                const likeStatus = detail.data.likeStatus;
                const collectStatus = detail.data.collectStatus;
                const shareStatus = detail.data.shareStatus;
                const incomplete =
                    !isDoneStatus(likeStatus) ||
                    !isDoneStatus(collectStatus) ||
                    (shareStatus !== null && shareStatus !== undefined && !isDoneStatus(shareStatus));
                if (incomplete) {
                    const title = short(post.title || `帖子 ${post.id}`, 24);
                    log(`   🔍 [任务] 找到可互动帖子：「${title}」`);
                    return post;
                }
            }
        }
        return null;
    }

    async pushEvent(eventId, content, targetId, targetName, businessId, businessName) {
        await this.safe(
            "事件上报",
            () =>
                this.request({
                    method: "POST",
                    url: `${API_BASE}/front/member/pushEvent`,
                    data: { eventId, content, targetId, targetName, businessId, businessName },
                    withAuth: true,
                    withTmpToken: false,
                }),
            true
        );
    }

    async insertFootPoint(buriedPointLogo, subordinateTerminal, businessName, businessCode, currentPageLink) {
        await this.safe(
            "埋点上报",
            () =>
                this.request({
                    method: "POST",
                    url: `${API_BASE}/front/foot/point/insertFootPoint`,
                    data: {
                        brandCode: BRAND_CODE,
                        buriedPointLogo,
                        subordinateTerminal,
                        businessName: businessName || "",
                        businessCode: businessCode || "",
                        currentPageLink: currentPageLink || "",
                    },
                    withAuth: true,
                    withTmpToken: false,
                }),
            true
        );
    }

    async likeSendPoint(postOrderId, triggerType, content, forwardType) {
        const data = { postOrderId: Number(postOrderId), triggerType, content };
        if (forwardType !== undefined) data.forwardType = forwardType;
        try {
            const ret = await this.request({
                method: "POST",
                url: `${API_BASE}/front/member/likeSendPoint`,
                data,
                withAuth: true,
                withTmpToken: false,
            });
            if (Number(ret.code) !== 0) {
                log(`   ⚠️ [积分] 送积分未成功：${content}（code=${ret.code}）`);
                return false;
            }
            return true;
        } catch (e) {
            if (isAuthError(e)) throw e;
            if (isAlreadyMessage(e.message)) return true;
            log(`   ⚠️ [积分] 送积分异常：${content}（${short(e.message, 50)}）`);
            return false;
        }
    }

    async likePost(post) {
        const postId = Number(post.id);
        const title = short(post.title || post.id, 24);
        await this.pushEvent("c_showhome_like", "晒家-点赞", "300001", "晒家-点赞", String(postId), title);

        const likeRet = await this.safe("点赞", () =>
            this.request({
                method: "POST",
                url: `${API_BASE}/front/postOrder/like`,
                data: { id: postId },
                withAuth: true,
                withTmpToken: false,
            }),
            true
        );
        let action = "success";
        if (!likeRet) action = "error";
        else if (Number(likeRet.code) !== 0 || isAlreadyMessage(likeRet.message)) action = "already";

        await this.insertFootPoint("do_good_btn", "会员小程序", "", "", "");
        const reward = await this.likeSendPoint(postId, 1, "点赞");
        if (action === "success") log(`   ✅ [任务] 点赞：${title}`);
        else if (action === "already") log("   ℹ️ [任务] 点赞：今日已完成");
        else log(`   ⚠️ [任务] 点赞失败：${title}`);
        return { status: action, reward };
    }

    async collectPost(post) {
        const postId = Number(post.id);
        const title = short(post.title || post.id, 24);
        const collectRet = await this.safe("收藏", () =>
            this.request({
                method: "POST",
                url: `${API_BASE}/front/postOrder/collect`,
                data: { id: postId },
                withAuth: true,
                withTmpToken: false,
            }),
            true
        );
        let action = "success";
        if (!collectRet) action = "error";
        else if (Number(collectRet.code) !== 0 || isAlreadyMessage(collectRet.message)) action = "already";

        await this.insertFootPoint("buriedPointLogo", "会员小程序", "", "", "");
        const reward = await this.likeSendPoint(postId, 2, "收藏");
        if (action === "success") log(`   ✅ [任务] 收藏：${title}`);
        else if (action === "already") log("   ℹ️ [任务] 收藏：今日已完成");
        else log(`   ⚠️ [任务] 收藏失败：${title}`);
        return { status: action, reward };
    }

    async sharePost(post) {
        const postId = Number(post.id);
        const title = short(post.title || post.id, 24);
        const shareRet = await this.safe("分享", () =>
            this.request({
                method: "POST",
                url: `${API_BASE}/front/postOrder/share`,
                data: { id: postId },
                withAuth: true,
                withTmpToken: false,
            }),
            true
        );
        let action = "success";
        if (!shareRet) action = "error";
        else if (Number(shareRet.code) !== 0 || isAlreadyMessage(shareRet.message)) action = "already";

        await this.insertFootPoint("share_friend_btn", "会员小程序", "", "", "");
        const reward = await this.likeSendPoint(postId, 3, "微信好友转发", 2);
        if (action === "success") log(`   ✅ [任务] 分享：${title}`);
        else if (action === "already") log("   ℹ️ [任务] 分享：今日已完成");
        else log(`   ⚠️ [任务] 分享失败：${title}`);
        return { status: action, reward };
    }

    async communityTasks() {
        if (!COMMUNITY_ENABLED) {
            log("   ℹ️ [任务] 社区互动已关闭（GJJJ_COMMUNITY=0）");
            return { status: "disabled", message: "已关闭", okCount: 0 };
        }
        const post = await this.findPost();
        if (!post) {
            log("   ℹ️ [任务] 暂无可互动帖子");
            return { status: "already", message: "暂无可互动帖子", okCount: 0 };
        }
        const title = short(post.title || post.id, 28);
        log(`   📝 [任务] 社区互动帖子：「${title}」`);

        const like = await this.likePost(post);
        await randomDelay(1, 2);
        const collect = await this.collectPost(post);
        await randomDelay(1, 2);
        const share = await this.sharePost(post);
        const results = [like, collect, share];
        const okCount = results.filter((item) => item.status === "success" || item.status === "already").length;
        const mark = (item) =>
            item.status === "success" ? "✓" : item.status === "already" ? "已" : "✗";
        const message = `社区互动 赞${mark(like)} / 藏${mark(collect)} / 享${mark(share)}（${okCount}/3）`;
        if (okCount === 3) log(`   ✅ [任务] ${message}`);
        else log(`   ⚠️ [任务] ${message}`);
        return { status: okCount === 3 ? "success" : "partial", message, okCount, like, collect, share };
    }

    async run() {
        let result = this.baseResult();
        for (let attempt = 0; attempt < 2; attempt++) {
            result = this.baseResult();
            try {
                const loginSource = await this.ensureLogin(attempt === 0);
                result.loginSource = loginSource;
                result.user = this.userText || "-";

                const pStart = await this.optional("积分查询", () => this.getPoints(), null);
                result.pointBefore = pStart;
                if (pStart !== null) log(`   💰 [积分] 当前 ${pStart}`);

                const cal = await this.optional("签到日历", () => this.getSignCalendar(), null);
                if (cal && cal.signCount !== undefined && cal.signCount !== null) {
                    result.signTotal = toInt(cal.signCount, 0);
                    log(`   📅 [签到] 累计 ${result.signTotal} 天`);
                }

                let signRes = null;
                let cal2 = cal;
                const signed = cal ? isTrueValue(cal.isTodaySigned) : null;
                if (signed !== true) {
                    signRes = await this.sign();
                    cal2 = await this.optional("签到日历", () => this.getSignCalendar(), null);
                }

                if (signRes && signRes.status === "already") {
                    result.signStatus = "already";
                    result.signMessage = `今日已签到${result.signTotal !== null ? `（累计${result.signTotal}天）` : ""}`;
                    log(`   ℹ️ [签到] ${result.signMessage}`);
                } else if (signed === true && !signRes) {
                    result.signStatus = "already";
                    result.signMessage = `今日已签到${result.signTotal !== null ? `（累计${result.signTotal}天）` : ""}`;
                    log(`   ℹ️ [签到] ${result.signMessage}`);
                } else {
                    const signConfirmed = cal2 ? isTrueValue(cal2.isTodaySigned) : true;
                    if (!signConfirmed) {
                        result.signStatus = "error";
                        result.signMessage = cal2
                            ? "签到接口返回成功但签到日历未确认"
                            : "签到成功，但签到日历查询失败，无法确认";
                        log(`   ⚠️ [签到] ${result.signMessage}`);
                    } else {
                        result.signStatus = "success";
                        result.signGain = signRes && typeof signRes.gain === "number" ? signRes.gain : 0;
                        if (cal2 && cal2.signCount !== undefined && cal2.signCount !== null) {
                            result.signTotal = toInt(cal2.signCount, result.signTotal ?? 0);
                        }
                        result.signMessage = `签到成功${
                            result.signTotal !== null ? `（累计${result.signTotal}天）` : ""
                        }`;
                        log(`   ✅ [签到] ${result.signMessage}`);
                        if (result.signGain > 0) log(`   🎁 [签到] 奖励 +${result.signGain} 积分`);
                    }
                }

                const tasks = (await this.safe("任务列表", () => this.getTaskList(), true)) || [];
                result.taskCount = Array.isArray(tasks) ? tasks.length : 0;

                result.community = await this.communityTasks();

                let pEnd = pStart;
                if (pStart !== null) {
                    let last = pStart;
                    let stable = 0;
                    for (let i = 0; i < 3; i++) {
                        await sleep(1500 + Math.random() * 500);
                        const pTry = await this.optional("积分刷新", () => this.getPoints(), null);
                        if (pTry === null) continue;
                        pEnd = pTry;
                        if (pTry === last) {
                            stable++;
                            if (pTry !== pStart && stable >= 1) break;
                            if (stable >= 2) break;
                        } else {
                            stable = 0;
                            last = pTry;
                        }
                    }
                }
                result.pointAfter = pEnd;
                if (pStart !== null && pEnd !== null) {
                    const delta = pEnd - pStart;
                    const signGain = result.signStatus === "success" ? result.signGain : 0;
                    const communityGain = delta - signGain;
                    const detail = [];
                    if (signGain !== 0) detail.push(`签到+${signGain}`);
                    if (communityGain !== 0) detail.push(`社区${communityGain >= 0 ? "+" : ""}${communityGain}`);
                    log(
                        `   💰 [积分] ${pStart} → ${pEnd}（本次 ${delta >= 0 ? "+" : ""}${delta}${
                            detail.length ? `，${detail.join("，")}` : ""
                        }）`
                    );
                } else if (pEnd !== null) {
                    log(`   💰 [积分] 当前 ${pEnd}`);
                }

                const signOk = result.signStatus === "success" || result.signStatus === "already";
                result.success = signOk;
                if (!signOk) result.error = result.signMessage || "签到未成功";
            } catch (e) {
                if (isAuthError(e) && attempt === 0) {
                    log("   🔄 [登录] 登录凭证失效，清除缓存重登...");
                    dropCache(this.server, this.ref);
                    this.accessToken = "";
                    this.memberId = "";
                    this.tmpToken = "";
                    await randomDelay(1, 2);
                    continue;
                }
                result.success = false;
                result.error = short(e.message || e, 100);
                if (result.signStatus === "none") {
                    result.signStatus = "error";
                    result.signMessage = result.error;
                }
                log(`   ❌ [失败] ${result.error}`);
                return result;
            }
            return result;
        }
        return result;
    }
}

// ====================== 通知 ======================
async function sendQingLongNotify(title, content) {
    for (const file of [
        "/ql/data/scripts/notify.js",
        "/ql/scripts/notify.js",
        path.join(SCRIPT_DIR, "notify.js"),
        path.join(SCRIPT_DIR, "SendNotify.js"),
    ]) {
        try {
            if (!fs.existsSync(file)) continue;
            const mod = require(file);
            const fn = (typeof mod === "function" && mod) || mod.sendNotify || mod.send;
            if (typeof fn === "function") {
                const ret = fn(title, content);
                if (ret && typeof ret.then === "function") await ret;
                return true;
            }
        } catch {
            continue;
        }
    }
    return false;
}

async function sendPushPlus(title, content) {
    const token = (
        process.env.PUSHPLUS_TOKEN ||
        process.env.PLUSPLUS_TOKEN ||
        process.env.PUSH_PLUS_TOKEN ||
        ""
    ).trim();
    if (!token) return false;
    try {
        await axios.post(
            "https://www.pushplus.plus/send",
            { token, title, content, template: "txt" },
            { timeout: 15000, proxy: false }
        );
        return true;
    } catch {
        return false;
    }
}

function pointText(r) {
    if (r.pointBefore === null && r.pointAfter === null) return "-";
    if (r.pointBefore === null) return `${r.pointAfter}`;
    const after = r.pointAfter === null ? r.pointBefore : r.pointAfter;
    const delta = after - r.pointBefore;
    const detail = [];
    if (r.signStatus === "success" && r.signGain) detail.push(`签到+${r.signGain}`);
    const communityGain = delta - (r.signStatus === "success" ? r.signGain : 0);
    if (communityGain !== 0) detail.push(`社区${communityGain >= 0 ? "+" : ""}${communityGain}`);
    return `${r.pointBefore} → ${after}（本次 ${delta >= 0 ? "+" : ""}${delta}${
        detail.length ? `，${detail.join("，")}` : ""
    }）`;
}

function taskText(r) {
    if (!r.community) return "-";
    return r.community.message || r.community.status;
}

function buildNotify(results) {
    return results
        .map((r) => {
            const lines = [
                `${r.success ? "✅" : "❌"} 账号${r.index} 🛋️ ${r.ref}${r.note ? `（${r.note}）` : ""}`,
                `• 登录：${r.loginSource}`,
                `• 用户：${r.user}`,
                `• 签到：${r.signMessage}`,
                `• 任务：${taskText(r)}`,
                `• 积分：${pointText(r)}`,
            ];
            if (!r.success) lines.push(`• 失败：${r.error}`);
            return lines.join("\n");
        })
        .join("\n\n");
}

// ====================== 主入口 ======================
(async () => {
    if (!SERVERS.length) {
        log("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识[#备注]，多账号换行分隔）");
        return;
    }
    const valid = [];
    for (const raw of SERVERS) {
        const parsed = parseYybGoEntry(raw);
        if (parsed.server && parsed.ref) valid.push(raw);
    }
    if (!valid.length) {
        log("❌ YYB_SERVER 无有效账号（格式：地址@标识[#备注]）");
        return;
    }
    SERVERS.length = 0;
    SERVERS.push(...valid);

    boxTop("🛋️ 顾家家居 每日任务");
    boxLine("🕒 启动时间", nowText());
    boxLine("🔢 账号数量", `${SERVERS.length} 个`);
    boxLine("💾 缓存", "gjjj_token_cache.json");
    boxLine("📌 社区互动", COMMUNITY_ENABLED ? "开启" : "关闭");
    boxBottom();

    const results = [];
    for (let i = 0; i < SERVERS.length; i++) {
        const entry = parseYybGoEntry(SERVERS[i]);
        const title = `标识 ${entry.ref || "-"}${entry.note ? `（${entry.note}）` : ""}`;
        accountFrame(i + 1, SERVERS.length, title, SERVERS[i]);

        const task = new Task(SERVERS[i], i + 1);
        let result;
        try {
            result = await task.run();
        } catch (e) {
            result = task.baseResult();
            result.success = false;
            result.error = short(e.message || e, 100);
            log(`   ❌ [失败] ${result.error}`);
        }
        log(result.success ? "   ✅ [完成] 该账号任务执行完成" : "   ❌ [完成] 该账号存在失败项");
        results.push(result);
        hr();
        if (i < SERVERS.length - 1) {
            log("   ⏳ 等待随机延时后执行下一个账号...");
            await randomDelay(2, 4);
        }
    }

    for (const r of results) {
        log(`${r.success ? "✅" : "❌"} 【账号 ${r.index} · 标识 ${r.ref}${r.note ? `（${r.note}）` : ""}】`);
        log(`   🔐 [登录] ${r.loginSource}`);
        log(`   👤 [用户] ${r.user}`);
        log(`   📅 [签到] ${r.signMessage}`);
        if (r.signStatus === "success" && r.signGain > 0) log(`   🎁 [签到] 奖励 +${r.signGain} 积分`);
        const taskIcon = r.community && r.community.status === "success" ? "✅" : r.community && r.community.status === "partial" ? "⚠️" : "ℹ️";
        log(`   ${taskIcon} [任务] ${taskText(r)}`);
        log(`   💰 [积分] ${pointText(r)}`);
        if (!r.success) log(`   ⚠️ [失败] ${r.error || "未知错误"}`);
    }

    const ok = results.filter((r) => r.success).length;
    boxTop("🏁 🛋️ 顾家家居 执行汇总");
    boxLine("📊 执行结果", `成功 ${ok} / 失败 ${results.length - ok} / 共 ${results.length}`);
    boxLine("🕒 结束时间", nowText());
    boxBottom();

    if (NOTIFY_ENABLED) {
        const content = buildNotify(results);
        if (await sendQingLongNotify(`${APP.name} 任务结果`, content)) {
            log("   📮 [通知] 已调用青龙 notify.py");
        } else {
            log("   ℹ️ [通知] 未找到青龙 notify.py");
        }
        if (await sendPushPlus(`${APP.name} 任务结果`, content)) {
            log("   📮 [通知] PushPlus 已发送");
        } else {
            log("   ℹ️ [推送] 未配置 PUSHPLUS_TOKEN，跳过 PushPlus");
        }
    } else {
        log("   ℹ️ [通知] GJJJ_NOTIFY=0，已关闭通知");
    }
})().catch((e) => {
    log(`❌ 脚本异常：${short(e && (e.stack || e.message || e), 300)}`);
    process.exitCode = 0;
});
