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
        const body = res.data || {};
        const code = String(body.code || "");
        const msg = String(body.msg || body.message || "");

        // 检测token失效
        if (code === "A00004" || /unauthorized|未登录|登录已过期|token/i.test(msg)) {
            const err = new Error(`token失效: ${msg || code}`);
            err.tokenInvalid = true;
            throw err;
        }

        const ok = res.status === 200 && ["00000", "000000", "A00002"].includes(code);
        if (!ok && !allowFail) throw new Error(`HTTP ${res.status}: ${short(body)}`);
        return body;
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
        this.memberId = data.memberId || data.member_id || data.crmId || data.id || "";
        this.gameOpenId = this.memberId;
        this.nickname = data.nickname || data.nickName || data.mobile || "";
        const score = data.score || data.points || data.integral || data.availableScore || data.totalScore;
        console.log(`👤 [用户] 账号[${this.index}] 用户: ${this.nickname || "未知"}，积分: ${score ?? "未知"}，memberId: ${this.memberId || "无"}`);
    }

    async receiveTask(activityId) {
        try {
            await this.api({
                method: "POST",
                path: "/c/activity/todo/receive",
                data: { activityId, mockTime: Date.now() },
                allowFail: true,
            });
        } catch {}
    }

    async completeTask(task) {
        const activityId = task.id;
        const taskName = task.name || "未知任务";
        await this.receiveTask(activityId);
        await sleep(1500);
        const result = await this.api({
            method: "POST",
            path: "/c/activity/todo/complete",
            data: { activityId, mockTime: Date.now() },
            allowFail: true,
        });
        const code = String(result?.code || "");
        if (["00000", "000000", "A00002"].includes(code)) {
            const credits = result?.data?.credits || "";
            console.log(`  ✅ [任务] ${taskName}: 完成${credits ? ` (+${credits}积分)` : ""}`);
            return true;
        }
        console.log(`  ℹ️ [任务] ${taskName}: ${result?.msg || result?.message || "未完成"}`);
        return false;
    }

    async completeGameTask(task) {
        const taskName = task.name || "连连看";
        const activityId = task.id;
        if (!this.gameOpenId) {
            console.log(`  ⏭️ [任务] ${taskName}: 无openid，跳过游戏`);
            return false;
        }
        try {
            // 游戏登录
            const gameNickname = encodeURIComponent(this.nickname || "");
            const loginRes = await axios.post(
                `https://momclub.feihe.com/pmall/v1/api/auth/login?openid=${this.gameOpenId}&nickname=${gameNickname}`,
                null,
                {
                    headers: {
                        "User-Agent": USER_AGENT,
                        authorization: "",
                        "content-length": "0",
                        origin: "https://momclub.feihe.com",
                        referer: `https://momclub.feihe.com/h5/game/?wxNickName=${gameNickname}&crmId=${this.memberId}&memberid=${this.gameOpenId}&programLogin=1`,
                    },
                    timeout: 15000,
                    validateStatus: () => true,
                    transformRequest: () => "",
                }
            );
            const loginData = loginRes.data;
            if (String(loginData?.code) !== "10000") {
                console.log(`  ⚠️ [任务] ${taskName}: 游戏登录失败 ${JSON.stringify(loginData).slice(0, 150)}`);
                return false;
            }
            const gameToken = loginData.data.accessToken;
            const gameHeaders = {
                "User-Agent": USER_AGENT,
                authorization: gameToken,
                "content-type": "application/json",
                referer: `https://momclub.feihe.com/h5/game/?wxNickName=${gameNickname}&crmId=${this.memberId}&memberid=${this.gameOpenId}&programLogin=1`,
            };

            await this.receiveTask(activityId);
            await sleep(1000);

            // 玩3关
            for (let level = 1; level <= 3; level++) {
                await axios.post(`https://momclub.feihe.com/pmall/v1/api/game/level/startLevel?level=${level}`, null, {
                    headers: gameHeaders, timeout: 15000, validateStatus: () => true, transformRequest: () => "",
                });
                await sleep(4000);
                await axios.post(`https://momclub.feihe.com/pmall/v1/api/game/level/complete?levelId=${level}`, null, {
                    headers: gameHeaders, timeout: 15000, validateStatus: () => true, transformRequest: () => "",
                });
                console.log(`  🎮 [任务] ${taskName}: 第${level}关完成`);
                await sleep(2000);
            }

            // 完成任务
            const result = await this.api({
                method: "POST",
                path: "/c/activity/todo/complete",
                data: { activityId, mockTime: Date.now() },
                allowFail: true,
            });
            const code = String(result?.code || "");
            if (["00000", "000000", "A00002"].includes(code)) {
                const credits = result?.data?.credits || "";
                console.log(`  ✅ [任务] ${taskName}: 游戏完成${credits ? ` (+${credits}积分)` : ""}`);
                return true;
            }
            return false;
        } catch (e) {
            console.log(`  ❌ [任务] ${taskName}: 游戏异常 ${e.message}`);
            return false;
        }
    }

    async sign() {
        const todo = await this.api({
            path: "/c/activity/todo/list",
            data: { mockTime: Date.now() },
            allowFail: true,
        });
        const todoData = todo?.data || {};

        // ===== 签到 =====
        const checkTodo = todoData.checkInTodo;
        if (checkTodo?.id) {
            const joinRecord = checkTodo.checkInExtra?.joinRecord || [];
            const todayRecord = joinRecord.find((r) => r.today);
            if (todayRecord?.joined) {
                console.log(`✅ [签到] 账号[${this.index}] 今日已签到 (+${todayRecord.credits || 0}积分)`);
            } else {
                const sign = await this.api({
                    method: "POST",
                    path: "/c/activity/todo/checkIn",
                    data: { activityId: checkTodo.id, mockTime: Date.now() },
                    allowFail: true,
                });
                const code = String(sign?.code || "");
                if (["00000", "000000", "A00002"].includes(code)) {
                    const credits = sign?.data?.credits || "";
                    console.log(`✅ [签到] 账号[${this.index}] 签到成功${credits ? ` (+${credits}积分)` : ""}`);
                } else {
                    console.log(`⚠️ [签到] 账号[${this.index}] ${sign?.msg || sign?.message || "已签到"}`);
                }
            }
        } else {
            console.log(`ℹ️ [签到] 账号[${this.index}] 无签到活动`);
        }

        // ===== 其他任务 =====
        const taskList = todoData.taskTodo || [];
        if (taskList.length) {
            const skipTypes = new Set(["Perfect", "AddQw", "FirstOrder"]);
            const gameKeywords = ["游戏", "连连看", "玩一"];
            console.log(`📋 [任务] 账号[${this.index}] 共 ${taskList.length} 个任务`);

            for (const task of taskList) {
                const extra = task.taskTodoExtra || {};
                const taskType = extra.type || "";
                const taskName = task.name || "未知";
                const status = String(extra.status || "");
                const completeCount = extra.completeCount || 0;
                const completeLimit = extra.completeLimit || 1;

                if (skipTypes.has(taskType)) {
                    console.log(`  ⏭️ [任务] ${taskName}: 需手动完成，跳过`);
                    continue;
                }
                if (status === "3" || completeCount >= completeLimit) {
                    console.log(`  ✅ [任务] ${taskName}: 已完成`);
                    continue;
                }

                const isGame = gameKeywords.some((kw) => taskName.includes(kw));
                if (isGame) {
                    await this.completeGameTask(task);
                } else {
                    await this.completeTask(task);
                }
                await sleep(3000);
            }
        }
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
            if (e.tokenInvalid && attempt === 0 && usedCache) {
                console.log(`🔄 [重登] 账号[${runner.index}] token失效(${e.message})，清除缓存重新登录...`);
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
