#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 鸿星尔克
# cron: 18 9,21 * * *
"""
鸿星尔克小程序 自动签到

环境变量：
- YYB_SERVER        必填；YYB Go 地址@微信账号标识，多账号每行一条，可带 #备注
- HXEK_NOTIFY       默认 1；0=关闭通知（青龙 notify.py 与 PushPlus 一起关）
- PLUSPLUS_TOKEN    可选；配置后额外走 PushPlus 推送

缓存：脚本目录 token_caches/hxek_token_cache.json，按「地址|标识」隔离，不设固定过期
校验：开跑前调用只读接口 sign/get-member-sign-info.json（连签/累计/今日是否已签）
      与 get-member-asset.json（可用积分 D007），失效才重新登录，不拿签到接口兼职校验
"""

import hashlib
import importlib.util
import json
import os
import random
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import requests

APP_NAME = "鸿星尔克"
APP_ID = "wxa1f1fa3785a47c7d"
ENTERPRISE_ID = "ff8080817d9fbda8017dc20674f47fb6"
SECRET = "damogic8888"
BASE_URL = (os.environ.get("HXEK_BASE_URL") or "https://hope.demogic.com").rstrip("/")
LOGIN_URL = f"{BASE_URL}/gic-wx-app/on_login.json"
SIGN_URL = f"{BASE_URL}/gic-wx-app/member_sign.json"
SIGN_INFO_URL = f"{BASE_URL}/gic-wx-app/sign/get-member-sign-info.json"
ASSET_URL = f"{BASE_URL}/gic-wx-app/get-member-asset.json"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(BASE_DIR, "token_caches", "hxek_token_cache.json")
NOTIFY_ENABLED = os.getenv("HXEK_NOTIFY", "1") != "0"
PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")

BOX_WIDTH = 48
BOX_INNER = 46

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541923) XWEB/19823"
)

# 只有明确的会员/登录失效提示才清缓存重登，业务失败（活动结束、太火爆）不重登
AUTH_PATTERN = re.compile(
    r"未登录|登录失效|登录已过期|请重新登录|token\s*(无效|过期|失效)"
    r"|memberId\s*(无效|不存在|错误)|会员不存在|用户不存在|账号异常"
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
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ====================== 工具 ======================
def china_ts() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def mask_id(mid: str) -> str:
    mid = str(mid)
    return mid if len(mid) <= 6 else f"{mid[:3]}****{mid[-3:]}"


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


def deep_find(obj, keys, depth=0):
    """在接口返回里任意层级找指定字段（连续天数/积分等），找不到返回 None"""
    if depth > 6 or obj is None:
        return None
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if v not in (None, "", "?", -1, "-1"):
                return v
        for v in obj.values():
            found = deep_find(v, keys, depth + 1)
            if found not in (None, "", "?", -1, "-1"):
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = deep_find(v, keys, depth + 1)
            if found not in (None, "", "?", -1, "-1"):
                return found
    return None


def brief(value, limit=120):
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


def parse_yyb(raw):
    server, ref, _ = parse_entry(raw)
    return server, ref


def cache_key(server, ref):
    return f"{server}|{ref}"


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


def read_cache_entry(ck, ref, raw):
    cache = read_token_cache()
    if (cache.get(ck) or {}).get("memberId"):
        return cache[ck]
    # 兼容旧版仅按标识存的缓存：读到即迁移
    for key in (ref, raw):
        entry = cache.get(key) or {}
        if entry.get("memberId"):
            cache[ck] = entry
            for k in (ref, raw):
                cache.pop(k, None)
            write_token_cache(cache)
            log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」")
            return entry
    return {}


def save_cache_entry(ck, member_id):
    cache = read_token_cache()
    cache[ck] = {"memberId": member_id, "updatedAt": now_text()}
    write_token_cache(cache)


def drop_cache_entry(ck):
    cache = read_token_cache()
    if ck in cache:
        cache.pop(ck, None)
        write_token_cache(cache)


# ====================== 取码 ======================
def get_wx_code(server_entry: str):
    server, ref, _ = parse_entry(server_entry)
    if not server or not ref:
        log("   ❌ [配置] YYB_SERVER 格式应为 地址@微信账号标识[#备注]")
        return None
    try:
        resp = requests.post(
            f"http://{server}/wxapp/getCode",
            json={"ref": ref, "app_id": APP_ID},
            timeout=20, proxies={"http": None, "https": None},
        )
        data = resp.json()
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
        if code_num == 0 and code:
            log("   ✅ [取码] 取码成功")
            return code
        log(f"   ❌ [取码] 取码失败：{brief(data)}")
        return None
    except Exception as e:
        log(f"   ❌ [取码] 取码异常：{e}")
        log(f"   💡 [提示] 请检查 YYB 服务地址 http://{server} 是否在线、{ref} 是否已登录")
        return None


# ====================== 只读查询接口 ======================
def _member_api(url, member_id, extra=None):
    """GET 只读接口：参数与签名规则同签到接口"""
    ts = china_ts()
    rand = random.randint(1000000, 9999999)
    trans_id = f"{APP_ID}{ts}"
    params = {
        "memberId": member_id, "cliqueId": "-1", "cliqueMemberId": "-1", "useClique": "0",
        "enterpriseId": ENTERPRISE_ID, "sign": make_sign(ts, rand, member_id),
        "random": str(rand), "appid": APP_ID, "transId": trans_id, "timestamp": ts,
        "gicWxaVersion": "3.9.95",
        "launchOptions": json.dumps({"path": "pages/authorize/authorize", "query": {}, "scene": 1027},
                                    ensure_ascii=False, separators=(",", ":")),
    }
    if extra:
        params.update(extra)
    headers = {
        "User-Agent": UA, "sign": ENTERPRISE_ID,
        "Content-Type": "application/json;charset=UTF-8", "Accept": "*/*",
        "Referer": f"https://servicewechat.com/{APP_ID}/89/page-frame.html",
    }
    try:
        res = requests.get(url, params=params, headers=headers,
                           timeout=20, proxies={"http": None, "https": None})
        return res.json()
    except Exception as e:
        log(f"   ⚠️ [接口] 只读请求异常：{e}")
        return None


def query_asset(member_id):
    """会员资产：D007 可用积分 / D010 冻结积分 / D021 今日是否已签 / D022 连签天数"""
    data = _member_api(ASSET_URL, member_id, {"dataIconKeyList": "D007,D010,D021,D022"})
    if not isinstance(data, dict) or str(data.get("code")) != "0":
        return None
    r = data.get("result") or {}
    return {"points": r.get("D007"), "frozen": r.get("D010"),
            "signed": r.get("D021"), "continuous": r.get("D022")}


def query_sign_info(member_id):
    """签到日历：continuousSign 连签天数 / cumulativeSign 累计 / 今日 signFlag"""
    data = _member_api(SIGN_INFO_URL, member_id)
    if not isinstance(data, dict):
        return None
    if str(data.get("code")) != "0":
        msg = str(data.get("message") or data.get("msg") or "")
        return {"ok": False, "msg": msg or "签到日历接口返回异常",
                "auth": bool(AUTH_PATTERN.search(msg))}
    r = data.get("result") or {}
    today = {}
    for d in (r.get("memberSignCalendar") or []):
        if d.get("currentDayFlag") == 1:
            today = d
            break
    return {"ok": True, "continuous": r.get("continuousSign"),
            "cumulative": r.get("cumulativeSign"),
            "signedToday": today.get("signFlag")}


def probe_member(member_id):
    """开跑前只读校验：不调用签到接口，判断登录态是否还有效并取回积分/连签"""
    asset = query_asset(member_id)
    info = query_sign_info(member_id)
    if asset is None and info is None:
        return {"ok": False, "auth": False, "msg": "只读接口无响应（网络异常，未动缓存）"}
    info = info or {}
    valid = bool(info.get("ok")) or asset is not None
    continuous = info.get("continuous")
    if continuous in (None, "", "?", -1, "-1"):
        continuous = (asset or {}).get("continuous")
    signed_today = info.get("signedToday")
    if signed_today is None and asset is not None:
        signed_today = (asset or {}).get("signed")
    return {
        "ok": valid,
        "auth": bool(info.get("auth")),
        "msg": info.get("msg") or "",
        "points": (asset or {}).get("points"),
        "continuous": continuous,
        "cumulative": info.get("cumulative"),
        "signedToday": signed_today,
    }


def apply_member_info(result, info):
    if info.get("points") is not None:
        result["points"] = fmt_points(info["points"])
    if info.get("continuous") not in (None, "", "?", -1, "-1"):
        result["continuous"] = f"{info['continuous']} 天"
    if info.get("cumulative") not in (None, "", "?", -1, "-1"):
        result["cumulative"] = f"{info['cumulative']} 天"
    if info.get("signedToday") in (0, 1):
        result["signedToday"] = int(info["signedToday"])


# ====================== 业务接口 ======================
def make_sign(ts: str, rand: int, member_id: str = "-1") -> str:
    raw = f"timestamp={ts}transId={APP_ID}{ts}secret={SECRET}random={rand}memberId={member_id}"
    return hashlib.md5(raw.encode()).hexdigest()


def build_sys_info() -> str:
    return json.dumps({
        "SDKVersion": "3.16.0", "brand": "microsoft", "model": "microsoft",
        "platform": "windows", "system": "Windows 10 x64", "version": "4.1.9.35",
        "screenHeight": 780, "screenWidth": 414, "windowHeight": 716, "windowWidth": 414,
        "language": "zh_CN", "theme": "light",
    }, ensure_ascii=False, separators=(",", ":"))


def extract_member_id(data):
    if not isinstance(data, dict):
        return None
    for path in [
        ("memberId",), ("member_id",),
        ("response", "memberId"), ("response", "member", "memberId"),
        ("response", "user", "id"),
        ("data", "memberId"), ("data", "member", "memberId"),
    ]:
        cur = data
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur and str(cur) not in ("", "-1"):
            return str(cur)
    return None


def login_by_code(server: str, code: str):
    ts = china_ts()
    rand = random.randint(1000000, 9999999)
    sign = make_sign(ts, rand, "-1")
    body = {
        "systemInfo": build_sys_info(), "jcode": code,
        "openid": "", "scene": "1027",
        "memberId": "-1", "cliqueId": "-1", "cliqueMemberId": "-1", "useClique": "0",
        "enterpriseId": "", "unionid": "", "wxOpenid": "",
        "random": str(rand), "appid": APP_ID,
        "transId": f"{APP_ID}{ts}", "sign": sign, "timestamp": ts,
        "gicWxaVersion": "3.9.74",
        "launchOptions": json.dumps({"path": "pages/authorize/authorize", "query": {}, "scene": 1027},
                                    ensure_ascii=False, separators=(",", ":")),
    }
    headers = {
        "User-Agent": UA, "channelEntrance": "wx_app", "xweb_xhr": "1",
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "*/*",
        "Referer": f"https://servicewechat.com/{APP_ID}/89/page-frame.html",
    }
    try:
        log("   🔐 [登录] 正在换取 memberId...")
        res = requests.post(LOGIN_URL, headers=headers, data=urlencode(body),
                            timeout=30, proxies={"http": None, "https": None})
        data = res.json()
        mid = extract_member_id(data)
        if mid:
            log(f"   ✅ [登录] 登录成功：{mask_id(mid)}")
            return mid
        log(f"   ❌ [登录] 登录失败：{brief(data, 150)}")
        return None
    except Exception as e:
        log(f"   ❌ [登录] 登录异常：{e}")
        return None


def sign_once(member_id: str) -> dict:
    ts = china_ts()
    rand = random.randint(1000000, 9999999)
    sign = make_sign(ts, rand, member_id)
    body = {
        "memberId": member_id, "cliqueId": "-1", "cliqueMemberId": "-1", "useClique": "0",
        "enterpriseId": ENTERPRISE_ID, "random": str(rand), "sign": sign,
        "timestamp": ts, "transId": f"{APP_ID}{ts}", "gicWxaVersion": "3.9.74",
        "launchOptions": json.dumps({"path": "pages/authorize/authorize", "scene": 1256},
                                    ensure_ascii=False, separators=(",", ":")),
    }
    headers = {
        "User-Agent": UA, "channelEntrance": "wx_app", "xweb_xhr": "1",
        "sign": ENTERPRISE_ID, "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*", "Referer": f"https://servicewechat.com/{APP_ID}/89/page-frame.html",
    }
    try:
        res = requests.post(SIGN_URL, headers=headers, data=urlencode(body),
                            timeout=30, proxies={"http": None, "https": None})
        if not res.ok:
            return {"ok": False, "msg": f"HTTP {res.status_code}", "auth": res.status_code in (401, 403)}
        data = res.json()
        errcode = to_number(data.get("errcode"))
        body = data.get("response") or {}
        ms = body.get("memberSign") or {}
        points = body.get("points", "?")
        if points in ("?", None, "", -1, "-1"):
            points = deep_find(data, ("points", "totalPoints", "integralTotal", "score")) or "?"
        continuous = ms.get("continuousCount", "?")
        if continuous in ("?", None, "", "-1", -1):
            continuous = deep_find(data, ("continuousCount", "continuousDays",
                                          "continuousSignCount", "continuousSignDays"))
        if continuous in (None, "", "-1", -1):
            continuous = "?"
        if errcode == 0:
            integral = ms.get("integralCount", "?")
            return {"ok": True, "msg": f"签到成功 +{integral}积分",
                    "points": points, "continuous": continuous, "auth": False}
        errmsg = str(data.get("errmsg") or body.get("errmsg") or "")
        already = any(k in errmsg for k in ("已签", "已经签", "签过", "重复", "已领取", "一签"))
        if already:
            text = f"今日已签到（{errmsg}）" if errmsg and "已经签到" not in errmsg else "今日已签到"
            return {"ok": True, "msg": text, "points": points,
                    "continuous": continuous, "auth": False}
        return {"ok": False, "msg": f"签到失败：{errmsg or brief(data)}",
                "continuous": continuous, "auth": bool(AUTH_PATTERN.search(errmsg))}
    except Exception as e:
        return {"ok": False, "msg": f"请求异常：{e}", "auth": False}


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
        "member": "-",
        "signMsg": "-",
        "points": "未知",
        "continuous": "-",
        "cumulative": "-",
        "signedToday": None,
        "error": "",
    }

    if not server or not ref:
        result["error"] = "YYB_SERVER 格式错误（应为 地址@微信账号标识）"
        log(f"   ❌ [配置] {result['error']}")
        return result

    ck = cache_key(server, ref)
    member_id = ""

    for attempt in range(2):
        # ---------- ① 复用缓存 ----------
        if attempt == 0 and not member_id:
            entry = read_cache_entry(ck, ref, server_entry)
            if entry.get("memberId"):
                member_id = entry["memberId"]
                log(f"   💾 [缓存] 复用已保存的 memberId：{mask_id(member_id)}")
                result["loginSource"] = "缓存"
                result["member"] = mask_id(member_id)

        # ---------- ② 开跑前只读校验（会员资产 + 签到日历，不触发签到） ----------
        if member_id:
            info = probe_member(member_id)
            if info.get("ok"):
                apply_member_info(result, info)
                extra = ""
                if result["cumulative"] != "-":
                    extra += f" ｜ 累计 {result['cumulative']}"
                log(f"   ✅ [校验] 登录态有效 ｜ 连签 {result['continuous']}{extra}"
                    f" ｜ 积分 {result['points']}")
            else:
                log(f"   ⚠️ [校验] 只读接口未通过：{info.get('msg') or '未知'}")
                if info.get("auth") and attempt == 0:
                    log("   🔄 [重试] 会员凭证失效，清理缓存后重新登录")
                    drop_cache_entry(ck)
                    member_id = ""
                    continue

        # ---------- ③ 没有缓存/失效 → 取码登录 ----------
        if not member_id:
            code = get_wx_code(server_entry)
            if not code:
                result["error"] = "取码失败（检查 YYB 服务地址与账号标识）"
                log("   ❌ [登录] 取码失败，跳过该账号")
                return result
            member_id = login_by_code(server, code)
            if not member_id:
                result["error"] = "登录失败（on_login 未返回 memberId，见上方日志）"
                log("   ❌ [登录] 登录失败，跳过该账号")
                return result
            save_cache_entry(ck, member_id)
            result["loginSource"] = "重新登录" if attempt == 1 else "新登录"
            result["member"] = mask_id(member_id)
            info = probe_member(member_id)
            if info.get("ok"):
                apply_member_info(result, info)
                extra = ""
                if result["cumulative"] != "-":
                    extra += f" ｜ 累计 {result['cumulative']}"
                log(f"   ✅ [校验] 登录态有效 ｜ 连签 {result['continuous']}{extra}"
                    f" ｜ 积分 {result['points']}")

        # ---------- ④ 今日已签到则不再发签到请求 ----------
        if result["signedToday"] == 1:
            result["signMsg"] = "今日已签到"
            result["success"] = True
            log(f"   ✅ [签到] 今日已签到（签到日历已确认），跳过签到请求")
            if result["continuous"] != "-":
                log(f"   📆 [连续] 已连续签到 {result['continuous']}")
            log(f"   💰 [积分] 当前 {result['points']} 分")
            log("   ✅ [完成] 该账号任务执行完成")
            return result

        # ---------- ⑤ 签到 ----------
        time.sleep(random.uniform(1, 2))
        sign = sign_once(member_id)
        result["signMsg"] = sign["msg"]
        if sign.get("continuous") not in (None, "", "?", "-1"):
            result["continuous"] = f"{sign['continuous']} 天"
            log(f"   📆 [连续] 已连续签到 {result['continuous']}")
        if sign.get("points", "?") != "?":
            result["points"] = fmt_points(sign.get("points"))

        if sign["ok"]:
            log(f"   ✅ [签到] {sign['msg']}")
            result["success"] = True
            # 签到后复查资产，取真实积分与连签天数
            asset = query_asset(member_id)
            if asset and asset.get("points") is not None:
                result["points"] = fmt_points(asset["points"])
            if asset and str(asset.get("continuous")) not in ("None", "", "-1"):
                result["continuous"] = f"{asset['continuous']} 天"
            log(f"   💰 [积分] 当前 {result['points']} 分" + (
                f" ｜ 连签 {result['continuous']}" if result["continuous"] != "-" else ""))
            log("   ✅ [完成] 该账号任务执行完成")
            return result

        log(f"   ❌ [签到] {sign['msg']}")
        # 只有明确的会员/登录失效才清缓存重登；业务失败直接判失败
        if sign.get("auth") and attempt == 0:
            log("   🔄 [重试] 会员凭证失效，清理缓存重登后重跑一次")
            drop_cache_entry(ck)
            member_id = ""
            continue

        result["error"] = sign["msg"]
        log("   ⚠️ [完成] 签到未成功")
        return result

    result["error"] = result["error"] or "重试后仍未完成（详见上方日志）"
    return result


# ====================== 通知 ======================
def build_notify(results):
    lines = [f"### {APP_NAME} 每日签到"]
    for r in results:
        flag = "✅" if r["success"] else "❌"
        lines.append("")
        lines.append(f"#### {flag} 账号 {r['index']} · {r['source']}")
        if r["loginSource"]:
            lines.append(f"- 登录：{r['loginSource']}")
            lines.append(f"- 会员：{r['member']}")
            lines.append(f"- 签到：{r['signMsg'] or '无结果'}")
            lines.append(f"- 连续：{r['continuous']}" + (
                f"（累计 {r['cumulative']}）" if r["cumulative"] != "-" else ""))
            lines.append(f"- 积分：{r['points']}")
        if not r["success"]:
            lines.append(f"- 失败原因：{r['error'] or '未知'}")
    return "\n".join(lines)


def send_qinglong_notify(title, content):
    if not NOTIFY_ENABLED:
        log("   ℹ️ [通知] HXEK_NOTIFY=0，已关闭通知")
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
            spec = importlib.util.spec_from_file_location("hxek_ql_notify", candidate)
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
    except Exception as e:
        log(f"   ⚠️ [推送] PushPlus 推送失败：{e}")


# ====================== 主入口 ======================
def main():
    servers = [line.strip() for line in os.getenv("YYB_SERVER", "").splitlines() if line.strip()]

    box_top(f"👟 {APP_NAME} 自动签到")
    if not servers:
        box_line("⚠️ 状态", "未配置 YYB_SERVER")
        box_bottom()
        log("格式：YYB Go 地址@微信账号标识，多账号每行一条，可带 #备注")
        return []
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(servers)} 个")
    box_line("💾 缓存", "token_caches/hxek_token_cache.json")
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
                "member": "-",
                "signMsg": "-",
                "points": "未知",
                "continuous": "-",
                "cumulative": "-",
                "signedToday": None,
                "error": f"执行异常：{exc}",
            })
        hr()
        if idx < len(servers):
            log("   ⏳ 等待2秒后执行下一个账号...")
            time.sleep(2)

    print()
    for r in results:
        icon = "✅" if r["success"] else "❌"
        title = f"【账号 {r['index']} · {r['source']}】"
        if r["name"] and r["name"] != r["source"]:
            title = f"【账号 {r['index']} · {r['source']}（{r['name']}）】"
        log(f"{icon} {title}")
        if r["loginSource"]:
            log(f"   🔐 [登录] {r['loginSource']}")
            log(f"   🆔 [会员] {r['member']}")
            log(f"   📅 [签到] {r['signMsg'] or '-'}")
            cont = r["continuous"] if r["continuous"] != "-" else "未知"
            if r["cumulative"] != "-":
                cont = f"{cont}（累计 {r['cumulative']}）"
            log(f"   📆 [连续] {cont}")
            log(f"   💰 [积分] {r['points']}")
        if not r["success"]:
            log(f"   ⚠️ [失败] {r['error'] or '未知原因'}")

    ok_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - ok_count

    box_top(f"🏁 {APP_NAME} 执行汇总")
    box_line("📊 执行结果", f"成功 {ok_count} / 失败 {fail_count} / 共 {len(results)}")
    box_bottom()

    content = build_notify(results)
    send_qinglong_notify(f"{APP_NAME}每日签到", content)
    send_pushplus(f"{APP_NAME}每日签到", content)
    return results


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ 程序异常: {e}")
