#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 奈雪的茶
# cron: 2 10,22 * * *
"""
奈雪点单（奈雪的茶）动态 code 签到

流程：YYB_SERVER 取码 → 奈雪登录接口换 token → 用户信息（开跑前校验）
      → 奈雪币 → 签到状态/签到 → 复查奈雪币

环境变量：
- YYB_SERVER      必填；YYB Go 地址@微信账号标识，多账号每行一条，可带 #备注
- PROXY_API       可选；品赞代理提取链接
- PROXY_TYPE      可选；http / socks5，默认 http
- PLUSPLUS_TOKEN  可选；PushPlus 推送
- NXDC_NOTIFY     默认 1；0=关闭青龙 notify.py 通知

缓存：脚本目录 token_caches/nxdc_token_cache.json，按「地址|标识」隔离，不设固定过期
"""

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import random
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

APP_NAME = "奈雪的茶"
APPID = "wxab7430e6e8b9a4ab"

OPEN_ID = "QL6ZOftGzbziPlZwfiXM"
SIGN_SECRET = "sArMTldQ9tqU19XIRDMWz7BO5WaeBnrezA"
LOGIN_URL = "https://tm-api.pin-dao.cn/passport/authenticate/wxapp/verify/grc"
USERINFO_URL = "https://tm-web.pin-dao.cn/user/base-userinfo"
SIGN_RECORDS_URL = "https://tm-web.pin-dao.cn/user/sign/records"
SIGN_SAVE_URL = "https://tm-web.pin-dao.cn/user/sign/save"
ACCOUNT_URL = "https://tm-web.pin-dao.cn/user/account/user-account"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "nxdc_token_cache.json")

PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
NOTIFY_ENABLED = os.getenv("NXDC_NOTIFY", "1") != "0"

BOX_WIDTH = 48
BOX_INNER = 46

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781 NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/19725",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781 NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/19613",
]

# 只认明确的凭证失效提示，业务失败不误判
AUTH_PATTERN = re.compile(
    r"未登录|登录失效|登录已过期|请重新登录|token\s*(无效|过期|失效)"
    r"|无效的?(token|凭证)|授权失败|认证失败|-401|\b401\b|\b403\b",
    re.I,
)


# ===================== 日志与边框 =====================
def log(*args):
    print(*args, flush=True)


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


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ===================== 工具函数 =====================
def sleep(seconds: float) -> None:
    time.sleep(seconds)


def rand_sleep(min_s: float = 2, max_s: float = 5) -> None:
    sleep(random.uniform(min_s, max_s))


def get_ua() -> str:
    return random.choice(UA_LIST)


def random_int_string(length: int) -> str:
    return "".join(random.choice("123456789") for _ in range(length))


def short_token(token: str) -> str:
    value = str(token or "")
    return f"{value[:6]}***{value[-6:]}" if len(value) > 14 else (value or "-")


def hmac_sha1_base64(secret: str, message: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def build_request_data(extra_params: dict | None = None) -> dict:
    nonce = random_int_string(6)
    timestamp = int(time.time())
    url_path = f"nonce={nonce}&openId={OPEN_ID}&timestamp={timestamp}"
    signature = hmac_sha1_base64(SIGN_SECRET, url_path)

    common = {
        "platform": "wxapp",
        "version": "6.0.42",
        "imei": "",
        "osn": "microsoft",
        "sv": "Windows 10 x64",
        "lat": "",
        "lng": "",
        "lang": "zh_CN",
        "currency": "CNY",
        "timeZone": "",
        "nonce": int(nonce),
        "openId": OPEN_ID,
        "timestamp": timestamp,
        "signature": signature,
    }

    params = {
        "businessType": 1,
        "brand": 26000252,
        "tenantId": 1,
        "channel": 2,
        "stallType": None,
        "storeId": "",
        "storeType": "",
        "cityId": "",
    }
    if extra_params:
        params.update(extra_params)

    return {"common": common, "params": params}


def china_date_parts() -> tuple[int, int, int]:
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.year, now.month, now.day


def mask_phone(phone: str) -> str:
    phone = str(phone or "")
    if len(phone) >= 11:
        return f"{phone[:3]}****{phone[7:]}"
    return phone or "未知"


def brief(value, limit=120):
    text = str(value or "").replace("\n", " ")
    return text[: limit - 1] + "…" if len(text) > limit else text


def fmt_coin(value):
    return str(value) if value not in (None, "", "-") else "未知"


def to_number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_auth_error(code, message) -> bool:
    number = to_number(code)
    if number in (401, 403, -401, -403):
        return True
    return bool(AUTH_PATTERN.search(str(message or "")))


def parse_entry(raw):
    """解析 地址@标识[#备注]，返回 (server, ref, note)"""
    value = str(raw or "").strip()
    note = ""
    body = value
    hash_pos = value.rfind("#")
    at_pos = value.rfind("@")
    if hash_pos > at_pos:
        body = value[:hash_pos].strip()
        note = value[hash_pos + 1:].strip()
    at_pos = body.rfind("@")
    if at_pos <= 0:
        return "", "", note
    server = re.sub(r"^https?://", "", body[:at_pos].strip(), flags=re.I).rstrip("/")
    ref = body[at_pos + 1:].strip()
    if not server or not ref:
        return "", "", note
    return server, ref, note


def parse_yyb_go_entry(raw_value):
    server, ref, _ = parse_entry(raw_value)
    if not server or not ref:
        log(f"   ❌ [配置] YYB_SERVER 格式应为 地址@微信账号标识[#备注]，当前值：{raw_value}")
    return server, ref


def cache_key(server, ref):
    return f"{server}|{ref}"


# ===================== Token 缓存 =====================
def read_token_cache() -> dict:
    try:
        if not os.path.exists(TOKEN_CACHE_FILE):
            return {}
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_token_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"   ⚠️ [缓存] 写入失败（不影响执行）：{exc}")


def read_cache_entry(ck, ref, raw):
    cache = read_token_cache()
    if (cache.get(ck) or {}).get("token"):
        return cache[ck]
    for key in (ref, raw):
        entry = cache.get(key) or {}
        if entry.get("token"):
            cache[ck] = entry
            for k in (ref, raw):
                cache.pop(k, None)
            write_token_cache(cache)
            log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」")
            return entry
    return {}


def save_cache_entry(ck, token):
    cache = read_token_cache()
    cache[ck] = {"token": token, "updatedAt": now_text()}
    write_token_cache(cache)


def drop_cache_entry(ck):
    cache = read_token_cache()
    if ck in cache:
        cache.pop(ck, None)
        write_token_cache(cache)


# ===================== 品赞代理 =====================
def parse_proxy_response(text) -> dict | None:
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)

    text = text.strip()
    if not text:
        return None

    parsed_json = False
    try:
        data = json.loads(text)
        parsed_json = True
        proxy_obj = None

        if isinstance(data.get("data"), list) and data["data"]:
            proxy_obj = data["data"][0]
        elif isinstance(data.get("data"), dict):
            data_obj = data["data"]
            proxy_list = data_obj.get("proxy_list")
            proxy_obj = proxy_list[0] if isinstance(proxy_list, list) and proxy_list else data_obj
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

    if parsed_json:
        return None

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


def build_proxy_dict(proxy_info: dict | None) -> dict | None:
    if not proxy_info:
        return None

    host = proxy_info["host"]
    port = proxy_info["port"]
    username = proxy_info.get("username", "")
    password = proxy_info.get("password", "")

    auth = f"{quote(username)}:{quote(password)}@" if username and password else ""
    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"
    log(f"   🌐 [代理] 生成 {scheme.upper()} 代理 {host}:{port}")
    return {"http": proxy_url, "https": proxy_url}


def validate_proxy(proxies: dict | None):
    if not proxies:
        return False, ""

    try:
        res = requests.get(PROXY_VALIDATE_URL, proxies=proxies, timeout=15)
        if res.status_code == 200:
            try:
                ip = res.json().get("origin", "未知")
            except Exception:
                ip = "未知"
            log(f"   ✅ [代理] 验证通过，出口 IP: {ip}")
            return True, ip
    except Exception as exc:
        log(f"   ⚠️ [代理] 验证失败：{exc}")
    return False, ""


def get_valid_proxy():
    if not PROXY_API:
        log("   🌐 [代理] 未配置 PROXY_API，使用直连")
        return None, ""

    log("   🔌 [代理] 正在获取品赞代理...")
    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            res = requests.get(PROXY_API, timeout=15)
            proxy_info = parse_proxy_response(res.text)
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


def request_with_proxy(method: str, url: str, *, proxies: dict | None = None, **kwargs):
    kwargs.setdefault("timeout", 30)
    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            log(f"   ⚠️ [代理] 代理请求失败：{exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            log("   🔄 [兜底] 切换直连重试")
    return requests.request(method, url, **kwargs)


# ===================== 取码 =====================
def get_code(server_entry: str) -> str | None:
    parsed_server, ref = parse_yyb_go_entry(server_entry)
    if not parsed_server or not ref:
        return None

    url = f"http://{parsed_server}/wxapp/getCode"
    log(f"   🧾 [授权] 取码请求 {url}")
    try:
        res = requests.post(
            url,
            json={"ref": ref, "app_id": APPID},
            timeout=20,
            proxies={"http": None, "https": None},
        )
        data = res.json()
        result = (data.get("data") or {}).get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                result = {}
        code = (result or {}).get("code")
        try:
            code_num = int(str(data.get("code")))
        except (TypeError, ValueError):
            code_num = -1
        if code_num != 0 or not code:
            reason = str(data.get("message") or data.get("msg") or "").strip()
            if not reason:
                reason = f"YYB 返回 code={code_num}，未取到 code 值"
            log(f"   ❌ [取码] 取码失败：{brief(reason, 80)}")
            return None
        log("   ✅ [取码] 取码成功")
        return code
    except Exception as exc:
        log(f"   ❌ [取码] 取码异常：{exc}")
        log(f"   💡 [提示] 请检查 YYB 服务地址 http://{parsed_server} 是否在线、{ref} 是否已登录")
        return None


def extract_token(data) -> str | None:
    if not isinstance(data, dict):
        return None

    candidates = [
        data.get("token"),
        data.get("accessToken"),
        data.get("access_token"),
        data.get("authToken"),
        data.get("memberToken"),
    ]

    inner = data.get("data")
    if isinstance(inner, dict):
        candidates.extend([
            inner.get("token"),
            inner.get("accessToken"),
            inner.get("access_token"),
            inner.get("authToken"),
            inner.get("memberToken"),
            inner.get("access_token_value"),
        ])
        token_info = inner.get("tokenInfo")
        if isinstance(token_info, dict):
            candidates.extend([token_info.get("token"), token_info.get("accessToken"), token_info.get("access_token")])
        user_token = inner.get("userToken")
        if isinstance(user_token, dict):
            candidates.extend([user_token.get("token"), user_token.get("accessToken"), user_token.get("access_token")])

    for item in candidates:
        if item and item != "null":
            return str(item)
    return None


# ===================== 业务接口 =====================
def login_by_code(code: str, ua: str, proxies: dict | None):
    headers = {
        "Host": "tm-api.pin-dao.cn",
        "Connection": "keep-alive",
        "Authorization": "Bearer null",
        "User-Agent": ua,
        "xweb_xhr": "1",
        "storeId": "",
        "Content-Type": "application/json",
        "iv": random_int_string(16),
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": f"https://servicewechat.com/{APPID}/819/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    body = build_request_data({
        "appId": APPID,
        "dAId": "",
        "type": 3,
        "wxappCode": code,
        "regChannelCode": "|1027",
    })

    log("   🔐 [登录] 使用 code 换取 token...")
    try:
        res = request_with_proxy(
            "POST", LOGIN_URL,
            headers=headers,
            data=json.dumps(body, separators=(",", ":"), ensure_ascii=False),
            proxies=proxies,
        )
        try:
            data = res.json()
        except Exception:
            data = {"raw": res.text[:500]}

        token = extract_token(data)
        if token:
            log(f"   ✅ [登录] 登录成功（token {short_token(token)}，已写入缓存）")
            return token, data

        log(f"   ❌ [登录] 登录成功但未识别 token 字段：{brief(data, 160)}")
        return None, data
    except Exception as exc:
        log(f"   ❌ [登录] 登录异常：{exc}")
        return None, None


def call_api(url: str, token: str, ua: str, proxies: dict | None, body: dict | None = None) -> dict:
    headers = {
        "User-Agent": ua,
        "Authorization": f"Bearer {token}",
        "Referer": "https://tm-web.pin-dao.cn/",
        "Origin": "https://tm-web.pin-dao.cn",
        "Content-Type": "application/json",
    }
    payload = build_request_data(body or {})
    try:
        res = request_with_proxy(
            "POST", url,
            headers=headers,
            data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            proxies=proxies,
        )
        return res.json()
    except Exception as exc:
        return {"code": -1, "message": str(exc)}


def api_ok(res: dict) -> bool:
    return to_number(res.get("code")) == 0


def api_error(res: dict) -> str:
    return str(res.get("message") or res.get("msg") or brief(res, 80))


# ===================== 业务逻辑 =====================
def run_account(idx: int, total: int, server_entry: str) -> dict:
    server, ref, note = parse_entry(server_entry)
    title = f"标识 {ref}" + (f"（{note}）" if note else "")
    account_frame(idx, total, title or "标识 未解析", f"{server}@{ref}" if ref else server_entry)

    result = {
        "index": idx,
        "source": f"{server}@{ref}" if ref else server_entry,
        "name": note or ref or f"账号{idx}",
        "success": False,
        "loginSource": "",
        "user": "-",
        "signMsg": "-",
        "coin": "未知",
        "coinBefore": None,
        "coinAfter": None,
        "delta": 0,
        "error": "",
        "proxyStatus": "使用直连",
        "proxyIp": "-",
    }

    if not server or not ref:
        result["error"] = "YYB_SERVER 配置格式错误（应为 地址@微信账号标识）"
        log(f"   ❌ [配置] {result['error']}")
        return result

    proxies, proxy_ip = get_valid_proxy()
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"
    if PROXY_API:
        sleep(PROXY_FETCH_INTERVAL)

    ua = get_ua()
    ck = cache_key(server, ref)
    token = ""
    delay = random.randint(2, 4)
    log(f"   ⏳ [等待] 启动延迟 {delay}s")
    sleep(delay)

    for attempt in range(2):
        try:
            # ---------- ① 复用缓存 ----------
            if attempt == 0 and not token:
                entry = read_cache_entry(ck, ref, server_entry)
                if entry.get("token"):
                    token = entry["token"]
                    log(f"   💾 [缓存] 复用已保存的登录 token（{short_token(token)}）")
                    result["loginSource"] = "缓存"

            # ---------- ② 开跑前校验（用户信息接口） ----------
            userinfo = call_api(USERINFO_URL, token, ua, proxies, {}) if token else {"code": -1}

            if token and not api_ok(userinfo):
                message = api_error(userinfo)
                if is_auth_error(userinfo.get("code"), message):
                    log(f"   ♻️ [缓存] 登录凭证未通过开跑前校验（{message}），清理缓存后重新登录")
                    drop_cache_entry(ck)
                    token = ""
                else:
                    result["error"] = f"缓存 token 校验失败（{message}）"
                    log(f"   ❌ [用户] 缓存 token 校验失败，保留缓存不删除：{message}")
                    return result

            # ---------- ③ 重新登录 ----------
            if not token:
                code = get_code(server_entry)
                if not code:
                    result["error"] = "取码失败（检查 YYB 服务地址与账号标识）"
                    log("   ❌ [登录] 取码失败，跳过该账号")
                    return result
                token, _ = login_by_code(code, ua, proxies)
                if not token:
                    result["error"] = "登录失败或未识别 token 字段"
                    log("   ❌ [登录] 登录失败，跳过该账号")
                    return result
                save_cache_entry(ck, token)
                result["loginSource"] = "新登录"

                userinfo = call_api(USERINFO_URL, token, ua, proxies, {})
                if not api_ok(userinfo):
                    message = api_error(userinfo)
                    if is_auth_error(userinfo.get("code"), message) and attempt == 0:
                        log(f"   ♻️ [登录] 新凭证校验未通过（{message}），清理缓存后重登一次")
                        drop_cache_entry(ck)
                        token = ""
                        sleep(1.5)
                        continue
                    result["error"] = f"登录后用户信息查询失败（{message}）"
                    log(f"   ❌ [用户] 登录后用户信息查询失败：{message}")
                    return result
                log("   ✅ [校验] 登录凭证校验通过（用户信息接口）")

            phone = (userinfo.get("data") or {}).get("phone", "")
            result["user"] = mask_phone(phone)
            log(f"   👤 [用户] {result['user']}")

            # ---------- ④ 当前奈雪币 ----------
            rand_sleep(1.5, 3)
            account = call_api(ACCOUNT_URL, token, ua, proxies, {})
            if api_ok(account):
                result["coinBefore"] = (account.get("data") or {}).get("coin")
                result["coin"] = fmt_coin(result["coinBefore"])
                log(f"   💰 [积分] 当前 {result['coin']} 奈雪币")
            else:
                log(f"   ⚠️ [积分] 查询奈雪币失败：{api_error(account)}")

            # ---------- ⑤ 签到 ----------
            year, month, day = china_date_parts()
            sign_date = f"{year}-{month:02d}-01"
            today = f"{year}-{month:02d}-{day:02d}"

            rand_sleep(1.5, 3)
            records = call_api(SIGN_RECORDS_URL, token, ua, proxies,
                               {"signDate": sign_date, "startDate": today})
            sign_ok = False
            if not api_ok(records):
                message = api_error(records)
                if is_auth_error(records.get("code"), message) and attempt == 0:
                    log(f"   🔄 [重试] 签到查询登录态失效（{message}），清理缓存重登后重跑一次")
                    drop_cache_entry(ck)
                    token = ""
                    sleep(1.5)
                    continue
                result["signMsg"] = f"查询签到失败：{message}"
                log(f"   ❌ [签到] {result['signMsg']}")
            else:
                status = bool((records.get("data") or {}).get("status"))
                count = (records.get("data") or {}).get("signCount", "-")
                if status:
                    result["signMsg"] = f"今日已签到，累计 {count} 天"
                    sign_ok = True
                    log(f"   ℹ️ [签到] 今日已签到，累计 {count} 天")
                else:
                    rand_sleep(1.5, 3)
                    save_res = call_api(SIGN_SAVE_URL, token, ua, proxies, {"signDate": today})
                    if api_ok(save_res) and (save_res.get("data") or {}).get("flag"):
                        result["signMsg"] = f"签到成功，累计 {count} 天"
                        sign_ok = True
                        log(f"   ✅ [签到] 签到成功，累计 {count} 天")
                    else:
                        message = api_error(save_res)
                        if is_auth_error(save_res.get("code"), message) and attempt == 0:
                            log(f"   🔄 [重试] 签到登录态失效（{message}），清理缓存重登后重跑一次")
                            drop_cache_entry(ck)
                            token = ""
                            sleep(1.5)
                            continue
                        result["signMsg"] = f"签到失败：{message}"
                        log(f"   ❌ [签到] {result['signMsg']}")

            # ---------- ⑥ 复查奈雪币 ----------
            rand_sleep(1.5, 3)
            account2 = call_api(ACCOUNT_URL, token, ua, proxies, {})
            if api_ok(account2):
                result["coinAfter"] = (account2.get("data") or {}).get("coin")
                result["coin"] = fmt_coin(result["coinAfter"])
            else:
                result["coinAfter"] = result["coinBefore"]

            before_num = to_number(result["coinBefore"])
            after_num = to_number(result["coinAfter"])
            if before_num is not None and after_num is not None:
                result["delta"] = after_num - before_num
                log(f"   💰 [积分] {before_num} → {after_num}（{int(result['delta']):+d}）")
            else:
                log(f"   💰 [积分] 当前 {fmt_coin(result['coinAfter'])} 奈雪币")

            result["success"] = sign_ok
            if sign_ok:
                log("   ✅ [完成] 该账号任务执行完成")
            else:
                result["error"] = result["signMsg"] if result["signMsg"] != "-" else "签到未成功"
                log("   ⚠️ [完成] 签到未成功")
            return result

        except Exception as exc:
            result["error"] = f"执行异常：{exc}"
            log(f"   ❌ [异常] {exc}")
            return result

    result["error"] = result["error"] or "重试后仍未完成（详见上方日志）"
    return result


# ===================== 通知 =====================
def build_notify(results):
    lines = [f"### {APP_NAME} 每日签到"]
    for r in results:
        flag = "✅" if r["success"] else "❌"
        lines.append("")
        lines.append(f"#### {flag} 账号 {r['index']} · {r['source']}")
        if r["loginSource"]:
            lines.append(f"- 登录：{r['loginSource']}")
            lines.append(f"- 用户：{r['user']}")
            lines.append(f"- 签到：{r['signMsg'] or '无结果'}")
            lines.append(f"- 奈雪币：{fmt_coin(r['coinBefore'])} → {fmt_coin(r['coinAfter'])}（{int(r['delta']):+d}）")
        if not r["success"]:
            lines.append(f"- 失败原因：{r['error'] or '未知'}")
    return "\n".join(lines)


def send_qinglong_notify(title, content):
    if not NOTIFY_ENABLED:
        log("   ℹ️ [通知] NXDC_NOTIFY=0，已关闭通知")
        return False
    for candidate in (
        "/ql/data/scripts/notify.py",
        "/ql/scripts/notify.py",
        "/ql/data/notify.py",
        os.path.join(SCRIPT_DIR, "notify.py"),
    ):
        if not os.path.exists(candidate):
            continue
        try:
            spec = importlib.util.spec_from_file_location("nxdc_ql_notify", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sender = getattr(module, "send", None) or getattr(module, "sendNotify", None)
            if callable(sender):
                sender(title, content)
                log("   📨 [通知] 已通过青龙 notify.py 推送")
                return True
        except Exception as exc:
            log(f"   ⚠️ [通知] 加载 {candidate} 失败：{exc}")
    return False


def send_pushplus(title, content):
    if not PLUSPLUS_TOKEN:
        log("   ℹ️ [推送] 未配置 PLUSPLUS_TOKEN，跳过 PushPlus")
        return
    try:
        requests.post("https://www.pushplus.plus/send", json={
            "token": PLUSPLUS_TOKEN, "title": title, "content": content, "template": "txt",
        }, timeout=10, proxies={"http": None, "https": None})
        log("   📨 [推送] PushPlus 推送成功")
    except Exception as exc:
        log(f"   ⚠️ [推送] PushPlus 推送失败：{exc}")


# ===================== 主入口 =====================
def main():
    servers = [line.strip() for line in os.getenv("YYB_SERVER", "").splitlines() if line.strip()]

    box_top(f"🥤 {APP_NAME} 动态 code 签到")
    if not servers:
        box_line("⚠️ 状态", "未配置 YYB_SERVER")
        box_bottom()
        log("格式：YYB Go 地址@微信账号标识，多账号每行一条，可带 #备注")
        return []
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(servers)} 个")
    box_line("💾 缓存", "token_caches/nxdc_token_cache.json")
    box_line("🌐 代理", "品赞代理" if PROXY_API else "直连")
    box_bottom()

    results = []
    for idx, entry in enumerate(servers, 1):
        try:
            results.append(run_account(idx, len(servers), entry))
        except Exception as exc:
            server, ref, note = parse_entry(entry)
            log(f"   ❌ [异常] 该账号执行异常：{exc}")
            results.append({
                "index": idx,
                "source": f"{server}@{ref}" if ref else entry,
                "name": note or ref or f"账号{idx}",
                "success": False,
                "loginSource": "",
                "user": "-",
                "signMsg": "-",
                "coin": "未知",
                "coinBefore": None,
                "coinAfter": None,
                "delta": 0,
                "error": f"执行异常：{exc}",
                "proxyStatus": "使用直连",
                "proxyIp": "-",
            })
        hr()
        if idx < len(servers):
            log("   ⏳ 等待2秒后执行下一个账号...")
            sleep(2)

    print()
    for r in results:
        icon = "✅" if r["success"] else "❌"
        title = f"【账号 {r['index']} · {r['source']}】"
        if r["name"] and r["name"] != r["source"]:
            title = f"【账号 {r['index']} · {r['source']}（{r['name']}）】"
        log(f"{icon} {title}")
        if r["loginSource"]:
            log(f"   🔐 [登录] {r['loginSource']}")
            log(f"   👤 [用户] {r['user']}")
            log(f"   📅 [签到] {r['signMsg'] or '-'}")
            log(f"   💰 [积分] {fmt_coin(r['coinBefore'])} → {fmt_coin(r['coinAfter'])}（{int(r['delta']):+d}）")
        if not r["success"]:
            log(f"   ⚠️ [失败] {r['error'] or '未知原因'}")

    ok_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - ok_count
    total_delta = sum(int(r["delta"] or 0) for r in results if r["success"])

    box_top(f"🏁 {APP_NAME} 执行汇总")
    box_line("📊 执行结果", f"成功 {ok_count} / 失败 {fail_count} / 共 {len(results)}")
    box_line("💰 奈雪币变化", f"{total_delta:+d}")
    box_bottom()

    content = build_notify(results)
    send_qinglong_notify(f"{APP_NAME}每日签到", content)
    send_pushplus(f"{APP_NAME}每日签到", content)
    return results


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"❌ 程序异常: {exc}")
