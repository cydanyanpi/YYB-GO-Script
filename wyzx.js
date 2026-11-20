// YYB-Go-Enhanced 适配说明：配置多行 YYB_SERVER=地址@账号标识；通知使用青龙 sendNotify。
// ===== YYB-Go-Enhanced + QingLong standalone adapter =====
function _yybRoutes() {
    const routes = String(process.env.YYB_SERVER || '').split(/\r?\n/)
        .map(v => v.trim()).filter(Boolean).map((line, index) => {
            const at = line.lastIndexOf('@');
            if (at <= 0 || at >= line.length - 1) {
                throw new Error(`YYB_SERVER 第 ${index + 1} 行格式错误，应为 地址@账号标识`);
            }
            let server = line.slice(0, at).trim().replace(/\/+$/, '');
            if (!/^https?:\/\//i.test(server)) server = `http://${server}`;
            const refRaw = line.slice(at + 1).trim();
            const hash = refRaw.indexOf('#');
            const ref = (hash >= 0 ? refRaw.slice(0, hash) : refRaw).trim();
            const note = (hash >= 0 ? refRaw.slice(hash + 1) : '').trim();
            return { server, ref, note };
        });
    if (!routes.length) throw new Error('未配置 YYB_SERVER（每行：地址@账号标识）');
    return routes;
}

function _yybCleanRef(value) {
    return String(value || '').split('#')[0].replace(/^(wx|yyb|wmpf|syzs):/i, '').trim();
}

function _yybRouteFor(identifier) {
    const routes = _yybRoutes();
    const wanted = _yybCleanRef(identifier);
    const exact = routes.find(x => _yybCleanRef(x.ref) === wanted);
    if (exact) return exact;
    if (/^\d+$/.test(wanted) && routes[Number(wanted) - 1]) return routes[Number(wanted) - 1];
    if (routes.length === 1) return routes[0];
    throw new Error(`YYB_SERVER 中找不到账号标识：${wanted || '(空)'}`);
}

function _yybAuthHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    const token = String(process.env.YYB_API_KEY || '').trim() || String(process.env.YYB_PROTOCOL_TOKEN || '').trim();
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
}

async function getSingleCode(appId, identifier) {
    const route = _yybRouteFor(identifier);
    const response = await globalThis.fetch(`${route.server}/wxapp/getCode`, {
        method: 'POST',
        headers: _yybAuthHeaders(),
        body: JSON.stringify({ ref: route.ref, app_id: appId }),
        signal: AbortSignal.timeout ? AbortSignal.timeout(30000) : undefined,
    });
    const body = await response.json().catch(() => null);
    // YYB 可能把 code 返回成字符串 "0"，统一按数字比较
    if (!body || Number(body.code) !== 0) {
        throw new Error(`/wxapp/getCode 返回失败：${body?.msg || body?.message || JSON.stringify(body)}`);
    }
    const code = body.data?.result?.code || body.data?.code;
    if (!code) throw new Error('/wxapp/getCode 未返回 code');
    return code;
}
global.getSingleCode = getSingleCode;
// ===== adapter end =====

// name: 丸丫甄选
// cron: 18 8 * * *
/*
------------------------------------------
@Author: sm
@Date: 2026.08.16
@Description: 丸丫甄选（有赞微商城）每日签到得积分
------------------------------------------
变量：
  YYB_SERVER     YYB-Go-Enhanced 路由，每行：地址@账号标识[#备注]
  YYB_API_KEY / YYB_PROTOCOL_TOKEN    启用协议鉴权时配置，二选一
  WYZX_NOTIFY    默认1，0=关闭青龙 notify.py 汇总通知
------------------------------------------
接口契约（h5.youzan.com，有赞 SaaS 通用签到，与本仓库 yz19.js 同一套）：
  静默登录 POST /wscshop/weapp/authorize.json  {appId, clientBiz, code}
        -> {accessToken|access_token, sessionId, kdtId, ...}
  签到活动 GET  /wscump/checkin/show_checkin_page_v2.json -> {checkinId, isShow}
  执行签到 GET  /wscump/checkin/checkinV2.json?checkinId=<id>
        -> {desc, list[{infos:{title}}]}；重复签到报「已达最大参与次数」
  积分余额 GET  /wscump/integral/user_points.json -> {current_points|real_points}
  公共 query：app_id / kdt_id / access_token；公共头：Extra-Data(sid/version/...)
  统一响应：code==0 成功，否则 msg 为错误原因
------------------------------------------
常量来源（反编译 wx35322299c6492f6e 主包）：
  kdtId=100939936、userVersion=2.219.11.101
------------------------------------------
*/

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const fetchFn = globalThis.fetch || ((...args) => import('node-fetch').then(({ default: f }) => f(...args)));

const MINI_APP_ID = 'wx35322299c6492f6e';
const CLIENT_BIZ = 'weapp_wsc';
const KDT_ID = '100939936';
const USER_VERSION = '2.219.11.101';
const PAGE_VERSION = '0'; // Referer 里的版本号，仅用于伪装来源，不参与校验
const API_BASE = 'https://h5.youzan.com';
const USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF';

// 缓存：脚本目录 token_caches/，按 地址|标识 隔离，不设固定过期
const CACHE_DIR = path.join(__dirname, 'token_caches');
const CACHE_FILE = path.join(CACHE_DIR, 'wyzx_token_cache.json');
const NOTIFY_ENABLED = (process.env.WYZX_NOTIFY || '1') !== '0';

// ===================== 日志美化 =====================
const BOX_WIDTH = 48;
const BOX_INNER = 46;
const LOG_WIDTH = 48;

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
    console.log('-'.repeat(LOG_WIDTH));
}

function truncText(s, max = 100) {
    const str = String(s ?? '');
    return str.length <= max ? str : `${str.slice(0, max - 1)}…`;
}

function maskMiddle(s, left = 8, right = 6) {
    const str = String(s || '');
    if (!str) return '-';
    if (str.length <= left + right + 3) return str;
    return `${str.slice(0, left)}…${str.slice(-right)}`;
}

function maskPhone(phone = '') {
    return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, '$1****$2');
}

function brief(v, max = 100) {
    if (v === undefined || v === null) return '';
    return truncText(typeof v === 'string' ? v : JSON.stringify(v), max);
}

function logInfo(msg) { console.log(`   ℹ️ ${msg}`); }
function logOk(msg) { console.log(`   ✅ ${msg}`); }
function logWarn(msg) { console.log(`   ⚠️ ${msg}`); }
function logErr(msg) { console.log(`   ❌ ${msg}`); }
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// ===================== 缓存（不过期，失效自动重登） =====================
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

// ===================== 错误判定 =====================
// 只认明确的凭证类提示，避免把业务错误误判成登录失效
const AUTH_HINTS = [
    'access_token', 'token失效', 'token无效', 'token已失效', '未登录', '登录已失效',
    '重新授权', 'invalid session', 'invalid token', 'unauthorized', '401', '403', '会话已失效',
];

function authError(message) {
    const err = new Error(message);
    err.authFailed = true;
    return err;
}

function isAuthText(text) {
    const value = String(text || '');
    const lower = value.toLowerCase();
    return AUTH_HINTS.some((hint) => lower.includes(hint.toLowerCase()));
}

function isRepeatCheckin(message) {
    return /已达最大参与次数|已签到|重复签到|今日已参与|已经签到|今日签到已完成/.test(String(message || ''));
}

// ===================== 账号解析 =====================
function parseAccounts() {
    const routes = _yybRoutes();
    return routes.map((x) => ({ server: x.server, ref: x.ref, note: x.note || '' }));
}

const ENV_NAME = 'wyzx';
const accounts = parseAccounts();

// ===================== 取码 =====================
async function getWxCode(ref) {
    try {
        const code = await getSingleCode(MINI_APP_ID, ref);
        if (!code || typeof code !== 'string') throw new Error(`未返回有效 code: ${brief(code)}`);
        return code;
    } catch (e) {
        throw new Error(`YYB 取码失败（${ref}）：${e.message || e}（检查 YYB_SERVER 地址与服务是否在线）`);
    }
}

// ===================== HTTP =====================
async function httpRequest({ method = 'GET', url, params = {}, data, headers = {}, timeout = 15000 }) {
    const target = new URL(url);
    for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null && value !== '') target.searchParams.append(key, String(value));
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
        const response = await fetchFn(target.toString(), {
            method,
            headers,
            body: data === undefined ? undefined : JSON.stringify(data),
            signal: controller.signal,
            redirect: 'follow',
        });
        const raw = await response.text();
        let body = raw;
        try { body = raw ? JSON.parse(raw) : {}; } catch { /* 保留原始文本 */ }
        const setCookie = typeof response.headers.getSetCookie === 'function'
            ? response.headers.getSetCookie()
            : (response.headers.get('set-cookie') ? [response.headers.get('set-cookie')] : []);
        return { status: response.status, body, setCookie };
    } finally {
        clearTimeout(timer);
    }
}

class Task {
    constructor(account, index) {
        this.account = account;
        this.index = index;
        this.ref = account.ref;
        this.token = '';
        this.sessionId = '';
        this.kdtId = KDT_ID;
        this.cookie = '';
        this.userInfo = {};
        this.tokenSource = '';
        this.before = null;
        this.after = null;
        this.signMsg = '';
        this.signFailed = false;
        this.checkinId = '';
        this.signedBefore = false;
    }

    clearAuth() {
        this.token = '';
        this.sessionId = '';
        this.cookie = '';
        this.tokenSource = '';
    }

    applyEntry(entry = {}) {
        this.token = entry.accessToken || entry.token || '';
        this.sessionId = entry.sessionId || '';
        this.kdtId = String(entry.kdtId || KDT_ID);
        this.cookie = entry.cookie || '';
        // 缓存里顺带存了昵称/手机号，复用登录态时也能展示用户信息
        this.userInfo = { nick_name: entry.nickName || '', mobile: entry.mobile || '' };
    }

    applyLogin(data = {}) {
        this.token = data.accessToken || data.access_token || '';
        this.sessionId = data.sessionId || data.session_id || this.sessionId || '';
        this.kdtId = String(data.kdtId || data.kdt_id || KDT_ID);
        this.userInfo = data || {};
    }

    getHeaders(extra = {}) {
        const headers = {
            'User-Agent': USER_AGENT,
            'Referer': `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            'Accept': '*/*',
            'Extra-Data': JSON.stringify({
                sid: this.sessionId || '',
                version: USER_VERSION,
                clientType: 'weapp-miniprogram',
                client: 'weapp',
                bizEnv: 'wsc',
            }),
            ...extra,
        };
        if (this.cookie) headers.Cookie = this.cookie;
        return headers;
    }

    baseParams(params = {}) {
        return { app_id: MINI_APP_ID, kdt_id: this.kdtId, access_token: this.token, ...params };
    }

    async api({ method = 'GET', path: apiPath, params = {}, data, auth = true, timeout = 15000 }) {
        const url = `${API_BASE}${apiPath.startsWith('/') ? apiPath : `/${apiPath}`}`;
        const headers = this.getHeaders(method === 'POST' ? { 'Content-Type': 'application/json' } : {});
        const res = await httpRequest({
            method,
            url,
            params: auth ? this.baseParams(params) : params,
            data,
            headers,
            timeout,
        });

        if (res.setCookie && res.setCookie.length) {
            this.cookie = res.setCookie.map((item) => item.split(';')[0]).join('; ');
        }
        if (res.status === 401 || res.status === 403) throw authError(`HTTP ${res.status}：${brief(res.body, 60)}`);
        if (res.status !== 200) throw new Error(`HTTP ${res.status}：${brief(res.body, 80)}`);

        let body = res.body;
        if (typeof body === 'string') {
            try { body = JSON.parse(body); } catch { /* 保持原样 */ }
        }
        if (!body || typeof body !== 'object') throw new Error(`接口返回非 JSON：${brief(body, 80)}`);

        const code = Number(body.code);
        const msg = body.msg || body.message || '';
        if (code !== 0) {
            if (isAuthText(msg) || [401, 403, 135000025, 160210092].includes(code)) {
                throw authError(msg || `code=${body.code}`);
            }
            throw new Error(msg || `接口返回 code=${body.code}`);
        }
        return body.data;
    }

    async getPoints() {
        const data = await this.api({ path: '/wscump/integral/user_points.json' });
        const points = data?.current_points ?? data?.real_points;
        if (points === undefined || points === null || points === '') {
            throw new Error('积分接口未返回 current_points / real_points');
        }
        return Number(points);
    }

    async login() {
        let data = null;
        let lastError = null;
        // code 一次性有效，换 token 偶发失败（135000025/160210092 等）时重新取码重试一次
        for (let attempt = 0; attempt < 2; attempt++) {
            const code = await getWxCode(this.ref);
            try {
                data = await this.api({
                    method: 'POST',
                    path: '/wscshop/weapp/authorize.json',
                    auth: false,
                    data: { appId: MINI_APP_ID, clientBiz: CLIENT_BIZ, code },
                });
                break;
            } catch (e) {
                lastError = e;
                if (attempt === 0 && /135000025|160210092|code|重新登/i.test(String(e.message || e))) {
                    logWarn(`[登录] 换取 token 失败（${truncText(e.message || e, 60)}），重新取码重试一次`);
                    await sleep(1000);
                    continue;
                }
                throw authError(`静默登录失败：${e.message || e}`);
            }
        }
        if (!data) throw authError(`静默登录失败：${lastError?.message || lastError || '未知错误'}`);

        this.applyLogin(data);
        if (!this.token) throw authError(`登录响应未包含 accessToken：${brief(data, 80)}`);

        saveCacheEntry(cacheKey(this.account.server, this.ref), {
            accessToken: this.token,
            sessionId: this.sessionId,
            kdtId: this.kdtId,
            cookie: this.cookie,
            mobile: this.userInfo.mobile || '',
            nickName: this.userInfo.nick_name || this.userInfo.nickName || '',
        });

        const nick = this.userInfo.nick_name || this.userInfo.nickName || '';
        const phone = maskPhone(this.userInfo.mobile || '');
        logOk(`[登录] 登录成功 ${[nick, phone].filter(Boolean).join(' / ') || '(未返回昵称)'} | token ${maskMiddle(this.token)}`);
    }

    async checkin() {
        let page;
        try {
            page = await this.api({ path: '/wscump/checkin/show_checkin_page_v2.json' });
        } catch (e) {
            if (e?.authFailed) throw e;
            this.signMsg = `获取签到活动失败：${e.message || e}`;
            this.signFailed = true;
            logErr(`[签到] ${this.signMsg}`);
            return;
        }

        this.checkinId = page?.checkinId || '';
        const isShow = !!page?.isShow;
        this.signedBefore = page?.todayCheckin === true || page?.isCheckin === true || page?.hasCheckinToday === true;
        logInfo(`[签到] 签到活动 checkinId=${this.checkinId || '未获取'} | 展示=${isShow ? '是' : '否'}${this.signedBefore ? ' | 今日已签' : ''}`);

        if (!this.checkinId) {
            this.signMsg = '未获取到 checkinId，跳过签到';
            this.signFailed = true;
            logWarn(`[签到] ${this.signMsg}`);
            return;
        }
        if (this.signedBefore) {
            this.signMsg = '今日已签到';
            logInfo(`[签到] ${this.signMsg}`);
            return;
        }

        try {
            const data = await this.api({ path: '/wscump/checkin/checkinV2.json', params: { checkinId: this.checkinId } });
            const awards = (data?.list || []).map((item) => item?.infos?.title).filter(Boolean).join(', ');
            this.signMsg = `${data?.desc || '签到成功'}${awards ? `（${awards}）` : ''}`;
            logOk(`[签到] ${this.signMsg}`);
        } catch (e) {
            if (e?.authFailed) throw e;
            if (isRepeatCheckin(e.message)) {
                this.signMsg = '今日已签到（服务端提示重复签到）';
                logInfo(`[签到] ${this.signMsg}`);
                return;
            }
            this.signMsg = `签到失败：${e.message || e}`;
            this.signFailed = true;
            logErr(`[签到] ${this.signMsg}`);
        }
    }

    async run() {
        const ck = cacheKey(this.account.server, this.ref);

        for (let attempt = 0; attempt < 2; attempt++) {
            try {
                // ① 首次尝试复用缓存 token
                if (attempt === 0) {
                    const entry = readCache()[ck];
                    if (entry && (entry.accessToken || entry.token)) {
                        this.applyEntry(entry);
                        logInfo(`[缓存] 复用已保存的登录 token（${maskMiddle(this.token)}）`);
                        try {
                            this.before = await this.getPoints();
                            this.tokenSource = '缓存';
                        } catch (e) {
                            if (e?.authFailed) {
                                logInfo('[缓存] token 已失效，清理后重新登录');
                                dropCacheEntry(ck);
                                this.clearAuth();
                            } else {
                                throw e; // 网络/业务异常：保留缓存，直接报错
                            }
                        }
                    }
                }

                // ② 没有可用 token → 重新登录
                if (this.tokenSource !== '缓存') {
                    await this.login();
                    this.tokenSource = '新登录';
                    this.before = await this.getPoints();
                }

                // ③ 登录行下面直接显示当前积分
                logInfo(`[积分] 当前 ${this.before} 分`);

                // ④ 签到 + 复查积分
                await this.checkin();
                this.after = await this.getPoints();
                const gained = this.after - this.before;

                if (this.signFailed) logWarn('[完成] 流程结束，但签到未成功');
                else logOk('[完成] 该账号任务执行完成');
                console.log(`   💰 [积分] ${this.before} → ${this.after}（${gained >= 0 ? '+' : ''}${gained}）`);
                return {
                    success: !this.signFailed,
                    error: this.signFailed ? this.signMsg : '',
                    tokenSource: this.tokenSource,
                    user: [this.userInfo.nick_name || this.userInfo.nickName || '', maskPhone(this.userInfo.mobile || '')].filter(Boolean).join(' / '),
                    signMsg: this.signMsg,
                    before: this.before,
                    after: this.after,
                    gained,
                };
            } catch (e) {
                if (e?.authFailed && attempt === 0) {
                    logWarn('[重试] 登录态失效，清理缓存重登后重跑一次');
                    dropCacheEntry(ck);
                    this.clearAuth();
                    await sleep(1500);
                    continue;
                }
                throw e;
            }
        }

        throw new Error('重试后仍未完成（详见上方日志）');
    }
}

// ===================== 青龙通知 =====================
function sendQingLongNotify(title, content) {
    if (!NOTIFY_ENABLED) {
        logInfo('WYZX_NOTIFY=0，已关闭通知');
        return;
    }
    const py = String.raw`
import importlib.util, os, sys
paths = ['/ql/data/scripts/notify.py', '/ql/scripts/notify.py', '/ql/data/notify.py', os.path.join(os.getcwd(), 'notify.py')]
for candidate in paths:
    if not os.path.isfile(candidate):
        continue
    try:
        spec = importlib.util.spec_from_file_location('ql_notify', candidate)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sender = getattr(module, 'send', None) or getattr(module, 'sendNotify', None)
        if not callable(sender):
            continue
        sender(os.environ['WYZX_NOTIFY_TITLE'], os.environ['WYZX_NOTIFY_CONTENT'])
        print('notify.py调用完成')
        sys.exit(0)
    except Exception as exc:
        continue
print('未找到可用的青龙notify.py', file=sys.stderr)
sys.exit(2)
`;
    try {
        const result = spawnSync(process.env.PYTHON_BIN || 'python3', ['-c', py], {
            encoding: 'utf8',
            timeout: 120000,
            env: { ...process.env, WYZX_NOTIFY_TITLE: title, WYZX_NOTIFY_CONTENT: content },
        });
        if (result.status === 0) logOk('[通知] 青龙通知模块调用完成（送达情况以通知渠道为准）');
        else logWarn(`[通知] 青龙通知失败（不影响任务结果）：${truncText(result.stderr || result.stdout || `exit ${result.status}`, 120)}`);
    } catch (e) {
        logWarn(`[通知] 青龙通知异常（不影响任务结果）：${e.message || e}`);
    }
}

// ===================== 主流程 =====================
(async () => {
    boxTop('🍬 丸丫甄选 每日签到');
    boxLine('🕒 启动时间', nowText());
    boxLine('🔢 账号数量', `${accounts.length} 个`);
    boxLine('💾 缓存', 'token_caches/wyzx_token_cache.json');
    boxBottom();

    const results = [];

    for (let i = 0; i < accounts.length; i++) {
        const account = accounts[i];
        accountFrame(i + 1, accounts.length, `标识 ${account.ref}${account.note ? `（${account.note}）` : ''}`, `${account.server}@${account.ref}`);

        try {
            const summary = await new Task(account, i + 1).run();
            results.push({ index: i + 1, account, ...summary });
        } catch (e) {
            logErr(`[失败] ${truncText(e.message || e, 120)}`);
            results.push({ index: i + 1, account, success: false, error: truncText(e.message || e, 120) });
        }

        hr();
        if (i < accounts.length - 1) {
            console.log('   ⏳ 等待2秒后执行下一个账号...');
            await sleep(2000);
        }
    }

    // ---------- 逐账号明细（汇总框上方） ----------
    for (const res of results) {
        const title = `【账号 ${res.index} · ${res.account.server}@${res.account.ref}${res.account.note ? `（${res.account.note}）` : ''}】`;
        console.log(`${res.success ? '✅' : '❌'} ${title}`);
        if (res.tokenSource) {
            console.log(`   🔐 [登录] ${res.tokenSource === '缓存' ? '缓存复用' : '新登录'}`);
            console.log(`   👤 [用户] ${res.user || '(未返回昵称/手机号)'}`);
            console.log(`   📅 [签到] ${res.signMsg || '未获取到签到结果'}`);
            console.log(`   💰 [积分] ${res.before} → ${res.after}（${res.gained >= 0 ? '+' : ''}${res.gained}）`);
        }
        if (!res.success) console.log(`   ⚠️ [失败] ${res.error || '未知原因'}`);
        console.log('');
    }

    const okCount = results.filter((r) => r.success).length;
    const failedCount = results.length - okCount;
    const totalGained = results.reduce((sum, r) => sum + (r.success ? r.gained : 0), 0);

    boxTop('🏁 丸丫甄选 执行汇总');
    boxLine('✅ 成功账号', `${okCount} / ${results.length}`);
    boxLine('❌ 失败账号', `${failedCount} / ${results.length}`);
    boxLine('💰 今日总新增', `${totalGained} 积分`);
    boxLine('🕒 结束时间', nowText());
    boxBottom();

    const notifyContent = [
        '### 丸丫甄选每日签到',
        ...results.flatMap((res) => {
            const head = `\n#### 账号 ${res.index} · ${res.account.server}@${res.account.ref}`;
            if (!res.tokenSource) return [head, `- 失败原因：${res.error}`];
            return [
                head,
                `- 登录：${res.tokenSource === '缓存' ? '缓存复用' : '新登录'}`,
                `- 用户：${res.user || '未返回'}`,
                `- 签到：${res.signMsg || '未获取到签到结果'}`,
                `- 积分：${res.before} → ${res.after}（${res.gained >= 0 ? '+' : ''}${res.gained}）`,
                ...(res.success ? [] : [`- 结果：${res.error}`]),
            ];
        }),
    ].join('\n');

    sendQingLongNotify('丸丫甄选', notifyContent);
    if (failedCount > 0) process.exitCode = 1;
})().catch((e) => {
    console.log(`❌ 程序异常: ${e.message || e}`);
    process.exitCode = 1;
});
//（注：内容由AI生成）
