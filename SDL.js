// name: 三得利
// cron: 48 8,20 * * *
const axios = require("axios");
const fs = require("fs");
const path = require("path");

// ====================== YYB Go 账号 ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.error("❌ 未配置环境变量 YYB_SERVER");
    process.exit(1);
}

const APPID = "wxb33ed03c6c715482";
const API_BASE = "https://xiaodian.miyatech.com/api";

// Token 缓存
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "sdl_token_cache.json");
try { fs.mkdirSync(TOKEN_CACHE_DIR, { recursive: true }); } catch (e) {}

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch { return {}; }
}
function writeTokenCache(cache) {
    try { fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8"); } catch (e) {}
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const HEADERS = {
    "HH-FROM": "20230130307725",
    "HH-APP": APPID,
    "HH-VERSION": "0.6.1",
    "X-VERSION": "2.3.5",
    "HH-CI": "saas-wechat-app",
    "appPublishType": "1",
    "componentSend": "1",
    "content-type": "application/json;charset=UTF-8",
    "Referer": `https://servicewechat.com/${APPID}/72/page-frame.html`,
};

function parseYybGoEntry(raw) {
    const v = String(raw || "").trim();
    if (!v) return { server: "", ref: "" };
    const i = v.indexOf("@");
    if (i === -1) return { server: "", ref: "" };
    let server = v.slice(0, i).trim();
    const ref = v.slice(i + 1).trim();
    if (server.startsWith("http://")) server = server.slice(7);
    else if (server.startsWith("https://")) server = server.slice(8);
    server = server.replace(/\/+$/, "");
    return { server, ref };
}

async function getCode(server) {
    const { server: s, ref } = parseYybGoEntry(server);
    if (!s || !ref) return null;
    try {
        const { data } = await axios.post(`http://${s}/wxapp/getCode`, { ref, app_id: APPID }, { timeout: 20000, proxy: false });
        const code = data?.data?.result?.code;
        if (data?.code !== 0 || !code) {
            console.log(`❌ [取码] 获取code失败: ${JSON.stringify(data).slice(0, 100)}`);
            return null;
        }
        console.log(`✅ [取码] 获取code成功`);
        return code;
    } catch (e) {
        console.log(`❌ [取码] 获取code异常: ${e.message}`);
        return null;
    }
}

// ====================== 输出美化 ======================
function logTitle() {
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🥃 三得利 自动签到                          ║");
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
function logEnd(successCount, failCount) {
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🏁 三得利任务完成                            ║");
    console.log(`║  ✅ 成功: ${String(successCount).padEnd(22)}║`);
    console.log(`║  ❌ 失败: ${String(failCount).padEnd(22)}║`);
    console.log(`║  🕒 结束时间: ${new Date().toLocaleString("zh-CN", { hour12: false }).padEnd(22)}║`);
    console.log("╚" + "═".repeat(48) + "╝");
}

class SanDele {
    constructor(server, index) {
        this.server = server;
        this.index = index;
        this.token = "";
    }

    async api(path, body = {}, auth = true) {
        const headers = { ...HEADERS };
        if (auth && this.token) headers["Authorization"] = `Bearer ${this.token}`;
        const res = await axios.post(`${API_BASE}${path}`, body, {
            headers, timeout: 20000, proxy: false, validateStatus: () => true,
        });
        return res.data;
    }

    async login() {
        const code = await getCode(this.server);
        if (!code) return false;
        const res = await this.api("/user/login/wx-jc", {
            jsCode: code, clientId: "saas-wechat-app", myUnionId: "", appPublishType: 1,
        }, false);
        if (res?.code !== 200 || !res.data?.tokenInfo?.access_token) {
            console.log(`❌ [登录] 账号[${this.index}] 登录失败: ${res?.msg || "未知"}`);
            return false;
        }
        this.token = res.data.tokenInfo.access_token;
        const c = readTokenCache();
        c[this.server] = { access_token: this.token };
        writeTokenCache(c);
        console.log(`✅ [登录] 账号[${this.index}] 登录成功`);
        return true;
    }

    async signIn() {
        const res = await this.api("/coupon/auth/signIn", { miniappId: 159 });
        if (res?.code === 200) {
            console.log(`✅ [签到] 账号[${this.index}] 签到成功: ${res.data?.integralToastText || ""}`);
            return true;
        }
        const msg = res?.msg || "";
        // 正常的"已签到"状态，不算失败也不算token失效
        if (/已签到|已获得|已签过|重复签到|今日已签/.test(msg)) {
            console.log(`ℹ️ [签到] 账号[${this.index}] ${msg}`);
            return true;
        }
        // 真token失效才抛错重登
        if (res?.code === 401 || /未登录|登录已过期|token.*(无效|过期|失效)|请重新登录/i.test(msg)) {
            const err = new Error(msg || "token失效");
            err.tokenInvalid = true;
            throw err;
        }
        console.log(`⚠️ [签到] 账号[${this.index}] 签到结果: ${msg || "未知"}`);
        return false;
    }

    async collect() {
        const res = await this.api("/user/auth/user/collect/record/save", { sceneValue: "1104" });
        if (res?.code === 200) {
            console.log(`✅ [收藏] 账号[${this.index}] 收藏成功: ${res.data?.integralToastText || ""}`);
            return;
        }
        const msg = res?.msg || "";
        if (/已获取|已领取|已完成|已收藏/.test(msg)) {
            console.log(`ℹ️ [收藏] 账号[${this.index}] ${msg}`);
        } else {
            console.log(`⚠️ [收藏] 账号[${this.index}] 收藏结果: ${msg || "未知"}`);
        }
    }

    async getScore() {
        const res = await this.api("/user/member/info", {});
        const score = res?.data?.currentScore ?? "未知";
        console.log(`💰 [积分] 账号[${this.index}] 当前积分: ${score}`);
    }

    async run() {
        // 读缓存
        const cache = readTokenCache();
        const cached = cache[this.server] || {};
        if (cached.access_token) {
            this.token = cached.access_token;
            console.log(`💾 [缓存] 账号[${this.index}] 使用缓存token`);
        }

        for (let attempt = 0; attempt < 2; attempt++) {
            try {
                if (attempt === 1) {
                    console.log(`🔄 [重登] 账号[${this.index}] token失效，清除缓存重新登录...`);
                    const c = readTokenCache();
                    delete c[this.server];
                    writeTokenCache(c);
                    if (!await this.login()) return false;
                }
                if (!this.token) {
                    if (!await this.login()) return false;
                }

                await sleep(1000);
                await this.signIn();
                await sleep(1000);
                await this.collect();
                await sleep(1000);
                await this.getScore();
                return true;
            } catch (e) {
                if (e.tokenInvalid && attempt === 0) {
                    console.log(`🔄 [重登] 账号[${this.index}] token失效(${e.message})，准备重新登录...`);
                    continue;
                }
                console.log(`❌ [执行] 账号[${this.index}] 失败: ${e.message}`);
                return false;
            }
        }
        return false;
    }
}

(async () => {
    logTitle();
    let successCount = 0, failCount = 0;
    for (let i = 0; i < SERVERS.length; i++) {
        logAccountHeader(i + 1, SERVERS.length, SERVERS[i]);
        const ok = await new SanDele(SERVERS[i], i + 1).run();
        if (ok) successCount++; else failCount++;
        await sleep(1500);
    }
    logEnd(successCount, failCount);
})().catch(e => console.log(`❌ 脚本异常: ${e.message}`));
