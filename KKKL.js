// name: 可口可乐
// cron: 32 12,0 * * *
const axios = require("axios");
const fs = require("fs");
const path = require("path");

const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/).map(s => s.trim()).filter(Boolean);
if (!SERVERS.length) {
    console.error("❌ 未配置环境变量 YYB_SERVER");
    process.exit(1);
}

const APPID = "wxa5811e0426a94686";
const API_BASE = "https://member-api.icoke.cn";
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "kkkl_token_cache.json");
try { fs.mkdirSync(TOKEN_CACHE_DIR, { recursive: true }); } catch (e) {}

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823";

function readCache() {
    try { return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {}; } catch { return {}; }
}
function writeCache(c) {
    try { fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(c, null, 2), "utf8"); } catch (e) {}
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function mask(t) { t = String(t || ""); return t.length > 12 ? `${t.slice(0,6)}***${t.slice(-6)}` : t; }

function parseYyb(raw) {
    raw = (raw || "").trim();
    if (!raw || !raw.includes("@")) return { server: "", ref: "" };
    let [server, ref] = raw.split("@", 2);
    server = server.trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
    return { server, ref: ref.trim() };
}

async function getCode(server) {
    const { server: s, ref } = parseYyb(server);
    if (!s || !ref) return null;
    try {
        const { data } = await axios.post(`http://${s}/wxapp/getCode`, { ref, app_id: APPID }, { timeout: 20000, proxy: false });
        const code = data?.data?.result?.code;
        if (data?.code === 0 && code) { console.log(`✅ [取码] 获取code成功`); return code; }
        console.log(`❌ [取码] 获取code失败`);
        return null;
    } catch (e) { console.log(`❌ [取码] 异常: ${e.message}`); return null; }
}

function authHeaders(token) {
    return {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "xweb_xhr": "1",
        "authorization": token,
        "content-type": "application/json",
        "Referer": `https://servicewechat.com/${APPID}/421/page-frame.html`,
    };
}

// ====================== 输出美化 ======================
function logTitle() {
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🥤 可口可乐 自动签到                          ║");
    console.log(`║  🕒 启动时间: ${new Date().toLocaleString("zh-CN", { hour12: false }).padEnd(22)}║`);
    console.log(`║  🔢 账号数量: ${String(SERVERS.length).padEnd(22)}║`);
    console.log("╚" + "═".repeat(48) + "╝");
}
function logAccount(idx, total, server) {
    const { ref } = parseYyb(server);
    console.log();
    console.log("┌" + "─".repeat(48) + "┐");
    console.log(`│  🧩 账号 ${idx} / ${total}${" ".repeat(26)}│`);
    console.log(`│  🔑 标识: ${String(ref || "-").padEnd(41)}│`);
    console.log("└" + "─".repeat(48) + "┘");
}
function logEnd(ok, fail) {
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🏁 可口可乐任务完成                          ║");
    console.log(`║  ✅ 成功: ${String(ok).padEnd(22)}║`);
    console.log(`║  ❌ 失败: ${String(fail).padEnd(22)}║`);
    console.log(`║  🕒 结束时间: ${new Date().toLocaleString("zh-CN", { hour12: false }).padEnd(22)}║`);
    console.log("╚" + "═".repeat(48) + "╝");
}

class Cola {
    constructor(server, idx) {
        this.server = server;
        this.index = idx;
        this.token = "";
    }

    async api(path, auth = true) {
        const headers = authHeaders(this.token);
        if (!auth) delete headers.authorization;
        const res = await axios.get(`${API_BASE}${path}`, { headers, timeout: 20000, proxy: false, validateStatus: () => true });
        return res.data;
    }

    async login() {
        const code = await getCode(this.server);
        if (!code) return false;
        try {
            const data = await this.api(`/api/sp-portal/store/icoke/wechat/loginNoCache/${code}`, false);
            if (data?.jwtString) {
                this.token = data.jwtString;
                // 解析jwt过期时间
                try {
                    const payload = JSON.parse(Buffer.from(this.token.split(".")[1], "base64").toString());
                    if (payload.exp) {
                        const expDate = new Date(payload.exp * 1000);
                        const hours = ((payload.exp - Date.now()/1000) / 3600).toFixed(1);
                        console.log(`⏰ [登录] token有效期: ${expDate.toLocaleString("zh-CN")}（剩余${hours}小时）`);
                    }
                } catch {}
                const c = readCache();
                c[this.server] = { token: this.token };
                writeCache(c);
                console.log(`✅ [登录] 登录成功: ${mask(this.token)}`);
                return true;
            }
            console.log(`❌ [登录] 登录失败: ${data?.message || JSON.stringify(data).slice(0,100)}`);
            return false;
        } catch (e) {
            console.log(`❌ [登录] 异常: ${e.message}`);
            return false;
        }
    }

    async getPoints() {
        try {
            const data = await this.api("/api/icoke-customer/icoke/mini/customer/main/points");
            if (data?.point === undefined && data?.message) {
                // 积分接口也返回授权错误
                if (/authorization|未登录|401|token/i.test(String(data.message))) {
                    const err = new Error(data.message);
                    err.tokenInvalid = true;
                    throw err;
                }
            }
            return data?.point ?? "?";
        } catch (e) {
            if (e.tokenInvalid) throw e;
            return "?";
        }
    }

    async signIn() {
        try {
            const data = await this.api("/api/icoke-sign/icoke/mini/sign/main/sign");
            if (data?.success === true) {
                console.log(`✅ [签到] 签到成功: +${data.point ?? "?"}快乐瓶`);
                return true;
            }
            const msg = data?.message || data?.msg || JSON.stringify(data);
            if (/已签|重复|今天/.test(msg)) {
                console.log(`ℹ️ [签到] ${msg}`);
                return true;
            }
            // token失效判断（中英文都匹配）
            if (/401|未登录|token|过期|授权|authorization|need auth/i.test(msg)) {
                const err = new Error(msg);
                err.tokenInvalid = true;
                throw err;
            }
            console.log(`❌ [签到] 签到失败: ${msg}`);
            return false;
        } catch (e) {
            if (e.tokenInvalid) throw e;
            console.log(`❌ [签到] 异常: ${e.message}`);
            return false;
        }
    }

    async run() {
        const cache = readCache();
        const cached = cache[this.server] || {};
        if (cached.token) {
            this.token = cached.token;
            console.log(`💾 [缓存] 使用缓存token: ${mask(this.token)}`);
        }

        for (let attempt = 0; attempt < 2; attempt++) {
            try {
                if (attempt === 1) {
                    console.log(`🔄 [重登] token失效，清除缓存重新登录...`);
                    const c = readCache();
                    delete c[this.server];
                    writeCache(c);
                    if (!await this.login()) return false;
                }
                if (!this.token) {
                    if (!await this.login()) return false;
                }

                const before = await this.getPoints();
                console.log(`💰 [积分] 签到前: ${before}快乐瓶`);
                await sleep(2000);
                await this.signIn();
                await sleep(2000);
                const after = await this.getPoints();
                console.log(`💰 [积分] 签到后: ${after}快乐瓶`);
                return true;
            } catch (e) {
                if (e.tokenInvalid && attempt === 0) {
                    console.log(`🔄 [重登] token失效(${e.message})，准备重登...`);
                    continue;
                }
                console.log(`❌ [执行] ${e.message}`);
                return false;
            }
        }
        return false;
    }
}

(async () => {
    logTitle();
    let ok = 0, fail = 0;
    for (let i = 0; i < SERVERS.length; i++) {
        logAccount(i + 1, SERVERS.length, SERVERS[i]);
        if (await new Cola(SERVERS[i], i + 1).run()) ok++; else fail++;
        await sleep(1500);
    }
    logEnd(ok, fail);
})().catch(e => console.log(`❌ 脚本异常: ${e.message}`));
