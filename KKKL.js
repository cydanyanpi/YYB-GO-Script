// name: 可口可乐
// cron: 32 12,0 * * *
const axios = require("axios");
// 代理依赖按需加载：缺少某个包时不至于整个脚本起不来（无代理运行时用不到）
let SocksProxyAgent = null, HttpsProxyAgent = null, HttpProxyAgent = null;
try { SocksProxyAgent = require("socks-proxy-agent").SocksProxyAgent; } catch {}
try { HttpsProxyAgent = require("https-proxy-agent").HttpsProxyAgent; } catch {}
try { HttpProxyAgent = require("http-proxy-agent").HttpProxyAgent; } catch {}
const fs = require("fs");
const path = require("path");

// Token 缓存
const TOKEN_CACHE_DIR = path.join(__dirname, "token_caches");
const TOKEN_CACHE_FILE = path.join(TOKEN_CACHE_DIR, "kkkl_token_cache.json");

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
    } catch (e) { console.log("⚠️ 缓存写入失败:", e.message); }
}

delete process.env.HTTP_PROXY;
delete process.env.HTTPS_PROXY;
delete process.env.http_proxy;
delete process.env.https_proxy;

const APPID = "wxa5811e0426a94686";

// 从环境变量 YYB_SERVER 读取内网服务，多条换行分隔
let SERVERS = [];
const envYybGo = process.env.YYB_SERVER || "";
if (envYybGo) {
    SERVERS = envYybGo
        .split(/\r?\n/)
        .map(item => item.trim())
        .filter(item => item.length > 0);
}
// 校验是否存在有效地址
const NOTIFY_ENABLED = String(process.env.KKKL_NOTIFY || "1").trim() !== "0";

const PLUSPLUS_TOKEN = process.env.PUSHPLUS_TOKEN || process.env.PLUSPLUS_TOKEN || "";

const PROXY_API = process.env.PROXY_API || "";
const PROXY_TYPE = (process.env.PROXY_TYPE || "http").toLowerCase();
const PROXY_RETRY_TIMES = 3;
const PROXY_VALIDATE_URL = "http://httpbin.org/ip";
const PROXY_FETCH_INTERVAL = 3000;
const ENABLE_DIRECT_FALLBACK = true;

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823";

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function random(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
}

function mask(value = "") {
    const text = String(value || "");
    if (!text) return "-";
    return text.length > 16 ? `${text.slice(0, 8)}***${text.slice(-8)}` : `${text.slice(0, 4)}***`;
}

function parseYybGoEntry(rawValue) {
    let value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "", note: "" };
    let note = "";
    const hashIndex = value.lastIndexOf("#");
    if (hashIndex > value.lastIndexOf("@") && hashIndex !== -1) {
        note = value.slice(hashIndex + 1).trim();
        value = value.slice(0, hashIndex).trim();
    }
    const atIndex = value.lastIndexOf("@");
    if (atIndex === -1) {
        console.log("   ❌ [账号] 格式应为 地址@标识[#备注]，当前值: " + value);
        return { server: "", ref: "", note: "" };
    }
    let server = value.slice(0, atIndex).trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
    const ref = value.slice(atIndex + 1).trim();
    if (!server || !ref) return { server: "", ref: "", note: "" };
    return { server, ref, note };
}

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
function toInt(value, fallback = 0) { const n = Number(value); return Number.isFinite(n) ? Math.trunc(n) : fallback; }
function brief(value, limit = 90) { const text = String(value ?? "").replace(/\n/g, " "); return text.length <= limit ? text : text.slice(0, limit - 1) + "…"; }
async function captureLogs(fn) {
    const lines = [];
    const original = console.log;
    console.log = (...args) => {
        const line = args.map((arg) => (typeof arg === "string" ? arg : JSON.stringify(arg))).join(" ");
        original("   " + line.replace(/^\s+/, ""));
        lines.push(line);
    };
    try { await fn(); } finally { console.log = original; }
    return lines;
}

function parseProxyResponse(text) {
    if (typeof text !== "string") {
        text = JSON.stringify(text);
    }

    text = text.trim();
    if (!text) return null;

    try {
        const data = JSON.parse(text);
        let proxyObj = null;

        if (data.data && Array.isArray(data.data) && data.data.length > 0) {
            proxyObj = data.data[0];
        } else if (data.data && typeof data.data === "object") {
            proxyObj = data.data;
        } else if (data.ip && data.port) {
            proxyObj = data;
        } else if (data.result && data.result.ip && data.result.port) {
            proxyObj = data.result;
        }

        if (proxyObj) {
            return {
                host: proxyObj.ip || proxyObj.host,
                port: proxyObj.port,
                username: proxyObj.user || proxyObj.username || "",
                password: proxyObj.pass || proxyObj.password || ""
            };
        }
    } catch (e) {}

    if (text.includes(":")) {
        const parts = text.split(":");
        if (parts.length >= 2) {
            return {
                host: parts[0],
                port: Number(parts[1]),
                username: parts[2] || "",
                password: parts[3] || ""
            };
        }
    }

    return null;
}

function buildProxyAgent(proxyInfo) {
    if (!proxyInfo) return null;

    const { host, port, username, password } = proxyInfo;
    let auth = "";

    if (username && password) {
        auth = `${encodeURIComponent(username)}:${encodeURIComponent(password)}@`;
    }

    try {
        if (PROXY_TYPE === "socks5") {
            if (!SocksProxyAgent) { console.log("⚠️ [代理] 缺少 socks-proxy-agent，改为直连"); return null; }
            const proxyUrl = `socks5://${auth}${host}:${port}`;
            console.log(`🛠️ [代理] 生成 SOCKS5 代理 ${host}:${port}`);
            return {
                httpAgent: new SocksProxyAgent(proxyUrl),
                httpsAgent: new SocksProxyAgent(proxyUrl)
            };
        }

        if (!HttpProxyAgent || !HttpsProxyAgent) { console.log("⚠️ [代理] 缺少 http(s)-proxy-agent，改为直连"); return null; }
        const proxyUrl = `http://${auth}${host}:${port}`;
        console.log(`🛠️ [代理] 生成 HTTP 代理 ${host}:${port}`);
        return {
            httpAgent: new HttpProxyAgent(proxyUrl),
            httpsAgent: new HttpsProxyAgent(proxyUrl)
        };
    } catch (e) {
        console.log(`❌ [代理] 生成代理失败: ${e.message}`);
        return null;
    }
}

async function validateProxy(agent) {
    if (!agent) return { ok: false, ip: "" };

    try {
        const res = await axios({
            method: "get",
            url: PROXY_VALIDATE_URL,
            timeout: 15000,
            ...agent
        });

        if (res.status === 200) {
            const ip = res.data?.origin || "未知";
            console.log(`✅ [代理] 验证通过，出口 IP: ${ip}`);
            return { ok: true, ip };
        }
    } catch (e) {
        console.log(`⚠️ [代理] 验证失败: ${e.message}`);
    }

    return { ok: false, ip: "" };
}

async function getValidProxy(accountName) {
    if (!PROXY_API) {
        console.log(`⚠️ [代理] ${accountName} 未配置 PROXY_API，使用直连`);
        return { agent: null, ip: "" };
    }

    console.log(`🌐 [代理] ${accountName} 正在获取品赞代理...`);

    for (let i = 1; i <= PROXY_RETRY_TIMES; i++) {
        try {
            const res = await axios.get(PROXY_API, {
                timeout: 15000,
                proxy: false
            });

            const proxyInfo = parseProxyResponse(res.data);

            if (!proxyInfo) {
                console.log(`⚠️ [代理] 第 ${i} 次解析失败`);
                continue;
            }

            console.log(`✅ [代理] 提取到 ${proxyInfo.host}:${proxyInfo.port}`);

            const agent = buildProxyAgent(proxyInfo);
            const valid = await validateProxy(agent);

            if (valid.ok) {
                return { agent, ip: valid.ip };
            }
        } catch (e) {
            console.log(`⚠️ [代理] 第 ${i} 次获取异常: ${e.message}`);
        }

        if (i < PROXY_RETRY_TIMES) {
            await sleep(2000);
        }
    }

    console.log("⚠️ [代理] 获取失败，使用直连");
    return { agent: null, ip: "" };
}

async function requestWithProxy(config, proxyAgent, server) {
    if (proxyAgent) {
        try {
            return await axios({
                timeout: 30000,
                ...config,
                ...proxyAgent
            });
        } catch (e) {
            console.log(`⚠️ [代理] ${server} 代理请求失败: ${e.message}`);

            if (!ENABLE_DIRECT_FALLBACK) {
                throw e;
            }

            console.log("🔁 [兜底] 切换直连重试");
        }
    }

    return await axios({
        timeout: 30000,
        proxy: false,
        ...config
    });
}

async function sendPushPlus(title, content) {
    if (!PLUSPLUS_TOKEN) {
        console.log("ℹ️ [PushPlus] 未配置 PUSHPLUS_TOKEN，跳过推送");
        return;
    }

    try {
        await axios.post(
            "https://www.pushplus.plus/send",
            {
                token: PLUSPLUS_TOKEN,
                title,
                content,
                template: "txt"
            },
            {
                timeout: 10000,
                proxy: false
            }
        );

        console.log("✅ [PushPlus] 推送成功");
    } catch (e) {
        console.log(`❌ [PushPlus] 推送失败: ${e.message}`);
    }
}

async function getCode(server) {
    const { server: parsedServer, ref } = parseYybGoEntry(server);
    if (!parsedServer || !ref) return null;

    const url = `http://${parsedServer}/wxapp/getCode`;

    try {
        const { data } = await axios.post(url, {
            ref,
            app_id: APPID
        }, {
            timeout: 20000,
            proxy: false
        });
        const code = data?.data?.result?.code;
        if (data?.code !== 0 || !code) {
            console.log(`   ❌ [授权] 取码失败: ${brief(JSON.stringify(data), 200)}`);
            return null;
        }
        console.log("   ✅ [授权] 取码成功");
        return code;
    } catch (e) {
        console.log(`   ❌ [授权] 取码异常: ${brief(e.message)}`);
        return null;
    }
}


async function getUserToken(code, proxyAgent, server) {
    const config = {
        method: "GET",
        url: `https://member-api.icoke.cn/api/sp-portal/store/icoke/wechat/loginNoCache/${code}`,
        headers: {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "xweb_xhr": "1",
            "Content-Type": "application/json",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://servicewechat.com/wxa5811e0426a94686/496/page-frame.html",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }
    };

    try {
        const { data } = await requestWithProxy(config, proxyAgent, server);

        if (data?.jwtString) {
            console.log(`✅ [登录] token 获取成功: ${mask(data.jwtString)}`);
            return {
                token: data.jwtString,
                raw: data
            };
        }

        console.log(`❌ [登录] token 获取失败: ${data?.message || JSON.stringify(data)}`);
        return {
            token: null,
            raw: data
        };
    } catch (e) {
        console.log(`❌ [登录] token 请求异常: ${e.message}`);
        return {
            token: null,
            raw: null
        };
    }
}

async function getUserInfo(token, proxyAgent, server) {
    const config = {
        method: "GET",
        url: "https://member-api.icoke.cn/api/icoke-customer/icoke/mini/customer/main/points",
        headers: {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "authorization": token,
            "content-type": "application/json",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
            "xweb_xhr": "1",
            "Referer": "https://servicewechat.com/wxa5811e0426a94686/421/page-frame.html",
            "Referrer-Policy": "unsafe-url"
        }
    };

    try {
        const { data } = await requestWithProxy(config, proxyAgent, server);
        console.log(`💰 [积分] 当前快乐瓶: ${data?.point ?? "-"}`);
        return data;
    } catch (e) {
        if (e.response?.status === 401) return { code: 401, message: "登录态失效（401）" };
        console.log(`⚠️ [积分] 查询异常: ${e.message}`);
        return null;
    }
}

async function addSign(token, proxyAgent, server) {
    const config = {
        method: "GET",
        url: "https://member-api.icoke.cn/api/icoke-sign/icoke/mini/sign/main/sign",
        headers: {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "authorization": token,
            "content-type": "application/json",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
            "xweb_xhr": "1",
            "Referer": "https://servicewechat.com/wxa5811e0426a94686/421/page-frame.html",
            "Referrer-Policy": "unsafe-url"
        }
    };

    try {
        const { data } = await requestWithProxy(config, proxyAgent, server);

        if (data?.success === true) {
            const msg = `签到成功，获得 ${data.point ?? "-"} 快乐瓶`;
            console.log(`✅ [签到] ${msg}`);
            return {
                success: true,
                message: msg,
                raw: data
            };
        }

        const msg = String(data?.message || data?.msg || JSON.stringify(data));
        if (/已签到|今天已签到|重复签到|今日已|明天再来/.test(msg)) {
            const text = `今日已签到（${msg}）`;
            console.log(`ℹ️ [签到] ${text}`);
            return { success: true, message: text, raw: data };
        }
        console.log(`❌ [签到] 签到失败: ${msg}`);
        return { success: false, message: msg, raw: data };
    } catch (e) {
        console.log(`❌ [签到] 请求异常: ${e.message}`);
        return {
            success: false,
            message: e.message,
            raw: null
        };
    }
}

function cacheKeyOf(entry) {
    return entry.server && entry.ref ? `${entry.server}|${entry.ref}` : String(entry.server || "");
}

// 静默解析旧缓存键的标识：纯标识 / 地址@标识 / 地址@标识#备注
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

function loadCachedToken(cache, entry) {
    const key = cacheKeyOf(entry);
    if (cache[key] && cache[key].token) return cache[key].token;
    for (const k of Object.keys(cache)) {
        if (k === key) continue;
        if (cache[k] && cache[k].token && legacyRefOf(k) === entry.ref) {
            cache[key] = { ...cache[k], updatedAt: new Date().toISOString() };
            delete cache[k];
            for (const other of Object.keys(cache)) {
                if (other !== key && cache[other] && legacyRefOf(other) === entry.ref) delete cache[other];
            }
            writeTokenCache(cache);
            console.log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」");
            return cache[key].token;
        }
    }
    return "";
}

function removeCachedToken(entry) {
    const cache = readTokenCache();
    const key = cacheKeyOf(entry);
    delete cache[key];
    for (const k of Object.keys(cache)) {
        if (k !== key && legacyRefOf(k) === entry.ref) delete cache[k];
    }
    writeTokenCache(cache);
}

async function runAccount(index, total, server) {
    const entry = parseYybGoEntry(server);
    const title = `标识 ${entry.ref || "-"}` + (entry.note ? `（${entry.note}）` : "");
    const result = {
        index, server, ref: entry.ref, name: title,
        success: false, proxyStatus: "未使用代理", proxyIp: "-",
        token: "-", loginSource: "", beforePoint: "-", afterPoint: "-",
        signMsg: "-", error: "",
    };

    accountFrame(index, total, title, server);
    if (!entry.server || !entry.ref) {
        result.error = "账号格式无效";
        console.log("   ❌ [账号] 账号格式无效（需要 地址@标识[#备注]）");
        return result;
    }

    const proxy = await getValidProxy(server);
    const proxyAgent = proxy.agent;
    result.proxyStatus = proxyAgent ? "使用专属代理" : "使用直连";
    result.proxyIp = proxy.ip || "-";


    await sleep(PROXY_FETCH_INTERVAL);

    const cache = readTokenCache();
    const key = cacheKeyOf(entry);
    let token = String(loadCachedToken(cache, entry) || "");
    if (token) {
        result.loginSource = "缓存";
        console.log(`   💾 [缓存] 复用已保存的 token（${mask(token)}）`);
    }

    await captureLogs(async () => {
        for (let attempt = 0; attempt < 2; attempt++) {
            if (attempt === 1 || !token) {
                if (attempt === 1) {
                    console.log("♻️ [登录] 重新登录后再试一次");
                    removeCachedToken(entry);
                    token = "";
                    result.loginSource = "重新登录";
                }
                const code = await getCode(server);
                if (!code) {
                    result.error = "获取 code 失败";
                    console.log("   ❌ [账号] 获取 code 失败");
                    return;
                }
                const login = await getUserToken(code, proxyAgent, server);
                if (!login.token) {
                    result.error = "获取 token 失败";
                    console.log("   ❌ [登录] 获取 token 失败");
                    return;
                }
                token = login.token;
                result.loginSource = result.loginSource === "重新登录" ? "重新登录" : "新登录";
                const c = readTokenCache();
                c[key] = { token, updatedAt: new Date().toISOString() };
                writeTokenCache(c);
                console.log(`🔐 [登录] token 获取成功并缓存（${mask(token)}）`);
            }

            result.token = mask(token);
            const beforeInfo = await getUserInfo(token, proxyAgent, server);
            if (!beforeInfo || beforeInfo.point === undefined) {
                if (attempt === 0) {
                    console.log("♻️ [校验] 登录凭证校验未通过，清理缓存后重登");
                    token = "";
                    result.loginSource = "重新登录";
                    continue;
                }
                result.error = "登录凭证校验失败";
                removeCachedToken(entry);
                console.log("   ❌ [校验] 登录凭证校验失败，已清除缓存");
                return;
            }
            result.beforePoint = beforeInfo.point;
            result.afterPoint = beforeInfo.point;
            console.log(`✅ [校验] 登录凭证校验通过（会员积分接口，来源${result.loginSource || "缓存"}）`);
            console.log(`🔐 [登录] 登录成功（来源${result.loginSource || "缓存"}）`);
            console.log(`💰 [积分] 签到前 ${beforeInfo.point} 快乐瓶`);

            await sleep(random(2000, 5000));
            const sign = await addSign(token, proxyAgent, server);
            result.signMsg = sign.message;
            const msgText = String(sign.message || "");
            result.success = !!sign.success || (
                /已签到|今天已签到|已领取|重复签到|今日已|明天再来|已完成/.test(msgText) &&
                !/异常|网络|超时/.test(msgText)
            );

            await sleep(random(2000, 5000));
            const afterInfo = await getUserInfo(token, proxyAgent, server);
            if (afterInfo && afterInfo.point !== undefined) {
                result.afterPoint = afterInfo.point;
                console.log(`📈 [积分] 签到后 ${afterInfo.point} 快乐瓶`);
            }

            if (result.success) {
                console.log("✅ [完成] 该账号任务执行完成");
                return;
            }

            if (attempt === 0) {
                console.log(`♻️ [签到] 未成功（${brief(sign.message)}），清理缓存后重登重试`);
                token = "";
                result.loginSource = "重新登录";
                continue;
            }
            result.error = sign.message;
            console.log(`❌ [签到] ${brief(sign.message)}`);
            return;
        }
    });

    return result;
}

function buildNotify(results) {
    const successCount = results.filter(item => item.success).length;
    const failCount = results.length - successCount;

    let content = `🥤 可口可乐多账号签到结果

━━━━━━━━━━━━━━━━━━━━
🏁 总结：${successCount} 成功 / ${failCount} 失败
🕒 时间：${new Date().toLocaleString("zh-CN")}
━━━━━━━━━━━━━━━━━━━━
`;

    results.forEach((res, index) => {
        const icon = res.success ? "✅" : "❌";

        content += `
🧩 账号 ${index + 1}
🌍 来源：${res.server}
🌐 代理：${res.proxyStatus}
📡 出口IP：${res.proxyIp}
🔐 Token：${res.token}
💰 签到前快乐瓶：${res.beforePoint}
📝 签到结果：${res.signMsg}
💰 签到后快乐瓶：${res.afterPoint}
${icon} 结果：${res.success ? "成功" : "失败"}
`;

        if (!res.success) {
            content += `❌ 原因：${res.error}\n`;
        }

        content += "━━━━━━━━━━━━━━━━━━━━\n";
    });

    return content;
}

async function sendQingLongNotify(title, content) {
    const candidates = [
        "/ql/data/scripts/notify.js",
        "/ql/scripts/notify.js",
        path.join(__dirname, "notify.js"),
        path.join(__dirname, "SendNotify.js"),
    ];
    for (const file of candidates) {
        try {
            if (!fs.existsSync(file)) continue;
            const mod = require(file);
            const fn = (typeof mod === "function" && mod) || mod.sendNotify || mod.send;
            if (typeof fn === "function") { await fn(title, content); return true; }
        } catch {}
    }
    return false;
}

(async () => {
    if (!SERVERS.length) {
        console.log("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识[#备注]，多账号换行分隔）");
        return;
    }
    const valid = SERVERS.filter(item => item.includes("@"));
    if (!valid.length) {
        console.log("❌ YYB_SERVER 无有效账号（格式：地址@标识[#备注]）");
        return;
    }
    SERVERS = valid;

    boxTop("🥤 可口可乐 每日签到");
    boxLine("🕒 启动时间", new Date().toLocaleString("zh-CN"));
    boxLine("🔢 账号数量", `${SERVERS.length} 个`);
    boxLine("💾 缓存", "kkkl_token_cache.json");
    boxLine("🌐 代理", PROXY_API ? "专属代理" : "直连");
    boxBottom();

    const results = [];
    for (let i = 0; i < SERVERS.length; i++) {
        try {
            results.push(await runAccount(i + 1, SERVERS.length, SERVERS[i]));
        } catch (e) {
            const entry = parseYybGoEntry(SERVERS[i]);
            console.log(`   ❌ [主程序] ${brief(e.message)}`);
            results.push({
                index: i + 1, server: SERVERS[i], ref: entry.ref, name: SERVERS[i],
                success: false, loginSource: "", proxyStatus: "-", proxyIp: "-",
                token: "-", beforePoint: "-", afterPoint: "-", signMsg: "-",
                error: `异常 ${brief(e.message)}`,
            });
        }
        hr();
        if (i < SERVERS.length - 1) {
            console.log("   ⏳ 等待2秒后执行下一个账号...");
            await sleep(2000);
        }
    }

    console.log("");
    for (const res of results) {
        console.log(`${res.success ? "✅" : "❌"} 【账号 ${res.index} · ${res.name}】`);
        console.log(`   🔐 [登录] ${res.loginSource || "-"}（${res.token}）`);
        console.log(`   📝 [签到] ${res.signMsg}`);
        console.log(`   💰 [积分] ${res.beforePoint} → ${res.afterPoint}`);
        if (!res.success) console.log(`   ⚠️ [失败] ${res.error || "未知错误"}`);
    }

    const successCount = results.filter(item => item.success).length;
    const failCount = results.length - successCount;
    boxTop("🏁 可口可乐 执行汇总");
    boxLine("📊 执行结果", `成功 ${successCount} / 失败 ${failCount} / 共 ${results.length}`);
    boxLine("🕒 结束时间", new Date().toLocaleString("zh-CN"));
    boxBottom();

    if (NOTIFY_ENABLED) {
        const content = buildNotify(results);
        const sent = await sendQingLongNotify("🥤 可口可乐签到任务完成", content);
        console.log(sent ? "   📮 [通知] 已调用青龙 notify" : "   ℹ️ [通知] 未找到青龙 notify 脚本");
        await sendPushPlus("🥤 可口可乐多账号签到完成", content);
    } else {
        console.log("   ℹ️ [通知] KKKL_NOTIFY=0，已关闭通知");
    }
})().catch(e => {
    console.log(`❌ [全局异常] ${e.message}`);
});
