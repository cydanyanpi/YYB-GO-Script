#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 甄稀冰淇淋
# cron: 5 9 * * *
# 版本: 1.1.1
"""
甄稀冰淇淋小程序（YYB Go 版 / HXEK 模板）

功能：
  1. YYB_SERVER 获取微信 code（地址@账号标识[#备注]，多账号换行）
  2. /auth/account/login 用 code 换 accessToken
  3. 开跑前用只读接口校验登录态（用户信息 / 积分 / 签到状态 / 积分明细）
  4. 未签到才调用签到接口，已签到直接跳过
  5. 输出会员等级、当前积分、今日积分明细；跑完汇总所有账号
  6. 青龙 notify + PushPlus + 可选企业微信推送

环境变量：
  YYB_SERVER        必填；YYB Go 地址@微信账号标识，多账号每行一条，可带 #备注
  ZHENXI_NOTIFY     默认 1；0=关闭青龙 notify / PushPlus / 企业微信
  PLUSPLUS_TOKEN    可选；PushPlus token
  QYWX_TOKEN        可选；企业微信机器人 Webhook key
  PROXY_API         可选；留空直连

缓存：token_caches/zhenxi_token_cache.json，按「地址|标识」隔离，并校验 appid+tenant，
      不会复用活力伊利等其他小程序的旧 token。
"""

import importlib.util
import json
import os
import random
import re
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests

APP_NAME = "甄稀冰淇淋"
APP_ID = "wx21fd8b5d6d4cf1ca"
TENANT_ID = "1734445152308379650"
WX_ROUTE_TAG = "a1da45c1c-wx621112590b635086"
WX_REFERER_VERSION = "240"
API_BASE = "https://msmarket.msx.digitalyili.com/gateway/api"
LOGIN_URL = f"{API_BASE}/auth/account/login"
USER_INFO_URL = f"{API_BASE}/auth/account/user/info"
POINT_URL = f"{API_BASE}/member/point"
SIGN_STATUS_URL = f"{API_BASE}/member/sign/status"
SIGN_CONFIG_URL = f"{API_BASE}/member/sign/config"
SIGN_URL = f"{API_BASE}/member/daily/sign?isUseNewLogic=1"
POINT_PAGE_URL = f"{API_BASE}/member/point/page"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(BASE_DIR, "token_caches", "zhenxi_token_cache.json")
CACHE_SCOPE = f"{APP_ID}|{TENANT_ID}"
NOTIFY_ENABLED = os.getenv("ZHENXI_NOTIFY", "1") != "0"
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
QYWX_TOKEN = os.getenv("QYWX_TOKEN", "")
PROXY_API = os.getenv("PROXY_API", "").strip()
TZ_CN = timezone(timedelta(hours=8))

BOX_WIDTH = 48
BOX_INNER = 46

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541923) XWEB/19823",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541d41) XWEB/25560",
    "Mozilla/5.0 (Linux; Android 12; M2012K11AC Build/SKQ1.220303.001; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.136 "
    "Mobile Safari/537.36 MicroMessenger/8.0.48.2580(0x28003036) "
    "MiniProgramEnv/android",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.50 NetType/WIFI Language/zh_CN",
]

AUTH_PATTERN = re.compile(
    r"未登录|登录失效|登录已过期|请重新登录|token\s*(无效|过期|失效)"
    r"|accessToken\s*(无效|过期|失效)|获取微信授权信息失败"
    r"|-4011|\b401\b|\b403\b",
    re.I,
)


# ====================== 日志与边框 ======================
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
    return datetime.now(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")


# ====================== 工具 ======================
def pick_ua():
    return random.choice(UA_POOL)


def mask_id(value):
    value = str(value or "")
    return value if len(value) <= 6 else f"{value[:3]}****{value[-3:]}"


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
    return str(value) if value is not None and value != "?" else "未知"


def brief(value, limit=180):
    text = str(value or "").replace("\n", " ")
    return text[: limit - 1] + "…" if len(text) > limit else text


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
    if at_pos <= 0:
        return "", "", note
    server = body[:at_pos].strip()
    ref = body[at_pos + 1:].strip()
    server = re.sub(r"^https?://", "", server, flags=re.I).rstrip("/")
    return server, ref, note


def cache_key(server, ref):
    return f"{server}|{ref}"


def json_preview(data, limit=300):
    try:
        return json.dumps(data, ensure_ascii=False)[:limit]
    except Exception:
        return str(data)[:limit]


# ====================== 缓存 ======================
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


def read_cache_entry(ck):
    entry = (read_token_cache().get(ck) or {})
    if entry.get("token") and entry.get("scope") == CACHE_SCOPE:
        return entry
    return {}


def save_cache_entry(ck, token, expire_time=None):
    cache = read_token_cache()
    cache[ck] = {
        "token": token,
        "expireTime": expire_time or "",
        "scope": CACHE_SCOPE,
        "updatedAt": now_text(),
    }
    write_token_cache(cache)


def drop_cache_entry(ck):
    cache = read_token_cache()
    if ck in cache:
        cache.pop(ck, None)
        write_token_cache(cache)


# ====================== 请求 ======================
def common_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": pick_ua(),
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "xweb_xhr": "1",
        "Origin": "https://servicewechat.com",
        "Referer": f"https://servicewechat.com/{APP_ID}/{WX_REFERER_VERSION}/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "tenant-id": TENANT_ID,
        "scene": "1027",
        "atv-page": "",
        "forward-appid": "",
        "register-source": "",
        "source-type": "",
        "X-WX-HTTP-MODE": "REROUTE",
        "X-WX-CONF-VERSION": "0",
        "x-wx-call-id": f"{int(time.time() * 1000)}-{random.randint(100000, 999999)}",
        "x-wx-route-tag": f"{WX_ROUTE_TAG}.sh.wxgateway.com",
        "x-wx-source": "wx_client",
        "x-wx-appid": APP_ID,
        "x-envoy-expected-rq-timeout-ms": "15000",
    }
    if token:
        headers["access-token"] = token
    return headers


def _proxies_for(server: str):
    """预留 PROXY_API；未配置时直连。"""
    if not PROXY_API:
        return None
    try:
        response = requests.get(PROXY_API, timeout=10, proxies={"http": None, "https": None})
        text = (response.text or "").strip()
        try:
            data = response.json()
        except Exception:
            data = None
        host = port = username = password = ""
        if isinstance(data, dict):
            item = data.get("data") or data
            if isinstance(item, dict):
                host = str(item.get("ip") or item.get("host") or "")
                port = str(item.get("port") or "")
                username = str(item.get("username") or item.get("user") or "")
                password = str(item.get("password") or item.get("pass") or "")
        if not host:
            parts = text.split(":")
            if len(parts) >= 2 and parts[1].strip().isdigit():
                host, port = parts[0].strip(), parts[1].strip()
                username = parts[2].strip() if len(parts) > 2 else ""
                password = parts[3].strip() if len(parts) > 3 else ""
        if host and port:
            auth = f"{username}:{password}@" if username and password else ""
            scheme = "socks5" if os.getenv("PROXY_TYPE", "http").lower() == "socks5" else "http"
            url = f"{scheme}://{auth}{host}:{port}"
            log(f"   🌐 [代理] 使用 {scheme.upper()} 代理 {host}:{port}")
            return {"http": url, "https": url}
        log("   ⚠️ [代理] 代理接口未返回可用地址，改用直连")
    except Exception as exc:
        log(f"   ⚠️ [代理] 获取失败，改用直连：{brief(exc, 80)}")
    return None


def api_request(method, url, token=None, *, json_body=None, params=None, proxies=None):
    try:
        response = requests.request(
            method, url, headers=common_headers(token), json=json_body, params=params,
            timeout=30, proxies=proxies if proxies is not None else {"http": None, "https": None},
        )
        try:
            data = response.json()
        except Exception:
            data = {"status": False, "error": {"msg": f"HTTP {response.status_code}: {response.text[:120]}"}}
        if isinstance(data, dict):
            data["_http"] = response.status_code
            return data
        return {"status": False, "error": {"msg": "接口返回非 JSON 对象"}, "_http": response.status_code}
    except Exception as exc:
        return {"status": False, "error": {"msg": f"请求异常: {exc}"}, "_http": 0}


def http_ok(data) -> bool:
    return isinstance(data, dict) and data.get("status") is True


def api_error(data) -> str:
    if not isinstance(data, dict):
        return "接口返回异常"
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("msg") or err.get("message") or json_preview(err, 120))
    if err:
        return str(err)
    return str(data.get("msg") or data.get("message") or "接口返回失败")


def is_auth_error(data) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("_http") in (401, 403):
        return True
    err = data.get("error")
    code = None
    msg = ""
    if isinstance(err, dict):
        code = err.get("code")
        msg = str(err.get("msg") or err.get("message") or "")
    elif err:
        msg = str(err)
    if code in (401, 403, "401", "403"):
        return True
    return bool(AUTH_PATTERN.search(msg or str(data.get("msg") or "")))


def get_wx_code(server_entry: str):
    server, ref, _ = parse_entry(server_entry)
    if not server or not ref:
        log("   ❌ [配置] YYB_SERVER 格式应为 地址@微信账号标识[#备注]")
        return None
    try:
        response = requests.post(
            f"http://{server}/wxapp/getCode",
            json={"ref": ref, "app_id": APP_ID},
            timeout=30, proxies={"http": None, "https": None},
        )
        data = response.json()
        result = (data.get("data") or {}).get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                result = {}
        code = (result or {}).get("code")
        try:
            code_num = int(str(data.get("code")))
        except Exception:
            code_num = -1
        if code_num == 0 and code:
            log("   ✅ [取码] 取码成功")
            return code
        log(f"   ❌ [取码] 取码失败：{brief(data)}")
        return None
    except Exception as exc:
        log(f"   ❌ [取码] 取码异常：{exc}")
        log(f"   💡 [提示] 请检查 YYB 服务地址 http://{server} 是否在线、{ref} 是否已登录")
        return None


def login_by_code(code: str, proxies=None):
    log("   🔐 [登录] 正在用 code 换 accessToken...")
    data = api_request("POST", LOGIN_URL, None, json_body={"jsCode": code}, proxies=proxies)
    if not http_ok(data):
        log(f"   ❌ [登录] 登录失败：{api_error(data)}")
        return None, data
    inner = data.get("data") or {}
    token = inner.get("accessToken") or data.get("accessToken")
    if not token:
        log(f"   ❌ [登录] 未返回 accessToken：{json_preview(data, 200)}")
        return None, data
    log(f"   ✅ [登录] 登录成功，token {mask_id(token)}")
    return token, data


# ====================== 业务解析 ======================
def extract_member_level(info) -> str:
    if not isinstance(info, dict):
        return "-"
    for tag in (info.get("userMemberTags") or []):
        name = str(tag.get("memberTagName") or "")
        if "会员等级" in name:
            values = tag.get("memberTagValues") or []
            if values:
                level = values[0].get("valueName")
                if level:
                    return str(level)
    level = to_number(info.get("userLevel"))
    level_map = {
        1: "普通会员", 2: "白银会员", 3: "黄金会员",
        4: "铂金会员", 5: "钻石会员",
    }
    return level_map.get(level, "-") if level is not None else "-"


def _parse_item_time(value):
    number = to_number(value)
    if number is None:
        return None
    try:
        return datetime.fromtimestamp(number / 1000, TZ_CN)
    except Exception:
        return None


def parse_point_page(page_data):
    items = (page_data or {}).get("items") or []
    details = []
    today_points = 0
    today_count = 0
    today = datetime.now(TZ_CN).date()
    for item in items:
        point = to_number(item.get("changePoint"))
        if point is None:
            point = 0
        dt = _parse_item_time(item.get("createTime"))
        remark = str(item.get("remark") or "-")
        if dt is not None:
            details.append(f"{dt.strftime('%m-%d %H:%M')} {remark} {int(point):+d}")
            if dt.date() == today:
                today_points += int(point)
                today_count += 1
        else:
            details.append(f"{remark} {int(point):+d}")
    # 连续签到：从今天往前数，明细里连续出现的“签到”日期
    sign_dates = set()
    for item in items:
        dt = _parse_item_time(item.get("createTime"))
        if dt is not None and "签到" in str(item.get("remark") or ""):
            sign_dates.add(dt.date())
    streak = 0
    cursor = today
    while cursor in sign_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return details, today_points, today_count, streak


def probe_member(token: str, proxies=None):
    """只读校验登录态，并取回用户、等级、积分、签到状态、今日明细。"""
    info_resp = api_request("GET", USER_INFO_URL, token, proxies=proxies)
    info_ok = http_ok(info_resp)
    user = (info_resp.get("data") or {}) if info_ok else {}

    point_resp = api_request("GET", POINT_URL, token, proxies=proxies)
    points = to_number((point_resp.get("data") if http_ok(point_resp) else None))

    status_resp = api_request("GET", SIGN_STATUS_URL, token, proxies=proxies)
    status_data = (status_resp.get("data") or {}) if http_ok(status_resp) else {}
    signed = status_data.get("signed") if http_ok(status_resp) else None
    week_days = status_data.get("weekSignDays")

    page_resp = api_request("POST", POINT_PAGE_URL, token,
                            json_body={"pageIndex": 1, "pageSize": 20}, proxies=proxies)
    page_data = (page_resp.get("data") or {}) if http_ok(page_resp) else {}
    details, today_points, today_count, streak = parse_point_page(page_data)

    bonus_point = None
    if signed is not True:
        config_resp = api_request("GET", SIGN_CONFIG_URL, token, proxies=proxies)
        if http_ok(config_resp):
            daily = (config_resp.get("data") or {}).get("dailySignConfig") or {}
            bonus_point = to_number(daily.get("bonusPoint"))

    auth = any(is_auth_error(x) for x in (info_resp, point_resp, status_resp, page_resp))
    valid = info_ok or http_ok(point_resp)
    msg = ""
    if not valid:
        msg = api_error(info_resp if not info_ok else point_resp)
    return {
        "ok": valid,
        "auth": auth,
        "msg": msg,
        "user": user,
        "nickname": user.get("nickName") or "-",
        "userId": user.get("userId") or "",
        "level": extract_member_level(user),
        "points": points,
        "signed": signed,
        "weekDays": week_days,
        "continuous": streak,
        "details": details,
        "todayPoints": today_points,
        "todayCount": today_count,
        "bonusPoint": bonus_point,
    }


def apply_probe(result: dict, probe: dict):
    result["nickname"] = probe.get("nickname") or result["nickname"]
    result["member"] = mask_id(probe.get("userId") or result["member"])
    result["level"] = probe.get("level") or result["level"]
    if probe.get("points") is not None:
        result["points"] = fmt_points(probe["points"])
    result["signedToday"] = probe.get("signed")
    result["continuous"] = probe.get("continuous")
    result["weekDays"] = probe.get("weekDays")
    result["details"] = probe.get("details") or []
    result["todayPoints"] = probe.get("todayPoints")
    result["todayCount"] = probe.get("todayCount")
    result["bonusPoint"] = probe.get("bonusPoint")


def sign_once(token: str, proxies=None):
    log("   ✍️ [签到] 正在提交签到请求...")
    data = api_request("POST", SIGN_URL, token, json_body={}, proxies=proxies)
    if http_ok(data):
        inner = data.get("data") or {}
        bonus = to_number((inner.get("dailySign") or {}).get("bonusPoint"))
        return {"ok": True, "already": False, "bonus": bonus,
                "msg": f"签到成功 +{bonus}积分" if bonus is not None else "签到成功"}
    msg = api_error(data)
    if any(k in msg for k in ("已签", "已经签", "签过", "重复", "已领取")):
        return {"ok": True, "already": True, "bonus": None, "msg": "今日已签到"}
    return {"ok": False, "already": False, "bonus": None, "msg": msg,
            "auth": is_auth_error(data)}


def _login_text(result):
    source = result.get("loginSource") or ""
    state = result.get("loginState") or "未确认"
    return f"{source}（{state}）" if source else state


def _level_text(result):
    return result.get("level") if result.get("level") not in (None, "", "-") else "未知"


def _today_text(result):
    count = int(result.get("todayCount") or 0)
    points = int(result.get("todayPoints") or 0)
    return f"{points:+d}（{count} 笔）" if count else "±0（0 笔）"


# ====================== 单账号 ======================
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
        "loginState": "未取得",
        "member": "-",
        "nickname": "-",
        "level": "-",
        "signMsg": "-",
        "points": "未知",
        "todayPoints": None,
        "todayCount": 0,
        "continuous": None,
        "weekDays": None,
        "signedToday": None,
        "details": [],
        "error": "",
    }

    if not server or not ref:
        result["error"] = "YYB_SERVER 格式错误（应为 地址@微信账号标识）"
        log(f"   ❌ [配置] {result['error']}")
        return result

    ck = cache_key(server, ref)
    token = ""
    probe = {}
    proxies = _proxies_for(server)

    for attempt in range(2):
        # ① 先复用缓存
        if attempt == 0 and not token:
            entry = read_cache_entry(ck)
            if entry.get("token"):
                token = entry["token"]
                result["loginSource"] = "缓存"
                result["loginState"] = "待校验"
                log(f"   💾 [缓存] 复用已保存 token：{mask_id(token)}")

        # ② 只读校验登录态
        if token:
            probe = probe_member(token, proxies)
            if probe.get("ok"):
                apply_probe(result, probe)
                result["loginState"] = "有效"
                log(f"   ✅ [校验] 登录态有效 ｜ 用户 {result['nickname']} ｜ 等级 {_level_text(result)} ｜ 积分 {result['points']}")
                break
            result["loginState"] = "未确认"
            log(f"   ⚠️ [校验] 只读接口未通过：{probe.get('msg') or '未知'}")
            if probe.get("auth") and attempt == 0:
                log("   🔄 [重试] 凭证失效，清理缓存后重新登录")
                drop_cache_entry(ck)
                token = ""
                continue
            # 非鉴权失败（网络/接口异常）保留 token，继续尝试签到
            break

        # ③ 没有缓存或缓存失效 → 取码登录
        code = get_wx_code(server_entry)
        if not code:
            result["error"] = "取码失败（检查 YYB 服务地址与账号标识）"
            result["loginState"] = "未取得"
            log("   ❌ [登录] 取码失败，跳过该账号")
            return result
        token, login_data = login_by_code(code, proxies)
        if not token:
            result["error"] = f"登录失败：{api_error(login_data)}"
            result["loginState"] = "未取得"
            log("   ❌ [登录] 登录失败，跳过该账号")
            return result
        inner = (login_data.get("data") or {}) if isinstance(login_data, dict) else {}
        expire_time = inner.get("expireTime") or inner.get("expire_time")
        save_cache_entry(ck, token, str(expire_time) if expire_time else "")
        result["loginSource"] = "重新登录" if attempt == 1 else "新登录"
        login_user = inner.get("userInfo") or {}
        if login_user:
            result["nickname"] = login_user.get("nickName") or result["nickname"]
            result["member"] = mask_id(login_user.get("userId") or "")
            result["level"] = extract_member_level(login_user)

        probe = probe_member(token, proxies)
        if probe.get("ok"):
            apply_probe(result, probe)
            result["loginState"] = "有效"
            log(f"   ✅ [校验] 登录态有效 ｜ 用户 {result['nickname']} ｜ 等级 {_level_text(result)} ｜ 积分 {result['points']}")
        else:
            result["loginState"] = "未确认"
            log(f"   ⚠️ [校验] 只读接口未通过：{probe.get('msg') or '未知'}")
        break

    if not token:
        result["error"] = "登录失败：未取得 accessToken"
        result["loginState"] = "未取得"
        log("   ❌ [完成] 该账号未取得登录态")
        return result

    if probe.get("auth") and not probe.get("ok"):
        result["error"] = "登录后凭证仍无效"
        result["loginState"] = "失效"
        log("   ❌ [完成] 登录后凭证仍无效")
        return result

    # ④ 已签到则直接跳过
    if result.get("signedToday") is True:
        result["signMsg"] = "今日已签到"
        result["success"] = True
        result["loginState"] = "有效"
        log("   ✅ [签到] 今日已签到，跳过签到请求")
    else:
        time.sleep(random.uniform(1.0, 1.8))
        sign = sign_once(token, proxies)

        # 签到返回 401/登录失效时，按模板只清缓存重登一次，再重试签到
        if not sign["ok"] and sign.get("auth"):
            log("   🔄 [重试] 签到返回凭证失效，清理缓存后重新登录")
            drop_cache_entry(ck)
            token = ""
            code = get_wx_code(server_entry)
            if code:
                token, login_data = login_by_code(code, proxies)
                if token:
                    save_cache_entry(ck, token, "")
                    result["loginSource"] = "重新登录"
                    probe = probe_member(token, proxies)
                    if probe.get("ok"):
                        apply_probe(result, probe)
                        result["loginState"] = "有效"
                    log(f"   ✅ [校验] 重新登录成功 ｜ 用户 {result['nickname']} ｜ 等级 {_level_text(result)}")
                    time.sleep(random.uniform(1.0, 1.5))
                    sign = sign_once(token, proxies)

        if sign["ok"]:
            result["signMsg"] = sign["msg"]
            result["success"] = True
            log(f"   ✅ [签到] {sign['msg']}")
            # 签到后复查，取真实积分与今日明细
            time.sleep(random.uniform(0.8, 1.2))
            probe_after = probe_member(token, proxies)
            if probe_after.get("ok"):
                before = to_number(result.get("points"))
                apply_probe(result, probe_after)
                after = to_number(result.get("points"))
                if before is not None and after is not None and after > before:
                    result["signMsg"] = f"签到成功 +{after - before}积分"
            else:
                log(f"   ⚠️ [复查] 签到后查询失败：{probe_after.get('msg') or '未知'}")
        else:
            result["signMsg"] = sign["msg"]
            result["error"] = sign["msg"]
            log(f"   ❌ [签到] {sign['msg']}")
            if sign.get("auth"):
                result["error"] = f"{sign['msg']}（重登后仍失败）"
                result["loginState"] = "失效"
            log("   ⚠️ [完成] 签到未成功")
            return result

    # ⑤ 账号收尾
    if result["nickname"] == "-" and result.get("name"):
        result["nickname"] = result["name"]
    if result["points"] == "未知":
        log("   ⚠️ [积分] 未取到积分")
    else:
        log(f"   💰 [积分] 当前 {result['points']} ｜ 今日 {_today_text(result)}")
    log(f"   🏅 [等级] {_level_text(result)}")
    if result.get("continuous"):
        log(f"   📆 [连续] 已连续签到 {result['continuous']} 天")
    elif result.get("weekDays") not in (None, "", "-1", -1):
        log(f"   📆 [签到] 本周已签 {result['weekDays']} 天")
    if result.get("details"):
        log(f"   🧾 [明细] 最近 {len(result['details'])} 笔")
        for line in result["details"][:5]:
            log(f"      • {line}")
    log("   ✅ [完成] 该账号任务执行完成")
    return result


# ====================== 统计与通知 ======================
def aggregate_point_stats(results: List[dict]) -> dict:
    total_points = 0
    point_accounts = 0
    today_points = 0
    today_count = 0
    active_accounts = 0
    for item in results:
        try:
            total_points += int(item.get("points"))
            point_accounts += 1
        except (TypeError, ValueError):
            pass
        today_points += int(item.get("todayPoints") or 0)
        today_count += int(item.get("todayCount") or 0)
        if int(item.get("todayCount") or 0):
            active_accounts += 1
    return {
        "totalPoints": total_points,
        "pointAccounts": point_accounts,
        "todayPoints": today_points,
        "todayCount": today_count,
        "activeAccounts": active_accounts,
    }


def print_point_summary(results: List[dict]) -> None:
    stats = aggregate_point_stats(results)
    print()
    print("-" * BOX_WIDTH)
    log("📊 本次积分统计")
    log(f"💰 当前积分合计：{stats['totalPoints']}（{stats['pointAccounts']} 个账号）")
    log(f"📥 今日新增合计：{stats['todayPoints']:+d}（{stats['todayCount']} 笔，{stats['activeAccounts']} 个账号有新增）")
    log("🏅 账号明细：")
    for item in results:
        icon = "✅" if item.get("success") else "❌"
        name = item.get("nickname") or item.get("name") or "-"
        level = _level_text(item)
        points = item.get("points") if item.get("points") not in (None, "") else "-"
        log(f"   {icon} 账号{item['index']}  {name}（{level}）  登录态 {item.get('loginState') or '未确认'}  当前 {points}  今日 {_today_text(item)}")
    print("-" * BOX_WIDTH)


def build_notify(results: List[dict]) -> str:
    stats = aggregate_point_stats(results)
    ok_count = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - ok_count
    lines = [
        f"### {APP_NAME} 每日签到",
        "",
        f"- 执行结果：成功 {ok_count} / 失败 {fail_count} / 共 {len(results)}",
        f"- 当前积分合计：{stats['totalPoints']}（{stats['pointAccounts']} 个账号）",
        f"- 今日新增合计：{stats['todayPoints']:+d}（{stats['todayCount']} 笔，{stats['activeAccounts']} 个账号有新增）",
        f"- 时间：{now_text()}",
    ]
    for r in results:
        flag = "✅" if r.get("success") else "❌"
        lines += [
            "",
            f"#### {flag} 账号 {r['index']} · {r['source']}",
            f"- 用户：{r.get('nickname') or '-'}",
            f"- 等级：{_level_text(r)}",
        ]
        lines.append(f"- 登录态：{_login_text(r)}")
        lines += [
            f"- 签到：{r.get('signMsg') or '-'}",
            f"- 积分：{r.get('points')}",
            f"- 今日：{_today_text(r)}",
        ]
        if r.get("continuous"):
            lines.append(f"- 连续：{r['continuous']} 天")
        elif r.get("weekDays") not in (None, "", "-1", -1):
            lines.append(f"- 本周已签：{r['weekDays']} 天")
        for line in (r.get("details") or [])[:3]:
            lines.append(f"  - {line}")
        if not r.get("success"):
            lines.append(f"- 失败原因：{r.get('error') or '未知'}")
    return "\n".join(lines)


def send_qinglong_notify(title, content):
    if not NOTIFY_ENABLED:
        log("   ℹ️ [通知] ZHENXI_NOTIFY=0，已关闭通知")
        return False
    for candidate in (
        "/ql/data/scripts/notify.py",
        "/ql/scripts/notify.py",
        "/ql/data/notify.py",
        os.path.join(BASE_DIR, "notify.py"),
    ):
        if not os.path.exists(candidate):
            continue
        try:
            spec = importlib.util.spec_from_file_location("zhenxi_ql_notify", candidate)
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
    if not NOTIFY_ENABLED:
        return
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


def send_qywx(title, content):
    if not NOTIFY_ENABLED or not QYWX_TOKEN:
        return
    try:
        requests.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={QYWX_TOKEN}",
            json={"msgtype": "text", "text": {"content": f"{title}\n{content}"}},
            timeout=10, proxies={"http": None, "https": None},
        )
        log("   📨 [推送] 企业微信推送成功")
    except Exception as exc:
        log(f"   ⚠️ [推送] 企业微信推送失败：{exc}")


# ====================== 主入口 ======================
def main():
    servers = [line.strip() for line in os.getenv("YYB_SERVER", "").splitlines() if line.strip()]

    box_top(f"🍦 {APP_NAME} 自动签到")
    if not servers:
        box_line("⚠️ 状态", "未配置 YYB_SERVER")
        box_bottom()
        log("格式：YYB Go 地址@微信账号标识，多账号每行一条，可带 #备注")
        return []
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(servers)} 个")
    box_line("💾 缓存", "token_caches/zhenxi_token_cache.json")
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
                "loginState": "未取得",
                "member": "-",
                "nickname": "-",
                "level": "-",
                "signMsg": "-",
                "points": "未知",
                "todayPoints": None,
                "todayCount": 0,
                "continuous": None,
                "weekDays": None,
                "signedToday": None,
                "details": [],
                "error": f"执行异常：{exc}",
            })
        hr()
        if idx < len(servers):
            log("   ⏳ 等待2秒后执行下一个账号...")
            time.sleep(2)

    print()
    for r in results:
        icon = "✅" if r.get("success") else "❌"
        log(f"{icon} 【账号 {r['index']} · {r['source']}】")
        log(f"   👤 [用户] {r.get('nickname') or '-'} ｜ 等级 {_level_text(r)}")
        log(f"   🔐 [登录] {_login_text(r)}")
        log(f"   📅 [签到] {r.get('signMsg') or '-'}")
        log(f"   💰 [积分] {r.get('points')} ｜ 今日 {_today_text(r)}")
        if not r.get("success"):
            log(f"   ⚠️ [失败] {r.get('error') or '未知原因'}")

    ok_count = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - ok_count

    print_point_summary(results)
    box_top(f"🏁 {APP_NAME} 执行汇总")
    box_line("📊 执行结果", f"成功 {ok_count} / 失败 {fail_count} / 共 {len(results)}")
    box_line("🔐 登录态", f"有效 {sum(1 for r in results if r.get('loginState') == '有效')} / 共 {len(results)}")
    box_bottom()

    content = build_notify(results)
    send_qinglong_notify(f"{APP_NAME}每日签到", content)
    send_pushplus(f"{APP_NAME}每日签到", content)
    send_qywx(f"{APP_NAME}每日签到", content)
    return results


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"❌ 程序异常: {exc}")
        traceback.print_exc()
