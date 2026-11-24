#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 统一梦时代
# cron: 21 9,21 * * *

"""
统一梦时代小程序（YYB Go版）

功能：
  1. YYB_SERVER 获取微信 code
  2. 微盟 loginX 换 token + wid
  3. 每日签到
  4. 查询积分余额
  5. 查询签到积分明细
  6. 青龙 notify 推送

环境变量：
  YYB_SERVER    YYB Go 服务地址，格式：server@wxid，多账号换行分隔
  PROXY_API     品赞代理提取 API，可选
  PROXY_TYPE    http / socks5，默认 http
"""

import json
import os
import random
import time
from datetime import datetime
from urllib.parse import quote

import requests

try:
    import notify
except ImportError:
    notify = None

APP_NAME = "统一梦时代"
APPID = "wx532ecb3bdaaf92f9"

# 微盟 API
BASE_URL = (os.environ.get("TYMSD_BASE_URL") or "https://xapi.weimob.com").rstrip("/")
LOGIN_URL = f"{BASE_URL}/fe/mapi/user/loginX"
SIGN_IN_URL = f"{BASE_URL}/api3/onecrm/mactivity/sign/misc/sign/activity/core/c/sign"
NOTICE_URL = f"{BASE_URL}/api3/onecrm/mactivity/sign/misc/sign/activity/c/getNotice"
POINT_URL = f"{BASE_URL}/api3/onecrm/point/myPoint/get"
POINT_DETAIL_URL = f"{BASE_URL}/api3/onecrm/point/myPoint/queryTrans"

WEIMOB_CONFIG = {
    "bosId": 4020112618957,
    "cid": 176205957,
    "vid": "6013753979957",
    "merchantId": 2000020692957,
    "tcode": "weimob",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541923) XWEB/19823"
)

# YYB_SERVER 解析
SERVERS = []
env_YYB_SERVER = os.getenv("YYB_SERVER", "")
if env_YYB_SERVER:
    SERVERS = [line.strip() for line in env_YYB_SERVER.splitlines() if line.strip()]

if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER")
    print("格式：地址@微信账号标识，多账号换行分隔")
    exit(1)

print(f"✅ 读取到 {len(SERVERS)} 个 YYB Go 账号")

PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "tymsd_token_cache.json")


def read_token_cache() -> dict:
    try:
        if not os.path.exists(TOKEN_CACHE_FILE):
            return {}
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_token_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"  [缓存] 写入失败: {exc}")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def mask(value) -> str:
    value = str(value or "")
    if len(value) <= 4:
        return "***"
    if len(value) <= 10:
        return f"{value[:2]}***{value[-2:]}"
    return f"{value[:5]}***{value[-3:]}"


def json_preview(data, limit: int = 300) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)[:limit]
    except Exception:
        return str(data)[:limit]



# ============ 通用版式 ============
BOX_WIDTH = 48
BOX_INNER = BOX_WIDTH - 2
TITLE = "统一梦时代"
CACHE_NAME = "tymsd_token_cache.json"
NOTIFY_ENABLED = (os.environ.get("TYMSD_NOTIFY") or "1") != "0"


def display_width(text: str) -> int:
    width = 0
    for ch in str(text):
        code = ord(ch)
        if code in (0xfe0f, 0xfe0e, 0x200d):
            continue
        width += 2 if code > 0xff else 1
    return width


def pad_width(text: str, width: int) -> str:
    pad = width - display_width(text)
    return text + " " * pad if pad > 0 else str(text)


def box_top() -> str:
    return "╔" + "═" * BOX_INNER + "╗"


def box_line(content: str) -> str:
    return "║ " + pad_width(content, BOX_INNER - 1) + "║"


def box_bottom() -> str:
    return "╚" + "═" * BOX_INNER + "╝"


def hr() -> None:
    print("-" * 48)


def brief(text, limit: int = 60) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def account_frame(index: int, total: int, ref: str, note: str, raw: str) -> None:
    print("┌" + "─" * BOX_INNER + "┐")
    label = f"  🧩 账号 {index} / {total}　标识 {ref}" + (f"（{note}）" if note else "")
    print("│" + pad_width(label, BOX_INNER) + "│")
    print("│" + pad_width(f"  🔗 来源: {raw}", BOX_INNER) + "│")
    print("└" + "─" * BOX_INNER + "┘")


def cache_key(server: str, ref: str) -> str:
    return f"{server}|{ref}"


def is_auth_error(message) -> bool:
    text = str(message or "").lower()
    return any(kw in text for kw in ["token", "登录", "未登录", "授权", "失效", "过期", "unauthorized"])


# ============ YYB Server 交互 ============

def parse_yyb_go_entry(raw_value: str):
    value = (raw_value or "").strip()
    if not value:
        return None, None, ""
    body, note = value, ""
    if "#" in body:
        idx = body.rfind("#")
        body, note = body[:idx], body[idx + 1:].strip()
    if "@" not in body:
        print(f"  ❌ [配置] 格式应为 地址@标识[#备注]，当前值：{value}")
        return None, None, ""
    server, ref = body[:body.rfind("@")].strip(), body[body.rfind("@") + 1:].strip()
    server = server.replace("http://", "", 1) if server.startswith("http://") else server
    if server.startswith("https://"):
        server = server[8:]
    server = server.rstrip("/")
    if not server or not ref:
        return None, None, ""
    return server, ref, note


def get_wx_code(server_entry: str) -> str | None:
    parsed_server, ref, _note = parse_yyb_go_entry(server_entry)
    if not parsed_server or not ref:
        return None
    url = f"http://{parsed_server}/wxapp/getCode"
    print(f"  [授权] 请求YYB Go获取code")
    try:
        resp = requests.post(
            url,
            json={"ref": ref, "app_id": APPID},
            timeout=20,
            proxies={"http": None, "https": None},
        )
        data = resp.json()
        code = (((data.get("data") or {}).get("result") or {}).get("code"))
        if data.get("code") == 0 and code:
            print(f"  [授权] code获取成功")
            return code
        else:
            print(f"  [授权] code获取失败: {str(data)[:200]}")
            return None
    except Exception as exc:
        print(f"  [授权] code获取异常: {exc}")
        return None


# ============ 代理系统（可选） ============

_persistent_session = None

def get_persistent_session() -> requests.Session:
    global _persistent_session
    if _persistent_session is None:
        _persistent_session = requests.Session()
        _persistent_session.trust_env = False
    return _persistent_session


def direct_session() -> requests.Session:
    return get_persistent_session()


def parse_proxy_response(text) -> dict | None:
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
                    "host": str(host), "port": int(port),
                    "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                    "password": proxy_obj.get("pass") or proxy_obj.get("password") or "",
                }
    except Exception:
        pass
    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2:
            return {
                "host": parts[0], "port": int(parts[1]),
                "username": parts[2] if len(parts) > 2 else "",
                "password": parts[3] if len(parts) > 3 else "",
            }
    return None


def build_proxy_dict(proxy_info: dict | None) -> dict | None:
    if not proxy_info:
        return None
    host, port = proxy_info["host"], proxy_info["port"]
    username, password = proxy_info.get("username", ""), proxy_info.get("password", "")
    auth = f"{quote(username)}:{quote(password)}@" if username and password else ""
    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"
    print(f"  [代理] 生成 {scheme.upper()} 代理 {host}:{port}")
    return {"http": proxy_url, "https": proxy_url}


def get_valid_proxy(server: str) -> dict | None:
    if not PROXY_API:
        return None
    for i in range(1, PROXY_RETRY_TIMES + 1):
        try:
            resp = direct_session().get(PROXY_API, timeout=15)
            info = parse_proxy_response(resp.text)
            if not info:
                continue
            proxies = build_proxy_dict(info)
            try:
                r = requests.get("http://www.baidu.com", proxies=proxies, timeout=10)
                if r.status_code == 200:
                    return proxies
            except Exception:
                pass
        except Exception as exc:
            print(f"  [代理] 第{i}次获取异常: {exc}")
        if i < PROXY_RETRY_TIMES:
            sleep(2)
    print("  [代理] 获取失败，使用直连")
    return None


def request_with_proxy(method: str, url: str, *, proxies: dict | None = None, server: str = "", **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            print(f"  [代理] {server} 请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("  [兜底] 切换直连重试")
    return direct_session().request(method, url, **kwargs)


# ============ 业务逻辑 ============

def common_headers(token: str | None = None) -> dict:
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "Referer": f"https://servicewechat.com/{APPID}/106/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["X-WX-Token"] = token
    return headers


def extract_token(data) -> str | None:
    if not data or not isinstance(data, dict):
        return None
    candidates = [
        data.get("token"), data.get("accessToken"), data.get("access_token"), data.get("jwt"),
    ]
    inner = data.get("data")
    if isinstance(inner, dict):
        candidates.extend([
            inner.get("token"), inner.get("accessToken"), inner.get("access_token"), inner.get("jwt"),
        ])
    for item in candidates:
        if item and str(item) != "null":
            return str(item)
    return None


def login_by_code(server: str, code: str, proxies: dict | None) -> tuple[str | None, str | None, dict | None]:
    print("  [登录] 使用 code 换 token")
    payload = {
        "appid": APPID,
        "basicInfo": {
            "bosId": str(WEIMOB_CONFIG["bosId"]),
            "cid": str(WEIMOB_CONFIG["cid"]),
            "tcode": WEIMOB_CONFIG["tcode"],
            "vid": WEIMOB_CONFIG["vid"],
        },
        "env": "production",
        "extendInfo": {"source": 1},
        "is_pre_fetch_open": True,
        "parentVid": 0,
        "pid": str(WEIMOB_CONFIG["bosId"]),
        "storeId": "0",
        "code": code,
        "queryAuthConfig": True,
    }
    try:
        resp = request_with_proxy(
            "POST", LOGIN_URL,
            headers=common_headers(),
            json=payload,
            proxies=proxies, server=server,
        )
        data = resp.json()
        token = extract_token(data)
        if token:
            wid = None
            inner = data.get("data") or {}
            if isinstance(inner, dict):
                wid = inner.get("wid") or (inner.get("userInfo") or {}).get("wid")
            print(f"  [登录] token获取成功: {mask(token)}")
            return token, wid, data
        print(f"  [登录] 未识别token: {json_preview(data)}")
        return None, None, data
    except Exception as exc:
        print(f"  [登录] 异常: {exc}")
        return None, None, None


def build_base_request() -> dict:
    return {
        "appid": APPID,
        "basicInfo": {
            "vid": int(WEIMOB_CONFIG["vid"]),
            "vidType": 2,
            "bosId": WEIMOB_CONFIG["bosId"],
            "productId": 146,
            "productInstanceId": 3168798957,
            "productVersionId": "14026",
            "merchantId": WEIMOB_CONFIG["merchantId"],
            "tcode": WEIMOB_CONFIG["tcode"],
            "cid": WEIMOB_CONFIG["cid"],
        },
        "extendInfo": {
            "wxTemplateId": 8175,
            "analysis": [{"channelCode": "youshu", "channelStatus": True, "token": "bicbd2929b97584cb7"}],
            "bosTemplateId": 1000002224,
            "childTemplateIds": [
                {"customId": 90004, "version": "crm@0.1.93"},
                {"customId": 90002, "version": "ec@85.0"},
                {"customId": 90006, "version": "hudong@0.0.252"},
                {"customId": 90008, "version": "cms@0.0.531"},
                {"customId": 90070, "version": "1.0.21y"},
            ],
            "quickdeliver": {"enable": False},
            "youshu": {"enable": True, "token": "bicbd2929b97584cb7"},
            "source": 1,
            "channelsource": 5,
            "refer": "onecrm-signgift",
            "mpScene": 1005,
        },
        "queryParameter": None,
        "i18n": {"language": "zh", "timezone": "8"},
        "pid": str(WEIMOB_CONFIG["bosId"]),
        "storeId": "0",
    }


def api_post(server: str, url: str, token: str, proxies: dict | None, payload: dict) -> dict:
    resp = request_with_proxy(
        "POST", url,
        headers=common_headers(token),
        json=payload,
        proxies=proxies, server=server,
    )
    return resp.json()


def sign_in(server: str, token: str, wid, proxies: dict | None) -> dict:
    print("  [签到] 执行签到...")
    try:
        payload = build_base_request()
        payload["customInfo"] = {"source": 0, "wid": wid}
        data = api_post(server, SIGN_IN_URL, token, proxies, payload)

        if data.get("errcode") == "0" and data.get("data"):
            result = data["data"]
            rewards = []
            fr = result.get("fixedReward") or {}
            if (fr.get("points") or 0) > 0:
                rewards.append(f"{fr['points']}{result.get('pointName', '积分')}")
            if (fr.get("growth") or 0) > 0:
                rewards.append(f"{fr['growth']}{result.get('growthName', '成长值')}")
            if (fr.get("amount") or 0) > 0:
                rewards.append(f"{fr['amount']}元")
            er = result.get("extraReward") or {}
            if (er.get("points") or 0) > 0:
                rewards.append(f"额外{er['points']}{result.get('pointName', '积分')}")
            msg = "、".join(rewards) or "无"
            print(f"  [签到] 成功！奖励: {msg}")
            return {"success": True, "message": msg, "already_signed": False}

        err_msg = data.get("errmsg") or ""
        if any(kw in err_msg for kw in ["重复", "已签到", "今日"]):
            print(f"  [签到] 今日已签到: {err_msg}")
            return {"success": True, "message": err_msg, "already_signed": True}

        print(f"  [签到] 失败: {err_msg}")
        return {"success": False, "message": err_msg or "签到失败", "already_signed": False}
    except Exception as exc:
        print(f"  [签到] 异常: {exc}")
        return {"success": False, "message": str(exc), "already_signed": False}


def query_points(server: str, token: str, wid, proxies: dict | None) -> dict:
    print("  [积分] 查询积分...")
    try:
        payload = build_base_request()
        payload["customInfo"] = {"source": 0, "wid": wid}
        payload["request"] = {"isNeedRecordDisplay": True, "isQueryAllAccount": True}
        data = api_post(server, POINT_URL, token, proxies, payload)

        if data.get("errcode") == "0" and data.get("data"):
            d = data["data"]
            available = d.get("availablePoint", 0)
            total = d.get("totalPoint", 0)
            print(f"  [积分] 可用: {available} / 总计: {total}")
            return {"success": True, "available": available, "total": total}

        print(f"  [积分] 查询失败: {data.get('errmsg', '')}")
        return {"success": False, "available": 0, "total": 0}
    except Exception as exc:
        print(f"  [积分] 异常: {exc}")
        return {"success": False, "available": 0, "total": 0}


def query_point_details(server: str, token: str, wid, proxies: dict | None) -> dict:
    print("  [明细] 查询积分明细...")
    try:
        payload = build_base_request()
        payload["customInfo"] = {"source": 0, "wid": wid}
        payload["queryParameter"] = {"modifyType": 1}
        payload["pageNum"] = 1
        payload["pageSize"] = 10
        data = api_post(server, POINT_DETAIL_URL, token, proxies, payload)

        if data.get("errcode") == "0" and data.get("data"):
            records = (data.get("data") or {}).get("pageList") or []
            today_str = datetime.now().strftime("%Y-%m-%d")
            today_records = [
                r for r in records
                if r.get("createTime", "").startswith(today_str)
                and (r.get("changeType") == "签到有礼" or r.get("remark") == "签到赠送")
            ]
            if today_records:
                today_pts = sum(int(r.get("point", 0)) for r in today_records)
                last_time = today_records[0].get("createTime", "")
                msg = f"今日签到{len(today_records)}次，获得{today_pts}积分，最后: {last_time}"
            else:
                msg = "今日暂无签到记录"
            print(f"  [明细] {msg}")
            return {"success": True, "message": msg}

        print(f"  [明细] 查询失败")
        return {"success": False, "message": "明细查询失败"}
    except Exception as exc:
        print(f"  [明细] 异常: {exc}")
        return {"success": False, "message": "明细查询异常"}


def run_account(index: int, total: int, server_entry: str) -> dict:
    parsed_server, wxid, note = parse_yyb_go_entry(server_entry)
    result = {
        "index": index,
        "wxid": mask(wxid or ""),
        "success": False,
        "proxy_status": "未使用代理",
        "login_source": "-",
        "sign_msg": "-",
        "points_msg": "-",
        "details_msg": "-",
        "error": "",
        "lines": [],
    }
    if not parsed_server or not wxid:
        result["error"] = "YYB_SERVER 格式无效"
        print("  ❌ [配置] YYB_SERVER 格式无效")
        hr()
        return result

    account_frame(index, total, mask(wxid), note, server_entry)

    proxies = get_valid_proxy(str(parsed_server))
    result["proxy_status"] = "使用专属代理" if proxies else "使用直连"

    ck = cache_key(parsed_server, wxid)
    cache = read_token_cache()
    # 旧键迁移（ref-only）
    if not cache.get(ck):
        for old_key in (wxid, server_entry, f"{parsed_server}@{wxid}"):
            if cache.get(old_key):
                cache[ck] = cache[old_key]
                cache.pop(old_key, None)
                write_token_cache(cache)
                break

    token = None
    wid = None
    login_source = ""

    entry = cache.get(ck) or {}
    if entry.get("token"):
        token, wid = entry["token"], entry.get("wid")
        print("   💾 [缓存] 发现已保存的 token，先做有效性校验")
        pts = query_points(parsed_server, token, wid, proxies)
        if pts.get("success"):
            login_source = "缓存"
            print("   ✅ [缓存] 校验通过，直接复用")
        else:
            print("   🔄 [缓存] 校验失败，清理缓存后重新登录")
            cache.pop(ck, None)
            write_token_cache(cache)
            token = wid = None

    if not token:
        delay = random.randint(2, 6)
        sleep(delay)
        code = get_wx_code(server_entry)
        if not code:
            result["error"] = "获取 code 失败"
            print("   ❌ [登录] 获取 code 失败")
            hr()
            return result
        token, wid, raw = login_by_code(parsed_server, code, proxies)
        if not token:
            result["error"] = f"登录失败: {json_preview(raw)}"
            print("   ❌ [登录] 登录失败")
            hr()
            return result
        login_source = "新登录"
        cache = read_token_cache()
        cache[ck] = {"token": token, "wid": wid, "updatedAt": now_text()}
        write_token_cache(cache)
        print("   ✅ [登录] 成功（已写入缓存）")

    result["login_source"] = login_source

    # 签到（失败且像鉴权问题 → 清缓存重登一次）
    sign_result = sign_in(parsed_server, token, wid, proxies)
    if not sign_result["success"] and not sign_result["already_signed"] and is_auth_error(sign_result.get("message")):
        print("   🔄 [重试] 签到提示登录态失效，清理缓存重登一次")
        cache = read_token_cache()
        cache.pop(ck, None)
        write_token_cache(cache)
        code = get_wx_code(server_entry)
        if code:
            token, wid, raw = login_by_code(parsed_server, code, proxies)
            if token:
                cache = read_token_cache()
                cache[ck] = {"token": token, "wid": wid, "updatedAt": now_text()}
                write_token_cache(cache)
                login_source = "重新登录"
                result["login_source"] = login_source
                print("   ✅ [登录] 重登成功，重跑签到")
                sign_result = sign_in(parsed_server, token, wid, proxies)

    if sign_result["already_signed"]:
        result["sign_msg"] = f"今日已签到（{brief(sign_result['message'], 40)}）"
    elif sign_result["success"]:
        result["sign_msg"] = f"签到成功 +{brief(sign_result['message'], 30)}"
    else:
        result["sign_msg"] = f"失败（{brief(sign_result['message'], 40)}）"

    # 积分（签到前后对比）
    pts_after = query_points(parsed_server, token, wid, proxies)
    if pts_after.get("success"):
        result["points_msg"] = f"可用 {pts_after['available']} / 总计 {pts_after['total']}"
    else:
        result["points_msg"] = "积分查询失败"

    # 明细
    det = query_point_details(parsed_server, token, wid, proxies)
    result["details_msg"] = det.get("message", "-")

    ok = bool(sign_result["success"] or sign_result["already_signed"]) and pts_after.get("success")
    result["success"] = ok
    if not ok and not result["error"]:
        result["error"] = result["sign_msg"] if not pts_after.get("success") else "任务未全部成功"

    result["lines"] = [
        f"👤 标识：{mask(wxid)}（登录态来源：{login_source}）",
        f"📅 签到：{result['sign_msg']}",
        f"💰 积分：{result['points_msg']}",
        f"📋 明细：{result['details_msg']}",
    ]
    print(f"   ℹ️ [积分] {result['points_msg']}")
    print(f"   ℹ️ [明细] {result['details_msg']}")
    hr()
    return result


def build_notify(results: list) -> str:
    ok = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok
    lines = [f"统一梦时代签到结果", "—" * 30]
    lines.append(f"✅ {ok}成功 / ❌ {fail}失败")
    lines.append(f"🕒 {now_text()}")
    lines.append("")
    for i, r in enumerate(results, 1):
        icon = "✅" if r.get("success") else "❌"
        lines.append(f"{icon} 账号{i} ({r.get('wxid', '-')})")
        lines.append(f"  签到: {r['sign_msg']}")
        lines.append(f"  积分: {r['points_msg']}")
        lines.append(f"  明细: {r['details_msg']}")
        if not r.get("success"):
            lines.append(f"  错误: {r.get('error', '')[:80]}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    print(box_top())
    print(box_line(f"💠 {TITLE} 每日任务"))
    print(box_line(f"🕒 启动时间: {now_text()}"))
    print(box_line(f"🔢 账号数量: {len(SERVERS)} 个"))
    print(box_line(f"💾 缓存: {CACHE_NAME}"))
    print(box_line("🌐 网络: 直连"))
    print(box_bottom())

    results = []
    for idx, server_entry in enumerate(SERVERS):
        try:
            r = run_account(idx + 1, len(SERVERS), server_entry)
            results.append(r)
        except Exception as exc:
            _, wxid, _note = parse_yyb_go_entry(server_entry)
            print(f"   ❌ [异常] 账号{idx + 1} 执行异常: {brief(exc, 80)}")
            hr()
            results.append({
                "index": idx + 1,
                "wxid": mask(wxid or ""),
                "success": False,
                "error": str(exc),
                "proxy_status": "-",
                "login_source": "-",
                "sign_msg": "-",
                "points_msg": "-",
                "details_msg": "-",
                "lines": [f"❌ 原因：{brief(exc, 80)}"],
            })
        if idx < len(SERVERS) - 1:
            sleep(2)

    ok = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok

    print()
    for r in results:
        icon = "✅" if r.get("success") else "❌"
        note_text = ""
        print(f"{icon} 【账号 {r.get('index', '-')}{note_text}】")
        for line in r.get("lines") or [f"❌ 原因：{r.get('error', '未知错误')}"]:
            print(f"   {line}")
        print("")

    print(box_top())
    print(box_line(f"📊 汇总: 成功 {ok} / {len(results)}"))
    print(box_line(f"❌ 失败: {fail}"))
    print(box_line(f"🕒 结束时间: {now_text()}"))
    print(box_bottom())

    if notify and NOTIFY_ENABLED:
        notify.send(APP_NAME, build_notify(results))
    elif notify and not NOTIFY_ENABLED:
        print("ℹ️ TYMSD_NOTIFY=0，已关闭通知")


if __name__ == "__main__":
    main()
