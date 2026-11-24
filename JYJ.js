// name: 劲友家
// cron: 0 13,1 * * *
const axios = require("axios");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
// ====================== YYB Go 账号（环境变量 YYB_SERVER = 地址@微信账号标识，多行） ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.error("❌ 未配置环境变量 YYB_SERVER，请设置后重试（格式：地址@微信账号标识，多行换行）");
    process.exit(1);
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
        const { data } = await axios.post(url, { ref, app_id: MINI_APP_ID }, { timeout: 20000, proxy: false });
        const code = data && data.data && data.data.result && data.data.result.code;
        if (!data || data.code !== 0 || !code) {
            console.log(`❌ [取码] ${parsedServer} 获取code失败: ${JSON.stringify(data)}`);
            return null;
        }
        console.log(`✅ [取码] ${parsedServer} 获取code成功`);
        return code;
    } catch (e) {
        console.log(`❌ [取码] ${parsedServer} 获取code异常: ${e.message}`);
        return null;
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

const MINI_APP_ID = "wx10bc773e0851aedd";
const API_BASE = (process.env.JYJ_API_BASE || "https://jjw.jingjiu.com/app-jingyoujia").replace(/\/+$/, "");
const NOTIFY_ENABLED = (process.env.JYJ_NOTIFY || "1") !== "0";
const PLUSPLUS_TOKEN = process.env.PLUSPLUS_TOKEN || "";
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "jingyoujia_token_cache.json");
try { fs.mkdirSync(path.dirname(TOKEN_CACHE_FILE), { recursive: true }); } catch (e) {}
const PAGE_VERSION = "1052";
const AES_KEY = "Z0J7M480h6kppf67";
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

function nowText() {
    const d = new Date();
    const pad = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}





function cacheKey(server, ref) {
    return `${server}|${ref}`;
}

function maskToken(token = "") {
    const text = String(token);
    if (text.length <= 8) return "***";
    return `${text.slice(0, 4)}***${text.slice(-4)}`;
}

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch (e) {
        return {};
    }
}

function writeTokenCache(cache) {
    try {
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
    } catch (e) {
        console.log(`⚠️ [缓存] 写入失败: ${e.message || e}`);
    }
}

function maskPhone(phone = "") {
    return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2");
}

function isTokenError(message) {
    return /401|token|登录|授权|未登录|无效|过期/i.test(String(message || ""));
}

function aesEncrypt(text) {
    const cipher = crypto.createCipheriv("aes-128-ecb", Buffer.from(AES_KEY, "utf8"), null);
    cipher.setAutoPadding(true);
    return Buffer.concat([cipher.update(String(text), "utf8"), cipher.final()]).toString("base64");
}

class Task {
    constructor(account) {
        this.server = account;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.index = userIdx++;
        this.account = String(account || "").trim();
        this.token = "";
        this.userInfo = {};
        this.points = "";
        this.task = null;
        this.record = null;
        this.success = false;
        this._tokenDead = false;
        this.summary = {
            member: "-", pointsBefore: "-", pointsAfter: "-",
            continuous: "-", sign: "-", activity: "-", errors: [],
        };
    }

    async run() {
        const s = this.summary;
        try {
            const cached = this.getCachedToken();
            if (cached) {
                this.applyToken(cached);
                console.log(`💾 [缓存] 账号[${this.index}] 读取缓存 token（${maskToken(this.token)}）`);
                const valid = await this.checkToken();
                if (valid) {
                    console.log(`✅ [校验] 账号[${this.index}] 缓存 token 有效，直接复用`);
                } else {
                    console.log(`⚠️ [校验] 账号[${this.index}] 缓存 token 已失效，清除后重新登录`);
                    this.removeCachedToken();
                }
            }

            if (!this.token) {
                await this.loginByWxCode();
                if (!this.token) { s.errors.push("登录失败"); return s; }
            }

            await this.runBusiness();

            // 业务执行中检测到登录失效 → 清缓存重登重试一次
            if (this._tokenDead) {
                console.log(`🔄 [重登] 账号[${this.index}] 业务返回登录失效，清除缓存重新登录并重试一次`);
                this.removeCachedToken();
                await this.loginByWxCode();
                if (this.token) {
                    this._tokenDead = false;
                    s.errors.length = 0;
                    await this.runBusiness();
                } else {
                    s.errors.push("重新登录失败");
                }
            }
            this.success = s.errors.length === 0;
        } catch (e) {
            s.errors.push(brief(e && e.message ? e.message : e));
            console.log(`❌ [异常] 账号[${this.index}] ${e.message || e}`);
        }
        return s;
    }

    async runBusiness() {
        await this.getCustomerDetails();
        await this.getIntegral();
        await this.findCheckTask();
        await this.queryRecord();
        await this.signIn();
        await this.getIntegral();
    }

    cacheKeyOf() {
        return cacheKey(this.server.split("@").slice(0, -1).join("@").replace(/^https?:\/\//, "").replace(/\/+$/, ""), this.ref);
    }

    getCachedToken() {
        const cache = readTokenCache();
        const key = this.cacheKeyOf();
        if (cache[key] && cache[key].accessToken) return cache[key];
        // 旧键（整条账号串 / 仅标识 / 地址@标识）迁移
        for (const legacy of [this.account, this.ref]) {
            if (legacy && cache[legacy] && cache[legacy].accessToken) {
                cache[key] = { ...cache[legacy], updatedAt: new Date().toISOString() };
                delete cache[legacy];
                writeTokenCache(cache);
                console.log(`🗂️ [缓存] 账号[${this.index}] 旧缓存键已迁移为「地址|标识」`);
                return cache[key];
            }
        }
        return null;
    }

    saveCachedToken() {
        if (!this.token) return;
        const cache = readTokenCache();
        cache[this.cacheKeyOf()] = {
            accessToken: this.token,
            userInfo: this.userInfo || {},
            updatedAt: new Date().toISOString(),
        };
        writeTokenCache(cache);
    }

    removeCachedToken() {
        const cache = readTokenCache();
        const key = this.cacheKeyOf();
        let changed = false;
        for (const k of [key, this.account, this.ref]) {
            if (k && cache[k]) { delete cache[k]; changed = true; }
        }
        if (changed) writeTokenCache(cache);
        this.token = "";
        this.userInfo = {};
    }

    applyToken(data = {}) {
        this.token = data.accessToken || data.token || "";
        this.userInfo = data.userInfo || {};
    }

    getHeaders(extra = {}) {
        return {
            "User-Agent": USER_AGENT,
            "Referer": `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            appId: MINI_APP_ID,
            Authorization: this.token || "none",
            ...extra,
        };
    }

    async request({ method = "GET", apiPath, params = {}, data = {}, notAuth = false }) {
        const upperMethod = method.toUpperCase();
        const options = {
            method: upperMethod,
            url: `${API_BASE}${apiPath.startsWith("/") ? apiPath : `/${apiPath}`}`,
            headers: this.getHeaders(notAuth ? { Authorization: "none" } : {}),
            timeout: 20000,
            validateStatus: () => true,
        };
        if (upperMethod === "GET") options.params = params;
        else options.data = data;

        const { data: result, status } = await axios.request(options);
        if (status !== 200) throw new Error(`HTTP ${status}: ${JSON.stringify(result)}`);
        if (!result || (Number(result.code) !== 200 && String(result.code) !== "200")) {
            throw new Error(result?.msg || result?.message || JSON.stringify(result));
        }
        return result.data;
    }

    async getLoginCode() {
        return await getCode(this.server);
    }

    async loginByWxCode() {
        try {
            const code = await this.getLoginCode();
            if (!code) throw new Error("获取code失败");
            const data = await this.request({
                method: "POST",
                apiPath: "/login",
                notAuth: true,
                data: { code },
            });
            this.token = data?.accessToken || "";
            if (!this.token) throw new Error(`登录响应未返回 accessToken: ${JSON.stringify(data)}`);
            this.saveCachedToken();
            console.log(`✅ [登录] 账号[${this.index}] 登录成功`);
        } catch (e) {
            console.log(`❌ [登录] 账号[${this.index}] 登录失败: ${e.message || e}`);
        }
    }

    async checkToken() {
        try {
            await this.request({ apiPath: "/app/jingyoujia/customer/detail" });
            return true;
        } catch (e) {
            return false;
        }
    }

    async getCustomerDetails() {
        try {
            const data = await this.request({ apiPath: "/app/jingyoujia/customer/detail" });
            this.userInfo = data || {};
            this.saveCachedToken();
            const nick = data?.nickName || data?.nickname || "未知";
            const phone = maskPhone(data?.mobile || "");
            this.summary.member = `${nick}${phone ? " " + phone : ""}`;
            console.log(`👤 [用户] 账号[${this.index}] 会员: ${this.summary.member}`);
        } catch (e) {
            console.log(`❌ [用户] 账号[${this.index}] 查询会员失败: ${e.message || e}`);
            if (isTokenError(e.message || e)) this._tokenDead = true;
        }
    }

    async getIntegral() {
        try {
            const data = await this.request({ apiPath: "/app/jingyoujia/customer/queryCustIntegral" });
            this.points = data?.usableIntegral ?? data?.integral ?? data?.custIntegral ?? data?.points ?? "";
            const shown = this.points === "" ? JSON.stringify(data) : this.points;
            if (this.summary.pointsBefore === "-") this.summary.pointsBefore = shown;
            this.summary.pointsAfter = shown;
            console.log(`💰 [积分] 账号[${this.index}] 当前积分: ${shown}`);
        } catch (e) {
            console.log(`❌ [积分] 账号[${this.index}] 查询积分失败: ${e.message || e}`);
        }
    }

    async findCheckTask() {
        try {
            const data = await this.request({ apiPath: "/app/jingyoujia/taskContinuousRecord/findCheckTask" });
            // id 可能为 null，但只要有 taskName 或积分配置就说明有签到活动
            if (!data || (!data.id && !data.taskName && !data.showIntegralConfigs)) {
                this.summary.activity = "无签到活动";
                console.log(`ℹ️ [签到] 账号[${this.index}] 当前无签到活动`);
                return;
            }
            this.task = data;
            this.summary.activity = `${data.taskName || "每日签到"}（${data.betweenDays || 7}天周期）`;
            console.log(`📅 [签到] 账号[${this.index}] 签到活动: ${this.summary.activity}`);
        } catch (e) {
            console.log(`❌ [签到] 账号[${this.index}] 获取签到活动失败: ${e.message || e}`);
        }
    }

    async queryRecord() {
        if (!this.task?.id) {
            // id 为 null 时，签到状态可能不需要查记录，直接签
            return;
        }
        try {
            const data = await this.request({
                apiPath: "/app/jingyoujia/taskContinuousRecord/queryRecord",
                params: { taskId: this.task.id },
            });
            this.record = data || {};
            this.summary.continuous = `连续${data?.continuousNum ?? 0}天`;
            this.summary.sign = data?.todayFinish ? "今日已签到" : "今日未签到";
            console.log(`📅 [签到] 账号[${this.index}] 签到状态: ${this.summary.continuous} 今日=${data?.todayFinish ? "已签" : "未签"}`);
        } catch (e) {
            // 查询失败不影响签到
        }
    }

    async signIn() {
        if (!this.task) return;
        if (this.record?.todayFinish) {
            this.summary.sign = "今日已签到";
            console.log(`✅ [签到] 账号[${this.index}] 今日已签到`);
            return;
        }
        try {
            // id 为 null 时不传 taskId，否则传
            const bodyData = this.task.id ? { taskId: this.task.id } : {};
            const data = await this.request({
                method: "POST",
                apiPath: "/app/jingyoujia/taskContinuousRecord",
                data: { v1: aesEncrypt(JSON.stringify(bodyData)) },
            });
            const integral = data?.currentSignIntegral ?? data?.integral ?? "";
            this.summary.sign = `签到成功${integral !== "" ? ` +${integral}积分` : ""}`;
            console.log(`✅ [签到] 账号[${this.index}] ${this.summary.sign}`);
            await this.finishTask();
        } catch (e) {
            const message = String(e.message || e);
            if (/已签到|重复|todayFinish|已完成/.test(message)) {
                this.summary.sign = "今日已签到";
                console.log(`✅ [签到] 账号[${this.index}] 今日已签到`);
                return;
            }
            if (/20230529|captcha|验证码|滑块/.test(message)) {
                this.summary.sign = "需验证码，已跳过";
                this.summary.errors.push("签到需要验证码");
                console.log(`⚠️ [签到] 账号[${this.index}] 签到需要验证码，已跳过`);
                return;
            }
            this.summary.errors.push(`签到失败: ${message}`);
            console.log(`❌ [签到] 账号[${this.index}] 签到失败: ${message}`);
            if (isTokenError(message)) this._tokenDead = true;
        }
    }

    async finishTask() {
        try {
            await this.request({
                method: "POST",
                apiPath: "/business/member/task/finish",
                data: {
                    latitude: 0,
                    longitude: 0,
                    taskType: 1,
                },
            });
        } catch (e) {
            console.log(`⚠️ [任务] 账号[${this.index}] 完成任务上报失败: ${e.message || e}`);
        }
    }
}

async function sendPushPlus(title, content) {
    if (!NOTIFY_ENABLED || !PLUSPLUS_TOKEN) return false;
    try {
        await axios.post("https://www.pushplus.plus/send", {
            token: PLUSPLUS_TOKEN, title, content, template: "txt",
        }, { timeout: 10000 });
        return true;
    } catch (e) {
        console.log(`   ⚠️ [推送] PushPlus 失败: ${brief(e.message || e)}`);
        return false;
    }
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

    boxTop("💪 劲友家 每日任务");
    boxLine("🕒 启动时间", new Date().toLocaleString("zh-CN"));
    boxLine("🔢 账号数量", `${SERVERS.length} 个`);
    boxLine("💾 缓存", "jingyoujia_token_cache.json");
    boxLine("🌐 网络", "直连");
    boxBottom();

    const results = [];
    for (let i = 0; i < SERVERS.length; i++) {
        const entry = parseYybGoEntry(SERVERS[i]);
        const label = `标识 ${entry.ref || "-"}` + (entry.note ? `（${entry.note}）` : "");
        accountFrame(i + 1, SERVERS.length, label, SERVERS[i]);
        let summary = {
            member: "-", pointsBefore: "-", pointsAfter: "-",
            continuous: "-", sign: "-", activity: "-", errors: ["脚本未执行"],
        };
        await captureLogs(async () => {
            try {
                const task = new Task(SERVERS[i], i + 1);
                summary = await task.run();
            } catch (e) {
                const msg = brief(e && e.message ? e.message : e);
                summary = { ...summary, errors: [msg] };
                console.log(`❌ [账号] 执行失败: ${msg}`);
            }
        });
        const ok = summary.errors.length === 0 && summary.sign !== "-";
        console.log(ok ? "   ✅ [完成] 该账号任务执行完成" : "   ❌ [完成] 该账号存在失败项");
        results.push({
            index: i + 1, ref: entry.ref, source: SERVERS[i], ok, summary,
        });
        hr();
        if (i < SERVERS.length - 1) {
            console.log("   ⏳ 等待2秒后执行下一个账号...");
            await sleep(2000);
        }
    }

    console.log("");
    for (const r of results) {
        const s = r.summary;
        const contSuffix = s.continuous !== "-" ? `（${s.continuous}）` : "";
        console.log(`${r.ok ? "✅" : "❌"} 【账号 ${r.index} · ${r.source}】`);
        console.log(`   👤 [会员] ${s.member}`);
        console.log(`   📅 [签到] ${s.sign}${contSuffix}`);
        console.log(`   💰 [积分] ${s.pointsBefore} → ${s.pointsAfter}`);
        if (s.activity !== "-") console.log(`   📋 [活动] ${s.activity}`);
        if (!r.ok) console.log(`   ⚠️ [失败] ${s.errors[0] || "见日志"}`);
    }

    const okCount = results.filter(r => r.ok).length;
    boxTop("🏁 💪 劲友家 执行汇总");
    boxLine("📊 执行结果", `成功 ${okCount} / 失败 ${results.length - okCount} / 共 ${results.length}`);
    boxLine("🕒 结束时间", new Date().toLocaleString("zh-CN"));
    boxBottom();

    const content = results.map(r => {
        const s = r.summary;
        const lines = [
            `${r.ok ? "✅" : "❌"} 账号${r.index} ${r.source}`,
            `- 会员：${s.member}`,
            `- 签到：${s.sign}${s.continuous !== "-" ? `（${s.continuous}）` : ""}`,
            `- 积分：${s.pointsBefore} → ${s.pointsAfter}`,
        ];
        if (s.activity !== "-") lines.push(`- 活动：${s.activity}`);
        if (!r.ok) lines.push(`- 失败原因：${s.errors[0] || "见日志"}`);
        return lines.join("\n");
    }).join("\n\n");

    if (NOTIFY_ENABLED) {
        const sent = await sendQingLongNotify("💪 劲友家任务完成", content);
        console.log(sent ? "   📮 [通知] 已调用青龙 notify" : "   ℹ️ [通知] 未找到青龙 notify 脚本");
        await sendPushPlus("💪 劲友家任务完成", content);
    } else {
        console.log("   ℹ️ [通知] JYJ_NOTIFY=0，已关闭通知");
    }
})().catch(e => console.log(`❌ [全局异常] ${e.message}`));
