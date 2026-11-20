#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: OPPO商城
# cron: 10 8,20 * * *
"""
OPPO 商城 微信小程序 签到 + 浏览任务脚本
版本: 2.1.0
YYB Go 取码服务（YYB_SERVER，格式：地址@微信账号标识，多账号换行分隔）
品赞代理（PROXY_API，业务请求代理优先，失败直连兜底）
PushPlus 推送（PLUSPLUS_TOKEN）
"""

import hashlib
import json
import os
import random
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

# =============================================================================
# 常量配置（硬编码，不依赖环境变量）
# =============================================================================

# ---- YYB Go 取码服务（环境变量 YYB_SERVER，格式：地址@微信账号标识，多账号换行分隔）----
_YYB_SERVER_RAW = os.getenv("YYB_SERVER", "")
SERVERS = [line.strip() for line in _YYB_SERVER_RAW.splitlines() if line.strip()]
if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER（格式：地址@微信账号标识，多账号换行分隔）")
    exit(1)
print(f"✅ 读取到 {len(SERVERS)} 个 YYB Go 账号")

# ---- 小程序 app_id ----
WX_APP_ID = "wx9c825da1a7ba062e"

# ---- OPPO 登录相关接口 ----
PRE_AUTH_URL = "https://id.opposhop.cn/api/bind-login/pre-auth"
MEMBER_INFO_URL = "https://msec.opposhop.cn/users/web/member/info"

# ---- OPPO 业务接口基地址 ----
HD_BASE = "https://hd.opposhop.cn"
API_CREDIT = f"{HD_BASE}/api/cn/oapi/marketing/member/queryMemberCreditInfo"
API_SIGN_DETAIL = f"{HD_BASE}/api/cn/oapi/marketing/cumulativeSignIn/getSignInDetail"
API_SIGN_IN = f"{HD_BASE}/api/cn/oapi/marketing/cumulativeSignIn/signIn"
API_TASK_LIST = f"{HD_BASE}/api/cn/oapi/marketing/task/queryTaskList"
API_TASK_REPORT = f"{HD_BASE}/api/cn/oapi/marketing/taskReport/signInOrShareTask"
API_TASK_RECEIVE = f"{HD_BASE}/api/cn/oapi/marketing/task/receiveAward"

# ---- 落地页 ----
LANDING_PAGE = "https://hd.opposhop.cn/bp/b371ce270f7509f0"
LANDING_PARAMS = "?nightModelEnable=true&us=wode&um=qiandaobanner&colorScheme=light"

# ---- 默认活动 ID（解析失败时回退）----
FALLBACK_SIGN_ACTIVITY_ID = "2083099953777090560"
FALLBACK_TASK_ACTIVITY_ID = "1919591795180969984"
CREDITS_ADD_ACTION_ID = "1788913e6d9e4683b8b9ab0088733560"

# ---- 签名相关常量 ----
APP_KEY = "H7N4jMYgvNopNk7csDDhnM"
SIGN_KEY = "uyIVtwnGi3Qyf8dtGJ1d6g=="

# ---- 小程序通用 UA ----
UA = (
    "Mozilla/5.0 (Linux; Android 16; 2308CPXD0C Build/BP2A.250605.031.A3; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.178 "
    "Mobile Safari/537.36 XWEB/1460249 MMWEBSDK/20260502 MMWEBID/6435 "
    "MicroMessenger/8.0.76.3141(0x28004C3C) WeChat/arm64 Weixin NetType/WIFI "
    "Language/zh_CN ABI/arm64 MiniProgramEnv/android"
)

# ---- 缓存文件路径 ----
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(_SCRIPT_DIR, "token_caches", "oppo_token_cache.json")

# ---- 脚本行为开关 ----
SIMULATE_WAIT = True          # 是否真实等待浏览秒数
BROWSE_TIMEOUT = 20           # 请求超时(秒)

# ---- 品赞代理（可选，业务请求代理优先，失败直连兜底）----
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

# ---- PushPlus 推送（可选）----
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")

# ---- 任务状态枚举 ----
TASK_STATUS_TODO = 1
TASK_STATUS_CLAIMABLE = 2
TASK_STATUS_DONE = 3
TASK_TYPE_BROWSE = 1

# =============================================================================
# 工具函数
# =============================================================================
_logs = []

def log(msg: str) -> None:
    line = str(msg)
    print(line, flush=True)
    _logs.append(line)
    if len(_logs) > 500:
        del _logs[: len(_logs) - 500]


def log_blank() -> None:
    log("")


def log_section(title: str) -> None:
    log(f"—— {title} ——")


def mask(s: str, keep: int = 6) -> str:
    s = str(s or "")
    if len(s) <= keep * 2:
        return "***"
    return s[:keep] + "***" + s[-keep:]


def points_text(amount) -> str:
    if amount is None or amount == "":
        return "未知"
    return str(amount)


# =============================================================================
# 日志美化
# =============================================================================
BOX_WIDTH = 48
BOX_INNER = 46


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _pad_str(value, width: int) -> str:
    text = str(value)
    length = 0
    for ch in text:
        if ch in ("\ufe0f", "\ufe0e", "\u200d"):
            continue
        length += 2 if ord(ch) > 255 else 1
    return text + " " * max(0, width - length)


def box_top(title: str) -> None:
    log("")
    log("╔" + "═" * BOX_WIDTH + "╗")
    log("║  " + _pad_str(title, BOX_INNER) + "║")


def box_line(label: str, value) -> None:
    log("║  " + _pad_str(f"{label}: {value}", BOX_INNER) + "║")


def box_bottom() -> None:
    log("╚" + "═" * BOX_WIDTH + "╝")


def account_frame(index: int, total: int, title: str, source: str) -> None:
    log("")
    log("┌" + "─" * BOX_WIDTH + "┐")
    log("│  " + _pad_str(f"🧩 账号 {index} / {total}　{title}", BOX_INNER) + "│")
    log("│  " + _pad_str(f"🔗 来源: {source}", BOX_INNER) + "│")
    log("└" + "─" * BOX_WIDTH + "┘")


def hr() -> None:
    log("")
    log("-" * BOX_WIDTH)


# =============================================================================
# 登录态失效判定（只认明确凭证类提示，避免把业务错误误判为登录失效）
# =============================================================================
AUTH_HINTS = (
    "未登录", "登录已失效", "登录失效", "请重新登录", "重新登录",
    "session失效", "session已失效", "NEWOPPOSID", "凭证失效",
)


def is_auth_error(data: Any) -> bool:
    if not isinstance(data, dict) or data.get("_error"):
        return False
    if data.get("code") in (401, 403):
        return True
    msg = str(data.get("message") or data.get("errorMessage") or data.get("msg") or "")
    return any(hint in msg for hint in AUTH_HINTS)


def brief_error(value: Any, limit: int = 80) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if not text:
        return "未知错误"
    return text[: limit - 1] + "…" if len(text) > limit else text


# =============================================================================
# 青龙 notify.py 推送
# =============================================================================
def send_qinglong_notify(title: str, content: str) -> bool:
    if os.getenv("OPPO_NOTIFY", "1") == "0":
        log("   ℹ️ [通知] OPPO_NOTIFY=0，已关闭通知")
        return False
    for path in (
        "/ql/data/scripts/notify.py",
        "/ql/scripts/notify.py",
        "/ql/data/notify.py",
        os.path.join(_SCRIPT_DIR, "notify.py"),
    ):
        if not os.path.exists(path):
            continue
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location("oppo_ql_notify", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sender = getattr(module, "send", None) or getattr(module, "sendNotify", None)
            if callable(sender):
                sender(title, content)
                return True
        except Exception as exc:
            log(f"   ⚠️ [通知] 加载 {path} 失败：{exc}")
    return False


def generate_sign(params: Dict[str, Any]) -> Tuple[str, int, str]:
    """生成 MD5 签名，返回 (sign, timestamp, nonce)"""
    data = params.copy()
    data["appKey"] = APP_KEY
    data["timestamp"] = int(time.time() * 1000)
    data["nonce"] = str(uuid.uuid4())
    data = {k: v for k, v in data.items() if v is not None and v != ""}
    sorted_keys = sorted(data.keys())
    raw = "&".join(f"{k}={data[k]}" for k in sorted_keys)
    sign_str = raw + f"&key={SIGN_KEY}"
    sign = hashlib.md5(sign_str.encode()).hexdigest()
    return sign, data["timestamp"], data["nonce"]


# =============================================================================
# 品赞代理工具（铛铛一下同款）
# =============================================================================
def json_preview(data: Any, limit: int = 800) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)[:limit]
    except Exception:
        return str(data)[:limit]


def direct_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def parse_proxy_response(text: Any) -> Optional[Dict[str, Any]]:
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


def build_proxy_dict(proxy_info: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
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

    log(f"🛠️ [代理] 生成 {scheme.upper()} 代理 {host}:{port}")

    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def validate_proxy(proxies: Optional[Dict[str, str]]) -> Tuple[bool, str]:
    if not proxies:
        return False, ""

    try:
        response = requests.get(PROXY_VALIDATE_URL, proxies=proxies, timeout=15)
        if response.status_code == 200:
            try:
                ip = response.json().get("origin", "未知")
            except Exception:
                ip = "未知"
            log(f"✅ [代理] 验证通过，出口 IP: {ip}")
            return True, ip
    except Exception as exc:
        log(f"⚠️ [代理] 验证失败: {exc}")

    return False, ""


def get_valid_proxy(account_name: str) -> Tuple[Optional[Dict[str, str]], str]:
    if not PROXY_API:
        log("   ℹ️ [代理] 未配置 PROXY_API，使用直连")
        return None, ""

    log("   🌐 [代理] 正在获取品赞代理...")

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
            time.sleep(2)

    log("   ⚠️ [代理] 获取失败，使用直连")
    return None, ""


def request_with_proxy(
    method: str,
    url: str,
    *,
    proxies: Optional[Dict[str, str]] = None,
    server: str = "",
    **kwargs,
) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)

    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            log(f"⚠️ [代理] {server} 代理请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            log("🔁 [兜底] 切换直连重试")

    session = direct_session()
    return session.request(method, url, **kwargs)


# =============================================================================
# 本地 code 服务（铛铛一下同款接口）
# =============================================================================
def parse_entry(raw: str) -> Tuple[str, str, str]:
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
    # 用正则剥协议头，避免 lstrip 按字符集误删 https 的 s
    server = re.sub(r"^https?://", "", server.strip(), flags=re.IGNORECASE).rstrip("/")
    ref = ref.strip()
    if not server or not ref:
        log(f"   ❌ [配置] YYB_SERVER 缺少地址或账号标识，当前值：{raw}")
        return "", "", note
    return server, ref, note


def parse_yyb_entry(raw: str) -> Tuple[str, str]:
    server, ref, _ = parse_entry(raw)
    return server, ref


def get_code(entry: str) -> Optional[str]:
    """通过 YYB Go 取码服务获取微信小程序 login code"""
    server, ref = parse_yyb_entry(entry)
    if not server or not ref:
        return None

    url = f"http://{server}/wxapp/getCode"
    log(f"   🧾 [授权] 取码请求 {url}")

    try:
        response = direct_session().post(
            url,
            json={"ref": ref, "app_id": WX_APP_ID},
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
        # YYB 可能把 code 返回成字符串 "0"，统一按数字比较
        try:
            code_ok = int(str(data.get("code")))
        except Exception:
            code_ok = -1
        if code_ok != 0 or not code:
            log(f"   ❌ [授权] 取码失败（{brief_error(data.get('msg') or data.get('message') or data.get('code'))}）")
            return None

        log("   ✅ [授权] 取码成功")
        return code
    except Exception as e:
        log(f"   ❌ [授权] 取码异常：{e}")
        return None


# =============================================================================
# OPPO 登录 (已修正 pre-auth 判定)
# =============================================================================
def login(code: str, proxies: Optional[Dict[str, str]] = None,
          server: str = "") -> Tuple[Optional[str], Optional[str], str]:
    """用微信 code 完成小程序登录，返回 (sessionId, aesSessionId, openid)"""
    # 1. pre-auth
    sign, ts, nonce = generate_sign({"loginType": "wechat", "code": code})
    headers = {
        "Content-Type": "application/json",
        "User-Agent": UA,
        "Referer": "https://servicewechat.com/wx9c825da1a7ba062e/592/page-frame.html",
        "source_type": "503",
        "s_channel": "program_wx",
        "s_version": "80457",
    }
    try:
        resp = request_with_proxy(
            "POST",
            PRE_AUTH_URL,
            json={
                "loginType": "wechat",
                "code": code,
                "appKey": APP_KEY,
                "timestamp": ts,
                "nonce": nonce,
                "sign": sign,
            },
            headers=headers,
            proxies=proxies,
            server=server,
        )
        data = resp.json()
        # ★ 修正：判断 success 字段
        if not data.get("success"):
            log(f"   ❌ [登录] pre-auth 未通过（{brief_error(data.get('message') or data.get('errorMessage') or data.get('code'))}）")
            return None, None, ""

        inner = data["data"]
        openid_ret = inner["openId"]
        encrypted_session = inner.get("encryptedSession")
        if not encrypted_session:
            log("   ❌ [登录] pre-auth 未返回 encryptedSession")
            return None, None, ""

        log(f"   ✅ [登录] pre-auth 通过（openid {mask(openid_ret)}）")
    except Exception as e:
        log(f"❌ pre-auth 异常: {e}")
        return None, None, ""

    # 3. 用 encryptedSession 换取最终凭证
    headers2 = {
        "NEWOPPOSID": encrypted_session,
        "openid": openid_ret,
        "source_type": "503",
        "s_channel": "program_wx",
        "s_version": "80457",
        "User-Agent": UA,
        "Referer": "https://servicewechat.com/wx9c825da1a7ba062e/592/page-frame.html",
    }
    try:
        resp2 = request_with_proxy(
            "GET",
            MEMBER_INFO_URL,
            headers=headers2,
            proxies=proxies,
            server=server,
        )
        info = resp2.json()
        if info.get("code") != 200:
            log(f"   ❌ [登录] 换取 session 失败（{brief_error(info.get('message') or info.get('code'))}）")
            return None, None, openid_ret

        inner2 = info["data"]
        session_id = inner2.get("sessionId")
        aes_key = inner2.get("aesSessionId")
        if not session_id or not aes_key:
            log("❌ member/info 返回缺少 sessionId/aesSessionId")
            return None, None, openid_ret

        log("   ✅ [登录] 获取最终凭证成功")
        return session_id, aes_key, openid_ret
    except Exception as e:
        log(f"❌ member/info 请求异常: {e}")
        return None, None, openid_ret


# =============================================================================
# 缓存管理 (凭证 + 活动ID)
# =============================================================================
def read_token_cache() -> Dict[str, Any]:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"accounts": {}, "activity_ids": {}}
        data.setdefault("accounts", {})
        data.setdefault("activity_ids", {})
        return data
    except Exception:
        return {"accounts": {}, "activity_ids": {}}


def write_token_cache(cache: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"   ⚠️ [缓存] 保存失败（不影响本次执行）：{exc}")


def cache_key(server: str, ref: str) -> str:
    """缓存键：地址|标识，避免不同 YYB 地址下同名标识串号。"""
    return f"{server}|{ref}"


def read_cache_entry(cache: Dict[str, Any], server: str, ref: str) -> Dict[str, Any]:
    accounts = cache.setdefault("accounts", {})
    ck = cache_key(server, ref)
    entry = accounts.get(ck)
    if isinstance(entry, dict) and entry.get("sessionId"):
        return entry
    # 兼容旧版仅按 ref 存的缓存：读到就迁移到新键
    legacy = accounts.get(ref)
    if isinstance(legacy, dict) and legacy.get("sessionId"):
        accounts[ck] = legacy
        accounts.pop(ref, None)
        write_token_cache(cache)
        return legacy
    return {}


def save_cache_entry(cache: Dict[str, Any], server: str, ref: str, entry: Dict[str, Any]) -> None:
    accounts = cache.setdefault("accounts", {})
    accounts[cache_key(server, ref)] = {**entry, "updatedAt": now_text()}
    write_token_cache(cache)


def drop_cache_entry(cache: Dict[str, Any], server: str, ref: str) -> None:
    accounts = cache.setdefault("accounts", {})
    ck = cache_key(server, ref)
    if ck in accounts:
        accounts.pop(ck, None)
        write_token_cache(cache)


def get_cached_activity_ids(cache: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """从缓存中获取当月的活动ID"""
    info = cache.get("activity_ids", {})
    if info.get("month") == time.strftime("%Y-%m"):
        return info.get("sign_activity_id"), info.get("task_activity_id")
    return None, None


def update_activity_ids_cache(cache: Dict[str, Any], sign_id: str, task_id: str) -> None:
    cache["activity_ids"] = {
        "month": time.strftime("%Y-%m"),
        "sign_activity_id": sign_id,
        "task_activity_id": task_id,
    }


# =============================================================================
# 活动 ID 自动提取
# =============================================================================
def extract_activity_ids() -> Tuple[Optional[str], Optional[str]]:
    """
    从签到落地页提取签到活动 ID 和任务活动 ID
    返回 (sign_activity_id, task_activity_id)
    """
    url = LANDING_PAGE + LANDING_PARAMS
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://servicewechat.com/wx9c825da1a7ba062e/592/page-frame.html",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        html = resp.text
        match = re.search(r"window\.__DSL__\s*=\s*(\{.*?\});", html, re.DOTALL)
        if not match:
            log("⚠️ 未找到 window.__DSL__，使用默认活动 ID")
            return FALLBACK_SIGN_ACTIVITY_ID, FALLBACK_TASK_ACTIVITY_ID
        dsl = json.loads(match.group(1))
        sign_id = None
        task_id = None
        by_id = dsl.get("byId", {})
        for comp_id, comp in by_id.items():
            if comp.get("type") == "SignIn":
                sign_id = comp.get("attr", {}).get("activityInfo", {}).get("activityId")
            elif comp.get("type") == "Task":
                task_id = comp.get("attr", {}).get("taskActivityInfo", {}).get("activityId")
        if not sign_id:
            log("⚠️ 未提取到签到活动 ID，使用默认值")
            sign_id = FALLBACK_SIGN_ACTIVITY_ID
        if not task_id:
            log("⚠️ 未提取到任务活动 ID，使用默认值")
            task_id = FALLBACK_TASK_ACTIVITY_ID
        log(f"📌 签到活动 ID: {sign_id}")
        log(f"📌 任务活动 ID: {task_id}")
        return sign_id, task_id
    except Exception as e:
        log(f"❌ 提取活动 ID 异常: {e}")
        return FALLBACK_SIGN_ACTIVITY_ID, FALLBACK_TASK_ACTIVITY_ID


# =============================================================================
# 业务客户端
# =============================================================================
class OppoMiniClient:
    def __init__(self, session_id: str, aes_key: str, openid: str,
                 sign_activity_id: str, task_activity_id: str,
                 credits_action_id: str = CREDITS_ADD_ACTION_ID,
                 proxies: Optional[Dict[str, str]] = None,
                 server: str = "") -> None:
        self.session_id = session_id
        self.aes_key = aes_key
        self.openid = openid
        self.sign_activity_id = sign_activity_id
        self.task_activity_id = task_activity_id
        self.credits_action_id = credits_action_id
        self.proxies = proxies
        self.server = server
        self.auth_expired = False
        self.last_error = ""
        self.session = requests.Session()
        self.session.headers.update(self._build_headers())

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Cookie": f"NEWOPPOSID={self.session_id}; newopkey={self.aes_key}",
            "openid": self.openid,
            "source_type": "503",
            "s_channel": "program_wx",
            "s_version": "080457",
            "User-Agent": UA,
            "Referer": "https://hd.opposhop.cn/bp/b371ce270f7509f0?us=wode&um=qiandaobanner",
            "Accept": "application/json, text/plain, */*",
        }

    def _get(self, url: str, params: dict = None) -> dict:
        try:
            resp = request_with_proxy(
                "GET",
                url,
                params=params,
                headers=dict(self.session.headers),
                proxies=self.proxies,
                server=self.server,
                timeout=BROWSE_TIMEOUT,
            )
            return self._note(resp.json())
        except Exception as exc:
            self.last_error = str(exc)
            return {"_error": str(exc)}

    def _note(self, data: Any) -> dict:
        if isinstance(data, dict):
            if data.get("_error"):
                self.last_error = str(data.get("_error"))
            elif is_auth_error(data):
                self.auth_expired = True
                self.last_error = str(
                    data.get("message") or data.get("errorMessage")
                    or data.get("msg") or f"code {data.get('code')}"
                )
        return data

    def _post(self, url: str, json_body: dict = None) -> dict:
        headers = dict(self.session.headers)
        headers["Content-Type"] = "application/json"
        try:
            resp = request_with_proxy(
                "POST",
                url,
                json=json_body,
                headers=headers,
                proxies=self.proxies,
                server=self.server,
                timeout=BROWSE_TIMEOUT,
            )
            return self._note(resp.json())
        except Exception as exc:
            self.last_error = str(exc)
            return {"_error": str(exc)}

    def check_session(self) -> Tuple[bool, str, dict]:
        """开跑前校验凭证：积分接口 + 任务列表接口都返回正常才算有效。

        只查积分不够——积分接口偶尔对过期 NEWOPPOSID 也返回 200，
        而任务列表/任务提交才真正校验登录态，所以两个都查。
        """
        credit = self.credit_info()
        if self.auth_expired:
            return False, brief_error(self.last_error) or "积分接口提示登录失效", {}
        if not credit:
            return False, brief_error(self.last_error) or "积分接口未返回数据", {}

        self.task_list()
        if self.auth_expired:
            return False, brief_error(self.last_error) or "任务列表接口提示登录失效", {}

        return True, "", credit

    def is_login_valid(self) -> bool:
        data = self._get(API_CREDIT)
        return data.get("code") == 200

    def credit_info(self) -> dict:
        data = self._get(API_CREDIT)
        if data.get("code") == 200:
            return data.get("data", {})
        return {}

    def sign_detail(self) -> dict:
        data = self._get(API_SIGN_DETAIL, params={"activityId": self.sign_activity_id})
        if data.get("code") == 200:
            return data.get("data", {})
        return {}

    def do_sign(self) -> Tuple[bool, str, Optional[int]]:
        detail = self.sign_detail()
        if detail.get("todaySignIn") is True:
            days = detail.get("signInDayNum")
            return True, f"今日已签到，本周累计【{days}】天", 0

        body = {
            "activityId": str(self.sign_activity_id),
            "creditsAddActionId": str(self.credits_action_id),
            "business": 1,
        }
        data = self._post(API_SIGN_IN, json_body=body)
        if data.get("code") != 200:
            msg = str(data.get("message") or data.get("errorMessage") or data)
            if any(k in msg for k in ("已签", "重复", "已经签到", "今日已")):
                return True, f"今日已签到（{msg}）", 0
            return False, f"签到失败: {msg}", None

        info = data.get("data") or {}
        award = None
        if isinstance(info, dict):
            if info.get("receiveStatus") is False:
                fail = info.get("receiveFailMsg") or "领取失败"
                if any(k in str(fail) for k in ("已签", "重复", "今日")):
                    return True, f"今日已签到（{fail}）", 0
                return False, f"签到领取失败: {fail}", None
            try:
                award = int(info.get("awardValue") or 0)
            except:
                award = None

        detail2 = self.sign_detail()
        days = detail2.get("signInDayNum") or detail.get("signInDayNum") or "?"
        if award is not None:
            return True, f"签到成功，获得【{award}】积分，累计【{days}】天", award
        return True, f"签到成功，累计【{days}】天", 0

    def task_list(self) -> List[dict]:
        data = self._get(API_TASK_LIST, params={"activityId": self.task_activity_id, "source": "c"})
        if data.get("code") == 200:
            return list((data.get("data") or {}).get("taskDTOList") or [])
        return []

    def report_browse(self, task: dict) -> Tuple[bool, str]:
        params = {
            "taskId": str(task.get("taskId") or ""),
            "activityId": str(task.get("activityId") or self.task_activity_id),
            "taskType": str(task.get("taskType") or TASK_TYPE_BROWSE),
        }
        data = self._get(API_TASK_REPORT, params=params)
        if data.get("code") == 200:
            return True, ""
        reason = data.get("message") or data.get("errorMessage") or data.get("_error") or data.get("code")
        return False, str(reason)

    def receive_award(self, task: dict) -> Tuple[bool, int, str]:
        params = {
            "taskId": str(task.get("taskId") or ""),
            "activityId": str(task.get("activityId") or self.task_activity_id),
            "creditsAddActionId": str(self.credits_action_id),
            "business": "1",
        }
        data = self._get(API_TASK_RECEIVE, params=params)
        if data.get("code") != 200:
            msg = str(data.get("message") or data.get("errorMessage") or data)
            return False, 0, msg
        info = data.get("data") or {}
        if isinstance(info, dict) and info.get("receiveStatus") is False:
            return False, 0, str(info.get("receiveFailMsg") or "领奖失败")
        points = 0
        if isinstance(info, dict):
            try:
                points = int(info.get("awardValue") or 0)
            except:
                points = 0
        return True, points, f"+{points}" if points else "ok"

    @staticmethod
    def browse_seconds(task: dict) -> int:
        cfg = task.get("attachConfigOne") or {}
        try:
            sec = int(cfg.get("browseTime") or 5)
        except:
            sec = 5
        return max(1, min(sec, 30))

    @staticmethod
    def task_award_points(task: dict) -> str:
        cfg = task.get("awardAttachConfig") or {}
        pts = cfg.get("pointsNum")
        return str(pts) if pts is not None else "?"

    def do_browse_tasks(self, simulate_wait: bool = True) -> dict:
        stats = {"done": 0, "awarded": 0, "skipped": 0, "failed": 0, "points": 0,
                 "details": [], "manual_hint": False}
        tasks = self.task_list()
        if not tasks:
            log("   ⚠️ [任务] 任务列表为空")
            return stats

        browse = [t for t in tasks if int(t.get("taskType") or -1) == TASK_TYPE_BROWSE]
        other = [t for t in tasks if int(t.get("taskType") or -1) != TASK_TYPE_BROWSE]
        log(f"   📋 [任务] 共【{len(tasks)}】个，可自动浏览【{len(browse)}】个")

        for t in other:
            name = str(t.get("taskName") or t.get("taskId") or "未知任务")
            log(f"   ⏭️ [任务] {name} 已跳过（非浏览任务）")
            stats["skipped"] += 1
            stats["manual_hint"] = True

        for task in browse:
            if self.auth_expired:
                log("   ⚠️ [任务] 登录凭证失效，停止剩余任务")
                break
            name = str(task.get("taskName") or task.get("taskId"))
            status = int(task.get("taskStatus") or 0)
            task_id = str(task.get("taskId") or "")
            award_show = self.task_award_points(task)

            if not task_id:
                stats["skipped"] += 1
                continue

            if status == TASK_STATUS_DONE:
                log(f"   ✅ [任务] {name} 已完成")
                stats["skipped"] += 1
                continue

            if status == TASK_STATUS_TODO:
                wait_s = self.browse_seconds(task)
                log(f"   🔎 [任务] {name}（待完成，奖励约【{award_show}】）")
                if simulate_wait:
                    log(f"   👀 [任务] {name} 浏览等待 {wait_s}s")
                    time.sleep(wait_s + 0.5)
                ok_report, report_msg = self.report_browse(task)
                if not ok_report:
                    stats["failed"] += 1
                    log(f"   ❌ [任务] {name} 提交失败：{report_msg}")
                    continue
                stats["done"] += 1
                log(f"   📤 [任务] {name} 提交成功")
                time.sleep(0.8)
                status = TASK_STATUS_CLAIMABLE
            else:
                log(f"   🔎 [任务] {name}（待领奖，奖励约【{award_show}】）")

            ok, pts, msg = self.receive_award(task)
            if ok:
                stats["awarded"] += 1
                stats["points"] += pts
                if pts:
                    stats["details"].append(f"{name} +{pts}")
                    log(f"   🎁 [任务] {name} 领奖成功（+{pts}）")
                else:
                    stats["details"].append(f"{name} 领奖成功")
                    log(f"   🎁 [任务] {name} 领奖成功")
            else:
                if any(k in msg for k in ("已领", "已完成", "重复", "已经")):
                    stats["skipped"] += 1
                    log(f"   ⏭️ [任务] {name} 已跳过（{msg}）")
                else:
                    stats["failed"] += 1
                    stats["details"].append(f"领奖失败: {name} > {msg}")
                    log(f"   ❌ [任务] {name} 领奖失败：{msg}")
            time.sleep(0.6)

        return stats


# =============================================================================
# 通知推送（PushPlus，铛铛一下同款）
# =============================================================================
def send_pushplus(title: str, content: str) -> None:
    if not PLUSPLUS_TOKEN:
        log("   ℹ️ [推送] 未配置 PLUSPLUS_TOKEN，跳过 PushPlus")
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
        log("   ✅ [推送] PushPlus 推送成功")
    except Exception as exc:
        log(f"   ❌ [推送] PushPlus 推送失败：{exc}")


# =============================================================================
# 主流程
# =============================================================================
def run_account(server: str, sign_act_id: str, task_act_id: str,
                cache: dict, index: int) -> dict:
    server_addr, ref, note = parse_entry(server)
    title = f"标识 {ref}" + (f"（{note}）" if note else "")
    account_frame(index, len(SERVERS), title or server, f"{server_addr or server}@{ref}" if ref else server)

    result = {
        "index": index,
        "name": note or ref or f"账号{index}",
        "source": f"{server_addr}@{ref}" if ref else server,
        "success": False,
        "login_source": "",
        "user": "",
        "level": "",
        "points_before": None,
        "points_after": None,
        "sign_points": 0,
        "task_points": 0,
        "sign_already": False,
        "sign": "",
        "tasks": "",
        "points_delta": 0,
        "error": "",
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
    }

    # 品赞代理：业务请求代理优先，失败直连兜底
    proxies, proxy_ip = get_valid_proxy(server)
    result["proxyStatus"] = "使用品赞代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"
    if proxies:
        log(f"   🌐 [代理] {result['proxyStatus']}" + (f"（{proxy_ip}）" if proxy_ip else ""))

    if PROXY_API:
        time.sleep(PROXY_FETCH_INTERVAL)
    delay = random.randint(2, 5)
    log(f"   ⏳ [等待] 启动延迟 {delay}s")
    time.sleep(delay)

    if not ref:
        result["error"] = "YYB_SERVER 配置格式错误（应为 地址@账号标识）"
        log(f"   ❌ [配置] {result['error']}")
        return result

    ck = cache_key(server_addr, ref)

    for attempt in range(2):
        client = None
        try:
            # ---------- ① 首次尝试复用缓存凭证 ----------
            if attempt == 0:
                entry = read_cache_entry(cache, server_addr, ref)
                if entry.get("sessionId") and entry.get("aesSessionId"):
                    log(f"   💾 [缓存] 复用已保存的登录凭证（NEWOPPOSID {mask(entry['sessionId'])}）")
                    client = OppoMiniClient(entry["sessionId"], entry["aesSessionId"],
                                            entry.get("openid", ""), sign_act_id, task_act_id,
                                            proxies=proxies, server=server)
                    ok_session, session_reason, credit = client.check_session()
                    if not ok_session:
                        log(f"   ♻️ [缓存] 登录凭证未通过开跑前校验（{session_reason}），清理缓存后重新登录")
                        drop_cache_entry(cache, server_addr, ref)
                        client = None
                    else:
                        result["login_source"] = "缓存"
                        log("   ✅ [缓存] 开跑前校验通过（积分接口 + 任务列表接口）")
                        show_credit(result, credit)

            # ---------- ② 没有可用凭证 → 重新登录 ----------
            if client is None:
                code = get_code(server)
                if not code:
                    result["error"] = "取码失败（检查 YYB 服务地址与账号标识）"
                    log("   ❌ [登录] 取码失败，跳过该账号")
                    return result

                session_id, aes_key, openid_ret = login(code, proxies=proxies, server=server)
                if not session_id or not aes_key:
                    result["error"] = "登录失败（pre-auth 或 member/info 未通过，见上方日志）"
                    log("   ❌ [登录] 登录失败，跳过该账号")
                    return result

                save_cache_entry(cache, server_addr, ref, {
                    "sessionId": session_id,
                    "aesSessionId": aes_key,
                    "openid": openid_ret or "",
                })
                result["login_source"] = "新登录"
                log(f"   🔐 [登录] 登录成功 openid {openid_ret or '-'}（已写入缓存）")

                client = OppoMiniClient(session_id, aes_key, openid_ret or "", sign_act_id, task_act_id,
                                        proxies=proxies, server=server)
                ok_session, session_reason, credit = client.check_session()
                if not ok_session:
                    if attempt == 0:
                        log(f"   ♻️ [登录] 新凭证校验未通过（{session_reason}），清理缓存后重登一次")
                        drop_cache_entry(cache, server_addr, ref)
                        client = None
                        time.sleep(1.5)
                        continue
                    result["error"] = f"登录后凭证校验失败（{session_reason}）"
                    log(f"   ❌ [登录] 登录后凭证校验失败：{session_reason}")
                    return result
                log("   ✅ [登录] 登录后校验通过（积分接口 + 任务列表接口）")
                show_credit(result, credit)

            # ---------- ③ 签到 ----------
            ok, msg, award = client.do_sign()
            result["sign"] = msg
            if ok:
                log(f"   ✅ [签到] {msg}")
                result["sign_points"] = award or 0
                result["sign_already"] = ("今日已签" in msg) and result["sign_points"] == 0
            else:
                log(f"   ❌ [签到] {msg}")

            # ---------- ④ 浏览任务 ----------
            stats = client.do_browse_tasks(simulate_wait=SIMULATE_WAIT)
            result["task_points"] = stats.get("points", 0)
            result["tasks"] = (f"提交 {stats['done']} · 领奖 {stats['awarded']}"
                               f"（+{stats['points']}）· 跳过 {stats['skipped']} · 失败 {stats['failed']}")
            if stats.get("manual_hint"):
                log("   ℹ️ [任务] 非浏览任务需人工完成")

            # ---------- ⑤ 执行中凭证失效 → 清缓存重登重跑一次 ----------
            if client.auth_expired and attempt == 0:
                log("   🔄 [重试] 执行中登录凭证失效，清理缓存重登后重跑一次")
                drop_cache_entry(cache, server_addr, ref)
                time.sleep(1.5)
                continue

            # ---------- ⑥ 复查积分 ----------
            credit2 = client.credit_info()
            points_after = None
            if credit2:
                points_after = credit2.get("amount")
                result["points_after"] = points_after
            elif result["points_before"] is not None:
                points_after = result["points_before"]
                result["points_after"] = points_after

            delta = 0
            before = result["points_before"]
            if before is not None and points_after is not None:
                try:
                    delta = int(points_after) - int(before)
                except Exception:
                    delta = result["sign_points"] + result["task_points"]
            else:
                delta = result["sign_points"] + result["task_points"]
            result["points_delta"] = delta

            if points_after is not None:
                log(f"   💰 [积分] {points_text(before)} → {points_text(points_after)}（{delta:+d}）")
            else:
                log(f"   ⚠️ [积分] 查询失败，按任务奖励推算：+{delta}")

            result["success"] = bool(ok) or ("今日已签" in msg) or bool(stats.get("awarded")) or bool(stats.get("done"))
            if result["success"]:
                log("   ✅ [完成] 该账号任务执行完成")
            else:
                result["error"] = msg or "签到与任务均未成功（详见上方日志）"
                log(f"   ⚠️ [完成] 流程结束，但未完成有效签到/任务")
            return result

        except Exception as exc:
            result["error"] = f"执行异常：{exc}"
            log(f"   ❌ [异常] {exc}")
            return result

    result["error"] = result["error"] or "重试后仍未完成（详见上方日志）"
    return result


def show_credit(result: dict, credit: dict) -> None:
    """把用户信息与当前积分写在登录行正下方"""
    user = credit.get("userNickName") or credit.get("userName") or ""
    level = credit.get("userLevel")
    amount = credit.get("amount")
    if user:
        result["user"] = user
    if level not in (None, ""):
        result["level"] = str(level)
    result["points_before"] = amount
    suffix = f" · 等级 {level}" if level not in (None, "") else ""
    log(f"   💰 [积分] 当前 {points_text(amount)} 分{suffix}")


def should_retry_with_new_ids(result: dict) -> bool:
    """根据错误信息判断是否需要重新拉取活动ID"""
    msg = result.get("sign", "") + result.get("tasks", "")
    return any(k in msg for k in ("活动已经结束", "活动已过期", "活动不存在"))


def main():
    box_top("🛒 OPPO 商城 签到 + 浏览任务")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(SERVERS)} 个")
    box_line("💾 缓存", "token_caches/oppo_token_cache.json")
    box_bottom()

    cache = read_token_cache()

    # 获取活动ID（优先缓存）
    sign_act_id, task_act_id = get_cached_activity_ids(cache)
    if not sign_act_id or not task_act_id:
        log("   🔍 [活动] 缓存中无活动 ID，从落地页提取")
        sign_act_id, task_act_id = extract_activity_ids()
        update_activity_ids_cache(cache, sign_act_id, task_act_id)
        write_token_cache(cache)
    log(f"   🎯 [活动] 签到 ID {sign_act_id} | 任务 ID {task_act_id}")

    results = []
    for idx, server in enumerate(SERVERS, 1):
        try:
            res = run_account(server, sign_act_id, task_act_id, cache, idx)
            # 失败时尝试重新拉取活动ID并重试一次
            if not res.get("success") and should_retry_with_new_ids(res):
                log("   ⚠️ [活动] 疑似活动 ID 过期，重新提取并重试本账号")
                new_sign, new_task = extract_activity_ids()
                if new_sign != sign_act_id or new_task != task_act_id:
                    update_activity_ids_cache(cache, new_sign, new_task)
                    write_token_cache(cache)
                    log(f"   🔄 [活动] 使用新 ID 重试：签到 {new_sign} | 任务 {new_task}")
                    res = run_account(server, new_sign, new_task, cache, idx)
                    sign_act_id, task_act_id = new_sign, new_task
                else:
                    log("   ℹ️ [活动] 活动 ID 未变化，不重试")
        except Exception as exc:
            _, ref, note = parse_entry(server)
            res = {
                "index": idx, "name": note or ref or f"账号{idx}",
                "source": server, "success": False, "error": f"执行异常：{exc}",
                "login_source": "", "user": "", "level": "",
                "points_before": None, "points_after": None,
                "sign_points": 0, "task_points": 0, "sign": "", "tasks": "",
                "points_delta": 0, "proxyStatus": "-", "proxyIp": "-",
            }
            log(f"   ❌ [异常] 该账号执行异常：{exc}")
        results.append(res)

        hr()
        if idx < len(SERVERS):
            log("   ⏳ 等待2秒后执行下一个账号...")
            time.sleep(2)

    # ---------- 逐账号明细（汇总框上方） ----------
    for res in results:
        icon = "✅" if res.get("success") else "❌"
        log("")
        note_txt = f"（{res['name']}）" if res.get("name") and res["name"] != res.get("source") else ""
        log(f"{icon} 【账号 {res['index']} · {res.get('source', '-')}{note_txt}】")
        if res.get("login_source"):
            log(f"   🔐 [登录] {'缓存复用' if res['login_source'] == '缓存' else '新登录'}")
            user_line = res.get("user") or "(未返回昵称)"
            if res.get("level"):
                user_line += f" · 等级 {res['level']}"
            log(f"   👤 [用户] {user_line}")
            log(f"   📅 [签到] {res.get('sign') or '未获取到签到结果'}")
            log(f"   📋 [任务] {res.get('tasks') or '无任务数据'}")
            log(f"   💰 [积分] {points_text(res.get('points_before'))} → "
                f"{points_text(res.get('points_after'))}（{int(res.get('points_delta') or 0):+d}）")
        if not res.get("success"):
            log(f"   ⚠️ [失败] {res.get('error') or '未知原因'}")

    ok_count = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - ok_count
    total_delta = sum(int(r.get("points_delta") or 0) for r in results if r.get("success"))

    box_top("🏁 OPPO 商城 执行汇总")
    box_line("✅ 成功账号", f"{ok_count} / {len(results)}")
    box_line("❌ 失败账号", f"{fail_count} / {len(results)}")
    box_line("💰 今日总新增", f"{total_delta} 积分")
    box_line("🕒 结束时间", now_text())
    box_bottom()

    # ---------- 通知 ----------
    lines = ["### OPPO 商城 签到任务"]
    for r in results:
        flag = "✅" if r.get("success") else "❌"
        lines.append(f"\n#### {flag} 账号 {r['index']} · {r.get('source', '-')}")
        if r.get("login_source"):
            lines.append(f"- 登录：{'缓存复用' if r['login_source'] == '缓存' else '新登录'}")
            lines.append(f"- 用户：{r.get('user') or '未返回'}")
            lines.append(f"- 签到：{r.get('sign') or '无结果'}")
            lines.append(f"- 任务：{r.get('tasks') or '无任务数据'}")
            lines.append(f"- 积分：{points_text(r.get('points_before'))} → "
                         f"{points_text(r.get('points_after'))}（{int(r.get('points_delta') or 0):+d}）")
        if not r.get("success"):
            lines.append(f"- 失败原因：{r.get('error') or '未知'}")
    content = "\n".join(lines)

    if send_qinglong_notify("OPPO 商城", content):
        log("   ✅ [通知] 青龙通知模块调用完成（送达情况以通知渠道为准）")
    send_pushplus("📱 OPPO 商城签到任务", content)


if __name__ == "__main__":
    main()
