#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 植白说
# cron: 32 6,18 * * *

"""
植白说官方商城小程序（YYB Go 版）

功能：
  1. 开跑前只读校验 token，失效自动清缓存重登
  2. 每日签到 + 连签天数
  3. 分享加积分
  4. 领取优惠券
  5. 订阅通知
  6. 积分变化统计
  7. 青龙 notify + PushPlus 通知
  8. 可选品赞代理（PROXY_API）

环境变量：
  YYB_SERVER      必填：地址@微信标识[#备注]，多账号换行
  PROXY_API       品赞代理提取 API，可选
  PROXY_TYPE      http / socks5，默认 http
  ZBS_NOTIFY=0    关闭通知
  PUSHPLUS_TOKEN  PushPlus token（兼容 PLUSPLUS_TOKEN / PUSH_PLUS_TOKEN）

依赖：requests
"""

import json
import os
import random
import re
import sys
import time
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

APP_NAME = "植白说官方商城"
APPID = "wx6b6c5243359fe265"

BOX_WIDTH = 48
BOX_INNER = 46

BASE_URL = "https://www.kozbs.com/demo/wx"
SIGN_URL = f"{BASE_URL}/home/sign"
SIGN_DAY_URL = f"{BASE_URL}/home/signDay"
ADD_INTEGRAL_BY_SHARE_URL = f"{BASE_URL}/user/addIntegralByShare"
COUPON_LIST_URL = f"{BASE_URL}/coupon/list"
COUPON_MY_LIST_URL = f"{BASE_URL}/coupon/mylist"
COUPON_RECEIVE_URL = f"{BASE_URL}/coupon/receive"
SUBSCRIPTION_URL = f"{BASE_URL}/user/subscription"
USER_INDEX_URL = f"{BASE_URL}/user/index"
USER_INTEGRAL_URL = f"{BASE_URL}/user/getUserIntegral"
USER_IS_SIGN_URL = f"{BASE_URL}/user/getUserIsSign"
LOGIN_URL = f"{BASE_URL}/auth/login_by_weixin"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "zbs_token_cache.json")

NOTIFY_ENABLED = os.getenv("ZBS_NOTIFY", "1").strip() != "0"
PROXY_API = os.getenv("PROXY_API", "").strip()
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254173b) XWEB/19027",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50(0x1800322e) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/19899",
]

AUTH_PATTERN = re.compile(r"501|token|无效用户|登录|未登录|授权", re.I)
SIGNED_PATTERN = re.compile(r"已签|签到过|重复|已完成", re.I)


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
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:limit] + "…" if len(text) > limit else text


def mask(value: Any) -> str:
    text = str(value or "")
    return text if len(text) <= 12 else f"{text[:6]}***{text[-6:]}"


def mask_phone(phone: Any) -> str:
    text = str(phone or "")
    return f"{text[:3]}****{text[-4:]}" if len(text) >= 11 else text


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
def common_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": random.choice(UA_POOL),
        "Content-Type": "application/json",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "Referer": f"https://servicewechat.com/{APPID}/171/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["X-Dts-Token"] = token
    return headers


def _auth_error(status: int, errno: Any, errmsg: str) -> bool:
    if status in (401, 403):
        return True
    if str(errno) == "501":
        return True
    return bool(AUTH_PATTERN.search(str(errmsg or "")))


def _parse_response(response: requests.Response) -> Dict[str, Any]:
    status = response.status_code
    try:
        body = response.json()
    except Exception:
        return {
            "ok": False,
            "status": status,
            "errno": -1,
            "errmsg": f"JSON解析失败: {short(response.text, 200)}",
            "data": None,
            "auth": status in (401, 403),
        }
    if not isinstance(body, dict):
        return {
            "ok": False,
            "status": status,
            "errno": -1,
            "errmsg": f"响应不是对象: {short(body, 100)}",
            "data": None,
            "auth": False,
        }
    errno = body.get("errno")
    errmsg = str(body.get("errmsg") or body.get("message") or "")
    ok = status == 200 and str(errno) == "0"
    auth = _auth_error(status, errno, errmsg)
    return {"ok": ok, "status": status, "errno": errno, "errmsg": errmsg, "data": body.get("data"), "auth": auth}


def api_get(
    token: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    proxies: Optional[Dict[str, str]] = None,
    server: str = "",
) -> Dict[str, Any]:
    response = request_with_proxy(
        "GET", url, headers=common_headers(token), params=params or {}, proxies=proxies, server=server
    )
    return _parse_response(response)


def api_post(
    token: str,
    url: str,
    payload: Dict[str, Any],
    proxies: Optional[Dict[str, str]] = None,
    server: str = "",
) -> Dict[str, Any]:
    response = request_with_proxy(
        "POST", url, headers=common_headers(token), json=payload, proxies=proxies, server=server
    )
    return _parse_response(response)


def is_auth_error(result: Dict[str, Any]) -> bool:
    return bool(result.get("auth"))


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "是")


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("data", "list", "rows", "records"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


# ====================== YYB 登录 ======================
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
                log("   ✅ [授权] code 获取成功")
                return code
            log(f"   ⚠️ [授权] code 获取失败（第 {attempt + 1} 次）：{short(data, 100)}")
        except Exception as exc:
            log(f"   ⚠️ [授权] code 获取异常（第 {attempt + 1} 次）：{short(exc, 80)}")
        if attempt == 0:
            time.sleep(1)
    return None


def login_by_wx_code(
    server: str, ref: str, proxies: Optional[Dict[str, str]]
) -> Tuple[Optional[str], Dict[str, Any], str]:
    code = get_wx_code(server, ref)
    if not code:
        return None, {}, "getCode 失败"
    try:
        response = request_with_proxy(
            "POST",
            LOGIN_URL,
            headers=common_headers(),
            json={"code": code, "userInfo": {}, "shareUserId": 1},
            proxies=proxies,
            server=server,
        )
        data = response.json()
    except Exception as exc:
        return None, {}, f"登录异常: {exc}"
    if data.get("errno") != 0:
        return None, {}, f"登录失败: {data.get('errmsg') or short(data, 100)}"
    token = (data.get("data") or {}).get("token")
    if not token:
        return None, {}, f"登录响应未返回 token: {short(data, 100)}"
    user_info = (data.get("data") or {}).get("userInfo") or {}
    if not isinstance(user_info, dict):
        user_info = {}
    log(
        f"   ✅ [登录] 成功：{user_info.get('nickname') or mask_phone(user_info.get('mobile')) or '微信用户'}"
    )
    return str(token), user_info, ""


def resolve_user_id(token: str, user_info: Dict[str, Any], proxies, server: str) -> Tuple[str, int, str]:
    """返回 (userId, 当前积分, 查询错误)。userId 缺失时回退 1（接口以 token 识别用户）"""
    user_id = str(user_info.get("userId") or user_info.get("id") or "").strip()
    if not user_id:
        r = api_get(token, USER_INDEX_URL, {}, proxies, server)
        if r["ok"] and isinstance(r["data"], dict):
            user_id = str(r["data"].get("userId") or r["data"].get("id") or "").strip()
            for key in ("nickname", "mobile"):
                if r["data"].get(key) and not user_info.get(key):
                    user_info[key] = r["data"][key]
    if not user_id:
        user_id = "1"
        log("   ℹ️ [用户] 登录信息未返回 userId，按 1 处理（接口以 token 识别身份）")
    r = api_get(token, USER_INTEGRAL_URL, {"userId": user_id}, proxies, server)
    if r["ok"]:
        data = r["data"] if isinstance(r["data"], dict) else {}
        integral = data.get("integer", data.get("integral", data.get("point", 0)))
        return user_id, int(integral or 0), ""
    return user_id, 0, r["errmsg"]


# ====================== 业务动作 ======================
class AuthExpired(Exception):
    pass


def get_sign_state(token, user_id, proxies, server) -> Dict[str, Any]:
    r = api_get(token, SIGN_DAY_URL, {"userId": user_id}, proxies, server)
    if is_auth_error(r):
        raise AuthExpired(r["errmsg"] or "签到状态查询失效")
    if r["ok"]:
        data = r["data"] if isinstance(r["data"], dict) else {}
        if "isSign" in data:
            return {"signed": truthy(data.get("isSign")), "data": data, "source": "signDay"}
        return {"signed": None, "data": data, "source": "signDay"}
    log(f"   ⚠️ [签到] signDay 查询失败：{short(r['errmsg'], 80)}")
    r2 = api_get(token, USER_IS_SIGN_URL, {"userId": user_id}, proxies, server)
    if is_auth_error(r2):
        raise AuthExpired(r2["errmsg"] or "签到状态查询失效")
    if r2["ok"]:
        data = r2["data"] if isinstance(r2["data"], dict) else {}
        return {"signed": truthy(data.get("isSign")), "data": {}, "source": "getUserIsSign"}
    log(f"   ⚠️ [签到] getUserIsSign 查询失败：{short(r2['errmsg'], 80)}")
    return {"signed": None, "data": {}, "source": "unknown"}


def do_sign(token, user_id, proxies, server, signed_state) -> Dict[str, Any]:
    if signed_state.get("signed") is True:
        return {"status": "already", "message": "今日已签到", "data": signed_state.get("data") or {}}
    r = api_get(token, SIGN_URL, {"userId": user_id}, proxies, server)
    if is_auth_error(r):
        raise AuthExpired(r["errmsg"] or "签到失效")
    if r["ok"]:
        return {"status": "success", "message": "签到成功", "data": r["data"] if isinstance(r["data"], dict) else {}}
    msg = r["errmsg"] or "签到失败"
    if SIGNED_PATTERN.search(msg):
        return {"status": "already", "message": "今日已签到", "data": {}}
    return {"status": "error", "message": msg, "data": {}}


def do_share(token, user_id, proxies, server) -> str:
    r = api_get(token, ADD_INTEGRAL_BY_SHARE_URL, {"userId": user_id}, proxies, server)
    if is_auth_error(r):
        raise AuthExpired(r["errmsg"] or "分享接口失效")
    if r["ok"]:
        data = r["data"] if isinstance(r["data"], dict) else {}
        gain = data.get("integral") or data.get("integer")
        return f"分享成功{f'（+{gain}）' if gain else ''}"
    msg = r["errmsg"] or "分享失败"
    if "已分享" in msg or "重复" in msg:
        return "今日已分享"
    return msg


def do_receive_coupons(token, proxies, server) -> str:
    r = api_get(token, COUPON_LIST_URL, {"page": 1, "size": 100}, proxies, server)
    if is_auth_error(r):
        raise AuthExpired(r["errmsg"] or "券列表失效")
    if not r["ok"]:
        return f"获取券列表失败: {r['errmsg']}"
    data = r["data"] if isinstance(r["data"], dict) else {}
    coupon_list = as_list(data)
    if not isinstance(coupon_list, list) or not coupon_list:
        return "暂无可领优惠券"

    my_resp = api_get(token, COUPON_MY_LIST_URL, {"status": 0, "page": 1, "size": 100}, proxies, server)
    my_ids = set()
    if my_resp["ok"]:
        my_data = my_resp["data"] if isinstance(my_resp["data"], dict) else {}
        for item in as_list(my_data):
            if isinstance(item, dict) and item.get("id") is not None:
                my_ids.add(str(item.get("id")))

    received = []
    already = 0
    for coupon in coupon_list:
        if not isinstance(coupon, dict):
            continue
        coupon_id = coupon.get("id")
        if coupon_id is None:
            continue
        name = str(coupon.get("name") or "未知券")
        if str(coupon.get("isGet")) in ("1", "True", "true") or str(coupon_id) in my_ids:
            already += 1
            continue
        time.sleep(random.uniform(1, 3))
        recv = api_post(token, COUPON_RECEIVE_URL, {"couponId": coupon_id}, proxies, server)
        if is_auth_error(recv):
            raise AuthExpired(recv["errmsg"] or "领券失效")
        if recv["ok"]:
            received.append(name)
            log(f"   🎫 [领券] {name} 领取成功")
        else:
            log(f"   ⚠️ [领券] {name} 失败：{short(recv['errmsg'], 60)}")
        my_ids.add(str(coupon_id))

    if not received:
        return f"无可领优惠券（已领 {already} 张）" if already else "暂无可领优惠券"
    return f"领取 {len(received)} 张：{'、'.join(received)}"


def do_subscription(token, proxies, server) -> str:
    r = api_post(token, SUBSCRIPTION_URL, {"type": "1"}, proxies, server)
    if is_auth_error(r):
        raise AuthExpired(r["errmsg"] or "订阅失效")
    if r["ok"]:
        return "订阅成功"
    msg = r["errmsg"] or "订阅失败"
    if "已订阅" in msg or "重复" in msg:
        return "今日已订阅"
    return msg


def do_get_integral(token, user_id, proxies, server) -> Tuple[str, int]:
    r = api_get(token, USER_INTEGRAL_URL, {"userId": user_id}, proxies, server)
    if is_auth_error(r):
        raise AuthExpired(r["errmsg"] or "积分查询失效")
    if r["ok"]:
        data = r["data"] if isinstance(r["data"], dict) else {}
        integral = data.get("integer", data.get("integral", data.get("point", 0)))
        return str(int(integral or 0)), int(integral or 0)
    return f"查询失败({short(r['errmsg'], 40)})", 0


def get_sign_day_text(token, user_id, proxies, server) -> str:
    r = api_get(token, SIGN_DAY_URL, {"userId": user_id}, proxies, server)
    if not r["ok"]:
        return "查询签到天数失败"
    data = r["data"] if isinstance(r["data"], dict) else {}
    return f"已签{data.get('signCount', 0)}天，积分{data.get('integral', 0)}，抽奖{data.get('lotteryNum', 0)}次"


# ====================== 账号执行 ======================
TOTAL_ACCOUNTS = 0


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
        "signMessage": "-",
        "signStatus": "",
        "shareMessage": "-",
        "couponMessage": "-",
        "subscribeMessage": "-",
        "signDayMessage": "-",
        "integralBefore": 0,
        "integralAfter": 0,
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

    # 缓存 / 登录
    cached = load_cache_entry(server, ref)
    if cached:
        token = str(cached.get("token") or "")
        user_info = cached.get("userInfo") if isinstance(cached.get("userInfo"), dict) else {}
        result["loginSource"] = "缓存复用"
        log(f"   💾 [缓存] 复用已保存 token {mask(token)}")
        probe = api_get(token, USER_INTEGRAL_URL, {"userId": str(user_info.get("userId") or user_info.get("id") or "1")}, proxies, server)
        if is_auth_error(probe):
            log(f"   ⚠️ [校验] 缓存 token 失效（{short(probe['errmsg'], 60)}），清缓存重登")
            drop_cache_entry(server, ref)
            token, user_info, error = login_by_wx_code(server, ref, proxies)
            if not token:
                result["error"] = f"重新登录失败：{error}"
                log(f"   ❌ [登录] {result['error']}")
                return result
            result["loginSource"] = "缓存失效重登"
        elif not probe["ok"]:
            log(f"   ⚠️ [校验] 积分接口异常但非鉴权（{short(probe['errmsg'], 60)}），继续执行")
        else:
            log("   ✅ [校验] 登录凭证校验通过（积分接口）")
    else:
        result["loginSource"] = "新登录"
        log("   🔄 [登录] 无缓存 token，执行首次登录")
        token, user_info, error = login_by_wx_code(server, ref, proxies)
        if not token:
            result["error"] = f"登录失败：{error}"
            log(f"   ❌ [登录] {result['error']}")
            return result

    user_id, integral, integral_error = resolve_user_id(token, user_info, proxies, server)
    if integral_error and AUTH_PATTERN.search(integral_error):
        result["error"] = f"token 校验失败：{integral_error}"
        log(f"   ❌ [校验] {result['error']}")
        return result
    result["userId"] = user_id
    result["nickname"] = str(user_info.get("nickname") or "")
    result["integralBefore"] = integral
    log(
        f"   👤 [会员] {result['nickname'] or mask_phone(user_info.get('mobile')) or '微信用户'}，userId={user_id}，当前积分 {integral}"
    )

    def execute() -> None:
        nonlocal token, user_id, user_info, integral
        # 签到
        state = get_sign_state(token, user_id, proxies, server)
        sign = do_sign(token, user_id, proxies, server, state)
        if sign["status"] == "already":
            log("   ℹ️ [签到] 今日已签到")
        elif sign["status"] == "success":
            log("   ✅ [签到] 签到成功")
        else:
            log(f"   ❌ [签到] 失败：{short(sign['message'], 80)}")
        result["signStatus"] = sign["status"]
        result["signMessage"] = sign["message"]

        # 连签信息：签到成功后重新查询，避免显示签到前的天数
        data = state.get("data") if isinstance(state.get("data"), dict) else {}
        if sign["status"] == "success":
            result["signDayMessage"] = get_sign_day_text(token, user_id, proxies, server)
        elif data:
            result["signDayMessage"] = f"已签{data.get('signCount', 0)}天，积分{data.get('integral', 0)}，抽奖{data.get('lotteryNum', 0)}次"
        else:
            result["signDayMessage"] = get_sign_day_text(token, user_id, proxies, server)
        log(f"   📅 [连签] {result['signDayMessage']}")

        time.sleep(random.uniform(1, 3))
        result["shareMessage"] = do_share(token, user_id, proxies, server)
        log(f"   🔗 [分享] {result['shareMessage']}")

        time.sleep(random.uniform(1, 3))
        result["couponMessage"] = do_receive_coupons(token, proxies, server)
        log(f"   🎫 [领券] {result['couponMessage']}")

        time.sleep(random.uniform(1, 2))
        result["subscribeMessage"] = do_subscription(token, proxies, server)
        log(f"   🔔 [订阅] {result['subscribeMessage']}")

        integral_text, integral_num = do_get_integral(token, user_id, proxies, server)
        if integral_text.isdigit():
            result["integralAfter"] = integral_num
        log(f"   💰 [积分] 当前积分 {integral_text}")

    try:
        execute()
    except AuthExpired as exc:
        log(f"   ⚠️ [重登] 业务返回鉴权失效（{short(exc, 60)}），重新登录后重试")
        drop_cache_entry(server, ref)
        token, user_info, error = login_by_wx_code(server, ref, proxies)
        if not token:
            result["error"] = f"重登失败：{error}"
            log(f"   ❌ [重登] {result['error']}")
            return result
        user_id, integral, _ = resolve_user_id(token, user_info, proxies, server)
        result["loginSource"] = "接口失效重登"
        result["userId"] = user_id
        result["integralBefore"] = integral
        for key in ("signMessage", "signStatus", "shareMessage", "couponMessage", "subscribeMessage", "signDayMessage"):
            result[key] = "-"
        try:
            execute()
        except AuthExpired as exc2:
            result["error"] = f"重登后仍失效：{exc2}"
            log(f"   ❌ [重登] {result['error']}")
            return result

    result["success"] = result["signStatus"] in ("success", "already")
    if not result["success"] and not result["error"]:
        result["error"] = f"签到失败：{result['signMessage']}" if result["signMessage"] != "-" else "签到未成功"
    save_cache_entry(
        server,
        ref,
        {
            "token": token,
            "userInfo": user_info,
            "userId": user_id,
            "nickname": result["nickname"],
            "updatedAt": now_text(),
        },
    )

    delta = int(result["integralAfter"] or 0) - int(result["integralBefore"] or 0)
    log(f"   💰 [积分] {result['integralBefore']} → {result['integralAfter']}（{'+' if delta >= 0 else ''}{delta}）")
    if result["success"]:
        log("   ✅ [完成] 该账号任务执行完成")
    else:
        log(f"   ⚠️ [完成] 签到未成功：{short(result['signMessage'], 80)}")
    return result


# ====================== 通知 ======================
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
    lines = [
        f"【{APP_NAME}】每日任务",
        f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}",
        "",
    ]
    for r in results:
        flag = "✅" if r["success"] else "❌"
        lines.append(f"{flag} 账号{r['index']} {r['title']}：{r.get('signMessage') or r.get('error') or '-'}")
        lines.append(
            f"   登录：{r.get('loginSource') or '-'}｜积分 {r.get('integralBefore', 0)} → {r.get('integralAfter', 0)}"
            f"｜{r.get('proxyStatus') or '-'}"
        )
        lines.append(f"   连签：{r.get('signDayMessage') or '-'}｜分享：{r.get('shareMessage') or '-'}")
        lines.append(f"   领券：{r.get('couponMessage') or '-'}｜订阅：{r.get('subscribeMessage') or '-'}")
        if not r["success"] and r.get("error"):
            lines.append(f"   失败：{r['error']}")
    return "\n".join(lines)


# ====================== 主流程 ======================
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

    global TOTAL_ACCOUNTS
    TOTAL_ACCOUNTS = len(valid)

    box_top(f"🥤 {APP_NAME} 每日任务")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(valid)} 个{f'（{len(invalid)} 行格式无效）' if invalid else ''}")
    box_line("💾 缓存", os.path.basename(TOKEN_CACHE_FILE))
    box_line("🧩 功能", "签到｜连签｜分享｜领券｜订阅")
    box_line("🌐 代理", f"品赞 {PROXY_TYPE.upper()}" if PROXY_API else "未配置（直连）")
    box_bottom()

    for line in invalid:
        log(f"   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过：{short(line, 60)}")

    results = []
    for index, entry in enumerate(valid, start=1):
        try:
            results.append(run_account(index, len(valid), entry))
        except Exception as exc:
            log(f"   ❌ [执行] 账号 {index} 未捕获异常：{short(exc, 100)}")
            results.append(
                {
                    "index": index,
                    "title": entry,
                    "success": False,
                    "loginSource": "",
                    "signMessage": "",
                    "integralBefore": 0,
                    "integralAfter": 0,
                    "proxyStatus": "-",
                    "error": f"异常 {short(exc, 100)}",
                }
            )
        hr()
        if index < len(valid):
            log("   ⏳ 等待2秒后执行下一个账号...")
            time.sleep(2)

    log()
    for r in results:
        if r["success"]:
            log(f"✅ 【账号 {r['index']} · {r['title']}】")
            log(f"   🔐 [登录] {r['loginSource'] or '-'}")
            log(f"   📅 [签到] {r['signMessage']}")
            log(f"   💰 [积分] {r['integralBefore']} → {r['integralAfter']}")
            log(f"   🔗 [分享] {r['shareMessage']}")
            log(f"   🎫 [领券] {r['couponMessage']}")
            log(f"   🔔 [订阅] {r['subscribeMessage']}")
        else:
            log(f"❌ 【账号 {r['index']} · {r['title']}】")
            log(f"   🔐 [登录] {r['loginSource'] or '-'}")
            log(f"   📅 [签到] {r['signMessage'] or '-'}")
            log(f"   ⚠️ [失败] {r['error'] or '未知错误'}")

    ok = sum(1 for r in results if r["success"])
    delta = sum(int(r["integralAfter"] or 0) - int(r["integralBefore"] or 0) for r in results)
    box_top(f"🏁 {APP_NAME} 执行汇总")
    box_line("📊 执行结果", f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}")
    box_line("💰 积分总变化", f"{'+' if delta >= 0 else ''}{delta}")
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
        log("   ℹ️ [通知] ZBS_NOTIFY=0，已关闭通知")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        log(f"❌ 脚本异常：{short(exc, 200)}")
