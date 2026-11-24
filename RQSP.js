#!/usr/bin/env node
// name: 日清食品
/**
 * 日清食品（RQSP）
 * cron: 8 9,21 * * *
 *
 * 流程：
 * YYB_SERVER -> /wxapp/getCode -> /auth/getOpenId -> /auth/login -> accessToken
 *   -> /auth/user/current（校验登录态 + 用户信息）
 *   -> /member/point（当前可用积分）
 *   -> /sign-in/statistics -> /sign-in（未签才签）
 *   -> /taskCenter/getEffectiveTask（查 PLAY_GAME 任务）
 *      -> /game/config -> /game/login -> /game/begin -> /game/end 上报成绩 -> 复查任务
 *
 * 环境变量：
 * - YYB_SERVER                       必填；YYB-Go-Enhanced 地址@账号标识，多账号每行一条
 * - YYB_API_KEY / YYB_PROTOCOL_TOKEN 可选，启用协议鉴权时配置
 * - RQSP_NOTIFY                      默认 1；0=关闭青龙 notify.py 汇总通知
 * - RQSP_GAME_ROUNDS                 默认 2；玩游戏任务未完成时最多打几局（1-3）
 * - RQSP_LOTTERY                     默认 1；0=跳过每日免费抽奖
 * - RQSP_LOTTERY_CHANCE_PATH         查询抽奖次数接口路径（需抓包，如 /activity/xxx/chance）
 * - RQSP_LOTTERY_DRAW_PATH           执行抽奖接口路径（需抓包，如 /activity/xxx/draw）
 * - RQSP_LOTTERY_DRAW_BODY           抽奖请求体 JSON（默认 {}）
 *
 * 缓存：脚本目录 token_caches/rqsp_token_cache.json，按 地址|标识 隔离，不设固定过期；
 *       每次运行先用 /auth/user/current 验证，有效直接复用；
 *       执行中若检测到登录态失效，自动清缓存 → 重新登录 → 重跑一次（attempt 上限 2）。
 */

'use strict';

const axios = require('axios');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const MINI_APP_ID = 'wx21b71db59d93bd6d';
const API_BASE = (process.env.RQSP_API_BASE || 'https://foodhall-prod-api.nissinfoodium.com.cn/miniapp').replace(/\/+$/, '');
// 幸运九宫格抽奖（抓包自小程序，路径相对 /miniapp）
const LOTTERY_INFO_PATH = '/activity/lottery/grid/info';
const LOTTERY_TIMES_PATH = '/activity/lottery/grid/user/times';
const LOTTERY_DRAW_PATH = '/activity/lottery/grid';
const LOTTERY_AWARDS_PATH = '/activity/lottery/grid/awards';
const PAGE_VERSION = '74';
const USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ' +
  'MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF';

// 缓存：脚本目录 token_caches/，按 地址|标识 隔离，不设固定过期
const CACHE_DIR = path.join(__dirname, 'token_caches');
const CACHE_FILE = path.join(CACHE_DIR, 'rqsp_token_cache.json');

const NOTIFY_ENABLED = (process.env.RQSP_NOTIFY || '1') !== '0';

const BOX_WIDTH = 48;
const BOX_INNER = 46;
const LOG_WIDTH = 74;

// 只认明确的凭证类提示，避免把「游戏登录失败」这类业务错误误判成登录失效
const AUTH_HINTS = [
  '未登录', '请重新登录', '登录失效', '登录已失效', '登录已过期',
  'token', '凭证', 'unauthorized', 'invalid token', 'auth-status', '会话失效',
];

// --------------------------------------------------------------------------- //
// 小工具
// --------------------------------------------------------------------------- //
function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

const PRIZE_TYPE_CN = {
  PHYSICAL_OBJECT: '实物奖',
  PHYSICAL: '实物奖',
  POINTS: '积分',
  POINT: '积分',
  COUPON: '优惠券',
  CASH_COUPON: '代金券',
  VIRTUAL: '虚拟奖品',
  CARD: '会员卡',
  RED_PACKET: '红包',
  NO_PRIZE: '未中奖',
};

function prizeTypeText(type) {
  const key = String(type || '').trim();
  if (!key) return '';
  return PRIZE_TYPE_CN[key] || key;
}

function isPhysicalPrize(type) {
  const key = String(type || '').trim().toUpperCase();
  return key === 'PHYSICAL_OBJECT' || key === 'PHYSICAL';
}

function formatAwardTime(value) {
  if (value === null || value === undefined || value === '') return '';
  const n = Number(value);
  if (Number.isFinite(n) && n > 0) {
    const ms = n > 1e12 ? n : n * 1000;
    const d = new Date(ms);
    if (!Number.isNaN(d.getTime())) {
      const pad = (x) => String(x).padStart(2, '0');
      return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }
  }
  return String(value).slice(0, 16);
}

function nowText() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

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

function accountDivider() {
  console.log('');
  console.log('-'.repeat(48));
}

function accountFrame(idx, total, title, source) {
  console.log('');
  console.log('┌' + '─'.repeat(BOX_WIDTH) + '┐');
  console.log('│  ' + padWidth(`🧩 账号 ${idx} / ${total}　${title}`, BOX_INNER) + '│');
  console.log('│  ' + padWidth(`🔗 来源: ${source}`, BOX_INNER) + '│');
  console.log('└' + '─'.repeat(BOX_WIDTH) + '┘');
}

function logOk(msg) {
  console.log(`✅ ${msg}`);
}

function logInfo(msg) {
  console.log(`ℹ️ ${msg}`);
}

function logWarn(msg) {
  console.log(`⚠️ ${msg}`);
}

function logErr(msg) {
  console.log(`❌ ${msg}`);
}

function truncText(s, max = 96) {
  const str = String(s ?? '');
  if (str.length <= max) return str;
  return `${str.slice(0, max - 1)}…`;
}

function brief(v, max = 200) {
  if (v === undefined || v === null) return '';
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return truncText(s, max);
}

function maskMiddle(s, left = 10, right = 8) {
  const str = String(s || '');
  if (!str) return '-';
  if (str.length <= left + right + 3) return str;
  return `${str.slice(0, left)}...${str.slice(-right)}`;
}

function maskPhone(phone = '') {
  const str = String(phone || '');
  if (str.length < 8) return str;
  return str.replace(/^(\d{3})\d+(\d{4})$/, '$1****$2');
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

/** /member/point 返回 {availablePoints}；兼容纯数字/字符串/其它字段名 */
function parsePoints(v) {
  const asNum = (x) => {
    if (typeof x === 'number' && Number.isFinite(x)) return x;
    if (typeof x === 'string' && x.trim() !== '' && Number.isFinite(Number(x))) return Number(x);
    return null;
  };
  const direct = asNum(v);
  if (direct !== null) return direct;
  if (v && typeof v === 'object') {
    for (const key of ['availablePoints', 'point', 'points', 'integral', 'totalPoint', 'totalIntegral']) {
      const got = asNum(v[key]);
      if (got !== null) return got;
    }
  }
  return null;
}

/** 关卡目标分：/game/config 的 shuzhi.mubiao，受 shuzhi.shangxian 上限约束 */
function pickScore(config) {
  const shuzhi = config?.shuzhi || {};
  const target = num(shuzhi.mubiao) || num(config?.targetScore) || 500;
  const cap = num(shuzhi.shangxian);
  const score = cap > 0 ? Math.min(target, cap) : target;
  return Math.max(1, Math.round(score));
}

// --------------------------------------------------------------------------- //
// 缓存
// --------------------------------------------------------------------------- //
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
    logWarn(`[缓存] 写入失败（不影响本次执行）：${e.message || e}`);
  }
}

function saveCache(ck, snapshot) {
  const cache = readCache();
  cache[ck] = { ...snapshot, updatedAt: nowText() };
  writeCache(cache);
}

function dropCache(ck) {
  const cache = readCache();
  if (ck in cache) {
    delete cache[ck];
    writeCache(cache);
  }
}

// --------------------------------------------------------------------------- //
// 登录态错误
// --------------------------------------------------------------------------- //
function authError(message) {
  const e = new Error(message);
  e.authFailed = true;
  return e;
}

function isAuthError(e) {
  if (!e) return false;
  if (e.authFailed) return true;
  const code = num(e.code);
  if (code === 401 || code === 403 || code === 900001) return true;
  const text = String(e.message || e).toLowerCase();
  return AUTH_HINTS.some((hint) => text.includes(hint.toLowerCase()));
}

// --------------------------------------------------------------------------- //
// 账号解析 / YYB 取码
// --------------------------------------------------------------------------- //
function parseAccounts(raw) {
  const lines = String(raw || '')
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (!lines.length) throw new Error('未配置 YYB_SERVER（每行：地址@账号标识）');

  const accounts = [];
  lines.forEach((line, i) => {
    const at = line.indexOf('@');
    if (at === -1) throw new Error(`YYB_SERVER 第 ${i + 1} 行格式错误，应为 地址@账号标识：${line}`);
    let server = line.slice(0, at).trim();
    let ref = line.slice(at + 1).trim();
    if (server.startsWith('http://')) server = server.slice(7);
    else if (server.startsWith('https://')) server = server.slice(8);
    server = server.replace(/\/+$/, '');
    if (!server || !ref) throw new Error(`YYB_SERVER 第 ${i + 1} 行格式错误，应为 地址@账号标识：${line}`);
    accounts.push({ server, ref, note: '' });
  });
  return accounts;
}

async function fetchWxCode(server, ref) {
  const headers = {};
  const apiKey = (process.env.YYB_API_KEY || process.env.YYB_PROTOCOL_TOKEN || '').trim();
  if (apiKey) headers.Authorization = apiKey.includes(' ') ? apiKey : `Bearer ${apiKey}`;

  try {
    const { data } = await axios.post(
      `http://${server}/wxapp/getCode`,
      { ref, app_id: MINI_APP_ID },
      { timeout: 20000, proxy: false, headers, validateStatus: () => true }
    );
    // YYB-GO 的 code 可能是数字 0，也可能是字符串 "0"，统一转 Number 比较
    if (num(data?.code) !== 0) {
      logWarn(`[授权] ${server} 获取 code 失败：${brief(data)}`);
      return null;
    }
    // data.result 可能是对象，也可能是 JSON 字符串
    let result = data?.data?.result;
    if (typeof result === 'string') {
      try {
        result = JSON.parse(result);
      } catch {
        result = { code: result };
      }
    }
    const code = result?.code;
    if (!code) {
      logWarn(`[授权] ${server} 未返回 code：${brief(data)}`);
      return null;
    }
    logOk(`[授权] ${server} 获取 code 成功`);
    return String(code);
  } catch (e) {
    logErr(`[授权] ${server} 获取 code 异常：${e.message || e}`);
    return null;
  }
}

// --------------------------------------------------------------------------- //
// 单账号
// --------------------------------------------------------------------------- //
class Task {
  constructor(account, index) {
    this.server = account.server;
    this.ref = account.ref;
    this.index = index;
    this.token = '';
    this.redOpenId = '';
    this.userId = '';
    this.user = {};
    this.signInfo = {};
  }

  // ---- 登录态 ---------------------------------------------------------- //
  applyCache(entry = {}) {
    this.token = String(entry.accessToken || entry.token || '');
    this.redOpenId = String(entry.redOpenId || entry.openId || '');
    this.userId = String(entry.userId || '');
    this.user = { mobile: entry.mobile || '' };
  }

  snapshot() {
    return {
      accessToken: this.token,
      redOpenId: this.redOpenId,
      userId: this.userId,
      mobile: this.user?.mobile || '',
    };
  }

  reset() {
    this.token = '';
    this.redOpenId = '';
    this.userId = '';
    this.user = {};
  }

  getHeaders(extra = {}) {
    const headers = {
      'User-Agent': USER_AGENT,
      Referer: `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
      Accept: 'application/json, text/plain, */*',
      ...extra,
    };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    return headers;
  }

  async request({ method = 'GET', apiPath, data, params, skipToken = false }) {
    const options = {
      method,
      url: `${API_BASE}${apiPath.startsWith('/') ? apiPath : `/${apiPath}`}`,
      headers: this.getHeaders(method === 'POST' ? { 'Content-Type': 'application/json' } : {}),
      timeout: 15000,
      validateStatus: () => true,
    };
    if (params) options.params = params;
    if (data !== undefined) options.data = data;
    if (skipToken) delete options.headers.Authorization;

    const { status, data: result, headers } = await axios.request(options);

    if (status === 401 || status === 403) throw authError(`HTTP ${status}`);
    if (status !== 200) throw new Error(`HTTP ${status}: ${brief(result, 160)}`);
    if (headers && String(headers['auth-status']) === 'false') throw authError('Auth-Status=false');

    const bizCode = num(result?.code);
    if (!result || bizCode !== 0) {
      const message = String(result?.msg || result?.message || brief(result, 160) || '接口返回空');
      if (bizCode === 401 || bizCode === 403 || bizCode === 900001) throw authError(message);
      const e = new Error(message);
      e.code = result?.code;
      throw e;
    }
    return result.data;
  }

  async loginByWxCode() {
    const code = await fetchWxCode(this.server, this.ref);
    if (!code) throw new Error('YYB 取码失败，无法登录');

    const openData = await this.request({
      method: 'POST',
      apiPath: '/auth/getOpenId',
      skipToken: true,
      data: { code, invitorMemberId: 0 },
    });
    this.redOpenId = String(openData?.openId || '');
    if (!this.redOpenId) throw new Error(`/auth/getOpenId 未返回 openId：${brief(openData)}`);

    const loginData = await this.request({
      method: 'POST',
      apiPath: '/auth/login',
      skipToken: true,
      data: { openId: this.redOpenId },
    });
    this.applyToken({ ...(loginData || {}), redOpenId: this.redOpenId });
    if (!this.token) throw new Error(`/auth/login 未返回 accessToken：${brief(loginData)}`);

    logOk(`[登录] 成功　userId=${this.userId || '未知'}`);
  }

  applyToken(data = {}) {
    this.token = String(data.accessToken || data.access_token || '');
    this.redOpenId = String(data.redOpenId || data.openId || data.open_id || this.redOpenId || '');
    this.userId = String(data.userId || data.user_id || '');
  }

  // ---- 用户 / 积分 ------------------------------------------------------ //
  async getUser(silent = false) {
    const data = await this.request({ apiPath: '/auth/user/current' });
    this.user = data || {};
    if (!silent) {
      const name = this.user.nickname || this.user.name || '';
      const phone = maskPhone(this.user.mobile);
      logInfo(`[用户] ${[name, phone].filter(Boolean).join(' ') || '接口未返回昵称'}`);
    }
    return this.user;
  }

  async getSignInInfo(silent = false) {
    const data = await this.request({ apiPath: '/sign-in/statistics' });
    this.signInfo = data || {};
    if (!silent) logInfo(`[积分] ${pointsText(this.signInfo)}`);
    return this.signInfo;
  }

  /** 真实可用积分（/member/point → data.availablePoints） */
  async getMemberPoints() {
    try {
      const data = await this.request({ apiPath: '/member/point' });
      return parsePoints(data);
    } catch (e) {
      if (isAuthError(e)) throw e;
      return null;
    }
  }

  // ---- 签到 ------------------------------------------------------------ //
  async doSign() {
    const info = await this.getSignInInfo(true);
    if (info.hasSignedToday) {
      logOk(`[签到] 今日已签到（连续 ${num(info.continuousDays)} 天）`);
      return `今日已签到（连续 ${num(info.continuousDays)} 天 / 累计 ${num(info.totalDays)} 天）`;
    }

    const gained = await this.request({ method: 'POST', apiPath: '/sign-in', data: {} });
    logOk(`[签到] 签到成功 +${gained ?? '未知'} 积分`);
    return `签到成功 +${gained ?? '未知'} 积分`;
  }

  // ---- 任务 / 游戏 ------------------------------------------------------ //
  async getTaskList() {
    const data = await this.request({ apiPath: '/taskCenter/getEffectiveTask' });
    return Array.isArray(data) ? data : [];
  }

  async findGameTask() {
    const tasks = await this.getTaskList();
    return tasks.find((item) => item?.ruleType === 'PLAY_GAME') || null;
  }

  async getPlayNum() {
    const data = await this.request({ apiPath: '/game/count' });
    return parsePoints(data);
  }

  /**
   * 完整一局：/game/login → /game/begin（返回 playId）→ /game/end 上报成绩。
   * 原版只打开了游戏页面、没走上报，所以 PLAY_GAME 任务永远未完成。
   */
  async playOneRound(score) {
    await this.request({
      method: 'POST',
      apiPath: '/game/login',
      data: { loginIp: '', loginLocation: '', invitorMemberId: '' },
    });

    const playId = await this.request({ method: 'POST', apiPath: '/game/begin', data: { loginIp: '' } });
    if (!playId) throw new Error('/game/begin 未返回 playId');

    const endData = await this.request({
      method: 'POST',
      apiPath: '/game/end',
      data: { score, playId },
    });
    return { playId, score, endData };
  }

  async enterGame() {
    const config = await this.request({ apiPath: '/game/config' });
    const title = config?.shareTitle || config?.title || '欢乐消消乐';
    const target = pickScore(config);
    const scoreCap = num(config?.shuzhi?.shangxian);

    const before = await this.findGameTask();
    if (before?.complete) {
      logOk('[游戏] 玩游戏任务已完成，跳过');
      return '玩游戏任务已完成';
    }
    logInfo(`[游戏] ${title}　目标 ${target} 分`);

    let plays = await this.getPlayNum();
    logInfo(`[游戏] 剩余次数 ${plays === null ? '未知' : plays}`);
    if (plays !== null && plays <= 0) {
      logWarn('[游戏] 剩余次数为 0，无法开局（等次日次数恢复）');
      return '次数为 0，未开局';
    }

    const maxRounds = Math.max(1, Math.min(3, num(process.env.RQSP_GAME_ROUNDS) || 2));
    let completed = false;
    let played = 0;

    for (let round = 1; round <= maxRounds; round++) {
      const startAt = Date.now();
      const rawScore = target * round;
      const roundScore = scoreCap > 0 ? Math.min(scoreCap, rawScore) : rawScore;
      try {
        const r = await this.playOneRound(roundScore);
        played += 1;
        logOk(`[游戏] 第 ${round} 局完成：成绩 ${r.score} 分，playId=${r.playId}（耗时 ${Math.round((Date.now() - startAt) / 1000)}s）`);
        if (r.endData !== undefined && r.endData !== null && typeof r.endData !== 'object') {
          logInfo(`[游戏] 结算返回：${brief(r.endData, 80)}`);
        }
      } catch (e) {
        if (isAuthError(e)) throw e;
        logWarn(`[游戏] 第 ${round} 局失败：${truncText(e.message || e, 80)}`);
        break;
      }

      await sleep(1500 + Math.floor(Math.random() * 800));

      const task = await this.findGameTask();
      if (task?.complete) {
        completed = true;
        logOk('[游戏] 玩游戏任务已完成');
        break;
      }

      plays = await this.getPlayNum();
      logInfo(`[游戏] 剩余次数 ${plays === null ? '未知' : plays}`);
      if (plays !== null && plays <= 0) {
        logWarn('[游戏] 次数已用完');
        break;
      }
    }

    if (!completed) {
      logWarn(`[游戏] 打了 ${played} 局，任务仍显示未完成（可能是后台延迟或需更高成绩，可用 RQSP_GAME_ROUNDS 调整局数）`);
      try {
        const raw = await this.getTaskList();
        const gameTask = (raw || []).find((item) => item?.ruleType === 'PLAY_GAME') || null;
        if (gameTask) {
          logInfo(`[游戏] 任务原始字段：${brief(JSON.stringify(gameTask), 160)}`);
        } else {
          logInfo('[游戏] 任务列表中未找到 PLAY_GAME 任务项');
        }
      } catch (e) {
        logInfo(`[游戏] 读取任务字段失败：${truncText(e.message || e, 60)}`);
      }
    }
    return completed
      ? `玩游戏任务已完成（${played} 局 × ${target} 分）`
      : `已打 ${played} 局 × ${target} 分，任务未完成`;
  }

  // ---- 每日免费抽奖 ------------------------------------------------------ //
  async doLottery() {
    if (process.env.RQSP_LOTTERY === '0') {
      logInfo('[抽奖] RQSP_LOTTERY=0，跳过');
      return '已按配置跳过';
    }

    // ① 活动信息（拿 activityId / 免费次数上限 / 消耗积分）
    let info = null;
    try {
      info = await this.request({ apiPath: LOTTERY_INFO_PATH });
    } catch (e) {
      if (isAuthError(e)) throw e;
      logWarn(`[抽奖] 查询活动失败：${truncText(e.message || e, 80)}`);
      return `活动查询失败（${truncText(e.message || e, 40)}）`;
    }
    const activityId = info?.id || info?.activityId;
    if (!activityId) {
      logWarn('[抽奖] 活动信息里没有 activityId，跳过');
      return '活动未开启或未取到 activityId，跳过';
    }
    const freeDaily = num(info?.userFreeLimitDaily);
    logInfo(`[抽奖] 活动：${info?.activityName || '幸运九宫格'}　每日免费 ${freeDaily || '未限制'} 次`);

    // ② 今日剩余免费次数
    let times = null;
    try {
      const raw = await this.request({ apiPath: LOTTERY_TIMES_PATH });
      times = typeof raw === 'number' ? raw : num(raw?.data ?? raw);
      logInfo(`[抽奖] 今日剩余免费次数：${times === null ? '未知' : times}`);
    } catch (e) {
      if (isAuthError(e)) throw e;
      logWarn(`[抽奖] 查询次数失败：${truncText(e.message || e, 80)}`);
      return `次数查询失败（${truncText(e.message || e, 40)}）`;
    }
    if (times !== null && times <= 0) {
      logOk('[抽奖] 今日免费次数已用完');
      return '今日免费次数已用完';
    }

    // ③ 执行免费抽奖
    let prizeText = '';
    try {
      const draw = await this.request({
        method: 'POST',
        apiPath: LOTTERY_DRAW_PATH,
        data: { activityId, lotteryType: 'FREE' },
      });
      const record = draw?.winningRecord || draw?.data?.winningRecord || {};
      const name = record?.prizeName || record?.prizeTypeName || '';
      const type = String(record?.prizeType || '');
      const typeCn = prizeTypeText(type);
      const noPrize = type === 'NO_PRIZE' || !name || name.includes('谢谢惠顾');

      if (draw?.success === false) {
        logWarn(`[抽奖] 未成功：${truncText(draw?.message || '接口未返回原因', 60)}`);
        return `未成功（${truncText(draw?.message || '未知', 30)}）`;
      }

      if (noPrize) {
        prizeText = name || '谢谢惠顾（未中奖）';
        logInfo(`[抽奖] 抽奖完成：${prizeText}`);
      } else if (isPhysicalPrize(type)) {
        const endTime = info?.endTime ? formatAwardTime(info.endTime) : '';
        prizeText = `${name}（实物奖）`;
        logOk(`[抽奖] 抽奖完成：${prizeText}`);
        logWarn(`[抽奖] 🎁 这是实物奖，请尽快到小程序「幸运九宫格 - 我的中奖记录」填写收货地址`);
        if (endTime) logWarn(`[抽奖] 请在活动结束（${endTime}）前填写，逾期视为放弃`);
        prizeText += endTime
          ? `｜⚠️ 请到「我的中奖记录」填写收货地址（活动 ${endTime} 截止）`
          : '｜⚠️ 请到「我的中奖记录」填写收货地址';
      } else {
        prizeText = typeCn ? `${name}（${typeCn}）` : name;
        logOk(`[抽奖] 抽奖完成：${prizeText}`);
      }
    } catch (e) {
      if (isAuthError(e)) throw e;
      logWarn(`[抽奖] 抽奖失败：${truncText(e.message || e, 80)}`);
      return `抽奖失败（${truncText(e.message || e, 40)}）`;
    }

    // ④ 复查剩余次数
    try {
      const rawAfter = await this.request({ apiPath: LOTTERY_TIMES_PATH });
      const after = typeof rawAfter === 'number' ? rawAfter : num(rawAfter?.data ?? rawAfter);
      if (after !== null) logInfo(`[抽奖] 抽奖后剩余次数：${after}`);
    } catch (e) {
      /* 复查失败不影响结果 */
    }

    return `获得 ${prizeText}`;
  }

  // ---- 我的中奖记录 ------------------------------------------------------ //
  async getLotteryRecords(size = 3) {
    try {
      const data = await this.request({
        apiPath: LOTTERY_AWARDS_PATH,
        params: { pageNum: 1, pageSize: size },
      });
      const list = Array.isArray(data) ? data : (data?.list || data?.records || []);
      if (!list.length) {
        logInfo('[抽奖] 中奖记录：暂无记录');
        return '暂无记录';
      }
      const shown = list.slice(0, size);
      const physicalCount = shown.filter((it) => isPhysicalPrize(it.prizeType)).length;
      const text = shown
        .map((it) => {
          const name = it.prizeName || it.awardName || it.name || '未知奖品';
          const tCn = prizeTypeText(it.prizeType);
          const t = it.createTime || it.awardTime || it.winTime || '';
          const timeText = t ? formatAwardTime(t) : '';
          const label = tCn ? `${name}（${tCn}）` : name;
          const pending = isPhysicalPrize(it.prizeType) ? '｜⚠️ 待填收货地址' : '';
          return (timeText ? `${label} ${timeText}` : label) + pending;
        })
        .join('；');
      logInfo(`[抽奖] 中奖记录：${text}`);
      if (physicalCount > 0) {
        logWarn(`[抽奖] 有 ${physicalCount} 个实物奖还没填收货地址，请到小程序「我的中奖记录」补齐`);
        return `${text}（共 ${physicalCount} 个实物奖待填地址）`;
      }
      return text;
    } catch (e) {
      if (isAuthError(e)) throw e;
      return `记录查询失败（${truncText(e.message || e, 30)}）`;
    }
  }

}

function pointsText(info) {
  const today = info?.todayPoints;
  const parts = [`今日 +${today ?? 0} 积分`];
  if (info?.continuousDays !== undefined) parts.push(`连续 ${num(info.continuousDays)} 天`);
  if (info?.totalDays !== undefined) parts.push(`累计 ${num(info.totalDays)} 天`);
  return parts.join(' · ');
}

function pointsSummary(before, after, signInfo) {
  if (after === null || after === undefined) return pointsText(signInfo);
  if (before === null || before === undefined) return `当前 ${after} 分`;
  const delta = after - before;
  const change = delta > 0 ? `本次 +${delta}` : delta < 0 ? `本次 ${delta}` : '本次无变化';
  return `当前 ${after} 分（${change}）`;
}

// --------------------------------------------------------------------------- //
// 单账号执行（缓存 + 失效重登）
// --------------------------------------------------------------------------- //
async function runOne(account, idx, total) {
  const { server, ref, note } = account;
  accountFrame(idx, total, `标识 ${ref}${note ? `（${note}）` : ''}`, `${server}@${ref}`);
  const ck = cacheKey(server, ref);

  for (let attempt = 0; attempt < 2; attempt++) {
    const task = new Task(account, idx);
    let tokenSource = '';
    try {
      // ① 复用缓存 token（仅首次尝试）
      if (attempt === 0) {
        const entry = readCache()[ck];
        if (entry && (entry.accessToken || entry.token)) {
          task.applyCache(entry);
          try {
            await task.getUser(true);
            tokenSource = '缓存';
            logOk(`[缓存] 复用已保存的登录 token（${maskMiddle(task.token)}）`);
          } catch (e) {
            if (isAuthError(e)) {
              logInfo(`[缓存] token 已失效，清理后重新登录（${truncText(e.message || e, 80)}）`);
              dropCache(ck);
            } else {
              logWarn(`[缓存] 校验异常，改为重新登录：${truncText(e.message || e, 60)}`);
            }
            task.reset();
          }
        }
      }

      // ② 新登录
      if (!task.token) {
        tokenSource = '新登录';
        await task.loginByWxCode();
        saveCache(ck, task.snapshot());
        await task.getUser(true);
      }

      // ③ 登录行下方 → 当前积分（优先 /member/point 真实可用积分）
      const beforeSign = await task.getSignInInfo(true);
      const beforePoints = await task.getMemberPoints();
      logInfo(`[积分] ${beforePoints === null ? pointsText(beforeSign) : `当前 ${beforePoints} 分`}`);

      // ④ 用户信息
      const user = task.user || {};
      logInfo(
        `[用户] ${[user.nickname || user.name || '', maskPhone(user.mobile)].filter(Boolean).join(' ') || '接口未返回昵称'}` +
          `（登录态来源：${tokenSource}）`
      );

      // ⑤ 签到 + 游戏任务
      const signMsg = await task.doSign();
      const gameMsg = await task.enterGame();
      const lotteryMsg = await task.doLottery();
      const recordMsg = await task.getLotteryRecords(2);
      await sleep(800);

      const afterSign = await task.getSignInInfo(true);
      const afterPoints = await task.getMemberPoints();
      const pointsLine = pointsSummary(beforePoints, afterPoints, afterSign);
      logInfo(`[积分] ${pointsLine}`);
      saveCache(ck, task.snapshot());

      return {
        ok: true,
        lines: [
          `👤 用户：${[user.nickname || user.name || '', maskPhone(user.mobile)].filter(Boolean).join(' ') || '未返回'}`,
          `📅 签到：${signMsg}`,
          `🎮 游戏：${gameMsg}`,
          `🎁 抽奖：${lotteryMsg}`,
          `🏆 记录：${recordMsg}`,
          `💰 积分：${pointsLine}`,
        ],
      };
    } catch (e) {
      // 登录态中途失效：清缓存 + 重新登录 + 重跑一次
      if (attempt === 0 && isAuthError(e)) {
        logInfo(`[重试] 登录态失效，清理缓存后重新登录重跑（${truncText(e.message || e, 80)}）`);
        dropCache(ck);
        continue;
      }
      logErr(`[账号] 执行失败：${truncText(e.message || e, 120)}`);
      return { ok: false, error: truncText(e.message || e, 120) };
    }
  }

  return { ok: false, error: '重试后仍失败' };
}

// --------------------------------------------------------------------------- //
// 青龙通知
// --------------------------------------------------------------------------- //
function sendQingLongNotify(title, content) {
  if (!NOTIFY_ENABLED) {
    logInfo('RQSP_NOTIFY=0，已关闭通知');
    return;
  }
  const py = String.raw`
import importlib.util, os, sys
paths = ['/ql/data/scripts/notify.py', '/ql/scripts/notify.py', '/ql/data/notify.py', os.path.join(os.getcwd(), 'notify.py')]
for candidate in paths:
    if not os.path.isfile(candidate):
        continue
    spec = importlib.util.spec_from_file_location('ql_notify', candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sender = getattr(module, 'send', None) or getattr(module, 'sendNotify', None)
    if not callable(sender):
        continue
    sender(os.environ['RQSP_NOTIFY_TITLE'], os.environ['RQSP_NOTIFY_CONTENT'])
    print('notify.py调用完成')
    sys.exit(0)
print('未找到可用的青龙notify.py', file=sys.stderr)
sys.exit(2)
`;
  try {
    const result = spawnSync(process.env.PYTHON_BIN || 'python3', ['-c', py], {
      encoding: 'utf8',
      timeout: 120000,
      env: { ...process.env, RQSP_NOTIFY_TITLE: title, RQSP_NOTIFY_CONTENT: content },
    });
    if (result.status === 0) logOk('[通知] 青龙通知模块调用完成');
    else logWarn(`[通知] 青龙通知失败（不影响任务结果）：${truncText(result.stderr || result.stdout || `exit ${result.status}`, 160)}`);
  } catch (e) {
    logWarn(`[通知] 青龙通知异常（不影响任务结果）：${e.message || e}`);
  }
}

// --------------------------------------------------------------------------- //
// 主流程
// --------------------------------------------------------------------------- //
(async () => {
  const raw = process.env.YYB_SERVER || '';
  if (!raw.trim()) {
    boxTop('🍜 日清食品 自动签到');
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
    boxTop('🍜 日清食品 自动签到');
    boxLine('⚠️ 状态', 'YYB_SERVER 格式错误');
    boxBottom();
    logErr(e.message || e);
    process.exitCode = 1;
    return;
  }

  boxTop('🍜 日清食品 自动签到');
  boxLine('🕒 启动时间', nowText());
  boxLine('🔢 账号数量', accounts.length);
  boxLine('💾 缓存', 'token_caches/rqsp_token_cache.json');
  boxBottom();

  const results = [];
  let failed = 0;

  for (let i = 0; i < accounts.length; i++) {
    let outcome;
    try {
      outcome = await runOne(accounts[i], i + 1, accounts.length);
    } catch (e) {
      logErr(`账号${i + 1}执行异常：${truncText(e.message || e, 120)}`);
      outcome = { ok: false, error: truncText(e.message || e, 120) };
    }
    if (!outcome.ok) failed += 1;
    results.push({ idx: i + 1, note: accounts[i].note, ...outcome });

    accountDivider();
    if (i < accounts.length - 1) {
      await sleep(2000);
    }
  }

  // 逐账号明细在前
  console.log('');
  for (const item of results) {
    const icon = item.ok ? '✅' : '❌';
    console.log(`${icon} 【账号 ${item.idx}${item.note ? ` · ${item.note}` : ''}】`);
    if (item.ok) {
      for (const line of item.lines) console.log(`   ${line}`);
    } else {
      console.log(`   ❌ 原因：${item.error || '未知错误'}`);
    }
    console.log('');
  }

  boxTop('🏁 日清食品 任务完成');
  boxLine('✅ 成功', accounts.length - failed);
  boxLine('❌ 失败', failed);
  boxLine('🕒 结束时间', nowText());
  boxBottom();

  const notifyLines = [`📊 成功 ${accounts.length - failed}｜失败 ${failed}`, ''];
  for (const item of results) {
    notifyLines.push(`${item.ok ? '✅' : '❌'} 账号${item.idx}`);
    if (item.ok) notifyLines.push(...item.lines);
    else notifyLines.push(`❌ 原因：${item.error || '未知错误'}`);
    notifyLines.push('');
  }
  sendQingLongNotify('日清食品', notifyLines.join('\n'));

  if (failed > 0) process.exitCode = 1;
})();
