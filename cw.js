#!/usr/bin/env node
// name:创维小程序
/**
 * 创维小程序
 * cron: 39 9,16 * * *
 *
 * 流程：
 * YYB_SERVER -> /wxapp/getCode -> /v2/user/exchange -> ticket -> /v2/user/signin -> Authorization
 * -> 固定5个任务：/userScoreStatusInfo + /v1/complete-task/{taskCode}
 * -> 额外签到（兑吧连续签到）：index-nav(register) -> duiba-nologin -> autoLogin -> doSign
 *
 * 环境变量：
 * - YYB_SERVER              必填；YYB-Go-Enhanced地址@账号标识，多账号每行一条
 * - YYB_API_KEY / YYB_PROTOCOL_TOKEN  可选，启用协议鉴权时配置
* - CHUANGW_APPID           默认 wxff438d3c60c63fb6
 * - CHUANGW_APP_PATH        默认 /pages/login/login
 * - CHUANGW_RUN_TASKS       默认1，0=只登录拿token
 * - CHUANGW_NOTIFY          默认1，0=关闭青龙 notify.py 汇总通知
 */

'use strict';

const crypto = require('crypto');
const vm = require('vm');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const ENV_NAME = 'chuangw';
const UC_API = 'https://uc-api.skyallhere.com/miniprogram/api';
const UC_ADMIN = 'https://uc-admin.skyallhere.com/api';

// 缓存：脚本目录 token_caches/，按 地址|标识 隔离，不设固定过期
const CACHE_DIR = path.join(__dirname, 'token_caches');
const CACHE_FILE = path.join(CACHE_DIR, 'cw_token_cache.json');

const APPID = process.env.CHUANGW_APPID || 'wxff438d3c60c63fb6';
const APP_VERSION = process.env.CHUANGW_APP_VERSION || '8.0.70';
const SDK_VERSION = process.env.CHUANGW_SDK_VERSION || '3.15.2';
const APP_PATH = process.env.CHUANGW_APP_PATH || '/pages/login/login';
const APP_SYSTEM = process.env.CHUANGW_APP_SYSTEM || 'iOS 26.1';
const APP_MODEL = process.env.CHUANGW_APP_MODEL || 'iPhone 15 pro max<iPhone16,2>';

const RUN_TASKS = (process.env.CHUANGW_RUN_TASKS || '1') !== '0';
const NOTIFY_ENABLED = (process.env.CHUANGW_NOTIFY || '1') !== '0';
// 固定任务：5个（不走环境变量）
const TASK_CODES = ['TS00016', 'TS00210', 'TS00203', 'TS00211', 'TS00213'];
const TASK_NAME_MAP = {
  TS00016: '每日签到',
  TS00210: '浏览商品详情',
  TS00201: '购买商品',
  TS00100: '添加产品',
  TS00202: '产品评价',
  TS00203: '分享商品',
  TS00211: '浏览商品详情(成长值)',
  TS00213: '浏览图片详情',
};

// 源码里硬编码私钥（calcSystemSignAndParam）
const TASK_SIGN_PRIVATE_KEY = `-----BEGIN RSA PRIVATE KEY-----
MIIBPAIBAAJBAMJrqTwwvDRo/NP3Pjq0wfeHtfAcwRu5vk5yTfdGmKAAqG9M9Bu8
COIBN/B0lGUcUx4HP4eIvK17HoIut8shun8CAwEAAQJAXVNWymjOfw4ChzFAsud/
0HVZlWgIHmn7+yYNXOyLaQnv8I7GTrVe85lnAvcmboSvpr5KFGzhY0KDpAnCcDsh
QQIhAPzyeP4ncY7cLkftHPUTSg7Mkve/gJUFZN7q2pW0KEGfAiEAxMRcDf8yqSXP
VfUmJpnzranrFRIAs9Eqi1jzbB4KmyECIQCu2hJHZg66uXuInuEQjKf5+PJzLj79
RIBJFEHLkIDvcwIhALvLwSQmvd5MVN9wU1IiOz0zYEfC3+K/LkDCy8kTvwGhAiEA
8OKljQOdOhQcWver4UsvF5jwGPC5CqkPq/not9YLtU4=
-----END RSA PRIVATE KEY-----`;

const fetchFn = globalThis.fetch || ((...args) => import('node-fetch').then(({ default: f }) => f(...args)));

function normalizeServer(raw) {
  const value = String(raw || '').trim();
  if (!value) return '';
  return (/^https?:\/\//i.test(value) ? value : `http://${value}`).replace(/\/+$/, '');
}

function parseAccounts(raw) {
  const accounts = [];
  String(raw || '').split(/\r?\n/).forEach((line, index) => {
    const value = line.trim();
    if (!value) return;
    const at = value.lastIndexOf('@');
    if (at <= 0 || at === value.length - 1) {
      throw new Error(`YYB_SERVER第${index + 1}行格式错误，应为 地址@账号标识`);
    }
    const server = normalizeServer(value.slice(0, at));
    const refPart = value.slice(at + 1).trim();
    const hash = refPart.indexOf('#');
    const ref = (hash >= 0 ? refPart.slice(0, hash) : refPart).trim();
    const note = (hash >= 0 ? refPart.slice(hash + 1) : '').trim();
    if (!server || !ref) throw new Error(`YYB_SERVER第${index + 1}行地址或账号标识为空`);
    accounts.push({ server, ref, note });
  });
  return accounts;
}

const LOG_WIDTH = 48;
const BOX_WIDTH = 48;
const BOX_INNER = 46;

function displayWidth(str) {
  let width = 0;
  for (const ch of String(str ?? '')) {
    const code = ch.codePointAt(0);
    if (code === 0xfe0f || code === 0xfe0e || code === 0x200d) continue;
    width += code > 0xff ? 2 : 1;
  }
  return width;
}

function padWidth(str, width) {
  const text = String(str ?? '');
  const gap = width - displayWidth(text);
  return text + ' '.repeat(Math.max(0, gap));
}

function nowText() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function boxTop(title) {
  console.log('');
  console.log('╔' + '═'.repeat(BOX_WIDTH) + '╗');
  console.log('║  ' + padWidth(title, BOX_INNER) + '║');
}

function boxLine(label, value) {
  console.log('║  ' + padWidth(`${label}: ${value}`, BOX_INNER) + '║');
}

function boxBottom() {
  console.log('╚' + '═'.repeat(BOX_WIDTH) + '╝');
}

function accountFrame(idx, total, title, source) {
  console.log('');
  console.log('┌' + '─'.repeat(BOX_WIDTH) + '┐');
  console.log('│  ' + padWidth(`🧩 账号 ${idx} / ${total}　${title}`, BOX_INNER) + '│');
  console.log('│  ' + padWidth(`🔗 来源: ${source}`, BOX_INNER) + '│');
  console.log('└' + '─'.repeat(BOX_WIDTH) + '┘');
}

function hr(char = '─') {
  console.log(char.repeat(LOG_WIDTH));
}

function truncText(s, max = 96) {
  const str = String(s ?? '');
  if (str.length <= max) return str;
  return `${str.slice(0, max - 1)}…`;
}

function wrapText(s, max = 86) {
  const str = String(s ?? '').replace(/\n+/g, ' ').trim();
  if (!str) return [''];
  const lines = [];
  for (let i = 0; i < str.length; i += max) lines.push(str.slice(i, i + max));
  return lines;
}

function section(title) {
  console.log(`\n🔹 [${title}]`);
}

function logWithIcon(icon, msg) {
  const lines = wrapText(msg);
  lines.forEach((line, idx) => {
    if (idx === 0) console.log(`${icon} ${line}`);
    else console.log(`   ${line}`);
  });
}

function logInfo(msg) {
  logWithIcon('ℹ️', msg);
}

function logOk(msg) {
  logWithIcon('✅', msg);
}

function logWarn(msg) {
  logWithIcon('⚠️', msg);
}

function logErr(msg) {
  logWithIcon('❌', msg);
}

function logSep(char = '─') {
  console.log(char.repeat(LOG_WIDTH));
}

function endSection() {
  console.log('');
}

function accountDivider() {
  console.log('');
  console.log('-'.repeat(48));
}

function maskMiddle(s, left = 10, right = 8) {
  const str = String(s || '');
  if (!str) return '';
  if (str.length <= left + right + 3) return str;
  return `${str.slice(0, left)}...${str.slice(-right)}`;
}

function brief(v, max = 54) {
  if (v === undefined || v === null) return '';
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return truncText(s, max);
}

function taskName(code) {
  return TASK_NAME_MAP[code] || '任务';
}

function taskStateText(v) {
  return Number(v) === 1 ? '已完成' : '未完成';
}

function isWxidLike(s) {
  const x = String(s || '').trim();
  if (!x) return false;
  if (x.startsWith('wx:')) return true;
  if (x.startsWith('wxid_')) return true;
  return /^[a-zA-Z0-9_-]{4,64}$/.test(x) && !x.includes('.');
}

function decodeJwtPayload(token) {
  try {
    const p = String(token || '').split('.');
    if (p.length < 2) return null;
    const b64 = p[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    return JSON.parse(Buffer.from(padded, 'base64').toString('utf8'));
  } catch {
    return null;
  }
}

// ---- 缓存 -------------------------------------------------------------- //
function cacheKey(server, ref) {
  return `${server}|${ref}`;
}

function readCache() {
  try {
    if (!fs.existsSync(CACHE_FILE)) return {};
    const data = JSON.parse(fs.readFileSync(CACHE_FILE, 'utf8'));
    return data && typeof data === 'object' ? data : {};
  } catch {
    return {};
  }
}

function writeCache(cache) {
  try {
    fs.mkdirSync(CACHE_DIR, { recursive: true });
    fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2), 'utf8');
  } catch (e) {
    logWarn(`缓存写入失败（不影响本次执行）：${e.message || e}`);
  }
}

function saveTokenCache(ck, token) {
  const cache = readCache();
  cache[ck] = { token, updatedAt: nowText() };
  writeCache(cache);
}

function dropTokenCache(ck) {
  const cache = readCache();
  if (ck in cache) {
    delete cache[ck];
    writeCache(cache);
  }
}

function jwtExpired(token, skewSec = 60) {
  const p = decodeJwtPayload(token) || {};
  const exp = Number(p.exp || 0);
  if (!exp) return false;      // 拿不到 exp 就不预判，交给接口验证
  return Date.now() / 1000 >= exp - skewSec;
}

// ---- 登录态失效判定 ----------------------------------------------------- //
// 只认明确的凭证类提示，避免把「活动已过期」这类业务错误误判成登录失效
const AUTH_HINTS = [
  'token', '登录', '未登录', '授权', '凭证', 'credential',
  'unauthorized', '401', '403', '会话',
];

function authError(message) {
  const e = new Error(message);
  e.authFailed = true;
  return e;
}

function isAuthFailure(code, msg) {
  const c = Number(code);
  if (c === 401 || c === 403) return true;
  const text = String(msg || '').toLowerCase();
  if (!text) return false;
  return AUTH_HINTS.some((hint) => text.includes(hint));
}

function assertOk(ret, label, { authStrict = false } = {}) {
  const code = ret?.code;
  if (Number(code) === 0) return ret;
  const msg = String(ret?.msg || ret?.message || '');
  if (isAuthFailure(code, msg)) {
    throw authError(`${label}：${msg || `code=${code}`}`);
  }
  if (authStrict) throw new Error(`${label}：${msg || `code=${code}`}`);
  return ret;
}

function fmtTs(ts) {
  const d = new Date(Number(ts) * 1000);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' });
}

function printTokenInfo(token) {
  const p = decodeJwtPayload(token) || {};
  const iat = Number(p.iat || 0);
  const exp = Number(p.exp || 0);
  if (!iat || !exp) return;
  const validM = Math.floor((exp - iat) / 60);
  const leftM = Math.max(0, Math.floor((exp - Math.floor(Date.now() / 1000)) / 60));
  logInfo(`Token有效期≈${validM}分钟，剩余≈${leftM}分钟`);
  logInfo(`签发时间: ${fmtTs(iat)}`);
  logInfo(`过期时间: ${fmtTs(exp)}`);
}

function commonHeaders(extra = {}) {
  return {
    'Content-Type': 'application/json',
    'App-Version': APP_VERSION,
    'App-Sdkversion': SDK_VERSION,
    'App-System': APP_SYSTEM,
    'App-Model': APP_MODEL,
    'App-Path': APP_PATH,
    'User-Agent': 'Mozilla/5.0 MicroMessenger MiniProgram',
    ...extra,
  };
}

function miniH5UA() {
  return `Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.70(0x1800463a) NetType/WIFI Language/zh_CN miniProgram/${APPID}`;
}

function safeJsonParse(text, fallback = null) {
  try { return JSON.parse(text); } catch { return fallback; }
}

function getSetCookieList(headers) {
  if (!headers) return [];
  if (typeof headers.getSetCookie === 'function') return headers.getSetCookie();
  if (typeof headers.raw === 'function') {
    const raw = headers.raw();
    if (raw && Array.isArray(raw['set-cookie'])) return raw['set-cookie'];
  }
  const single = headers.get ? headers.get('set-cookie') : '';
  if (!single) return [];
  return String(single).split(/,(?=[^;,]+=)/g).map(s => s.trim()).filter(Boolean);
}

function setCookieToJar(jar, setCookieLine) {
  const line = String(setCookieLine || '');
  const first = line.split(';')[0] || '';
  const idx = first.indexOf('=');
  if (idx <= 0) return;
  const k = first.slice(0, idx).trim();
  const v = first.slice(idx + 1).trim();
  if (!k) return;
  jar[k] = v;
}

function cookieHeaderFromJar(jar) {
  return Object.entries(jar || {}).map(([k, v]) => `${k}=${v}`).join('; ');
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function genNonce() {
  return crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

async function httpJson(url, { method = 'GET', headers = {}, body, timeout = 20000 } = {}) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(new Error('timeout')), timeout);
  try {
    const resp = await fetchFn(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: c.signal,
    });
    const text = await resp.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
    if (!resp.ok) {
      const detail = `${method} ${url} -> ${resp.status} ${text.slice(0, 400)}`;
      // 401/403 视为登录态失效，供上层清缓存重登
      if (resp.status === 401 || resp.status === 403) throw authError(detail);
      throw new Error(detail);
    }
    return data;
  } finally {
    clearTimeout(t);
  }
}

async function httpText(url, { method = 'GET', headers = {}, body, timeout = 20000, jar = null, redirect = 'manual' } = {}) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(new Error('timeout')), timeout);
  try {
    const reqHeaders = { ...headers };
    if (jar && Object.keys(jar).length) {
      reqHeaders.Cookie = cookieHeaderFromJar(jar);
    }
    const resp = await fetchFn(url, {
      method,
      headers: reqHeaders,
      body,
      redirect,
      signal: c.signal,
    });

    if (jar) {
      const setCookies = getSetCookieList(resp.headers);
      for (const line of setCookies) setCookieToJar(jar, line);
    }

    const text = await resp.text();
    const isRedirect = resp.status >= 300 && resp.status < 400;
    if (!resp.ok && !isRedirect) {
      throw new Error(`${method} ${url} -> ${resp.status} ${text.slice(0, 400)}`);
    }
    return { status: resp.status, headers: resp.headers, text, finalUrl: resp.url };
  } finally {
    clearTimeout(t);
  }
}

function _yybAuthHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    const token = String(process.env.YYB_API_KEY || '').trim() || String(process.env.YYB_PROTOCOL_TOKEN || '').trim();
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
}

async function getWxCode(server, ref, appid = APPID) {
  const ret = await httpJson(`${server}/wxapp/getCode`, {
    method: 'POST',
    headers: _yybAuthHeaders(),
    body: { ref, app_id: appid },
  });
  const code = ret?.data?.result?.code || '';
  if (Number(ret?.code) === 0 && code) return code;
  throw new Error(`YYB-Go-Enhanced取code失败: ${brief(ret?.message || ret?.msg || ret, 160)}`);
}

function scoreSnapshot(profile) {
  const base = profile?.data?.baseInfo || {};
  const current = Number(base.userScore);
  const today = Number(base.todayScore);
  return {
    current: Number.isFinite(current) ? current : null,
    today: Number.isFinite(today) ? today : null,
  };
}

function scoreSummary(before, after) {
  const delta = before.current !== null && after.current !== null ? after.current - before.current : null;
  const deltaText = delta === null ? '接口未返回' : `${delta >= 0 ? '+' : ''}${delta}`;
  const todayText = after.today === null ? '接口未返回' : String(after.today);
  const currentText = after.current === null ? '接口未返回' : String(after.current);
  return `💰 本次增加 ${deltaText}｜今日累计 ${todayText}｜当前积分 ${currentText}`;
}

async function exchangeByCode(code) {
  const ret = await httpJson(`${UC_API}/v2/user/exchange`, {
    method: 'POST',
    headers: commonHeaders(),
    body: { code },
  });
  const ticket = ret?.data?.ticket || (typeof ret?.data === 'string' ? ret.data : '');
  if ((ret?.code === 0 || ret?.code === '0') && ticket) return ticket;
  throw new Error(`exchange失败(code=${ret?.code ?? '-'}): ${truncText(ret?.msg || '未知错误', 100)}`);
}

async function signinByTicket(ticket) {
  const ret = await httpJson(`${UC_API}/v2/user/signin`, {
    method: 'POST',
    headers: commonHeaders(),
    body: { ticket },
  });
  const token = ret?.data?.token || '';
  if ((ret?.code === 0 || ret?.code === '0') && token) return token;
  const error = new Error(`signin失败(code=${ret?.code ?? '-'}): ${truncText(ret?.msg || '未知错误', 100)}`);
  if (Number(ret?.code) === 19998 && String(ret?.msg || '').includes('用户不存在')) error.accountSkipped = true;
  throw error;
}

async function getUserByToken(token) {
  const ret = await httpJson(`${UC_API}/v1/get-user`, {
    method: 'GET',
    headers: commonHeaders({ Authorization: `Bearer ${token}` }),
  });
  assertOk(ret, '/v1/get-user', { authStrict: true });
  return ret;
}

async function getWdStatus(token) {
  const ret = await httpJson(`${UC_ADMIN}/userEquityScoreLog/miniProgram/userScoreStatusInfo`, {
    method: 'GET',
    headers: commonHeaders({
      Authorization: `Bearer ${token}`,
      isNoToken: '1',
      'App-Path': '/pages-user/get-wd/get-wd',
    }),
  });
  assertOk(ret, 'userScoreStatusInfo');
  const arr = Array.isArray(ret?.data) ? ret.data : [];
  const map = {};
  for (const x of arr) map[x.taskLabel] = Number(x.isComplete || 0);
  return { raw: ret, map };
}

async function getIndexNav(token) {
  const ret = await httpJson(`${UC_API}/v1/index-nav`, {
    method: 'GET',
    headers: commonHeaders({
      Authorization: `Bearer ${token}`,
      'App-Path': '/pages/user/user',
    }),
  });
  assertOk(ret, 'index-nav', { authStrict: true });
  return ret;
}

async function getDuibaAutoLoginUrl(token) {
  const nav = await getIndexNav(token);
  const tokenUrl = nav?.data?.register || '';
  if (!tokenUrl) {
    throw new Error('index-nav未返回register签到入口');
  }
  const ret = await httpJson(tokenUrl, {
    method: 'GET',
    headers: commonHeaders({
      Authorization: `Bearer ${token}`,
      'App-Path': '/pages/user/user',
    }),
  });
  const autoLoginUrl = typeof ret?.data === 'string' ? ret.data : '';
  if (!autoLoginUrl) throw new Error(`duiba-nologin失败: ${JSON.stringify(ret)}`);
  return { tokenUrl, autoLoginUrl };
}

function extractScriptBlocks(html) {
  const out = [];
  const re = /<script[^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(String(html || '')))) {
    out.push(m[1] || '');
  }
  return out;
}

function decodeObfuscatedEvalScript(scriptCode, context = {}) {
  let generated = '';
  const sandbox = {
    window: {},
    location: { host: '74367-1-activity.m.dexfu.cn' },
    XMLHttpRequest: function () {},
    eval: (s) => {
      generated = String(s || '');
      return s;
    },
    ...context,
  };
  vm.createContext(sandbox);
  vm.runInContext(String(scriptCode || ''), sandbox, { timeout: 2500 });
  return generated;
}

function extractDuibaKeyFromPageHtml(pageHtml) {
  try {
    const scripts = extractScriptBlocks(pageHtml);
    const target = scripts.find(s => s.includes('获取token') || s.includes('/chw/ctoken/getToken'));
    if (!target) return 'e7a76d7t';
    const generated = decodeObfuscatedEvalScript(target);
    const m = generated.match(/var\s+key\s*=\s*['"]([^'"]+)['"]/);
    return m?.[1] || 'e7a76d7t';
  } catch {
    return 'e7a76d7t';
  }
}

function extractWindowAssignments(code) {
  const map = {};
  const re = /window\[['"]([^'"]+)['"]\]\s*=\s*['"]([^'"]*)['"]/g;
  let m;
  while ((m = re.exec(String(code || '')))) {
    map[m[1]] = m[2];
  }
  return map;
}

function resolveDuibaCtoken(tokenScript, keyHint = '') {
  let generated = '';
  try {
    generated = decodeObfuscatedEvalScript(String(tokenScript || ''), { window: {} });
  } catch {
    generated = '';
  }

  if (generated) {
    try {
      const sandbox = { window: {} };
      vm.createContext(sandbox);
      vm.runInContext(generated, sandbox, { timeout: 1500 });
      const win = sandbox.window || {};
      if (keyHint && typeof win[keyHint] === 'string') return win[keyHint];
      for (const v of Object.values(win)) {
        if (typeof v === 'string' && /^[a-zA-Z0-9]{4,24}$/.test(v)) return v;
      }
    } catch {
      // ignore
    }
  }

  const map = extractWindowAssignments(generated || tokenScript);
  if (keyHint && typeof map[keyHint] === 'string') return map[keyHint];
  for (const v of Object.values(map)) {
    if (typeof v === 'string' && /^[a-zA-Z0-9]{4,24}$/.test(v)) return v;
  }
  return '';
}

function getRedirectLocation(headers, baseUrl) {
  const loc = headers?.get ? headers.get('location') : '';
  if (!loc) return '';
  try { return new URL(loc, baseUrl).toString(); } catch { return loc; }
}

async function getDuibaIndexInfo(origin, signOperatingId, pageUrl, jar, ua) {
  const url = `${origin}/sign/component/index?${new URLSearchParams({
    signOperatingId: String(signOperatingId),
    preview: 'false',
    _: String(Date.now()),
  }).toString()}`;
  const resp = await httpText(url, {
    method: 'GET',
    jar,
    redirect: 'manual',
    headers: {
      Accept: 'application/json, text/plain, */*',
      Referer: pageUrl,
      'User-Agent': ua,
    },
  });
  return safeJsonParse(resp.text, {});
}

async function getDuibaCtoken(origin, pageUrl, jar, ua, keyHint) {
  const resp = await httpText(`${origin}/chw/ctoken/getToken`, {
    method: 'POST',
    jar,
    redirect: 'manual',
    headers: {
      Accept: '*/*',
      'Content-Type': 'application/x-www-form-urlencoded',
      Origin: origin,
      Referer: pageUrl,
      'User-Agent': ua,
    },
    body: `timestamp=${Date.now()}`,
  });
  const data = safeJsonParse(resp.text, {});
  if (!data?.success || !data?.token) {
    throw new Error(`ctoken接口失败: ${String(resp.text).slice(0, 200)}`);
  }
  const token = resolveDuibaCtoken(data.token, keyHint);
  if (!token) throw new Error('ctoken解析失败');
  return token;
}

async function doDuibaSign(origin, signOperatingId, signToken, pageUrl, jar, ua) {
  const resp = await httpText(`${origin}/sign/component/doSign?_=${Date.now()}`, {
    method: 'POST',
    jar,
    redirect: 'manual',
    headers: {
      Accept: 'application/json, text/plain, */*',
      'Content-Type': 'application/x-www-form-urlencoded',
      Origin: origin,
      Referer: pageUrl,
      'User-Agent': ua,
    },
    body: new URLSearchParams({
      signOperatingId: String(signOperatingId),
      token: String(signToken),
    }).toString(),
  });
  return safeJsonParse(resp.text, {});
}

async function getDuibaSignResult(origin, orderNum, pageUrl, jar, ua) {
  const url = `${origin}/sign/component/signResult?orderNum=${encodeURIComponent(String(orderNum))}&_=${Date.now()}`;
  const resp = await httpText(url, {
    method: 'GET',
    jar,
    redirect: 'manual',
    headers: {
      Accept: 'application/json, text/plain, */*',
      Referer: pageUrl,
      'User-Agent': ua,
    },
  });
  return safeJsonParse(resp.text, {});
}

function calcTaskSign(taskCode, nonce, timestamp, snCode = '') {
  const data = { taskCode, nonce, timestamp: String(timestamp) };
  if (snCode) data.snCode = snCode;

  const keys = Object.keys(data).sort((a, b) => (a > b ? 1 : -1));
  let preSign = '';
  for (const k of keys) {
    if (k !== 'taskCode' && k !== 'snCode') preSign += `${k}=${data[k]}&`;
  }

  const signer = crypto.createSign('RSA-SHA256');
  signer.update(preSign);
  signer.end();
  const sign = signer.sign(TASK_SIGN_PRIVATE_KEY, 'base64');

  return { preSign, sign };
}

async function completeTask(token, taskCode) {
  const nonce = genNonce();
  const timestamp = String(Date.now());
  const { preSign, sign } = calcTaskSign(taskCode, nonce, timestamp);

  const qs = new URLSearchParams({ taskCode, nonce, timestamp }).toString();
  const url = `${UC_API}/v1/complete-task/${taskCode}?${qs}`;

  const appPathMap = {
    TS00210: '/pages-cwshop/goods/detail/detail?wd=2',
    TS00016: '/pages/webview/webview?taskCode=TS00016',
    TS00203: '/pages-cwshop/goods/detail/detail?czz=1',
    TS00211: '/pages-cwshop/goods/detail/detail?czz=2',
    TS00213: '/pages-picture/picture/page-picture-detail',
  };

  const ret = await httpJson(url, {
    method: 'GET',
    headers: commonHeaders({
      Authorization: `Bearer ${token}`,
      nonce,
      timestamp,
      sign,
      'App-Path': appPathMap[taskCode] || APP_PATH,
    }),
  });

  return { ret, preSign };
}

async function runTasks(token) {
  section('任务中心');
  const before = await getWdStatus(token);
  logInfo(`固定任务(${TASK_CODES.length})：${TASK_CODES.map(c => `${c}(${taskName(c)})`).join('，')}`);
  logSep();

  let execCount = 0;
  let successCount = 0;

  for (let i = 0; i < TASK_CODES.length; i++) {
    const taskCode = TASK_CODES[i];
    const name = taskName(taskCode);
    const b = before.map[taskCode];
    if (Number(b) === 1) {
      logWarn(`[${i + 1}/${TASK_CODES.length}] ${taskCode} ${name}：已完成，跳过`);
      continue;
    }

    execCount++;
    logInfo(`[${i + 1}/${TASK_CODES.length}] 开始上报 ${taskCode} ${name}`);
    try {
      const { ret } = await completeTask(token, taskCode);
      const msg = brief(ret?.data || ret?.msg || ret);
      if (Number(ret?.code) === 0 || String(ret?.code) === '0') {
        successCount++;
        logOk(`${taskCode} ${name}：${msg || '成功'}`);
      } else if (isAuthFailure(ret?.code, ret?.msg)) {
        // 登录态中途失效：立即抛出，由上层清缓存重登后重跑
        throw authError(`${taskCode} ${name}：${ret?.msg || `code=${ret?.code}`}`);
      } else {
        logWarn(`${taskCode} ${name}：${msg || '失败'}`);
      }
    } catch (e) {
      if (e?.authFailed) throw e;   // 登录态失效要冒泡，交由上层清缓存重登
      logErr(`${taskCode} ${name}：${e.message || e}`);
    }
    await sleep(800);
  }

  const after = await getWdStatus(token);
  logSep();
  logInfo('任务状态对比（执行前 -> 执行后）');
  for (const taskCode of TASK_CODES) {
    const name = taskName(taskCode);
    const b = taskStateText(before.map[taskCode]);
    const a = taskStateText(after.map[taskCode]);
    const icon = a === '已完成' ? '✅' : '▫️';
    console.log(`   ${icon} ${taskCode} ${name}: ${b} -> ${a}`);
  }
  logSep();
  logOk(`任务执行结束：尝试 ${execCount} 个，成功 ${successCount} 个，跳过 ${TASK_CODES.length - execCount} 个`);
  endSection();
  return `固定任务：尝试${execCount}，成功${successCount}，跳过${TASK_CODES.length - execCount}`;
}

async function runDuibaExtraSign(token) {
  section('额外签到（兑吧连续签到）');
  try {
    const { autoLoginUrl } = await getDuibaAutoLoginUrl(token);
    logOk('签到入口获取成功');

    const jar = {};
    const ua = miniH5UA();

    const autoResp = await httpText(autoLoginUrl, {
      method: 'GET',
      jar,
      redirect: 'manual',
      headers: {
        Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'User-Agent': ua,
      },
    });

    const signPageUrl = getRedirectLocation(autoResp.headers, autoLoginUrl) || autoLoginUrl;
    const pageResp = await httpText(signPageUrl, {
      method: 'GET',
      jar,
      redirect: 'follow',
      headers: {
        Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        Referer: autoLoginUrl,
        'User-Agent': ua,
      },
    });

    const finalPageUrl = pageResp.finalUrl || signPageUrl;
    const u = new URL(finalPageUrl);
    const origin = `${u.protocol}//${u.host}`;
    const signOperatingId = u.searchParams.get('signOperatingId');
    if (!signOperatingId) throw new Error(`未找到signOperatingId: ${finalPageUrl}`);

    const keyHint = extractDuibaKeyFromPageHtml(pageResp.text);
    logInfo('已进入签到页');

    const before = await getDuibaIndexInfo(origin, signOperatingId, finalPageUrl, jar, ua);
    const bCon = Number(before?.data?.consecutiveCount || 0);
    const bTot = Number(before?.data?.totalCount || 0);
    const beforeSigned = Boolean(before?.data?.signResult);
    logInfo(`签到前：连签${bCon}天，总签到${bTot}天`);
    logInfo(`签到前状态：${beforeSigned ? '今日已签到' : '今日未签到'}`);

    const signToken = await getDuibaCtoken(origin, finalPageUrl, jar, ua, keyHint);
    logOk('ctoken解析成功');

    const signRet = await doDuibaSign(origin, signOperatingId, signToken, finalPageUrl, jar, ua);
    const signResult = Number(signRet?.data?.signResult ?? -1);
    const orderNum = signRet?.data?.orderNum || '';
    const signTextMap = {
      100: '签到请求已受理',
      2: '今日已签到',
      1: '签到成功',
    };
    logInfo(`doSign：${signTextMap[signResult] || `状态码 ${signResult}`}${orderNum ? `（单号${orderNum}）` : ''}`);

    let finalResult = null;
    if (orderNum) {
      for (let i = 0; i < 3; i++) {
        await sleep(350 + i * 350);
        finalResult = await getDuibaSignResult(origin, orderNum, finalPageUrl, jar, ua);
        if (Number(finalResult?.data?.signResult || 0) === 2) break;
      }
    }
    let finalSignCode = NaN;
    if (finalResult?.data) {
      const sr = Number(finalResult?.data?.signResult ?? -1);
      finalSignCode = sr;
      const credits = finalResult?.data?.credits;
      logInfo(`结果确认：状态码 ${sr}${credits !== null && credits !== undefined ? `，奖励 ${credits} 维豆` : ''}`);
    }

    const after = await getDuibaIndexInfo(origin, signOperatingId, finalPageUrl, jar, ua);
    const aCon = Number(after?.data?.consecutiveCount || 0);
    const aTot = Number(after?.data?.totalCount || 0);
    const afterSigned = Boolean(after?.data?.signResult);
    logSep();
    logInfo(`状态对比: 连签 ${bCon} -> ${aCon}，总签到 ${bTot} -> ${aTot}`);
    logInfo(`签到后状态：${afterSigned ? '今日已签到' : '今日未签到'}`);

    const progressChanged = aCon > bCon || aTot > bTot;
    const signedNow = !beforeSigned && afterSigned;
    const alreadySigned = beforeSigned && afterSigned && !progressChanged;

    if (progressChanged || signedNow || finalSignCode === 1) {
      logOk('兑吧连续签到成功');
      return '兑吧签到：成功';
    } else if (alreadySigned || signResult === 2 || finalSignCode === 2) {
      logInfo('今日已签到（可能是你手动签过）');
      return '兑吧签到：今日已签到';
    } else {
      logWarn('签到状态未变化（可能已签/风控）');
      return '兑吧签到：状态未变化';
    }
  } catch (e) {
    if (e?.authFailed) throw e;   // 登录态失效要冒泡给重登逻辑，不能当普通签到失败吞掉
    logErr(`兑吧签到失败: ${e.message || e}`);
    return `兑吧签到：失败（${truncText(e.message || e, 60)}）`;
  }
}

async function acquireToken(account) {
  const { server, ref } = account;
  const code = await getWxCode(server, ref, APPID);
  logOk('YYB-Go-Enhanced获取wx.login code成功');

  const ticket = await exchangeByCode(code);
  logOk('exchange成功');

  const token = await signinByTicket(ticket);
  logOk('signin成功');
  printTokenInfo(token);
  return token;
}

async function runOne(account, idx, total) {
  const { server, ref, note = '' } = account;
  accountFrame(idx, total, `标识 ${ref}${note ? `（${note}）` : ''}`, `${server}@${ref}`);
  const ck = cacheKey(server, ref);
  let token = '';
  let tokenSource = '';

  for (let attempt = 0; attempt < 2; attempt++) {
    let usedCache = false;
    try {
      // ① 复用缓存 token（仅在首次尝试时）
      if (attempt === 0) {
        const entry = readCache()[ck] || {};
        if (entry.token) {
          if (jwtExpired(entry.token)) {
            logInfo('💾 [缓存] token 已过有效期，清理后重新登录');
            dropTokenCache(ck);
          } else {
            try {
              await getUserByToken(entry.token);
              token = entry.token;
              tokenSource = '缓存';
              usedCache = true;
              logOk('💾 [缓存] 复用已保存的 token');
            } catch (e) {
              if (e?.authFailed) {
                logInfo('♻️ [缓存] token 已失效，清理后重新登录');
                dropTokenCache(ck);
              } else {
                logWarn(`[缓存] token 校验异常，改为重新登录：${truncText(e.message || e, 80)}`);
              }
            }
          }
        }
      }

      // ② 重新登录
      if (!usedCache) {
        token = await acquireToken(account);
        tokenSource = '新登录';
        saveTokenCache(ck, token);
      }
      logSep();

      // ③ 用户状态与积分基线
      const profile = await getUserByToken(token);
      const beforeScore = scoreSnapshot(profile);
      logOk(`/v1/get-user 成功（登录态来源：${tokenSource}）`);
      logInfo(`执行前积分：${beforeScore.current ?? '接口未返回'}，今日累计：${beforeScore.today ?? '接口未返回'}`);
      logSep();

      // ④ 任务 + 兑吧签到
      if (RUN_TASKS) {
        const taskSummary = await runTasks(token);
        const signSummary = await runDuibaExtraSign(token);
        await sleep(1000);
        const afterProfile = await getUserByToken(token);
        const afterScore = scoreSnapshot(afterProfile);
        const points = scoreSummary(beforeScore, afterScore);
        logOk(points.replace('💰 ', ''));
        saveTokenCache(ck, token);
        return [points, `✅ ${taskSummary}`, `📅 ${signSummary}`].filter(Boolean).join('\n');
      }

      logWarn('CHUANGW_RUN_TASKS=0，已跳过全部任务（含兑吧签到）');
      saveTokenCache(ck, token);
      return [scoreSummary(beforeScore, beforeScore), '⚠️ 已按配置跳过任务'].join('\n');
    } catch (e) {
      // 登录态中途失效：清缓存 + 重新登录 + 重跑一次
      if (e?.authFailed && attempt === 0) {
        logInfo(`🔄 [重试] 登录态失效，清理缓存后重新登录重跑（${truncText(e.message || e, 80)}）`);
        dropTokenCache(ck);
        token = '';
        tokenSource = '';
        continue;
      }
      throw e;
    }
  }
}

function sendQingLongNotify(title, content) {
  if (!NOTIFY_ENABLED) {
    logInfo('CHUANGW_NOTIFY=0，已关闭通知');
    return;
  }
  const py = String.raw`
import importlib.util, os, sys
paths = ['/ql/data/scripts/notify.py', '/ql/scripts/notify.py', os.path.join(os.getcwd(), 'notify.py')]
for candidate in paths:
    if not os.path.isfile(candidate):
        continue
    spec = importlib.util.spec_from_file_location('ql_notify', candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sender = getattr(module, 'send', None) or getattr(module, 'sendNotify', None)
    if not callable(sender):
        continue
    sender(os.environ['CW_NOTIFY_TITLE'], os.environ['CW_NOTIFY_CONTENT'])
    print('notify.py调用完成')
    sys.exit(0)
print('未找到可用的青龙notify.py', file=sys.stderr)
sys.exit(2)
`;
  try {
    const result = spawnSync(process.env.PYTHON_BIN || 'python3', ['-c', py], {
      encoding: 'utf8',
      timeout: 120000,
      env: { ...process.env, CW_NOTIFY_TITLE: title, CW_NOTIFY_CONTENT: content },
    });
    if (result.status === 0) logOk('青龙通知模块调用完成');
    else logWarn(`青龙通知失败（不影响任务结果）：${truncText(result.stderr || result.stdout || `exit ${result.status}`, 160)}`);
  } catch (e) {
    logWarn(`青龙通知异常（不影响任务结果）：${e.message || e}`);
  }
}

(async () => {
  const raw = process.env.YYB_SERVER || '';
  if (!raw.trim()) {
    boxTop('📺 创维小程序 自动签到');
    boxLine('⚠️ 状态', '未配置 YYB_SERVER');
    boxBottom();
    console.log('格式：YYB-Go-Enhanced地址@账号标识，多账号每行一条');
    process.exitCode = 1;
    return;
  }

  let accounts;
  try {
    accounts = parseAccounts(raw);
  } catch (e) {
    logErr(e.message || e);
    process.exitCode = 1;
    return;
  }

  boxTop('📺 创维小程序 自动签到');
  boxLine('🕒 启动时间', nowText());
  boxLine('🔢 账号数量', accounts.length);
  boxLine('🧩 固定任务', `${TASK_CODES.length} 项`);
  boxLine('💾 缓存文件', 'token_caches/cw_token_cache.json');
  boxBottom();

  const results = [];
  let failed = 0;
  let skipped = 0;
  for (let i = 0; i < accounts.length; i++) {
    try {
      const summary = await runOne(accounts[i], i + 1, accounts.length);
      results.push(`【账号${i + 1}${accounts[i].note ? ` · ${accounts[i].note}` : ''}】\n${summary}`);
      accountDivider();
    } catch (e) {
      if (e?.accountSkipped) {
        logWarn(`账号${i + 1}未注册创维小程序，已跳过`);
        results.push(`【账号${i + 1}${accounts[i].note ? ` · ${accounts[i].note}` : ''}】\n⏭️ 未注册创维，已跳过`);
        skipped++;
      } else {
        logErr(`账号${i + 1}失败: ${e.message || e}`);
        results.push(`【账号${i + 1}${accounts[i].note ? ` · ${accounts[i].note}` : ''}】\n❌ 失败：${truncText(e.message || e, 80)}`);
        failed++;
      }
      accountDivider();
    }
  }

  // 逐账号明细在前
  console.log('');
  for (const item of results) {
    console.log(item);
    console.log('');
  }

  boxTop('🏁 创维小程序 任务完成');
  boxLine('✅ 成功', accounts.length - failed - skipped);
  boxLine('⏭️ 跳过', skipped);
  boxLine('❌ 失败', failed);
  boxLine('🕒 结束时间', nowText());
  boxBottom();

  sendQingLongNotify('创维小程序', [
    `📊 成功 ${accounts.length - failed - skipped}｜跳过 ${skipped}｜失败 ${failed}`,
    '',
    ...results.flatMap((item, index) => index === results.length - 1 ? [item] : [item, '']),
  ].join('\n'));
  if (failed > 0) process.exitCode = 1;
})();
