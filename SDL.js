#!/usr/bin/env node
// name: 三得利
// cron: 48 8,20 * * *
/**
 * 三得利小程序 自动签到
 *
 * 环境变量：
 * - YYB_SERVER     必填；YYB Go 地址@微信账号标识，多账号每行一条，可带 #备注
 * - SDL_NOTIFY     默认 1；0=关闭通知（青龙 notify.py 与 PushPlus 一起关）
 * - PLUSPLUS_TOKEN 可选；配置后额外走 PushPlus 推送
 *

 * 缓存：脚本目录 token_caches/sdl_token_cache.json，按「地址|标识」隔离，不设固定过期
 */

'use strict';

const axios = require('axios');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const APPID = 'wxb33ed03c6c715482';
const API_BASE = 'https://xiaodian.miyatech.com/api';
const APP_NAME = '三得利';
const MINIAPP_ID = 159;
const COLLECT_SCENE = '1104';

const CACHE_DIR = path.join(__dirname, 'token_caches');
const CACHE_FILE = path.join(CACHE_DIR, 'sdl_token_cache.json');
const NOTIFY_ENABLED = (process.env.SDL_NOTIFY || '1') !== '0';
const PLUSPLUS_TOKEN = process.env.PLUSPLUS_TOKEN || '';

const BOX_WIDTH = 48;
const BOX_INNER = 46;

const HEADERS = {
  'HH-FROM': '20230130307725',
  'HH-APP': APPID,
  'HH-VERSION': '0.6.1',
  'X-VERSION': '2.3.5',
  'HH-CI': 'saas-wechat-app',
  'appPublishType': '1',
  'componentSend': '1',
  'content-type': 'application/json;charset=UTF-8',
  Referer: `https://servicewechat.com/${APPID}/72/page-frame.html`,
};

// ====================== 基础工具 ======================
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

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
  let text = String(str ?? '');
  while (displayWidth(text) > width) text = text.slice(0, -1);
  return text + ' '.repeat(Math.max(0, width - displayWidth(text)));
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
function hr() {
  console.log('');
  console.log('-'.repeat(BOX_WIDTH));
}

function maskName(value) {
  const text = String(value || '');
  return text.length > 10 ? `${text.slice(0, 4)}***${text.slice(-3)}` : text;
}

function shortToken(token) {
  const value = String(token || '').replace(/Bearer /, '');
  return value ? `${value.slice(0, 6)}***${value.slice(-6)}` : '';
}

function brief(value, max = 90) {
  const text = typeof value === 'string' ? value : JSON.stringify(value ?? '');
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

// ====================== 账号解析 ======================
function normalizeServer(raw) {
  const value = String(raw || '').trim();
  if (!value) return '';
  return value.replace(/^https?:\/\//i, '').replace(/\/+$/, '');
}

function parseEntry(raw) {
  const value = String(raw || '').trim();
  let note = '';
  let body = value;
  const hash = value.lastIndexOf('#');
  if (hash > value.lastIndexOf('@')) {
    body = value.slice(0, hash).trim();
    note = value.slice(hash + 1).trim();
  }
  const at = body.lastIndexOf('@');
  if (at <= 0) return { server: '', ref: '', note };
  const server = normalizeServer(body.slice(0, at));
  const ref = body.slice(at + 1).trim();
  return { server, ref, note };
}

function parseAccounts(raw) {
  return String(raw || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const entry = parseEntry(line);
      if (!entry.server || !entry.ref) {
        throw new Error(`YYB_SERVER 第${index + 1}行格式错误，应为 地址@微信账号标识`);
      }
      return { raw: line, ...entry };
    });
}

// ====================== 缓存 ======================
function cacheKey(server, ref) { return `${server}|${ref}`; }

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
    console.log(`   ⚠️ [缓存] 写入失败（不影响执行）：${e.message || e}`);
  }
}

function readCacheEntry(ck, account) {
  const cache = readCache();
  if (cache[ck]?.access_token) return cache[ck];
  // 兼容旧版按「地址@标识（可能带备注）」存的缓存：读到即迁移到 地址|标识
  const legacyKeys = [account.raw, `${account.server}@${account.ref}`];
  for (const key of legacyKeys) {
    const legacy = cache[key];
    if (!legacy?.access_token) continue;
    cache[ck] = legacy;
    legacyKeys.forEach((k) => delete cache[k]);
    writeCache(cache);
    console.log('   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」');
    return legacy;
  }
  // 顺手清理残留的旧键
  if (legacyKeys.some((k) => k in cache)) {
    legacyKeys.forEach((k) => delete cache[k]);
    writeCache(cache);
  }
  return {};
}

function saveCacheEntry(ck, entry) {
  const cache = readCache();
  cache[ck] = { ...entry, updatedAt: nowText() };
  writeCache(cache);
}

function dropCacheEntry(ck) {
  const cache = readCache();
  if (ck in cache) {
    delete cache[ck];
    writeCache(cache);
  }
}

// ====================== 取码 ======================
function pickCode(payload) {
  let result = payload?.data?.result ?? payload?.result;
  if (typeof result === 'string') {
    try { result = JSON.parse(result); } catch { result = {}; }
  }
  return (result || {}).code || (payload?.data || {}).code;
}

async function getCode(server, ref) {
  try {
    const res = await axios.post(
      `http://${server}/wxapp/getCode`,
      { ref, app_id: APPID },
      { timeout: 20000, proxy: false, validateStatus: () => true },
    );
    const payload = res.data || {};
    const codeNum = Number(payload.code);
    const code = pickCode(payload);
    if (codeNum !== 0 || !code) {
      console.log(`   ❌ [取码] 取码失败：${brief(payload, 120)}`);
      return null;
    }
    console.log('   ✅ [取码] 取码成功');
    return code;
  } catch (e) {
    console.log(`   ❌ [取码] 取码异常：${e.message}`);
    console.log(`   💡 [提示] 请检查 YYB 服务地址 http://${server} 是否在线、${ref} 是否已登录`);
    return null;
  }
}

// ====================== 登录态失效判定 ======================
const AUTH_PATTERN = /-4011|\b401\b|\b403\b|token\s*(无效|过期|失效)|未登录|请重新登录|登录已(过期|失效)|登录态?失效|凭证失效|授权失败/i;

function isAuthError(code, message) {
  if (Number(code) === 401 || Number(code) === 403) return true;
  return AUTH_PATTERN.test(String(message || ''));
}

function authError(message) {
  const e = new Error(message);
  e.tokenInvalid = true;
  return e;
}

// ====================== 业务客户端 ======================
class SanDeLi {
  constructor(account, index) {
    this.index = index;
    this.raw = account.raw;
    this.server = account.server;
    this.ref = account.ref;
    this.note = account.note;
    this.ck = cacheKey(account.server, account.ref);
    this.token = '';
  }

  async request(apiPath, body = {}, auth = true) {
    const headers = { ...HEADERS };
    if (auth && this.token) headers.Authorization = `Bearer ${this.token}`;
    const res = await axios.post(`${API_BASE}${apiPath}`, body, {
      headers, timeout: 20000, proxy: false, validateStatus: () => true,
    });
    return res.data || {};
  }

  async login() {
    const code = await getCode(this.server, this.ref);
    if (!code) return false;

    console.log('   🔐 [登录] 使用 code 换取 token...');
    let res;
    try {
      res = await this.request('/user/login/wx-jc', {
        jsCode: code, clientId: 'saas-wechat-app', myUnionId: '', appPublishType: 1,
      }, false);
    } catch (e) {
      console.log(`   ❌ [登录] 请求异常：${e.message}`);
      return false;
    }

    const token = res?.data?.tokenInfo?.access_token;
    if (Number(res?.code) !== 200 || !token) {
      console.log(`   ❌ [登录] 登录失败：${brief(res?.msg || res)}`);
      return false;
    }
    this.token = token;
    saveCacheEntry(this.ck, { access_token: token });
    console.log(`   ✅ [登录] 登录成功（已写入缓存）`);
    return true;
  }

  async fetchScore({ strict = false } = {}) {
    const res = await this.request('/user/member/info', {});
    if (Number(res?.code) === 200) {
      const score = res?.data?.currentScore;
      return { ok: true, score: score === undefined || score === null ? null : Number(score) || score, raw: res };
    }
    const msg = String(res?.msg || brief(res));
    if (isAuthError(res?.code, msg)) throw authError(`积分接口：${msg}`);
    if (strict) throw new Error(`积分接口：${msg}`);
    console.log(`   ⚠️ [积分] 查询失败：${msg}`);
    return { ok: false, score: null, raw: res };
  }

  async validateCache() {
    const info = await this.fetchScore({ strict: true });
    return info.score;
  }

  async signIn() {
    const res = await this.request('/coupon/auth/signIn', { miniappId: MINIAPP_ID });
    const msg = String(res?.msg || '');
    if (Number(res?.code) === 200) {
      const toast = res?.data?.integralToastText || msg || '签到成功';
      console.log(`   ✅ [签到] ${toast}`);
      return { ok: true, already: false, msg: toast };
    }
    if (/已签到|已获得|已签过|重复签到|今日已签/.test(msg)) {
      console.log(`   ℹ️ [签到] ${msg}（今日已签到）`.replace('（今日已签到）（今日已签到）','（今日已签到）'));
      return { ok: true, already: true, msg: msg };
    }
    if (isAuthError(res?.code, msg)) throw authError(`签到接口：${msg || `code=${res?.code}`}`);
    console.log(`   ❌ [签到] 签到失败：${msg || `code=${res?.code}`}`);
    return { ok: false, already: false, msg: msg || `code=${res?.code}` };
  }

  async collect() {
    const res = await this.request('/user/auth/user/collect/record/save', { sceneValue: COLLECT_SCENE });
    const msg = String(res?.msg || '');
    if (Number(res?.code) === 200) {
      const toast = res?.data?.integralToastText || msg || '收藏成功';
      console.log(`   ✅ [收藏] ${toast}`);
      return { ok: true, msg: toast };
    }
    if (/已获取|已领取|已完成|已收藏/.test(msg)) {
      console.log(`   ℹ️ [收藏] ${msg}`);
      return { ok: true, msg: msg };
    }
    if (isAuthError(res?.code, msg)) throw authError(`收藏接口：${msg || `code=${res?.code}`}`);
    console.log(`   ⚠️ [收藏] 收藏结果：${msg || `code=${res?.code}`}`);
    return { ok: false, msg: msg || `code=${res?.code}` };
  }

  async run() {
    const result = {
      index: this.index,
      source: `${this.server}@${this.ref}`,
      name: this.note || this.ref,
      loginSource: '',
      scoreBefore: null,
      scoreAfter: null,
      delta: 0,
      signMsg: '-',
      collectMsg: '-',
      success: false,
      error: '',
    };

    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        // ---------- ① 先用缓存，开跑前校验 ----------
        if (attempt === 0 && !this.token) {
          const entry = readCacheEntry(this.ck, { raw: this.raw, server: this.server, ref: this.ref });
          if (entry.access_token) {
            this.token = entry.access_token;
            console.log(`   💾 [缓存] 复用已保存的登录 token（${shortToken(this.token)}）`);
            try {
              result.scoreBefore = await this.validateCache();
              result.loginSource = '缓存';
              console.log('   ✅ [校验] 缓存 token 可用（积分接口通过）');
              console.log(`   💰 [积分] 当前 ${result.scoreBefore ?? '未知'} 分`);
            } catch (e) {
              if (!e.tokenInvalid) {
                console.log(`   ⚠️ [校验] 缓存 token 校验异常：${e.message}`);
                result.error = `缓存 token 校验失败：${e.message}`;
                return result;
              }
              console.log(`   ♻️ [缓存] token 已失效，清理缓存后重新登录`);
              dropCacheEntry(this.ck);
              this.token = '';
            }
          }
        }

        // ---------- ② 重新登录 ----------
        if (!this.token) {
          if (!await this.login()) {
            result.error = '登录失败（取码或换取 token 未通过，见上方日志）';
            console.log('   ❌ [登录] 失败，跳过该账号');
            return result;
          }
          result.loginSource = '新登录';
          result.scoreBefore = await this.validateCache();
          console.log(`   💰 [积分] 当前 ${result.scoreBefore ?? '未知'} 分`);
        }

        // ---------- ③ 签到 + 收藏 ----------
        const sign = await this.signIn();
        result.signMsg = sign.msg;
        const collect = await this.collect();
        result.collectMsg = collect.msg;

        // ---------- ④ 执行中失效 → 清缓存重登重跑 ----------
        await sleep(600);

        // ---------- ⑤ 复查积分 ----------
        try {
          const info = await this.fetchScore();
          result.scoreAfter = info.ok ? info.score : result.scoreBefore;
        } catch (e) {
          if (e.tokenInvalid && attempt === 0) {
            console.log('   🔄 [重试] 执行中登录态失效，清理缓存重登后重跑一次');
            dropCacheEntry(this.ck);
            this.token = '';
            continue;
          }
          console.log(`   ⚠️ [积分] 最终积分获取失败：${e.message}`);
          result.scoreAfter = result.scoreBefore;
        }

        if (result.scoreBefore !== null && result.scoreAfter !== null) {
          result.delta = Number(result.scoreAfter) - Number(result.scoreBefore);
          console.log(`   💰 [积分] ${result.scoreBefore} → ${result.scoreAfter}（${result.delta >= 0 ? '+' : ''}${result.delta}）`);
        } else {
          console.log(`   💰 [积分] 当前 ${result.scoreAfter ?? '未知'} 分`);
        }

        result.success = sign.ok;
        if (sign.ok) {
          console.log('   ✅ [完成] 该账号任务执行完成');
        } else {
          result.error = `签到失败：${sign.msg}`;
          console.log('   ⚠️ [完成] 签到未成功');
        }
        return result;
      } catch (e) {
        if (e.tokenInvalid && attempt === 0) {
          console.log(`   🔄 [重试] 登录态失效（${e.message}），清理缓存重登后重跑一次`);
          dropCacheEntry(this.ck);
          this.token = '';
          await sleep(1500);
          continue;
        }
        console.log(`   ❌ [异常] ${e.message}`);
        result.error = e.message;
        return result;
      }
    }

    result.error = result.error || '重试后仍未完成（详见上方日志）';
    return result;
  }
}

// ====================== 通知 ======================
function buildNotify(results) {
  const lines = [`### ${APP_NAME} 每日签到`];
  for (const r of results) {
    const flag = r.success ? '✅' : '❌';
    lines.push('');
    lines.push(`#### ${flag} 账号 ${r.index} · ${r.source}`);
    if (r.loginSource) {
      lines.push(`- 登录：${r.loginSource === '缓存' ? '缓存复用' : '新登录'}`);
      lines.push(`- 签到：${r.signMsg || '无结果'}`);
      lines.push(`- 收藏：${r.collectMsg || '无结果'}`);
      lines.push(`- 积分：${r.scoreBefore ?? '未知'} → ${r.scoreAfter ?? '未知'}（${r.delta >= 0 ? '+' : ''}${r.delta}）`);
    }
    if (!r.success) lines.push(`- 失败原因：${r.error || '未知'}`);
  }
  return lines.join('\n');
}

function sendQingLongNotify(title, content) {
  if (!NOTIFY_ENABLED) {
    console.log('   ℹ️ [通知] SDL_NOTIFY=0，已关闭通知');
    return false;
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
    sender(os.environ['SDL_NOTIFY_TITLE'], os.environ['SDL_NOTIFY_CONTENT'])
    print('notify.py调用完成')
    sys.exit(0)
print('未找到可用的青龙notify.py', file=sys.stderr)
sys.exit(2)
`;
  try {
    const result = spawnSync(process.env.PYTHON_BIN || 'python3', ['-c', py], {
      encoding: 'utf8',
      timeout: 120000,
      env: { ...process.env, SDL_NOTIFY_TITLE: title, SDL_NOTIFY_CONTENT: content },
    });
    if (result.status === 0) {
      console.log('   📨 [通知] 已通过青龙 notify.py 推送');
      return true;
    }
    console.log(`   ⚠️ [通知] 青龙通知失败（不影响任务）：${brief(result.stderr || result.stdout || `exit ${result.status}`, 150)}`);
  } catch (e) {
    console.log(`   ⚠️ [通知] 青龙通知异常（不影响任务）：${e.message}`);
  }
  return false;
}

async function sendPushPlus(title, content) {
  if (!NOTIFY_ENABLED) return;
  if (!PLUSPLUS_TOKEN) {
    console.log('   ℹ️ [推送] 未配置 PLUSPLUS_TOKEN，跳过 PushPlus');
    return;
  }
  try {
    await axios.post('https://www.pushplus.plus/send', {
      token: PLUSPLUS_TOKEN, title, content, template: 'txt',
    }, { timeout: 10000, proxy: false });
    console.log('   📨 [推送] PushPlus 推送成功');
  } catch (e) {
    console.log(`   ⚠️ [推送] PushPlus 推送失败：${e.message}`);
  }
}

// ====================== 主入口 ======================
(async () => {
  const raw = process.env.YYB_SERVER || '';
  if (!raw.trim()) {
    boxTop(`🥃 ${APP_NAME} 自动签到`);
    boxLine('⚠️ 状态', '未配置 YYB_SERVER');
    boxBottom();
    console.log('格式：YYB Go 地址@微信账号标识，多账号每行一条，可带 #备注');
    process.exitCode = 1;
    return;
  }

  let accounts;
  try {
    accounts = parseAccounts(raw);
  } catch (e) {
    boxTop(`🥃 ${APP_NAME} 自动签到`);
    boxLine('❌ 配置', e.message);
    boxBottom();
    process.exitCode = 1;
    return;
  }

  boxTop(`🥃 ${APP_NAME} 自动签到`);
  boxLine('🕒 启动时间', nowText());
  boxLine('🔢 账号数量', `${accounts.length} 个`);
  boxLine('💾 缓存', 'token_caches/sdl_token_cache.json');
  boxBottom();

  const results = [];
  for (let i = 0; i < accounts.length; i++) {
    const account = accounts[i];
    const title = `标识 ${account.ref}` + (account.note ? `（${account.note}）` : '');
    accountFrame(i + 1, accounts.length, title, `${account.server}@${account.ref}`);

    const client = new SanDeLi(account, i + 1);
    let result;
    try {
      result = await client.run();
    } catch (e) {
      result = {
        index: i + 1,
        source: `${account.server}@${account.ref}`,
        name: account.note || account.ref,
        loginSource: '',
        scoreBefore: null,
        scoreAfter: null,
        delta: 0,
        signMsg: '-',
        collectMsg: '-',
        success: false,
        error: `执行异常：${e.message}`,
      };
      console.log(`   ❌ [异常] 该账号执行异常：${e.message}`);
    }
    results.push(result);
    hr();

    if (i < accounts.length - 1) {
      console.log('   ⏳ 等待2秒后执行下一个账号...');
      await sleep(2000);
    }
  }

  console.log('');
  for (const r of results) {
    const icon = r.success ? '✅' : '❌';
    const title = `【账号 ${r.index} · ${r.source}${r.name && r.name !== r.source ? `（${r.name}）` : ''}】`;
    console.log(`${icon} ${title}`);
    if (r.loginSource) {
      console.log(`   🔐 [登录] ${r.loginSource === '缓存' ? '缓存复用' : '新登录'}`);
      console.log(`   📅 [签到] ${r.signMsg || '-'}`);
      console.log(`   ⭐ [收藏] ${r.collectMsg || '-'}`);
      console.log(`   💰 [积分] ${r.scoreBefore ?? '未知'} → ${r.scoreAfter ?? '未知'}（${r.delta >= 0 ? '+' : ''}${r.delta}）`);
    }
    if (!r.success) console.log(`   ⚠️ [失败] ${r.error || '未知原因'}`);
  }

  const okCount = results.filter((r) => r.success).length;
  const failCount = results.length - okCount;
  const totalDelta = results.reduce((sum, r) => sum + (r.success ? Number(r.delta) || 0 : 0), 0);

  boxTop(`🏁 ${APP_NAME} 执行汇总`);
  boxLine('📊 执行结果', `成功 ${okCount} / 失败 ${failCount} / 共 ${results.length}`);
  boxLine('💰 积分变化', `${totalDelta >= 0 ? '+' : ''}${totalDelta}`);
  boxBottom();

  const content = buildNotify(results);
  sendQingLongNotify(`${APP_NAME}每日签到`, content);
  await sendPushPlus(`${APP_NAME}每日签到`, content);

  if (failCount > 0) process.exitCode = 1;
})().catch((e) => console.log(`❌ 脚本异常: ${e.message}`));
