// name: 飞鹤星妈会
// cron: 8 15,3 * * *
const axios = require("axios");
const fs = require("fs");
const path = require("path");

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
    } catch (e) { console.log(`⚠️ [缓存] 写入失败: ${e.message}`); }
}
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
        const { data } = await axios.post(url, { ref, app_id: 'wxc83b55d61c7fc51d' }, { timeout: 20000, proxy: false });
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

async function getWxCode(server) {
        return await getCode(server);
    }

// ==================== 输出美化 ====================
function logTitle() {
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🍼 飞鹤星妈会 自动签到                      ║");
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

class FeiheMom {
    constructor(openid) {
        this.server = openid;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.openid = openid;
        this.base = "https://momclub.feihe.com/capis";
        this.token = "";
        this.index = userIdx++;
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
        const ok = res.status === 200 && ["00000", "000000", "A00002"].includes(String(res.data?.code));
        if (!ok && !allowFail) throw new Error(`HTTP ${res.status}: ${short(res.data)}`);
        return res.data;
    }

    async login() {
        // 尝试缓存（不过期）
        const cache = readTokenCache();
        const cached = cache[this.server] || {};
        if (cached.accessToken) {
            this.token = cached.accessToken;
            console.log(`💾 [缓存] 账号[${this.index}] 使用缓存token: ${this.token.slice(0, 8)}***`);
            return true;
        }

        console.log(`🔐 [登录] 账号[${this.index}] 使用 code 换取 token...`);
        const code = await getWxCode(this.server);
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
        c[this.server] = { accessToken: token };
        writeTokenCache(c);

        console.log(`✅ [登录] 账号[${this.index}] 登录成功: ${token.slice(0, 8)}***`);
        return true;
    }

    async query() {
        const member = await this.api({ path: "/c/user/memberInfo", allowFail: true });
        const user = await this.api({ path: "/p/user/userInfo", allowFail: true });
        const data = member?.data || user?.data || {};
        const score = data.score || data.points || data.integral || data.availableScore || data.totalScore;
        const name = data.nickName || data.nickname || data.memberName || data.mobile || data.phone || "";
        console.log(`👤 [用户] 账号[${this.index}] 用户: ${name || "未知"}，积分: ${score ?? "未知"}`);
    }

    async sign() {
        const todo = await this.api({
            path: "/c/activity/todo/list",
            data: { mockTime: Date.now() },
            allowFail: true,
        });
        const checkTodo =
            getByPath(todo, "data.checkInTodo") ||
            findFirst(todo?.data, (item) => item && (item.checkInExtra || /签到|打卡|check/i.test(`${item.taskName || item.name || item.title || ""}`)));
        const activityId = checkTodo?.id || checkTodo?.activityId || checkTodo?.taskId;
        if (!activityId) {
            console.log(`⚠️ [签到] 账号[${this.index}] 未找到签到任务: ${short(todo)}`);
            return;
        }
        const todaySigned =
            checkTodo?.todaySigned ||
            checkTodo?.signed ||
            checkTodo?.finish ||
            checkTodo?.completed ||
            checkTodo?.status === 1 ||
            checkTodo?.state === 1;
        if (todaySigned) {
            console.log(`✅ [签到] 账号[${this.index}] 今日已签到`);
            return;
        }
        const sign = await this.api({
            method: "POST",
            path: "/c/activity/todo/checkIn",
            data: { activityId, mockTime: Date.now() },
            allowFail: true,
        });
        console.log(`✅ [签到] 账号[${this.index}] 签到完成: ${short(sign)}`);
    }
}

async function runAccount(openid, index, total) {
    logAccountHeader(index, total, openid);
    let usedCache = !!(readTokenCache()[openid] || {}).accessToken;
    for (let attempt = 0; attempt < 2; attempt++) {
        const runner = new FeiheMom(openid);
        try {
            await runner.login();
            await runner.query();
            await runner.sign();
            return true;
        } catch (e) {
            if (attempt === 0 && usedCache) {
                console.log(`🔄 [重登] 账号[${runner.index}] 缓存token失效，清除缓存重新登录...`);
                const c = readTokenCache();
                delete c[openid];
                writeTokenCache(c);
                continue;
            }
            console.log(`❌ [执行] 账号[${runner.index}] 执行失败：${e.message || e}`);
            return false;
        }
    }
    return false;
}

(async () => {
    logTitle();
    let successCount = 0;
    let failCount = 0;
    for (let i = 0; i < SERVERS.length; i++) {
        const ok = await runAccount(SERVERS[i], i + 1, SERVERS.length);
        if (ok) successCount++; else failCount++;
        await sleep(800);
    }
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🏁 飞鹤星妈会任务执行完成                    ║");
    console.log(`║  ✅ 成功: ${String(successCount).padEnd(22)}║`);
    console.log(`║  ❌ 失败: ${String(failCount).padEnd(22)}║`);
    console.log(`║  🕒 结束时间: ${new Date().toLocaleString("zh-CN", { hour12: false }).padEnd(22)}║`);
    console.log("╚" + "═".repeat(48) + "╝");
})().catch((e) => {
    console.log(`❌ 脚本异常：${e.stack || e.message || e}`);
});
