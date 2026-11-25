#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 洽洽会员俱乐部
# cron: 25 9,21 * * *

"""
洽洽会员俱乐部小程序（YYB Go 版）

功能：取码登录 → 查询积分 → 每日签到 → 浏览页面任务 → 领取奖励 → 抽奖活动查询
环境变量：
  YYB_SERVER        必填，YYB Go 服务地址@微信标识[#备注]，多账号换行
  QQFOOD_TENANT_ID  可选，租户 ID，默认 1
  QQHYJLB_NOTIFY    可选，0 关闭通知，默认 1
  PUSHPLUS_TOKEN    可选，PushPlus 推送
  PROXY_API         可选，品赞代理提取 API
  PROXY_TYPE        可选，http / socks5，默认 http

缓存：token_caches/qqhyjlb_token_cache.json，键为「地址|标识」，不设固定过期，开跑前只读校验，失效自动重登。
"""

import importlib.util
import json
import os
import random
import re
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

APP_NAME = "洽洽会员俱乐部"
APPID = "wxc72491b6cd007333"
TENANT_ID = os.getenv("QQFOOD_TENANT_ID", "1")
NOTIFY_ON = os.getenv("QQHYJLB_NOTIFY", "1").strip() != "0"

BASE_URL = "https://vip.qiaqiafood.com"
LOGIN_URL = f"{BASE_URL}/upms/wechat/login/code"
SIGN_URL = f"{BASE_URL}/vip/member/sign"
LIST_INTEGRAL_TASK_URL = f"{BASE_URL}/vip/member/listIntegralTask"
TASK_FINISHED_URL = f"{BASE_URL}/vip/member/taskFinished"
GET_VIP_EXT_INFO_URL = f"{BASE_URL}/vip/member/getVipExtInfo"
AWARD_SEARCH_URL = f"{BASE_URL}/award/center/search"
AWARD_RECEIVE_URL = f"{BASE_URL}/award/center/receive"
LOTTERY_LIST_URL = f"{BASE_URL}/activity/lottery/list"

UA_LIST = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
     "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
     "UnifiedPCWindowsWechat(0xf2541a1d) XWEB/19899"),
    ("Mozilla/5.0 (Linux; Android 10; Redmi K30 Pro) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/132.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.50.2701 MiniProgramEnv/android"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Mobile/15E148 MicroMessenger/8.0.49(0x18003121) NetType/WIFI Language/zh_CN miniProgram/wxc72491b6cd007333"),
]

PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()
PROXY_RETRY_TIMES = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

VISIT_PAGE_WAIT_SECONDS = 10
VISIT_PAGE_DAILY_LIMIT = 2

BOX_WIDTH = 48
BOX_INNER = 46

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "qqhyjlb_token_cache.json")

AUTH_WORDS = ("登录", "未登录", "授权", "失效", "过期", "token", "认证", "会话")
SIGNED_WORDS = ("已签", "重复", "今天已", "今日已", "已达", "上限")


# ==================== 日志 ====================
def _display_width(text: Any) -> int:
    width = 0
    for ch in str(text):
        code = ord(ch)
        if code in (0xFE0F, 0xFE0E, 0x200D):
            continue
        width += 2 if code > 0xFF else 1
    return width


def _pad(text: Any, width: int) -> str:
    text = str(text)
    while _display_width(text) > width:
        text = text[:-1]
    return text + " " * max(0, width - _display_width(text))


def box_top(title: str) -> None:
    print()
    print("╔" + "═" * BOX_WIDTH + "╗")
    print("║  " + _pad(title, BOX_INNER) + "║")


def box_line(label: str, value: Any) -> None:
    print("║  " + _pad(f"{label}: {value}", BOX_INNER) + "║")


def box_bottom() -> None:
    print("╚" + "═" * BOX_WIDTH + "╝")


def account_frame(index: int, total: int, title: str, source: str) -> None:
    print()
    print("┌" + "─" * BOX_WIDTH + "┐")
    print("│  " + _pad(f"🧩 账号 {index} / {total}　{title}", BOX_INNER) + "│")
    print("│  " + _pad(f"🔗 来源: {source}", BOX_INNER) + "│")
    print("└" + "─" * BOX_WIDTH + "┘")


def hr() -> None:
    print()
    print("-" * BOX_WIDTH)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ify(seconds: float) -> None:
    time.sleep(seconds)


def mask(value: Any) -> str:
    text = str(value or "")
    if not text:
        return "-"
    return text if len(text) <= 12 else f"{text[:6]}***{text[-4:]}"


def brief(value: Any, limit: int = 90) -> str:
    text = str(value or "").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def json_preview(data: Any, limit: int = 300) -> str:
    try:
        return brief(json.dumps(data, ensure_ascii=False), limit)
    except Exception:
        return brief(data, limit)


def to_number(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


# ==================== 账号解析 ====================
def parse_entry(raw_value: str) -> Tuple[str, str, str]:
    """地址@标识[#备注]"""
    value = str(raw_value or "").strip()
    if not value:
        return "", "", ""
    note = ""
    hash_pos = value.rfind("#")
    at_pos = value.rfind("@")
    if hash_pos != -1 and hash_pos > at_pos:
        note = value[hash_pos + 1:].strip()
        value = value[:hash_pos].strip()
    at_pos = value.rfind("@")
    if at_pos == -1:
        return "", "", note
    server = value[:at_pos].strip()
    if server.startswith("http://"):
        server = server[7:]
    elif server.startswith("https://"):
        server = server[8:]
    server = server.rstrip("/")
    ref = value[at_pos + 1:].strip()
    return server, ref, note


def cache_key(server: str, ref: str) -> str:
    return f"{server}|{ref}"


def legacy_ref_of(key: str) -> str:
    """旧键兼容：ref、地址@ref、地址@ref#备注"""
    value = str(key or "").strip()
    if not value or "|" in value:
        return ""
    body = value
    hash_pos = body.rfind("#")
    at_pos = body.rfind("@")
    if hash_pos != -1 and hash_pos > at_pos:
        body = body[:hash_pos].strip()
    at_pos = body.rfind("@")
    return body[at_pos + 1:].strip() if at_pos != -1 else body.strip()


# ==================== 缓存 ====================
def read_cache() -> Dict[str, Any]:
    try:
        if not os.path.exists(CACHE_FILE):
            return {}
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_cache(cache: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"   ⚠️ [缓存] 写入失败: {exc}")


def load_cache_entry(cache: Dict[str, Any], server: str, ref: str, raw: str) -> Optional[Dict[str, Any]]:
    ck = cache_key(server, ref)
    entry = cache.get(ck)
    if isinstance(entry, dict) and entry.get("token"):
        return entry
    candidates = []
    for key, value in list(cache.items()):
        if key == ck or not isinstance(value, dict) or not value.get("token"):
            continue
        if legacy_ref_of(key) == ref:
            candidates.append((str(value.get("updatedAt") or ""), key, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, _, best = candidates[0]
    cache[ck] = dict(best)
    for _, key, _ in candidates:
        cache.pop(key, None)
    cache.pop(str(raw).strip(), None)
    write_cache(cache)
    print("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」")
    return cache[ck]


def save_cache(server: str, ref: str, token: str, uid: str, nickname: str = "") -> None:
    cache = read_cache()
    cache[cache_key(server, ref)] = {
        "token": token,
        "uid": uid,
        "nickname": nickname or "",
        "updatedAt": now_text(),
    }
    write_cache(cache)


def drop_cache(server: str, ref: str) -> None:
    cache = read_cache()
    cache.pop(cache_key(server, ref), None)
    for key in list(cache.keys()):
        if key != cache_key(server, ref) and legacy_ref_of(key) == ref:
            cache.pop(key, None)
    write_cache(cache)


# ==================== 会话 / 代理 ====================
_session: Optional[requests.Session] = None


def direct_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.trust_env = False
    return _session


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


def build_proxy_dict(proxy_info: Dict[str, Any]) -> Dict[str, str]:
    host, port = proxy_info["host"], proxy_info["port"]
    username, password = proxy_info.get("username", ""), proxy_info.get("password", "")
    auth = f"{quote(username)}:{quote(password)}@" if username and password else ""
    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"
    return {"http": proxy_url, "https": proxy_url}


def get_valid_proxy(account: str) -> Tuple[Optional[Dict[str, str]], str]:
    if not PROXY_API:
        return None, ""
    print(f"   🌐 [代理] {account} 正在获取品赞代理")
    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=15)
            proxy_info = parse_proxy_response(response.text)
            if not proxy_info:
                print(f"   🌐 [代理] 第 {index} 次解析失败")
                continue
            proxies = build_proxy_dict(proxy_info)
            try:
                if requests.get("http://www.baidu.com", proxies=proxies, timeout=10).status_code == 200:
                    print(f"   🌐 [代理] 使用 {proxy_info['host']}:{proxy_info['port']}")
                    return proxies, proxy_info["host"]
            except Exception:
                pass
            print(f"   🌐 [代理] 第 {index} 次不可用")
        except Exception as exc:
            print(f"   🌐 [代理] 第 {index} 次异常: {brief(exc)}")
        if index < PROXY_RETRY_TIMES:
            ify(2)
    print("   🌐 [代理] 获取失败，使用直连")
    return None, ""


def request_with_proxy(method: str, url: str, *, proxies=None, server: str = "", **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            print(f"   🌐 [代理] {server} 请求失败: {brief(exc)}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("   🌐 [兜底] 切换直连重试")
    kwargs.setdefault("proxies", {"http": None, "https": None})
    return direct_session().request(method, url, **kwargs)


# ==================== YYB 取码 ====================
def get_wx_code(server: str, ref: str) -> Optional[str]:
    url = f"http://{server}/wxapp/getCode"
    print("   🧾 [授权] 请求 YYB Go 获取 code")
    try:
        resp = requests.post(url, json={"ref": ref, "app_id": APPID}, timeout=20,
                             proxies={"http": None, "https": None})
        data = resp.json()
    except Exception as exc:
        print(f"   ❌ [授权] 取码异常: {brief(exc)}")
        return None
    if to_number(data.get("code")) != 0:
        print(f"   ❌ [授权] 取码失败: {json_preview(data)}")
        return None
    payload = data.get("data") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    result = payload.get("result") or {}
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            result = {}
    code = result.get("code")
    if not code:
        print(f"   ❌ [授权] 未取到 code: {json_preview(data)}")
        return None
    print("   ✅ [授权] 取码成功")
    return code


# ==================== 业务客户端 ====================
def api_ok(resp: Dict[str, Any]) -> bool:
    return resp.get("success") is True or str(resp.get("status")) == "0"


def is_auth_fail(resp: Dict[str, Any], msg: str = "") -> bool:
    status = str(resp.get("status") or "")
    text = f"{msg} {resp.get('msg') or ''} {resp.get('message') or ''}"
    if status in ("-1", "-2", "401", "403"):
        return True
    return any(word in text for word in AUTH_WORDS)


class Qiaqia:
    def __init__(self, server: str, ref: str, proxies=None):
        self.server = server
        self.ref = ref
        self.proxies = proxies
        self.token = ""
        self.uid = ""
        self.nickname = ""

    def headers(self, with_token: bool = True) -> Dict[str, str]:
        headers = {
            "User-Agent": random.choice(UA_LIST),
            "Content-Type": "application/json",
            "Accept": "*/*",
            "xweb_xhr": "1",
            "Referer": f"https://servicewechat.com/{APPID}/520/page-frame.html",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if with_token and self.token:
            headers["Authorization"] = self.token
        return headers

    def post(self, url: str, body: Optional[Dict[str, Any]] = None, with_token: bool = True) -> Dict[str, Any]:
        payload = {"uid": self.uid, "tenantId": TENANT_ID}
        if body:
            payload.update(body)
        try:
            resp = request_with_proxy("POST", url, headers=self.headers(with_token), json=payload,
                                      proxies=self.proxies, server=self.server)
            return resp.json()
        except Exception as exc:
            return {"success": False, "status": "-9", "msg": f"请求异常 {brief(exc)}"}

    # ---- 登录 ----
    def login(self) -> bool:
        code = get_wx_code(self.server, self.ref)
        if not code:
            return False
        print("   🔐 [登录] 使用 code 换取 token")
        body = {"code": code, "tenantId": TENANT_ID, "appId": APPID, "componentAppId": APPID}
        try:
            resp = request_with_proxy("POST", LOGIN_URL, headers=self.headers(False), json=body,
                                      proxies=self.proxies, server=self.server)
            data = resp.json()
        except Exception as exc:
            print(f"   ❌ [登录] 请求异常: {brief(exc)}")
            return False
        inner = data.get("data")
        if not isinstance(inner, dict):
            print(f"   ❌ [登录] 响应异常: {json_preview(data)}")
            return False
        token = inner.get("token")
        uid = inner.get("loginId") or (inner.get("account") or {}).get("userId")
        if not token or not uid:
            print(f"   ❌ [登录] 未识别 token/uid: {json_preview(data)}")
            return False
        self.token, self.uid = str(token), str(uid)
        account = inner.get("account") or {}
        self.nickname = str(account.get("nickName") or account.get("nickname") or "").strip()
        print(f"   ✅ [登录] 登录成功 token: {mask(self.token)}")
        return True

    # ---- 只读校验 / 积分 ----
    def vip_info(self) -> Dict[str, Any]:
        return self.post(GET_VIP_EXT_INFO_URL)

    def read_points(self, info: Optional[Dict[str, Any]] = None) -> Tuple[Optional[int], str]:
        info = info if info is not None else self.vip_info()
        inner = info.get("data")
        if not isinstance(inner, dict):
            return None, ""
        point = to_number(inner.get("point"))
        self.nickname = self.nickname or str(inner.get("nickName") or "").strip()
        extra = f"等级 {inner.get('vipLevel', '?')}，连续签到 {inner.get('continuousSignDays', 0)} 天"
        return (point if point >= 0 else None), extra

    def verify(self) -> Tuple[bool, str]:
        info = self.vip_info()
        if api_ok(info) and isinstance(info.get("data"), dict):
            return True, ""
        return False, str(info.get("msg") or info.get("message") or json_preview(info, 60))

    # ---- 签到 ----
    def sign(self) -> Tuple[bool, str, Optional[int]]:
        resp = self.post(SIGN_URL, {"channel": ""})
        if api_ok(resp):
            inner = resp.get("data") or {}
            days = inner.get("continueDays", "?")
            value = to_number(inner.get("value"))
            return True, f"签到成功，连续 {days} 天" + (f"，+{value}积分" if value > 0 else ""), (value if value >= 0 else None)
        msg = str(resp.get("msg") or resp.get("message") or "签到失败")
        if any(word in msg for word in SIGNED_WORDS):
            return True, f"今日已签到（{msg}）", None
        if is_auth_fail(resp, msg):
            return False, msg, None
        return False, msg, None

    # ---- 浏览任务 ----
    def visit_pages(self) -> Tuple[str, int]:
        task_resp = self.post(LIST_INTEGRAL_TASK_URL)
        tasks = task_resp.get("data") or []
        task = next((item for item in tasks if item.get("taskType") == "VISIT_PAGE"), None)
        if not task:
            return "未找到浏览任务", 0
        finished = max(0, to_number(task.get("finishedCount")))
        limit_value = to_number(task.get("limitValue"))
        if limit_value <= 0:
            limit_value = VISIT_PAGE_DAILY_LIMIT
        remaining = limit_value - finished
        if remaining <= 0:
            return f"今日浏览已完成（{finished}/{limit_value}）", 0
        print(f"   👀 [浏览] 今日 {finished}/{limit_value}，还需 {remaining} 次")
        gained = 0
        parts: List[str] = []
        for i in range(1, remaining + 1):
            wait_time = random.randint(VISIT_PAGE_WAIT_SECONDS, VISIT_PAGE_WAIT_SECONDS + 5)
            print(f"   ⏳ [浏览] 第 {i} 次，模拟浏览 {wait_time}s")
            ify(wait_time)
            resp = self.post(TASK_FINISHED_URL, {"pointTaskType": "VISIT_PAGE"})
            if api_ok(resp):
                inner = resp.get("data") or {}
                value = to_number(inner.get("value")) if isinstance(inner, dict) else -1
                if value > 0:
                    gained += value
                parts.append(f"第{i}次+{value if value > 0 else 2}分")
                print(f"   ✅ [浏览] 第 {i} 次完成" + (f"，+{value}积分" if value > 0 else ""))
            else:
                msg = str(resp.get("msg") or resp.get("message") or "失败")
                parts.append(f"第{i}次失败({brief(msg, 20)})")
                print(f"   ❌ [浏览] 第 {i} 次: {brief(msg, 40)}")
            if i < remaining:
                ify(random.randint(3, 6))
        return "、".join(parts) if parts else "已完成", gained

    # ---- 奖励 ----
    def receive_awards(self) -> str:
        resp = self.post(AWARD_SEARCH_URL, {
            "page": 1, "pageSize": 10, "awardType": "", "awardStatus": "UNRECEIVED",
        })
        awards = resp.get("data") or []
        if not isinstance(awards, list) or not awards:
            return "暂无待领取奖励"
        received: List[str] = []
        for award in awards:
            award_id = award.get("id")
            title = str(award.get("awardTitle") or "未知奖励")
            if not award_id:
                continue
            recv = self.post(AWARD_RECEIVE_URL, {"id": str(award_id)})
            if api_ok(recv):
                received.append(title)
                print(f"   🎁 [奖励] 领取成功: {title}")
            else:
                print(f"   ⚠️ [奖励] {title}: {brief(recv.get('msg') or recv.get('message') or '领取失败', 40)}")
        return f"已领取 {len(received)} 项：{'、'.join(received)}" if received else "待领取奖励未领取成功"

    # ---- 抽奖 ----
    def lotteries(self) -> str:
        resp = self.post(LOTTERY_LIST_URL, {
            "page": 1, "pageSize": 3, "activityStatus": "UNDERWAY", "showPointsActivity": "T",
        })
        items = resp.get("data") or []
        if not isinstance(items, list) or not items:
            return "暂无进行中的抽奖"
        return f"进行中 {len(items)} 个抽奖活动"


def run_account(index: int, total: int, raw_entry: str) -> Dict[str, Any]:
    server, ref, note = parse_entry(raw_entry)
    result = {
        "index": index, "ref": ref or "-", "note": note, "success": False,
        "loginSource": "", "nickname": "", "pointsBefore": None, "pointsAfter": None,
        "delta": 0, "signMsg": "", "visitMsg": "", "awardMsg": "", "lotteryMsg": "",
        "error": "",
    }
    if not server or not ref:
        print(f"   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过: {brief(raw_entry, 60)}")
        result["error"] = "账号格式无效"
        return result

    title = f"标识 {ref}" + (f"（{note}）" if note else "")
    account_frame(index, total, title, str(raw_entry).strip())

    proxies, proxy_ip = get_valid_proxy(str(server))
    print(f"   🌐 [网络] {'代理 ' + proxy_ip if proxies else '直连'}")
    ify(random.randint(2, 6))

    client = Qiaqia(server, ref, proxies)
    cache = read_cache()
    cached = load_cache_entry(cache, server, ref, raw_entry)
    used_cache = False
    if cached and cached.get("token"):
        client.token = str(cached.get("token"))
        client.uid = str(cached.get("uid") or "")
        client.nickname = str(cached.get("nickname") or "")
        used_cache = True
        print(f"   💾 [缓存] 复用已保存 token: {mask(client.token)}")

    if used_cache:
        ok, reason = client.verify()
        if ok:
            print("   ✅ [校验] 缓存 token 有效，直接复用")
            result["loginSource"] = "缓存"
        else:
            print(f"   ⚠️ [校验] 缓存 token 失效（{brief(reason, 50)}），清除后重新登录")
            drop_cache(server, ref)
            client.token = client.uid = ""
            used_cache = False

    if not used_cache:
        if not client.login():
            result["error"] = "登录失败"
            print("   ❌ [完成] 登录失败")
            return result
        save_cache(server, ref, client.token, client.uid, client.nickname)
        ok, reason = client.verify()
        if not ok:
            print(f"   ⚠️ [校验] 新 token 校验失败（{brief(reason, 50)}），清除缓存后重登")
            drop_cache(server, ref)
            if not client.login():
                result["error"] = "重登失败"
                print("   ❌ [完成] 重登失败")
                return result
            save_cache(server, ref, client.token, client.uid, client.nickname)
            ok, reason = client.verify()
            if not ok:
                result["error"] = f"重登后校验仍失败（{brief(reason, 50)}）"
                print(f"   ❌ [完成] {result['error']}")
                return result
        result["loginSource"] = "新登录"
        print("   ✅ [校验] 登录凭证校验通过（积分接口）")

    result["nickname"] = client.nickname or "-"
    points, extra = client.read_points()
    result["pointsBefore"] = points
    print(f"   👤 [会员] {result['nickname']}")
    print(f"   💰 [积分] 当前 {points if points is not None else '未知'}" + (f"（{extra}）" if extra else ""))

    try:
        ok, msg, sign_value = client.sign()
        result["signMsg"] = msg
        quiet = any(word in msg for word in SIGNED_WORDS)
        print(f"   {'ℹ️' if quiet else ('✅' if ok else '❌')} [签到] {msg}")

        visit_msg, visit_gain = client.visit_pages()
        result["visitMsg"] = visit_msg

        result["awardMsg"] = client.receive_awards()
        print(f"   🎁 [奖励] {result['awardMsg']}")

        result["lotteryMsg"] = client.lotteries()
        print(f"   🎰 [抽奖] {result['lotteryMsg']}")

        ify(1)
        after, _ = client.read_points()
        result["pointsAfter"] = after
        if after is not None and points is not None:
            result["delta"] = after - points
        result["success"] = bool(ok)
        if not ok:
            result["error"] = msg
        print(f"   💰 [积分] {points if points is not None else '未知'} → {after if after is not None else '未知'}"
              + (f"（{result['delta']:+d}）" if points is not None and after is not None else ""))
        print(f"   {'✅' if result['success'] else '⚠️'} [完成] {'该账号任务执行完成' if result['success'] else '签到未成功'}")
    except Exception as exc:
        result["error"] = f"{exc}"
        print(f"   ❌ [异常] {brief(traceback.format_exc(), 120)}")
    return result


# ==================== 通知 ====================
def send_qinglong_notify(title: str, content: str) -> bool:
    try:
        import notify as ql_notify  # type: ignore
        if hasattr(ql_notify, "send"):
            ql_notify.send(title, content)
            return True
    except Exception:
        pass
    for path in ("/ql/data/scripts/notify.py", "/ql/scripts/notify.py",
                 "/ql/data/notify.py", os.path.join(SCRIPT_DIR, "notify.py")):
        if not os.path.exists(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location("ql_notify", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fn = getattr(mod, "send", None) or getattr(mod, "sendNotify", None)
            if fn:
                fn(title, content)
                return True
        except Exception:
            continue
    return False


def send_pushplus(title: str, content: str) -> bool:
    token = (os.getenv("PUSHPLUS_TOKEN") or os.getenv("PLUSPLUS_TOKEN")
             or os.getenv("PUSH_PLUS_TOKEN"))
    if not token:
        return False
    try:
        resp = requests.post("https://www.pushplus.plus/send",
                             json={"token": token, "title": title, "content": content, "template": "txt"},
                             timeout=15, proxies={"http": None, "https": None})
        return to_number(resp.json().get("code")) == 200
    except Exception:
        return False


def build_notify(results: List[Dict[str, Any]]) -> str:
    ok = sum(1 for r in results if r.get("success"))
    lines = [f"🥜 {APP_NAME} 任务结果", f"✅ {ok} 成功 / ❌ {len(results) - ok} 失败", now_text(), ""]
    for r in results:
        lines.append(f"{'✅' if r.get('success') else '❌'} 账号{r.get('index')} 标识 {r.get('ref')}")
        lines.append(f"  签到：{r.get('signMsg') or '-'}")
        lines.append(f"  浏览：{r.get('visitMsg') or '-'}")
        lines.append(f"  奖励：{r.get('awardMsg') or '-'}")
        lines.append(f"  抽奖：{r.get('lotteryMsg') or '-'}")
        lines.append(f"  积分：{r.get('pointsBefore')} → {r.get('pointsAfter')}")
        if not r.get("success"):
            lines.append(f"  失败：{brief(r.get('error') or '-', 80)}")
        lines.append("")
    return "\n".join(lines)


# ==================== 主流程 ====================
def main() -> None:
    entries = [line.strip() for line in os.getenv("YYB_SERVER", "").splitlines() if line.strip()]
    if not entries:
        print("❌ 未配置环境变量 YYB_SERVER")
        print("  格式：YYB Go 服务地址@微信账号标识[#备注]，多账号换行分隔")
        return

    valid, invalid = [], []
    for line in entries:
        server, ref, _ = parse_entry(line)
        (valid if server and ref else invalid).append(line)
    for line in invalid:
        print(f"   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过: {brief(line, 60)}")

    box_top(f"🥜 {APP_NAME} 每日任务")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(valid)} 个" + (f"（{len(invalid)} 行格式无效）" if invalid else ""))
    box_line("💾 缓存", os.path.basename(CACHE_FILE))
    box_line("🌐 网络", "代理" if PROXY_API else "直连")
    box_bottom()

    results: List[Dict[str, Any]] = []
    for index, entry in enumerate(valid, 1):
        try:
            results.append(run_account(index, len(valid), entry))
        except Exception as exc:
            print(f"   ❌ [执行] 账号 {index} 未捕获异常: {brief(exc, 80)}")
            _, ref, note = parse_entry(entry)
            results.append({"index": index, "ref": ref or "-", "note": note, "success": False,
                            "loginSource": "", "nickname": "", "pointsBefore": None, "pointsAfter": None,
                            "delta": 0, "signMsg": "", "visitMsg": "", "awardMsg": "", "lotteryMsg": "",
                            "error": str(exc)})
        hr()
        if index < len(valid):
            print("   ⏳ 等待2秒后执行下一个账号...")
            ify(2)

    print()
    for r in results:
        title = f"标识 {r.get('ref')}" + (f"（{r.get('note')}）" if r.get("note") else "")
        print(f"{'✅' if r.get('success') else '❌'} 【账号 {r.get('index')} · {title}】")
        print(f"   🔐 登录：{r.get('loginSource') or '-'}")
        print(f"   👤 会员：{r.get('nickname') or '-'}")
        print(f"   📅 签到：{r.get('signMsg') or '-'}")
        print(f"   👀 浏览：{r.get('visitMsg') or '-'}")
        print(f"   🎁 奖励：{r.get('awardMsg') or '-'}")
        print(f"   💰 积分：{r.get('pointsBefore')} → {r.get('pointsAfter')}"
              + (f"（{int(r.get('delta') or 0):+d}）" if r.get("pointsBefore") is not None and r.get("pointsAfter") is not None else ""))
        if not r.get("success"):
            print(f"   ⚠️ 失败：{brief(r.get('error') or '未知错误', 80)}")

    ok = sum(1 for r in results if r.get("success"))
    total_delta = sum(int(r.get("delta") or 0) for r in results)
    box_top(f"🏁 {APP_NAME} 执行汇总")
    box_line("📊 执行结果", f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}")
    box_line("💰 积分总变化", f"{total_delta:+d}")
    box_line("🕒 结束时间", now_text())
    box_bottom()

    if NOTIFY_ON:
        content = build_notify(results)
        title = f"🥜 {APP_NAME} 任务完成"
        print("   📮 [通知] 已通过青龙 notify 推送" if send_qinglong_notify(title, content)
              else "   ℹ️ [通知] 未找到青龙 notify 脚本")
        if send_pushplus(title, content):
            print("   📨 [通知] PushPlus 推送成功")
    else:
        print("   ℹ️ [通知] QQHYJLB_NOTIFY=0，已关闭通知")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"❌ [全局异常] {exc}")
        traceback.print_exc()
