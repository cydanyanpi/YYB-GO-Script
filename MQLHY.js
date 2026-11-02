// name: 米其林会员
// cron: 0 11,23 * * *

const axios = require("axios");
const fs = require("fs");
const path = require("path");

const APP_ID = "wx14413dafd16b9540";
const BASE = "https://ulp.michelin.com.cn";

const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.error("❌ 未配置环境变量 YYB_SERVER，请设置后重试（格式：地址@微信账号标识，多行换行）");
    process.exit(1);
}

const SCRIPT_DIR = __dirname;
const CACHE_FILE = path.join(SCRIPT_DIR, "token_caches", "mqlhy_token_cache.json");

function readCache() {
    try {
        if (!fs.existsSync(CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(CACHE_FILE, "utf-8")) || {};
    } catch (e) { return {}; }
}
function writeCache(c) {
    try {
        fs.mkdirSync(path.dirname(CACHE_FILE), { recursive: true });
        fs.writeFileSync(CACHE_FILE, JSON.stringify(c, null, 2), "utf-8");
    } catch (e) {}
}
function nowText() {
    const d = new Date();
    const p = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function mask(v) {
    v = String(v || "");
    return v.length <= 16 ? v : v.slice(0, 8) + "..." + v.slice(-8);
}
function padStr(str, width) {
    str = String(str);
    let len = 0;
    for (const ch of str) len += ch.charCodeAt(0) > 255 ? 2 : 1;
    return str + " ".repeat(Math.max(0, width - len));
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
    if (!server || !ref) return { server: "", ref: "" };
    return { server, ref };
}
async function getCode(server) {
    const { server: parsedServer, ref } = parseYybGoEntry(server);
    if (!parsedServer || !ref) return null;
    try {
        const { data } = await axios.post("http://" + parsedServer + "/wxapp/getCode",
            { ref, app_id: APP_ID }, { timeout: 20000, proxy: false });
        const code = data && data.data && data.data.result && data.data.result.code;
        if (!data || data.code !== 0 || !code) return null;
        return code;
    } catch (e) { return null; }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const defaultUA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.31(0x18001e31) NetType/WIFI Language/zh_CN miniProgram";

let userIdx = 1;

function logTitle() {
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🚗 米其林会员 自动签到                        ║");
    console.log("║  🕒 启动时间: " + padStr(nowText(), 25) + "║");
    console.log("║  🔢 账号数量: " + padStr(String(SERVERS.length), 25) + "║");
    console.log("╚" + "═".repeat(48) + "╝");
}
function logAccount(i, total, server) {
    const { ref } = parseYybGoEntry(server);
    console.log();
    console.log("┌" + "─".repeat(48) + "┐");
    console.log("│  🧩 账号 " + padStr(`${i} / ${total}`, 40) + "│");
    console.log("│  🔑 标识: " + padStr(ref || "-", 39) + "│");
    console.log("└" + "─".repeat(48) + "┘");
}
function logEnd(ok, fail) {
    console.log();
    console.log("╔" + "═".repeat(48) + "╗");
    console.log("║  🏁 米其林任务完成                            ║");
    console.log("║  ✅ 成功: " + padStr(String(ok), 26) + "║");
    console.log("║  ❌ 失败: " + padStr(String(fail), 26) + "║");
    console.log("║  🕒 结束时间: " + padStr(nowText(), 24) + "║");
    console.log("╚" + "═".repeat(48) + "╝");
}

class Task {
    constructor(env) {
        this.server = env;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.index = userIdx++;
        this.token = null;
        this.fromCache = false;
        this.tokenInvalid = false;
        this.paperStatus = true;
        this.stdAnswers = [];
        this.questionList = [];
    }

    async run() {
        const cache = readCache();
        const cached = cache[this.ref] || {};
        if (cached.token) {
            this.token = cached.token;
            this.fromCache = true;
            console.log("💾 [缓存] 使用缓存token: " + mask(this.token));
        }

        for (let attempt = 0; attempt < 2; attempt++) {
            try {
                if (attempt === 1 || !this.token) {
                    if (attempt === 1) {
                        console.log("🔄 [重登] token失效，清除缓存重新登录...");
                        const c = readCache();
                        if (this.ref in c) { delete c[this.ref]; writeCache(c); }
                    }
                    if (!await this.login()) return false;
                }

                const ok = await this.biz();
                if (ok) {
                    const c = readCache();
                    c[this.ref] = { token: this.token };
                    writeCache(c);
                    return true;
                }
                if (this.tokenInvalid && attempt === 0 && this.fromCache) {
                    this.token = null;
                    continue;
                }
                return false;
            } catch (e) {
                console.log("❌ [执行] 异常: " + e.message);
                if (attempt === 0 && this.fromCache) { this.token = null; continue; }
                return false;
            }
        }
        return false;
    }

    async login() {
        await sleep(Math.floor(Math.random() * 20 + 5) * 1000);
        const code = await getCode(this.server);
        if (!code) {
            console.log("❌ [取码] 获取code失败");
            return false;
        }
        try {
            const { data: result } = await axios.request({
                method: "GET",
                url: `${BASE}/bff/wechat/login/${code}`,
                headers: { "User-Agent": defaultUA, "Referer": `https://servicewechat.com/${APP_ID}/130/page-frame.html` },
                timeout: 20000,
            });
            const accessToken = result?.data?.token?.access_token;
            if (!accessToken) {
                console.log("❌ [登录] 登录失败: " + JSON.stringify(result).slice(0, 150));
                return false;
            }
            this.token = accessToken;
            console.log("✅ [登录] 登录成功: " + mask(this.token));
            return true;
        } catch (e) {
            console.log("❌ [登录] 异常: " + e.message);
            return false;
        }
    }

    async biz() {
        // 查积分
        const points = await this.getUserInfo();
        if (points === null) return false;
        // 问卷答题
        await this.doPaper();
        // 分享10次
        let shareOk = 0;
        for (let i = 0; i < 10; i++) {
            if (await this.share()) shareOk++;
            await sleep(Math.floor(Math.random() * 2000) + 1000);
        }
        console.log("📤 [分享] 完成 " + shareOk + "/10 次转发");
        return true;
    }

    async getUserInfo() {
        try {
            const { data: result } = await axios.request({
                method: "GET",
                url: `${BASE}/bff/profile`,
                headers: { "User-Agent": defaultUA, "Authorization": "Bearer " + this.token },
                timeout: 20000,
            });
            if (result?.data?.points !== undefined && result?.data?.points !== null) {
                console.log("👤 [用户] 当前积分: " + result.data.points);
                return result.data.points;
            }
            if (String(result?.code) === "401" || String(result?.code) === "403") {
                this.tokenInvalid = true;
                return null;
            }
            console.log("⚠️ [用户] 积分查询异常: " + JSON.stringify(result).slice(0, 120));
            return null;
        } catch (e) {
            if (e.response && [401, 403].includes(e.response.status)) {
                this.tokenInvalid = true;
                return null;
            }
            console.log("❌ [用户] 积分查询失败: " + e.message);
            return null;
        }
    }

    async share() {
        try {
            const { data: result } = await axios.request({
                method: "POST",
                url: `${BASE}/op/points/share/have`,
                headers: {
                    "User-Agent": defaultUA,
                    "Authorization": "Bearer " + this.token,
                    "Content-Type": "application/json",
                },
                data: { "type": "ARTICLE", "code": "COM-MHT-93" },
                timeout: 20000,
            });
            if (String(result?.code) === "200") {
                console.log("  ✅ [转发] 转发成功");
                return true;
            }
            if (String(result?.code) === "401" || String(result?.code) === "403") this.tokenInvalid = true;
            console.log("  ℹ️ [转发] " + (result?.message || "转发失败"));
            return false;
        } catch (e) {
            if (e.response && [401, 403].includes(e.response.status)) {
                this.tokenInvalid = true;
                return false;
            }
            console.log("  ❌ [转发] 异常: " + e.message);
            return false;
        }
    }

    async doPaper() {
        await this.getPaper();
        if (!this.paperStatus) {
            console.log("ℹ️ [问卷] 本周奖励已领取，跳过答题");
            return;
        }
        await this.getOpenTpaper(this.npsPaperCode);
        if (!this.questionList.length) {
            console.log("⚠️ [问卷] 未获取到题目，跳过答题");
            return;
        }
        let index = 1;
        for (const question of this.questionList) {
            const stem = question?.questionChoise?.stemHtml || "未知题目";
            const options = question?.questionChoise?.options || [];
            const theQuestion = question.questionChoise.npsQuestionPk;
            const detail = this.stdAnswers.find(a => theQuestion == a.npsQuestionChoisePk) || {};
            let answer = options.find(o => o.npsQuestionChoiseOptionPk == detail.npsQuestionChoiseOptionPk);
            if (!answer) answer = options[0];
            if (!answer) {
                console.log("  ⏭️ [问卷] 第" + index + "题无选项，跳过");
                index++;
                continue;
            }
            const res = await this.answer(theQuestion, answer.npsQuestionChoiseOptionPk);
            console.log("  📝 [问卷] 第" + index + "题: " + res);
            index++;
        }
        await this.paperScore(this.paperCode);
    }

    async getPaper() {
        try {
            const { data: result } = await axios.request({
                method: "POST",
                url: `${BASE}/campaign/paper/user`,
                headers: {
                    "User-Agent": defaultUA,
                    "Authorization": "Bearer " + this.token,
                    "Content-Type": "application/json",
                },
                data: {},
                timeout: 20000,
            });
            if (String(result?.code) === "200") {
                const d = result?.data || {};
                console.log("📋 [问卷] 问卷" + d.npsPaperCode + "，共" + d.questionNum + "题，状态:" + d.status);
                this.paperStatus = d.status !== "DONE";
                this.npsPaperCode = d.npsPaperCode;
                this.paperCode = d.paperCode;
            } else if (String(result?.code) === "401" || String(result?.code) === "403") {
                this.tokenInvalid = true;
            } else {
                console.log("⚠️ [问卷] 获取问卷失败: " + (result?.message || JSON.stringify(result).slice(0, 100)));
            }
        } catch (e) {
            if (e.response && [401, 403].includes(e.response.status)) {
                this.tokenInvalid = true;
                return;
            }
            console.log("❌ [问卷] 获取问卷异常: " + e.message);
        }
    }

    async getOpenTpaper(npsPaperCode) {
        try {
            const { data: result } = await axios.request({
                method: "GET",
                url: `${BASE}/npspaper/nps-admin/open/api/cp/public/get_open_tpaper/${npsPaperCode}`,
                headers: { "User-Agent": "", "Authorization": "Bearer " + this.token },
                timeout: 20000,
            });
            if (result?.success) {
                const payload = result?.data || {};
                const tpaper = payload.tpaper || payload;
                this.stdAnswers = payload.stdAnswers || tpaper.stdAnswers || [];
                this.questionList = payload.questionList || tpaper.questionList || tpaper.questions || [];
                if (!this.questionList.length) {
                    console.log("🔍 [调试] getOpenTpaper返回: " + JSON.stringify(payload).slice(0, 600));
                }
            } else {
                console.log("❌ [问卷] 获取题目失败: " + (result?.message || JSON.stringify(result).slice(0, 100)));
            }
        } catch (e) {
            if (e.response && [401, 403].includes(e.response.status)) {
                this.tokenInvalid = true;
                return;
            }
            console.log("❌ [问卷] 获取题目异常: " + e.message);
        }
    }

    async answer(question, answer) {
        try {
            const { data: result } = await axios.request({
                method: "POST",
                url: `${BASE}/campaign/paper/user/answer`,
                headers: {
                    "User-Agent": defaultUA,
                    "Authorization": "Bearer " + this.token,
                    "Content-Type": "application/json",
                },
                data: { "answerOptionId": [`${answer}`], "paperCode": `${this.paperCode}`, "questionId": `${question}` },
                timeout: 20000,
            });
            return String(result?.code) === "200" ? "回答成功" : "回答失败: " + (result?.message || "");
        } catch (e) {
            if (e.response && [401, 403].includes(e.response.status)) {
                this.tokenInvalid = true;
                return "token失效";
            }
            return "回答异常: " + e.message;
        }
    }

    async paperScore(paperCode) {
        try {
            const { data: res } = await axios.request({
                method: "POST",
                url: `${BASE}/campaign/paper/score/${paperCode}`,
                headers: {
                    "User-Agent": defaultUA,
                    "Authorization": "Bearer " + this.token,
                    "Content-Type": "application/json",
                },
                data: {},
                timeout: 20000,
            });
            console.log("🏆 [问卷] 提交成功，正确率" + res?.data?.score + "%，排名" + res?.data?.rank);
        } catch (e) {
            if (e.response && [401, 403].includes(e.response.status)) {
                this.tokenInvalid = true;
                return;
            }
            console.log("❌ [问卷] 提交问卷失败: " + e.message);
        }
    }
}

!(async () => {
    logTitle();
    let ok = 0, fail = 0;
    for (let i = 0; i < SERVERS.length; i++) {
        logAccount(i + 1, SERVERS.length, SERVERS[i]);
        if (await new Task(SERVERS[i]).run()) ok++;
        else fail++;
        await sleep(2000);
    }
    logEnd(ok, fail);
})().catch(e => console.log("❌ " + e.message));
