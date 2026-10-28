// name: 康师傅畅饮社
// cron: 24 12,0 * * *
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
function parseYybGoEntry(rawValue) {
    const value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "" };
    const atIndex = value.indexOf("@");
    if (atIndex === -1) return { server: "", ref: "" };
    let server = value.slice(0, atIndex).trim();
    const ref = value.slice(atIndex + 1).trim();
    if (server.startsWith("http://")) server = server.slice(7);
    else if (server.startsWith("https://")) server = server.slice(8);
    server = server.replace(/\/+$/, "");
    return { server, ref };
}
async function getCode(server) {
    const { server: parsedServer, ref } = parseYybGoEntry(server);
    if (!parsedServer || !ref) return null;
    const url = "http://" + parsedServer + "/wxapp/getCode";
    try {
        const { data } = await axios.post(url, { ref, app_id: MINI_APP_ID }, { timeout: 20000, proxy: false });
        const code = data?.data?.result?.code;
        if (!data || data.code !== 0 || !code) {
            console.log(`❌ [取码] 获取code失败: ${JSON.stringify(data)}`);
            return null;
        }
        console.log(`✅ [取码] 获取code成功`);
        return code;
    } catch (e) {
        console.log(`❌ [取码] 获取code异常: ${e.message}`);
        return null;
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const MINI_APP_ID = "wx54f3e6a00f7973a7";
const API_BASE = "https://club.biqr.cn/";
const FORUM_BASE = "https://nclub.gdshcm.com/pro/";
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "kangshifu_token_cache.json");
try { fs.mkdirSync(TOKEN_CACHE_DIR, { recursive: true }); } catch (e) {}

const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254173b) XWEB/19027";

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch (e) { return {}; }
}
function writeTokenCache(cache) {
    try { fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8"); } catch (e) {}
}
function shortToken(token = "") {
    const v = String(token);
    return v ? `${v.slice(0, 6)}***` : "";
}
function maskPhone(phone = "") {
    return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2");
}
function formBody(data = {}) {
    return new URLSearchParams(data).toString();
}

// ====================== 输出美化 ======================
function logTitle() {
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🥤 康师傅畅饮社 自动签到                    ║");
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
    console.log("║  🏁 康师傅畅饮社任务完成                      ║");
    console.log(`║  ✅ 成功: ${String(successCount).padEnd(22)}║`);
    console.log(`║  ❌ 失败: ${String(failCount).padEnd(22)}║`);
    console.log(`║  🕒 结束时间: ${new Date().toLocaleString("zh-CN", { hour12: false }).padEnd(22)}║`);
    console.log("╚" + "═".repeat(48) + "╝");
}

class Task {
    constructor(openid, index) {
        this.server = openid;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = openid;
        this.index = index;
        this.token = "";
        this.member = {};
    }

    getCachedToken() {
        return readTokenCache()[this.openid] || null;
    }
    saveCachedToken() {
        if (!this.token) return;
        const cache = readTokenCache();
        cache[this.openid] = { token: this.token, member: this.member };
        writeTokenCache(cache);
    }
    removeCachedToken() {
        const cache = readTokenCache();
        if (cache[this.openid]) { delete cache[this.openid]; writeTokenCache(cache); }
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
            headers: this.headers(form ? { "Content-Type": "application/x-www-form-urlencoded;" } : {}),
            timeout: 15000,
            validateStatus: () => true,
        };
        if (!auth) delete options.headers.token;
        if (data !== undefined) options.data = form ? formBody(data) : data;

        const { data: result, status } = await axios.request(options);
        if (status !== 200) throw new Error(`HTTP ${status}`);
        if (Number(result?.code) !== 0) {
            const err = new Error(`${result?.msg || result?.error || JSON.stringify(result)}`);
            // 精确判断token失效
            if (/token.*(无效|过期|失效|非法)|未登录|登录已过期|请先登录|身份验证失败/i.test(err.message)) {
                err.tokenInvalid = true;
            }
            throw err;
        }
        return result;
    }

    async loginByWxCode() {
        try {
            const code = await getCode(this.server);
            if (!code) return false;
            const result = await this.request(FORUM_BASE, "whale-member/api/login/login", {
                method: "POST", auth: false,
                data: { code, inviterId: "", inviterType: "", inviterMatchUserId: "", spUrl: "" },
            });
            const token = result?.data?.token || "";
            if (!token) return false;
            this.token = token;
            this.member = result?.data?.member || {};
            this.saveCachedToken();
            const name = this.member.nickname || maskPhone(this.member.phone) || this.member.id || "";
            console.log(`✅ [登录] 账号[${this.index}] 登录成功: ${name}`);
            return true;
        } catch (e) {
            console.log(`❌ [登录] 账号[${this.index}] 登录失败: ${e.message}`);
            return false;
        }
    }

    async getMemberInfo() {
        const result = await this.request(FORUM_BASE, "whale-member/api/member/getMemberInfo", {
            params: { token: this.token },
        });
        this.member = result?.data || this.member;
        return this.member;
    }

    async memberInfo(prefix = "当前") {
        try {
            const data = await this.getMemberInfo();
            const name = data?.nickname || maskPhone(data?.phone) || data?.id || "";
            const integral = data?.integral ?? data?.point ?? data?.points ?? data?.score ?? "未知";
            console.log(`👤 [用户] 账号[${this.index}] ${prefix}用户: ${name}，积分: ${integral}`);
        } catch (e) {
            if (e.tokenInvalid) throw e;
            console.log(`⚠️ [用户] 账号[${this.index}] 查询用户信息失败: ${e.message}`);
        }
    }

    async signIn() {
        try {
            // 先查签到状态
            const statusRes = await this.request(API_BASE, "api/signIn/integralSignInList", {
                method: "POST", data: { token: this.token }, form: true,
            });
            const status = statusRes?.data || {};
            if (status?.signIs) {
                console.log(`ℹ️ [签到] 账号[${this.index}] 今日已签到`);
                return true;
            }

            // 执行签到
            const result = await this.request(API_BASE, "api/signIn/integralSignIn", {
                method: "POST", data: { token: this.token }, form: true,
            });
            console.log(`✅ [签到] 账号[${this.index}] 签到成功: ${result?.msg || "成功"}`);
            return true;
        } catch (e) {
            if (/已签到|已签|重复签到/.test(e.message)) {
                console.log(`ℹ️ [签到] 账号[${this.index}] 今日已签到`);
                return true;
            }
            if (e.tokenInvalid) throw e;
            console.log(`❌ [签到] 账号[${this.index}] 签到失败: ${e.message}`);
            return false;
        }
    }

    async watchVideo() {
        // 看视频赚积分：遍历所有分类 → 跳过已看过的 → 把新视频都看完
        const VIDEO_BASE = "https://club.ksf.cn/";
        const VIDEO_TYPES = [1, 2, 3, 4];
        const TYPE_NAMES = { 1: "品牌故事", 2: "热门赛事", 3: "快闪活动", 4: "活动宣传" };

        // 从缓存读取已看过的视频ID
        const cache = readTokenCache();
        const cacheKey = this.openid;
        const accountCache = cache[cacheKey] || {};
        const watchedVideos = accountCache.watchedVideos || [];

        let watchCount = 0;
        try {
            for (const type of VIDEO_TYPES) {
                // 获取该分类视频列表
                const listRes = await this.request(VIDEO_BASE, "api/shortVideo/getVideoList", {
                    params: { keyWord: "", pageNum: 1, pageSize: 20, type },
                });
                let videos = listRes?.rows || [];
                if (!videos.length) continue;

                // 跳过已看过的
                videos = videos.filter(v => !watchedVideos.includes(v.id));
                if (!videos.length) {
                    console.log(`ℹ️ [视频] 账号[${this.index}] ${TYPE_NAMES[type]}: 已全部看过`);
                    continue;
                }
                console.log(`🎬 [视频] 账号[${this.index}] ${TYPE_NAMES[type]}: 有${videos.length}个新视频`);

                for (const video of videos) {
                    const videoId = video.id;
                    const videoName = (video.name || "").slice(0, 20);
                    try {
                        await this.request(VIDEO_BASE, "api/shortVideo/click", {
                            method: "POST",
                            params: { type, videoId },
                            data: {}, form: true,
                        });
                        console.log(`⏳ [视频] 账号[${this.index}] 正在观看: ${videoName}...（30秒）`);
                        await sleep(30000);
                        await this.request(VIDEO_BASE, "api/shortVideo/addIntegral", {
                            method: "POST",
                            params: { videoId },
                            data: {}, form: true,
                        });
                        console.log(`✅ [视频] 账号[${this.index}] 观看完成: ${videoName}`);
                        watchCount++;
                        watchedVideos.push(videoId);
                    } catch (e) {
                        if (e.tokenInvalid) throw e;
                        console.log(`⚠️ [视频] 账号[${this.index}] 观看失败: ${videoName} - ${e.message}`);
                    }
                    await sleep(3000);
                }
            }

            // 保存已看过的视频ID到缓存
            const c = readTokenCache();
            if (!c[cacheKey]) c[cacheKey] = {};
            c[cacheKey].watchedVideos = watchedVideos;
            writeTokenCache(c);

            if (watchCount > 0) {
                console.log(`🏁 [视频] 账号[${this.index}] 本次完成${watchCount}个新视频，累计已看${watchedVideos.length}个`);
            } else {
                console.log(`ℹ️ [视频] 账号[${this.index}] 所有视频均已看过，累计${watchedVideos.length}个`);
            }
        } catch (e) {
            if (e.tokenInvalid) throw e;
            console.log(`⚠️ [视频] 账号[${this.index}] 视频任务异常: ${e.message}`);
        }
    }

    async run() {
        const cached = this.getCachedToken();
        if (cached?.token) {
            this.token = cached.token;
            this.member = cached.member || {};
            console.log(`💾 [缓存] 账号[${this.index}] 使用缓存token: ${shortToken(this.token)}`);
        }

        // 最多尝试2次：缓存token → 失败则清缓存重登
        for (let attempt = 0; attempt < 2; attempt++) {
            try {
                if (attempt === 1) {
                    console.log(`🔄 [重登] 账号[${this.index}] token失效，清除缓存重新登录...`);
                    this.removeCachedToken();
                    const ok = await this.loginByWxCode();
                    if (!ok) return false;
                }
                if (!this.token) {
                    const ok = await this.loginByWxCode();
                    if (!ok) return false;
                }

                await this.memberInfo("当前");
                await this.signIn();
                await this.watchVideo();
                await this.memberInfo("签到后");
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
        const ok = await new Task(SERVERS[i], i + 1).run();
        if (ok) successCount++; else failCount++;
        await sleep(800);
    }
    logEnd(successCount, failCount);
})().catch((e) => console.log(`❌ 脚本异常: ${e.message}`));
