#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 加多宝Club
# cron: 1 10,22 * * *

"""
加多宝Club小程序（YYB Go 版）

功能：
  1. 双 code 登录换 token / apitoken，缓存复用 + 失效自动重登
  2. 会员状态检查，未注册时手机号验证并自动注册
  3. 每日签到 + 签到奖励
  4. 每日任务：分享小程序、浏览商城
  5. 宝藏星期五抽奖
  6. 积分 / 阅历查询
  7. 青龙 notify + PushPlus 通知

环境变量：
  YYB_SERVER        必填：地址@微信标识[#备注]，多账号换行
  PROXY_API         品赞代理提取 API，可选
  PROXY_TYPE        http / socks5，默认 http
  JDB_NOTIFY=0      关闭通知
  JDB_LOTTERY=0     关闭抽奖
  PUSHPLUS_TOKEN    PushPlus token（兼容 PLUSPLUS_TOKEN / PUSH_PLUS_TOKEN）

依赖：requests
"""

import json
import os
import random
import re
import time
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

APP_NAME = "加多宝Club小程序"
APPID = "wx8371875e443e177f"
CLIENT_CODE = "CLI2113448692"

BOX_WIDTH = 48
BOX_INNER = 46

BASE_URL = "https://api-mp.jdbchina.com"

LOGIN_URL = f"{BASE_URL}/geement.authjextra/api/v1/loginsession/2weichatmicroprogram"
NANOPROGRAM_AUTH_URL = f"{BASE_URL}/geement.authjextra/api/v1/common/nanoprogramauth"
GET_PHONE_URL = f"{BASE_URL}/geement.authjextra/api/v1/loginsession/2weichatmicroprogram/getuserphonenumberwithcheckid"
REGISTER_MEMBER_URL = f"{BASE_URL}/geement.usercenter/api/v1/user/informationvbyfiled"
USER_INFO_URL = f"{BASE_URL}/geement.usercenter/api/v1/user/information"

SIGNIN_LIST_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin?status=30&pageNum=1&pageSize=1"
SIGNIN_USERINFO_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin/userinfo"
SIGNIN_DO_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin/signbyuser"
SIGNIN_USERLOGS_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin/userlogs"

TASK_JOIN_URL = f"{BASE_URL}/geement.marketingplay/api/v1/task/join"

ACT_CHECK_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/check"
ACT_LOTTERY_COUNT_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/lottery/data/todaycount"
ACT_DATA_REPORT_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/data/pu"
ACT_LOTTERY_URL = f"{BASE_URL}/geement.marketinglottery/api/v1/marketinglottery"

SENIORITY_URL = f"{BASE_URL}/geement.usercenter/api/v1/user/seniority"
POINT_URL = f"{BASE_URL}/thirty.jdb/api/member/point/expire"

SHARE_TASK_ID = "2508121123571"
BROWSE_TASK_ID = "2508121124311"
ACT_CODE = "ACT2508121127551"
SCENE_CODE = "SCENE-2508121128271"
SEN_CODE = "SEN2508111752581"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "jdbclub_token_cache.json")

NOTIFY_ENABLED = os.getenv("JDB_NOTIFY", "1").strip() != "0"
LOTTERY_ENABLED = os.getenv("JDB_LOTTERY", "1").strip() != "0"
PROXY_API = os.getenv("PROXY_API", "").strip()
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/20089",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50(0x1800322e) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/19899",
]

AUTH_PATTERN = re.compile(
    r"未登录|请登录|登录失效|登录态|token|授权|凭证|身份|请重新|查询用户信息失败|^501$", re.I
)
SIGNED_PATTERN = re.compile(r"已完成签到|已经签到|已签到|已签|重复", re.I)


# ====================== 日志版式 ======================
def display_width(text: str) -> int:
    width = 0
    for ch in str(text):
        code = ord(ch)
        if code in (0xFE0F, 0xFE0E, 0x200D) or unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def pad(text: Any, width: int) -> str:
    value = str(text)
    while display_width(value) > width:
        value = value[:-1]
    return value + " " * max(0, width - display_width(value))


def log(msg: str = "") -> None:
    print(msg)


def box_top(title: str) -> None:
    log()
    log("╔" + "═" * BOX_WIDTH + "╗")
    log("║  " + pad(title, BOX_INNER) + "║")


def box_line(label: str, value: Any) -> None:
    log("║  " + pad(f"{label}: {value}", BOX_INNER) + "║")


def box_bottom() -> None:
    log("╚" + "═" * BOX_WIDTH + "╝")


def account_frame(index: int, total: int, title: str, source: str) -> None:
    log()
    log("┌" + "─" * BOX_WIDTH + "┐")
    log("│  " + pad(f"🧩 账号 {index} / {total}　{title}", BOX_INNER) + "│")
    log("│  " + pad(f"🔗 来源: {source}", BOX_INNER) + "│")
    log("└" + "─" * BOX_WIDTH + "┘")


def hr() -> None:
    log()
    log("-" * BOX_WIDTH)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def short(value: Any, limit: int = 300) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)
    return text[:limit] + "…" if len(text) > limit else text


def mask(value: Any) -> str:
    text = str(value or "")
    return text if len(text) <= 12 else f"{text[:6]}***{text[-6:]}"


def mask_phone(phone: Any) -> str:
    text = str(phone or "")
    return f"{text[:3]}****{text[-4:]}" if len(text) >= 11 else text


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "是", "成功")


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# ====================== 账号解析 ======================
def parse_entry(raw_value: str) -> Tuple[str, str, str]:
    value = str(raw_value or "").strip()
    note = ""
    if not value:
        return "", "", ""
    hash_index = value.find("#")
    if hash_index != -1:
        note = value[hash_index + 1:].strip()
        value = value[:hash_index].strip()
    if "@" not in value:
        return "", "", note
    server, ref = value.split("@", 1)
    server = server.strip()
    ref = ref.strip()
    if "#" in ref:
        ref = ref.split("#")[0].strip()
    if server.startswith("http://"):
        server = server[7:]
    elif server.startswith("https://"):
        server = server[8:]
    server = server.rstrip("/")
    if not server or not ref:
        return "", "", note
    return server, ref, note


# ====================== 缓存 ======================
def read_raw_cache() -> Dict[str, Any]:
    try:
        if not os.path.exists(TOKEN_CACHE_FILE):
            return {}
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log(f"   ⚠️ [缓存] 读取失败：{short(e, 60)}")
        return {}
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        converted = {}
        for item in data:
            if not isinstance(item, dict) or not item.get("token"):
                continue
            ref = str(item.get("ref") or item.get("wxid") or "").strip()
            server = str(item.get("server") or "").strip()
            if not ref:
                continue
            converted[f"{server}|{ref}" if server else f"legacy|{ref}"] = item
        return converted
    return {}


def write_raw_cache(cache: Dict[str, Any]) -> bool:
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log(f"   ⚠️ [缓存] 写入失败：{short(e, 60)}")
        return False


def cache_key_matches(key: Any, server: str, ref: str) -> bool:
    k = str(key or "").strip()
    if not k:
        return False
    if k == ref:
        return True
    if "|" in k:
        left, right = k.rsplit("|", 1)
        return right.strip() == ref and left.strip() in (server, "legacy")
    if "@" in k:
        left, right = k.split("@", 1)
        left = left.replace("http://", "").replace("https://", "").rstrip("/")
        right = right.split("#")[0].strip()
        return right == ref and left == server
    return False


def load_cache_entry(server: str, ref: str) -> Optional[Dict[str, Any]]:
    cache = read_raw_cache()
    exact = f"{server}|{ref}"
    candidates = []
    for key, value in cache.items():
        if not cache_key_matches(key, server, ref):
            continue
        if not isinstance(value, dict) or not value.get("token"):
            continue
        candidates.append((str(value.get("updatedAt") or ""), key, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best = candidates[0]
    if best[1] != exact:
        cache[exact] = dict(best[2])
        for _, key, _ in candidates:
            if key != exact:
                cache.pop(key, None)
        write_raw_cache(cache)
        log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」")
        return dict(best[2])
    return dict(best[2])


def save_cache_entry(server: str, ref: str, entry: Dict[str, Any]) -> None:
    cache = read_raw_cache()
    exact = f"{server}|{ref}"
    for key in list(cache.keys()):
        if cache_key_matches(key, server, ref) and key != exact:
            cache.pop(key, None)
    cache[exact] = dict(entry)
    cache[exact]["updatedAt"] = now_text()
    write_raw_cache(cache)


def drop_cache_entry(server: str, ref: str) -> None:
    cache = read_raw_cache()
    for key in list(cache.keys()):
        if cache_key_matches(key, server, ref):
            cache.pop(key, None)
    write_raw_cache(cache)


# ====================== 代理 ======================
_persistent_session: Optional[requests.Session] = None


def direct_session() -> requests.Session:
    global _persistent_session
    if _persistent_session is None:
        _persistent_session = requests.Session()
        _persistent_session.trust_env = False
    return _persistent_session


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
    auth = f"{quote(username)}:{quote(password)}@" if username and password else ""
    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"
    return {"http": proxy_url, "https": proxy_url}


def get_valid_proxy(account_name: str) -> Tuple[Optional[Dict[str, str]], str]:
    if not PROXY_API:
        return None, ""
    log(f"   🌐 [代理] {account_name} 正在获取品赞代理...")
    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=15)
            proxy_info = parse_proxy_response(response.text)
            if not proxy_info:
                log(f"   ⚠️ [代理] 第 {index} 次解析失败")
                continue
            proxies = build_proxy_dict(proxy_info)
            try:
                check = requests.get("http://www.baidu.com", proxies=proxies, timeout=10)
                if check.status_code == 200:
                    log(f"   ✅ [代理] 使用 {proxy_info['host']}:{proxy_info['port']}")
                    return proxies, proxy_info["host"]
            except Exception:
                pass
            log(f"   ⚠️ [代理] 第 {index} 次不可用")
        except Exception as exc:
            log(f"   ⚠️ [代理] 第 {index} 次异常：{short(exc, 80)}")
        if index < PROXY_RETRY_TIMES:
            time.sleep(2)
    log("   ℹ️ [代理] 获取失败，改用直连")
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
            log(f"   ⚠️ [代理] {server} 请求失败：{short(exc, 80)}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            log("   🔁 [兜底] 切换直连重试")
    return direct_session().request(method, url, **kwargs)


# ====================== 请求与判定 ======================
def common_headers(token: Optional[str] = None, apitoken: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": random.choice(UA_POOL),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": f"https://servicewechat.com/{APPID}/45/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["unique_identity"] = token
        headers["apitoken"] = apitoken or token
    return headers


def _auth_error(status: int, msg: str) -> bool:
    if status in (401, 403):
        return True
    return bool(AUTH_PATTERN.search(str(msg or "")))


def _parse_response(response: requests.Response) -> Dict[str, Any]:
    status = response.status_code
    try:
        body = response.json()
    except Exception:
        msg = f"JSON解析失败: {short(response.text, 200)}"
        return {"ok": False, "status": status, "msg": msg, "data": None, "auth": status in (401, 403)}
    if not isinstance(body, dict):
        return {"ok": False, "status": status, "msg": f"响应不是对象: {short(body, 100)}", "data": None, "auth": False}
    success = truthy(body.get("success"))
    msg = str(body.get("msg") or body.get("message") or "")
    auth = _auth_error(status, msg)
    return {"ok": status == 200 and success, "status": status, "msg": msg, "data": body.get("data"), "auth": auth}


def api_request(
    method: str,
    url: str,
    token: str,
    apitoken: str,
    proxies: Optional[Dict[str, str]],
    server: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    form: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = common_headers(token, apitoken)
    kwargs: Dict[str, Any] = {"params": params or {}}
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        kwargs["data"] = form
    elif json_body is not None:
        headers["Content-Type"] = "application/json"
        kwargs["json"] = json_body
    response = request_with_proxy(
        method, url, headers=headers, proxies=proxies, server=server, **kwargs
    )
    return _parse_response(response)


def api_get(token, apitoken, url, proxies, server, params=None) -> Dict[str, Any]:
    return api_request("GET", url, token, apitoken, proxies, server, params=params)


def api_post_form(token, apitoken, url, proxies, server, form=None) -> Dict[str, Any]:
    return api_request("POST", url, token, apitoken, proxies, server, form=form or {})


def api_post_json(token, apitoken, url, proxies, server, payload=None) -> Dict[str, Any]:
    return api_request("POST", url, token, apitoken, proxies, server, json_body=payload or {})


def is_auth_error(result: Dict[str, Any]) -> bool:
    return bool(result.get("auth"))


class AuthExpired(Exception):
    pass


def raise_if_auth(result: Dict[str, Any]) -> None:
    if is_auth_error(result):
        raise AuthExpired(result.get("msg") or "登录状态失效")


# ====================== YYB / 登录 ======================
def get_wx_code(server: str, ref: str) -> Optional[str]:
    url = f"http://{server}/wxapp/getCode"
    for attempt in range(2):
        try:
            response = requests.post(
                url,
                json={"ref": ref, "app_id": APPID},
                timeout=20,
                proxies={"http": None, "https": None},
            )
            data = response.json()
            code = (((data.get("data") or {}).get("result") or {}).get("code"))
            if data.get("code") == 0 and code:
                log("   ✅ [授权] 登录 code 获取成功")
                return str(code)
            log(f"   ⚠️ [授权] 登录 code 获取失败（第 {attempt + 1} 次）：{short(data, 100)}")
        except Exception as exc:
            log(f"   ⚠️ [授权] 登录 code 异常（第 {attempt + 1} 次）：{short(exc, 80)}")
        if attempt == 0:
            time.sleep(1)
    return None


def get_phone_code(server: str, ref: str) -> Optional[str]:
    url = f"http://{server}/wxapp/getPhoneNumber"
    for attempt in range(2):
        try:
            response = requests.post(
                url,
                json={"ref": ref, "app_id": APPID},
                timeout=20,
                proxies={"http": None, "https": None},
            )
            data = response.json()
            result = ((data.get("data") or {}).get("result") or {})
            code = result.get("code") or (data.get("data") or {}).get("code")
            if data.get("code") == 0 and code:
                log("   ✅ [授权] 手机号 code 获取成功")
                return str(code)
            log(f"   ⚠️ [授权] 手机号 code 获取失败（第 {attempt + 1} 次）：{short(data, 100)}")
        except Exception as exc:
            log(f"   ⚠️ [授权] 手机号 code 异常（第 {attempt + 1} 次）：{short(exc, 80)}")
        if attempt == 0:
            time.sleep(1)
    return None


def login_bundle(server: str, ref: str, proxies) -> Tuple[Optional[str], Optional[str], Dict[str, Any], str]:
    """取两个 jscode：登录换 token，授权换 apitoken"""
    login_code = get_wx_code(server, ref)
    if not login_code:
        return None, None, {}, "获取登录 code 失败"

    try:
        response = request_with_proxy(
            "POST",
            LOGIN_URL,
            headers=common_headers(),
            data={"jscode": login_code, "app_id": APPID, "client_code": CLIENT_CODE},
            proxies=proxies,
            server=server,
        )
        data = response.json()
    except Exception as exc:
        return None, None, {}, f"登录异常: {short(exc, 100)}"

    token = ((data.get("data") or {}).get("token")) if isinstance(data, dict) else None
    if not token:
        return None, None, data if isinstance(data, dict) else {}, f"登录未返回 token: {short(data, 120)}"
    token = str(token)
    log(f"   ✅ [登录] token 获取成功 {mask(token)}")

    apitoken = token
    auth_code = get_wx_code(server, ref)
    if auth_code:
        auth_resp = request_with_proxy(
            "GET",
            NANOPROGRAM_AUTH_URL,
            headers=common_headers(),
            params={"app_id": APPID, "client_code": CLIENT_CODE, "jscode": auth_code},
            proxies=proxies,
            server=server,
        )
        try:
            auth_data = auth_resp.json()
        except Exception:
            auth_data = {}
        raw = auth_data.get("data") if isinstance(auth_data, dict) else None
        if isinstance(raw, dict):
            raw = raw.get("apitoken") or raw.get("token")
        if raw:
            apitoken = str(raw)
            log(f"   ✅ [登录] apitoken 获取成功 {mask(apitoken)}")
        else:
            log("   ⚠️ [登录] apitoken 获取失败，使用 token 代替")
    else:
        log("   ⚠️ [登录] 授权 code 获取失败，使用 token 代替 apitoken")

    return token, apitoken, data if isinstance(data, dict) else {}, ""


# ====================== 会员 ======================
def extract_user_info(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    info = dict(data)
    member_info = info.get("extra_memberinfo")
    if isinstance(member_info, dict):
        memberdto = member_info.get("memberdto")
        if isinstance(memberdto, dict):
            info.setdefault("member_id", memberdto.get("m_id") or memberdto.get("member_id"))
            if not info.get("userId"):
                info["userId"] = info.get("id") or info.get("member_id")
    if not info.get("phone") and info.get("mobile"):
        info["phone"] = info.get("mobile")
    if not info.get("nickname"):
        info["nickname"] = info.get("nickName") or info.get("nick_name") or ""
    return info


def ensure_member(server: str, ref: str, token: str, apitoken: str, proxies) -> Tuple[bool, str, Dict[str, Any]]:
    info_resp = api_get(token, apitoken, USER_INFO_URL, proxies, server)
    raise_if_auth(info_resp)
    if not info_resp.get("ok"):
        return False, f"查询用户信息失败: {short(info_resp.get('msg'), 80)}", {}

    user_data = extract_user_info(info_resp.get("data"))
    member_info = user_data.get("extra_memberinfo") if isinstance(user_data.get("extra_memberinfo"), dict) else {}
    member_status = member_info.get("member_status", 0)
    phone = str(user_data.get("phone") or user_data.get("mobile") or "")

    if truthy(member_status):
        memberdto = member_info.get("memberdto") if isinstance(member_info.get("memberdto"), dict) else {}
        member_id = memberdto.get("m_id") or memberdto.get("member_id") or user_data.get("member_id") or ""
        log(f"   👤 [会员] 已是会员{f'（ID {member_id}）' if member_id else ''}")
        return True, f"已是会员{f'（ID {member_id}）' if member_id else ''}", user_data

    log("   ℹ️ [会员] 尚未注册，尝试手机号验证 + 注册")
    phone_code = get_phone_code(server, ref)
    if not phone_code:
        return False, "未注册会员（手机号 code 获取失败）", user_data

    phone_resp = api_post_form(
        token, apitoken, GET_PHONE_URL, proxies, server,
        {"code": phone_code, "app_id": APPID, "client_code": CLIENT_CODE},
    )
    raise_if_auth(phone_resp)
    if not phone_resp.get("ok"):
        return False, f"手机号验证失败: {short(phone_resp.get('msg'), 80)}", user_data

    phone_data = phone_resp.get("data") if isinstance(phone_resp.get("data"), dict) else {}
    check_id = phone_data.get("check_id")
    phone_number = str(phone_data.get("phone_number") or phone)
    if not check_id:
        return False, "手机号验证未返回 check_id", user_data

    log(f"   ✅ [会员] 手机号验证通过：{mask_phone(phone_number)}")
    reg_payload = {
        "custom_fields": [{"id": "phone", "field_valuestr": phone_number}] if phone_number else [],
        "register_member": True,
        "register_member_phonenumbercheckdto": {"system_checkid": check_id},
        "member_sourceinfo": {
            "source_key01": "jdbmember001",
            "source_key02": "加多宝小程序虚拟门店",
            "source_key03": "",
            "source_key04": "",
        },
    }
    reg_resp = api_post_json(token, apitoken, REGISTER_MEMBER_URL, proxies, server, reg_payload)
    raise_if_auth(reg_resp)
    if reg_resp.get("ok"):
        reg_data = reg_resp.get("data") if isinstance(reg_resp.get("data"), dict) else {}
        result = reg_data.get("register_member_result") if isinstance(reg_data.get("register_member_result"), dict) else {}
        new_id = result.get("member_id") or result.get("m_id") or ""
        log(f"   ✅ [会员] 注册成功{f'（ID {new_id}）' if new_id else ''}")
        user_data["member_status"] = 1
        return True, f"注册成功{f'（ID {new_id}）' if new_id else ''}", user_data

    msg = reg_resp.get("msg") or "注册失败"
    return False, f"注册失败: {short(msg, 80)}", user_data


# ====================== 签到 ======================
def is_today(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    if text[:10] == today:
        return True
    normalized = text[:10].replace("/", "-").replace(".", "-")
    if normalized == today:
        return True
    if text.isdigit() and len(text) >= 10:
        try:
            ts = int(text[:10])
            if ts < 10000000000:
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d") == today
        except Exception:
            return False
    return False


def do_signin(server: str, token: str, apitoken: str, proxies) -> Dict[str, Any]:
    signin_list = api_get(token, apitoken, SIGNIN_LIST_URL, proxies, server)
    raise_if_auth(signin_list)
    if not signin_list.get("ok"):
        return {"status": "error", "message": f"获取签到活动失败: {short(signin_list.get('msg'), 80)}"}

    data = signin_list.get("data")
    if isinstance(data, dict):
        data = data.get("list") or data.get("rows") or []
    if not isinstance(data, list) or not data:
        return {"status": "none", "message": "暂无进行中的签到活动"}

    activity = data[0].get("activitydto") if isinstance(data[0], dict) else {}
    activity_id = (activity or {}).get("id")
    if not activity_id:
        return {"status": "error", "message": "签到活动未返回活动 ID"}
    activity_name = (activity or {}).get("activity_name") or "每日签到"
    log(f"   📅 [签到] 活动：{activity_name}（ID {activity_id}）")

    userinfo = api_get(
        token, apitoken, SIGNIN_USERINFO_URL, proxies, server, params={"task_id": activity_id}
    )
    raise_if_auth(userinfo)

    total_days = 0
    continuity = 0
    already = False
    if userinfo.get("ok") and isinstance(userinfo.get("data"), dict):
        ud = userinfo["data"]
        total_days = int_value(ud.get("total_signindays"), 0)
        continuity = int_value(ud.get("continuity_signindays"), 0)
        already = is_today(ud.get("latest_signin_time"))
        log(f"   📅 [签到] 累计 {total_days} 天，连续 {continuity} 天")

    if already:
        _show_signin_rewards(server, token, apitoken, proxies, activity_id)
        return {"status": "already", "message": f"今日已签到（累计{total_days}天）", "total": total_days}

    resp = api_post_form(
        token, apitoken, SIGNIN_DO_URL, proxies, server, {"task_id": activity_id}
    )
    raise_if_auth(resp)
    if resp.get("ok"):
        time.sleep(1)
        _show_signin_rewards(server, token, apitoken, proxies, activity_id)
        userinfo2 = api_get(
            token, apitoken, SIGNIN_USERINFO_URL, proxies, server, params={"task_id": activity_id}
        )
        if userinfo2.get("ok") and isinstance(userinfo2.get("data"), dict):
            total_days = int_value(userinfo2["data"].get("total_signindays"), total_days + 1)
            continuity = int_value(userinfo2["data"].get("continuity_signindays"), continuity)
        return {"status": "success", "message": f"签到成功（累计{total_days}天）", "total": total_days}

    msg = resp.get("msg") or "签到失败"
    if SIGNED_PATTERN.search(str(msg)):
        _show_signin_rewards(server, token, apitoken, proxies, activity_id)
        return {"status": "already", "message": f"今日已签到（{short(msg, 40)}）", "total": total_days}
    return {"status": "error", "message": f"签到失败: {short(msg, 80)}"}


def _show_signin_rewards(server, token, apitoken, proxies, activity_id) -> None:
    logs_resp = api_get(
        token, apitoken, SIGNIN_USERLOGS_URL, proxies, server,
        params={"task_id": activity_id, "pageNum": 1, "pageSize": 7},
    )
    if not logs_resp.get("ok"):
        return
    logs = logs_resp.get("data")
    if isinstance(logs, dict):
        logs = logs.get("list") or logs.get("rows") or []
    if not isinstance(logs, list):
        return
    for entry in logs:
        if not isinstance(entry, dict) or not is_today(entry.get("signin_date")):
            continue
        content = entry.get("reward_content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except Exception:
                continue
        if not isinstance(content, list):
            continue
        for reward in content:
            details = reward.get("rule_reward_details") if isinstance(reward, dict) else None
            if not isinstance(details, list):
                continue
            for detail in details:
                if isinstance(detail, dict):
                    log(f"   🎁 [签到] 奖励：{detail.get('relationship_name', '未知')} × {detail.get('reward_count', 0)}")


# ====================== 每日任务 ======================
def do_task(server, token, apitoken, proxies, task_id: str, task_name: str) -> Dict[str, Any]:
    resp = api_get(
        token, apitoken, TASK_JOIN_URL, proxies, server, params={"task_id": task_id}
    )
    raise_if_auth(resp)
    msg = resp.get("msg") or ""
    data_text = str(resp.get("data") or "")
    if resp.get("ok"):
        if "已参" in msg or "已参" in data_text or "已完成" in data_text:
            log(f"   ✅ [任务] {task_name} 今日已完成")
            return {"status": "already", "message": f"{task_name}: 今日已完成"}
        log(f"   ✅ [任务] {task_name} 完成")
        return {"status": "success", "message": f"{task_name}: 成功"}
    if "已参" in msg or "已完成" in msg:
        log(f"   ℹ️ [任务] {task_name} 今日已完成")
        return {"status": "already", "message": f"{task_name}: 今日已完成"}
    log(f"   ⚠️ [任务] {task_name} 失败：{short(msg or data_text, 60)}")
    return {"status": "error", "message": f"{task_name}: {short(msg or data_text, 60)}"}


# ====================== 宝藏星期五 ======================
def extract_count(value: Any) -> int:
    if isinstance(value, dict):
        for key in ("count", "today_count", "todaycount", "num"):
            if value.get(key) is not None:
                return int_value(value.get(key), 0)
        return 0
    return int_value(value, 0)


def do_lottery(server: str, token: str, apitoken: str, proxies) -> Dict[str, Any]:
    if not LOTTERY_ENABLED:
        return {"status": "disabled", "message": "抽奖已关闭"}

    # 先做活动页数据上报，再检查活动状态（部分账号不报会没有抽奖次数）
    report_resp = api_post_form(token, apitoken, ACT_DATA_REPORT_URL, proxies, server, {"a": "1"})
    raise_if_auth(report_resp)

    check_resp = api_get(
        token, apitoken, ACT_CHECK_URL, proxies, server, params={"act_code": ACT_CODE}
    )
    raise_if_auth(check_resp)
    if not check_resp.get("ok"):
        return {"status": "error", "message": f"活动检查失败: {short(check_resp.get('msg'), 60)}"}

    check_data = check_resp.get("data") if isinstance(check_resp.get("data"), dict) else {}
    act_status = check_data.get("act_status", check_data.get("act_status_full", 0))
    if str(act_status) not in ("1", "2"):
        return {"status": "inactive", "message": f"活动未在进行中（状态 {act_status}）"}

    count_resp = api_get(
        token, apitoken, ACT_LOTTERY_COUNT_URL, proxies, server, params={"act_code": ACT_CODE}
    )
    raise_if_auth(count_resp)
    today_count = extract_count(count_resp.get("data")) if count_resp.get("ok") else 0
    max_per_day = int_value(
        check_data.get("user_max_scan_count_perday", check_data.get("max_count", 1)), 1
    )
    remaining = min(max(0, max_per_day - today_count), 10)
    log(f"   🎰 [抽奖] 今日 {today_count}/{max_per_day} 次，可抽 {remaining} 次")
    if remaining <= 0:
        return {"status": "already", "message": f"今日抽奖次数已用完（{today_count}/{max_per_day}）"}

    prizes: List[str] = []
    for draw_index in range(1, remaining + 1):
        wait_time = random.randint(2, 4)
        log(f"   ⏳ [抽奖] 第 {draw_index}/{remaining} 次，等待 {wait_time}s")
        time.sleep(wait_time)
        resp = api_post_json(
            token, apitoken, ACT_LOTTERY_URL, proxies, server,
            {"code": SCENE_CODE, "scene_code": SCENE_CODE},
        )
        raise_if_auth(resp)
        if resp.get("ok"):
            data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
            prizedto = data.get("prizedto") if isinstance(data.get("prizedto"), dict) else {}
            prize_name = prizedto.get("prize_name") or data.get("prize_name") or data.get("prizeName")
            prize_level = prizedto.get("prize_level") or data.get("prize_level") or ""
            if prize_name:
                prize_text = f"{prize_level} {prize_name}".strip()
                prizes.append(prize_text)
                log(f"   🎉 [抽奖] 第 {draw_index} 次获得：{prize_text}")
            else:
                prizes.append(f"第{draw_index}次参与成功")
                log(f"   🎉 [抽奖] 第 {draw_index} 次参与成功")
        else:
            msg = resp.get("msg") or "抽奖失败"
            if "次数已经达到最大" in msg or "次数已用完" in msg:
                prizes.append("次数已用完")
                break
            # 活动状态是进行中，但抽奖窗口还没开（宝藏星期五通常只有周五开放）
            if any(
                key in msg
                for key in (
                    "还未达到活动抽奖时间",
                    "未达到活动抽奖时间",
                    "未到活动抽奖时间",
                    "不在活动时间",
                    "非活动时间",
                    "活动未开始",
                    "活动已结束",
                )
            ):
                if not prizes:
                    log("   ℹ️ [抽奖] 未到抽奖开放时间，今日跳过")
                    return {"status": "inactive", "message": "未到抽奖开放时间，已跳过"}
                prizes.append("未到抽奖开放时间")
                break
            prizes.append(f"第{draw_index}次失败: {short(msg, 40)}")
            log(f"   ⚠️ [抽奖] 第 {draw_index} 次失败：{short(msg, 60)}")

    if not prizes:
        return {"status": "error", "message": "未获得抽奖结果"}
    status = "success" if not any("失败" in p for p in prizes) else "partial"
    return {"status": status, "message": "、".join(prizes)}


# ====================== 积分 / 阅历 ======================
POINT_FIELD_NAMES = (
    "point", "points", "integral", "score", "bonus",
    "totalPoint", "total_point", "totalPoints", "total_points",
    "pointBalance", "point_balance", "availablePoint", "available_point",
    "availableIntegral", "available_integral", "currentPoint", "current_point",
    "memberPoint", "member_point", "usablePoint", "usable_point",
    "totalIntegral", "total_integral",
)
POINT_CONTAINER_NAMES = (
    "memberdto", "extra_memberinfo", "memberInfo", "member_info",
    "userInfo", "user_info", "member", "user",
)


def _point_int(value: Any):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def extract_point_value(data: Any, depth: int = 0):
    """从积分接口/用户信息里提取当前积分，兼容常见的几种字段名。"""
    if depth > 3:
        return None
    if isinstance(data, dict):
        for key in POINT_FIELD_NAMES:
            if key in data:
                value = _point_int(data.get(key))
                if value is not None:
                    return value
        for key in POINT_CONTAINER_NAMES:
            child = data.get(key)
            if isinstance(child, (dict, list)):
                value = extract_point_value(child, depth + 1)
                if value is not None:
                    return value
        return None
    if isinstance(data, list):
        for item in data:
            value = extract_point_value(item, depth + 1)
            if value is not None:
                return value
    return None


def query_point(server, token, apitoken, proxies) -> Dict[str, Any]:
    resp = api_get(token, apitoken, POINT_URL, proxies, server)
    raise_if_auth(resp)
    value = extract_point_value(resp.get("data")) if resp.get("ok") else None
    # point/expire 接口有时只返回“即将过期积分”，0 不代表总积分；用用户信息兜底
    if value in (None, 0):
        info_resp = api_get(token, apitoken, USER_INFO_URL, proxies, server)
        raise_if_auth(info_resp)
        if info_resp.get("ok"):
            info_value = extract_point_value(info_resp.get("data"))
            if info_value is not None and info_value != 0:
                value = info_value
    if value is None:
        return {"value": None, "message": short(resp.get("msg"), 60)}
    return {"value": value, "message": ""}


def query_seniority(server, token, apitoken, proxies) -> str:
    resp = api_get(
        token, apitoken, SENIORITY_URL, proxies, server, params={"sencodes": SEN_CODE}
    )
    raise_if_auth(resp)
    if not resp.get("ok"):
        return f"查询失败({short(resp.get('msg'), 40)})"
    data = resp.get("data")
    if isinstance(data, dict):
        data = data.get("list") or data.get("rows") or [data]
    if not isinstance(data, list) or not data:
        return "暂无阅历数据"
    item = data[0] if isinstance(data[0], dict) else {}
    total = int_value(item.get("total_count"), 0)
    used = int_value(item.get("used_count"), 0)
    return f"总计{total}/已用{used}"


# ====================== 账号执行 ======================
def run_account(index: int, total: int, raw_entry: str) -> Dict[str, Any]:
    server, ref, note = parse_entry(raw_entry)
    title = f"标识 {ref}" + (f"（{note}）" if note else "")
    result = {
        "index": index,
        "title": title,
        "success": False,
        "loginSource": "",
        "nickname": "",
        "userId": "-",
        "memberMsg": "-",
        "signMsg": "-",
        "signStatus": "",
        "taskShareMsg": "-",
        "taskBrowseMsg": "-",
        "lotteryMsg": "-",
        "pointBefore": "-",
        "pointAfter": "-",
        "seniority": "-",
        "proxyStatus": "直连",
        "proxyIp": "-",
        "error": "",
    }
    account_frame(index, total, title, f"{server}@{ref}" + (f"#{note}" if note else ""))

    proxies, proxy_ip = get_valid_proxy(server)
    if proxies:
        result["proxyStatus"] = "专属代理"
        result["proxyIp"] = proxy_ip or "-"

    delay = random.randint(2, 6)
    log(f"   ⏳ [延迟] 启动延迟 {delay}s")
    time.sleep(delay)

    cached = load_cache_entry(server, ref)
    token = ""
    apitoken = ""
    user_info: Dict[str, Any] = {}
    if cached:
        token = str(cached.get("token") or "")
        apitoken = str(cached.get("apitoken") or token)
        user_info = cached.get("userInfo") if isinstance(cached.get("userInfo"), dict) else {}
        result["loginSource"] = "缓存复用"
        log(f"   💾 [缓存] 复用已保存 token {mask(token)}")
    else:
        result["loginSource"] = "新登录"

    def login() -> bool:
        nonlocal token, apitoken, user_info
        token, apitoken, raw_login, error = login_bundle(server, ref, proxies)
        if not token:
            result["error"] = f"登录失败：{error}"
            log(f"   ❌ [登录] {result['error']}")
            return False
        user_info = (raw_login.get("data") or {}).get("userInfo") if isinstance(raw_login, dict) else {}
        if not isinstance(user_info, dict):
            user_info = {}
        return True

    if not token and not login():
        return result

    def reset_business() -> None:
        for key in ("memberMsg", "signMsg", "taskShareMsg", "taskBrowseMsg", "lotteryMsg",
                    "pointBefore", "pointAfter", "seniority"):
            result[key] = "-"

    for attempt in range(2):
        if attempt == 1:
            drop_cache_entry(server, ref)
            log("   🔄 [重登] token 失效，清缓存重新登录")
            if not login():
                return result
            result["loginSource"] = "失效重登"
            reset_business()

        try:
            member_ok, member_msg, user_info = ensure_member(server, ref, token, apitoken, proxies)
            result["memberMsg"] = member_msg
            if not member_ok:
                log(f"   ⚠️ [会员] {short(member_msg, 80)}")
            result["nickname"] = str(
                user_info.get("nickname") or user_info.get("nick_name") or user_info.get("display_name") or ""
            )
            result["userId"] = str(user_info.get("userId") or user_info.get("user_id") or user_info.get("member_id") or "-")
            who = result["nickname"] or mask_phone(user_info.get("phone") or user_info.get("mobile")) or "微信用户"
            log(f"   👤 [用户] {who}，userId={result['userId']}")

            point_before = query_point(server, token, apitoken, proxies)
            result["pointBefore"] = point_before["value"] if point_before["value"] is not None else "-"
            log(f"   💰 [积分] 当前 {result['pointBefore']}")

            sign = do_signin(server, token, apitoken, proxies)
            result["signStatus"] = sign["status"]
            result["signMsg"] = sign["message"]
            if sign["status"] == "success":
                log(f"   ✅ [签到] {sign['message']}")
            elif sign["status"] == "already":
                log(f"   ℹ️ [签到] {sign['message']}")
            elif sign["status"] == "none":
                log(f"   ℹ️ [签到] {sign['message']}")
            else:
                log(f"   ❌ [签到] {sign['message']}")

            time.sleep(random.uniform(1, 3))
            share = do_task(server, token, apitoken, proxies, SHARE_TASK_ID, "分享小程序")
            result["taskShareMsg"] = share["message"]

            time.sleep(random.uniform(1, 3))
            browse = do_task(server, token, apitoken, proxies, BROWSE_TASK_ID, "浏览商城")
            result["taskBrowseMsg"] = browse["message"]

            time.sleep(random.uniform(1, 3))
            lottery = do_lottery(server, token, apitoken, proxies)
            result["lotteryMsg"] = lottery["message"]
            log(f"   🎰 [抽奖] {lottery['message']}")

            point_after = query_point(server, token, apitoken, proxies)
            result["pointAfter"] = point_after["value"] if point_after["value"] is not None else "-"
            log(f"   💰 [积分] 当前 {result['pointAfter']}")

            result["seniority"] = query_seniority(server, token, apitoken, proxies)
            log(f"   📖 [阅历] {result['seniority']}")

            result["success"] = sign["status"] in ("success", "already")
            if not result["success"]:
                result["error"] = result["signMsg"] if result["signMsg"] != "-" else "签到未成功"
            save_cache_entry(
                server, ref,
                {
                    "token": token,
                    "apitoken": apitoken,
                    "userInfo": user_info,
                    "userId": result["userId"],
                    "nickname": result["nickname"],
                    "updatedAt": now_text(),
                },
            )
            if result["success"]:
                log("   ✅ [完成] 该账号任务执行完成")
            else:
                log(f"   ⚠️ [完成] 签到未成功：{short(result['error'], 80)}")
            return result

        except AuthExpired as exc:
            log(f"   ⚠️ [鉴权] {short(exc, 60)}")
            token = ""
            apitoken = ""
            continue

    if not result["error"]:
        result["error"] = "重登后仍无法完成业务"
    return result


# ====================== 通知 / 主流程 ======================
def send_qinglong_notify(title: str, content: str) -> bool:
    try:
        import notify
        notify.send(title, content)
        return True
    except Exception as exc:
        log(f"   ℹ️ [通知] 青龙 notify 不可用：{short(exc, 60)}")
        return False


def send_pushplus(title: str, content: str) -> bool:
    token = (
        os.getenv("PUSHPLUS_TOKEN")
        or os.getenv("PLUSPLUS_TOKEN")
        or os.getenv("PUSH_PLUS_TOKEN")
        or ""
    ).strip()
    if not token:
        return False
    try:
        response = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content, "template": "txt"},
            timeout=15,
            proxies={"http": None, "https": None},
        )
        return response.json().get("code") == 200
    except Exception:
        return False


def build_notify(results: List[Dict[str, Any]]) -> str:
    ok = sum(1 for r in results if r["success"])
    lines = [f"【{APP_NAME}】每日任务", f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}", ""]
    for r in results:
        flag = "✅" if r["success"] else "❌"
        lines.append(f"{flag} 账号{r['index']} {r['title']}：{r.get('signMsg') or r.get('error') or '-'}")
        lines.append(
            f"   登录：{r.get('loginSource') or '-'}｜会员：{r.get('memberMsg') or '-'}"
            f"｜积分 {r.get('pointBefore', '-')} → {r.get('pointAfter', '-')}"
        )
        lines.append(f"   分享：{r.get('taskShareMsg') or '-'}｜浏览：{r.get('taskBrowseMsg') or '-'}")
        lines.append(f"   抽奖：{r.get('lotteryMsg') or '-'}｜阅历：{r.get('seniority') or '-'}")
        if not r["success"] and r.get("error"):
            lines.append(f"   失败：{r['error']}")
    return "\n".join(lines)


def main() -> None:
    entries = [line.strip() for line in os.getenv("YYB_SERVER", "").splitlines() if line.strip()]
    if not entries:
        log("❌ 未配置环境变量 YYB_SERVER")
        log("格式：地址@微信标识[#备注]，多账号换行分隔")
        return

    valid = []
    invalid = []
    for entry in entries:
        server, ref, _ = parse_entry(entry)
        if server and ref:
            valid.append(entry)
        else:
            invalid.append(entry)
    if not valid:
        log("❌ YYB_SERVER 没有可用账号（格式：地址@标识[#备注]）")
        return

    box_top(f"🥤 {APP_NAME} 每日任务")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(valid)} 个{f'（{len(invalid)} 行格式无效）' if invalid else ''}")
    box_line("💾 缓存", os.path.basename(TOKEN_CACHE_FILE))
    box_line("🧩 功能", "签到｜任务｜抽奖｜积分｜阅历")
    box_line("🌐 代理", f"品赞 {PROXY_TYPE.upper()}" if PROXY_API else "未配置（直连）")
    box_line("🎰 抽奖", "开启" if LOTTERY_ENABLED else "关闭")
    box_bottom()

    for line in invalid:
        log(f"   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过：{short(line, 60)}")

    results: List[Dict[str, Any]] = []
    for index, entry in enumerate(valid, start=1):
        try:
            results.append(run_account(index, len(valid), entry))
        except Exception as exc:
            log(f"   ❌ [执行] 账号 {index} 未捕获异常：{short(exc, 100)}")
            _, ref, _ = parse_entry(entry)
            results.append({
                "index": index, "title": f"标识 {ref}", "success": False, "loginSource": "",
                "nickname": "", "userId": "-", "memberMsg": "-", "signMsg": "-", "signStatus": "",
                "taskShareMsg": "-", "taskBrowseMsg": "-", "lotteryMsg": "-",
                "pointBefore": "-", "pointAfter": "-", "seniority": "-",
                "proxyStatus": "-", "proxyIp": "-", "error": short(exc, 100),
            })
        hr()
        if index < len(valid):
            log("   ⏳ 等待2秒后执行下一个账号...")
            time.sleep(2)

    log()
    for r in results:
        if r["success"]:
            log(f"✅ 【账号 {r['index']} · {r['title']}】")
            log(f"   🔐 [登录] {r['loginSource'] or '-'}")
            log(f"   👤 [会员] {r['memberMsg']}")
            log(f"   📅 [签到] {r['signMsg']}")
            log(f"   💰 [积分] {r['pointBefore']} → {r['pointAfter']}")
            log(f"   🔗 [分享] {r['taskShareMsg']}")
            log(f"   🛍️ [浏览] {r['taskBrowseMsg']}")
            log(f"   🎰 [抽奖] {r['lotteryMsg']}")
            log(f"   📖 [阅历] {r['seniority']}")
        else:
            log(f"❌ 【账号 {r['index']} · {r['title']}】")
            log(f"   🔐 [登录] {r['loginSource'] or '-'}")
            log(f"   📅 [签到] {r['signMsg'] or '-'}")
            log(f"   ⚠️ [失败] {r['error'] or '未知错误'}")

    ok = sum(1 for r in results if r["success"])
    box_top(f"🏁 {APP_NAME} 执行汇总")
    box_line("📊 执行结果", f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}")
    box_bottom()

    if NOTIFY_ENABLED:
        content = build_notify(results)
        if send_qinglong_notify(f"{APP_NAME} 执行结果", content):
            log("   📮 [通知] 已调用青龙 notify")
        else:
            log("   ℹ️ [通知] 青龙 notify 未发送")
        if send_pushplus(f"{APP_NAME} 执行结果", content):
            log("   📮 [通知] PushPlus 已发送")
        else:
            log("   ℹ️ [通知] 未配置 PUSHPLUS_TOKEN，跳过 PushPlus")
    else:
        log("   ℹ️ [通知] JDB_NOTIFY=0，已关闭通知")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
