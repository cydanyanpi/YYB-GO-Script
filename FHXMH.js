// name: 飞鹤星妈会
// cron: 8 15,3 * * *
// 环境变量：FHXMH_GAME=0 关闭闯关；FHXMH_GAME_WAIT_MIN/MAX 随机等待秒（默认30~60）；FHXMH_GAME_LEVEL 指定关卡；
// FHXMH_GAME_SCORE 固定分数（不设则随机）；FHXMH_GAME_SCORE_MIN/MAX 随机区间（默认300~800）；FHXMH_GAME_PLAYS 默认20；
// FHXMH_GAME_ACTIVITY_GUID 活动 GUID（默认 jntkxkaa）；FHXMH_NOTIFY=0 关闭青龙/PushPlus 通知
// 说明：闯关无法真实操作小游戏，脚本按目标分模拟对局并提交成绩（AES 加密与 H5 一致）；分数越高排名越靠前，但异常分值会被后台判定异常并封禁，建议小号先试
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

// Token 缓存
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "fhxmh_token_cache.json");

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf-8")) || {};
    } catch { return {}; }
}

function writeTokenCache(cache) {
    try {
        fs.mkdirSync(TOKEN_CACHE_DIR, { recursive: true });
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf-8");
    } catch (e) { console.log("⚠️ 缓存写入失败:", e.message); }
}
function cacheKey(server, ref) { return `${server}|${ref}`; }

// 静默解析缓存键里的标识：兼容老版本「纯标识」与「地址@标识[#备注]」两种键
function legacyRefOf(key) {
    const value = String(key || "").trim();
    if (!value) return "";
    if (!value.includes("@")) return value;
    let body = value;
    const hashIndex = body.lastIndexOf("#");
    const atIndexAll = body.lastIndexOf("@");
    if (hashIndex !== -1 && hashIndex > atIndexAll) body = body.slice(0, hashIndex);
    const atIndex = body.lastIndexOf("@");
    return atIndex === -1 ? body.trim() : body.slice(atIndex + 1).trim();
}

function removeCacheKey(key, ref) {
    const cache = readTokenCache();
    delete cache[key];
    for (const k of Object.keys(cache)) {
        if (k !== key && legacyRefOf(k) === ref) delete cache[k];
    }
    writeTokenCache(cache);
}

// ====================== YYB Go 账号（环境变量 YYB_SERVER = 地址@微信账号标识，多行） ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
const NOTIFY_ON = String(process.env.FHXMH_NOTIFY ?? "1") !== "0";
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
    if (atIndex === -1) {
        console.log("   ❌ [账号] 格式应为 地址@标识[#备注]，当前值: " + value);
        return { server: "", ref: "", note: "" };
    }
    let server = value.slice(0, atIndex).trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
    const ref = value.slice(atIndex + 1).trim();
    if (!server || !ref) return { server: "", ref: "", note: "" };
    return { server, ref, note };
}

const BOX_WIDTH = 48;
const BOX_INNER = 46;
const _VARIATION = /[\uFE0F\uFE0E\u200D]/g;

function displayWidth(text) {
    return String(text).replace(_VARIATION, "").split("").reduce((n, ch) => n + (ch.codePointAt(0) > 0xFF ? 2 : 1), 0);
}

function padWidth(text, width) {
    let value = String(text);
    while (displayWidth(value) > width) value = value.slice(0, -1);
    return value + " ".repeat(Math.max(0, width - displayWidth(value)));
}

function boxTop(title) { console.log("\n╔" + "═".repeat(BOX_WIDTH) + "╗"); console.log("║  " + padWidth(title, BOX_INNER) + "║"); }
function boxLine(label, value) { console.log("║  " + padWidth(label + ": " + value, BOX_INNER) + "║"); }
function boxBottom() { console.log("╚" + "═".repeat(BOX_WIDTH) + "╝"); }
function accountFrame(index, total, title, source) {
    console.log("\n┌" + "─".repeat(BOX_WIDTH) + "┐");
    console.log("│  " + padWidth("🧩 账号 " + index + " / " + total + "　" + title, BOX_INNER) + "│");
    console.log("│  " + padWidth("🔗 来源: " + source, BOX_INNER) + "│");
    console.log("└" + "─".repeat(BOX_WIDTH) + "┘");
}
function hr() { console.log("\n" + "-".repeat(BOX_WIDTH)); }
function toInt(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? Math.trunc(n) : fallback; }
function brief(value, limit = 90) { const text = String(value ?? "").replace(/\n/g, " "); return text.length <= limit ? text : text.slice(0, limit - 1) + "…"; }
async function captureLogs(fn) {
    const lines = [];
    const original = console.log;
    console.log = (...args) => {
        const line = args.map((arg) => (typeof arg === "string" ? arg : JSON.stringify(arg))).join(" ");
        original("   " + line);
        lines.push(line);
    };
    try { await fn(); } finally { console.log = original; }
    return lines;
}

async function getCode(server) {
    const { server: parsedServer, ref } = parseYybGoEntry(server);
    if (!parsedServer || !ref) return null;
    const url = "http://" + parsedServer + "/wxapp/getCode";
    try {
        const { data } = await axios.post(url, { ref, app_id: 'wxc83b55d61c7fc51d' }, { timeout: 20000, proxy: false });
        const code = data && data.data && data.data.result && data.data.result.code;
        if (!data || data.code !== 0 || !code) {
            console.log(parsedServer + " 获取code失败: " + JSON.stringify(data));
            return null;
        }
        console.log(parsedServer + " 获取code成功");
        return code;
    } catch (e) {
        console.log(parsedServer + " 获取code异常: " + e.message);
        return null;
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

const APP = { name: "飞鹤星妈会", appid: "wxc83b55d61c7fc51d" };

const USER_AGENT =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

function short(value, max = 220) {
    if (value === undefined || value === null) return "";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return text.length > max ? `${text.slice(0, max)}...` : text;
}

function getByPath(obj, path) {
    return String(path)
        .split(".")
        .reduce((cur, key) => (cur && cur[key] !== undefined ? cur[key] : undefined), obj);
}

function findFirst(obj, predicate, depth = 0) {
    if (!obj || depth > 8) return null;
    if (Array.isArray(obj)) {
        for (const item of obj) {
            const found = findFirst(item, predicate, depth + 1);
            if (found) return found;
        }
        return null;
    }
    if (typeof obj === "object") {
        if (predicate(obj)) return obj;
        for (const value of Object.values(obj)) {
            const found = findFirst(value, predicate, depth + 1);
            if (found) return found;
        }
    }
    return null;
}

async function request(options) {
    const res = await axios.request({
        timeout: 20000,
        validateStatus: () => true,
        ...options,
        headers: {
            "User-Agent": USER_AGENT,
            Accept: "application/json, text/plain, */*",
            ...(options.headers || {}),
        },
    });
    return { status: res.status, headers: res.headers || {}, data: res.data };
}

// ====================== 业务逻辑 ======================
const API_BASE = (process.env.FHXMH_API_BASE || "https://momclub.feihe.com/capis").replace(/\/+$/, "");
const GAME_ON = String(process.env.FHXMH_GAME ?? "1") !== "0";
// 鹤小飞超级大闯关真实链路：momclub token -> ca.rrx.cn 换取 rrx JWT -> resactiviy 闯关接口
const RRX_CA = (process.env.FHXMH_RRX_CA || "https://ca.rrx.cn").replace(/\/+$/, "");
const RRX_SITE = process.env.FHXMH_RRX_SITE || "tv23ty";
const RRX_MALL = process.env.FHXMH_RRX_MALL || "xdag4i";
const RRX_ACT = process.env.FHXMH_GAME_ACTIVITY_GUID || "jntkxkaa";
const RRX_CHANNEL = process.env.FHXMH_RRX_CHANNEL || "2";
const RRX_PCS = process.env.FHXMH_RRX_PCS || "7c9a359609ec215d"; // H5 AES key/iv（window.RRX_WSITE_INFO.pcs）
const GAME_LEVEL_WANT = Number(process.env.FHXMH_GAME_LEVEL || 0); // 0 = 自动取可玩关卡
const GAME_WAIT_MIN = Math.max(5, Math.min(300, Number(process.env.FHXMH_GAME_WAIT_MIN || 30))); // 每局随机等待下限
const GAME_WAIT_MAX = Math.max(GAME_WAIT_MIN, Math.min(300, Number(process.env.FHXMH_GAME_WAIT_MAX || 60))); // 上限
const GAME_SCORE = Number(process.env.FHXMH_GAME_SCORE || 0); // 0 = targetScore×10（分数越高排名越靠前，可用 FHXMH_GAME_SCORE 直接指定）
const GAME_DEBUG = String(process.env.FHXMH_DEBUG ?? "0") === "1";
const GAME_SCORE_MIN = Math.max(0, Number(process.env.FHXMH_GAME_SCORE_MIN || 300)); // 随机下限，不低于 300
const GAME_SCORE_MAX = Math.max(GAME_SCORE_MIN, Number(process.env.FHXMH_GAME_SCORE_MAX || 800)); // 随机上限
const GAME_PLAYS = Math.max(1, Math.min(20, Number(process.env.FHXMH_GAME_PLAYS || 20))); // 默认一次跑满 20 局

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781 MiniProgramEnv/Windows WindowsWechat/WMPF";
const RRX_INFO = (process.env.FHXMH_RRX_INFO || "https://resinfo.rrx.cn").replace(/\/+$/, "");
const RRX_ACT_BASE = (process.env.FHXMH_RRX_ACT_BASE || "https://resactiviy.rrx.cn").replace(/\/+$/, "");
const RRX_GAME_BASE = `${RRX_ACT_BASE}/game/gameLevelView`;

function aesZeroPad(text, keyText) {
    const key = Buffer.from(String(keyText), "utf8");
    const data = Buffer.from(text, "utf8");
    const block = 16;
    const pad = data.length % block === 0 ? 0 : block - (data.length % block);
    const buf = Buffer.concat([data, Buffer.alloc(pad)]);
    const c = crypto.createCipheriv("aes-128-cbc", key, key);
    c.setAutoPadding(false);
    return Buffer.concat([c.update(buf), c.final()]).toString("base64");
}

function randomGuid(len) {
    const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
    let out = "";
    for (let i = 0; i < len; i++) out += chars[Math.floor(Math.random() * chars.length)];
    return out;
}

function maskToken(token) {
    const text = String(token || "");
    if (text.length <= 8) return "***";
    return text.slice(0, 6) + "***" + text.slice(-4);
}

async function request(options) {
    const res = await axios.request({
        timeout: 20000,
        proxy: false,
        validateStatus: () => true,
        ...options,
        headers: {
            "User-Agent": USER_AGENT,
            Accept: "application/json, text/plain, */*",
            ...(options.headers || {}),
        },
    });
    return { status: res.status, headers: res.headers || {}, data: res.data };
}

const OK_CODES = ["00000", "000000"];

class FeiheMom {
    constructor(entry) {
        const parsed = parseYybGoEntry(entry);
        this.server = parsed.server;
        this.ref = parsed.ref;
        this.note = parsed.note;
        this.key = cacheKey(parsed.server, parsed.ref);
        this.base = API_BASE;
        this.token = "";
    }

    async api({ method = "GET", path, data, allowFail = false }) {
        const opts = {
            method,
            url: `${this.base}${path}`,
            headers: {
                Authorization: this.token,
                locale: "zh_CN",
                "content-type": "application/json",
            },
        };
        if (method === "GET") opts.params = data || {};
        else opts.data = data === undefined ? {} : data;
        const res = await request(opts);
        const ok = res.status === 200 && OK_CODES.includes(String(res.data?.code));
        if (!ok && !allowFail) throw new Error(`HTTP ${res.status}: ${short(res.data)}`);
        return { ok, data: res.data, status: res.status };
    }

    async login() {
        // 1) 优先复用缓存 token（开跑前会再做只读校验）
        const cache = readTokenCache();
        let cached = cache[this.key];
        if (!cached) {
            for (const k of Object.keys(cache)) {
                const value = cache[k];
                if (value && value.accessToken && k !== this.key && legacyRefOf(k) === this.ref) {
                    cached = { ...value, updatedAt: nowText() };
                    cache[this.key] = cached;
                    delete cache[k];
                    writeTokenCache(cache);
                    console.log("   🗂️ [缓存] 旧缓存键已迁移为「地址|标识」");
                    break;
                }
            }
        }
        if (cached && cached.accessToken) {
            this.token = cached.accessToken;
            console.log(`   💾 [缓存] 复用已保存 token：${maskToken(this.token)}`);
            return { line: `缓存 token ${maskToken(this.token)}`, fromCache: true };
        }

        // 2) 取码登录
        console.log("   🔐 [取码] 请求 YYB Go 获取 code");
        const code = await getCode(this.server, this.ref);
        if (!code) throw new Error("获取 code 失败");
        console.log("   ✅ [取码] code 获取成功");
        const res = await request({
            method: "POST",
            url: `${this.base}/social/ma`,
            headers: { "content-type": "application/json", locale: "zh_CN" },
            data: code,
            transformRequest: [(data) => data],
        });
        const token = res.data?.data?.tokenInfo?.accessToken || res.data?.data?.accessToken || "";
        if (res.status !== 200 || !token) throw new Error(`登录失败 HTTP ${res.status}: ${short(res.data)}`);
        this.token = token;
        const c = readTokenCache();
        for (const k of Object.keys(c)) {
            if (k !== this.key && legacyRefOf(k) === this.ref) delete c[k];
        }
        c[this.key] = { accessToken: token, updatedAt: nowText() };
        writeTokenCache(c);
        console.log("   ✅ [登录] 新 token 获取成功");
        return { line: `新登录 ${maskToken(token)}`, fromCache: false };
    }

    /** 只读校验：memberInfo 能正常返回即视为登录态有效 */
    async verifyToken() {
        const res = await this.api({ path: "/c/user/memberInfo", allowFail: true });
        const msg = res.data?.message || res.data?.msg || res.data?.code || "未知";
        return { ok: res.ok, msg: String(msg) };
    }

    /** 会员信息 + 积分（结构化） */
    async profile() {
        const member = await this.api({ path: "/c/user/memberInfo", allowFail: true });
        const user = await this.api({ path: "/p/user/userInfo", allowFail: true });
        const memberData = member?.data?.data || member?.data || {};
        const userData = user?.data?.data || user?.data || {};
        const data = { ...memberData, ...userData };
        const name = userData.nickName || userData.nickname || memberData.nickName || memberData.memberName || memberData.mobile || "未知";
        return {
            name: String(name),
            memberId: String(memberData.memberId || data.memberId || data.crmId || ""),
            openId: String(memberData.openId || data.openId || ""),
            score: pickScore(data),
        };
    }

    async sign(scoreBefore) {
        const todo = await this.api({
            path: "/c/activity/todo/list",
            data: { mockTime: Date.now() },
            allowFail: true,
        });
        const body = todo?.data?.data ?? todo?.data ?? {};
        const checkTodo =
            body.checkInTodo ||
            findFirst(body, (item) => item && typeof item === "object" && (item.checkInExtra || /签到|打卡|check/i.test(`${item.taskName || item.name || item.title || ""}`)));
        const activityId = checkTodo?.id || checkTodo?.activityId || checkTodo?.taskId;
        if (!activityId) {
            return { ok: false, text: `未找到签到任务（${short(todo?.data, 120)}）`, scoreAfter: null };
        }
        const todaySigned =
            checkTodo?.todaySigned ||
            checkTodo?.signed ||
            checkTodo?.finish ||
            checkTodo?.completed ||
            checkTodo?.status === 1 ||
            checkTodo?.state === 1;
        if (todaySigned) {
            const after = await this.profile();
            return { ok: true, text: `今日已签到（activityId ${activityId}）`, scoreAfter: after.score };
        }
        const sign = await this.api({
            method: "POST",
            path: "/c/activity/todo/checkIn",
            data: { activityId, mockTime: Date.now() },
            allowFail: true,
        });
        const msg = String(sign.data?.message || sign.data?.msg || "");
        const already = /已签|重复|签到过/i.test(msg);
        const success = sign.ok || already;
        const after = await this.profile();
        return {
            ok: success,
            text: already ? `今日已签到（${msg}）` : (success ? `签到成功${msg && !/^签到成功/.test(msg) ? `（${msg}）` : ""}` : `签到失败：${msg || short(sign.data, 120)}`),
            scoreAfter: after.score,
        };
    }

    /** rrx 侧鉴权：ca.rrx.cn 由服务端下发签名 SSO 跳转，跟随后即可拿到 JWT Cookie */
    async rrxAuth() {
        const url = `${RRX_CA}/v/${RRX_SITE}?token=${encodeURIComponent(this.token)}&v=1&mwa=1`;
        const res = await axios.get(url, {
            headers: { "user-agent": UA, accept: "text/html,application/xhtml+xml,*/*;q=0.8" },
            maxRedirects: 6,
            validateStatus: () => true,
            proxy: false,
            timeout: 30000,
        });
        if (res.status !== 200) throw new Error(`rrx 授权跳转 HTTP ${res.status}`);
        const cookies = res.headers["set-cookie"] || [];
        let jwt = "", day = "";
        for (const raw of cookies) {
            const pair = String(raw).split(";")[0];
            const idx = pair.indexOf("=");
            if (idx === -1) continue;
            const name = pair.slice(0, idx).trim();
            const value = pair.slice(idx + 1).trim();
            if (value.startsWith("eyJ") && value.split(".").length === 3) jwt = value;
            else if (name.startsWith("authByDayWith")) day = pair;
        }
        if (!jwt) throw new Error("rrx 授权未返回 JWT");
        const headers = {
            authorization: `Bearer ${jwt}`,
            cookie: day,
            origin: RRX_CA,
            referer: `${RRX_CA}/`,
            "user-agent": UA,
        };
        const info = await axios.get(`${RRX_INFO}/m/auth/checkIsLogin?${this.rrxQuery()}`, { headers, proxy: false, validateStatus: () => true, timeout: 25000 });
        const data = info.data?.data || {};
        if (info.status !== 200 || info.data?.result !== 0 || !data.guid) {
            throw new Error(`rrx 登录态校验失败：${brief(info.data?.msg || info.data?.message || `HTTP ${info.status}`, 60)}`);
        }
        return { jwt, headers, guid: String(data.guid), name: String(data.name || ""), openId: String(data.openId || "") };
    }

    rrxQuery() {
        return `channel=${RRX_CHANNEL}&mallGuid=${RRX_MALL}&wsiteGuid=${RRX_SITE}`;
    }

    /** 鹤小飞超级大闯关：取 JWT → 查可玩关卡 → 开局 → 提交成绩 → 领奖机会 */
    async playGame(profile) {
        if (!GAME_ON) {
            console.log("   ℹ️ [游戏] FHXMH_GAME=0，已跳过");
            return { ok: true, skipped: true, text: "已关闭（FHXMH_GAME=0）" };
        }
        try {
            let auth = await this.rrxAuth();
            const q = this.rrxQuery();
            const maxRes = await axios.get(`${RRX_GAME_BASE}/getPlayMaxLevel?${q}&activityGuid=${RRX_ACT}`, { headers: auth.headers, proxy: false, validateStatus: () => true, timeout: 25000 });
            const maxData = maxRes.data?.data || {};
            if (maxRes.data?.result !== 0) throw new Error(`查询关卡失败：${brief(maxRes.data?.msg || `HTTP ${maxRes.status}`, 60)}`);
            const played = Number(maxData.playMaxLevel || 0);
            if (Number.isFinite(played) && played >= 100) return { ok: true, skipped: true, text: "100 关已全部通关" };
            let level = GAME_LEVEL_WANT > 0 ? GAME_LEVEL_WANT : Math.max(1, played + 1);
            console.log(`   🎮 [游戏] 已进入闯关（rrx ${auth.guid.slice(0, 8)}…），从第 ${level} 关开始，本账号今天最多 20 局`);
            if (maxData.checkIntegralJoin) console.log("   ℹ️ [游戏] 接口标记需积分校验，按活动规则继续尝试");
            console.log("   ⚠️ [游戏] 脚本为模拟对局提交成绩，活动规则写明异常账号会封禁，风险自担");

            const parts = [];
            let passCount = 0, totalAfter = 0;
            for (let n = 1; n <= GAME_PLAYS; n++) {
                // rrx JWT 有效期很短，多局时定期刷新，避免后半程 401
                if (n > 1 && (n - 1) % 4 === 0) {
                    try { auth = await this.rrxAuth(); } catch (e) { console.log(`   ⚠️ [游戏] JWT 刷新失败（${brief(e.message, 40)}），继续用旧凭证`); }
                }
                const one = await this.playOneGame(auth, level);
                if (!one.ok) {
                    parts.push(`第${n}局失败（${one.error}）`);
                    break;
                }
                parts.push(one.text);
                totalAfter = one.totalAfter || totalAfter;
                if (one.pass) {
                    passCount++;
                    level = one.nextLevel > level ? one.nextLevel : level + 1;
                } else break;
            }
            const summary = `计划 ${GAME_PLAYS} 局，成功 ${passCount} 局${totalAfter ? `，总分 ${totalAfter}` : ""}`;
            return { ok: true, text: `${summary}｜${parts.join("；")}` };
        } catch (e) {
            const msg = e && e.message ? e.message : String(e);
            return { ok: false, text: `闯关失败（${brief(msg, 80)}）` };
        }
    }

    async playOneGame(auth, level) {
        const q = this.rrxQuery();
        const start = await axios.post(
            `${RRX_GAME_BASE}/startGame?${q}&activityGuid=${RRX_ACT}`,
            new URLSearchParams({ activityGuid: RRX_ACT, mallGuid: RRX_MALL, fmid: "", gameLevel: String(level) }).toString(),
            { headers: { ...auth.headers, "content-type": "application/x-www-form-urlencoded" }, proxy: false, validateStatus: () => true, timeout: 25000 }
        );
        const sd = start.data?.data || {};
        if (start.data?.result !== 0 || !sd.gameStartToken) {
            return { ok: false, error: brief(start.data?.msg || `HTTP ${start.status}`, 60) };
        }
        const need = Number(sd.targetScore || 60);
        const floor = Math.max(need, GAME_SCORE_MIN);
        const ceil = Math.max(floor, GAME_SCORE_MAX);
        const target = GAME_SCORE > 0 ? Math.max(GAME_SCORE, floor) : floor + Math.floor(Math.random() * (ceil - floor + 1));
        const totalBefore = Number(sd.myRecord?.totalScore || 0);
        console.log(`   🎮 [游戏] 第 ${level} 关开局，目标 ${need} 分，本局提交 ${target}，累计 ${totalBefore}`);
        const waitSec = GAME_WAIT_MIN + Math.floor(Math.random() * (GAME_WAIT_MAX - GAME_WAIT_MIN + 1));
        console.log(`   ⏳ [游戏] 模拟对局中，本局随机等待 ${waitSec}s 后提交`);
        await sleep(waitSec * 1000);
        const now = Date.now();
        const isPass = target >= need ? 1 : 0;
        const plain = JSON.stringify({
            score: target,
            currentTime: waitSec * 1000 + 1200,
            microTime: now,
            activityGuid: RRX_ACT,
            memberGuid: auth.guid,
            gameLevel: level,
            isPass,
            gameGrade: 1,
        });
        const cipher = aesZeroPad(plain, RRX_PCS);
        const submitToken = now.toString(36) + "_" + randomGuid(16);
        const body = new URLSearchParams({
            activityGuid: RRX_ACT,
            fmid: "",
            currentScore: cipher,
            currentTime: String(waitSec * 1000 + 1200),
            isHelpStyle: "0",
            gameLevel: String(level),
            isPass: String(isPass),
            gameGrade: "1",
            gameMemo: "",
            gameStartToken: sd.gameStartToken,
            gameSubmitToken: submitToken,
            _t: String(now),
        }).toString();
        const save = await axios.post(`${RRX_GAME_BASE}/saveGame?${q}&activityGuid=${RRX_ACT}`, body, {
            headers: { ...auth.headers, "content-type": "application/x-www-form-urlencoded" },
            proxy: false, validateStatus: () => true, timeout: 25000,
        });
        const res = save.data || {};
        if (GAME_DEBUG) console.log(`   🔍 [游戏] saveGame 原始返回：${brief(JSON.stringify(res), 220)}`);
        if (res.result !== 0) return { ok: false, error: brief(res.msg || res.message || `HTTP ${save.status}`, 60) };
        const d = res.data || {};
        const pass = String(d.status || "").includes("Pass") || Number(d.isPass) === 1 || Number(d.currentGrade) > 0;
        const totalAfter = Number(d.totalScore || totalBefore);
        const delta = totalAfter - totalBefore;
        const ranking = Number(d.ranking || 0);
        const rankText = ranking > 0 ? `，当前排名第 ${ranking}` : "";
        return {
            ok: true,
            pass,
            totalAfter,
            nextLevel: Number(d.currentLevel || 0),
            text: pass
                ? `第${level}关通关（${Number(d.lastScore || target)}分）${delta > 0 ? `，总分 ${totalBefore}→${totalAfter}（+${delta}）` : `，总分 ${totalAfter}`}${rankText}`
                : `第${level}关未通关（${Number(d.lastScore || target)}/${need}分）${rankText}`,
        };
    }
}

function pickScore(data) {
    if (!data || typeof data !== "object") return null;
    const keys = ["score", "points", "integral", "availableScore", "totalScore", "point", "scoreValue"];
    for (const key of keys) {
        if (data[key] !== undefined && data[key] !== null && Number.isFinite(Number(data[key]))) return Number(data[key]);
    }
    const found = findFirst(data, (item) => {
        if (!item || typeof item !== "object") return false;
        return keys.some((key) => item[key] !== undefined && Number.isFinite(Number(item[key])));
    });
    if (found) {
        const key = keys.find((k) => found[k] !== undefined && Number.isFinite(Number(found[k])));
        return Number(found[key]);
    }
    return null;
}

function nowText() {
    return new Date().toLocaleString("zh-CN", { hour12: false });
}

async function getCode(server, ref) {
    const url = `http://${server}/wxapp/getCode`;
    try {
        const { data } = await axios.post(url, { ref, app_id: APP.appid }, { timeout: 20000, proxy: false });
        const code = data && data.data && data.data.result && data.data.result.code;
        if (!data || data.code !== 0 || !code) {
            console.log(`   ❌ [取码] 失败：${short(data, 150)}`);
            return null;
        }
        return code;
    } catch (e) {
        console.log(`   ❌ [取码] 异常：${e.message}`);
        return null;
    }
}

async function runAccount(entry, index) {
    const runner = new FeiheMom(entry);
    const result = {
        index, ref: runner.ref, note: runner.note,
        name: "", scoreBefore: null, scoreAfter: null, signText: "", gameText: "", gameOk: true, ok: true, error: "",
    };
    let usedCache = !!(readTokenCache()[runner.key] || {}).accessToken;

    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            const loginInfo = await runner.login();
            if (loginInfo.fromCache) {
                const verify = await runner.verifyToken();
                if (!verify.ok) {
                    console.log(`   ⚠️ [校验] 缓存 token 失效（${brief(verify.msg)}），清除后重新登录`);
                    removeCacheKey(runner.key, runner.ref);
                    usedCache = false;
                    continue;
                }
                console.log("   ✅ [校验] 缓存 token 有效，直接复用");
            }
            const profile = await runner.profile();
            result.name = profile.name;
            result.scoreBefore = profile.score;
            console.log(`   👤 [会员] ${profile.name}`);
            console.log(`   💰 [积分] ${profile.score === null ? "未知" : profile.score}`);

            const signInfo = await runner.sign(profile.score);
            result.signText = signInfo.text;
            result.scoreAfter = signInfo.scoreAfter;
            console.log(`   ${signInfo.ok ? "✅" : "❌"} [签到] ${signInfo.text}`);

            const game = await runner.playGame({ name: profile.name, memberId: profile.memberId, score: signInfo.scoreAfter });
            result.gameText = game.skipped && /当前无游戏任务/.test(game.text || "") ? "" : (game.text || "");
            result.gameOk = game.ok !== false;
            if (result.gameText) {
                console.log(`   ${game.skipped ? "ℹ️" : result.gameOk ? "✅" : "❌"} [游戏] ${result.gameText}`);
            }
            if (game.ok !== false) {
                const after = await runner.profile();
                if (after.score !== null) result.scoreAfter = after.score;
            }

            result.ok = signInfo.ok && result.gameOk;
            if (!result.ok) result.error = signInfo.ok ? result.gameText : signInfo.text;
            return result;
        } catch (e) {
            const msg = e && e.message ? e.message : String(e);
            if (attempt === 0 && usedCache) {
                console.log(`   ⚠️ [校验] 缓存 token 使用失败（${brief(msg)}），清除后重新登录`);
                removeCacheKey(runner.key, runner.ref);
                usedCache = false;
                continue;
            }
            result.ok = false;
            result.error = msg;
            console.log(`   ❌ [异常] ${brief(msg)}`);
            return result;
        }
    }
    result.ok = false;
    result.error = result.error || "重登后仍失败";
    return result;
}

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
    const token = process.env.PLUSPLUS_TOKEN || "";
    if (!token) return false;
    try {
        await axios.post("https://www.pushplus.plus/send", {
            token, title, content, template: "txt",
        }, { timeout: 10000, proxy: false });
        return true;
    } catch (e) {
        console.log(`   ⚠️ [通知] PushPlus 失败：${e.message}`);
        return false;
    }
}

function deltaText(before, after) {
    if (before === null || after === null) return "";
    const diff = after - before;
    if (diff === 0) return "";
    return `${before} → ${after}（${diff > 0 ? "+" : ""}${diff}）`;
}

(async () => {
    if (!SERVERS.length) {
        console.log("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识[#备注]，多账号换行分隔）");
        return;
    }
    const valid = SERVERS.filter(item => item.includes("@"));
    if (!valid.length) {
        console.log("❌ YYB_SERVER 无有效账号（格式：地址@标识[#备注]）");
        return;
    }
    SERVERS.length = 0;
    SERVERS.push(...valid);

    boxTop("🍼 飞鹤星妈会 每日任务");
    boxLine("🕒 启动时间", new Date().toLocaleString("zh-CN"));
    boxLine("🔢 账号数量", `${SERVERS.length} 个`);
    boxLine("💾 缓存", "fhxmh_token_cache.json");
    boxLine("🌐 网络", process.env.FHXMH_PROXY_API ? "代理" : "直连");
    boxBottom();

    const results = [];
    for (let i = 0; i < SERVERS.length; i++) {
        const entry = parseYybGoEntry(SERVERS[i]);
        const label = `标识 ${entry.ref || "-"}` + (entry.note ? `（${entry.note}）` : "");
        accountFrame(i + 1, SERVERS.length, label, SERVERS[i]);
        const res = await runAccount(SERVERS[i], i + 1);
        results.push(res);
        console.log(res.ok ? "   ✅ [完成] 该账号任务执行完成" : "   ❌ [完成] 该账号存在失败项");
        hr();
        if (i < SERVERS.length - 1) {
            console.log("   ⏳ 等待2秒后执行下一个账号...");
            await sleep(2000);
        }
    }

    console.log("");
    for (const r of results) {
        const title = `${r.ok ? "✅" : "❌"} 【账号 ${r.index} · 标识 ${r.ref || "-"}` + (r.note ? `（${r.note}）` : "") + "】";
        console.log(title);
        console.log(`   👤 [会员] ${r.name || "未知"}`);
        const scoreLine = deltaText(r.scoreBefore, r.scoreAfter) || `${r.scoreAfter ?? r.scoreBefore ?? "未知"}`;
        console.log(`   💰 [积分] ${scoreLine}`);
        console.log(`   📅 [签到] ${r.signText || (r.ok ? "已完成" : "未完成")}`);
        if (r.gameText) console.log(`   🎮 [游戏] ${r.gameText}`);
        if (!r.ok) console.log(`   ⚠️ [失败] ${brief(r.error)}`);
    }

    const ok = results.filter(r => r.ok).length;
    console.log("");
    boxTop("🏁 飞鹤星妈会 执行汇总");
    boxLine("📊 执行结果", `成功 ${ok} / 失败 ${results.length - ok} / 共 ${results.length}`);
    boxLine("🕒 结束时间", new Date().toLocaleString("zh-CN"));
    boxBottom();

    const content = results.map(r => `${r.ok ? "✅" : "❌"} 账号${r.index} ${r.ref || "-"}` + (r.note ? `（${r.note}）` : "") +
        `\n会员：${r.name || "未知"}\n积分：${deltaText(r.scoreBefore, r.scoreAfter) || (r.scoreAfter ?? r.scoreBefore ?? "未知")}\n签到：${r.signText || (r.ok ? "已完成" : "未完成")}${r.gameText ? `\n游戏：${r.gameText}` : ""}` +
        (r.ok ? "" : `\n失败：${r.error}`)).join("\n\n");

    if (NOTIFY_ON) {
        const sent = await sendQingLongNotify("🍼 飞鹤星妈会任务完成", content);
        console.log(sent ? "   📮 [通知] 已通过青龙 notify 推送" : "   ℹ️ [通知] 未找到青龙 notify 脚本");
        if (await sendPushPlus("🍼 飞鹤星妈会任务完成", content)) console.log("   📨 [通知] PushPlus 推送成功");
    } else {
        console.log("   ℹ️ [通知] FHXMH_NOTIFY=0，已关闭通知");
    }
})().catch(e => console.log(`❌ [全局异常] ${e.message}`));
