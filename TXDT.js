// name: 腾讯地图
// cron: 0 8,20 * * *
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const APP = { name: "腾讯地图", appid: "wx7643d5f831302ab0", version: 545 };

const MINI_LOGIN_BASE = "https://miniapp.map.qq.com";
const MAP_BASE = "https://mmapgwh.map.qq.com";
const LOGIN_ACCESS_KEY = "1";
const LOGIN_SECRET_KEY = "4300eec60bedec22a73408a0d76b03ec";
const TMAP_SECRET = "3a9875e795c3ecff15f617085e72d4cc";
const CHECKIN_TOKEN = "e643d512f085d621bf6c9e80310d0498";
const ACTIVITY_ID = 1721983577;
const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

const BOX_WIDTH = 48;
const BOX_INNER = 46;

const NOTIFY_ENABLED = String(process.env.TXDT_NOTIFY || "1").trim() !== "0";
const LOTTERY_ENABLED = String(process.env.TXDT_LOTTERY || "1").trim() !== "0";
const WITHDRAW_ENABLED = String(process.env.TXDT_WITHDRAW || "1").trim() !== "0";
const LOTTERY_MAX = Math.max(0, parseInt(process.env.TXDT_LOTTERY_MAX || "0", 10) || 0);

const SCRIPT_DIR = __dirname;
const TOKEN_CACHE_DIR = path.join(SCRIPT_DIR, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "txdt_token_cache.json");

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
    let value = String(text);
    while (displayWidth(value) > width) value = value.slice(0, -1);
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

function short(value, max = 300) {
    if (value === undefined || value === null) return "";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return text.length > max ? text.slice(0, max) + "…" : text;
}

function mask(value) {
    const text = String(value || "");
    return text.length <= 8 ? text : `${text.slice(0, 4)}***${text.slice(-4)}`;
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function md5(value) {
    return crypto.createHash("md5").update(String(value)).digest("hex");
}

function sha256(value) {
    return crypto.createHash("sha256").update(String(value)).digest("hex");
}

function uuid() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
        const n = (Math.random() * 16) | 0;
        return (char === "x" ? n : (n & 3) | 8).toString(16);
    });
}

function sortedQuery(data) {
    const normalized = {};
    Object.keys(data)
        .sort()
        .forEach((key) => {
            if (data[key] !== undefined && data[key] !== null) normalized[key] = data[key];
        });
    return Object.keys(normalized)
        .map((key) => `${key}=${normalized[key]}`)
        .join("&");
}

function formatCoin(value) {
    const num = Number(value || 0);
    return `${num}(${(num / 100).toFixed(2)})`;
}

function coinNumber(value) {
    const num = Number(value || 0);
    return Number.isFinite(num) ? num : 0;
}

function yuan(fen) {
    return (coinNumber(fen) / 100).toFixed(2);
}

// ====================== 账号解析 ======================
function parseYybGoEntry(rawValue) {
    let value = String(rawValue || "").trim();
    let note = "";
    if (!value) return { server: "", ref: "", note: "" };
    const hash = value.indexOf("#");
    if (hash !== -1) {
        note = value.slice(hash + 1).trim();
        value = value.slice(0, hash).trim();
    }
    const atIndex = value.indexOf("@");
    if (atIndex === -1) return { server: "", ref: "", note };
    let server = value.slice(0, atIndex).trim();
    let ref = value.slice(atIndex + 1).trim();
    if (ref.indexOf("#") !== -1) ref = ref.split("#")[0].trim();
    if (server.startsWith("http://")) server = server.slice(7);
    else if (server.startsWith("https://")) server = server.slice(8);
    server = server.replace(/\/+$/, "");
    if (!server || !ref) return { server: "", ref: "", note };
    return { server, ref, note };
}

// ====================== 缓存 ======================
function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        const data = JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf-8"));
        return data && typeof data === "object" ? data : {};
    } catch (e) {
        log(`   ⚠️ [缓存] 读取失败：${short(e.message, 60)}`);
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
    return !!value && typeof value === "object" && !!value.user_id && !!value.openid;
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

function saveCache(server, ref, loginInfo) {
    const cache = readTokenCache();
    cache[cacheKeyOf(server, ref)] = Object.assign({}, loginInfo, { updatedAt: nowText() });
    writeTokenCache(cache);
}

function dropCache(server, ref) {
    const cache = readTokenCache();
    for (const key of Object.keys(cache)) {
        if (cacheMatches(key, server, ref)) delete cache[key];
    }
    writeTokenCache(cache);
}

// ====================== YYB 取码 ======================
async function getWxCode(serverEntry) {
    const { server, ref } = parseYybGoEntry(serverEntry);
    if (!server || !ref) {
        log("   ❌ [取码] 账号格式异常，跳过");
        return null;
    }
    const url = "http://" + server + "/wxapp/getCode";
    try {
        const { data } = await axios.post(url, { ref, app_id: APP.appid }, { timeout: 20000, proxy: false });
        const code = data && data.data && data.data.result && data.data.result.code;
        if (!data || data.code !== 0 || !code) {
            log(`   ❌ [取码] 获取 code 失败：${short(data)}`);
            return null;
        }
        log("   ✅ [取码] code 获取成功");
        return code;
    } catch (e) {
        log(`   ❌ [取码] 获取 code 异常：${short(e.message, 80)}`);
        return null;
    }
}

async function getCodeWithRetry(serverEntry) {
    for (let i = 0; i < 2; i++) {
        const code = await getWxCode(serverEntry);
        if (code) return code;
        if (i === 0) {
            log("   🔁 [取码] 失败，2 秒后重试");
            await sleep(2000);
        }
    }
    return null;
}

// ====================== 签名与请求 ======================
function loginSign({ appId, sessionId = "-1", openId, userId, postBody }) {
    const reqId = md5(`${Math.random()} ${Date.now()}`);
    const reqTime = Date.now().toString().slice(0, 10);
    const signParams = {
        appId,
        reqId,
        reqTime,
        userId,
        openID: openId,
        sessionID: sessionId,
        accessKey: LOGIN_ACCESS_KEY,
        businessStr: JSON.stringify(postBody),
    };
    const signText = `${sortedQuery(signParams)}&secretKey=${LOGIN_SECRET_KEY}`;
    const headers = {
        "mapservice-sign-version": "v2",
        "mapservice-sign": sha256(signText),
        "mapservice-reqid": reqId,
        "mapservice-reqtime": reqTime,
        "mapservice-appid": appId,
        "mapservice-accesskey": LOGIN_ACCESS_KEY,
        "mapservice-sessionid": sessionId,
    };
    if (sessionId && sessionId !== "-1") {
        headers["mapservice-openid"] = openId;
        headers["mapservice-userid"] = userId;
    }
    return headers;
}

function mapH5Sign(apiPath, user) {
    const reqId = uuid();
    const reqTime = Date.now();
    const normalizedPath = apiPath.split("?")[0];
    const signBase = `mapinst=0&mapnonce=0&reqid=${reqId}&reqtime=${reqTime}`;
    const defaultSign = md5(`${signBase}${normalizedPath}0${TMAP_SECRET}`);
    const headers = {
        "tmap-reqid": reqId,
        "tmap-reqtime": reqTime,
        "tmap-userid": Number(user.user_id) || Number(user.userId) || 0,
        "tmap-login-ssid": user.session_id || user.sessionId || 0,
        "tmap-imei": 0,
        "tmap-qimei": 0,
        "tmap-qimei36": 0,
        "tmap-nonce": 0,
        "tmap-install-id": 0,
        "tmap-sign": 0,
        "tmap-default-sign": defaultSign,
        "tmap-app-version": 0,
        "tmap-channel": 0,
        "tmap-engine": "web",
        "tmap-mini-login-ssid": user.map_session_id || user.mapSessionId || "",
        "tmap-app-id": user.appId || APP.appid,
    };
    if (user.openid || user.openId) headers["tmap-openid"] = user.openid || user.openId;
    return headers;
}

function checkinHeader(user) {
    const requestId = uuid();
    const timestamp = Math.floor(Date.now() / 1000);
    const signText = `request_id=${requestId}&from_source=${APP.appid}&timestamp=${timestamp}&token=${CHECKIN_TOKEN}`;
    return {
        user_id: user.openid || user.openId,
        from_source: APP.appid,
        request_id: requestId,
        timestamp,
        sign: sha256(signText).toUpperCase(),
    };
}

async function request(options) {
    const res = await axios.request({
        timeout: 20000,
        validateStatus: () => true,
        ...options,
        headers: {
            "User-Agent": USER_AGENT,
            Accept: "application/json, text/plain, */*",
            Referer: `https://servicewechat.com/${APP.appid}/${APP.version}/page-frame.html`,
            ...(options.headers || {}),
        },
    });
    return { status: res.status, headers: res.headers || {}, data: res.data };
}

const AUTH_WORDS = ["登录", "token", "未授权", "失效", "过期", "凭证", "401", "403"];

function isAuthFail(status, body) {
    if (status === 401 || status === 403) return true;
    const text = short(body, 200).toLowerCase();
    return AUTH_WORDS.some((word) => text.indexOf(word.toLowerCase()) !== -1);
}

// ====================== 业务类 ======================
class TencentMap {
    constructor(rawAccount, index) {
        const parsed = parseYybGoEntry(rawAccount);
        this.raw = rawAccount;
        this.server = parsed.server;
        this.ref = parsed.ref;
        this.note = parsed.note;
        this.index = index;
        this.loginInfo = {};
        this.userInfo = {};
        this.needRelogin = false;
        this.lastError = "";
    }

    title() {
        return `标识 ${this.ref}` + (this.note ? `（${this.note}）` : "");
    }

    source() {
        return `${this.server}@${this.ref}` + (this.note ? `#${this.note}` : "");
    }

    async miniLogin() {
        const code = await getCodeWithRetry(this.raw);
        if (!code) throw new Error("取码失败");
        const body = {
            seqid: uuid(),
            app_id: APP.appid,
            auth_code: code,
            devHeader: {},
        };
        const { status, data } = await request({
            method: "POST",
            url: `${MINI_LOGIN_BASE}/minLogin/v2/login`,
            headers: {
                "content-type": "application/json",
                ...loginSign({ appId: APP.appid, postBody: body }),
            },
            data: body,
        });
        if (status !== 200 || Number(data && data.err_code) !== 0) {
            throw new Error(`登录失败 HTTP ${status}: ${short(data)}`);
        }
        this.loginInfo = Object.assign({}, data, { appId: APP.appid });
        this.needRelogin = false;
        log(`   ✅ [登录] 成功 userId=${data.user_id || "未知"} openid=${mask(data.openid)}`);
        return this.loginInfo;
    }

    async queryUser() {
        const user = this.loginInfo;
        const body = {
            seqid: uuid(),
            app_id: APP.appid,
            userId: user.user_id,
            openId: user.openid,
            source: "mini-tencentmap",
        };
        const { status, data } = await request({
            method: "POST",
            url: `${MINI_LOGIN_BASE}/minLogin/v2/getUserInfo`,
            headers: {
                "content-type": "application/json",
                ...loginSign({
                    appId: APP.appid,
                    sessionId: user.session_id,
                    userId: user.user_id,
                    openId: user.openid,
                    postBody: body,
                }),
            },
            data: body,
        });
        if (status === 401 || status === 403 || Number(data && data.err_code) === 10205) {
            this.needRelogin = true;
            this.lastError = `凭据不完整（HTTP ${status} / err_code ${data && data.err_code}）`;
            return { ok: false, authFail: true };
        }
        if (status !== 200 || Number(data && data.err_code) !== 0) {
            this.lastError = `用户信息查询失败 HTTP ${status}: ${short(data)}`;
            log(`   ⚠️ [用户] ${this.lastError}`);
            return { ok: false, authFail: isAuthFail(status, data) };
        }
        this.userInfo = data || {};
        log(`   👤 [会员] ${data.nickname || "微信用户"}，userId=${data.userid || user.user_id}`);
        return { ok: true, authFail: false };
    }

    async mapApi(apiPath, data) {
        const { status, data: body } = await request({
            method: "POST",
            url: `${MAP_BASE}${apiPath}`,
            headers: {
                "content-type": "application/json",
                ...checkinHeader(this.loginInfo),
                ...mapH5Sign(apiPath, this.loginInfo),
            },
            data,
        });
        const pass = status === 200 && (Number(body && body.code) === 0 || (body && body.message === "ok"));
        if (!pass) {
            const reason = body && (body.message || body.msg);
            const err = new Error(`${apiPath} HTTP ${status}: ${reason || short(body)}`);
            err.authFail = isAuthFail(status, body);
            throw err;
        }
        return body.data || {};
    }

    async queryBalance(prefix = "现金余额") {
        const data = await this.mapApi("/activity/v1/withdraw/home", {
            activity_id: ACTIVITY_ID,
            game_id: 4,
            rule_id: "tencent_map_withdraw",
        });
        log(
            `   💰 [余额] ${prefix}：金币=${formatCoin(data.coins)}，可提现=${formatCoin(data.withdrawable_amount)}，门槛=${formatCoin(data.current_withdraw_threshold)}，奖池=${formatCoin(data.jackpot_amount)}`
        );
        return data;
    }

    async queryAssets() {
        const data = await this.mapApi("/activity/v1/assert/home", { activity_id: ACTIVITY_ID });
        log(
            `   🎁 [资产] 金币=${formatCoin(data.coins)}，优惠券=${data.coupons_total || 0}，抽奖券=${data.lottery_ticket_total || 0}`
        );
        return data;
    }

    async lotteryDetail() {
        const data = await this.mapApi("/activity/v1/lottery/detail", {
            activity_id: ACTIVITY_ID,
            game_id: 3,
            rule_id: "tencent_map_lottery",
        });
        return Number(data.available_ticket_number || 0);
    }

    async lotteryOnce() {
        const data = await this.mapApi("/activity/v1/lottery", { activity_id: ACTIVITY_ID, game_id: 3 });
        const prizes = Array.isArray(data.prizes) ? data.prizes : [];
        return prizes.map((item) => ({
            name: item.name || item.type || "奖励",
            amount: item.amount == null ? "" : item.amount,
        }));
    }

    async runLottery() {
        if (!LOTTERY_ENABLED) {
            log("   ℹ️ [抽奖] TXDT_LOTTERY=0，已关闭");
            return { draws: 0, wins: [], tickets: 0, skipped: true };
        }
        const tickets = await this.lotteryDetail();
        if (!tickets) {
            log("   ℹ️ [抽奖] 暂无抽奖券，跳过");
            return { draws: 0, wins: [], tickets: 0 };
        }
        const target = LOTTERY_MAX > 0 ? Math.min(tickets, LOTTERY_MAX) : tickets;
        log(`   🎰 [抽奖] 持有 ${tickets} 张，本次计划抽 ${target} 次${LOTTERY_MAX > 0 ? `（上限 ${LOTTERY_MAX}）` : ""}`);
        const wins = [];
        let draws = 0;
        for (let i = 1; i <= target; i++) {
            try {
                const prizes = await this.lotteryOnce();
                draws += 1;
                for (const prize of prizes) wins.push(prize);
                const text = prizes.length ? prizes.map((p) => `${p.name}${p.amount === "" ? "" : `×${p.amount}`}`).join("，") : "无奖励";
                if (i <= 3 || i % 20 === 0 || i === target) {
                    log(`   🎁 [抽奖] 第 ${i}/${target} 次：${text}`);
                }
            } catch (e) {
                if (e.authFail) throw e;
                log(`   ⚠️ [抽奖] 第 ${i}/${target} 次失败：${short(e.message, 100)}`);
                break;
            }
            if (i < target) await sleep(1200 + Math.floor(Math.random() * 800));
        }
        const summary = this.winSummary(wins);
        log(`   🎰 [抽奖] 完成 ${draws} 次${summary ? `，累计：${summary}` : "，暂无奖励"}`);
        return { draws, wins, tickets, remaining: Math.max(0, tickets - draws) };
    }

    winSummary(wins) {
        const counts = {};
        for (const item of wins) {
            const key = `${item.name}${item.amount === "" ? "" : `×${item.amount}`}`;
            counts[key] = (counts[key] || 0) + 1;
        }
        return Object.keys(counts)
            .map((key) => `${key}${counts[key] > 1 ? `（${counts[key]}次）` : ""}`)
            .join("，");
    }

    async withdraw() {
        if (!WITHDRAW_ENABLED) {
            log("   ℹ️ [提现] TXDT_WITHDRAW=0，已关闭");
            return { status: "disabled", amount: 0, threshold: 0 };
        }
        const wallet = await this.mapApi("/activity/v1/withdraw/home", {
            activity_id: ACTIVITY_ID,
            game_id: 4,
            rule_id: "tencent_map_withdraw",
        });
        const amount = coinNumber(wallet.withdrawable_amount);
        const threshold = coinNumber(wallet.current_withdraw_threshold);
        if (amount <= 0) {
            log("   ℹ️ [提现] 可提现金额 0.00 元，跳过");
            return { status: "empty", amount: 0, threshold };
        }
        if (threshold > 0 && amount < threshold) {
            log(`   ℹ️ [提现] 可提现 ${yuan(amount)} 元，未达门槛 ${yuan(threshold)} 元，跳过`);
            return { status: "below", amount, threshold };
        }
        const data = await this.mapApi("/activity/v1/withdraw", { activity_id: ACTIVITY_ID, game_id: 4 });
        log(`   💸 [提现] 已提交提现 ${yuan(amount)} 元${data && data.amount ? `（接口返回 ${yuan(data.amount)} 元）` : ""}`);
        return { status: "ok", amount, threshold };
    }

    todayKey() {
        const now = new Date();
        const year = now.getFullYear();
        const month = `${now.getMonth() + 1}`.padStart(2, "0");
        const day = `${now.getDate()}`.padStart(2, "0");
        return `${year}${month}${day}`;
    }

    async queryCalendar(prefix = "签到状态") {
        const data = await this.mapApi("/activity/v1/checkin/calendar", {
            activity_id: ACTIVITY_ID,
            game_id: 1,
            rule_id: "tencent_map_checkin",
        });
        let list = data.calendar || {};
        if (Array.isArray(list)) {
            list = list.reduce((acc, item) => {
                if (item && item.date) acc[String(item.date).replace(/-/g, "")] = item;
                return acc;
            }, {});
        }
        const today = list[this.todayKey()] || {};
        const prizes = Array.isArray(today.prizes)
            ? today.prizes.map((item) => `${item.name || item.type || "奖励"}:${item.amount == null ? "" : item.amount}`).join("，")
            : "";
        log(`${prefix}：今日${today.checkin ? "已签" : "未签"}，周期已签=${data.checkin_days || 0}/${data.period || 0}${prizes ? `，奖励=${prizes}` : ""}`);
        return { data, today, prizes };
    }

    async checkin() {
        const before = await this.queryCalendar("   📅 [签到] 签到前");
        if (before.today.checkin) {
            log("   ℹ️ [签到] 今日已签到");
            return { ok: true, message: "今日已签到", prizes: before.prizes };
        }
        const data = await this.mapApi("/activity/v1/checkin", {
            activity_id: ACTIVITY_ID,
            game_id: 1,
            rule_id: "tencent_map_checkin",
            nick: this.userInfo.nickname || "微信用户",
        });
        const prizes = Array.isArray(data.prizes)
            ? data.prizes.map((item) => `${item.name || item.type || "奖励"}:${item.amount == null ? "" : item.amount}`).join("，")
            : "";
        log(`   ✅ [签到] 签到成功${prizes ? `，${prizes}` : ""}`);
        return { ok: true, message: "签到成功", prizes: prizes || short(data, 80) };
    }
}

// ====================== 通知 ======================
function sendQinglongNotify(title, content) {
    for (const file of ["/ql/data/scripts/notify.js", "/ql/scripts/notify.js", path.join(SCRIPT_DIR, "notify.js"), path.join(SCRIPT_DIR, "SendNotify.js")]) {
        try {
            if (!fs.existsSync(file)) continue;
            const mod = require(file);
            const fn = (typeof mod === "function" && mod) || mod.sendNotify || mod.send;
            if (typeof fn === "function") {
                fn(title, content);
                return true;
            }
        } catch (e) {
            continue;
        }
    }
    return false;
}

async function sendPushPlus(title, content) {
    const token = (process.env.PUSHPLUS_TOKEN || process.env.PLUSPLUS_TOKEN || process.env.PUSH_PLUS_TOKEN || "").trim();
    if (!token) return false;
    try {
        await axios.post(
            "https://www.pushplus.plus/send",
            { token, title, content, template: "txt" },
            { timeout: 15000, proxy: false }
        );
        return true;
    } catch (e) {
        return false;
    }
}

function lotteryText(r) {
    if (!r.lotteryTickets) return "无抽奖券";
    return `${r.lotteryDraws} 次${r.lotteryWins ? `（${r.lotteryWins}）` : "（无奖励）"}`;
}

function withdrawText(r) {
    if (r.withdrawStatus === "ok") return `已提交 ${yuan(r.withdrawAmount)} 元`;
    if (r.withdrawStatus === "below") return `未达门槛（可提 ${yuan(r.withdrawAmount)} / ${yuan(r.withdrawThreshold)} 元）`;
    if (r.withdrawStatus === "empty") return "可提现 0.00 元，跳过";
    if (r.withdrawStatus === "disabled") return "已关闭";
    if (r.withdrawStatus === "error") return `失败：${r.withdrawError}`;
    return "-";
}

function buildNotify(results) {
    const ok = results.filter((r) => r.success).length;
    const lines = [
        `【${APP.name}】每日签到`,
        `成功 ${ok} / 失败 ${results.length - ok} / 共 ${results.length}`,
        "",
    ];
    for (const r of results) {
        const flag = r.success ? "✅" : "❌";
        lines.push(`${flag} 账号${r.index} ${r.title}：${r.signMessage || r.error || "-"}`);
        lines.push(`   登录：${r.loginSource || "-"}｜金币 ${r.coinsBefore} → ${r.coinsAfter}｜券 ${r.coupons}`);
        lines.push(`   抽奖：${lotteryText(r)}｜提现：${withdrawText(r)}`);
        if (!r.success) lines.push(`   失败：${r.error || "-"}`);
    }
    return lines.join("\n");
}

// ====================== 单账号执行 ======================
async function runAccount(rawAccount, index, total) {
    const bot = new TencentMap(rawAccount, index);
    if (!bot.server || !bot.ref) {
        log(`   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过：${short(rawAccount, 60)}`);
        return { index, title: "格式错误", success: false, error: "账号格式错误", coinsBefore: 0, coinsAfter: 0, coupons: 0 };
    }

    accountFrame(index, total, bot.title(), bot.source());

    let loginSource = "缓存复用";
    const cached = loadCache(bot.server, bot.ref);
    if (cached) {
        bot.loginInfo = Object.assign({}, cached, { appId: APP.appid });
        log(`   💾 [缓存] 复用已保存凭据 userId=${cached.user_id} openid=${mask(cached.openid)}`);
    } else {
        loginSource = "新登录";
        log("   🔄 [登录] 无缓存凭据，执行首次登录");
        await bot.miniLogin();
        saveCache(bot.server, bot.ref, bot.loginInfo);
    }

    let user = await bot.queryUser();
    if (!user.ok && (user.authFail || bot.needRelogin)) {
        if (cached) {
            log("   ⚠️ [校验] 缓存凭据失效，清理缓存后重新登录");
            dropCache(bot.server, bot.ref);
            loginSource = "缓存失效重登";
        } else {
            log("   ⚠️ [校验] 新登录凭据不可用，重新登录一次");
        }
        await bot.miniLogin();
        saveCache(bot.server, bot.ref, bot.loginInfo);
        user = await bot.queryUser();
    }
    if (!user.ok) {
        log(`   ❌ [校验] 登录凭证校验失败：${bot.lastError}`);
        return {
            index,
            title: bot.title(),
            success: false,
            loginSource,
            error: `校验失败：${bot.lastError}`,
            coinsBefore: 0,
            coinsAfter: 0,
            coupons: 0,
            signMessage: "",
        };
    }
    log("   ✅ [校验] 登录凭证校验通过（用户信息接口）");

    let coinsBefore = 0;
    let coinsAfter = 0;
    let coupons = 0;
    let signMessage = "";
    let error = "";
    let lottery = { draws: 0, wins: [], tickets: 0, error: "" };
    let withdraw = { status: "none", amount: 0, threshold: 0 };
    let ticketsLeft = 0;

    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            const balanceBefore = await bot.queryBalance("签到前");
            coinsBefore = coinNumber(balanceBefore.coins);
            await sleep(300);
            const assets = await bot.queryAssets();
            coupons = Number(assets.coupons_total || 0);
            await sleep(300);
            const sign = await bot.checkin();
            signMessage = sign.message;
            await sleep(300);
            try {
                lottery = await bot.runLottery();
            } catch (e) {
                if (e.authFail) throw e;
                lottery.error = short(e.message, 100);
                log(`   ⚠️ [抽奖] 执行失败：${lottery.error}`);
            }
            await sleep(300);
            try {
                withdraw = await bot.withdraw();
            } catch (e) {
                if (e.authFail) throw e;
                withdraw.status = "error";
                withdraw.error = short(e.message, 100);
                log(`   ⚠️ [提现] 执行失败：${withdraw.error}`);
            }
            await sleep(300);
            const assetsAfter = await bot.queryAssets();
            ticketsLeft = Number(assetsAfter.lottery_ticket_total || 0);
            coupons = Math.max(coupons, Number(assetsAfter.coupons_total || 0));
            await sleep(300);
            const balanceAfter = await bot.queryBalance("签到后");
            coinsAfter = coinNumber(balanceAfter.coins);
            await sleep(300);
            await bot.queryCalendar("   📅 [签到] 签到后");
            break;
        } catch (e) {
            bot.lastError = e.message || String(e);
            if (attempt === 0 && e.authFail) {
                log(`   ⚠️ [请求] 接口校验失败，重新登录后重试：${short(bot.lastError, 80)}`);
                dropCache(bot.server, bot.ref);
                await bot.miniLogin();
                saveCache(bot.server, bot.ref, bot.loginInfo);
                loginSource = "接口失效重登";
                const again = await bot.queryUser();
                if (!again.ok) {
                    error = `重新登录后校验失败：${bot.lastError}`;
                    break;
                }
                continue;
            }
            error = bot.lastError;
            break;
        }
    }

    const success = !error && !!signMessage;
    if (success) {
        log("   ✅ [完成] 该账号任务执行完成");
    } else {
        log(`   ⚠️ [完成] ${error || "签到未完成"}`);
    }

    return {
        index,
        title: bot.title(),
        success,
        loginSource,
        nickname: bot.userInfo.nickname || "微信用户",
        signMessage: signMessage || "未签到",
        coinsBefore,
        coinsAfter,
        coupons,
        lotteryDraws: lottery.draws || 0,
        lotteryWins: bot.winSummary(lottery.wins || []),
        lotteryTickets: lottery.tickets || 0,
        lotteryLeft: ticketsLeft,
        lotteryError: lottery.error || "",
        withdrawStatus: withdraw.status,
        withdrawAmount: withdraw.amount || 0,
        withdrawThreshold: withdraw.threshold || 0,
        withdrawError: withdraw.error || "",
        error,
    };
}

// ====================== 主流程 ======================
(async () => {
    const entries = (process.env.YYB_SERVER || "")
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter(Boolean);
    if (!entries.length) {
        log("❌ 未配置环境变量 YYB_SERVER");
        log("格式：YYB Go 服务地址@微信账号标识[#备注]，多账号换行分隔");
        return;
    }

    const valid = entries.filter((entry) => {
        const p = parseYybGoEntry(entry);
        return p.server && p.ref;
    });
    const invalid = entries.filter((entry) => {
        const p = parseYybGoEntry(entry);
        return !p.server || !p.ref;
    });
    if (!valid.length) {
        log("❌ YYB_SERVER 没有可用账号（格式：地址@标识[#备注]）");
        return;
    }

    boxTop(`📍 ${APP.name} 每日签到`);
    boxLine("🕒 启动时间", nowText());
    boxLine("🔢 账号数量", `${valid.length} 个${invalid.length ? `（${invalid.length} 行格式无效）` : ""}`);
    boxLine("💾 缓存", path.basename(TOKEN_CACHE_FILE));
    boxLine("🎰 功能", `签到${LOTTERY_ENABLED ? "｜抽奖" : ""}${WITHDRAW_ENABLED ? "｜自动提现" : ""}`);
    boxBottom();

    for (const line of invalid) {
        log(`   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过：${short(line, 60)}`);
    }

    const results = [];
    for (let i = 0; i < valid.length; i++) {
        try {
            results.push(await runAccount(valid[i], i + 1, valid.length));
        } catch (e) {
            log(`   ❌ [执行] 账号 ${i + 1} 未捕获异常：${short(e.message || e, 100)}`);
            results.push({
                index: i + 1,
                title: valid[i],
                success: false,
                error: `异常 ${short(e.message || e, 100)}`,
                coinsBefore: 0,
                coinsAfter: 0,
                coupons: 0,
                signMessage: "",
            });
        }
        hr();
        if (i < valid.length - 1) {
            log("   ⏳ 等待2秒后执行下一个账号...");
            await sleep(2000);
        }
    }

    log();
    for (const r of results) {
        if (r.success) {
            log(`✅ 【账号 ${r.index} · ${r.title}】`);
            log(`   🔐 [登录] ${r.loginSource || "-"}`);
            log(`   👤 [会员] ${r.nickname || "-"}`);
            log(`   📅 [签到] ${r.signMessage}`);
            log(`   💰 [金币] ${r.coinsBefore} → ${r.coinsAfter}（${coinNumber(r.coinsAfter) - coinNumber(r.coinsBefore) >= 0 ? "+" : ""}${coinNumber(r.coinsAfter) - coinNumber(r.coinsBefore)}）`);
            log(`   🎰 [抽奖] ${lotteryText(r)}${r.lotteryLeft ? `，剩余抽奖券 ${r.lotteryLeft} 张` : ""}`);
            log(`   💸 [提现] ${withdrawText(r)}`);
            log(`   🎁 [资产] 优惠券 ${r.coupons} 张`);
        } else {
            log(`❌ 【账号 ${r.index} · ${r.title}】`);
            log(`   🔐 [登录] ${r.loginSource || "-"}`);
            log(`   📅 [签到] ${r.signMessage || "-"}`);
            log(`   ⚠️ [失败] ${r.error || "未知错误"}`);
        }
    }

    const ok = results.filter((r) => r.success).length;
    const totalDelta = results.reduce((sum, r) => sum + (coinNumber(r.coinsAfter) - coinNumber(r.coinsBefore)), 0);
    boxTop(`🏁 ${APP.name} 执行汇总`);
    boxLine("📊 执行结果", `成功 ${ok} / 失败 ${results.length - ok} / 共 ${results.length}`);
    boxLine("💰 金币总变化", `${totalDelta >= 0 ? "+" : ""}${totalDelta}`);
    boxBottom();

    if (NOTIFY_ENABLED) {
        const content = buildNotify(results);
        if (sendQinglongNotify(`${APP.name} 签到结果`, content)) {
            log("   📮 [通知] 已调用青龙 notify.py");
        } else {
            log("   ℹ️ [通知] 未找到青龙 notify.py");
        }
        if (await sendPushPlus(`${APP.name} 签到结果`, content)) {
            log("   📮 [通知] PushPlus 已发送");
        } else {
            log("   ℹ️ [推送] 未配置 PUSHPLUS_TOKEN，跳过 PushPlus");
        }
    } else {
        log("   ℹ️ [通知] TXDT_NOTIFY=0，已关闭通知");
    }
})().catch((e) => {
    log(`❌ 脚本异常：${short(e && (e.stack || e.message || e), 300)}`);
    process.exitCode = 0;
});
