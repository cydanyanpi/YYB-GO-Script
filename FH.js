// name: 飞鹤·北纬47°好物
// cron: 16 15,3 * * *
#小程序://飞鹤丨北纬47度好物/dIs1dmyVLMr2mqI
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

const MINI_APP_ID = "wx4205ec55b793245e";
const API_BASE = "https://www.feihevip.com";
const APP_ID = "xmyx";
const APP_KEY = "TwUQ01lKS1Km5zlV2f7amsZc5EQYkTbv";
const SIGN_TASK_TYPE = "DJSYQD";
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "fh_token_cache.json");
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";


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

function maskToken(token = "") {
    if (!token) return "";
    return token.length > 16 ? `${token.slice(0, 8)}***${token.slice(-8)}` : `${token.slice(0, 4)}***`;
}

function randomString(length) {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    let result = "";
    for (let i = 0; i < length; i++) {
        result += chars[Math.floor(Math.random() * chars.length)];
    }
    return result;
}

function md5Upper(text) {
    return crypto.createHash("md5").update(text).digest("hex").toUpperCase();
}

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
    // 签名: fhAppid{appid}fhNonceStr{nonce}fhTimestamp{ts}{body}{appKey}
    // body为空时和py一致，不为空时把body加进去
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

// ==================== 输出美化 ====================
function logTitle() {
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🥛 飞鹤·北纬47°好物 自动签到                ║");
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
    constructor(account) {
        this.server = account;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.index = userIdx++;
        this.account = String(account || "").trim();
        this.token = "";
        this.userInfo = {};
    }

    async run() {
        const usedCache = !!this.getCachedToken();
        if (usedCache) {
            const cached = this.getCachedToken();
            this.token = cached.token || "";
            this.userInfo = cached.userInfo || {};
            console.log(`💾 [缓存] 账号[${this.index}] 使用缓存token: ${maskToken(this.token)}`);
        }
        for (let attempt = 0; attempt < 2; attempt++) {
            if (attempt === 1 || !this.token) {
                if (attempt === 1) {
                    console.log(`🔄 [重登] 账号[${this.index}] token失效，重新登录...`);
                    this.removeCachedToken();
                    this.token = "";
                }
                await this.loginByCode();
                if (!this.token) return false;
            }
            try {
                await this.getIndexInfo();
                const pointsBefore = await this.getPoints();
                await this.signIn();
                await this.doAllTasks();
                const pointsAfter = await this.getPoints();
                if (pointsBefore !== null && pointsAfter !== null) {
                    const earned = pointsAfter - pointsBefore;
                    console.log(`📊 [汇总] 账号[${this.index}] 今日获取: ${earned >= 0 ? "+" : ""}${earned}积分（${pointsBefore} → ${pointsAfter}）`);
                }
                return true;
            } catch (e) {
                const msg = String(e.message || e);
                if (attempt === 0 && usedCache && /token|登录|授权|invalid|401|403/i.test(msg)) {
                    console.log(`🔄 [重登] 账号[${this.index}] 业务token失效，清除缓存重新登录...`);
                    this.removeCachedToken();
                    this.token = "";
                    continue;
                }
                console.log(`❌ [执行] 账号[${this.index}] 执行失败: ${msg}`);
                return false;
            }
        }
        return false;
    }

    getCachedToken() {
        const cache = readTokenCache();
        return cache[this.account] || null;
    }

    saveCachedToken() {
        if (!this.token) return;
        const cache = readTokenCache();
        cache[this.account] = {
            token: this.token,
            userInfo: this.userInfo,
        };
        writeTokenCache(cache);
    }

    removeCachedToken() {
        const cache = readTokenCache();
        if (cache[this.account]) {
            delete cache[this.account];
            writeTokenCache(cache);
        }
    }

    async request({ method = "GET", apiPath, query = {}, data = null, token = this.token, allowFail = false }) {
        const options = {
            method,
            url: buildUrl(apiPath, query),
            headers: buildSignedHeaders({ data: method === "GET" ? null : data, token }),
            timeout: 15000,
            validateStatus: () => true,
        };
        if (method !== "GET" && data) options.data = data;

        const { status, data: result } = await axios.request(options);
        const ok = status === 200 && String(result?.code) === "200";
        if (!ok && !allowFail) {
            throw new Error(`HTTP ${status} ${JSON.stringify(result)}`);
        }
        return result;
    }

    async getWxCode() {
        return await getCode(this.server);
    }

    async loginByCode() {
        console.log(`🔐 [登录] 账号[${this.index}] 使用 code 换取 token...`);
        const code = await this.getWxCode();
        const result = await this.request({
            apiPath: "/api/starMember/getUserToken",
            query: { code },
            token: "",
        });
        const data = result.data || {};
        this.token = result.token || data.token || "";
        this.userInfo = {
            crmId: data.crmId,
            openId: data.openId,
            unionId: data.unionId,
            loginStatus: data.loginStatus,
            expireTime: data.expireTime,
        };
        if (!this.token) throw new Error(`登录成功但未返回token: ${JSON.stringify(result)}`);
        this.saveCachedToken();
        console.log(`✅ [登录] 账号[${this.index}] 登录成功: crmId=${data.crmId || data.openId || ""} token=${maskToken(this.token)}`);
    }

    async checkToken() {
        try {
            const result = await this.request({
                method: "POST",
                apiPath: "/api/structures/index",
                data: { id: "" },
                allowFail: true,
            });
            return String(result?.code) === "200";
        } catch (e) {
            return false;
        }
    }

    async getIndexInfo() {
        const result = await this.request({
            method: "POST",
            apiPath: "/api/structures/index",
            data: { id: "" },
            allowFail: true,
        });
        if (String(result?.code) === "200") {
            const signModule = (result.data?.modules || []).find((item) => String(item.moduleType) === "17");
            console.log(`📋 [首页] 账号[${this.index}] 签到入口: ${signModule ? "已发现" : "未发现"}`);
        } else {
            console.log(`⚠️ [首页] 账号[${this.index}] 首页信息查询失败: ${result?.msg || JSON.stringify(result)}`);
        }
    }

    async getPoints() {
        try {
            const result = await this.request({
                apiPath: "/api/member/signin/getSignInfo",
                query: { signType: 1 },
                allowFail: true,
            });
            if (String(result?.code) === "200") {
                const member = result.data?.memberDetail || {};
                const points = Number(member.totalPoint) || 0;
                console.log(`💰 [积分] 账号[${this.index}] 当前总积分: ${points}`);
                return points;
            }
            return null;
        } catch (e) {
            return null;
        }
    }

    async doAllTasks() {
        // 获取任务列表
        const listResult = await this.request({
            apiPath: "/api/member/signin/getTaskList",
            allowFail: true,
        });
        if (String(listResult?.code) !== "200") {
            console.log(`ℹ️ [任务] 账号[${this.index}] 任务列表获取失败: ${listResult?.msg || JSON.stringify(listResult)}`);
            return;
        }
        const tasks = listResult.data || [];
        if (!tasks.length) {
            console.log(`ℹ️ [任务] 账号[${this.index}] 暂无任务`);
            return;
        }
        console.log(`📋 [任务] 账号[${this.index}] 共 ${tasks.length} 个任务`);

        for (const task of tasks) {
            const taskName = task.taskName || "未知任务";
            const taskType = task.taskType || "";
            const isCompleted = task.isCompleted === true;
            const totalCount = task.totalCount || 0;
            const completedCount = task.completedCount || 0;
            const duration = task.completeTaskDuration || 1;

            if (isCompleted) {
                console.log(`  ⏭️ [任务] ${taskName}: 已完成，跳过`);
                continue;
            }

            const remaining = Math.max(0, totalCount - completedCount);
            for (let i = 0; i < remaining; i++) {
                try {
                    // 开始任务
                    const start = await this.request({
                        apiPath: "/api/member/signin/tofinish",
                        query: { taskType },
                        allowFail: true,
                    });
                    if (start.msg) {
                        console.log(`  ℹ️ [任务] ${taskName}: ${start.msg}`);
                        break;
                    }

                    // 等待
                    console.log(`  ⏳ [任务] ${taskName}: 等待${duration}秒...`);
                    await sleep(duration * 1000);

                    // 完成任务
                    const finish = await this.request({
                        apiPath: "/api/member/signin/completeTask",
                        query: { taskType },
                        allowFail: true,
                    });
                    if (finish.msg) {
                        console.log(`  ✅ [任务] ${taskName}: ${finish.msg}`);
                    } else if (finish.data?.awardSendPoints) {
                        console.log(`  🎁 [任务] ${taskName}: +${finish.data.awardSendPoints}积分`);
                    } else {
                        console.log(`  ✅ [任务] ${taskName}: 完成`);
                    }
                } catch (e) {
                    console.log(`  ❌ [任务] ${taskName} 异常: ${e.message}`);
                    break;
                }
                await sleep(10000);
            }
        }
    }

    async signIn() {
        const sign = await this.request({
            method: "POST",
            apiPath: "/api/member/signin/sign",
            allowFail: true,
        });
        if (String(sign?.code) === "200") {
            const data = sign.data || {};
            const points = data.awardSendPoints || data.awardPoint || data.points || "";
            console.log(`✅ [签到] 账号[${this.index}] 签到成功${points ? ` (+${points}积分)` : ""}`);
        } else {
            const msg = sign?.msg || JSON.stringify(sign);
            if (/已签|重复|今天/.test(msg)) {
                console.log(`ℹ️ [签到] 账号[${this.index}] 今日已签到`);
            } else {
                console.log(`⚠️ [签到] 账号[${this.index}] ${msg}`);
            }
        }
    }
}

!(async () => {
    logTitle();
    if (!SERVERS.length) return;
    let successCount = 0;
    let failCount = 0;
    let currentIdx = 1;
    for (const account of SERVERS) {
        logAccountHeader(currentIdx, SERVERS.length, account);
        const task = new Task(account);
        try {
            const ok = await task.run();
            if (ok) successCount++; else failCount++;
        } catch (e) {
            console.log(`❌ [执行] 账号[${task.index}] 运行失败: ${e.message || e}`);
            failCount++;
        }
        currentIdx++;
    }
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🏁 飞鹤·北纬47°好物任务完成                ║");
    console.log(`║  ✅ 成功: ${String(successCount).padEnd(22)}║`);
    console.log(`║  ❌ 失败: ${String(failCount).padEnd(22)}║`);
    console.log(`║  🕒 结束时间: ${new Date().toLocaleString("zh-CN", { hour12: false }).padEnd(22)}║`);
    console.log("╚" + "═".repeat(48) + "╝");
})()
    .catch((e) => console.log(`❌ 运行异常: ${e.message || e}`));
