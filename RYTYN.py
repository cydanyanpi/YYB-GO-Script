#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 认养一头牛
# cron: 17 9,21 * * *

"""
认养一头牛（牛奶卡商城）每日任务

功能：
  1. 开跑前只读校验 token，失效自动清缓存重登
  2. 每日签到（含积分/等级/手机号状态）
  3. 试用申请
  4. 中奖记录查询
  5. 社区答题（正确答案落盘缓存）
  6. 发帖种草后自动删帖
  7. 青龙 notify + PushPlus 通知

环境变量：
  YYB_SERVER          必填：YYB Go 地址@微信账号标识[#备注]，多账号换行
  RYTYN_NOTIFY=0      关闭通知
  RYTYN_TRIAL=0       关闭试用申请
  RYTYN_QUIZ=0        关闭社区答题
  RYTYN_POST=0        关闭发帖种草
  PUSHPLUS_TOKEN      PushPlus token（兼容 PLUSPLUS_TOKEN / PUSH_PLUS_TOKEN）

依赖：requests
"""

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

BASE_URL = "https://www.milkcard.mall.ryytngroup.com"
APP_ID = "wx0408f3f20d769a2f"
PAGE_VERSION = "323"

BOX_WIDTH = 48
BOX_INNER = 46

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "rytyn_token_cache.json")
ANSWER_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "rytyn_answer_cache.json")

NOTIFY_ENABLED = os.getenv("RYTYN_NOTIFY", "1").strip() != "0"
TRIAL_ENABLED = os.getenv("RYTYN_TRIAL", "1").strip() != "0"
QUIZ_ENABLED = os.getenv("RYTYN_QUIZ", "1").strip() != "0"
POST_ENABLED = os.getenv("RYTYN_POST", "1").strip() != "0"

UA_POOL = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.61(0x18003d24) NetType/4G Language/zh_CN",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50(0x1800322e) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (iPad; CPU OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49(0x18003123) NetType/WIFI Language/zh_CN",
]

AUTH_PATTERN = re.compile(r"token|登录|未授权|授权|失效|过期|未登录|鉴权|401|403", re.I)
SIGNED_PATTERN = re.compile(r"已签|签到过|重复|已完成|今日已")


# ====================== 日志版式 ======================
def display_width(text):
    width = 0
    for ch in str(text):
        code = ord(ch)
        if code in (0xFE0F, 0xFE0E, 0x200D):
            continue
        width += 2 if code > 0xFF else 1
    return width


def pad(text, width):
    value = str(text)
    while display_width(value) > width:
        value = value[:-1]
    return value + " " * max(0, width - display_width(value))


def log(msg=""):
    print(msg)


def box_top(title):
    log()
    log("╔" + "═" * BOX_WIDTH + "╗")
    log("║  " + pad(title, BOX_INNER) + "║")


def box_line(label, value):
    log("║  " + pad(f"{label}: {value}", BOX_INNER) + "║")


def box_bottom():
    log("╚" + "═" * BOX_WIDTH + "╝")


def account_frame(index, total, title, source):
    log()
    log("┌" + "─" * BOX_WIDTH + "┐")
    log("│  " + pad(f"🧩 账号 {index} / {total}　{title}", BOX_INNER) + "│")
    log("│  " + pad(f"🔗 来源: {source}", BOX_INNER) + "│")
    log("└" + "─" * BOX_WIDTH + "┘")


def hr():
    log()
    log("-" * BOX_WIDTH)


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def short(value, limit=300):
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:limit] + "…" if len(text) > limit else text


def mask_token(token):
    token = str(token or "")
    return token if len(token) <= 12 else f"{token[:6]}***{token[-4:]}"


def mask_phone(phone):
    phone = str(phone or "")
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 11 else phone


# ====================== 账号解析 ======================
def parse_yyb_entry(raw):
    value = str(raw or "").strip()
    note = ""
    if not value:
        return "", "", ""
    hash_index = value.find("#")
    if hash_index != -1:
        note = value[hash_index + 1:].strip()
        value = value[:hash_index].strip()
    at_index = value.find("@")
    if at_index == -1:
        return "", "", note
    server = value[:at_index].strip()
    ref = value[at_index + 1:].strip()
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
def _read_raw_cache():
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
            ref = str(item.get("ref") or "").strip()
            server = str(item.get("server") or "").strip()
            if not ref:
                continue
            key = f"{server}|{ref}" if server else f"legacy|{ref}"
            converted[key] = item
        return converted
    return {}


def _write_raw_cache(cache):
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log(f"   ⚠️ [缓存] 写入失败：{short(e, 60)}")
        return False


def _cache_key_matches(key, server, ref):
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


def load_cache_entry(server, ref):
    cache = _read_raw_cache()
    exact = f"{server}|{ref}"
    candidates = []
    for key, value in cache.items():
        if not _cache_key_matches(key, server, ref):
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
        _write_raw_cache(cache)
        log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」")
        return dict(best[2])
    return dict(best[2])


def save_cache_entry(server, ref, entry):
    cache = _read_raw_cache()
    exact = f"{server}|{ref}"
    for key in list(cache.keys()):
        if _cache_key_matches(key, server, ref) and key != exact:
            cache.pop(key, None)
    cache[exact] = dict(entry)
    cache[exact]["updatedAt"] = now_text()
    _write_raw_cache(cache)


def drop_cache_entry(server, ref):
    cache = _read_raw_cache()
    for key in list(cache.keys()):
        if _cache_key_matches(key, server, ref):
            cache.pop(key, None)
    _write_raw_cache(cache)


def load_answer_cache():
    try:
        if not os.path.exists(ANSWER_CACHE_FILE):
            return {}
        with open(ANSWER_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_answer_cache(cache):
    try:
        os.makedirs(os.path.dirname(ANSWER_CACHE_FILE), exist_ok=True)
        with open(ANSWER_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ====================== 请求封装 ======================
def _headers(token=""):
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": random.choice(UA_POOL),
        "Referer": f"https://servicewechat.com/{APP_ID}/305/page-frame.html",
        "X-Auth-Token": token,
    }


def _auth_fail(status, code, msg):
    if status in (401, 403):
        return True
    return bool(AUTH_PATTERN.search(f"{code} {msg}"))


def api_request(token, method, path, payload=None):
    url = BASE_URL + path
    headers = _headers(token)
    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        else:
            response = requests.post(url, headers=headers, json=payload or {}, timeout=30)
    except Exception as e:
        return {"ok": False, "status": 0, "code": None, "msg": f"请求异常: {e}", "data": None, "auth": False}
    status = response.status_code
    try:
        body = response.json()
    except Exception:
        text = response.text
        return {
            "ok": False,
            "status": status,
            "code": None,
            "msg": f"非 JSON 响应: {short(text, 200)}",
            "data": None,
            "auth": status in (401, 403),
        }
    code = body.get("code") if isinstance(body, dict) else None
    msg = (body.get("msg") or body.get("message") or "") if isinstance(body, dict) else ""
    data = body.get("data") if isinstance(body, dict) else None
    ok = status == 200 and str(code) == "200"
    auth = _auth_fail(status, code, msg)
    return {"ok": ok, "status": status, "code": code, "msg": str(msg), "data": data, "auth": auth, "body": body}


def _post_json(url, payload, headers=None, timeout=20):
    merged = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": random.choice(UA_POOL),
    }
    if headers:
        merged.update(headers)
    return requests.post(url, json=payload, headers=merged, timeout=timeout, proxies={"http": None, "https": None})


# ====================== YYB 登录 ======================
def refresh_token(server, ref):
    """先取手机号授权数据，再取 wx.login code（保证 session_key 一致），最后 minilogin"""
    phone = None
    wx_code = None

    for attempt in range(2):
        try:
            resp = _post_json(
                f"http://{server}/wxapp/getPhoneNumber",
                {"ref": ref, "app_id": APP_ID},
                timeout=15,
            )
            body = resp.json()
            if body.get("code") == 0:
                phone = body.get("data", {}).get("result") or {}
                break
            log(f"   ⚠️ [登录] 取手机号失败（第 {attempt + 1} 次）：{short(body, 100)}")
        except Exception as e:
            log(f"   ⚠️ [登录] 取手机号异常（第 {attempt + 1} 次）：{short(e, 80)}")
        time.sleep(1 + attempt)
    if not phone or not phone.get("encryptedData") or not phone.get("iv"):
        return None, "getPhoneNumber 未返回 encryptedData/iv"

    for attempt in range(2):
        try:
            resp = _post_json(f"http://{server}/wxapp/getCode", {"ref": ref, "app_id": APP_ID}, timeout=15)
            body = resp.json()
            if body.get("code") == 0:
                wx_code = (body.get("data", {}).get("result") or {}).get("code")
                break
            log(f"   ⚠️ [登录] 取 code 失败（第 {attempt + 1} 次）：{short(body, 100)}")
        except Exception as e:
            log(f"   ⚠️ [登录] 取 code 异常（第 {attempt + 1} 次）：{short(e, 80)}")
        time.sleep(1 + attempt)
    if not wx_code:
        return None, "getCode 未返回 code"

    payload = {
        "encryptedData": phone.get("encryptedData"),
        "offset": phone.get("iv"),
        "wxCode": wx_code,
        "code": phone.get("code", ""),
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": random.choice(UA_POOL),
        "Referer": f"https://servicewechat.com/{APP_ID}/{PAGE_VERSION}/page-frame.html",
    }
    try:
        resp = requests.post(f"{BASE_URL}/mall/xhr/minilogin", headers=headers, json=payload, timeout=30)
    except Exception as e:
        return None, f"minilogin 请求异常: {e}"
    token = resp.headers.get("X-Auth-Token") or resp.headers.get("x-auth-token")
    body = {}
    try:
        body = resp.json()
    except Exception:
        pass
    if not token and isinstance(body, dict):
        data = body.get("data") or {}
        if isinstance(data, dict):
            token = data.get("token") or data.get("x-auth-token") or data.get("xAuthToken")
        token = token or body.get("token")
    if not token:
        msg = (body.get("msg") or body.get("message")) if isinstance(body, dict) else ""
        code = body.get("code") if isinstance(body, dict) else "?"
        return None, f"minilogin 未返回 token：HTTP {resp.status_code} code={code} msg={msg or short(resp.text, 100)}"
    return str(token), ""


# ====================== 业务类 ======================
class Account:
    def __init__(self, raw, index):
        self.raw = raw
        self.index = index
        self.server, self.ref, self.note = parse_yyb_entry(raw)
        self.token = ""
        self.nickname = ""
        self.phone = ""
        self.grade = None
        self.point = 0
        self.login_source = ""
        self.result = {
            "index": index,
            "title": f"标识 {self.ref}" + (f"（{self.note}）" if self.note else ""),
            "success": False,
            "loginSource": "",
            "signMessage": "",
            "signStatus": "",
            "pointBefore": 0,
            "pointAfter": 0,
            "trialCount": 0,
            "winCount": 0,
            "quizMessage": "",
            "postMessage": "",
            "error": "",
        }

    def title(self):
        return self.result["title"]

    def source(self):
        return f"{self.server}@{self.ref}" + (f"#{self.note}" if self.note else "")

    def log(self, text):
        log(text)

    def api(self, method, path, payload=None):
        return api_request(self.token, method, path, payload)

    def login(self):
        token, error = refresh_token(self.server, self.ref)
        if not token:
            return False, error
        self.token = token
        self.login_source = "新登录"
        self.log(f"   ✅ [登录] token 获取成功 {mask_token(token)}")
        return True, ""

    def probe(self):
        """只读校验：签到规则接口，不产生签到副作用"""
        r = self.api("GET", "/mall/xhr/task/checkin/getRule")
        if r["ok"]:
            return "ok", r
        if r["auth"]:
            return "auth", r
        return "unknown", r

    def ensure_token(self):
        cached = load_cache_entry(self.server, self.ref)
        if cached:
            self.token = str(cached.get("token") or "")
            self.nickname = str(cached.get("nickname") or "")
            self.phone = str(cached.get("phone") or "")
            self.grade = cached.get("grade")
            self.point = cached.get("point") or 0
            self.login_source = "缓存复用"
            self.log(f"   💾 [缓存] 复用已保存 token {mask_token(self.token)}")
            status, r = self.probe()
            if status == "auth":
                self.log(f"   ⚠️ [校验] 缓存 token 失效（{short(r['msg'], 60)}），清缓存重登")
                drop_cache_entry(self.server, self.ref)
                re_login_ok, error = self.login()
                if not re_login_ok:
                    return False, f"重新登录失败：{error}"
                self.login_source = "缓存失效重登"
            else:
                self.log("   ✅ [校验] 登录凭证校验通过（签到规则接口）")
            return True, ""

        self.login_source = "新登录"
        self.log("   🔄 [登录] 无缓存 token，执行首次登录")
        ok, error = self.login()
        if not ok:
            return False, f"登录失败：{error}"
        status, r = self.probe()
        if status == "auth":
            return False, f"新 token 校验失败：{short(r['msg'], 60)}"
        self.log("   ✅ [校验] 登录凭证校验通过（签到规则接口）")
        return True, ""

    def sign(self, label="签到", retry=True):
        r = self.api("POST", "/mall/xhr/task/checkin/save", {})
        if r["ok"]:
            data = r["data"] if isinstance(r["data"], dict) else {}
            self.phone = str(data.get("phone") or self.phone or "")
            self.grade = data.get("grade", self.grade)
            self.point = int(data.get("point") or self.point or 0)
            message = r["msg"] or "签到成功"
            status = "already" if SIGNED_PATTERN.search(message) else "success"
            if label == "签到":
                if status == "already":
                    self.log(f"   ℹ️ [签到] 今日已签到（{message}）")
                else:
                    self.log(f"   ✅ [签到] 签到成功，积分 {self.point}")
            return {"ok": True, "status": status, "message": message, "point": self.point}

        msg = r["msg"] or short(r.get("body"), 100)
        if SIGNED_PATTERN.search(msg):
            self.log(f"   ℹ️ [签到] 今日已签到（{msg}）")
            return {"ok": True, "status": "already", "message": msg, "point": self.point}
        if retry and r["auth"]:
            self.log(f"   ⚠️ [签到] 会话失效（{short(msg, 60)}），重新登录后重试")
            drop_cache_entry(self.server, self.ref)
            ok, error = self.login()
            if not ok:
                return {"ok": False, "status": "error", "message": f"重登失败：{error}", "point": self.point}
            self.login_source = "接口失效重登"
            return self.sign(label, retry=False)
        self.log(f"   ❌ [签到] 失败：{short(msg, 100)}")
        return {"ok": False, "status": "error", "message": msg, "point": self.point}

    def get_address(self):
        r = self.api("POST", "/mall/xhr/address/receive/list", {})
        if not r["ok"]:
            self.log(f"   ⚠️ [地址] 获取失败：{short(r['msg'], 80)}")
            return None, ""
        data = r["data"]
        addresses = data if isinstance(data, list) else (data.get("list") if isinstance(data, dict) else []) or []
        if not addresses:
            self.log("   ℹ️ [地址] 没有收货地址，试用申请跳过")
            return None, ""
        first = addresses[0] if isinstance(addresses[0], dict) else {}
        try:
            address_id = int(first.get("id"))
        except Exception:
            return None, ""
        city = str(first.get("cityName") or "")
        return address_id, city

    def run_trial(self, address_id):
        if not TRIAL_ENABLED:
            self.log("   ℹ️ [试用] RYTYN_TRIAL=0，已关闭")
            return 0
        if not address_id:
            return 0
        r = self.api("POST", "/mall/xhr/freeTrial/getList", {"pageNum": 1, "pageSize": 10, "statusList": [1, 2]})
        if not r["ok"]:
            self.log(f"   ⚠️ [试用] 获取列表失败：{short(r['msg'], 80)}")
            return 0
        data = r["data"]
        items = (data.get("list") if isinstance(data, dict) else []) or []
        applied = 0
        skipped = 0
        for item in items:
            if not isinstance(item, dict) or item.get("freeTrialButton") != 3:
                continue
            grade_list = [str(x) for x in (item.get("gradeList") or [])]
            if self.grade is None or str(self.grade) not in grade_list:
                skipped += 1
                continue
            trial_id = item.get("id")
            if trial_id is None:
                continue
            name = str(item.get("productName") or "")
            draw_time = str(item.get("drawTime") or "")
            res = self.api("POST", "/mall/xhr/freeTrial/apply", {"id": trial_id, "addressId": address_id})
            if res["ok"]:
                applied += 1
                self.log(f"   🎁 [试用] 申请成功：{name}{f'（开奖 {draw_time}）' if draw_time else ''}")
            else:
                self.log(f"   ⚠️ [试用] 申请失败：{name or trial_id}｜{short(res['msg'], 80)}")
        if not applied:
            self.log(f"   ℹ️ [试用] 暂无可申请商品{f'（等级不符 {skipped} 个）' if skipped else ''}")
        return applied

    def run_winnings(self):
        r = self.api(
            "POST",
            "/mall/xhr/freeTrialUser/getList",
            {"parentTabStatus": 1, "pageNum": 1, "pageSize": 10, "subTabStatus": 1},
        )
        if not r["ok"]:
            self.log(f"   ⚠️ [中奖] 查询失败：{short(r['msg'], 80)}")
            return 0
        data = r["data"]
        records = (data.get("list") if isinstance(data, dict) else data if isinstance(data, list) else []) or []
        if not records:
            self.log("   ℹ️ [中奖] 暂无中奖记录")
            return 0
        for item in records:
            if isinstance(item, dict):
                self.log(f"   🏆 [中奖] {item.get('productName') or '未知商品'}（需提交试用报告）")
        return len(records)

    def run_quiz(self):
        if not QUIZ_ENABLED:
            self.log("   ℹ️ [答题] RYTYN_QUIZ=0，已关闭")
            return ""
        r = self.api("GET", "/mall/xhr/quizActivity/activities")
        if not r["ok"]:
            self.log(f"   ⚠️ [答题] 获取题库失败：{short(r['msg'], 80)}")
            return ""
        data = r["data"]
        activities = data if isinstance(data, list) else (data.get("list") if isinstance(data, dict) else []) or []
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        today_quiz = None
        for item in activities:
            if not isinstance(item, dict):
                continue
            related = str(item.get("relatedDate") or "")
            if related[:10] == today:
                today_quiz = item
                break
        if not today_quiz:
            self.log("   ℹ️ [答题] 今日暂无题目")
            return ""

        try:
            options = json.loads(today_quiz.get("options") or "[]")
        except Exception:
            self.log("   ⚠️ [答题] 选项解析失败")
            return ""
        options = [o for o in options if isinstance(o, dict) and o.get("key")]
        if not options:
            self.log("   ℹ️ [答题] 未获取到选项，跳过")
            return ""

        question = str(today_quiz.get("questionTitle") or "")[:30]
        self.log(f"   🧠 [答题] 今日题目：{question}")

        r = self.api("GET", "/mall/xhr/quizActivity/records")
        records = []
        if r["ok"]:
            data = r["data"]
            records = data if isinstance(data, list) else (data.get("list") if isinstance(data, dict) else []) or []
        today_record = None
        for item in records:
            if isinstance(item, dict) and str(item.get("relatedDate") or "")[:10] == today:
                today_record = item
                break
        if today_record:
            if today_record.get("isCorrect") == 1:
                correct = today_record.get("correctAnswer") or "?"
                self.log(f"   ℹ️ [答题] 今日已答对（{correct}），不重复提交")
                return "今日已答对"
            self.log("   ℹ️ [答题] 今日已作答（未答对），不重复提交")
            return "今日已作答"

        answer_cache = load_answer_cache()
        selected_key = answer_cache.get(today)
        if selected_key:
            self.log(f"   🧠 [答题] 使用缓存答案：{selected_key}")
        else:
            selected = random.choice(options)
            selected_key = str(selected.get("key"))
            self.log(f"   🎲 [答题] 随机选择：{selected_key}，提交后记录正确答案")
            time.sleep(6 + random.random() * 2)
            res = self.api(
                "POST",
                "/mall/xhr/quizActivity/submit",
                {"quizActivityId": today_quiz.get("id"), "userAnswer": selected_key},
            )
            if not res["ok"]:
                self.log(f"   ⚠️ [答题] 提交失败：{short(res['msg'], 80)}")
                return ""
            return self._handle_quiz_result(res["data"], today, answer_cache)

        time.sleep(6 + random.random() * 2)
        res = self.api(
            "POST",
            "/mall/xhr/quizActivity/submit",
            {"quizActivityId": today_quiz.get("id"), "userAnswer": selected_key},
        )
        if not res["ok"]:
            self.log(f"   ⚠️ [答题] 提交失败：{short(res['msg'], 80)}")
            return ""
        return self._handle_quiz_result(res["data"], today, answer_cache)

    def _handle_quiz_result(self, data, today, answer_cache):
        data = data if isinstance(data, dict) else {}
        correct = data.get("correctAnswer")
        if correct:
            answer_cache[today] = str(correct)
            save_answer_cache(answer_cache)
        if data.get("isCorrect") == 1:
            point = data.get("point", 0)
            self.log(f"   ✅ [答题] 回答正确，获得 {point} 积分")
            return f"答对 +{point}"
        self.log(f"   ⚠️ [答题] 回答错误{f'，正确答案 {correct}' if correct else ''}")
        return f"答错（正确答案 {correct or '未知'}）"

    def run_post(self):
        if not POST_ENABLED:
            self.log("   ℹ️ [种草] RYTYN_POST=0，已关闭")
            return ""
        r = self.api(
            "POST",
            "/mall/xhr/community/home/recommend/item",
            {"recommendationId": 7, "sort": "personalized", "direction": "desc", "pageNum": 1, "pageSize": 3},
        )
        if not r["ok"]:
            self.log(f"   ⚠️ [种草] 获取推荐内容失败：{short(r['msg'], 80)}")
            return ""
        data = r["data"]
        items = (data.get("list") if isinstance(data, dict) else []) or []
        items = [i for i in items if isinstance(i, dict) and (i.get("content") or i.get("imageUrls"))]
        if not items:
            self.log("   ℹ️ [种草] 没有可参考的帖子，跳过")
            return ""
        item = random.choice(items)
        content = str(item.get("content") or "")
        image_urls = item.get("imageUrls") or []
        self.log(f"   📝 [种草] 准备发帖：{content[:12]}…")
        time.sleep(6 + random.random() * 2)
        res = self.api(
            "POST",
            "/mall/xhr/community/posts/push",
            {
                "postId": None,
                "title": "",
                "content": content,
                "imageUrls": image_urls,
                "topicLabelNames": [],
                "communityTopicActivityId": None,
                "communitPostDraftId": None,
                "freeTrialCommentId": None,
                "productIds": [],
            },
        )
        if not res["ok"]:
            self.log(f"   ⚠️ [种草] 发帖失败：{short(res['msg'], 80)}")
            return ""
        post_id = self._extract_post_id(res["data"])
        if not post_id:
            self.log("   ⚠️ [种草] 发帖成功但未取到 postId，跳过删帖")
            return "发帖成功（未删）"
        time.sleep(2 + random.random())
        res = self.api("GET", f"/mall/xhr/community/posts/delete?postId={post_id}")
        if res["ok"]:
            self.log("   ✅ [种草] 发帖并删除成功")
            return "发帖成功，已删除"
        self.log(f"   ⚠️ [种草] 删帖失败：{short(res['msg'], 80)}")
        return "发帖成功，删帖失败"

    def _extract_post_id(self, data):
        if isinstance(data, (int, str)) and str(data).isdigit():
            return str(data)
        if isinstance(data, dict):
            for key in ("postId", "id", "post_id"):
                value = data.get(key)
                if value is not None and str(value).isdigit():
                    return str(value)
        return ""

    def run(self):
        if not self.server or not self.ref:
            return self.result

        account_frame(self.index, TOTAL_ACCOUNTS, self.title(), self.source())
        ok, error = self.ensure_token()
        if not ok:
            self.result["error"] = error
            self.log(f"   ❌ [校验] {error}")
            return self.result
        self.result["loginSource"] = self.login_source

        try:
            initial = self.sign()
        except Exception as e:
            self.result["error"] = f"签到异常：{short(e, 80)}"
            self.log(f"   ❌ [签到] 异常：{short(e, 80)}")
            return self.result

        self.result["signMessage"] = initial["message"]
        self.result["signStatus"] = initial["status"]
        self.result["pointBefore"] = initial.get("point", 0)
        self.result["pointAfter"] = initial.get("point", 0)

        self.log(
            f"   👤 [会员] {mask_phone(self.phone) or '未知手机号'}，等级 {self.grade if self.grade is not None else '-'}，当前积分 {initial.get('point', 0)}"
        )

        address_id, city = self.get_address()
        try:
            self.result["trialCount"] = self.run_trial(address_id)
        except Exception as e:
            self.log(f"   ⚠️ [试用] 异常：{short(e, 80)}")
        try:
            self.result["winCount"] = self.run_winnings()
        except Exception as e:
            self.log(f"   ⚠️ [中奖] 异常：{short(e, 80)}")
        try:
            self.result["quizMessage"] = self.run_quiz()
        except Exception as e:
            self.log(f"   ⚠️ [答题] 异常：{short(e, 80)}")
        try:
            self.result["postMessage"] = self.run_post()
        except Exception as e:
            self.log(f"   ⚠️ [种草] 异常：{short(e, 80)}")

        # 复查积分（checkin/save 幂等，只取状态）
        try:
            final = self.sign(label="复查")
            self.result["pointAfter"] = final.get("point", self.point)
        except Exception:
            self.result["pointAfter"] = self.point

        success = initial["status"] in ("success", "already")
        self.result["success"] = success
        entry = {
            "token": self.token,
            "nickname": self.nickname,
            "phone": self.phone,
            "grade": self.grade,
            "point": self.result["pointAfter"],
        }
        save_cache_entry(self.server, self.ref, entry)

        delta = int(self.result["pointAfter"] or 0) - int(self.result["pointBefore"] or 0)
        self.log(f"   💰 [积分] 签到后 {self.result['pointBefore']} → 复查 {self.result['pointAfter']}（{'+' if delta >= 0 else ''}{delta}）")
        if success:
            self.log("   ✅ [完成] 该账号任务执行完成")
        else:
            self.log(f"   ⚠️ [完成] 签到未成功：{short(initial['message'], 80)}")
        return self.result


TOTAL_ACCOUNTS = 0


# ====================== 通知 ======================
def send_qinglong_notify(title, content):
    try:
        from notify import send
    except Exception as e:
        log(f"   ℹ️ [通知] 青龙 notify 不可用：{short(e, 60)}")
        return False
    try:
        send(title, content)
        return True
    except Exception as e:
        log(f"   ⚠️ [通知] 青龙 notify 发送失败：{short(e, 60)}")
        return False


def send_pushplus(title, content):
    token = (
        os.getenv("PUSHPLUS_TOKEN")
        or os.getenv("PLUSPLUS_TOKEN")
        or os.getenv("PUSH_PLUS_TOKEN")
        or ""
    ).strip()
    if not token:
        return False
    try:
        resp = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content, "template": "txt"},
            timeout=15,
            proxies={"http": None, "https": None},
        )
        body = resp.json()
        return body.get("code") == 200
    except Exception:
        return False


def build_notify(results):
    ok = sum(1 for r in results if r["success"])
    lines = [
        "【认养一头牛】每日任务",
        f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}",
        "",
    ]
    for r in results:
        flag = "✅" if r["success"] else "❌"
        lines.append(f"{flag} 账号{r['index']} {r['title']}：{r['signMessage'] or r['error'] or '-'}")
        lines.append(
            f"   登录：{r['loginSource'] or '-'}｜积分 {r['pointBefore']} → {r['pointAfter']}"
            f"｜试用 {r['trialCount']}｜中奖 {r['winCount']}"
        )
        if r["quizMessage"]:
            lines.append(f"   答题：{r['quizMessage']}")
        if r["postMessage"]:
            lines.append(f"   种草：{r['postMessage']}")
        if not r["success"] and r["error"]:
            lines.append(f"   失败：{r['error']}")
    return "\n".join(lines)


# ====================== 主流程 ======================
def main():
    entries = [line.strip() for line in os.getenv("YYB_SERVER", "").splitlines() if line.strip()]
    if not entries:
        log("❌ 未配置环境变量 YYB_SERVER")
        log("格式：YYB Go 地址@微信账号标识[#备注]，多账号换行分隔")
        return

    valid = []
    invalid = []
    for entry in entries:
        server, ref, note = parse_yyb_entry(entry)
        if server and ref:
            valid.append(entry)
        else:
            invalid.append(entry)

    if not valid:
        log("❌ YYB_SERVER 没有可用账号（格式：地址@标识[#备注]）")
        return

    global TOTAL_ACCOUNTS
    TOTAL_ACCOUNTS = len(valid)

    box_top("🥛 认养一头牛 每日任务")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(valid)} 个{f'（{len(invalid)} 行格式无效）' if invalid else ''}")
    box_line("💾 缓存", os.path.basename(TOKEN_CACHE_FILE))
    features = ["签到"]
    if TRIAL_ENABLED:
        features.append("试用")
    if QUIZ_ENABLED:
        features.append("答题")
    if POST_ENABLED:
        features.append("种草")
    box_line("🧩 功能", "｜".join(features))
    box_bottom()

    for line in invalid:
        log(f"   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过：{short(line, 60)}")

    results = []
    for index, entry in enumerate(valid, start=1):
        account = Account(entry, index)
        try:
            results.append(account.run())
        except Exception as e:
            log(f"   ❌ [执行] 账号 {index} 未捕获异常：{short(e, 100)}")
            results.append(
                {
                    "index": index,
                    "title": account.title(),
                    "success": False,
                    "loginSource": "",
                    "signMessage": "",
                    "pointBefore": 0,
                    "pointAfter": 0,
                    "trialCount": 0,
                    "winCount": 0,
                    "quizMessage": "",
                    "postMessage": "",
                    "error": f"异常 {short(e, 100)}",
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
            log(f"   💰 [积分] 签到后 {r['pointBefore']} → 复查 {r['pointAfter']}")
            log(f"   🎁 [试用] 申请 {r['trialCount']} 个｜🏆 中奖 {r['winCount']} 条")
            log(f"   🧠 [答题] {r['quizMessage'] or '未执行'}")
            log(f"   📝 [种草] {r['postMessage'] or '未执行'}")
        else:
            log(f"❌ 【账号 {r['index']} · {r['title']}】")
            log(f"   🔐 [登录] {r['loginSource'] or '-'}")
            log(f"   📅 [签到] {r['signMessage'] or '-'}")
            log(f"   ⚠️ [失败] {r['error'] or '未知错误'}")

    ok = sum(1 for r in results if r["success"])
    total_delta = sum(int(r["pointAfter"] or 0) - int(r["pointBefore"] or 0) for r in results)
    box_top("🏁 认养一头牛 执行汇总")
    box_line("📊 执行结果", f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}")
    box_line("💰 任务积分变化", f"{'+' if total_delta >= 0 else ''}{total_delta}")
    box_bottom()

    if NOTIFY_ENABLED:
        content = build_notify(results)
        if send_qinglong_notify("认养一头牛 执行结果", content):
            log("   📮 [通知] 已调用青龙 notify")
        else:
            log("   ℹ️ [通知] 青龙 notify 未发送")
        if send_pushplus("认养一头牛 执行结果", content):
            log("   📮 [通知] PushPlus 已发送")
        else:
            log("   ℹ️ [通知] 未配置 PUSHPLUS_TOKEN，跳过 PushPlus")
    else:
        log("   ℹ️ [通知] RYTYN_NOTIFY=0，已关闭通知")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        log(f"❌ 脚本异常：{short(e, 200)}")
