// name: 杰士邦会员中心
// cron: 24 13,1 * * *

const axios = require("axios");
const fs = require("fs");
const path = require("path");

const APP = {
    name: "杰士邦会员中心",
    appid: "wx5966681b4a895dee",
    shopId: "467028",
    signActivityId: "170630",
};

const BASE = "https://api.vshop.hchiv.cn/jfmb";
const EP_LOGIN = "/cloud/member/wechatlogin/authLoginApplet";
const EP_CLIENT = "/cloud/member/tblogin/getClientInfo";
const EP_CARD = "/api/customize/get-card-info.do";
const EP_SHOP = "/cloud/member/shop/getShopInfo";
const EP_SIGN_INFO = "/cloud/activity/sign/load-sign";
const EP_SIGN = "/cloud/activity/sign/add-sign";

const BOX_WIDTH = 48;
const BOX_INNER = 46;
const SCRIPT_DIR = __dirname;
const CACHE_DIR = path.join(SCRIPT_DIR, "token_caches");
const CACHE_FILE = path.join(CACHE_DIR, "jsbhyzx_token_cache.json");

const NOTIFY_ON = String(process.env.JSBHYZX_NOTIFY ?? "1").trim() !== "0";
const COMMUNITY_RE = /微信小程序|登录|未登录|token|授权|鉴权|clientToken|session|cookie|失效|过期|401|403/i;
const SIGNED_RE = /已签|签到过|重复|已完成|无法参与|已达到上限/;

const UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/19027",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50(0x1800322e) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (Linux; Android 13; 22021211RC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.47.2560(0x28002F30) WeChat/arm64 Weixin NetType/WIFI MiniProgramEnv/android",
];

function readCache() {
    try {
        if (!fs.existsSync(CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(CACHE_FILE, "utf-8")) || {};
    } catch {
        return {};
    }
}

function writeCache(cache) {
    try {
        fs.mkdirSync(CACHE_DIR, { recursive: true });
        fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2), "utf-8");
        return true;
    } catch (e) {
        console.log(`   ⚠️ [缓存] 写入失败: ${brief(e.message, 60)}`);
        return false;
    }
}

function cacheKey(server, ref) {
    return `${server}|${ref}`;
}

function entryToken(entry) {
    return entry && (entry.clientToken || entry.token || "");
}

function entrySession(entry) {
    return entry && (entry.jsession || entry.session || "");
}

function loadCache(server, ref, raw) {
    const cache = readCache();
    const key = cacheKey(server, ref);
    const entry = cache[key];
    if (entryToken(entry) || entrySession(entry)) return entry;

    const legacyKeys = [
        ref,
        String(raw || "").trim(),
        `${server}@${ref}`,
        `${server}@${ref}${String(raw || "").includes("#") ? "#" + String(raw).split("#").slice(1).join("#") : ""}`,
    ];
    for (const legacy of legacyKeys) {
        if (!legacy || legacy === key) continue;
        const old = cache[legacy];
        if (!entryToken(old) && !entrySession(old)) continue;
        const migrated = { ...old };
        cache[key] = migrated;
        delete cache[legacy];
        writeCache(cache);
        console.log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」");
        return migrated;
    }

    for (const oldKey of Object.keys(cache)) {
        if (oldKey === key || !oldKey.includes("@")) continue;
        const left = oldKey.slice(0, oldKey.lastIndexOf("@"));
        if (left !== server) continue;
        const oldRef = oldKey.slice(oldKey.lastIndexOf("@") + 1).split("#")[0].trim();
        const old = cache[oldKey];
        if (oldRef !== ref || (!entryToken(old) && !entrySession(old))) continue;
        const migrated = { ...old };
        cache[key] = migrated;
        delete cache[oldKey];
        writeCache(cache);
        console.log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」");
        return migrated;
    }
    return null;
}

function saveCache(task) {
    const cache = readCache();
    cache[cacheKey(task.server, task.ref)] = {
        clientToken: task.global.clientToken,
        jsession: task.global.jsession,
        openId: task.global.openId,
        unionid: task.global.unionid,
        securePlatId: task.global.securePlatId,
        shopId: task.global.shopId,
        shopNick: task.global.shopNick,
        mainShopNick: task.global.mainShopNick,
        nickname: task.userName,
        points: task.points,
        updatedAt: new Date().toISOString(),
    };
    writeCache(cache);
}

function dropCache(server, ref) {
    const cache = readCache();
    delete cache[cacheKey(server, ref)];
    writeCache(cache);
}

function parseEntry(rawValue) {
    let value = String(rawValue || "").trim();
    let note = "";
    if (!value) return { server: "", ref: "", note: "", raw: "" };
    const hash = value.lastIndexOf("#");
    const at = value.lastIndexOf("@");
    if (hash > at && hash !== -1) {
        note = value.slice(hash + 1).trim();
        value = value.slice(0, hash).trim();
    }
    if (value.lastIndexOf("@") === -1) return { server: "", ref: "", note, raw: String(rawValue) };
    const atIndex = value.lastIndexOf("@");
    const server = value.slice(0, atIndex).trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
    const ref = value.slice(atIndex + 1).trim();
    return { server, ref, note, raw: String(rawValue) };
}

function displayWidth(text) {
    let width = 0;
    for (const ch of String(text)) {
        const code = ch.codePointAt(0);
        if (code === 0xfe0f || code === 0xfe0e || code === 0x200d) continue;
        width += code > 0xff ? 2 : 1;
    }
    return width;
}

function pad(text, width) {
    let value = String(text);
    while (value && displayWidth(value) > width) value = value.slice(0, -1);
    return value + " ".repeat(Math.max(0, width - displayWidth(value)));
}

function boxTop(title) {
    console.log(`\n╔${"═".repeat(BOX_WIDTH)}╗`);
    console.log(`║  ${pad(title, BOX_INNER)}║`);
}

function boxLine(label, value) {
    console.log(`║  ${pad(`${label}: ${value}`, BOX_INNER)}║`);
}

function boxBottom() {
    console.log(`╚${"═".repeat(BOX_WIDTH)}╝`);
}

function accountFrame(index, total, title, source) {
    console.log(`\n┌${"─".repeat(BOX_WIDTH)}┐`);
    console.log(`│  ${pad(`🧩 账号 ${index} / ${total}　${title}`, BOX_INNER)}│`);
    console.log(`│  ${pad(`🔗 来源: ${source}`, BOX_INNER)}│`);
    console.log(`└${"─".repeat(BOX_WIDTH)}┘`);
}

function hr() {
    console.log(`\n${"-".repeat(BOX_WIDTH)}`);
}

function brief(value, limit = 100) {
    const text = String(value ?? "").replace(/\s+/g, " ").trim();
    return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function short(value, limit = 220) {
    if (value === undefined || value === null) return "";
    let text;
    try {
        text = typeof value === "string" ? value : JSON.stringify(value);
    } catch {
        text = String(value);
    }
    return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function toInt(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? Math.trunc(n) : fallback;
}

function truthy(value) {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value !== 0;
    return ["1", "true", "yes", "y", "on"].includes(String(value).trim().toLowerCase());
}

function firstValue(...values) {
    for (const value of values) {
        if (value !== undefined && value !== null && value !== "") return value;
    }
    return "";
}

function apiCode(body) {
    if (!body || typeof body !== "object") return null;
    const inner = body.data;
    if (inner && typeof inner === "object" && inner.code !== undefined) return toInt(inner.code, -1);
    if (body.code !== undefined) return toInt(body.code, -1);
    return null;
}

function apiMessage(body) {
    if (!body || typeof body !== "object") return "";
    return String(
        body.message ||
        body.msg ||
        body.data?.message ||
        body.data?.msg ||
        body.errorMessage ||
        ""
    ).trim();
}

function apiSuccess(body) {
    const code = apiCode(body);
    return code === null || code === 0 || code === 200;
}

function authCode(code) {
    return code === 401 || code === 403;
}

function unwrap(body) {
    let cur = body;
    for (let i = 0; i < 4; i++) {
        if (!cur || typeof cur !== "object") return {};
        if (cur.data && typeof cur.data === "object") {
            if (cur.data.code !== undefined || cur.data.message !== undefined || cur.data.msg !== undefined) {
                cur = cur.data;
                continue;
            }
            return cur.data;
        }
        return cur;
    }
    return cur && typeof cur === "object" ? cur : {};
}

class ApiError extends Error {
    constructor(message, code = -1, body = null) {
        super(message);
        this.code = code;
        this.body = body;
    }
}

class AuthError extends ApiError {}

class NotMemberError extends ApiError {}

async function request(options) {
    const res = await axios.request({
        timeout: 20000,
        proxy: false,
        validateStatus: () => true,
        ...options,
        headers: {
            "User-Agent": UA_POOL[Math.floor(Math.random() * UA_POOL.length)],
            Accept: "application/json, text/plain, */*",
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
    });
    return { status: res.status, headers: res.headers || {}, data: res.data };
}

async function getCode(server) {
    const entry = parseEntry(server);
    if (!entry.server || !entry.ref) return null;
    try {
        const { data } = await axios.post(
            `http://${entry.server}/wxapp/getCode`,
            { ref: entry.ref, app_id: APP.appid },
            { timeout: 20000, proxy: false, validateStatus: () => true }
        );
        let result = data?.data?.result;
        if (typeof result === "string") {
            try { result = JSON.parse(result); } catch { result = {}; }
        }
        const code = result?.code || data?.data?.code;
        if (!data || toInt(data.code, -1) !== 0 || !code) {
            console.log(`   ❌ [取码] 取码失败: ${brief(data?.message || data?.msg || data, 100)}`);
            return null;
        }
        console.log("   ✅ [取码] 取码成功");
        return code;
    } catch (e) {
        console.log(`   ❌ [取码] 请求异常: ${brief(e.message, 80)}`);
        return null;
    }
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

class JsbMember {
    constructor(entry) {
        this.server = entry.server;
        this.ref = entry.ref;
        this.note = entry.note;
        this.raw = entry.raw;
        this.userName = "";
        this.points = "未知";
        this.level = "";
        this.global = {
            appId: APP.appid,
            shopId: APP.shopId,
            openId: "",
            shopNick: "",
            mainShopNick: "",
            unionid: "",
            phoneNumber: "",
            jsession: "",
            clientToken: "",
            securePlatId: "",
            sourceShopId: "",
        };
    }

    buildData(data = {}, reqType = 2) {
        const timestamp = Date.now();
        const common = {
            appId: this.global.appId,
            openId: this.global.openId || this.ref,
            shopNick: this.global.shopNick || "",
            timestamp,
            interfaceSource: 0,
        };
        return reqType === 2 ? { ...common, ...data } : { ...data };
    }

    async api(apiPath, data = {}, { reqType = 2 } = {}) {
        const headers = {
            "content-type": "application/json",
            appenv: "test",
            Referer: `https://servicewechat.com/${APP.appid}/33/page-frame.html`,
        };
        if (this.global.jsession) headers.cookie = this.global.jsession;
        if (this.global.clientToken) headers.Authorization = `Bearer ${this.global.clientToken}`;

        const body = typeof data === "string" ? JSON.parse(data) : data;
        const timestamp = Date.now();
        const query = reqType === 2
            ? `?sideType=3&mob=${encodeURIComponent(this.global.phoneNumber || "")}`
              + `&appId=${encodeURIComponent(this.global.appId)}`
              + `&shopNick=${encodeURIComponent(this.global.mainShopNick || this.global.appId)}`
              + `&timestamp=${timestamp}`
              + `${this.global.securePlatId ? `&securePlatId=${encodeURIComponent(this.global.securePlatId)}` : ""}`
              + `${this.global.sourceShopId ? `&sourceShopId=${encodeURIComponent(this.global.sourceShopId)}` : ""}`
            : "";

        const res = await request({
            method: "POST",
            url: `${BASE}${apiPath}${query}`,
            headers,
            data: this.buildData(body, reqType),
        });

        const setCookie = res.headers["set-cookie"];
        const cookie = Array.isArray(setCookie) ? setCookie[0] : setCookie;
        if (cookie) this.global.jsession = String(cookie).split(";")[0];

        const token = res.data?.data?.clientToken || res.data?.data?.data?.clientToken;
        if (token) this.global.clientToken = token;
        const securePlatId = res.data?.data?.data?.securePlatId || res.data?.data?.securePlatId;
        if (securePlatId) this.global.securePlatId = securePlatId;

        if (res.status === 401 || res.status === 403) {
            throw new AuthError(`HTTP ${res.status}，登录凭证已失效`, 401, res.data);
        }
        return res.data;
    }

    throwIfAuth(body) {
        const code = apiCode(body);
        const msg = apiMessage(body);
        if (authCode(code) || COMMUNITY_RE.test(msg)) {
            throw new AuthError(msg || `接口返回 code=${code}`, code || 401, body);
        }
    }

    async login() {
        const code = await getCode(this.raw);
        if (!code) throw new ApiError("取码失败，无法登录");

        const auth = await this.api(EP_LOGIN, {
            wxInfo: code,
            extend: "{}",
            sessionIdForWxShop: "",
        });
        const innerCode = apiCode(auth);
        const msg = apiMessage(auth);
        if (!apiSuccess(auth)) {
            throw new ApiError(`登录失败: ${brief(msg || `code=${innerCode}`, 80)}`, innerCode, auth);
        }

        const payload = unwrap(auth);
        this.global.openId = firstValue(payload.openId, payload.openid, auth?.data?.openId, this.ref);
        this.global.unionid = firstValue(payload.unionId, payload.unionid, auth?.data?.unionId, "");

        if (!this.global.clientToken && !this.global.jsession) {
            throw new NotMemberError("登录未返回 clientToken，该微信号可能还没在杰士邦注册会员");
        }
        console.log(`   ✅ [登录] 登录成功（clientToken=${this.global.clientToken ? short(this.global.clientToken, 22) : "无，使用 session"}）`);
    }

    async query() {
        const clientBody = await this.api(EP_CLIENT, {});
        this.throwIfAuth(clientBody);
        if (!apiSuccess(clientBody)) {
            throw new ApiError(`用户信息查询失败: ${brief(apiMessage(clientBody) || `code=${apiCode(clientBody)}`, 80)}`);
        }
        const client = unwrap(clientBody);

        let card = {};
        try {
            const cardBody = await this.api(EP_CARD, {});
            if (apiSuccess(cardBody)) card = unwrap(cardBody);
        } catch {
            // 会员卡信息是可选数据，失败不影响登录校验
        }

        let shop = {};
        try {
            const shopBody = await this.api(EP_SHOP, {});
            if (apiSuccess(shopBody)) shop = unwrap(shopBody);
        } catch {
            // 店铺信息仅用于补充展示，失败不影响签到
        }

        if (shop.sellerId) this.global.shopId = String(shop.sellerId);
        if (shop.mainShopNick) this.global.mainShopNick = shop.mainShopNick;
        if (shop.shopNick) this.global.shopNick = shop.shopNick;

        this.userName = String(firstValue(
            client.client_name,
            client.nickname,
            client.nickName,
            client.user_mob,
            client.mobile,
            card.name,
            ""
        ));
        this.level = String(firstValue(
            client.member_level_str,
            client.levelName,
            client.currLevelName,
            card.currLevelName,
            ""
        ));
        this.points = firstValue(
            client.residualIntegral,
            client.integral,
            client.points,
            client.currentPoints,
            card.residualIntegral,
            card.points,
            "未知"
        );
        this.global.phoneNumber = String(firstValue(client.user_mob, client.mobile, this.global.phoneNumber, ""));

        return {
            name: this.userName || "未知",
            points: this.points,
            level: this.level,
            shop: firstValue(shop.shopTitle, shop.title, shop.shopNick, ""),
            client,
            card,
        };
    }

    async sign() {
        const activityId = APP.signActivityId;
        const info = await this.api(EP_SIGN_INFO, { activityId });
        this.throwIfAuth(info);
        const infoCode = apiCode(info);
        const infoMsg = apiMessage(info);

        if (infoCode === 204 || /未注册|未登录|未绑定/.test(infoMsg)) {
            return { ok: false, registered: false, message: infoMsg || "该微信号还没在杰士邦注册会员" };
        }
        if (!apiSuccess(info)) {
            return { ok: false, message: `签到活动查询失败 activityId=${activityId}: ${brief(infoMsg || short(info), 90)}` };
        }

        const signInfo = unwrap(info);
        if (truthy(signInfo.signed)) {
            return {
                ok: true,
                signed: true,
                message: `今日已签到 连续=${toInt(signInfo.continuousSignNum, 0)} 累计=${toInt(signInfo.totalSignNum, 0)}`,
            };
        }

        const signBody = await this.api(EP_SIGN, { activityId });
        this.throwIfAuth(signBody);
        const signCode = apiCode(signBody);
        const signMsg = apiMessage(signBody);
        const data = unwrap(signBody);

        if (apiSuccess(signBody)) {
            const prizes = Array.isArray(data.prizeList) && data.prizeList.length
                ? ` 奖励=${data.prizeList.map((x) => x.prizeName || x.name || short(x, 30)).join("，")}`
                : "";
            return {
                ok: true,
                signed: false,
                message: `签到成功 +${data.integralCount ?? "未知"}积分 连续=${data.continuousSignNum ?? "?"} 累计=${data.totalSignNum ?? "?"}${prizes}`,
                points: firstValue(data.integralCount, ""),
            };
        }
        if (SIGNED_RE.test(signMsg)) {
            return { ok: true, signed: true, message: `今日已签到（${brief(signMsg, 80)}）` };
        }
        return { ok: false, message: `签到失败: ${brief(signMsg || `code=${signCode}`, 100)}` };
    }

    async ensureLogin() {
        const cached = loadCache(this.server, this.ref, this.raw);
        if (cached && (entryToken(cached) || entrySession(cached))) {
            this.global.clientToken = entryToken(cached);
            this.global.jsession = entrySession(cached);
            this.global.openId = cached.openId || "";
            this.global.securePlatId = cached.securePlatId || "";
            this.global.shopId = cached.shopId || APP.shopId;
            this.global.shopNick = cached.shopNick || "";
            this.global.mainShopNick = cached.mainShopNick || "";
            console.log(`   💾 [缓存] 复用已保存 token（${this.global.clientToken ? short(this.global.clientToken, 22) : "session"}）`);
            try {
                const info = await this.query();
                console.log(`   ✅ [校验] 登录凭证校验通过`);
                return { source: "缓存", info };
            } catch (e) {
                if (!(e instanceof AuthError)) throw e;
                console.log(`   ♻️ [缓存] 登录凭证失效（${brief(e.message, 70)}），清除缓存重登`);
                dropCache(this.server, this.ref);
                this.global.clientToken = "";
                this.global.jsession = "";
            }
        }

        console.log("   🔐 [登录] 新登录");
        await this.login();
        const info = await this.query();
        console.log("   ✅ [校验] 登录凭证校验通过");
        saveCache(this);
        return { source: "新登录", info };
    }
}

async function runAccount(raw, index, total) {
    const entry = parseEntry(raw);
    const result = {
        index,
        ref: entry.ref,
        note: entry.note,
        ok: false,
        loginSource: "",
        user: "-",
        pointsBefore: "未知",
        pointsAfter: "未知",
        delta: 0,
        signMessage: "",
        error: "",
    };

    if (!entry.server || !entry.ref) {
        result.error = "账号格式无效";
        console.log(`   ❌ [账号] 格式无效，跳过: ${brief(raw, 80)}`);
        return result;
    }

    for (let attempt = 0; attempt < 2; attempt++) {
        const runner = new JsbMember(entry);
        const usedCache = !!(loadCache(runner.server, runner.ref, raw));
        try {
            const login = await runner.ensureLogin();
            result.loginSource = login.source;
            result.user = login.info.name || "-";
            result.pointsBefore = login.info.points;
            console.log(`   🔐 [登录] ${login.source === "缓存" ? "缓存复用" : "新登录成功"}`);
            console.log(`   👤 [用户] ${result.user}${login.info.level ? ` / ${login.info.level}` : ""}`);
            console.log(`   💰 [积分] 当前 ${result.pointsBefore}`);

            const sign = await runner.sign();
            result.signMessage = sign.message;
            if (!sign.ok) {
                console.log(`   ❌ [签到] ${sign.message}`);
                result.error = sign.registered === false ? `未注册会员: ${sign.message}` : sign.message;
                return result;
            }
            console.log(`   ✅ [签到] ${sign.message}`);
            result.ok = true;

            await sleep(800);
            const afterInfo = await runner.query();
            result.pointsAfter = afterInfo.points;
            const before = toInt(result.pointsBefore, -1);
            const after = toInt(result.pointsAfter, -1);
            result.delta = before >= 0 && after >= 0 ? after - before : 0;
            console.log(`   💰 [积分] ${result.pointsBefore} → ${result.pointsAfter}（${result.delta >= 0 ? "+" : ""}${result.delta}）`);
            saveCache(runner);

            if (result.ok) console.log("   ✅ [完成] 该账号任务执行完成");
            return result;
        } catch (e) {
            const msg = e.message || String(e);
            if (attempt === 0 && (usedCache || e instanceof AuthError || /登录/.test(msg))) {
                console.log(`   ♻️ [重登] ${brief(msg, 80)}，清除缓存后重试`);
                dropCache(runner.server, runner.ref);
                continue;
            }
            result.error = msg;
            console.log(`   ❌ [失败] ${brief(msg, 100)}`);
            return result;
        }
    }
    return result;
}

async function sendQingLongNotify(title, content) {
    for (const file of [
        "/ql/data/scripts/notify.js",
        "/ql/scripts/notify.js",
        path.join(SCRIPT_DIR, "notify.js"),
        path.join(SCRIPT_DIR, "SendNotify.js"),
    ]) {
        try {
            if (!fs.existsSync(file)) continue;
            const mod = require(file);
            const fn = (typeof mod === "function" && mod) || mod.sendNotify || mod.send;
            if (typeof fn === "function") {
                await fn(title, content);
                return true;
            }
        } catch {
            // 继续尝试下一个通知文件
        }
    }
    return false;
}

async function sendPushPlus(title, content) {
    const token = process.env.PLUSPLUS_TOKEN || process.env.PUSH_PLUS_TOKEN || process.env.PUSHPLUS_TOKEN;
    if (!token) return false;
    try {
        await axios.post("http://www.pushplus.plus/send", {
            token,
            title,
            content,
            template: "txt",
        }, { timeout: 15000, proxy: false });
        return true;
    } catch {
        return false;
    }
}

async function main() {
    const raw = process.env.YYB_SERVER || process.env.YYB_GO || "";
    const accounts = raw.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    if (!accounts.length) {
        console.log("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识[#备注]，多账号换行）");
        return;
    }
    const valid = accounts.filter((item) => item.includes("@"));
    if (!valid.length) {
        console.log("❌ YYB_SERVER 无有效账号（格式：地址@标识[#备注]）");
        return;
    }

    boxTop(`🛡️ ${APP.name} 每日任务`);
    boxLine("🕒 启动时间", new Date().toLocaleString("zh-CN"));
    boxLine("🔢 账号数量", `${valid.length} 个`);
    boxLine("💾 缓存", "token_caches/jsbhyzx_token_cache.json");
    boxLine("🌐 网络", "直连");
    boxBottom();

    const results = [];
    for (let i = 0; i < valid.length; i++) {
        const entry = parseEntry(valid[i]);
        const title = `标识 ${entry.ref || "-"}` + (entry.note ? `（${entry.note}）` : "");
        accountFrame(i + 1, valid.length, title, valid[i]);
        results.push(await runAccount(valid[i], i + 1, valid.length));
        hr();
        if (i < valid.length - 1) {
            const wait = 2 + Math.floor(Math.random() * 3);
            console.log(`   ⏳ 等待${wait}秒后执行下一个账号...`);
            await sleep(wait * 1000);
        }
    }

    console.log("");
    for (const r of results) {
        const title = `标识 ${r.ref || "-"}` + (r.note ? `（${r.note}）` : "");
        if (r.ok) {
            console.log(`✅ 【账号 ${r.index} · ${title}】`);
            console.log(`   🔐 [登录] ${r.loginSource === "缓存" ? "缓存复用" : "新登录"}`);
            console.log(`   👤 [用户] ${r.user || "-"}`);
            console.log(`   📅 [签到] ${r.signMessage || "-"}`);
            console.log(`   💰 [积分] ${r.pointsBefore} → ${r.pointsAfter}（${r.delta >= 0 ? "+" : ""}${r.delta}）`);
        } else {
            console.log(`❌ 【账号 ${r.index} · ${title}】`);
            console.log(`   🔐 [登录] ${r.loginSource || "-"}`);
            console.log(`   📅 [签到] ${r.signMessage || "-"}`);
            console.log(`   ⚠️ [失败] ${r.error || "未知错误"}`);
        }
    }

    const ok = results.filter((r) => r.ok).length;
    const fail = results.length - ok;
    const totalDelta = results.reduce((n, r) => n + (Number(r.delta) || 0), 0);
    boxTop(`🏁 🛡️ ${APP.name} 执行汇总`);
    boxLine("📊 执行结果", `成功 ${ok} / 失败 ${fail} / 共 ${results.length}`);
    boxLine("💰 积分总变化", `${totalDelta >= 0 ? "+" : ""}${totalDelta}`);
    boxLine("🕒 结束时间", new Date().toLocaleString("zh-CN"));
    boxBottom();

    if (NOTIFY_ON) {
        const content = results.map((r) => {
            const flag = r.ok ? "✅" : "❌";
            return `${flag} 账号${r.index} 🛡️ ${r.ref || "-"}\n`
                + `• 登录：${r.loginSource || "-"}\n`
                + `• 用户：${r.user || "-"}\n`
                + `• 签到：${r.signMessage || "-"}\n`
                + `• 积分：${r.pointsBefore} → ${r.pointsAfter}`
                + (r.ok ? "" : `\n⚠️ ${r.error || "未知错误"}`);
        }).join("\n\n");
        const title = `🛡️ ${APP.name} 任务完成`;
        const ql = await sendQingLongNotify(title, content);
        console.log(ql ? "   📮 [通知] 已调用青龙 notify" : "   ℹ️ [通知] 未找到青龙 notify 脚本");
        const pp = await sendPushPlus(title, content);
        console.log(pp ? "   📮 [通知] PushPlus 已发送" : "   ℹ️ [通知] 未配置 PLUSPLUS_TOKEN，跳过 PushPlus");
    } else {
        console.log("   ℹ️ [通知] JSBHYZX_NOTIFY=0，已关闭通知");
    }
}

main().catch((e) => console.log(`❌ [全局异常] ${e.stack || e.message || e}`));
