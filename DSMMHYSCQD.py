#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 袋鼠妈妈会员商场签到
# cron: 8 16,4 * * *

"""
袋鼠妈妈会员商场（有赞）自动签到 - 纯 YYB Go 版

环境变量：
  YYB_SERVER     必填：YYB Go 服务地址@微信账号标识[#备注]，多行换行
  DSMM_NOTIFY    可选：0 关闭通知，默认 1
  PLUSPLUS_TOKEN 可选：PushPlus 推送 token

缓存：脚本目录 token_caches/dsmmhyscqd_token_cache.json，键 地址|标识，不设固定过期
"""

import importlib.util
import json
import os
import random
import re
import time
from datetime import datetime

import requests

APP_NAME = "袋鼠妈妈"
APPID = "wxb27b46293d405a20"
KDT_ID = "44587018"
CHECKIN_ID = "17019"

BASE_URL = "https://h5.youzan.com"
LOGIN_URL = f"https://uic.youzan.com/passport/general/auth.json?kdt_id={KDT_ID}&app_id={APPID}"
SIGN_URL = f"{BASE_URL}/wscump/checkin/checkinV2.json"
MONTH_SIGN_URL = f"{BASE_URL}/wscump/checkin/find_checkin_info_by_month.json"
ASSET_URL = f"{BASE_URL}/retail/h5/showcase/getAssetInfo.json"

YYB_NOTIFY = os.getenv("DSMM_NOTIFY", "1").strip() != "0"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "dsmmhyscqd_token_cache.json")

UA_LIST = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
     "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
     "UnifiedPCWindowsWechat(0xf2541923) XWEB/19899"),
    ("Mozilla/5.0 (Linux; Android 10; Redmi K30 Pro) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/132.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.50.2701 MiniProgramEnv/android"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Mobile/15E148 MicroMessenger/8.0.49(0x18003121) NetType/WIFI Language/zh_CN miniProgram/wxb27b46293d405a20"),
]

BOX_WIDTH = 48
BOX_INNER = 46

AUTH_PATTERN = re.compile(
    r"(未登录|登录失效|登录已过期|请重新登录|请登录|token\s*(无效|过期|失效)|无效的?\s*token"
    r"|access[_\s]*token|凭证|授权失败|认证失败|身份|会话.*(失效|过期)|session.*(invalid|expired)|-401|401|403)",
    re.IGNORECASE,
)


# ====================== 日志 ======================
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


def mask(value):
    value = str(value or "")
    return value if len(value) <= 12 else f"{value[:6]}...{value[-6:]}"


def brief(value, limit=80):
    text = str(value or "").replace("\n", " ")
    return text[: limit - 1] + "…" if len(text) > limit else text


def to_number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def is_auth_fail(payload, msg=""):
    """业务返回里 401/403 或提示词命中鉴权失败"""
    code = to_number((payload or {}).get("code"))
    text = f"{msg} {((payload or {}).get('msg') or '')} {((payload or {}).get('message') or '')}"
    return code in (401, 403) or bool(AUTH_PATTERN.search(text))


# ====================== 账号解析 ======================
def parse_entry(raw):
    value = str(raw or "").strip()
    if not value or "@" not in value:
        return "", "", ""
    note = ""
    hash_pos = value.rfind("#")
    at_pos = value.rfind("@")
    if hash_pos > at_pos:
        note = value[hash_pos + 1:].strip()
        value = value[:hash_pos].strip()
    at_pos = value.rfind("@")
    server = value[:at_pos].strip()
    ref = value[at_pos + 1:].strip()
    server = re.sub(r"^https?://", "", server).rstrip("/")
    return server, ref, note


def ckey(server, ref):
    return f"{server}|{ref}"


# ====================== 缓存 ======================
def read_cache():
    try:
        if not os.path.exists(CACHE_FILE):
            return {}
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"   ⚠️ [缓存] 写入失败：{exc}")


def legacy_ref_of(key):
    """从旧缓存键里提取标识：支持 ref、地址@ref、地址@ref#备注"""
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


def load_cache_entry(cache, server, ref, raw):
    ck = ckey(server, ref)
    entry = cache.get(ck)
    if isinstance(entry, dict) and entry.get("accessToken"):
        return entry
    candidates = []
    for key, value in list(cache.items()):
        if key == ck or not isinstance(value, dict) or not value.get("accessToken"):
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
    log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」")
    return cache[ck]


def save_cache_entry(server, ref, token, session_id, nickname=""):
    cache = read_cache()
    cache[ckey(server, ref)] = {
        "accessToken": token,
        "sessionId": session_id,
        "nickname": nickname or "",
        "updatedAt": now_text(),
    }
    write_cache(cache)


def drop_cache_entry(server, ref):
    cache = read_cache()
    cache.pop(ckey(server, ref), None)
    write_cache(cache)


# ====================== YYB ======================
def get_code(raw_entry):
    server, ref, _ = parse_entry(raw_entry)
    if not server or not ref:
        log("   ❌ [取码] 账号格式无效")
        return None
    log(f"   🧾 [授权] 取码请求 http://{server}/wxapp/getCode")
    try:
        resp = requests.post(f"http://{server}/wxapp/getCode",
                             json={"ref": ref, "app_id": APPID},
                             timeout=20,
                             proxies={"http": None, "https": None})
        data = resp.json()
    except Exception as exc:
        log(f"   ❌ [取码] 请求异常：{brief(exc)}")
        return None
    try:
        code_num = int(str(data.get("code")))
    except (TypeError, ValueError):
        code_num = -1
    payload = data.get("data") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    result = payload.get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            result = {}
    code = (result or {}).get("code")
    if code_num != 0 or not code:
        reason = str(data.get("message") or data.get("msg") or "").strip()
        log(f"   ❌ [取码] 取码失败：{brief(reason or f'YYB 返回 code={code_num}，未取到 code 值')}")
        log(f"   💡 [提示] 请检查 YYB 服务地址 http://{server} 是否在线、{ref} 是否已登录")
        return None
    log("   ✅ [取码] 取码成功")
    return code


# ====================== 业务 ======================
def build_headers(token="", session_id=""):
    headers = {
        "User-Agent": random.choice(UA_LIST),
        "Content-Type": "application/json",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "Referer": f"https://servicewechat.com/{APPID}/39/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["Extra-Data"] = json.dumps({
            "is_weapp": 1, "sid": session_id, "version": "2.232.5.101",
            "client": "weapp", "bizEnv": "wsc",
        })
    return headers


def api_get(url, token, session_id="", extra_params=None):
    params = {"app_id": APPID, "kdt_id": KDT_ID, "access_token": token}
    if extra_params:
        params.update(extra_params)
    try:
        resp = requests.get(url, params=params, headers=build_headers(token, session_id),
                            timeout=30, proxies={"http": None, "https": None})
        return resp.json()
    except Exception as exc:
        return {"code": -1, "msg": f"网络异常 {brief(exc)}"}


class Daishu:
    def __init__(self, raw_entry):
        self.raw_entry = raw_entry
        self.server, self.ref, self.note = parse_entry(raw_entry)
        self.token = ""
        self.session_id = ""
        self.points = "未知"
        self.nickname = "-"

    def login(self):
        code = get_code(self.raw_entry)
        if not code:
            return False
        try:
            payload = {
                "appId": APPID, "code": code, "platformName": "weapp",
                "signature": "windows", "clientBiz": "weapp_wsc",
                "inWsc": True, "kdtId": KDT_ID,
            }
            resp = requests.post(LOGIN_URL, headers=build_headers(), json=payload,
                                 timeout=30, proxies={"http": None, "https": None})
            data = resp.json()
        except Exception as exc:
            log(f"   ❌ [登录] 请求异常：{brief(exc)}")
            return False
        d = data.get("data") or {}
        token = d.get("accessToken")
        if token and token != "null":
            self.token = token
            self.session_id = d.get("sessionId", "")
            self.nickname = d.get("nickname") or "-"
            log(f"   ✅ [登录] 登录成功，token: {mask(token)}")
            return True
        reason = str(data.get("msg") or data.get("message") or "").strip()
        code_num = to_number(data.get("code"))
        log(f"   ❌ [登录] 登录失败：{brief(reason or f'code={code_num}')}")
        return False

    def fetch_asset(self):
        """只读接口，同时用于开跑前校验缓存"""
        return api_get(ASSET_URL, self.token, self.session_id)

    def read_points(self, asset):
        d = asset.get("data") or {}
        info = d.get("assetInfo") or {}
        points = info.get("currentPoints")
        if points in (None, ""):
            for key in ("points", "currentPoint", "totalPoints"):
                if d.get(key) not in (None, ""):
                    points = d.get(key)
                    break
        if points not in (None, ""):
            self.points = points
        return self.points

    def month_signed(self):
        month = api_get(MONTH_SIGN_URL, self.token, self.session_id, {
            "checkin_id": CHECKIN_ID,
            "year": datetime.now().year,
            "month": datetime.now().month,
        })
        if to_number(month.get("code")) == 0:
            return len((month.get("data") or {}).get("checkin_date") or [])
        return None

    def do_sign(self):
        """返回 (是否成功, 说明, 是否鉴权失败)"""
        sign = api_get(SIGN_URL, self.token, self.session_id, {"checkinId": CHECKIN_ID})
        if to_number(sign.get("code")) == 0:
            d = sign.get("data") or {}
            msg = str(d.get("desc") or "").strip()
            rewards = d.get("list") or []
            title = rewards[0].get("infos", {}).get("title", "") if rewards else ""
            if d.get("success") or "成功" in msg:
                return True, title or msg or "签到成功", False
            if any(word in msg for word in ("已签", "重复", "已达最大参与次数", "无法参与", "已达上限", "今日已")):
                return True, msg or "今日已签到", False
            return False, msg or "未知", False
        msg = str(sign.get("msg") or sign.get("message") or "").strip()
        if any(word in msg for word in ("已签", "重复", "已达最大参与次数", "无法参与", "已达上限", "今日已")):
            return True, msg, False
        return False, msg or f"code={to_number(sign.get('code'))}", is_auth_fail(sign, msg)


def run_account(idx, total, raw_entry):
    server, ref, note = parse_entry(raw_entry)
    if not server or not ref:
        log(f"   ❌ [账号] 第 {idx} 行格式无效，跳过：{brief(raw_entry)}")
        return {"index": idx, "source": str(raw_entry).strip(), "success": False, "error": "账号格式无效"}

    title = f"标识 {ref}" + (f"（{note}）" if note else "")
    account_frame(idx, total, title, str(raw_entry).strip())

    result = {"index": idx, "source": f"{server}@{ref}", "success": False, "loginSource": "",
              "user": "-", "signMsg": "", "monthSigned": None,
              "pointsBefore": "未知", "pointsAfter": "未知", "delta": 0, "error": ""}

    client = Daishu(raw_entry)
    cache = read_cache()
    entry = load_cache_entry(cache, server, ref, raw_entry)
    login_source = ""
    need_login = False

    if entry and entry.get("accessToken"):
        client.token = entry["accessToken"]
        client.session_id = entry.get("sessionId", "")
        client.nickname = entry.get("nickname") or "-"
        log(f"   💾 [缓存] 复用已保存的登录 token（{mask(client.token)}）")
        asset = client.fetch_asset()
        if to_number(asset.get("code")) != 0:
            msg = str(asset.get("msg") or asset.get("message") or "")
            if is_auth_fail(asset, msg):
                log(f"   ♻️ [缓存] 登录凭证未通过开跑前校验（{brief(msg)}），清理缓存后重新登录")
                drop_cache_entry(server, ref)
                client.token = ""
                need_login = True
            else:
                log(f"   ❌ [用户] 缓存 token 校验失败，保留缓存不删除：{brief(msg)}")
                result["error"] = f"缓存 token 校验失败（{msg}）"
                return result
        else:
            login_source = "缓存"
            client.read_points(asset)

    if need_login or not client.token:
        if not client.login():
            result["error"] = "登录失败"
            return result
        login_source = "新登录"
        result["loginSource"] = "新登录"
        save_cache_entry(server, ref, client.token, client.session_id, client.nickname)
        login_source = "新登录"
        asset = client.fetch_asset()
        if to_number(asset.get("code")) != 0:
            msg = str(asset.get("msg") or asset.get("message") or "")
            if is_auth_fail(asset, msg):
                log(f"   ♻️ [登录] 新凭证校验未通过（{brief(msg)}），清理缓存后重登一次")
                drop_cache_entry(server, ref)
                if not client.login():
                    result["error"] = "重登失败"
                    return result
                save_cache_entry(server, ref, client.token, client.session_id, client.nickname)
                asset = client.fetch_asset()
                if to_number(asset.get("code")) != 0:
                    msg2 = str(asset.get("msg") or asset.get("message") or "")
                    log(f"   ❌ [用户] 重登后资产查询仍失败：{brief(msg2)}")
                    result["error"] = f"重登后资产查询失败（{msg2}）"
                    return result
            else:
                log(f"   ❌ [用户] 登录后资产查询失败：{brief(msg)}")
                result["error"] = f"登录后资产查询失败（{msg}）"
                return result
        client.read_points(asset)
        log("   ✅ [校验] 登录凭证校验通过（资产接口）")

    result["loginSource"] = login_source
    result["user"] = client.nickname or "-"
    result["pointsBefore"] = client.points
    log(f"   💰 [积分] 当前 {client.points} 积分")

    signed = client.month_signed()
    result["monthSigned"] = signed
    if signed is not None:
        log(f"   📅 [签到] 当月已签 {signed} 天")

    ok, msg, auth_fail = client.do_sign()
    if auth_fail:
        log(f"   ♻️ [签到] 鉴权失败（{brief(msg)}），清理缓存后重登重跑")
        drop_cache_entry(server, ref)
        if client.login():
            save_cache_entry(server, ref, client.token, client.session_id, client.nickname)
            result["loginSource"] = "签到鉴权失败重登"
            client.read_points(client.fetch_asset())
            time.sleep(1)
            ok, msg, auth_fail = client.do_sign()
    result["signMsg"] = msg
    result["success"] = ok
    if ok:
        signed_now = client.month_signed()
        if signed_now is not None:
            result["monthSigned"] = signed_now
    if ok:
        quiet = any(word in msg for word in ("已签", "重复", "已达最大参与次数", "无法参与", "已达上限"))
        log(f"   {'ℹ️' if quiet else '✅'} [签到] {msg}")
    else:
        log(f"   ❌ [签到] 签到失败：{msg}")

    time.sleep(1)
    client.read_points(client.fetch_asset())
    result["pointsAfter"] = client.points
    before = to_number(result["pointsBefore"])
    after = to_number(result["pointsAfter"])
    delta = after - before if before >= 0 and after >= 0 else 0
    result["delta"] = delta
    log(f"   💰 [积分] {result['pointsBefore']} → {result['pointsAfter']}（{delta:+d}）")

    if result["success"]:
        log("   ✅ [完成] 该账号任务执行完成")
    else:
        log("   ⚠️ [完成] 签到未成功")
    return result


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


def build_notify(results):
    ok = sum(1 for r in results if r.get("success"))
    lines = [f"【{APP_NAME}】每日签到", f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}"]
    for r in results:
        flag = "✅" if r.get("success") else "❌"
        lines.append(f"{flag} 账号{r.get('index')} {r.get('source')}：{r.get('signMsg') or r.get('error') or '-'}"
                     f"（积分 {r.get('pointsBefore')} → {r.get('pointsAfter')}）")
    return "\n".join(lines)


# ====================== 主流程 ======================
def main():
    entries = [line.strip() for line in os.getenv("YYB_SERVER", "").splitlines() if line.strip()]
    if not entries:
        log("❌ 未配置环境变量 YYB_SERVER")
        log("格式：YYB Go 服务地址@微信账号标识[#备注]，多账号换行分隔")
        return []
    valid = [e for e in entries if "@" in e]
    invalid = [e for e in entries if "@" not in e]
    if not valid:
        log("❌ YYB_SERVER 无有效账号（格式：地址@标识[#备注]）")
        return []
    for line in invalid:
        log(f"   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过：{brief(line)}")

    box_top(f"🦘 {APP_NAME} 自动签到")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(valid)} 个" + (f"（{len(invalid)} 行格式无效）" if invalid else ""))
    box_line("💾 缓存", os.path.basename(CACHE_FILE))
    box_bottom()

    results = []
    for i, entry in enumerate(valid, 1):
        try:
            results.append(run_account(i, len(valid), entry))
        except Exception as exc:
            log(f"   ❌ [执行] 账号 {i} 未捕获异常：{brief(exc)}")
            results.append({"index": i, "source": entry, "success": False, "error": f"异常 {brief(exc)}"})
        hr()
        if i < len(valid):
            log("   ⏳ 等待2秒后执行下一个账号...")
            time.sleep(2)

    log()
    for r in results:
        _, ref, note = parse_entry(r.get("source", ""))
        title = (f"标识 {ref}" + (f"（{note}）" if note else "")) if ref else (r.get("source") or "-")
        if r.get("success"):
            log(f"✅ 【账号 {r.get('index')} · {title}】")
            log(f"   🔐 [登录] {r.get('loginSource') or '-'}")
            log(f"   👤 [用户] {r.get('user') or '-'}")
            if r.get("monthSigned") is not None:
                log(f"   📅 [签到] {r.get('signMsg')}（当月已签 {r.get('monthSigned')} 天）")
            else:
                log(f"   📅 [签到] {r.get('signMsg')}")
            log(f"   💰 [积分] {r.get('pointsBefore')} → {r.get('pointsAfter')}（{int(r.get('delta') or 0):+d}）")
        else:
            log(f"❌ 【账号 {r.get('index')} · {title}】")
            log(f"   🔐 [登录] {r.get('loginSource') or '-'}")
            log(f"   📅 [签到] {r.get('signMsg') or '-'}")
            log(f"   ⚠️ [失败] {r.get('error') or r.get('signMsg') or '未知错误'}")

    ok = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok
    total_delta = sum(int(r.get("delta") or 0) for r in results)
    box_top(f"🏁 {APP_NAME} 执行汇总")
    box_line("📊 执行结果", f"成功 {ok} / 失败 {fail} / 共 {len(results)}")
    box_line("💰 积分总变化", f"{total_delta:+d}")
    box_bottom()

    if YYB_NOTIFY:
        content = build_notify(results)
        if send_qinglong_notify(f"{APP_NAME} 签到结果", content):
            log("   📮 [通知] 已调用青龙 notify.py")
        else:
            log("   ℹ️ [通知] 未找到青龙 notify.py")
        if send_pushplus(f"{APP_NAME} 签到结果", content):
            log("   📮 [通知] PushPlus 已发送")
        else:
            log("   ℹ️ [推送] 未配置 PLUSPLUS_TOKEN，跳过 PushPlus")
    else:
        log("   ℹ️ [通知] DSMM_NOTIFY=0，已关闭通知")

    return results


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"❌ 程序异常: {exc}")
