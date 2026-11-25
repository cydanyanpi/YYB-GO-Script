// name: 戴可思
// cron: 24 16,4 * * *
// 环境变量：DKS_NOTIFY=0 关闭青龙/PushPlus 通知；PUSHPLUS_TOKEN 配置后额外走 PushPlus
const axios = require("axios");
const fs = require("fs");
const path = require("path");

// ====================== 基础常量 ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.error("❌ 未配置环境变量 YYB_SERVER，请设置后重试（格式：地址@微信账号标识[#备注]，多行换行）");
    process.exit(1);
}

const BOX_WIDTH = 48;
const BOX_INNER = 46;
const MINI_APP_ID = "wx9d46d96c4c35a53a";
const CLIENT_BIZ = "weapp_wsc";
const KDT_ID = "46323516";
const USER_VERSION = "2.233.4.101";
const PAGE_VERSION = "96";
const API_BASE = (process.env.DKS_API_BASE || "https://h5.youzan.com").replace(/\/+$/, "");
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";
const NOTIFY_ON = String(process.env.DKS_NOTIFY ?? "1") !== "0";

// ====================== 缓存 ======================
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "dks_token_cache.json");

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch { return {}; }
}

function writeTokenCache(cache) {
    try {
        fs.mkdirSync(TOKEN_CACHE_DIR, { recursive: true });
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
    } catch (e) { console.log("   ⚠️ [缓存] 写入失败: " + (e.message || e)); }
}

function cacheKey(server, ref) { return `${server}|${ref}`; }

function legacyRefOf(key) {
    const value = String(key || "").trim();
    if (!value) return "";
    if (!value.includes("@")) return value;
    let body = value;
    const hashIndex = body.lastIndexOf("#");
    if (hashIndex !== -1 && hashIndex > body.lastIndexOf("@")) body = body.slice(0, hashIndex);
    const atIndex = body.lastIndexOf("@");
    return atIndex === -1 ? body.trim() : body.slice(atIndex + 1).trim();
}

function nowText() { return new Date().toLocaleString("zh-CN", { hour12: false }); }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ====================== 账号解析 ======================
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
    if (!server || !ref) return { server: "", ref, note };
    return { server, ref, note };
}

// ====================== 输出美化 ======================
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
function brief(value, limit = 90) { const text = String(value ?? "").replace(/\n/g, " "); return text.length <= limit ? text : text.slice(0, limit - 1) + "…"; }
function maskPhone(phone = "") { return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2"); }
function maskToken(token = "") {
    const text = String(token || "");
    if (!text) return "-";
    return text.length > 16 ? `${text.slice(0, 8)}***${text.slice(-8)}` : `${text.slice(0, 4)}***`;
}
function pickToken(data = {}) { return data.accessToken || data.access_token || ""; }

// ====================== 取码 ======================
async function getCode(server, ref) {
    const url = `http://${server}/wxapp/getCode`;
    try {
        const { data } = await axios.post(url, { ref, app_id: MINI_APP_ID }, { timeout: 20000, proxy: false });
        const code = data?.data?.result?.code;
        if (!data || data.code !== 0 || !code) {
            console.log("   ❌ [取码] 获取 code 失败: " + brief(JSON.stringify(data), 80));
            return "";
        }
        return code;
    } catch (e) {
        console.log("   ❌ [取码] 请求 YYB Go 失败: " + brief(e.message));
        return "";
    }
}

// ====================== 账号任务 ======================
let userIdx = 0;

class Task {
    constructor(account) {
        const entry = parseYybGoEntry(account);
        this.server = entry.server;
        this.ref = entry.ref;
        this.note = entry.note;
        this.index = ++userIdx;
        this.key = cacheKey(this.server, this.ref);
        this.token = "";
        this.sessionId = "";
        this.cookie = "";
        this.kdtId = KDT_ID;
        this.userInfo = {};
        this.checkinId = "";
    }

    getHeaders(extra = {}) {
        const headers = {
            "User-Agent": USER_AGENT,
            Referer: `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            Accept: "*/*",
            "Extra-Data": JSON.stringify({
                sid: this.sessionId || "",
                version: USER_VERSION,
                clientType: "weapp-miniprogram",
                client: "weapp",
                bizEnv: "wsc",
            }),
            ...extra,
        };
        if (this.cookie) headers.Cookie = this.cookie;
        return headers;
    }

    getBaseParams(params = {}) {
        return { app_id: MINI_APP_ID, kdt_id: this.kdtId, access_token: this.token, ...params };
    }

    async request({ method = "GET", path: apiPath, params = {}, data = {}, skipToken = false }) {
        const options = {
            method,
            url: `${API_BASE}${apiPath.startsWith("/") ? apiPath : `/${apiPath}`}`,
            headers: this.getHeaders(method === "POST" ? { "Content-Type": "application/json" } : {}),
            timeout: 15000,
            validateStatus: () => true,
            proxy: false,
        };
        options.params = skipToken ? params : this.getBaseParams(params);
        if (method !== "GET") options.data = data;
        const { data: result, status, headers } = await axios.request(options);
        if (headers["set-cookie"]) this.cookie = headers["set-cookie"].map((item) => item.split(";")[0]).join("; ");
        if (status !== 200) throw new Error(`HTTP ${status}: ${brief(JSON.stringify(result), 80)}`);
        if (!result || result.code !== 0) throw new Error(result?.msg || JSON.stringify(result));
        return result.data;
    }

    // ---------- 缓存 / 登录 ----------
    async login() {
        const cache = readTokenCache();
        let cached = cache[this.key];
        if (!cached) {
            for (const k of Object.keys(cache)) {
                if (cache[k] && cache[k].accessToken && legacyRefOf(k) === this.ref) {
                    cached = { ...cache[k], updatedAt: cache[k].updatedAt || nowText() };
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
            this.sessionId = cached.sessionId || "";
            this.cookie = cached.cookie || "";
            this.kdtId = String(cached.kdtId || KDT_ID);
            this.userInfo = cached;
            console.log("   💾 [缓存] 复用已保存 token: " + maskToken(this.token));
            return { fromCache: true };
        }
        await this.loginByWxCode();
        return { fromCache: false };
    }

    async loginByWxCode() {
        console.log("   🔐 [取码] 请求 YYB Go 获取 code");
        const code = await getCode(this.server, this.ref);
        if (!code) throw new Error("获取 code 失败");
        console.log("   ✅ [取码] code 获取成功");
        const data = await this.request({
            method: "POST",
            path: "/wscshop/weapp/authorize.json",
            skipToken: true,
            data: { appId: MINI_APP_ID, clientBiz: CLIENT_BIZ, code },
        });
        this.token = pickToken(data);
        if (!this.token) throw new Error("登录成功但未返回 accessToken");
        this.sessionId = data.sessionId || data.session_id || "";
        this.kdtId = String(data.kdtId || data.kdt_id || KDT_ID);
        this.cookie = data.cookie || this.cookie || "";
        this.userInfo = data || {};
        const cache = readTokenCache();
        for (const k of Object.keys(cache)) {
            if (k !== this.key && legacyRefOf(k) === this.ref) delete cache[k];
        }
        cache[this.key] = {
            accessToken: this.token,
            sessionId: this.sessionId,
            kdtId: this.kdtId,
            cookie: this.cookie,
            mobile: this.userInfo.mobile || "",
            nickName: this.userInfo.nick_name || this.userInfo.nickName || "",
            updatedAt: nowText(),
        };
        writeTokenCache(cache);
        console.log("   ✅ [登录] 新 token 获取成功: " + `${data.nick_name || data.nickName || ""} ${maskPhone(data.mobile) || ""}`.trim());
    }

    removeCachedToken() {
        const cache = readTokenCache();
        delete cache[this.key];
        for (const k of Object.keys(cache)) {
            if (k !== this.key && legacyRefOf(k) === this.ref) delete cache[k];
        }
        writeTokenCache(cache);
        this.token = "";
        this.sessionId = "";
        this.cookie = "";
    }

    /** 只读校验：积分接口能返回即登录态有效 */
    async verifyToken() {
        try {
            await this.request({ path: "/wscump/integral/user_points.json" });
            return { ok: true, msg: "" };
        } catch (e) {
            return { ok: false, msg: brief(e.message, 50) };
        }
    }

    async profile() {
        const data = await this.request({ path: "/wscump/integral/user_points.json" });
        const points = data?.current_points ?? data?.real_points;
        const member = this.userInfo || {};
        const name = member.nick_name || member.nickName || maskPhone(member.mobile || "") || this.ref;
        return { name: String(name || "未知"), points: Number.isFinite(Number(points)) ? Number(points) : null };
    }

    async showCheckinPage() {
        const data = await this.request({ path: "/wscump/checkin/show_checkin_page_v2.json" });
        this.checkinId = data?.checkinId || "";
        return { show: !!data?.isShow, id: this.checkinId };
    }

    async doCheckin() {
        if (!this.checkinId) return { ok: false, text: "未获取到签到活动（checkinId 为空）" };
        try {
            const data = await this.request({ path: "/wscump/checkin/checkinV2.json", params: { checkinId: this.checkinId } });
            const awards = (data?.list || []).map((item) => item?.infos?.title).filter(Boolean).join(", ");
            const desc = String(data?.desc || "");
            const extra = awards && !desc.includes(awards) ? ` ${awards}` : "";
            return { ok: true, text: `签到成功${desc ? `（${desc}）` : ""}${extra}` };
        } catch (e) {
            const message = String(e.message || e);
            if (/已达最大参与次数|已签到|重复签到|今日已/.test(message)) return { ok: true, text: `今日已签到（${message}）` };
            return { ok: false, text: `签到失败（${brief(message, 60)}）` };
        }
    }

    async runAccount() {
        const result = {
            index: this.index, ref: this.ref, note: this.note,
            name: "", pointsBefore: null, pointsAfter: null,
            signText: "", ok: true, error: "",
        };
        let usedCache = !!(readTokenCache()[this.key] || {}).accessToken;
        for (let attempt = 0; attempt < 2; attempt++) {
            try {
                const loginInfo = await this.login();
                if (loginInfo.fromCache) {
                    const verify = await this.verifyToken();
                    if (!verify.ok) {
                        console.log(`   ⚠️ [校验] 缓存 token 失效（${verify.msg}），清除后重新登录`);
                        this.removeCachedToken();
                        usedCache = false;
                        continue;
                    }
                    console.log("   ✅ [校验] 缓存 token 有效，直接复用");
                }
                const profile = await this.profile();
                result.name = profile.name;
                result.pointsBefore = profile.points;
                console.log(`   👤 [会员] ${profile.name}`);
                console.log(`   💰 [积分] ${profile.points === null ? "未知" : profile.points}`);

                const page = await this.showCheckinPage();
                console.log(`   📋 [活动] ${page.show ? "签到活动进行中" : "今日无可签到活动"}${page.id ? `（${page.id}）` : ""}`);
                const sign = await this.doCheckin();
                result.signText = sign.text;
                console.log(`   ${sign.ok ? "✅" : "❌"} [签到] ${sign.text}`);

                const after = await this.profile();
                if (after.points !== null) result.pointsAfter = after.points;
                result.ok = sign.ok;
                if (!result.ok) result.error = sign.text;
                return result;
            } catch (e) {
                const msg = e && e.message ? e.message : String(e);
                if (attempt === 0 && usedCache) {
                    console.log(`   ⚠️ [校验] 缓存 token 使用失败（${brief(msg)}），清除后重新登录`);
                    this.removeCachedToken();
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
}

function deltaText(before, after) {
    if (before === null && after === null) return "";
    if (before === null) return String(after ?? "未知");
    if (after === null) return String(before);
    if (after === before) return `${after}`;
    return `${before} → ${after}（${after > before ? "+" : ""}${after - before}）`;
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
    boxTop("🧴 戴可思 每日任务");
    boxLine("🕒 启动时间", nowText());
    boxLine("🔢 账号数量", `${SERVERS.length} 个`);
    boxLine("💾 缓存", "dks_token_cache.json");
    boxLine("🌐 网络", process.env.PROXY_API ? "代理" : "直连");
    boxBottom();

    const results = [];
    for (let i = 0; i < SERVERS.length; i++) {
        const entry = parseYybGoEntry(SERVERS[i]);
        if (!entry.ref) {
            console.log(`\n   ❌ [账号] 格式应为 地址@标识[#备注]，当前值: ${SERVERS[i]}`);
            results.push({ index: i + 1, ref: "", note: "", name: "", pointsBefore: null, pointsAfter: null, signText: "", ok: false, error: "账号格式错误" });
            hr();
            continue;
        }
        accountFrame(i + 1, SERVERS.length, "标识 " + entry.ref, SERVERS[i]);
        const result = await new Task(SERVERS[i]).runAccount();
        results.push(result);
        hr();
        if (i < SERVERS.length - 1) {
            console.log("   ⏳ 等待2秒后执行下一个账号...");
            await sleep(2000);
        }
    }

    console.log("");
    for (const r of results) {
        console.log(`${r.ok ? "✅" : "❌"} 【账号 ${r.index} · ${r.ref || "-"}】`);
        console.log(`   👤 会员：${r.name || "未知"}`);
        console.log(`   💰 积分：${deltaText(r.pointsBefore, r.pointsAfter) || "未知"}`);
        console.log(`   📅 签到：${r.signText || (r.ok ? "已完成" : "未完成")}`);
        if (!r.ok) console.log(`   ⚠️ 失败：${brief(r.error || "见上方日志", 80)}`);
    }

    const ok = results.filter(r => r.ok).length;
    boxTop("🏁 🧴 戴可思 执行汇总");
    boxLine("📊 执行结果", `成功 ${ok} / 失败 ${results.length - ok} / 共 ${results.length}`);
    boxLine("🕒 结束时间", nowText());
    boxBottom();

    const content = results.map(r => `${r.ok ? "✅" : "❌"} 账号${r.index} ${r.ref || "-"}` +
        `\n会员：${r.name || "未知"}\n积分：${deltaText(r.pointsBefore, r.pointsAfter) || "未知"}` +
        `\n签到：${r.signText || (r.ok ? "已完成" : "未完成")}` +
        (r.ok ? "" : `\n失败：${brief(r.error || "", 80)}`)).join("\n\n");

    if (NOTIFY_ON) {
        const sent = await sendQingLongNotify("🧴 戴可思任务完成", content);
        console.log(sent ? "   📮 [通知] 已通过青龙 notify 推送" : "   ℹ️ [通知] 未找到青龙 notify 脚本");
        if (await sendPushPlus("🧴 戴可思任务完成", content)) console.log("   📨 [通知] PushPlus 推送成功");
    } else {
        console.log("   ℹ️ [通知] DKS_NOTIFY=0，已关闭通知");
    }
})().catch(e => console.log(`❌ [全局异常] ${e.message}`));
