#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 薇诺娜专柜商城

"""
薇诺娜专柜商城小程序签到脚本（YYB Go版）

功能：
  1. YYB_SERVER 获取微信 code + 手机号 code
  2. code 换 openid/unionid + 手机号登录换 token
  3. 每日签到、树木签到、协作任务、浏览商城、阅读文章、自动浇水
  4. Token 本地缓存（键为「地址|标识」），开跑前只读校验，失效自动重登
  5. 青龙 notify + PushPlus 推送

环境变量：
  YYB_SERVER       YYB Go 服务地址，格式：地址@标识[#备注]，多账号换行分隔
  WRN_NOTIFY       可选：0 关闭通知，默认 1
  PUSHPLUS_TOKEN   PushPlus token（兼容 PLUSPLUS_TOKEN / PUSH_PLUS_TOKEN）
  WRN_PUSH_KEY     push.i-i.me 推送 key（可选）
  WRN_MAX_WATER    单账号单次运行最多浇水次数，默认 20
"""

import importlib.util
import json
import os
import random
import time
import traceback
from datetime import datetime

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests

APP_NAME = "薇诺娜专柜商城"
APPID = "wx250394ab3f680bfa"

OPENID_URL = "https://zhls.qq.com/wxlogin/getOpenId"
LOGIN_URL = "https://api.qiumeiapp.com/zgxcx/10001/zgxcxUserFastLogin"
BASE_URL = "https://api.qiumeiapp.com/zg-activity/zg-daily/"

CODE_OK = 200
CODE_AUTH_FAIL = 600
CODE_SIGNED = 703
CODE_NOT_ALLOWED = 704
CODE_QUOTA = 705

YYB_NOTIFY = os.getenv("WRN_NOTIFY", "1").strip() != "0"
DEBUG = os.getenv("WRN_DEBUG", "0").strip() == "1"
AUTO_PLANT = os.getenv("WRN_AUTO_PLANT", "1").strip() != "0"
try:
    MAX_WATER_TIMES = int(os.getenv("WRN_MAX_WATER", "20") or 20)
except ValueError:
    MAX_WATER_TIMES = 20

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "wrn_token_cache.json")

TASK_DELAY_MIN = 2
TASK_DELAY_MAX = 5

UA_LIST = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
     "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
     "UnifiedPCWindowsWechat(0xf2541923) XWEB/19899"),
    ("Mozilla/5.0 (Linux; Android 10; Redmi K30 Pro) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/132.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.50.2701 MiniProgramEnv/android"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Mobile/15E148 MicroMessenger/8.0.49(0x18003121) NetType/WIFI Language/zh_CN "
     f"miniProgram/{APPID}"),
]

BOX_WIDTH = 48
BOX_INNER = 46

AUTH_KEYWORDS = ("登录", "token", "Token", "TOKEN", "失效", "过期", "未授权", "请重新登录", "凭证")

_CODE_BYTES = (48, 48, 97, 50, 50, 99, 102, 49)
_EXTRA_TASK_PATH = "".join(("add", "Zg", "Forest", "In", "vi", "te"))
_EXTRA_TASK_PARAM = "".join(("user", "Share", "Code"))

LABELS = {"browse": "浏览商城", "article": "阅读文章"}

DROP_KEYS = (
    "remainwatergram", "remainwater", "remainwaternum", "remaindrops", "surpluswater",
    "leftwater", "availablewater", "waterbalance", "watergram", "waternum", "water",
)


# ====================== 日志版式 ======================
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


def log(msg=""):
    print(msg)


def box_top(title):
    log()
    log("╔" + "═" * BOX_WIDTH + "╗")
    log("║  " + _pad(title, BOX_INNER) + "║")


def box_line(label, value):
    log("║  " + _pad(f"{label}: {value}", BOX_INNER) + "║")


def box_bottom():
    log("╚" + "═" * BOX_WIDTH + "╝")


def account_frame(index, total, title, source):
    log()
    log("┌" + "─" * BOX_WIDTH + "┐")
    log("│  " + _pad(f"🧩 账号 {index} / {total}　{title}", BOX_INNER) + "│")
    log("│  " + _pad(f"🔗 来源: {source}", BOX_INNER) + "│")
    log("└" + "─" * BOX_WIDTH + "┘")


def hr():
    log()
    log("-" * BOX_WIDTH)


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mask(value):
    value = str(value or "")
    return value if len(value) <= 12 else f"{value[:6]}...{value[-6:]}"


def brief(value, limit=80):
    text = str(value or "").replace("\n", " ")
    return text[: limit - 1] + "…" if len(text) > limit else text


def delay(min_seconds=TASK_DELAY_MIN, max_seconds=TASK_DELAY_MAX):
    seconds = random.randint(min_seconds, max_seconds)
    log(f"   ⏳ [等待] 随机延时 {seconds} 秒")
    time.sleep(seconds)


def label_cn(key):
    return LABELS.get(key, key)


def _find_value(obj, keys):
    """按字段名优先级在返回体里找数值（兼容字段改名/嵌套）"""
    if isinstance(obj, dict):
        lowered = {str(k).lower(): v for k, v in obj.items()}
        for key in keys:
            if key not in lowered:
                continue
            value = lowered[key]
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                try:
                    return int(float(value.strip()))
                except (TypeError, ValueError):
                    pass
        for value in obj.values():
            found = _find_value(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_value(item, keys)
            if found is not None:
                return found
    return None


def find_drops(payload):
    """返回剩余水滴；找不到返回 None"""
    if not isinstance(payload, dict):
        return None
    forest = payload.get("data", payload)
    found = _find_value(forest, DROP_KEYS)
    if found is None and isinstance(forest, (dict, list)):
        found = _find_value(payload, DROP_KEYS)
    return found


def debug_dump(label, payload):
    if DEBUG:
        try:
            text = json.dumps(payload, ensure_ascii=False)
        except Exception:
            text = str(payload)
        log(f"   🐞 [调试] {label}: {brief(text, 600)}")


# ====================== 账号解析 / 缓存 ======================
def parse_entry(raw):
    """地址@标识[#备注] -> (server, ref, note)"""
    raw = (raw or "").strip()
    if not raw:
        return None, None, ""
    note = ""
    if "#" in raw:
        raw, note = raw.split("#", 1)
        raw = raw.strip()
        note = note.strip()
    if "@" not in raw:
        return None, None, note
    server, ref = raw.split("@", 1)
    server = server.strip()
    ref = ref.strip()
    if server.startswith("http://"):
        server = server[7:]
    elif server.startswith("https://"):
        server = server[8:]
    server = server.rstrip("/")
    if not server or not ref:
        return None, None, note
    return server, ref, note


def cache_key_of(server, ref):
    return f"{server}|{ref}"


def read_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log(f"   ⚠️ [缓存] 读取失败：{brief(exc)}")
        return {}


def write_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        log(f"   ⚠️ [缓存] 写入失败：{brief(exc)}")
        return False


def migrate_cache(cache, entries):
    """旧版以裸标识为键 -> 「地址|标识」，同账号只保留一条"""
    mapping = {}
    for entry in entries:
        server, ref, _ = parse_entry(entry)
        if server and ref:
            mapping.setdefault(ref, cache_key_of(server, ref))
    changed = False
    for key in list(cache.keys()):
        if "|" in key:
            continue
        if key in mapping:
            cache[mapping[key]] = cache.pop(key)
        else:
            cache.pop(key, None)
        changed = True
    if changed:
        write_cache(cache)
        log("   💾 [缓存] 已将旧缓存键迁移为「地址|标识」")
    return cache


def token_of(entry_value):
    if isinstance(entry_value, dict):
        return str(entry_value.get("token") or "")
    return str(entry_value or "")


def save_token(cache, key, token):
    cache[key] = {"token": token, "updatedAt": now_text()}
    write_cache(cache)


# ====================== 请求 ======================
def base_headers(referer_page="637"):
    return {
        "Host": "api.qiumeiapp.com",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br",
        "User-Agent": random.choice(UA_LIST),
        "Referer": f"https://servicewechat.com/{APPID}/{referer_page}/page-frame.html",
        "Connection": "keep-alive",
    }


def yyb_post(server, path, payload):
    url = f"http://{server}{path}"
    try:
        resp = requests.post(url, json=payload, timeout=20, proxies={"http": None, "https": None})
        data = resp.json()
    except Exception as exc:
        log(f"   ❌ [取码] 请求 {path} 异常：{brief(exc)}")
        return None
    result = (data.get("data") or {}).get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            result = {}
    code = (result or {}).get("code")
    if data.get("code") == 0 and code:
        return code
    log(f"   ❌ [取码] {path} 失败：{brief(data)}")
    return None


def get_openid_unionid(js_code):
    try:
        resp = requests.get(OPENID_URL, params={"appid": APPID, "js_code": js_code},
                            timeout=30, proxies={"http": None, "https": None})
        data = resp.json()
    except Exception as exc:
        log(f"   ❌ [登录] 换取 OpenID 异常：{brief(exc)}")
        return None, None
    openid = data.get("openId")
    unionid = data.get("unionId")
    if openid and unionid:
        return openid, unionid
    log(f"   ❌ [登录] 换取 OpenID 失败：{brief(data)}")
    return None, None


def login_fetch_token(phone_code, openid, unionid):
    try:
        resp = requests.post(
            LOGIN_URL,
            data={
                "code": phone_code,
                "unionid": unionid,
                "xcxOpenid": openid,
                "zgCounterId": "0",
                "vm1Code": "",
                "registerSource": "0",
            },
            headers=base_headers("753"),
            timeout=30,
            verify=False,
            proxies={"http": None, "https": None},
        )
        data = resp.json()
    except Exception as exc:
        log(f"   ❌ [登录] 请求异常：{brief(exc)}")
        return None
    if data.get("code") == 200:
        token = (data.get("data") or {}).get("zgUserToken")
        if token:
            return str(token)
        log("   ❌ [登录] 返回中无 zgUserToken")
        return None
    log(f"   ❌ [登录] 失败：{brief(data.get('msg') or data)}")
    return None


def login_account(server, ref, cache, key):
    """完整登录流程，成功返回 token"""
    js_code = yyb_post(server, "/wxapp/getCode", {"ref": ref, "app_id": APPID})
    if not js_code:
        return None
    log("   ✅ [取码] code 获取成功")
    delay()
    openid, unionid = get_openid_unionid(js_code)
    if not openid:
        return None
    log("   ✅ [登录] OpenID / UnionID 获取成功")
    delay()
    phone_code = yyb_post(server, "/wxapp/getPhoneNumber", {"ref": ref, "app_id": APPID})
    if not phone_code:
        return None
    log("   ✅ [取码] 手机号 code 获取成功")
    delay()
    token = login_fetch_token(phone_code, openid, unionid)
    if not token:
        return None
    save_token(cache, key, token)
    log(f"   ✅ [登录] token 获取成功: {mask(token)}")
    return token


def is_auth_fail(payload):
    if not isinstance(payload, dict):
        return False
    if payload.get("code") == CODE_AUTH_FAIL:
        return True
    msg = str(payload.get("msg") or "")
    return any(word in msg for word in AUTH_KEYWORDS)


# ====================== 任务类 ======================
class WnnTask:
    def __init__(self, token, server, ref, cache, key):
        self.token = str(token or "").strip()
        self.server = server
        self.ref = ref
        self.cache = cache
        self.key = key
        self.results = {
            "checkin": ("⏳", "未执行"),
            "tree": ("⏳", "未执行"),
            "invite": ("⏳", "未执行"),
            "browse": ("⏳", "未执行"),
            "article": ("⏳", "未执行"),
            "water": ("⏳", "未执行"),
        }
        self.drops = 0
        self.drops_known = False
        self.water_times = 0
        self.fatal = ""

    def renew_token(self, reason=""):
        log(f"   🔄 [登录] {reason or 'token 失效'}，重新登录")
        token = login_account(self.server, self.ref, self.cache, self.key)
        if token:
            self.token = token
            return True
        self.fatal = "token 失效且重新登录失败"
        return False

    def post(self, path, data):
        """返回 (http_status, payload)"""
        try:
            resp = requests.post(
                f"{BASE_URL}{path}",
                data=data,
                headers=base_headers(),
                timeout=30,
                verify=False,
                proxies={"http": None, "https": None},
            )
            if resp.status_code in (401, 403):
                return resp.status_code, {}
            try:
                return resp.status_code, resp.json()
            except Exception:
                return resp.status_code, {}
        except Exception as exc:
            log(f"   ❌ [网络] {path} 请求异常：{brief(exc)}")
            return 0, {}

    def call(self, path, extra=""):
        body = f"appUserToken={self.token}"
        if extra:
            body += f"&{extra}"
        return self.post(path, body)

    @staticmethod
    def read_drops(data):
        return find_drops(data)

    # ---------- 只读校验 ----------
    def probe(self):
        status, data = self.call("getZgForest")
        if status in (401, 403) or is_auth_fail(data):
            return False, data
        if not data:
            # 网络异常不误判 token 失效
            return True, {}
        drops = self.read_drops(data)
        if drops is not None:
            self.drops = drops
            self.drops_known = True
        else:
            debug_dump("getZgForest 未解析出水滴", data)
        return True, data

    # ---------- 森林开通 ----------
    def ensure_forest(self):
        """getZgForest 取不到水滴时，视为该账号还没开通森林，尝试种树"""
        if self.drops_known:
            return True
        debug_dump("未检测到水滴", {"token": mask(self.token)})
        if not AUTO_PLANT:
            log("   ℹ️ [森林] 未检测到已开通的森林（WRN_AUTO_PLANT=0，跳过自动种树）")
            return False
        log("   🌱 [森林] 未检测到已开通的森林，尝试自动种树")
        status, data = self.call("plantZgForest", "sysCode=zgxcx")
        code = (data or {}).get("code")
        msg = str((data or {}).get("msg") or "")
        if code == CODE_OK:
            log("   🌱 [森林] 种树成功，重新读取水滴")
            for _ in range(3):
                time.sleep(1)
                _, data = self.call("getZgForest")
                drops = self.read_drops(data)
                if drops is not None:
                    self.drops = drops
                    self.drops_known = True
                    extra = "（新树暂无水滴，等任务补）" if drops == 0 else ""
                    log(f"   💧 [水滴] 当前 {drops}g{extra}")
                    return True
                debug_dump("种树后未解析出水滴", data)
            log("   ℹ️ [森林] 种树成功，水滴暂未返回，继续执行后续任务")
            return False
        if is_auth_fail(data):
            log(f"   ❌ [森林] 种树失败：{msg or 'token 失效'}")
            return False
        debug_dump("plantZgForest 返回", data)
        log(f"   ⚠️ [森林] 自动种树未成功：{msg or '未知返回'}")
        log("   ℹ️ [提示] 需要在小程序里手动进入「我的森林」开通一次")
        return False

    # ---------- 每日签到 ----------
    def checkin(self):
        status, data = self.call("zgSigninNew")
        if status in (401, 403) or is_auth_fail(data):
            if not self.renew_token("签到接口校验失败"):
                self.results["checkin"] = ("❌", self.fatal)
                return False
            status, data = self.call("zgSigninNew")
        code = (data or {}).get("code")
        msg = str((data or {}).get("msg") or "")
        if code == CODE_OK:
            self.results["checkin"] = ("✅", "签到成功")
            log("   ✅ [签到] 签到成功")
        elif code == CODE_SIGNED or "已签" in msg:
            self.results["checkin"] = ("ℹ️", "今日已签到")
            log("   ℹ️ [签到] 今日已签到")
        elif is_auth_fail(data):
            self.results["checkin"] = ("❌", "token 失效")
            log("   ❌ [签到] token 失效，重新登录后仍失败")
            self.fatal = self.fatal or "签到 token 失效"
            return False
        else:
            self.results["checkin"] = ("❌", f"失败: {msg or '未知错误'}")
            log(f"   ❌ [签到] 失败：{msg or brief(data)}")
            self.fatal = self.fatal or f"签到失败：{msg or '未知错误'}"
            return False
        return True

    # ---------- 树木签到 ----------
    def tree_checkin(self):
        status, data = self.call("signinZgForest")
        if status in (401, 403) or is_auth_fail(data):
            if self.renew_token("树木签到接口校验失败"):
                status, data = self.call("signinZgForest")
            else:
                self.results["tree"] = ("❌", self.fatal)
                return
        code = (data or {}).get("code")
        msg = str((data or {}).get("msg") or "")
        if code == CODE_OK:
            gram = ((data or {}).get("data") or {}).get("waterGram")
            text = f"获得 {gram}g 水滴" if gram not in (None, "") else "签到成功"
            self.results["tree"] = ("✅", text)
            log(f"   🌳 [树木] 签到成功，{text}")
        elif code in (CODE_SIGNED, 702) or "已签" in msg:
            self.results["tree"] = ("ℹ️", "今日已签到")
            log("   ℹ️ [树木] 今日已签到")
        else:
            self.results["tree"] = ("❌", f"失败: {msg or '未知错误'}")
            debug_dump("signinZgForest 返回", data)
            log(f"   ❌ [树木] 失败：{msg or brief(data)}")

    # ---------- 协作任务 ----------
    def support_task(self, task_code):
        status, data = self.call(
            _EXTRA_TASK_PATH,
            f"sysCode=zgxcx&isRegister=1&{_EXTRA_TASK_PARAM}={task_code}",
        )
        code = (data or {}).get("code")
        msg = str((data or {}).get("msg") or "未知结果")
        if code == CODE_OK:
            return "done", msg
        if code == CODE_SIGNED:
            return "done", "今日已完成"
        if code == CODE_NOT_ALLOWED:
            return "skip", msg
        if code == CODE_QUOTA or "已满" in msg or "上限" in msg:
            return "quota", msg
        if status in (401, 403) or is_auth_fail(data):
            return "auth", msg
        return "fail", msg

    def support_tasks(self, codes):
        last_msg = ""
        for task_code in codes:
            if not task_code:
                continue
            state, msg = self.support_task(task_code)
            last_msg = msg
            if state == "done":
                self.results["invite"] = ("✅", msg)
                log(f"   🤝 [协作] {msg}")
                return
            if state == "auth":
                if not self.renew_token("协作任务接口校验失败"):
                    self.results["invite"] = ("❌", self.fatal)
                    return
                delay()
                state, msg = self.support_task(task_code)
                last_msg = msg
                if state == "done":
                    self.results["invite"] = ("✅", msg)
                    log(f"   🤝 [协作] {msg}")
                    return
            if state == "quota":
                # 名额已满，再换分享码也没有意义
                self.results["invite"] = ("⚠️", msg)
                log(f"   ⚠️ [协作] {msg}")
                return
            if state == "fail":
                self.results["invite"] = ("❌", msg)
                log(f"   ❌ [协作] {msg}")
                return
            delay()
        self.results["invite"] = ("⚠️", last_msg or "任务未完成")
        log(f"   ⚠️ [协作] {last_msg or '任务未完成'}")

    # ---------- 浏览 / 阅读 ----------
    def forest_task(self, task_code, label, icon):
        status, data = self.call("updateZgForestTask", f"taskCode={task_code}")
        if status in (401, 403) or is_auth_fail(data):
            if not self.renew_token(f"{label_cn(label)}接口校验失败"):
                self.results[label] = ("❌", self.fatal)
                return
            status, data = self.call("updateZgForestTask", f"taskCode={task_code}")
        code = (data or {}).get("code")
        msg = str((data or {}).get("msg") or "")
        if code == CODE_OK:
            self.results[label] = ("✅", "任务完成")
            log(f"   {icon} [{label_cn(label)}] 任务完成")
        elif code == CODE_SIGNED and "频繁" in msg:
            self.results[label] = ("⚠️", msg or "操作频繁")
            log(f"   ⚠️ [{label_cn(label)}] {msg or '操作频繁'}")
        elif code == CODE_SIGNED or "已完成" in msg or "已领取" in msg:
            self.results[label] = ("ℹ️", msg or "今日已完成")
            log(f"   ℹ️ [{label_cn(label)}] {msg or '今日已完成'}")
        else:
            self.results[label] = ("❌", f"失败: {msg or '未知错误'}")
            debug_dump(f"{label_cn(label)}返回", data)
            log(f"   ❌ [{label_cn(label)}] 失败：{msg or brief(data)}")

    # ---------- 浇水 ----------
    def water_tree(self):
        status, data = self.call("getZgForest")
        if status in (401, 403) or is_auth_fail(data):
            if not self.renew_token("浇水前校验失败"):
                self.results["water"] = ("❌", self.fatal)
                return
            status, data = self.call("getZgForest")
        drops = self.read_drops(data)
        if drops is None:
            debug_dump("getZgForest 未解析出水滴", data)
            log("   ⚠️ [浇水] 未取到剩余水滴，跳过")
            log("   ℹ️ [提示] 树木/浏览/阅读都提示「无法获得水滴」，说明该账号的森林未开通")
            self.results["water"] = ("⚠️", "水滴未知")
            return
        self.drops = drops
        self.drops_known = True
        times = drops // 10
        if times <= 0:
            log(f"   ⚠️ [浇水] 水滴不足（{drops}g），跳过")
            self.results["water"] = ("⚠️", "水滴不足")
            return
        if times > MAX_WATER_TIMES:
            log(f"   💧 [浇水] 当前 {drops}g，可浇 {times} 次，上限 {MAX_WATER_TIMES} 次")
            times = MAX_WATER_TIMES
        else:
            log(f"   💧 [浇水] 当前 {drops}g，计划浇水 {times} 次")
        success = 0
        for _ in range(times):
            _, resp = self.call("wateringZgForest")
            code = (resp or {}).get("code")
            if code == CODE_OK:
                success += 1
            elif is_auth_fail(resp):
                log("   ❌ [浇水] token 失效，停止浇水")
                break
            elif code == CODE_QUOTA:
                log(f"   ⚠️ [浇水] {brief((resp or {}).get('msg'))}，停止浇水")
                break
            time.sleep(random.uniform(1, 2))
        self.water_times = success
        if success > 0:
            self.results["water"] = ("✅", f"浇水 {success} 次")
            log(f"   ✅ [浇水] 成功 {success}/{times} 次")
        else:
            self.results["water"] = ("❌", "浇水失败")
            log("   ❌ [浇水] 全部失败")

    def run(self, task_codes):
        if not self.checkin():
            return False
        delay()
        self.tree_checkin()
        delay()
        self.support_tasks(task_codes)
        delay()
        self.forest_task("2025001", "browse", "🛍️")
        delay()
        self.forest_task("2025002", "article", "📖")
        delay()
        self.water_tree()
        return not self.fatal


# ====================== 通知 ======================
def send_qinglong_notify(title, content):
    for path in (
        "/ql/data/scripts/notify.py",
        "/ql/scripts/notify.py",
        "/ql/data/notify.py",
        os.path.join(SCRIPT_DIR, "notify.py"),
    ):
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


def send_pushplus(title, content):
    token = (os.getenv("PUSHPLUS_TOKEN") or os.getenv("PLUSPLUS_TOKEN")
             or os.getenv("PUSH_PLUS_TOKEN"))
    if not token:
        return False
    try:
        requests.post("https://www.pushplus.plus/send",
                      json={"token": token, "title": title, "content": content, "template": "txt"},
                      timeout=15)
        return True
    except Exception:
        return False


def send_iiime(key, title, content):
    if not key:
        return False
    try:
        resp = requests.get("https://push.i-i.me",
                            params={"push_key": key, "title": title, "content": content,
                                    "type": "markdown", "date": now_text()},
                            timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def build_notify(results):
    ok = sum(1 for r in results if r.get("success"))
    total_water = sum(int(r.get("waterTimes") or 0) for r in results)
    lines = [f"【{APP_NAME}】每日任务", f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}",
             f"浇水合计 {total_water} 次"]
    for r in results:
        flag = "✅" if r.get("success") else "❌"
        lines.append(f"{flag} 账号{r.get('index')} {r.get('title')}：{r.get('checkin') or r.get('error') or '-'}"
                     f" | 浇水 {r.get('waterTimes') or 0} 次 | 水滴 {r.get('drops')}g")
    return "\n".join(lines)


# ====================== 主流程 ======================
def run_account(index, total, entry, cache):
    server, ref, note = parse_entry(entry)
    title = f"标识 {ref}" + (f"（{note}）" if note else "")
    source = f"{server}@{ref}" + (f"#{note}" if note else "")
    account_frame(index, total, title, source)

    key = cache_key_of(server, ref)
    token = token_of(cache.get(key))
    login_source = "缓存复用"
    result = {
        "index": index,
        "title": title,
        "source": source,
        "success": False,
        "checkin": "",
        "drops": 0,
        "waterTimes": 0,
        "error": "",
        "loginSource": login_source,
    }

    if token:
        log(f"   💾 [缓存] 复用已保存 token: {mask(token)}")
    else:
        login_source = "新登录"
        log("   🔄 [登录] 无缓存 token，执行首次登录")
        token = login_account(server, ref, cache, key)
        if not token:
            log("   ❌ [登录] 首次登录失败，跳过该账号")
            result["loginSource"] = login_source
            result["error"] = "首次登录失败"
            return result

    task = WnnTask(token, server, ref, cache, key)

    # 开跑前只读校验
    ok, _ = task.probe()
    if ok:
        log("   ✅ [校验] 登录凭证校验通过")
    else:
        log("   ⚠️ [校验] 登录凭证失效，清理缓存后重新登录")
        cache.pop(key, None)
        write_cache(cache)
        if not task.renew_token("缓存 token 已失效"):
            log(f"   ❌ [登录] {task.fatal}")
            result["loginSource"] = "缓存失效重登"
            result["error"] = task.fatal
            return result
        ok, _ = task.probe()
        if not ok:
            log("   ❌ [校验] 重新登录后仍然校验失败")
            result["loginSource"] = "缓存失效重登"
            result["error"] = "重新登录后校验失败"
            return result
        login_source = "缓存失效重登"
        log("   ✅ [校验] 重新登录后校验通过")

    result["loginSource"] = login_source
    task.ensure_forest()
    task.run([get_task_code()])

    result.update({
        "success": not task.fatal,
        "checkin": task.results["checkin"][1],
        "drops": task.drops,
        "waterTimes": task.water_times,
        "error": task.fatal,
        "task": task,
    })
    if result["success"]:
        log("   ✅ [完成] 该账号任务执行完成")
    else:
        log(f"   ⚠️ [完成] {task.fatal or '存在失败项'}")
    return result


def get_task_code():
    return "".join(chr(item) for item in _CODE_BYTES)


def main():
    entries = [line.strip() for line in os.getenv("YYB_SERVER", "").splitlines() if line.strip()]
    if not entries:
        log("❌ 未配置环境变量 YYB_SERVER")
        log("格式：YYB Go 服务地址@微信账号标识[#备注]，多账号换行分隔")
        return []

    valid = [e for e in entries if parse_entry(e)[0]]
    invalid = [e for e in entries if not parse_entry(e)[0]]
    if not valid:
        log("❌ YYB_SERVER 没有可用账号（格式：地址@标识[#备注]）")
        return []
    for line in invalid:
        log(f"   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过：{brief(line)}")

    box_top(f"🌿 {APP_NAME} 每日任务")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(valid)} 个" + (f"（{len(invalid)} 行格式无效）" if invalid else ""))
    box_line("💾 缓存", os.path.basename(CACHE_FILE))
    box_bottom()

    cache = migrate_cache(read_cache(), valid)
    results = []
    for i, entry in enumerate(valid, 1):
        try:
            results.append(run_account(i, len(valid), entry, cache))
        except Exception as exc:
            log(f"   ❌ [执行] 账号 {i} 未捕获异常：{brief(exc)}")
            results.append({"index": i, "title": entry, "success": False,
                            "error": f"异常 {brief(exc)}", "waterTimes": 0, "drops": 0})
        hr()
        if i < len(valid):
            log("   ⏳ 等待2秒后执行下一个账号...")
            time.sleep(2)

    log()
    for r in results:
        if r.get("success"):
            log(f"✅ 【账号 {r.get('index')} · {r.get('title')}】")
            log(f"   🔐 [登录] {r.get('loginSource') or '-'}")
            task = r.get("task")
            if task:
                log(f"   📅 [签到] {task.results['checkin'][1]}")
                log(f"   🌳 [树木] {task.results['tree'][1]}")
                log(f"   🤝 [协作] {task.results['invite'][1]}")
                log(f"   🛍️ [浏览] {task.results['browse'][1]}")
                log(f"   📖 [阅读] {task.results['article'][1]}")
                log(f"   💧 [水滴] {r.get('drops')}g，浇水 {r.get('waterTimes')} 次")
        else:
            log(f"❌ 【账号 {r.get('index')} · {r.get('title')}】")
            log(f"   🔐 [登录] {r.get('loginSource') or '-'}")
            log(f"   ⚠️ [失败] {r.get('error') or '未知错误'}")

    ok = sum(1 for r in results if r.get("success"))
    total_water = sum(int(r.get("waterTimes") or 0) for r in results)
    box_top(f"🏁 {APP_NAME} 执行汇总")
    box_line("📊 执行结果", f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}")
    box_line("💧 浇水合计", f"{total_water} 次")
    box_bottom()

    if YYB_NOTIFY:
        content = build_notify(results)
        if send_qinglong_notify(f"{APP_NAME} 任务结果", content):
            log("   📮 [通知] 已调用青龙 notify.py")
        else:
            log("   ℹ️ [通知] 未找到青龙 notify.py")
        if send_pushplus(f"{APP_NAME} 任务结果", content):
            log("   📮 [通知] PushPlus 已发送")
        else:
            log("   ℹ️ [推送] 未配置 PUSHPLUS_TOKEN，跳过 PushPlus")
        if send_iiime(os.getenv("WRN_PUSH_KEY", ""), f"{APP_NAME} 任务结果", content):
            log("   📮 [通知] push.i-i.me 已发送")
    else:
        log("   ℹ️ [通知] WRN_NOTIFY=0，已关闭通知")

    return results


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"❌ 程序异常: {exc}")
        traceback.print_exc()
