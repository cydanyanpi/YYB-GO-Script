// name: WPS
// cron: 32 7,19 * * *
const axios = require("axios");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
// ====================== YYB Go 账号（环境变量 YYB_SERVER = 地址@微信账号标识，多行） ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
const NOTIFY_ENABLED = String(process.env.WPS_NOTIFY || "1").trim() !== "0";
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
        original("   " + line);
        lines.push(line);
    };
    try { await fn(); } finally { console.log = original; }
    return lines;
}
async function getCode(server, appId = MINI_APP_ID) {
    const { server: parsedServer, ref } = parseYybGoEntry(server);
    if (!parsedServer || !ref) return null;
    const url = "http://" + parsedServer + "/wxapp/getCode";
    try {
        const { data } = await axios.post(url, { ref, app_id: appId }, { timeout: 20000, proxy: false });
        const code = data && data.data && data.data.result && data.data.result.code;
        if (!data || data.code !== 0 || !code) {
            console.log(parsedServer + " 获取code失败: " + JSON.stringify(data));
            return null;
        }
        console.log(parsedServer + " 获取code成功");
        return code;
    } catch (e) {
        console.log(parsedServer + " 获取code异常: " + e.message);
        return null;
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

const MINI_APP_ID = "wx2f333d84a103825d";
const ACCOUNT_PLUGIN_APPID = "wxe5f87d6a233b5aab";
const WPS_MPID = "app_op_act";
const CLIENT_TYPE = 1;
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "wps_token_cache.json");
try { fs.mkdirSync(path.dirname(TOKEN_CACHE_FILE), { recursive: true }); } catch (e) {}

const ACCOUNT_BASE = "https://account.wps.cn";
const PERSONAL_BUS = "https://personal-bus.wps.cn";
const PERSONAL_ACT = "https://personal-act.wps.cn";
const CLOCK_INFO = `${PERSONAL_BUS}/activity/clock_in/v1/info`;
const CLOCK_IN = `${PERSONAL_BUS}/activity/clock_in/v1/clock_in`;
const TASK_OUTLINE = `${PERSONAL_BUS}/activity/clock_in/v1/task/outline`;
const TASK_START_BROWSE = `${PERSONAL_BUS}/activity/clock_in/v1/task/start_browse`;
const TASK_FINISH_BROWSE = `${PERSONAL_BUS}/activity/clock_in/v1/task/finish_browse`;
const LOTTERY_TIMES = `${PERSONAL_BUS}/activity/clock_in/v1/task/lottery_times`;
const ACTIVITY_CONFIG = "https://personal-act.wpscdn.cn/srcapi/act/rubik-service/honeycomb-adapter/client/module-info?pid=113&mg_id=47736&id=48312";
const LOTTERY_PAGE = "https://personal-act.wps.cn/rubik2/portal/HD2024082815116866/YM2024082815122017";
const COMPONENT_ACTION = `${PERSONAL_ACT}/activity-rubik/activity/component_action`;
const LOTTERY_ACTIVITY = "HD2024082815116866";
const LOTTERY_PAGE_NO = "YM2024082815122017";
const LOTTERY_COMPONENT_NO = "ZJ2025092916516585";
const LOTTERY_COMPONENT_NODE_ID = "FN1766995952bvx3";

function readCache() {
  try {
    if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
    return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
  } catch {
    return {};
  }
}

function writeCache(cache) {
  try {
    fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
  } catch (e) {
    console.log(`token缓存写入失败: ${e.message || e}`);
  }
}

function md5(text) {
  return crypto.createHash("md5").update(String(text)).digest("hex");
}

function hmacSha256Hex(text, key) {
  return crypto.createHmac("sha256", key).update(String(text)).digest("hex");
}

function base64url(input) {
  return Buffer.from(input).toString("base64url");
}

function mask(value = "") {
  value = String(value);
  if (!value) return "";
  if (value.length <= 12) return `${value.slice(0, 3)}***`;
  return `${value.slice(0, 6)}***${value.slice(-6)}`;
}

function parseCookie(cookie = "") {
  if (!cookie || typeof cookie !== "string") return {};
  return Object.fromEntries(
    cookie
      .split(/;\s*/)
      .filter((v) => v.includes("="))
      .map((v) => [v.slice(0, v.indexOf("=")).trim(), v.slice(v.indexOf("=") + 1).trim()])
  );
}

function cookieHeader(cookies = {}) {
  return Object.entries(cookies)
    .filter(([, v]) => v !== undefined && v !== null && String(v) !== "")
    .map(([k, v]) => `${k}=${v}`)
    .join(";");
}

function mergeSetCookie(setCookie = [], current = {}) {
  const cookies = { ...current };
  for (const line of Array.isArray(setCookie) ? setCookie : [setCookie]) {
    const first = String(line || "").split(";")[0];
    if (!first.includes("=")) continue;
    const key = first.slice(0, first.indexOf("=")).trim();
    const value = first.slice(first.indexOf("=") + 1).trim();
    if (key) cookies[key] = value;
  }
  return cookies;
}

function parseAccount(raw) {
  const text = String(raw || "").trim();
  if (!text) return { openid: "", cookie: "", secret: "" };

  if (text.startsWith("{")) {
    try {
      const data = JSON.parse(text);
      return {
        openid: data.openid || data.openId || data.account || "",
        cookie: data.cookie || data.Cookie || "",
        secret: data.secret || data.jsrsasign_secret || "",
      };
    } catch {}
  }

  for (const sep of ["#", "|"]) {
    if (text.includes(sep)) {
      const [openid, cookie, secret] = text.split(sep);
      return { openid: openid.trim(), cookie: (cookie || "").trim(), secret: (secret || "").trim() };
    }
  }

  if (text.includes("wps_sid=") || text.includes("kso_sid=")) return { openid: "", cookie: text, secret: "" };
  return { openid: text, cookie: "", secret: "" };
}

function canonicalJson(data = {}) {
  const sorted = {};
  Object.keys(data || {})
    .sort()
    .forEach((key) => {
      sorted[key] = data[key];
    });
  return JSON.stringify(sorted);
}

function makeSignature(data, config = {}) {
  const key = config.key || "";
  const ss = config.ss || "";
  if (!key || !ss) return {};
  const date = new Date().toUTCString();
  const payload = `${key}${md5(canonicalJson(data))}${date}`;
  return {
    Date: date,
    Signature: hmacSha256Hex(payload, ss),
  };
}

function randomHex(bytes = 16) {
  return crypto.randomBytes(bytes).toString("hex");
}

function makePopToken(method, url, secret, cv = "") {
  if (!secret) return "";
  const header = base64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = {
    htm: String(method || "GET").toUpperCase(),
    htu: new URL(url).pathname,
    iat: Math.floor(Date.now() / 1000),
  };
  if (cv) body.cv = cv;
  const payload = base64url(JSON.stringify(body));
  const sig = crypto.createHmac("sha256", Buffer.from(secret)).update(`${header}.${payload}`).digest("base64url");
  return `${header}.${payload}.${sig}`;
}

function genEcKeyPair() {
  return crypto.generateKeyPairSync("ec", { namedCurve: "prime256v1" });
}

function signEc(privateKey, text) {
  return crypto
    .sign("sha256", Buffer.from(String(text)), {
      key: privateKey.export({ type: "pkcs8", format: "pem" }),
      dsaEncoding: "der",
    })
    .toString("base64url");
}

function deriveSecret(privateKey, serverJwkB64) {
  const jwk = JSON.parse(Buffer.from(serverJwkB64, "base64url").toString("utf8"));
  const publicKey = crypto.createPublicKey({ key: jwk, format: "jwk" });
  return crypto.diffieHellman({ privateKey, publicKey }).toString("base64url");
}

async function accountRequest(method, urlPath, { data = null, cookies = {}, secret = "" } = {}) {
  const url = `${ACCOUNT_BASE}${urlPath}`;
  const headers = {
    platform: "wx_mini",
    app_name: "account_wx_mini_plugin",
    Cookie: `csrf=1234567890${cookieHeader(cookies) ? `;${cookieHeader(cookies)}` : ""}`,
    "X-CSRFToken": "1234567890",
    "User-Agent": "Mozilla/5.0 MicroMessenger MiniProgramEnv/Windows",
    Referer: `https://servicewechat.com/${MINI_APP_ID}/249/page-frame.html`,
  };
  const pop = makePopToken(method, urlPath, secret, cookies.cv || "");
  if (pop) headers["X-Pop-Token"] = pop;
  const res = await axios({
    method,
    url,
    data,
    headers,
    timeout: 20000,
    validateStatus: () => true,
  });
  return { data: res.data, cookies: mergeSetCookie(res.headers["set-cookie"], cookies), status: res.status };
}

async function wpsRequest(method, url, { data = null, params = null, cookies = {}, secret = "", signed = false, clockConfig = {}, headers: extraHeaders = {} } = {}) {
  const csrf = "1234567890";
  const headers = {
    "X-CSRFToken": csrf,
    Cookie: `${cookieHeader(cookies)};csrf=${csrf}`,
    "User-Agent": "Mozilla/5.0 MicroMessenger MiniProgramEnv/Windows",
    Referer: `https://servicewechat.com/${MINI_APP_ID}/249/page-frame.html`,
    ...extraHeaders,
  };
  const pop = makePopToken(method, url, secret, cookies.cv || "");
  if (pop) headers["X-Pop-Token"] = pop;
  if (signed) Object.assign(headers, makeSignature(data || {}, clockConfig));

  const res = await axios({
    method,
    url,
    data,
    params,
    headers,
    timeout: 20000,
    validateStatus: () => true,
  });
  return { data: res.data, cookies: mergeSetCookie(res.headers["set-cookie"], cookies), status: res.status };
}

function assertOk(res, action) {
  if (!res || res.result !== "ok") {
    throw new Error(`${action}失败: ${res?.msg || res?.result || JSON.stringify(res)}`);
  }
  return res.data ?? res;
}

class Task {
  constructor(raw) {
        this.server = raw;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
    this.index = userIdx++;
    this.serverAddr = _yyb.server || "";
    this.ref = _yyb.ref || "";
    this.note = _yyb.note || "";
    const cleanRaw = this.serverAddr && this.ref ? `${this.serverAddr}@${this.ref}` : raw;
    const account = parseAccount(cleanRaw);
    this.openid = account.openid;
    this.cookies = parseCookie(account.cookie);
    this.secret = account.secret || "";
    this.uid = this.cookies.uid || "";
    this.clockConfig = {};
    this.cacheKey = this.serverAddr && this.ref ? `${this.serverAddr}|${this.ref}` : (this.openid || (account.cookie ? md5(account.cookie).slice(0, 16) : `account_${this.index}`));
    this.loginSource = ""; this.signMsg = "-"; this.nickname = "-"; this.userName = "-"; this.lotteryMsg = "-";
  }

  getCached() {
    const cache = readCache();
    if (cache[this.cacheKey]) return cache[this.cacheKey];
    const legacyKeys = [this.ref, `${this.serverAddr}@${this.ref}`, this.openid].filter(Boolean);
    for (const key of legacyKeys) {
      if (cache[key] && (cache[key].cookie || cache[key].secret)) {
        cache[this.cacheKey] = { ...cache[key], updatedAt: new Date().toISOString() };
        delete cache[key];
        writeCache(cache);
        console.log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」");
        return cache[this.cacheKey];
      }
    }
    return {};
  }

  saveCache(extra = {}) {
    const cache = readCache();
    cache[this.cacheKey] = {
      ...(cache[this.cacheKey] || {}),
      openid: this.openid || this.getCached().openid || "",
      uid: this.uid || this.cookies.uid || "",
      cookie: cookieHeader(this.cookies),
      secret: this.secret,
      ...extra,
      updatedAt: new Date().toISOString(),
    };
    writeCache(cache);
  }

  removeLogin() {
    const cache = readCache();
    if (cache[this.cacheKey]) {
      delete cache[this.cacheKey].cookie;
      delete cache[this.cacheKey].secret;
      writeCache(cache);
    }
    this.cookies = {};
    this.secret = "";
  }

  loadCache() {
    const cache = this.getCached();
    if (!this.openid && cache.openid) this.openid = cache.openid;
    if (!this.secret && cache.secret) this.secret = cache.secret;
    if (!Object.keys(this.cookies).length && cache.cookie) this.cookies = parseCookie(cache.cookie);
    this.uid = this.cookies.uid || cache.uid || this.uid || "";
  }

  async login() {
    if (!this.openid) throw new Error("缺少 openid，无法自动登录。可设置 wps=openid 或 wps=openid#Cookie");
    const authCode = await getCode(this.server, ACCOUNT_PLUGIN_APPID);
    const keyPair = genEcKeyPair();
    const body = {
      type: "wxapp",
      appid: ACCOUNT_PLUGIN_APPID,
      auth_code: authCode,
      public_key: base64url(JSON.stringify(keyPair.publicKey.export({ format: "jwk" }))),
      auth_code_sign: signEc(keyPair.privateKey, authCode),
      slv: "none",
    };
    const res = await accountRequest("POST", "/passport/secure/api/easy_login", { data: body });
    const data = assertOk(res.data, "WPS自动登录");
    if (data.further_action) throw new Error(`WPS登录需要额外操作: ${data.further_action}`);
    if (!data.jwk) throw new Error(`WPS登录未返回 jwk: ${JSON.stringify(res.data)}`);
    this.cookies = res.cookies;
    this.secret = deriveSecret(keyPair.privateKey, data.jwk);
    this.uid = data.user_id || this.cookies.uid || "";
    this.saveCache();
    console.log(`账号[${this.index}] WPS登录成功: ${mask(this.uid || this.cookies.wps_sid)}`);
  }

  async ensureLogin() {
    this.loadCache();
    if (this.cookies.kso_sid && this.cookies.wps_sid && this.secret) {
      this.loginSource = this.loginSource || "缓存";
      return;
    }
    await this.login();
  }

  async request(method, url, options = {}) {
    await this.ensureLogin();
    const res = await wpsRequest(method, url, {
      ...options,
      cookies: this.cookies,
      secret: this.secret,
      clockConfig: this.clockConfig,
    });
    this.cookies = res.cookies;
    this.saveCache();
    if (res.data?.msg === "empty wps_sid" || res.data?.result === "userNotLogin") {
      if (!this.openid) throw new Error("WPS登录态失效，且缺少 openid 无法刷新");
      console.log(`账号[${this.index}] WPS登录态失效，重新登录`);
      this.removeLogin();
      await this.login();
      this.loginSource = "重新登录";
      const retry = await wpsRequest(method, url, {
        ...options,
        cookies: this.cookies,
        secret: this.secret,
        clockConfig: this.clockConfig,
      });
      this.cookies = retry.cookies;
      this.saveCache();
      return retry.data;
    }
    return res.data;
  }

  async loadClockConfig() {
    const res = await axios.get(ACTIVITY_CONFIG, {
      timeout: 15000,
      validateStatus: () => true,
      headers: {
        "User-Agent": "Mozilla/5.0 MicroMessenger MiniProgramEnv/Windows",
        Referer: `https://servicewechat.com/${MINI_APP_ID}/249/page-frame.html`,
      },
    });
    if (res.data?.result === "ok" && res.data?.data?.value) {
      this.clockConfig = res.data.data.value;
      if (!this.clockConfig.key && this.clockConfig.s_key) this.clockConfig.key = this.clockConfig.s_key;
    }
  }

  async userInfo() {
    const data = assertOk(await this.request("POST", "https://account.wps.cn/p/auth/check"), "查询用户信息");
    this.uid = data.userid || data.id || this.uid || this.cookies.uid || "";
    this.saveCache({ nickname: data.nickname || data.username || "" });
    this.nickname = data.nickname || data.username || this.uid || "-";
    console.log(`账号[${this.index}] 用户: ${mask(this.nickname)}`);
  }

  async sign() {
    const body = { client_type: CLIENT_TYPE };
    const res = await this.request("POST", CLOCK_IN, { data: body, signed: true });
    if (res.result === "ok") {
      const data = res.data || {};
      console.log(`账号[${this.index}] 签到成功: 连续${data.continuous_days ?? data.continuousDays ?? "未知"}天`);
      this.signMsg = `签到成功，连续${data.continuous_days ?? data.continuousDays ?? "未知"}天`;
      return;
    }
    if (res.msg === "already clocked in today") {
      console.log(`账号[${this.index}] 今日已签到`);
      this.signMsg = "今日已签到";
      return;
    }
    throw new Error(`签到失败: ${res.msg || JSON.stringify(res)}`);
  }

  async clockInfo() {
    try {
      const res = await this.request("GET", CLOCK_INFO, {
        params: {
          client_type: CLIENT_TYPE,
          page_index: 0,
          page_size: 10,
        },
      });
      if (res.result === "ok") {
        const d = res.data || {};
        if (d.s_key) this.clockConfig.key = d.s_key;
        console.log(`账号[${this.index}] 签到信息: 连续${d.continuous_days ?? 0}天，累计${d.clock_in_total_num ?? "未知"}人打卡`);
      }
    } catch (e) {
      console.log(`账号[${this.index}] 查询签到信息失败: ${e.message || e}`);
    }
  }

  async getMainCode() {
    if (!this.openid) return "";
    return getCode(this.server, MINI_APP_ID);
  }

  async taskOutline() {
    const authCode = await this.getMainCode();
    if (!authCode) throw new Error("缺少 openid，无法获取任务 auth_code");
    const res = await this.request("GET", TASK_OUTLINE, {
      params: {
        mp_id: WPS_MPID,
        auth_code: authCode,
      },
    });
    return assertOk(res, "查询任务列表") || {};
  }

  async lotteryTimes() {
    const res = await this.request("GET", LOTTERY_TIMES, {
      params: {
        position: "wx_xcx_clock_activity",
      },
    });
    if (res.result === "ok") {
      console.log(`账号[${this.index}] 可抽奖次数: ${res.data ?? 0}`);
      return Number(res.data || 0);
    }
    console.log(`账号[${this.index}] 查询抽奖次数失败: ${res.msg || JSON.stringify(res)}`);
    return 0;
  }

  flattenTasks(outline = {}) {
    const tasks = [];
    const collect = (type, item) => {
      if (!item) return;
      if (Array.isArray(item)) {
        item.forEach((v) => collect(type, v));
      } else if (typeof item === "object") {
        tasks.push({ ...item, type });
      }
    };
    for (const [type, value] of Object.entries(outline)) collect(type, value);
    return tasks;
  }

  async doBrowseTask(task) {
    const authCode = await this.getMainCode();
    const clientType = task.client_type || "wechat";
    const startBody = {
      mp_id: WPS_MPID,
      auth_code: authCode,
      browse_app_id: task.app_id || MINI_APP_ID,
      client_type: clientType,
      version: "new",
    };
    if (clientType !== "wechat" && task.path) startBody.path = task.path;
    const start = await this.request("POST", TASK_START_BROWSE, { data: startBody });
    if (start.result !== "ok" && start.msg !== "任务已完成") {
      console.log(`账号[${this.index}] 浏览任务启动失败[${task.title || task.task_id || task.app_id}]: ${start.msg || JSON.stringify(start)}`);
      return false;
    }

    await await sleep(16000, 17000);

    const finish = await this.request("POST", TASK_FINISH_BROWSE, {
      data: {
        mp_id: WPS_MPID,
        auth_code: await this.getMainCode(),
        app_id: clientType === "wechat_web" ? MINI_APP_ID : task.app_id || MINI_APP_ID,
        client_type: clientType,
        path: clientType === "wechat_web" ? task.path || "" : "",
        version: "new",
        user_id: Number(this.uid || this.cookies.uid || 0),
      },
    });
    if (finish.result === "ok" || finish.msg === "任务已完成") {
      console.log(`账号[${this.index}] 浏览任务完成: ${task.title || task.task_id || task.app_id || task.path || ""}`);
      return true;
    }
    console.log(`账号[${this.index}] 浏览任务完成失败[${task.title || task.task_id || task.app_id}]: ${finish.msg || JSON.stringify(finish)}`);
    return false;
  }

  async browseTasks() {
    let outline;
    try {
      outline = await this.taskOutline();
    } catch (e) {
      console.log(`账号[${this.index}] 查询任务列表失败: ${e.message || e}`);
      return;
    }
    const tasks = this.flattenTasks(outline).filter((t) => t.type === "browse" && Number(t.status || 0) !== 1);
    if (!tasks.length) {
      console.log(`账号[${this.index}] 暂无待完成浏览任务`);
      return;
    }
    console.log(`账号[${this.index}] 待浏览任务: ${tasks.length}个`);
    for (const task of tasks) {
      try {
        await this.doBrowseTask(task);
      } catch (e) {
        console.log(`账号[${this.index}] 浏览任务异常: ${e.message || e}`);
      }
    }
  }

  async tryLotteryOnce(index) {
    const actCsrf = randomHex(16);
    const body = {
      component_uniq_number: {
        activity_number: LOTTERY_ACTIVITY,
        page_number: LOTTERY_PAGE_NO,
        component_number: LOTTERY_COMPONENT_NO,
        component_node_id: LOTTERY_COMPONENT_NODE_ID,
        filter_params: {},
      },
      component_type: 45,
      component_action: "lottery_v2.exec",
      lottery_v2: {
        session_id: 1,
      },
    };
    const cookies = { ...this.cookies, act_csrf_token: actCsrf };
    const res = await wpsRequest("POST", COMPONENT_ACTION, {
      data: body,
      cookies,
      secret: this.secret,
      headers: {
        "Content-Type": "application/json",
        "X-Act-Csrf-Token": actCsrf,
        Referer: LOTTERY_PAGE,
      },
    }).catch((e) => ({ data: { result: "error", msg: e.message || String(e) }, cookies: this.cookies }));
    this.cookies = mergeSetCookie([], { ...this.cookies, ...res.cookies });
    this.saveCache();

    const result = res.data;
    if (result?.result === "ok" && result.data?.lottery_v2?.success) {
      const reward = result.data.lottery_v2;
      const rewardText = reward.reward_name || reward.reward_type || JSON.stringify(reward).slice(0, 120);
      console.log(`   🎁 [抽奖] 第 ${index} 次成功：${rewardText}`);
      if (!this._lotteryRewards) this._lotteryRewards = [];
      this._lotteryRewards.push(String(rewardText));
      return true;
    }
    const detail = result?.data?.lottery_v2?.error_code ? `错误码${result.data.lottery_v2.error_code}` : result?.msg || JSON.stringify(result);
    console.log(`   ⚠️ [抽奖] 第 ${index} 次失败：${brief(detail, 60)}`);
    return false;
  }

  async lottery() {
    this._lotteryRewards = [];
    let count = 0;
    try {
      count = await this.lotteryTimes();
    } catch (e) {
      console.log(`   ⚠️ [抽奖] 查询次数失败：${brief(e.message || e, 50)}`);
    }
    const limit = Math.min(Number(count) || 0, Number(process.env.wps_lottery_limit || 5));
    console.log(`   🎁 [抽奖] 今日可抽 ${count} 次（本次最多 ${limit} 次）`);
    let done = 0;
    for (let i = 1; i <= limit; i++) {
      const ok = await this.tryLotteryOnce(i);
      if (!ok) break;
      done += 1;
      await sleep(1000, 1800);
    }
    if (limit === 0) this.lotteryMsg = "今日无抽奖次数";
    else if (done === 0) this.lotteryMsg = "未抽到奖品（首次即失败）";
    else this.lotteryMsg = `抽 ${done} 次：${this._lotteryRewards.join(" / ")}`;
  }

  async run() {
    const title = `标识 ${this.ref || this.openid || "-"}` + (this.note ? `（${this.note}）` : "");
    accountFrame(this.index, SERVERS.length, title, this.server || this.cacheKey);
    this.logs = [];
    try {
      this.logs = await captureLogs(async () => {
        const hadCache = !!this.getCached().cookie;
        console.log(hadCache ? "💾 [缓存] 复用已保存的登录 Cookie" : "🆕 [登录] 缓存为空，准备登录");
        await this.ensureLogin();
        await this.loadClockConfig();
        await this.userInfo();
        console.log("✅ [校验] 登录凭证校验通过（用户信息接口）");
        console.log(`🔐 [登录] 登录成功（${mask(this.nickname)}，来源${this.loginSource || "新登录"}）`);
        await this.clockInfo();
        await this.sign();
        await this.browseTasks();
        await this.lottery();
      });
      this.success = true;
      console.log("   ✅ [完成] 该账号任务执行完成");
    } catch (e) {
      this.success = false;
      this.error = brief(e && e.message ? e.message : e);
      console.log(`   ❌ [账号] 任务执行失败: ${this.error}`);
    }
    return this;
  }
}

async function sendQingLongNotify(title, content) {
  const candidates = ["/ql/data/scripts/notify.js", "/ql/scripts/notify.js", path.join(__dirname, "notify.js"), path.join(__dirname, "SendNotify.js")];
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

function buildNotify(results) {
  const ok = results.filter((r) => r.success).length;
  const lines = ["🖥️ WPS 打卡任务结果", "━".repeat(20), `🏁 总结：${ok} 成功 / ${results.length - ok} 失败`, `🕒 时间：${new Date().toLocaleString("zh-CN")}`, "━".repeat(20)];
  for (const r of results) {
    lines.push("");
    lines.push(`${r.success ? "✅" : "❌"} 账号${r.index} ${mask(r.ref || r.openid || "-")}`);
    lines.push(`🔐 登录：${r.loginSource || "-"}`);
    lines.push(`👤 用户：${r.nickname || "-"}`);
    lines.push(`📝 签到：${r.signMsg || "-"}`);
    lines.push(`🎁 抽奖：${r.lotteryMsg || "-"}`);
    if (!r.success) lines.push(`⚠️ 原因：${r.error || "未知错误"}`);
    lines.push("━".repeat(20));
  }
  return lines.join("\n");
}

(async () => {
  if (!SERVERS.length) {
    console.log("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识[#备注]，多账号换行分隔）");
    return;
  }
  const valid = SERVERS.filter((item) => item.includes("@"));
  if (!valid.length) {
    console.log("❌ YYB_SERVER 无有效账号（格式：地址@标识[#备注]）");
    return;
  }
  SERVERS.length = 0;
  SERVERS.push(...valid);
  userIdx = 1;

  boxTop("🖥️ WPS 每日打卡");
  boxLine("🕒 启动时间", new Date().toLocaleString("zh-CN"));
  boxLine("🔢 账号数量", `${SERVERS.length} 个`);
  boxLine("💾 缓存", "wps_token_cache.json");
  boxLine("🌐 网络", "直连");
  boxBottom();

  const results = [];
  for (const account of SERVERS) {
    try {
      const task = new Task(account);
      results.push(await task.run());
    } catch (e) {
      const entry = parseYybGoEntry(account);
      console.log(`   ❌ [主程序] ${brief(e && e.message ? e.message : e)}`);
      results.push({ index: userIdx++, ref: entry.ref, openid: entry.ref, success: false, loginSource: "", nickname: "-", signMsg: "-", error: brief(e && e.message ? e.message : e) });
    }
    hr();
    if (results.length < SERVERS.length) {
      console.log("   ⏳ 等待2秒后执行下一个账号...");
      await sleep(2000);
    }
  }

  console.log("");
  for (const r of results) {
    console.log(`${r.success ? "✅" : "❌"} 【账号 ${r.index} · 标识 ${r.ref || r.openid || "-"}】`);
    console.log(`   🔐 [登录] ${r.loginSource || "-"}`);
    console.log(`   👤 [用户] ${r.nickname || "-"}`);
    console.log(`   📝 [签到] ${r.signMsg || "-"}`);
    console.log(`   🎁 [抽奖] ${r.lotteryMsg || "-"}`);
    if (!r.success) console.log(`   ⚠️ [失败] ${r.error || "未知错误"}`);
  }

  const ok = results.filter((r) => r.success).length;
  boxTop("🏁 WPS 执行汇总");
  boxLine("📊 执行结果", `成功 ${ok} / 失败 ${results.length - ok} / 共 ${results.length}`);
  boxLine("🕒 结束时间", new Date().toLocaleString("zh-CN"));
  boxBottom();

  if (NOTIFY_ENABLED) {
    const content = buildNotify(results);
    const sent = await sendQingLongNotify("🖥️ WPS 打卡任务完成", content);
    console.log(sent ? "   📮 [通知] 已调用青龙 notify" : "   ℹ️ [通知] 未找到青龙 notify 脚本");
    const token = process.env.PLUSPLUS_TOKEN || "";
    if (token) {
      try {
        await axios.post("http://www.pushplus.plus/send", { token, title: "🖥️ WPS 打卡任务完成", content, template: "txt" }, { timeout: 15000, proxy: false });
        console.log("   📮 [通知] PushPlus 已推送");
      } catch (e) {
        console.log(`   ⚠️ [通知] PushPlus 推送失败: ${brief(e.message)}`);
      }
    }
  } else {
    console.log("   ℹ️ [通知] WPS_NOTIFY=0，已关闭通知");
  }
})()
  .catch((e) => console.log(`脚本异常: ${e.message || e}`))
