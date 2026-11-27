#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: iQOO社区
# version: v1.0.2
# cron: 20 8,20 * * *

"""
iQOO社区小程序积分 动态 code 版

功能：
  1. 四端口本地服务获取微信 code
  2. /v3/users/vivo/mini 使用 code 换 token
  3. 获取用户信息
  4. 每日任务（浏览/点赞/分享/评论/发帖删除）
  5. 抽奖
  6. 签到
  7. PushPlus 推送
  8. 品赞代理，业务请求优先代理，失败直连兜底

环境变量：
  YYB_SERVER        YYB Go 服务地址，格式：地址@微信账号标识，多账号换行分隔
  PLUSPLUS_TOKEN    PushPlus token，可选
  PROXY_API         品赞代理提取 API，可选
  PROXY_TYPE        http / socks5，默认 http

依赖：
  pip install requests
  socks5 代理需：
  pip install requests[socks]
"""

import hashlib
import hmac
import json
import os
import random
import re
import time
import base64
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests


APP_NAME = "iQOO社区小程序"
VERSION = "v1.0.2"

MINI_APP_ID = "wxcf4266fbc9463132"
PAGE_VERSION = "256"
API_BASE = "https://bbs-api.iqoo.com/api/"
SIGN_SECRET = "2618194b0ebb620055e19cf9811d3c13"
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(_SCRIPT_DIR, "token_caches", "iqoo_token_cache.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf254173b) XWEB/19027"
)

_YYB_SERVER_RAW = os.getenv("YYB_SERVER", "")
SERVERS = [line.strip() for line in _YYB_SERVER_RAW.splitlines() if line.strip()]
if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识，多账号换行分隔）")
    exit(1)

PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "https://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30
_user_idx = 0


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sleep(seconds):
    time.sleep(seconds)


def log(*args):
    print(*args, flush=True)


BOX_WIDTH = 48
BOX_INNER = 46


def _display_width(text):
    width = 0
    for ch in str(text):
        code = ord(ch)
        if code in (0xfe0f, 0xfe0e, 0x200d):
            continue
        width += 2 if code > 0xff else 1
    return width


def _pad(text, width):
    text = str(text)
    while _display_width(text) > width:
        text = text[:-1]
    return text + " " * max(0, width - _display_width(text))


def box_top(title):
    print()
    print("╔" + "═" * BOX_WIDTH + "╗")
    print("║  " + _pad(title, BOX_INNER) + "║")


def box_line(label, value):
    print("║  " + _pad(f"{label}: {value}", BOX_INNER) + "║")


def box_bottom():
    print("╚" + "═" * BOX_WIDTH + "╝")


def account_frame(index, total, title, source):
    print()
    print("┌" + "─" * BOX_WIDTH + "┐")
    print("│  " + _pad(f"🧩 账号 {index} / {total}　{title}", BOX_INNER) + "│")
    print("│  " + _pad(f"🔗 来源: {source}", BOX_INNER) + "│")
    print("└" + "─" * BOX_WIDTH + "┘")


def hr():
    print()
    print("-" * BOX_WIDTH)


def to_number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_points(value):
    return str(value) if value is not None else "未知"

def mask_name(value):
    text = str(value or "")
    return f"{text[:4]}***{text[-3:]}" if len(text) > 10 else text


def short_token(token=""):
    value = str(token or "").replace("Bearer ", "", 1)
    return f"{value[:6]}***{value[-6:]}" if value else ""


def is_success(result):
    try:
        return int(result.get("Code", -1)) == 0
    except (TypeError, ValueError):
        return False


def is_token_error(message):
    """只认明确的登录凭证失效提示，避免把业务失败误判成 token 失效而删缓存。"""
    pattern = (
        r"-4011|\b401\b|\b403\b"
        r"|token\s*(失效|无效|过期|不存在|错误)"
        r"|(登录|登录态|凭证|授权)\s*(失效|过期|无效|已过期|异常)"
        r"|请先登录|未登录|跳转到登录页|访客没有权限|重新登录"
    )
    return bool(re.search(pattern, str(message or ""), re.I))


def json_preview(data, limit=800):
    try:
        return json.dumps(data, ensure_ascii=False)[:limit]
    except Exception:
        return str(data)[:limit]


def read_token_cache():
    try:
        if not os.path.exists(TOKEN_CACHE_FILE):
            return {}
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_token_cache(cache):
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"   ⚠️ [缓存] 保存失败（不影响本次执行）：{exc}")


def cache_key(server, ref):
    """缓存键：地址|标识，避免不同 YYB 地址下同名标识串号。"""
    return f"{server}|{ref}"


def read_cache_entry(ck, ref):
    cache = read_token_cache()
    entry = cache.get(ck)
    if isinstance(entry, dict) and entry.get("accessToken"):
        return entry
    # 兼容旧缓存：旧键可能没有协议头，或仅按 ref 存；按标识匹配后迁移到新键
    candidates = [k for k, v in cache.items()
                  if k != ck and isinstance(v, dict) and v.get("accessToken")
                  and (k == ref or str(k).rsplit("|", 1)[-1] == str(ref))]
    if candidates:
        legacy = cache.get(candidates[0])
        cache[ck] = legacy
        cache.pop(candidates[0], None)
        write_token_cache(cache)
        return legacy
    return {}


def save_cache_entry(ck, entry):
    cache = read_token_cache()
    cache[ck] = {**entry, "updatedAt": now_text()}
    write_token_cache(cache)


def drop_cache_entry(ck):
    cache = read_token_cache()
    if ck in cache:
        cache.pop(ck, None)
        write_token_cache(cache)

def direct_session():
    session = requests.Session()
    session.trust_env = False
    return session


def parse_proxy_response(text):
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)

    text = text.strip()
    if not text:
        return None

    try:
        data = json.loads(text)
        proxy_obj = None

        if isinstance(data.get("data"), list) and data["data"]:
            proxy_obj = data["data"][0]
        elif isinstance(data.get("data"), dict):
            proxy_obj = data["data"]
        elif data.get("ip") and data.get("port"):
            proxy_obj = data
        elif isinstance(data.get("result"), dict):
            proxy_obj = data["result"]

        if proxy_obj:
            host = proxy_obj.get("ip") or proxy_obj.get("host")
            port = proxy_obj.get("port")
            if host and port:
                return {
                    "host": str(host),
                    "port": int(port),
                    "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                    "password": proxy_obj.get("pass") or proxy_obj.get("password") or "",
                }
    except Exception:
        pass

    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2:
            return {
                "host": parts[0],
                "port": int(parts[1]),
                "username": parts[2] if len(parts) > 2 else "",
                "password": parts[3] if len(parts) > 3 else "",
            }

    return None


def build_proxy_dict(proxy_info):
    if not proxy_info:
        return None

    host = proxy_info["host"]
    port = proxy_info["port"]
    username = proxy_info.get("username", "")
    password = proxy_info.get("password", "")

    auth = ""
    if username and password:
        auth = f"{quote(username)}:{quote(password)}@"

    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"

    log(f"   🌐 [代理] 生成 {scheme.upper()} 代理 {host}:{port}")

    return {"http": proxy_url, "https": proxy_url}


def validate_proxy(proxies):
    if not proxies:
        return False, ""

    try:
        response = requests.get(PROXY_VALIDATE_URL, proxies=proxies, timeout=15)
        if response.status_code == 200:
            try:
                ip = response.json().get("origin", "未知")
            except Exception:
                ip = "未知"
            log(f"   ✅ [代理] 验证通过，出口 IP: {ip}")
            return True, ip
    except Exception as exc:
        log(f"   ⚠️ [代理] 验证失败：{exc}")

    return False, ""


def get_valid_proxy(server):
    if not PROXY_API:
        log("   🌐 [代理] 未配置 PROXY_API，使用直连")
        return None, ""

    log("   🔌 [代理] 正在获取品赞代理...")

    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=15)
            proxy_info = parse_proxy_response(response.text)

            if not proxy_info:
                log(f"   ⚠️ [代理] 第 {index} 次代理解析失败")
                continue

            log(f"   ✅ [代理] 提取到 {proxy_info['host']}:{proxy_info['port']}")
            proxies = build_proxy_dict(proxy_info)

            ok, ip = validate_proxy(proxies)
            if ok:
                return proxies, ip

            log(f"   ⚠️ [代理] 第 {index} 次代理不可用")
        except Exception as exc:
            log(f"   ⚠️ [代理] 第 {index} 次获取代理异常：{exc}")

        if index < PROXY_RETRY_TIMES:
            sleep(2)

    log("   ⚠️ [代理] 获取失败，使用直连")
    return None, ""


def request_with_proxy(method, url, *, proxies=None, server="", **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)

    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            log(f"   ⚠️ [代理] 代理请求失败：{exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            log("   🔄 [兜底] 切换直连重试")

    session = direct_session()
    return session.request(method, url, **kwargs)

# ==================== PushPlus推送 ====================

def send_pushplus(title, content):
    if not PLUSPLUS_TOKEN:
        log("   ℹ️ [推送] 未配置 PLUSPLUS_TOKEN，跳过推送")
        return

    try:
        requests.post(
            "https://www.pushplus.plus/send",
            json={
                "token": PLUSPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "txt",
            },
            timeout=10,
        )
        log("   📨 [推送] PushPlus 推送成功")
    except Exception as exc:
        log(f"   ❌ [推送] PushPlus 推送失败：{exc}")


def build_notify(results):
    daily_total = sum(
        int(res.get("dailyDelta"))
        for res in results
        if isinstance(res.get("dailyDelta"), (int, float))
    )
    earned_total = sum(
        int(res.get("todayEarned"))
        for res in results
        if isinstance(res.get("todayEarned"), (int, float))
    )
    spent_total = sum(
        int(res.get("todaySpent"))
        for res in results
        if isinstance(res.get("todaySpent"), (int, float))
    )
    count_total = sum(
        int(res.get("todayCount"))
        for res in results
        if isinstance(res.get("todayCount"), (int, float))
    )
    lines = ["### iQOO社区 每日任务"]
    if count_total:
        lines.append(f"> 📈 今日获得：**+{earned_total}** 酷币（{count_total} 笔）")
        if spent_total:
            lines.append(f"> 📉 今日消耗：**{spent_total}** 酷币")
        lines.append(f"> 📊 今日净增：**{daily_total:+d}** 酷币")
    elif any(isinstance(res.get("dailyDelta"), (int, float)) for res in results):
        lines.append(f"> 📈 今日合计：**{daily_total:+d}** 酷币（余额净增）")
    for res in results:
        flag = "✅" if res.get("success") else "❌"
        lines.append(f"\n#### {flag} 账号 {res['index']} · {res['source']}")
        if res.get("login_source"):
            source = "缓存复用" if res["login_source"] == "缓存" else "新登录"
            lines.append(f"- 登录：{source}")
            lines.append(f"- 用户：{res.get('userName') or '未返回'}")
            lines.append(f"- 任务：{res.get('tasksMsg') or '无任务数据'}")
            lines.append(f"- 签到：{res.get('signMsg') or '无结果'}")
            lines.append(f"- 抽奖：{res.get('drawMsg') or '无结果'}")
            lines.append(f"- 积分：{fmt_points(res.get('before'))} → "
                         f"{fmt_points(res.get('after'))}（本次 {int(res.get('delta') or 0):+d}）")
            if isinstance(res.get("todayEarned"), (int, float)):
                lines.append(f"- 今日：获得 +{int(res.get('todayEarned'))} / "
                             f"消耗 {int(res.get('todaySpent') or 0)}"
                             f"（{int(res.get('todayCount') or 0)} 笔，{res.get('scoreSource') or '余额基线'}）")
                for item in (res.get("scoreBreakdown") or [])[:8]:
                    lines.append(f"  - {item}")
            elif res.get("dailyDelta") is not None:
                lines.append(f"- 今日净增：{int(res.get('dailyDelta')):+d}"
                             f"（起始 {res.get('dailyStart')}）")
        if not res.get("success"):
            lines.append(f"- 失败原因：{res.get('error') or '未知'}")
    return "\n".join(lines)

# ==================== 青龙 notify.py 推送 ====================

def send_qinglong_notify(title, content):
    if os.getenv("IQOO_NOTIFY", "1") == "0":
        log("   ℹ️ [通知] IQOO_NOTIFY=0，已关闭通知")
        return False
    for candidate in (
        "/ql/data/scripts/notify.py",
        "/ql/scripts/notify.py",
        "/ql/data/notify.py",
        os.path.join(_SCRIPT_DIR, "notify.py"),
    ):
        if not os.path.exists(candidate):
            continue
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location("iqoo_ql_notify", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sender = getattr(module, "send", None) or getattr(module, "sendNotify", None)
            if callable(sender):
                sender(title, content)
                return True
        except Exception as exc:
            log(f"   ⚠️ [通知] 加载 {candidate} 失败：{exc}")
    return False


def parse_entry(raw):
    """解析 YYB_SERVER 条目：地址@微信账号标识[#备注] → (服务器地址, 标识, 备注)"""
    value = str(raw or "").strip()
    note = ""
    if "#" in value:
        value, note = value.split("#", 1)
        value, note = value.strip(), note.strip()
    if "@" not in value:
        log(f"   ❌ [配置] YYB_SERVER 格式应为 地址@微信账号标识，当前值：{raw}")
        return "", "", note
    server, ref = value.rsplit("@", 1)
    server = server.strip().rstrip("/")
    # 保留显式协议，未写协议时默认 http，避免 HTTPS 服务被强制降级
    if not re.match(r"^https?://", server, re.I):
        server = "http://" + server
    ref = ref.strip()
    if not server or not ref:
        log(f"   ❌ [配置] YYB_SERVER 缺少地址或账号标识，当前值：{raw}")
        return "", "", note
    return server, ref, note


def parse_yyb_entry(raw):
    server, ref, _ = parse_entry(raw)
    return server, ref

def get_code(entry):
    """通过 YYB Go 取码服务获取微信小程序 login code"""
    server, ref = parse_yyb_entry(entry)
    if not server or not ref:
        return None

    url = f"{server.rstrip('/')}/wxapp/getCode"

    try:
        response = direct_session().post(
            url,
            json={"ref": ref, "app_id": MINI_APP_ID},
            timeout=20,
        )
        data = response.json()

        result = (data.get("data") or {}).get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                result = {}
        code = (result or {}).get("code")
        # YYB 可能把 code 返回成字符串 "0"，统一按整数判断
        try:
            code_num = int(str(data.get("code")))
        except (TypeError, ValueError):
            code_num = -1
        if code_num != 0 or not code:
            log(f"   ❌ [取码] 取码失败：{json_preview(data)}")
            return None

        log("   ✅ [取码] 取码成功")
        return code
    except Exception as exc:
        log(f"   ❌ [取码] 取码异常：{exc}")
        log(f"   💡 [提示] 请检查 YYB 服务地址 http://{server} 是否在线、{ref} 是否已登录")
        return None


# ==================== Task ====================

class Task:
    def __init__(self, server, proxies, index=1):
        self.index = index
        self.server = server
        self.proxies = proxies
        self.server_addr, self.ref, self.note = parse_entry(server)
        self.ck = cache_key(self.server_addr, self.ref)
        self.openid = server
        self.token = ""
        self.refresh_token = ""
        self.user_id = ""
        self.user_info = {}
        self.thread_list = []
        self.visitor = hashlib.md5((self.ref or self.openid or str(int(time.time()))).encode()).hexdigest()
        self.sign_msg = "-"
        self.draw_msg = "-"
        self.tasks_msg = "-"
        self.login_source = ""
        self.before = None
        self.after = None
        self.daily_date = ""
        self.daily_start = None
        self.daily_delta = None
        self.daily_source = ""
        self.last_balance = None
        self.last_balance_date = ""
        self.today_earned = None
        self.today_spent = None
        self.today_count = None
        self.today_breakdown = []
        self.today_ledger_ok = False
        self.sign_ok = False
        self.task_ok = False
        self.draw_ok = False
        self._login_error = ""
        self._token_dead = False

    def run(self):
        result = {
            "index": self.index,
            "source": f"{self.server_addr}@{self.ref}" if self.ref else self.server,
            "name": self.note or self.ref or f"账号{self.index}",
            "success": False,
            "login_source": "",
            "userName": "-",
            "before": None,
            "after": None,
            "delta": 0,
            "dailyStart": None,
            "dailyDelta": None,
            "dailyDate": "",
            "todayEarned": None,
            "todaySpent": None,
            "todayCount": None,
            "scoreSource": "",
            "signMsg": "-",
            "drawMsg": "-",
            "tasksMsg": "-",
            "error": "",
            "proxyStatus": "使用专属代理" if self.proxies else "使用直连",
            "proxyIp": "-",
            "token": "-",
        }

        for attempt in range(2):
            try:
                # ---------- ① 首次尝试复用缓存 token ----------
                if attempt == 0:
                    entry = read_cache_entry(self.ck, self.ref)
                    if entry.get("accessToken"):
                        self.apply_token(entry)
                        log(f"   💾 [缓存] 复用已保存的登录 token（{short_token(self.token)}）")
                        verify_error = None
                        try:
                            self.fetch_user()
                        except Exception as exc:
                            verify_error = exc

                        if verify_error is None:
                            self.login_source = "缓存"
                            self.report_user()
                        elif is_token_error(str(verify_error)) or self._token_dead:
                            log("   ♻️ [缓存] token 已失效，清理缓存后重新登录")
                            self.remove_cached_token()
                        else:
                            result["error"] = f"缓存 token 校验失败：{verify_error}"
                            log("   ❌ [用户] 缓存 token 校验失败，保留缓存不删除")
                            return self._fill(result)

                # ---------- ② 没有可用 token → 重新登录 ----------
                if not self.token:
                    self.login_by_wx_code()
                    if not self.token:
                        result["error"] = self._login_error or "登录失败（取码或换 token 未通过，见上方日志）"
                        log("   ❌ [登录] 失败，跳过该账号")
                        return self._fill(result)
                    self.login_source = "新登录"
                    self.fetch_user()
                    self.report_user()

                # ---------- ③ 日常任务 / 抽奖 / 签到 ----------
                self._token_dead = False
                self.run_daily_tasks()
                if not self._token_dead:
                    self.get_draw_num()
                    self.sign_in()

                # ---------- ④ 执行中登录态失效 → 清缓存重登重跑一次 ----------
                if self._token_dead and attempt == 0:
                    log("   🔄 [重试] 执行中登录态失效，清理缓存重登后重跑一次")
                    self.remove_cached_token()
                    sleep(1.5)
                    continue

                # ---------- ⑤ 复查积分 ----------
                self.refresh_points()

                result["success"] = bool(self.sign_ok or self.task_ok or self.draw_ok)
                if result["success"]:
                    log("   ✅ [完成] 该账号任务执行完成")
                else:
                    result["error"] = self.sign_msg if self.sign_msg not in ("-", "") else "签到、任务、抽奖均未成功（详见上方日志）"
                    log("   ⚠️ [完成] 流程结束，但没有有效结果")
                return self._fill(result)

            except Exception as exc:
                if (is_token_error(str(exc)) or self._token_dead) and attempt == 0:
                    log("   🔄 [重试] 登录态失效，清理缓存重登后重跑一次")
                    self.remove_cached_token()
                    sleep(1.5)
                    continue
                result["error"] = f"执行异常：{exc}"
                log(f"   ❌ [异常] {exc}")
                return self._fill(result)

        result["error"] = result["error"] or "重试后仍未完成（详见上方日志）"
        return self._fill(result)

    def _fill(self, result):
        result["login_source"] = self.login_source
        result["signMsg"] = self.sign_msg
        result["drawMsg"] = self.draw_msg
        result["tasksMsg"] = self.tasks_msg
        result["token"] = short_token(self.token)
        result["userName"] = mask_name(self.user_name()) or "-"
        result["before"] = self.before
        result["after"] = self.after
        result["dailyStart"] = self.daily_start
        result["dailyDelta"] = self.daily_delta
        result["dailyDate"] = self.daily_date
        result["todayEarned"] = self.today_earned
        result["todaySpent"] = self.today_spent
        result["todayCount"] = self.today_count
        result["scoreSource"] = "积分明细" if self.today_ledger_ok else "余额基线"
        result["scoreBreakdown"] = list(self.today_breakdown)
        if isinstance(self.before, (int, float)) and isinstance(self.after, (int, float)):
            result["delta"] = int(self.after - self.before)
        return result

    def user_name(self):
        return (self.user_info.get("nickname")
                or self.user_info.get("username")
                or self.user_info.get("userName")
                or self.user_id
                or "")

    def current_points(self):
        for key in ("score", "points", "coolCoin"):
            value = self.user_info.get(key)
            if value is None:
                continue
            number = to_number(value)
            return number if number is not None else value
        return None

    def report_user(self):
        self.before = self.current_points()
        self.ensure_daily_baseline()
        log(f"   👤 [用户] {mask_name(self.user_name()) or '-'}")
        log(f"   💰 [积分] 当前 {fmt_points(self.before)} 酷币")

    def ensure_daily_baseline(self):
        """确定当天起始余额。

        优先复用当天已记录的基线；跨天时优先用上一次运行的收盘余额，
        这样即使当天第一次运行发生在手动签到/做任务之后，也能统计出当天净增。
        只有没有任何历史收盘数据时，才退回“以当前余额为起点”。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        entry = read_cache_entry(self.ck, self.ref)
        self.daily_source = ""

        start = None
        if self.daily_date == today and isinstance(self.daily_start, (int, float)):
            start = int(self.daily_start)
            self.daily_source = "今日已有基线"
        elif entry.get("dailyDate") == today and isinstance(entry.get("dailyStart"), (int, float)):
            start = int(entry.get("dailyStart"))
            self.daily_date = today
            self.daily_source = "今日已有基线"
        else:
            prev = None
            prev_date = ""
            if (isinstance(self.last_balance, (int, float))
                    and self.last_balance_date and self.last_balance_date < today):
                prev = int(self.last_balance)
                prev_date = self.last_balance_date
            elif (isinstance(entry.get("lastBalance"), (int, float))
                  and entry.get("lastBalanceDate")
                  and str(entry.get("lastBalanceDate")) < today):
                prev = int(entry.get("lastBalance"))
                prev_date = str(entry.get("lastBalanceDate"))
            if prev is not None:
                start = prev
                self.daily_source = f"上次收盘 {prev_date}"
            elif isinstance(self.before, (int, float)):
                start = int(self.before)
                self.daily_source = "无历史收盘，以本次为起点"

        if start is not None:
            self.daily_date = today
            self.daily_start = start
            if isinstance(self.before, (int, float)):
                self.daily_delta = int(self.before - start)
            self.save_cached_token()
            if self.daily_source == "无历史收盘，以本次为起点":
                log("   ℹ️ [今日] 暂无历史收盘余额，稍后优先用官方积分流水校准")

    def refresh_points(self):
        try:
            self.fetch_user()
        except Exception as exc:
            log(f"   ⚠️ [积分] 最终积分获取失败（{exc}）")
            if isinstance(self.before, (int, float)):
                self.after = self.before
            return

        self.after = self.current_points()
        if isinstance(self.after, (int, float)):
            self.last_balance = int(self.after)
            self.last_balance_date = datetime.now().strftime("%Y-%m-%d")
            self.save_cached_token(update_last=True)

        # 优先用官方积分流水统计当天：不依赖历史缓存，首次运行也能算准
        ledger = self.fetch_today_score_ledger()
        if ledger.get("ok"):
            self.today_ledger_ok = True
            self.today_earned = ledger["earned"]
            self.today_spent = ledger["spent"]
            self.today_count = ledger["count"]
            self.today_breakdown = ledger["breakdown"]
            self.daily_delta = ledger["net"]
            self.daily_date = datetime.now().strftime("%Y-%m-%d")
            self.daily_source = "积分明细"
            if isinstance(self.after, (int, float)):
                self.daily_start = int(self.after - ledger["net"])
            log(f"   📥 [今日] 获得 +{ledger['earned']} / 消耗 {ledger['spent']}"
                f"（{ledger['count']} 笔，官方积分流水）")
            for line in ledger["breakdown"][:8]:
                log(f"      · {line}")
            if len(ledger["breakdown"]) > 8:
                log(f"      · 其余 {len(ledger['breakdown']) - 8} 类略")
        elif isinstance(self.daily_start, (int, float)) and isinstance(self.after, (int, float)):
            self.daily_delta = int(self.after - self.daily_start)

        if isinstance(self.before, (int, float)) and isinstance(self.after, (int, float)):
            log(f"   💰 [积分] {self.before} → {self.after}（本次 {int(self.after - self.before):+d}）")
        else:
            log(f"   💰 [积分] 当前 {fmt_points(self.after)} 酷币")
        if self.daily_delta is not None:
            log(f"   📈 [今日] 净增 {self.daily_delta:+d}（起始 {self.daily_start} → 当前 {self.after}）")

    def fetch_today_score_ledger(self):
        """读取 v3/user.score.recode 当天流水，统计获得、消耗和分类明细。"""
        empty = {"ok": False, "earned": 0, "spent": 0, "net": 0, "count": 0, "breakdown": []}
        if not self.user_id:
            log("   ⚠️ [明细] 缺少 userId，跳过当天流水")
            return empty

        today = datetime.now().strftime("%m-%d")
        items = []
        seen_older = False
        total = None
        try:
            for page in range(1, 7):
                result = self.request("v3/user.score.recode", {
                    "page": page,
                    "perPage": 20,
                    "userId": self.user_id,
                }, {"method": "GET"})
                data = result.get("Data") or {}
                page_items = data.get("list") or []
                if total is None:
                    total = int(data.get("total") or 0)
                if not page_items:
                    break
                for item in page_items:
                    created = str(item.get("created_at") or "")
                    if created.startswith(today):
                        items.append(item)
                    elif items:
                        seen_older = True
                        break
                if seen_older:
                    break
                if page == 1 and not items:
                    break
                if total and page * 20 >= total:
                    break
        except Exception as exc:
            log(f"   ⚠️ [明细] 获取当天积分流水失败，改用余额基线（{exc}）")
            return empty

        groups = {}
        earned = 0
        spent = 0
        for item in items:
            if item.get("is_valid") is False:
                continue
            change = to_number(item.get("this_score"))
            if change is None:
                old = to_number(item.get("old_score"))
                new = to_number(item.get("new_score"))
                change = (new - old) if old is not None and new is not None else 0
            change = int(change)
            if change >= 0:
                earned += change
            else:
                spent += change
            reason = (item.get("get_reason")
                      or ((item.get("score_rule") or {}).get("access"))
                      or "其他")
            reason = str(reason).replace("抽奖获取酷币：", "抽奖 ").strip()
            group = groups.setdefault(reason, {"count": 0, "score": 0})
            group["count"] += 1
            group["score"] += change

        breakdown = []
        for reason, group in sorted(groups.items(), key=lambda kv: (-kv[1]["score"], kv[0])):
            score = group["score"]
            breakdown.append(f"{reason} {score:+d} ×{group['count']}")
        return {
            "ok": True,
            "earned": earned,
            "spent": spent,
            "net": earned + spent,
            "count": len(items),
            "breakdown": breakdown,
        }

    def run_daily_tasks(self):
        daily_tasks = self.fetch_daily_tasks()
        if self._token_dead:
            return
        if not daily_tasks:
            self.tasks_msg = "未获取到每日任务"
            log("   ⚠️ [任务] 未获取到每日任务，跳过")
            return

        def task_upper(task):
            value = task.get("upper_limit")
            if value in (None, "", "不限次数"):
                return None
            number = to_number(value)
            return int(number) if number is not None else None

        need_threads = any(
            task_upper(t) is not None
            and task_upper(t) > int(t.get("isFinal", 0) or 0)
            and t.get("rule") in ("view_thread", "like", "share", "create_post")
            for t in daily_tasks
        )
        if need_threads:
            self.get_thread_list()

        executed = []
        for task in daily_tasks:
            if self._token_dead:
                break
            rule = task.get("rule")
            done = int(task.get("isFinal", 0) or 0)
            max_count = task_upper(task)
            if max_count is None:
                continue
            remaining = max_count - done
            if remaining <= 0:
                continue

            label = task.get("access") or rule or "任务"
            log(f"   📋 [任务] {label} 已完成 {done}/{max_count}，还需 {remaining} 次")
            start_remaining = remaining

            if rule == "view_thread":
                for item in self.thread_list:
                    if remaining <= 0 or self._token_dead:
                        break
                    self.view_post(item.get("threadId"))
                    remaining -= 1
                    sleep(3)
            elif rule == "like":
                for item in self.thread_list:
                    if remaining <= 0 or self._token_dead:
                        break
                    self.like_post(item.get("threadId"), item.get("postId"))
                    remaining -= 1
                    sleep(3)
            elif rule == "share":
                for item in self.thread_list:
                    if remaining <= 0 or self._token_dead:
                        break
                    self.share_post(item.get("threadId"))
                    remaining -= 1
                    sleep(3)
            elif rule == "create_post":
                if self.thread_list:
                    self.comment_post(self.thread_list[0].get("threadId"))
                    remaining -= 1
                else:
                    log("   ⚠️ [任务] 无帖子可评论")
            elif rule == "create_thread":
                self.create_and_delete_thread()
                remaining -= 1

            finished = max(0, start_remaining - remaining)
            if finished:
                executed.append(f"{label} {finished}")

        done_total = len(executed)
        self.task_ok = done_total > 0
        self.tasks_msg = " · ".join(executed) if executed else "没有需要执行的待办任务"
        if done_total:
            log(f"   📋 [任务] 本次完成 {done_total} 项任务：{self.tasks_msg}")
        else:
            log("   ℹ️ [任务] 没有需要执行的待办任务")

    def save_cached_token(self, update_last=False):
        if not self.token:
            return
        entry = {
            "accessToken": self.token,
            "refreshToken": self.refresh_token,
            "userId": self.user_id,
            "userInfo": self.user_info,
            "visitor": self.visitor,
            "dailyDate": self.daily_date,
            "dailyStart": self.daily_start,
        }
        if isinstance(self.last_balance, (int, float)):
            entry["lastBalance"] = self.last_balance
            entry["lastBalanceDate"] = self.last_balance_date
        save_cache_entry(self.ck, entry)

    def remove_cached_token(self):
        drop_cache_entry(self.ck)
        self.token = ""
        self.refresh_token = ""
        self.user_id = ""
        self.user_info = {}

    def apply_token(self, data=None):
        data = data or {}
        self.token = data.get("accessToken") or data.get("token") or ""
        self.refresh_token = data.get("refreshToken") or ""
        user_info = data.get("userInfo") or data.get("user") or {}
        self.user_id = data.get("userId") or data.get("uid") or user_info.get("userId") or user_info.get("uid") or ""
        self.user_info = user_info
        self.visitor = data.get("visitor") or self.visitor
        self.daily_date = data.get("dailyDate") or self.daily_date
        if isinstance(data.get("dailyStart"), (int, float)):
            self.daily_start = int(data.get("dailyStart"))
        if isinstance(data.get("lastBalance"), (int, float)):
            self.last_balance = int(data.get("lastBalance"))
            self.last_balance_date = data.get("lastBalanceDate") or self.last_balance_date

    def query_string(self, data=None):
        data = data or {}
        parts = []
        for key in sorted(data.keys()):
            value = data[key]
            if value is None:
                continue
            parts.append(f"{quote(str(key), safe='')}={quote(str(value), safe='')}")
        return "&".join(parts)

    def get_sign(self, method, api_path, data=None):
        data = data or {}
        upper_method = method.upper()
        timestamp = int(time.time())
        query = self.query_string(data) if upper_method == "GET" else ""
        body = "" if upper_method == "GET" else json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        raw = f"{upper_method}&/api/{api_path}&{query}&{body}&appid=1002&timestamp={timestamp}"
        signature = base64.b64encode(hmac.new(SIGN_SECRET.encode(), raw.encode(), hashlib.sha256).digest()).decode()
        return f"IQOO-HMAC-SHA256 appid=1002,timestamp={timestamp},signature={signature}"

    def build_headers(self, method, api_path, data, extra=None):
        extra = extra or {}
        headers = {
            "Authorization": f"Bearer {self.token}" if self.token else "Bearer ",
            "X-Visitor": self.visitor,
            "X-Platform": "mini",
            "SIGN": self.get_sign(method, api_path, data),
            "Content-Nonce": "",
            "User-Agent": USER_AGENT,
            "Referer": f"https://servicewechat.com/{MINI_APP_ID}/{PAGE_VERSION}/page-frame.html",
        }
        headers.update(extra)
        return headers

    def request(self, api_path, data=None, options=None):
        data = data or {}
        options = options or {}
        method = (options.get("method") or "POST").upper()
        url = requests.compat.urljoin(API_BASE, api_path)
        headers = self.build_headers(method, api_path, data, options.get("headers") or {})

        if method == "GET":
            response = request_with_proxy(
                "GET", url,
                headers=headers,
                params=data,
                proxies=self.proxies,
                server=self.server,
            )
        else:
            headers["Content-Type"] = "application/json"
            body_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            response = request_with_proxy(
                method, url,
                headers=headers,
                data=body_str.encode("utf-8"),
                proxies=self.proxies,
                server=self.server,
            )

        try:
            result = response.json()
        except Exception:
            raise Exception(f"JSON解析失败: {response.text[:300]}")

        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {json_preview(result)}")
        if not is_success(result):
            raise Exception(f"{result.get('Code', '')} {result.get('Message') or json_preview(result)}".strip())
        return result

    def fetch_daily_tasks(self):
        try:
            result = self.request("v5/users/tasks", {}, {"method": "GET"})
            return (result.get("Data") or {}).get("perDayData") or []
        except Exception as e:
            log(f"   ❌ [任务] 获取每日任务失败：{e}")
            if is_token_error(str(e)):
                self._token_dead = True
                self.remove_cached_token()
            return []

    def login_by_wx_code(self):
        try:
            code = get_code(self.server)
            if not code:
                raise Exception("获取code失败")
            sleep(1.5)

            encrypted_data = base64.b64encode(os.urandom(48)).decode()
            iv = base64.b64encode(os.urandom(16)).decode()

            payload = {
                "code": code,
                "encryptedData": encrypted_data,
                "iv": iv,
                "from": 46,
            }
            log("   🔐 [登录] 使用 code 换取 token...")
            result = self.request("v3/users/vivo/mini", payload)
            data = result.get("Data") or {}
            token = data.get("accessToken") or data.get("token") or ""
            if not token:
                raise Exception(f"登录响应未返回token: {json_preview(result)}")
            self.token = token
            self.refresh_token = data.get("refreshToken") or ""
            self.user_id = data.get("userId") or data.get("uid") or ""
            self.user_info = data.get("user") or data
            self.save_cached_token()
            name = self.user_info.get("nickname") or self.user_info.get("username") or self.user_id
            log(f"   ✅ [登录] 登录成功：{mask_name(name)}")
        except Exception as e:
            self._login_error = str(e)
            log(f"   ❌ [登录] 登录失败：{e}")

    def fetch_user(self):
        if not self.user_id:
            raise Exception("缺少 userId，无法校验登录态")
        result = self.request("v3/user", {"userId": self.user_id}, {"method": "GET"})
        self.user_info = result.get("Data") or self.user_info
        self.save_cached_token()

    def get_draw_num(self):
        try:
            result = self.request("v3/today.draw.count", {}, {"method": "GET"})
            if (result.get("Data") or {}).get("count") == 0:
                self.draw()
            else:
                self.draw_msg = "今日已抽奖"
                self.draw_ok = True
                log("   🎰 [抽奖] 今日已抽奖")
        except Exception as exc:
            self.draw_msg = f"查询抽奖失败：{exc}"
            log(f"   ❌ [抽奖] 查询抽奖次数失败：{exc}")
            if is_token_error(str(exc)):
                self._token_dead = True
                self.remove_cached_token()

    def draw(self):
        try:
            result = self.request("v3/luck.draw", {})
            prize = (result.get("Data") or {}).get("prize_name") or "奖励"
            self.draw_msg = f"抽奖成功，获得 {prize}"
            self.draw_ok = True
            log(f"   🎰 [抽奖] 抽奖成功，获得 {prize}")
        except Exception as exc:
            self.draw_msg = f"抽奖失败：{exc}"
            log(f"   ❌ [抽奖] 抽奖失败：{exc}")
            if is_token_error(str(exc)):
                self._token_dead = True
                self.remove_cached_token()

    def sign_in(self):
        try:
            result = self.request("v3/sign", {"from": "group"})
            data = result.get("Data") or {}
            score = data.get("score")
            total = data.get("scoreCount")
            self.sign_msg = (f"签到成功 连续{data.get('serialDays')}天"
                             f" +{score}积分 当前{total}")
            self.sign_ok = True
            log(f"   ✅ [签到] {self.sign_msg}")
        except Exception as exc:
            message = str(exc)
            if re.search(r"已签|重复|今日|13006", message):
                self.sign_msg = "今日已签到"
                self.sign_ok = True
                log("   ℹ️ [签到] 今日已签到")
                return
            self.sign_msg = f"签到失败：{message}"
            log(f"   ❌ [签到] {self.sign_msg}")
            if is_token_error(message):
                self._token_dead = True
                self.remove_cached_token()

    def _interaction_error(self, label, exc):
        log(f"   ❌ [{label}] {exc}")
        if is_token_error(str(exc)):
            self._token_dead = True
            self.remove_cached_token()

    def like_post(self, thread_id, post_id):
        try:
            self.request("v3/posts.update", {"id": thread_id, "postId": post_id, "data": {"attributes": {"isLiked": True}}})
            log("   ❤️ [互动] 帖子点赞成功")
        except Exception as e:
            self._interaction_error("互动", f"帖子点赞失败：{e}")
            return
        try:
            self.request("v3/posts.update", {"id": thread_id, "postId": post_id, "data": {"attributes": {"isLiked": False}}})
        except Exception:
            pass

    def share_post(self, thread_id):
        try:
            self.request("v3/thread.share", {"threadId": thread_id})
            log("   🔗 [互动] 帖子分享成功")
        except Exception as e:
            self._interaction_error("互动", f"帖子分享失败：{e}")

    def view_post(self, thread_id):
        try:
            self.request("v3/view.count", {"threadId": thread_id, "type": 0}, {"method": "GET"})
            log("   👀 [互动] 帖子浏览成功")
        except Exception as e:
            self._interaction_error("互动", f"帖子浏览失败：{e}")

    def comment_post(self, thread_id):
        try:
            self.request("v3/posts.create", {"id": thread_id, "type": 0, "content": "666", "source": "", "attachments": []})
            log("   💬 [互动] 帖子评论成功")
        except Exception as e:
            self._interaction_error("互动", f"帖子评论失败：{e}")

    def create_and_delete_thread(self):
        try:
            result = self.request("v3/thread.create", {
                "categoryId": 16,
                "content": {
                    "text": "<p>设计内核传递IQO0\"不止竞技\"的理念，将自然美</p><p>融入数码产品。既有电竞产品标志性光效元素，可</p><p>兼具清新简约气路，无论是沉浸式游戏、日常通勤</p><p>聆听音乐，都能适配多元场景，实现性能美学与实</p><p>用体验的平衡</p>"
                },
                "position": {},
                "price": 0,
                "freeWords": 0,
                "attachmentPrice": 0,
                "draft": 0,
                "anonymous": 0,
                "topicId": "",
                "source": "",
                "videoId": "",
                "type": 7,
                "attachments": [],
                "isAigc": False
            })
            thread_id = (result.get("Data") or {}).get("threadId")
            if not thread_id:
                log("   ⚠️ [发帖] 发帖成功但未获取到 threadId，无法删除")
                return
            log(f"   📝 [发帖] 发帖成功，threadId: {thread_id}")
            sleep(2)
            self.request("v3/thread.delete", {"threadId": thread_id, "message": ""})
            log("   🗑️ [发帖] 帖子已删除")
        except Exception as e:
            self._interaction_error("发帖", f"发帖/删除失败：{e}")

    def get_thread_list(self):
        try:
            result = self.request("v3/thread.list", {
                "scope": 5,
                "page": 1,
                "perPage": 20,
                "filter[sort]": 4,
                "filter[essence]": 1,
                "sequence": 0,
            }, {"method": "GET"})
            self.thread_list = (result.get("Data") or {}).get("pageData") or []
            log(f"   📋 [帖子] 获取到 {len(self.thread_list)} 条帖子")
        except Exception as e:
            log(f"   ❌ [帖子] 获取帖子列表失败：{e}")
            self.thread_list = []

# ==================== 主入口 ====================

def main():
    box_top(f"📱 iQOO社区 每日任务 {VERSION}")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(SERVERS)} 个")
    box_line("💾 缓存", "token_caches/iqoo_token_cache.json")
    box_bottom()

    results = []
    for idx, server in enumerate(SERVERS, 1):
        server_addr, ref, note = parse_entry(server)
        title = f"标识 {ref}" + (f"（{note}）" if note else "") if ref else "标识 未解析"
        account_frame(idx, len(SERVERS), title, f"{server_addr}@{ref}" if ref else server)
        proxies, proxy_ip = get_valid_proxy(server)
        if PROXY_API:
            sleep(PROXY_FETCH_INTERVAL)
        if proxies:
            log("   🌐 [代理] 使用专属代理" + (f"（{proxy_ip}）" if proxy_ip else ""))

        task = Task(server, proxies, idx)
        try:
            result = task.run()
        except Exception as exc:
            result = {
                "index": idx,
                "source": f"{server_addr}@{ref}" if ref else server,
                "name": note or ref or f"账号{idx}",
                "success": False,
                "login_source": "",
                "userName": "-",
                "before": None,
                "after": None,
                "delta": 0,
                "signMsg": "-",
                "drawMsg": "-",
                "tasksMsg": "-",
                "error": f"执行异常：{exc}",
                "token": "-",
            }
            log(f"   ❌ [异常] 该账号执行异常：{exc}")
        result["proxyIp"] = proxy_ip or "-"
        results.append(result)
        hr()
        if idx < len(SERVERS):
            log("   ⏳ 等待2秒后执行下一个账号...")
            sleep(2)

    print()
    for res in results:
        icon = "✅" if res.get("success") else "❌"
        title = f"【账号 {res['index']} · {res['source']}】"
        if res.get("name") and res["name"] != res["source"]:
            title = f"【账号 {res['index']} · {res['source']}（{res['name']}）】"
        log(f"{icon} {title}")
        if res.get("login_source"):
            login_text = "缓存复用" if res["login_source"] == "缓存" else "新登录"
            log(f"   🔐 [登录] {login_text} | token {res.get('token') or '-'}")
            log(f"   👤 [用户] {res.get('userName') or '-'}")
            log(f"   📋 [任务] {res.get('tasksMsg') or '-'}")
            log(f"   📅 [签到] {res.get('signMsg') or '-'}")
            log(f"   🎰 [抽奖] {res.get('drawMsg') or '-'}")
            log(f"   💰 [积分] {fmt_points(res.get('before'))} → "
                f"{fmt_points(res.get('after'))}（本次 {int(res.get('delta') or 0):+d}）")
            if isinstance(res.get("todayEarned"), (int, float)):
                log(f"   📥 [今日] 获得 +{int(res.get('todayEarned'))} / "
                    f"消耗 {int(res.get('todaySpent') or 0)}"
                    f"（{int(res.get('todayCount') or 0)} 笔，{res.get('scoreSource')}）")
                for item in (res.get("scoreBreakdown") or [])[:8]:
                    log(f"      · {item}")
            if res.get("dailyDelta") is not None:
                log(f"   📈 [今日] 净增 {int(res.get('dailyDelta')):+d}（起始 {res.get('dailyStart')}）")
        if not res.get("success"):
            log(f"   ⚠️ [失败] {res.get('error') or '未知原因'}")

    ok_count = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - ok_count
    total_delta = sum(int(r.get("delta") or 0) for r in results if r.get("success"))
    total_daily = sum(
        int(r.get("dailyDelta"))
        for r in results
        if isinstance(r.get("dailyDelta"), (int, float))
    )
    has_daily = any(isinstance(r.get("dailyDelta"), (int, float)) for r in results)
    total_earned = sum(
        int(r.get("todayEarned"))
        for r in results
        if isinstance(r.get("todayEarned"), (int, float))
    )
    total_spent = sum(
        int(r.get("todaySpent"))
        for r in results
        if isinstance(r.get("todaySpent"), (int, float))
    )
    total_count = sum(
        int(r.get("todayCount"))
        for r in results
        if isinstance(r.get("todayCount"), (int, float))
    )

    box_top("🏁 iQOO社区 执行汇总")
    box_line("📊 执行结果", f"成功 {ok_count} / 失败 {fail_count} / 共 {len(results)}")
    box_line("💰 本次变化", f"{total_delta:+d}")
    if total_count:
        box_line("📥 今日获得", f"+{total_earned} 酷币（{total_count} 笔）")
        if total_spent:
            box_line("📉 今日消耗", f"{total_spent} 酷币")
        box_line("📈 今日净增", f"{total_daily:+d} 酷币")
    elif has_daily:
        box_line("📈 今日净增", f"{total_daily:+d} 酷币")
    box_bottom()

    content = build_notify(results)
    if send_qinglong_notify("iQOO社区每日任务", content):
        log("   📨 [通知] 已通过青龙 notify.py 推送")
    send_pushplus("iQOO社区任务完成", content)
    return results


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ 程序异常: {e}")
