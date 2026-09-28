// name: 戴可思
// cron: 24 16,4 * * *
const axios = require("axios");
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
    const value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "" };
    const atIndex = value.indexOf("@");
    if (atIndex === -1) {
        console.log("⚠️ YYB_SERVER 格式应为 地址@微信账号标识，当前值: " + value);
        return { server: "", ref: "" };
    }
    let server = value.slice(0, atIndex).trim();
    const ref = value.slice(atIndex + 1).trim();
    if (server.startsWith("http://")) server = server.slice(7);
    else if (server.startsWith("https://")) server = server.slice(8);
    server = server.replace(/\/+$/, "");
    if (!server || !ref) return { server: "", ref: "" };
    return { server, ref };
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

const MINI_APP_ID = "wx9d46d96c4c35a53a";
const CLIENT_BIZ = "weapp_wsc";
const KDT_ID = "46323516";
const USER_VERSION = "2.233.4.101";
const PAGE_VERSION = "96";
const API_BASE = "https://h5.youzan.com";
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "dks_token_cache.json");
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

// ==================== 缓存 ====================
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
        fs.mkdirSync(TOKEN_CACHE_DIR, { recursive: true });
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
    } catch (e) {
        console.log(`⚠️ [缓存] 写入失败: ${e.message || e}`);
    }
}

function maskPhone(phone = "") {
    return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2");
}

function pickToken(data = {}) {
    return data.accessToken || data.access_token || "";
}

// ==================== 输出美化 ====================
function logTitle() {
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🧴 戴可思 自动签到                          ║");
    console.log(`║  🕒 启动时间: ${new Date().toLocaleString("zh-CN", { hour12: false }).padEnd(22)}║`);
    console.log(`║  🔢 账号数量: ${String(SERVERS.length).padEnd(22)}║`);
    console.log("╚" + "═".repeat(48) + "╝");
}

function logAccountHeader(index, total, server) {
    const { ref } = parseYybGoEntry(server);
    console.log();
    console.log("┌" + "─".repeat(48) + "┐");
    console.log(`│  🧩 账号 ${index} / ${total}${" ".repeat(26)}│`);
    console.log(`│  🔑 标识: ${String(ref || "-").padEnd(41)}│`);
    console.log("└" + "─".repeat(48) + "┘");
}

class Task {
    constructor(openid) {
        this.server = openid;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.index = userIdx++;
        this.openid = String(openid || "").trim();
        this.token = "";
        this.sessionId = "";
        this.cookie = "";
        this.kdtId = KDT_ID;
        this.userInfo = {};
    }

    async run() {
        const usedCache = !!this.getCachedToken();
        if (usedCache) {
            const cached = this.getCachedToken();
            this.token = cached.accessToken || "";
            this.sessionId = cached.sessionId || "";
            this.kdtId = cached.kdtId || KDT_ID;
            this.cookie = cached.cookie || "";
            this.userInfo = cached;
            console.log(`💾 [缓存] 账号[${this.index}] 使用缓存token: ${this.token.slice(0, 8)}***`);
        }
        for (let attempt = 0; attempt < 2; attempt++) {
            if (attempt === 1 || !this.token) {
                if (attempt === 1) {
                    console.log(`🔄 [重登] 账号[${this.index}] token失效，重新登录...`);
                    this.removeCachedToken();
                }
                await this.loginByWxCode();
                if (!this.token) return;
            }
            try {
                await this.showCheckinPage();
                await this.doCheckin();
                await this.getPoints();
                return;
            } catch (e) {
                const msg = String(e.message || e);
                if (attempt === 0 && usedCache && /access_token|token|登录|授权|invalid session|401|403/i.test(msg)) {
                    console.log(`🔄 [重登] 账号[${this.index}] 业务token失效，清除缓存重新登录...`);
                    this.removeCachedToken();
                    continue;
                }
                console.log(`❌ [执行] 账号[${this.index}] 执行失败: ${msg}`);
            }
        }
    }

    getCachedToken() {
        const cache = readTokenCache();
        return cache[this.openid] || null;
    }

    saveCachedToken() {
        if (!this.token) return;
        const cache = readTokenCache();
        cache[this.openid] = {
            accessToken: this.token,
            sessionId: this.sessionId,
            kdtId: this.kdtId,
            cookie: this.cookie,
            mobile: this.userInfo.mobile || "",
            nickName: this.userInfo.nick_name || this.userInfo.nickName || "",
        };
        writeTokenCache(cache);
    }

    removeCachedToken() {
        const cache = readTokenCache();
        if (cache[this.openid]) {
            delete cache[this.openid];
            writeTokenCache(cache);
        }
        this.token = "";
        this.sessionId = "";
        this.cookie = "";
    }

    applyToken(data = {}) {
        this.token = pickToken(data);
        this.sessionId = data.sessionId || data.session_id || "";
        this.kdtId = String(data.kdtId || data.kdt_id || KDT_ID);
        this.cookie = data.cookie || "";
    }

    getHeaders(extra = {}) {
        const headers = {
            "User-Agent": USER_AGENT,
            "Referer": `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            "Accept": "*/*",
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
        return {
            app_id: MINI_APP_ID,
            kdt_id: this.kdtId,
            access_token: this.token,
            ...params,
        };
    }

    async request({ method = "GET", path: apiPath, params = {}, data = {}, skipToken = false }) {
        const options = {
            method,
            url: `${API_BASE}${apiPath.startsWith("/") ? apiPath : `/${apiPath}`}`,
            headers: this.getHeaders(method === "POST" ? { "Content-Type": "application/json" } : {}),
            timeout: 15000,
            validateStatus: () => true,
        };
        options.params = skipToken ? params : this.getBaseParams(params);
        if (method !== "GET") options.data = data;

        const { data: result, status, headers } = await axios.request(options);
        if (headers["set-cookie"]) {
            this.cookie = headers["set-cookie"].map((item) => item.split(";")[0]).join("; ");
        }
        if (status !== 200) throw new Error(`HTTP ${status}: ${JSON.stringify(result)}`);
        if (!result || result.code !== 0) throw new Error(result?.msg || JSON.stringify(result));
        return result.data;
    }

    async getLoginCode() {
        return await getCode(this.server);
    }

    async loginByWxCode() {
        try {
            console.log(`🔐 [登录] 账号[${this.index}] 使用 code 换取 token...`);
            const code = await this.getLoginCode();
            const data = await this.request({
                method: "POST",
                path: "/wscshop/weapp/authorize.json",
                skipToken: true,
                data: {
                    appId: MINI_APP_ID,
                    clientBiz: CLIENT_BIZ,
                    code,
                },
            });
            this.applyToken(data);
            this.userInfo = data || {};
            this.saveCachedToken();
            console.log(`✅ [登录] 账号[${this.index}] 登录成功: ${data.nick_name || data.nickName || ""} ${maskPhone(data.mobile) || ""}`);
        } catch (e) {
            console.log(`❌ [登录] 账号[${this.index}] 登录失败: ${e.message || e}`);
        }
    }

    async checkToken() {
        try {
            const data = await this.request({ path: "/wscump/integral/user_points.json" });
            this.points = data?.current_points ?? data?.real_points;
            return true;
        } catch (e) {
            return false;
        }
    }

    async showCheckinPage() {
        try {
            const data = await this.request({ path: "/wscump/checkin/show_checkin_page_v2.json" });
            this.checkinId = data?.checkinId;
            this.isShow = !!data?.isShow;
            console.log(`📋 [活动] 账号[${this.index}] checkinId=${this.checkinId || "未获取"} isShow=${this.isShow}`);
        } catch (e) {
            console.log(`❌ [活动] 账号[${this.index}] 获取签到活动失败: ${e.message || e}`);
            if (/access_token|token|登录|授权|invalid session/i.test(String(e.message || e))) throw e;
        }
    }

    async doCheckin() {
        if (!this.checkinId) {
            console.log(`⚠️ [签到] 账号[${this.index}] 未获取到 checkinId，跳过签到`);
            return;
        }
        try {
            const data = await this.request({
                path: "/wscump/checkin/checkinV2.json",
                params: { checkinId: this.checkinId },
            });
            const awards = (data?.list || []).map((item) => item?.infos?.title).filter(Boolean).join(", ");
            console.log(`✅ [签到] 账号[${this.index}] 签到成功: ${data?.desc || ""}${awards ? ` ${awards}` : ""}`);
        } catch (e) {
            const message = String(e.message || e);
            if (/已达最大参与次数|已签到|重复签到/.test(message)) {
                console.log(`✅ [签到] 账号[${this.index}] 今日已签到`);
                return;
            }
            console.log(`❌ [签到] 账号[${this.index}] 签到失败: ${message}`);
            if (/access_token|token|登录|授权|invalid session/i.test(message)) throw e;
        }
    }

    async getPoints() {
        try {
            const data = await this.request({ path: "/wscump/integral/user_points.json" });
            console.log(`💰 [积分] 账号[${this.index}] 当前积分: ${data?.current_points ?? data?.real_points ?? "未知"}`);
        } catch (e) {
            console.log(`❌ [积分] 账号[${this.index}] 查询积分失败: ${e.message || e}`);
        }
    }
}

!(async () => {
    logTitle();
    let successCount = 0;
    let failCount = 0;
    let currentIdx = 1;
    for (const openid of SERVERS) {
        logAccountHeader(currentIdx, SERVERS.length, openid);
        const before = new Task(openid);
        await before.run();
        if (before.token) successCount++; else failCount++;
        currentIdx++;
    }
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🏁 戴可思任务执行完成                        ║");
    console.log(`║  ✅ 成功: ${String(successCount).padEnd(22)}║`);
    console.log(`║  ❌ 失败: ${String(failCount).padEnd(22)}║`);
    console.log(`║  🕒 结束时间: ${new Date().toLocaleString("zh-CN", { hour12: false }).padEnd(22)}║`);
    console.log("╚" + "═".repeat(48) + "╝");
})()
    .catch((e) => console.log(e.message || e));
