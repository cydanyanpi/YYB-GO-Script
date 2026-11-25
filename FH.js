// name: 飞鹤
// cron: 16 15,3 * * *
// 环境变量：FH_NOTIFY=0 关闭青龙/PushPlus 通知；PUSHPLUS_TOKEN 配置后额外走 PushPlus
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
    console.error("❌ 未配置环境变量 YYB_SERVER，请设置后重试（格式：地址@微信账号标识[#备注]，多行换行）");
    process.exit(1);
}

const BOX_WIDTH = 48;
const BOX_INNER = 46;
const MINI_APP_ID = "wx4205ec55b793245e";
const API_BASE = (process.env.FH_API_BASE || "https://www.feihevip.com").replace(/\/+$/, "");
const APP_ID = "xmyx";
const APP_KEY = "TwUQ01lKS1Km5zlV2f7amsZc5EQYkTbv";
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";
const NOTIFY_ON = String(process.env.FH_NOTIFY ?? "1") !== "0";

// ====================== Token 缓存 ======================
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "fh_token_cache.json");

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

// 静默解析缓存键里的标识：兼容「纯标识」与「地址@标识[#备注]」两种老键
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
    if (!server || !ref) return { server: "", ref: "", note };
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
function maskToken(token = "") {
    if (!token) return "";
    return token.length > 16 ? `${token.slice(0, 8)}***${token.slice(-8)}` : `${token.slice(0, 4)}***`;
}

// ====================== 签名 / 请求 ======================
function randomString(length) {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    let result = "";
    for (let i = 0; i < length; i++) result += chars[Math.floor(Math.random() * chars.length)];
    return result;
}
function md5Upper(text) { return crypto.createHash("md5").update(text).digest("hex").toUpperCase(); }
function buildSignedHeaders({ data = null, token = "" } = {}) {
    const headers = {
        fhAppid: APP_ID,
        fhNonceStr: randomString(16),
        fhTimestamp: Math.floor(Date.now() / 1000),
        token,
        source: "1",
        OrderUpdate: 1,
        visit: "",
    };
    if (data) headers["Content-Type"] = "application/json";
    const bodyStr = data && typeof data === "object" ? JSON.stringify(data) : data ? String(data) : "";
    const signText = `fhAppid${APP_ID}fhNonceStr${headers.fhNonceStr}fhTimestamp${headers.fhTimestamp}${bodyStr}`;
    return {
        ...headers,
        fhSign: md5Upper(signText + APP_KEY),
        Referer: `https://servicewechat.com/${MINI_APP_ID}/420/page-frame.html`,
        "User-Agent": USER_AGENT,
        Accept: "application/json, text/plain, */*",
    };
}
function buildUrl(apiPath, query = {}) {
    const params = new URLSearchParams();
    Object.entries(query || {}).forEach(([key, value]) => {
        if (value !== undefined && value !== null) params.append(key, String(value));
    });
    return `${API_BASE}${apiPath}${params.toString() ? `?${params.toString()}` : ""}`;
}

async function getCode(server, ref) {
    const url = `http://${server}/wxapp/getCode`;
    try {
        const { data } = await axios.post(url, { ref, app_id: MINI_APP_ID }, { timeout: 20000, proxy: false });
        return data?.data?.result?.code || "";
    } catch (e) {
        console.log("   ❌ [取码] 请求 YYB Go 失败: " + brief(e.message));
        return "";
    }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

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
        this.userInfo = {};
        this.name = "";
    }

    async request({ method = "GET", apiPath, query = {}, data = null, token = this.token, allowFail = false }) {
        const options = {
            method,
            url: buildUrl(apiPath, query),
            headers: buildSignedHeaders({ data: method === "GET" ? null : data, token }),
            timeout: 15000,
            validateStatus: () => true,
            proxy: false,
        };
        if (method !== "GET" && data) options.data = data;
        const { status, data: result } = await axios.request(options);
        const ok = status === 200 && String(result?.code) === "200";
        if (!ok && !allowFail) throw new Error(`HTTP ${status} ${brief(JSON.stringify(result), 80)}`);
        return result;
    }

    // ---------- 登录 / 缓存 ----------
    async login() {
        const cache = readTokenCache();
        let cached = cache[this.key];
        if (!cached) {
            for (const k of Object.keys(cache)) {
                const value = cache[k];
                if (value && value.token && k !== this.key && legacyRefOf(k) === this.ref) {
                    cached = { ...value, updatedAt: value.updatedAt || nowText() };
                    cache[this.key] = cached;
                    delete cache[k];
                    writeTokenCache(cache);
                    console.log("   🗂️ [缓存] 旧缓存键已迁移为「地址|标识」");
                    break;
                }
            }
        }
        if (cached && cached.token) {
            this.token = cached.token;
            this.userInfo = cached.userInfo || {};
            console.log("   💾 [缓存] 复用已保存 token: " + maskToken(this.token));
            return { fromCache: true };
        }
        await this.loginByCode();
        return { fromCache: false };
    }

    async loginByCode() {
        console.log("   🔐 [取码] 请求 YYB Go 获取 code");
        const code = await getCode(this.server, this.ref);
        if (!code) throw new Error("获取 code 失败");
        console.log("   ✅ [取码] code 获取成功");
        const result = await this.request({
            apiPath: "/api/starMember/getUserToken",
            query: { code },
            token: "",
        });
        const data = result.data || {};
        this.token = result.token || data.token || "";
        if (!this.token) throw new Error("登录成功但未返回 token");
        this.userInfo = {
            crmId: data.crmId, openId: data.openId, unionId: data.unionId,
            loginStatus: data.loginStatus, expireTime: data.expireTime,
        };
        const cache = readTokenCache();
        for (const k of Object.keys(cache)) {
            if (k !== this.key && legacyRefOf(k) === this.ref) delete cache[k];
        }
        cache[this.key] = { token: this.token, userInfo: this.userInfo, updatedAt: nowText() };
        writeTokenCache(cache);
        console.log("   ✅ [登录] 新 token 获取成功: " + maskToken(this.token));
    }

    removeCachedToken() {
        const cache = readTokenCache();
        delete cache[this.key];
        for (const k of Object.keys(cache)) {
            if (k !== this.key && legacyRefOf(k) === this.ref) delete cache[k];
        }
        writeTokenCache(cache);
    }

    /** 只读校验：首页接口能正常返回即视为登录态有效 */
    async verifyToken() {
        const result = await this.request({
            method: "POST",
            apiPath: "/api/structures/index",
            data: { id: "" },
            allowFail: true,
        });
        return { ok: String(result?.code) === "200", msg: result?.msg || result?.code || "未知" };
    }

    // ---------- 业务 ----------
    async getIndexInfo() {
        const result = await this.request({ method: "POST", apiPath: "/api/structures/index", data: { id: "" }, allowFail: true });
        if (String(result?.code) !== "200") throw new Error(`首页信息查询失败：${brief(result?.msg || "", 60)}`);
        const signModule = (result.data?.modules || []).find((item) => String(item.moduleType) === "17");
        return { hasSign: !!signModule };
    }

    async profile() {
        const result = await this.request({ apiPath: "/api/member/signin/getSignInfo", query: { signType: 1 }, allowFail: true });
        const member = result?.data?.memberDetail || {};
        const name = member.nickName || member.nickname || member.mobile || this.userInfo.crmId || this.userInfo.openId || "未知";
        const points = Number(member.totalPoint);
        this.name = String(name);
        return { name: String(name), points: Number.isFinite(points) ? points : null, member };
    }

    async signIn() {
        const sign = await this.request({ method: "POST", apiPath: "/api/member/signin/sign", allowFail: true });
        if (String(sign?.code) === "200") {
            const data = sign.data || {};
            const points = data.awardSendPoints || data.awardPoint || data.points || "";
            return { ok: true, text: `签到成功${points ? `（+${points} 积分）` : ""}` };
        }
        const msg = String(sign?.msg || "");
        if (/已签|重复|今天/.test(msg)) {
            return { ok: true, text: `今日已签到${msg && !/已签/.test(msg) ? `（${msg}）` : ""}` };
        }
        return { ok: false, text: `签到失败（${brief(msg || JSON.stringify(sign), 60)}）` };
    }

    async doAllTasks() {
        const listResult = await this.request({ apiPath: "/api/member/signin/getTaskList", allowFail: true });
        if (String(listResult?.code) !== "200") {
            return { ok: false, text: `任务列表获取失败（${brief(listResult?.msg || "", 50)}）`, done: 0, gain: 0 };
        }
        const tasks = listResult.data || [];
        if (!tasks.length) return { ok: true, text: "暂无任务", done: 0, gain: 0 };

        let done = 0, gain = 0;
        const texts = [];
        for (const task of tasks) {
            const taskName = task.taskName || "未知任务";
            const taskType = task.taskType || "";
            const totalCount = Number(task.totalCount || 0);
            const completedCount = Number(task.completedCount || 0);
            const duration = Number(task.completeTaskDuration || 1);
            if (task.isCompleted === true || completedCount >= totalCount) {
                texts.push(`${taskName} 已完成`);
                continue;
            }
            const remaining = Math.max(0, totalCount - completedCount);
            for (let i = 0; i < remaining; i++) {
                const start = await this.request({ apiPath: "/api/member/signin/tofinish", query: { taskType }, allowFail: true });
                if (start?.msg) { texts.push(`${taskName}：${start.msg}`); break; }
                console.log(`   ⏳ [任务] ${taskName}，等待 ${duration}s`);
                await sleep(duration * 1000);
                const finish = await this.request({ apiPath: "/api/member/signin/completeTask", query: { taskType }, allowFail: true });
                if (finish?.msg) {
                    texts.push(`${taskName}：${finish.msg}`);
                    if (/失败|异常|未完成/.test(String(finish.msg))) break;
                } else {
                    const add = Number(finish?.data?.awardSendPoints || 0);
                    done++; gain += add;
                    texts.push(`${taskName}${add ? ` +${add}积分` : " 完成"}`);
                    console.log(`   ✅ [任务] ${taskName}${add ? ` +${add} 积分` : " 完成"}`);
                }
                await sleep((Math.floor(Math.random() * 21) + 10) * 1000);
            }
        }
        const fail = texts.some(t => /失败|异常/.test(t));
        return { ok: !fail, text: texts.join("；"), done, gain };
    }

    async runAccount() {
        const result = {
            index: this.index, ref: this.ref, note: this.note,
            name: "", pointsBefore: null, pointsAfter: null,
            signText: "", taskText: "", ok: true, error: "",
        };
        let usedCache = !!(readTokenCache()[this.key] || {}).token;
        for (let attempt = 0; attempt < 2; attempt++) {
            try {
                const loginInfo = await this.login();
                if (loginInfo.fromCache) {
                    const verify = await this.verifyToken();
                    if (!verify.ok) {
                        console.log(`   ⚠️ [校验] 缓存 token 失效（${brief(verify.msg)}），清除后重新登录`);
                        this.removeCachedToken();
                        usedCache = false;
                        continue;
                    }
                    console.log("   ✅ [校验] 缓存 token 有效，直接复用");
                }
                await this.getIndexInfo();
                const profile = await this.profile();
                result.name = profile.name;
                result.pointsBefore = profile.points;
                console.log(`   👤 [会员] ${profile.name}`);
                console.log(`   💰 [积分] ${profile.points === null ? "未知" : profile.points}`);

                const sign = await this.signIn();
                result.signText = sign.text;
                console.log(`   ${sign.ok ? "✅" : "❌"} [签到] ${sign.text}`);

                const task = await this.doAllTasks();
                result.taskText = task.text;
                console.log(`   ${task.ok ? "✅" : "❌"} [任务] 完成 ${task.done} 个任务${task.gain ? `，+${task.gain} 积分` : ""}`);

                const after = await this.profile();
                if (after.points !== null) result.pointsAfter = after.points;
                result.ok = sign.ok && task.ok;
                if (!result.ok) result.error = sign.ok ? task.text : sign.text;
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
    const token = process.env.PUSHPLUS_TOKEN || "";
    if (!token) return false;
    try {
        const res = await axios.post("https://www.pushplus.plus/send", { token, title, content, template: "txt" }, { timeout: 15000, proxy: false });
        return res.data?.code === 200;
    } catch { return false; }
}

// ====================== 主流程 ======================
(async () => {
    boxTop("🍼 飞鹤 每日任务");
    boxLine("🕒 启动时间", nowText());
    boxLine("🔢 账号数量", `${SERVERS.length} 个`);
    boxLine("💾 缓存", "fh_token_cache.json");
    boxLine("🌐 网络", process.env.PROXY_API ? "代理" : "直连");
    boxBottom();

    const results = [];
    for (let i = 0; i < SERVERS.length; i++) {
        const entry = parseYybGoEntry(SERVERS[i]);
        if (!entry.ref) {
            console.log(`\n   ❌ [账号] 格式应为 地址@标识[#备注]，当前值: ${SERVERS[i]}`);
            results.push({ index: i + 1, ref: "", note: "", name: "", pointsBefore: null, pointsAfter: null, signText: "", taskText: "", ok: false, error: "账号格式错误" });
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

    // 明细（在汇总框上方）
    console.log("");
    for (const r of results) {
        console.log(`${r.ok ? "✅" : "❌"} 【账号 ${r.index} · ${r.ref || "-"}】`);
        console.log(`   👤 会员：${r.name || "未知"}`);
        console.log(`   💰 积分：${deltaText(r.pointsBefore, r.pointsAfter) || "未知"}`);
        console.log(`   📅 签到：${r.signText || (r.ok ? "已完成" : "未完成")}`);
        if (r.taskText) console.log(`   🧾 任务：${brief(r.taskText, 160)}`);
        if (!r.ok) console.log(`   ⚠️ 失败：${brief(r.error || "见上方日志", 80)}`);
    }

    const ok = results.filter(r => r.ok).length;
    boxTop("🏁 🍼 飞鹤 执行汇总");
    boxLine("📊 执行结果", `成功 ${ok} / 失败 ${results.length - ok} / 共 ${results.length}`);
    boxLine("🕒 结束时间", nowText());
    boxBottom();

    const content = results.map(r => `${r.ok ? "✅" : "❌"} 账号${r.index} ${r.ref || "-"}` +
        `\n会员：${r.name || "未知"}\n积分：${deltaText(r.pointsBefore, r.pointsAfter) || "未知"}` +
        `\n签到：${r.signText || (r.ok ? "已完成" : "未完成")}` +
        (r.taskText ? `\n任务：${brief(r.taskText, 120)}` : "") +
        (r.ok ? "" : `\n失败：${brief(r.error || "", 80)}`)).join("\n\n");

    if (NOTIFY_ON) {
        const sent = await sendQingLongNotify("🍼 飞鹤任务完成", content);
        console.log(sent ? "   📮 [通知] 已通过青龙 notify 推送" : "   ℹ️ [通知] 未找到青龙 notify 脚本");
        if (await sendPushPlus("🍼 飞鹤任务完成", content)) console.log("   📨 [通知] PushPlus 推送成功");
    } else {
        console.log("   ℹ️ [通知] FH_NOTIFY=0，已关闭通知");
    }
})().catch(e => console.log(`❌ [全局异常] ${e.message}`));
