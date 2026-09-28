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
    const value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "" };
    const atIndex = value.indexOf("@");
    if (atIndex === -1) {
        console.log("❌ YYB_SERVER 格式应为 地址@微信账号标识，当前值: " + value);
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

const MINI_APP_ID = "wx10bc773e0851aedd";
const API_BASE = "https://jjw.jingjiu.com/app-jingyoujia";
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

function pad(text, width) {
    text = String(text);
    let w = 0;
    for (const ch of text) w += ch.charCodeAt(0) > 127 ? 2 : 1;
    return text + " ".repeat(Math.max(0, width - w));
}

function logTitle() {
    console.log();
    console.log("╔" + "=".repeat(50) + "╗");
    console.log("║  " + pad("💼 劲友家 每日任务", 46) + "║");
    console.log("║  " + pad(`🕒 启动时间: ${nowText()}`, 46) + "║");
    console.log("║  " + pad(`🔢 账号数量: ${SERVERS.length}`, 46) + "║");
    console.log("╚" + "=".repeat(50) + "╝");
}

function logAccountHeader(index, total, account) {
    console.log();
    console.log("┌" + "-".repeat(50) + "┐");
    console.log("│  " + pad(`🧩 账号 ${index} / ${total}`, 46) + "│");
    const { server, ref } = parseYybGoEntry(account);
    console.log("│  " + pad(`🔑 标识: ${ref || server}`, 46) + "│");
    console.log("└" + "-".repeat(50) + "┘");
}

function logFooter(successCount, failCount) {
    console.log();
    console.log("╔" + "=".repeat(50) + "╗");
    console.log("║  " + pad("🏁 劲友家任务执行完成", 46) + "║");
    console.log("║  " + pad(`✅ 成功: ${successCount}`, 46) + "║");
    console.log("║  " + pad(`❌ 失败: ${failCount}`, 46) + "║");
    console.log("║  " + pad(`🕒 结束时间: ${nowText()}`, 46) + "║");
    console.log("╚" + "=".repeat(50) + "╝");
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
    }

    async run() {
        try {
            const cached = this.getCachedToken();
            if (cached) {
                this.applyToken(cached);
                console.log(`💾 [缓存] 账号[${this.index}] 使用缓存token`);
                if (!(await this.checkToken())) {
                    this.removeCachedToken();
                    console.log(`🔄 [重登] 账号[${this.index}] 缓存token失效，重新登录`);
                }
            }

            if (!this.token) {
                await this.loginByWxCode();
                if (!this.token) return;
            }

            await this.getCustomerDetails();
            await this.getIntegral();
            await this.findCheckTask();
            await this.queryRecord();
            await this.signIn();
            await this.getIntegral();
            this.success = true;
        } catch (e) {
            console.log(`❌ [异常] 账号[${this.index}] ${e.message || e}`);
        }
    }

    getCachedToken() {
        const cache = readTokenCache();
        const item = cache[this.account];
        return item && item.accessToken ? item : null;
    }

    saveCachedToken() {
        if (!this.token) return;
        const cache = readTokenCache();
        cache[this.account] = {
            accessToken: this.token,
            userInfo: this.userInfo || {},
            updatedAt: new Date().toISOString(),
        };
        writeTokenCache(cache);
    }

    removeCachedToken() {
        const cache = readTokenCache();
        if (cache[this.account]) {
            delete cache[this.account];
            writeTokenCache(cache);
        }
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
            console.log(`👤 [用户] 账号[${this.index}] 会员: ${data?.nickName || data?.nickname || "未知"} ${maskPhone(data?.mobile || "")}`);
        } catch (e) {
            console.log(`❌ [用户] 账号[${this.index}] 查询会员失败: ${e.message || e}`);
            if (isTokenError(e.message || e)) this.removeCachedToken();
        }
    }

    async getIntegral() {
        try {
            const data = await this.request({ apiPath: "/app/jingyoujia/customer/queryCustIntegral" });
            this.points = data?.usableIntegral ?? data?.integral ?? data?.custIntegral ?? data?.points ?? "";
            console.log(`💰 [积分] 账号[${this.index}] 当前积分: ${this.points === "" ? JSON.stringify(data) : this.points}`);
        } catch (e) {
            console.log(`❌ [积分] 账号[${this.index}] 查询积分失败: ${e.message || e}`);
        }
    }

    async findCheckTask() {
        try {
            const data = await this.request({ apiPath: "/app/jingyoujia/taskContinuousRecord/findCheckTask" });
            if (!data || !data.id) {
                console.log(`ℹ️ [签到] 账号[${this.index}] 当前无签到活动`);
                return;
            }
            this.task = data;
            const start = String(data.startTime || "").slice(0, 10);
            const end = String(data.endTime || "").slice(0, 10);
            console.log(`📅 [签到] 账号[${this.index}] 签到活动: taskId=${data.id}${start || end ? ` ${start}-${end}` : ""}`);
        } catch (e) {
            console.log(`❌ [签到] 账号[${this.index}] 获取签到活动失败: ${e.message || e}`);
        }
    }

    async queryRecord() {
        if (!this.task?.id) return;
        try {
            const data = await this.request({
                apiPath: "/app/jingyoujia/taskContinuousRecord/queryRecord",
                params: { taskId: this.task.id },
            });
            this.record = data || {};
            console.log(`📅 [签到] 账号[${this.index}] 签到状态: 连续${data?.continuousNum ?? 0}天 今日=${data?.todayFinish ? "已签" : "未签"}`);
        } catch (e) {
            console.log(`❌ [签到] 账号[${this.index}] 查询签到状态失败: ${e.message || e}`);
        }
    }

    async signIn() {
        if (!this.task?.id) return;
        if (this.record?.todayFinish) {
            console.log(`✅ [签到] 账号[${this.index}] 今日已签到`);
            return;
        }
        try {
            const data = await this.request({
                method: "POST",
                apiPath: "/app/jingyoujia/taskContinuousRecord",
                data: {
                    v1: aesEncrypt(JSON.stringify({ taskId: this.task.id })),
                },
            });
            const integral = data?.currentSignIntegral ?? data?.integral ?? "";
            console.log(`✅ [签到] 账号[${this.index}] 签到成功${integral !== "" ? `: +${integral}积分` : ""}`);
            await this.finishTask();
        } catch (e) {
            const message = String(e.message || e);
            if (/已签到|重复|todayFinish/.test(message)) {
                console.log(`✅ [签到] 账号[${this.index}] 今日已签到`);
                return;
            }
            if (/20230529|captcha|验证码|滑块/.test(message)) {
                console.log(`⚠️ [签到] 账号[${this.index}] 签到需要验证码，已跳过`);
                return;
            }
            console.log(`❌ [签到] 账号[${this.index}] 签到失败: ${message}`);
            if (isTokenError(message)) this.removeCachedToken();
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

!(async () => {
    logTitle();
    const results = [];
    for (const account of SERVERS) {
        logAccountHeader(results.length + 1, SERVERS.length, account);
        const task = new Task(account);
        await task.run();
        results.push(task);
    }
    const successCount = results.filter(r => r.success).length;
    const failCount = results.length - successCount;
    logFooter(successCount, failCount);
})()
    .catch((e) => console.log("❌ " + (e.message || e)));
