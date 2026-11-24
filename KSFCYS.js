// name: 康师傅畅饮社
// cron: 24 12,0 * * *
const axios = require("axios");
const fs = require("fs");
const path = require("path");

// ====================== 基础配置 ======================
const MINI_APP_ID = "wx54f3e6a00f7973a7";
const API_BASE = "https://club.biqr.cn/";
const FORUM_BASE = "https://nclub.gdshcm.com/pro/";
const VIDEO_BASE = "https://club.ksf.cn/";
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "kangshifu_token_cache.json");
const NOTIFY_ON = String(process.env.KSFCYS_NOTIFY ?? "1") !== "0";
const VIDEO_TYPES = [1, 2, 3, 4];
const TYPE_NAMES = { 1: "品牌故事", 2: "热门赛事", 3: "快闪活动", 4: "活动宣传" };
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254173b) XWEB/19027";

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
function brief(value, limit = 90) { const text = String(value ?? "").replace(/\n/g, " "); return text.length <= limit ? text : text.slice(0, limit - 1) + "…"; }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function maskPhone(phone = "") { return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2"); }
function shortToken(token = "") { const v = String(token); return v ? `${v.slice(0, 6)}***${v.slice(-4)}` : ""; }
function deltaText(before, after) {
    if (before === null || before === undefined || after === null || after === undefined) return "";
    const b = Number(before), a = Number(after);
    if (!Number.isFinite(b) || !Number.isFinite(a)) return "";
    return `${before} → ${after}（${a - b >= 0 ? "+" : ""}${a - b}）`;
}
function formBody(data = {}) { return new URLSearchParams(data).toString(); }

// ====================== 账号解析（环境变量用，带提示） ======================
function parseYybGoEntry(rawValue) {
    let value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "", note: "" };
    let note = "";
    const hashIndex = value.lastIndexOf("#");
    if (hashIndex !== -1 && hashIndex > value.lastIndexOf("@")) {
        note = value.slice(hashIndex + 1).trim();
        value = value.slice(0, hashIndex).trim();
    }
    const atIndex = value.lastIndexOf("@");
    if (atIndex === -1) {
        console.log("   ❌ [账号] 格式应为 地址@标识[#备注]，当前值: " + value);
        return { server: "", ref: "", note: "" };
    }
    const server = value.slice(0, atIndex).trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
    const ref = value.slice(atIndex + 1).trim();
    if (!server || !ref) return { server: "", ref: "", note: "" };
    return { server, ref, note };
}

/** 静默解析缓存键标识：兼容「纯标识」「地址@标识」「地址@标识#备注」「整条账号串」 */
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
function cacheKeyOf(server, ref) { return `${server}|${ref}`; }

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch { return {}; }
}
function writeTokenCache(cache) {
    try { fs.mkdirSync(TOKEN_CACHE_DIR, { recursive: true }); fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8"); } catch (e) { console.log("⚠️ 缓存写入失败:", e.message); }
}

const SERVERS = (process.env.YYB_SERVER || "").split(/\r?\n/).map(s => s.trim()).filter(Boolean);

async function getCode(server, ref) {
    const url = "http://" + server + "/wxapp/getCode";
    try {
        const { data } = await axios.post(url, { ref, app_id: MINI_APP_ID }, { timeout: 20000, proxy: false });
        const code = data?.data?.result?.code;
        if (!data || data.code !== 0 || !code) {
            console.log(`   ❌ [取码] 获取 code 失败: ${brief(JSON.stringify(data))}`);
            return null;
        }
        console.log("   ✅ [取码] code 获取成功");
        return code;
    } catch (e) {
        console.log(`   ❌ [取码] 获取 code 异常: ${brief(e.message)}`);
        return null;
    }
}

// ====================== 业务类 ======================
class Task {
    constructor(entry, index) {
        const { server, ref, note } = parseYybGoEntry(entry);
        this.server = server;
        this.ref = ref;
        this.note = note;
        this.key = cacheKeyOf(server, ref);
        this.index = index;
        this.token = "";
        this.member = {};
    }

    headers(extra = {}) {
        const h = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "xweb_xhr": "1",
            "Referer": "https://servicewechat.com/wx54f3e6a00f7973a7/816/page-frame.html",
            "Accept-Language": "zh-CN,zh;q=0.9",
            ...extra,
        };
        if (this.token) { h.token = this.token; h.Token = this.token; }
        return h;
    }

    async request(baseURL, apiPath, { method = "GET", data, params, auth = true, form = false } = {}) {
        const options = {
            method,
            url: new URL(apiPath, baseURL).toString(),
            params,
            headers: this.headers(form ? { "Content-Type": "application/x-www-form-urlencoded" } : {}),
            timeout: 15000,
            validateStatus: () => true,
            proxy: false,
        };
        if (!auth) { delete options.headers.token; delete options.headers.Token; }
        if (data !== undefined) options.data = form ? formBody(data) : data;

        const { data: result, status } = await axios.request(options);
        if (status !== 200) throw new Error(`HTTP ${status}`);
        if (Number(result?.code) !== 0) {
            const err = new Error(brief(result?.msg || result?.error || JSON.stringify(result), 120));
            if (/token.*(无效|过期|失效|非法)|未登录|登录已过期|请先登录|身份验证失败/i.test(err.message)) err.tokenInvalid = true;
            throw err;
        }
        return result;
    }

    // ---------- 缓存 ----------
    loadCache() {
        const cache = readTokenCache();
        let cached = cache[this.key];
        if (!cached) {
            for (const k of Object.keys(cache)) {
                if (cache[k] && legacyRefOf(k) === this.ref) {
                    cached = cache[k];
                    cache[this.key] = cached;
                    delete cache[k];
                    writeTokenCache(cache);
                    console.log("   🗂️ [缓存] 旧缓存键已迁移为「地址|标识」");
                    break;
                }
            }
        }
        if (cached?.token) {
            this.token = cached.token;
            this.member = cached.member || {};
            console.log(`   💾 [缓存] 复用已保存 token: ${shortToken(this.token)}`);
            return true;
        }
        return false;
    }
    saveCache(extra = {}) {
        if (!this.token) return;
        const cache = readTokenCache();
        const old = cache[this.key] || {};
        cache[this.key] = { ...old, token: this.token, member: this.member, ...extra, updatedAt: new Date().toLocaleString("zh-CN", { hour12: false }) };
        for (const k of Object.keys(cache)) {
            if (k !== this.key && legacyRefOf(k) === this.ref) delete cache[k];
        }
        writeTokenCache(cache);
    }
    removeCache() {
        const cache = readTokenCache();
        delete cache[this.key];
        for (const k of Object.keys(cache)) if (legacyRefOf(k) === this.ref) delete cache[k];
        writeTokenCache(cache);
        this.token = "";
        this.member = {};
    }

    // ---------- 登录 / 校验 ----------
    async loginByWxCode() {
        const code = await getCode(this.server, this.ref);
        if (!code) throw new Error("获取 code 失败");
        const result = await this.request(FORUM_BASE, "whale-member/api/login/login", {
            method: "POST", auth: false,
            data: { code, inviterId: "", inviterType: "", inviterMatchUserId: "", spUrl: "" },
        });
        const token = result?.data?.token || "";
        if (!token) throw new Error("登录未返回 token");
        this.token = token;
        this.member = result?.data?.member || {};
        this.saveCache();
        const name = this.member.nickname || maskPhone(this.member.phone) || this.member.id || "未知";
        console.log(`   ✅ [登录] 新 token 获取成功（${name}）`);
        return true;
    }

    async getMemberInfo() {
        const result = await this.request(FORUM_BASE, "whale-member/api/member/getMemberInfo", { params: { token: this.token } });
        this.member = result?.data || this.member;
        return this.member;
    }

    async verifyToken() {
        try {
            await this.getMemberInfo();
        } catch (e) {
            return { ok: false, msg: e.message };
        }
        // 视频域是独立会话，必须在开跑前一起校验，否则会跑到一半才提示未登录
        try {
            await this.request(VIDEO_BASE, "api/shortVideo/getVideoList", { params: { keyWord: "", pageNum: 1, pageSize: 1, type: 1 } });
        } catch (e) {
            if (e.tokenInvalid) return { ok: false, msg: e.message };
            console.log(`   ⚠️ [校验] 视频接口暂不可用（${brief(e.message, 40)}），跳过视频域校验`);
        }
        return { ok: true };
    }

    // ---------- 业务 ----------
    async signIn() {
        const statusRes = await this.request(API_BASE, "api/signIn/integralSignInList", { method: "POST", data: { token: this.token }, form: true });
        const status = statusRes?.data || {};
        if (status?.signIs) return { ok: true, text: "今日已签到", changed: false };
        const result = await this.request(API_BASE, "api/signIn/integralSignIn", { method: "POST", data: { token: this.token }, form: true });
        return { ok: true, text: `签到成功${result?.msg ? `（${result.msg}）` : ""}`, changed: true };
    }

    async watchVideo() {
        const cache = readTokenCache();
        const watched = (cache[this.key]?.watchedVideos) || [];
        let count = 0;
        for (const type of VIDEO_TYPES) {
            let listRes;
            try {
                listRes = await this.request(VIDEO_BASE, "api/shortVideo/getVideoList", { params: { keyWord: "", pageNum: 1, pageSize: 20, type } });
            } catch (e) {
                if (e.tokenInvalid) throw e;
                console.log(`   ⚠️ [视频] ${TYPE_NAMES[type]} 列表获取失败: ${brief(e.message)}`);
                continue;
            }
            const videos = (listRes?.rows || []).filter(v => v && v.id && !watched.includes(v.id));
            if (!videos.length) { console.log(`   ℹ️ [视频] ${TYPE_NAMES[type]}：已全部看过`); continue; }
            console.log(`   🎬 [视频] ${TYPE_NAMES[type]}：${videos.length} 个新视频`);
            for (const video of videos) {
                const name = String(video.name || "视频").slice(0, 20);
                try {
                    await this.request(VIDEO_BASE, "api/shortVideo/click", { method: "POST", params: { type, videoId: video.id }, data: {}, form: true });
                    console.log(`   ⏳ [视频] 正在观看: ${name}（30 秒）`);
                    await sleep(30000);
                    await this.request(VIDEO_BASE, "api/shortVideo/addIntegral", { method: "POST", params: { videoId: video.id }, data: {}, form: true });
                    console.log(`   ✅ [视频] 观看完成: ${name}`);
                    watched.push(video.id);
                    count++;
                    this.saveCache({ watchedVideos: watched });
                } catch (e) {
                    if (e.tokenInvalid) throw e;
                    console.log(`   ⚠️ [视频] 观看失败: ${name} - ${brief(e.message)}`);
                }
                await sleep(3000);
            }
        }
        this.saveCache({ watchedVideos: watched });
        return { ok: true, count, total: watched.length };
    }

    async run() {
        const result = { index: this.index, ref: this.ref, note: this.note, ok: true, name: "", pointsBefore: null, pointsAfter: null, signText: "", videoText: "", error: "" };
        const usedCache = this.loadCache();

        for (let attempt = 0; attempt < 2; attempt++) {
            try {
                if (attempt === 0 && usedCache) {
                    const verify = await this.verifyToken();
                    if (!verify.ok) {
                        console.log(`   ⚠️ [校验] 缓存 token 失效（${brief(verify.msg, 40)}），清除后重新登录`);
                        this.removeCache();
                        await this.loginByWxCode();
                        console.log("   ✅ [校验] 重新登录成功");
                    } else {
                        console.log("   ✅ [校验] 缓存 token 有效，直接复用");
                    }
                } else if (!this.token) {
                    await this.loginByWxCode();
                }

                const member = await this.getMemberInfo();
                const name = member?.nickname || maskPhone(member?.phone) || member?.id || "未知";
                result.name = String(name);
                result.pointsBefore = member?.integral ?? member?.point ?? member?.points ?? member?.score ?? null;
                console.log(`   👤 [会员] ${result.name}`);
                console.log(`   💰 [积分] ${result.pointsBefore === null ? "未知" : result.pointsBefore}`);

                const sign = await this.signIn();
                result.signText = sign.text;
                console.log(`   ${sign.ok ? "✅" : "❌"} [签到] ${sign.text}`);

                const video = await this.watchVideo();
                result.videoText = video.count > 0 ? `本次观看 ${video.count} 个新视频（累计 ${video.total}）` : `无新视频（累计 ${video.total}）`;
                console.log(`   ✅ [视频] ${result.videoText}`);

                const after = await this.getMemberInfo();
                result.pointsAfter = after?.integral ?? after?.point ?? after?.points ?? after?.score ?? null;
                console.log(`   💰 [积分] ${deltaText(result.pointsBefore, result.pointsAfter) || (result.pointsAfter ?? "未知")}`);
                return result;
            } catch (e) {
                const msg = e && e.message ? e.message : String(e);
                if (attempt === 0 && (e.tokenInvalid || usedCache)) {
                    console.log(`   ⚠️ [校验] 缓存 token 已失效（${brief(msg, 40)}），清除后重新登录`);
                    this.removeCache();
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
    const token = process.env.PUSH_PLUS_TOKEN || process.env.PUSHPLUS_TOKEN || "";
    if (!token) return false;
    try {
        const res = await axios.post("https://www.pushplus.plus/send", { token, title, content, template: "txt" }, { timeout: 15000, proxy: false });
        return Number(res?.data?.code) === 200;
    } catch (e) {
        console.log(`   ⚠️ [通知] PushPlus 推送失败: ${brief(e.message, 50)}`);
        return false;
    }
}

// ====================== 主流程 ======================
(async () => {
    if (!SERVERS.length) {
        console.log("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识[#备注]，多账号换行分隔）");
        process.exitCode = 1;
        return;
    }

    boxTop("🥤 康师傅畅饮社 每日任务");
    boxLine("🕒 启动时间", new Date().toLocaleString("zh-CN", { hour12: false }));
    boxLine("🔢 账号数量", `${SERVERS.length} 个`);
    boxLine("💾 缓存名称", "kangshifu_token_cache.json");
    boxLine("🌐 网络", "直连");
    boxBottom();

    const results = [];
    for (let i = 0; i < SERVERS.length; i++) {
        const entry = parseYybGoEntry(SERVERS[i]);
        const label = `标识 ${entry.ref || "-"}` + (entry.note ? `（${entry.note}）` : "");
        accountFrame(i + 1, SERVERS.length, label, SERVERS[i]);
        const r = await new Task(SERVERS[i], i + 1).run();
        results.push(r);
        if (!r.ok) console.log(`   ❌ [完成] 该账号存在失败项（${brief(r.error, 60)}）`);
        else console.log("   ✅ [完成] 该账号任务执行完成");
        hr();
        if (i < SERVERS.length - 1) {
            console.log("   ⏳ 等待 2 秒后执行下一个账号...");
            await sleep(2000);
        }
    }

    const ok = results.filter(r => r.ok).length;
    console.log("");
    for (const r of results) {
        console.log(`${r.ok ? "✅" : "❌"} 账号 ${r.index} / ${results.length}　标识 ${r.ref || "-"}${r.note ? `（${r.note}）` : ""}`);
        console.log(`   👤 会员：${r.name || "未知"}`);
        console.log(`   💰 积分：${deltaText(r.pointsBefore, r.pointsAfter) || (r.pointsAfter ?? r.pointsBefore ?? "未知")}`);
        console.log(`   📅 签到：${r.signText || (r.ok ? "已完成" : "未完成")}`);
        if (r.videoText) console.log(`   🎬 视频：${r.videoText}`);
        if (!r.ok) console.log(`   ⚠️ 失败：${brief(r.error, 80)}`);
        console.log("");
    }
    boxTop("🏁 🥤 康师傅畅饮社 执行汇总");
    boxLine("📊 执行结果", `成功 ${ok} / 失败 ${results.length - ok} / 共 ${results.length}`);
    boxLine("🕒 结束时间", new Date().toLocaleString("zh-CN", { hour12: false }));
    boxBottom();

    const content = results.map(r => `${r.ok ? "✅" : "❌"} 账号${r.index} 标识 ${r.ref || "-"}\n会员：${r.name || "未知"}\n积分：${deltaText(r.pointsBefore, r.pointsAfter) || (r.pointsAfter ?? "未知")}\n签到：${r.signText || "未完成"}${r.videoText ? `\n视频：${r.videoText}` : ""}` + (r.ok ? "" : `\n失败：${r.error}`)).join("\n\n");

    if (NOTIFY_ON) {
        const sent = await sendQingLongNotify("🥤 康师傅畅饮社任务完成", content);
        console.log(sent ? "   📮 [通知] 已通过青龙 notify 推送" : "   ℹ️ [通知] 未找到青龙 notify 脚本");
        if (await sendPushPlus("🥤 康师傅畅饮社任务完成", content)) console.log("   📨 [通知] PushPlus 推送成功");
    } else {
        console.log("   ℹ️ [通知] KSFCYS_NOTIFY=0，已关闭通知");
    }
})().catch(e => console.log(`❌ [全局异常] ${e.message}`));
