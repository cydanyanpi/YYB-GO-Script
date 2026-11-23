#!/usr/bin/env python3
# name: 小福家
# cron: 30 7,19 * * *
# -*- coding: utf-8 -*-

"""
小福家小程序登录 - 纯 YYB Go 版
code + 手机号加密数据均从 YYB Go 获取

环境变量：
  YYB_SERVER    必填：YYB Go 服务地址@微信账号标识[#备注]，多行换行
  XFJ_NOTIFY    可选：0 关闭通知，默认 1
  PLUSPLUS_TOKEN 可选：PushPlus 推送 token

缓存：脚本目录 token_caches/xfj_token_cache.json，键 地址|标识，不设固定过期

依赖：
  pip install requests
"""

import importlib.util
import json
import os
import re
import sys
import time
import hashlib
from datetime import datetime

import requests

APP_NAME = "小福家"
APPID = "wxe6ba46e6100e68e9"
APPKEY = "b98b1abf926b44e3998e5573b42f101f"
APPSECRET = "e5e3333fbb7448c7813281c68bad7f57"
API_HOST = "api.xiaofujia.com"
API_BASE = f"https://{API_HOST}"
PLATFORM = 12

YYB_NOTIFY = os.getenv("XFJ_NOTIFY", "1").strip() != "0"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "xfj_token_cache.json")

UA_LIST = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49(0x18003121) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.47(0x18002f2c) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.50(0x18003228) NetType/WIFI Language/zh_CN",
]

BOX_WIDTH = 48
BOX_INNER = 46

AUTH_PATTERN = re.compile(
    r"(未登录|登录失效|登录已过期|请重新登录|token\s*(无效|过期|失效)|无效的?\s*token|凭证|授权失败|认证失败|-401|401|403)",
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


def mask_token(token):
    token = str(token or "")
    if len(token) <= 16:
        return token or "-"
    return f"{token[:8]}***{token[-6:]}"


def brief(value, limit=80):
    text = str(value or "").replace("\n", " ")
    return text[: limit - 1] + "…" if len(text) > limit else text


# ====================== 账号解析 ======================
def parse_entry(raw):
    """解析 地址@标识[#备注]，返回 (server, ref, note)"""
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
def read_token_cache():
    try:
        if not os.path.exists(TOKEN_CACHE_FILE):
            return {}
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_token_cache(cache):
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"   ⚠️ [缓存] 写入失败：{exc}")


def load_cache_entry(cache, server, ref, raw):
    """按 地址|标识 读取缓存，命中旧键（标识 / 原始行）即迁移"""
    ck = ckey(server, ref)
    entry = cache.get(ck)
    if isinstance(entry, dict) and entry.get("access_token"):
        return entry
    for legacy in (ref, str(raw).strip()):
        old = cache.get(legacy)
        if isinstance(old, dict) and old.get("access_token"):
            cache[ck] = dict(old)
            cache.pop(legacy, None)
            write_token_cache(cache)
            log("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」")
            return cache[ck]
    return None


def save_cache_entry(server, ref, token):
    cache = read_token_cache()
    cache[ckey(server, ref)] = {"access_token": token, "updatedAt": now_text()}
    write_token_cache(cache)


def drop_cache_entry(server, ref):
    cache = read_token_cache()
    cache.pop(ckey(server, ref), None)
    write_token_cache(cache)


# ====================== YYB ======================
def yyb_post(raw_entry, endpoint, app_id=APPID):
    server, ref, _ = parse_entry(raw_entry)
    if not server or not ref:
        log("   ❌ [YYB] 账号格式无效，应为 地址@标识[#备注]")
        return None
    if not re.match(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$", server) and ":" not in server:
        server = server
    try:
        resp = requests.post(f"http://{server}{endpoint}",
                             json={"ref": ref, "app_id": app_id},
                             timeout=20,
                             proxies={"http": None, "https": None})
        data = resp.json()
    except Exception as exc:
        log(f"   ❌ [YYB] {endpoint} 请求异常：{brief(exc)}")
        return None
    try:
        code_num = int(str(data.get("code")))
    except (TypeError, ValueError):
        code_num = -1
    if code_num != 0:
        reason = str(data.get("message") or data.get("msg") or "").strip()
        log(f"   ❌ [YYB] {endpoint} 失败：{brief(reason or f'code={code_num}')}")
        return None
    result = data.get("data")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            result = {}
    return result or {}


def get_code(raw_entry):
    data = yyb_post(raw_entry, "/wxapp/getCode")
    if not data:
        return None
    payload = data.get("result") or data
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    code = (payload or {}).get("code")
    if not code:
        log("   ❌ [取码] 未取到 code，请检查 YYB 服务与账号标识")
        return None
    log("   ✅ [取码] 取码成功")
    return code


def get_phone_data(raw_entry):
    data = yyb_post(raw_entry, "/wxapp/getPhoneNumber")
    if not data:
        return None
    result = data.get("result") or {}
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            result = {}
    encrypted = result.get("encryptedData") or data.get("encryptedData")
    iv = result.get("iv") or data.get("iv")
    if not encrypted or not iv:
        log("   ❌ [手机号] 加密数据不完整，请确认 YYB 已授权手机号")
        return None
    log("   ✅ [手机号] 获取加密数据成功")
    return {"encryptedData": encrypted, "iv": iv}


def xiaofujia_login(code, mobile):
    login_url = f"{API_BASE}/familychat/user/login"
    auth_token = json.dumps({
        "code": code,
        "mobile_encrypt_data": mobile["encryptedData"],
        "mobile_iv": mobile["iv"],
    })
    body = {
        "auth_type": 2,
        "auth_token": auth_token,
        "platform": PLATFORM,
        "did": "nfPQXpkJaxRQ8BQw4B66KWtWBFXC22SH",
        "metadata": {"launch_mnp_scene": 0},
    }
    t = int(time.time())
    params = {"time": t, "appkey": APPKEY}
    sign_str = "".join(f"{k}{params[k]}" for k in sorted(params)) + APPSECRET
    sign = hashlib.md5(sign_str.encode()).hexdigest()
    full_url = f"{login_url}?time={t}&appkey={APPKEY}&sign={sign}"

    ua = UA_LIST[int(time.time()) % len(UA_LIST)]
    headers = {
        "content-type": "application/json;charset=UTF-8",
        "Host": API_HOST,
        "User-Agent": ua,
        "Referer": f"https://servicewechat.com/{APPID}/116/page-frame.html",
    }
    try:
        resp = requests.post(full_url, json=body, headers=headers, timeout=30)
        data = resp.json()
    except Exception as exc:
        log(f"   ❌ [登录] 请求异常：{brief(exc)}")
        return None
    try:
        code_num = int(str(data.get("code")))
    except (TypeError, ValueError):
        code_num = -1
    if code_num != 0:
        reason = str(data.get("msg") or data.get("message") or "").strip()
        log(f"   ❌ [登录] 登录失败：{brief(reason or f'code={code_num}')}")
        return None
    token = (data.get("data") or {}).get("access_token", "")
    if not token:
        log("   ❌ [登录] 返回中没有 access_token")
        return None
    log(f"   ✅ [登录] 登录成功（{mask_token(token)}，已写入缓存）")
    return token


# ====================== 单账号 ======================
def run_account(idx, total, raw_entry):
    server, ref, note = parse_entry(raw_entry)
    if not server or not ref:
        log(f"   ❌ [账号] 第 {idx} 行格式无效，跳过：{brief(raw_entry)}")
        return {"index": idx, "success": False, "error": "账号格式无效", "token": "", "source": str(raw_entry).strip()}
    title = f"标识 {ref}" + (f"（{note}）" if note else "")
    account_frame(idx, total, title, f"{server}@{ref}")

    result = {"index": idx, "source": f"{server}@{ref}", "success": False,
              "token": "", "loginSource": "", "error": "", "note": note}

    cache = read_token_cache()
    entry = load_cache_entry(cache, server, ref, raw_entry)
    if entry and entry.get("access_token"):
        token = entry["access_token"]
        result["token"] = token
        result["loginSource"] = "缓存"
        result["success"] = True
        log(f"   💾 [缓存] 复用已保存的 access_token（{mask_token(token)}）")
        log(f"   🔑 [TOKEN] {token}")
        log("   ✅ [完成] 该账号token获取完成")
        return result

    code = get_code(raw_entry)
    if not code:
        result["error"] = "取码失败（检查 YYB 服务地址与账号标识）"
        log("   ❌ [登录] 取码失败，跳过该账号")
        return result

    mobile = get_phone_data(raw_entry)
    if not mobile:
        result["error"] = "获取手机号加密数据失败"
        log("   ❌ [登录] 手机号数据缺失，跳过该账号")
        return result

    token = xiaofujia_login(code, mobile)
    if not token:
        result["error"] = "登录失败"
        return result

    save_cache_entry(server, ref, token)
    result["token"] = token
    result["loginSource"] = "新登录"
    result["success"] = True
    log(f"   🔑 [TOKEN] {token}")
    log("   ✅ [完成] 该账号token获取完成")
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
    token = os.getenv("PLUSPLUS_TOKEN") or os.getenv("PUSH_PLUS_TOKEN")
    if not token:
        return False
    try:
        requests.post("http://www.pushplus.plus/send",
                      json={"token": token, "title": title, "content": content, "template": "txt"},
                      timeout=15)
        return True
    except Exception:
        return False


def build_notify(results):
    lines = [f"【{APP_NAME}】token 获取结果"]
    ok = sum(1 for r in results if r.get("success"))
    lines.append(f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}")
    for r in results:
        flag = "✅" if r.get("success") else "❌"
        source = r.get("source") or "-"
        if r.get("success"):
            lines.append(f"{flag} 账号{r.get('index')} {source}：{mask_token(r.get('token'))}")
        else:
            lines.append(f"{flag} 账号{r.get('index')} {source}：{r.get('error') or '失败'}")
    return "\n".join(lines)


# ====================== 主流程 ======================
def main():
    raw_env = os.getenv("YYB_SERVER", "")
    entries = [line.strip() for line in raw_env.splitlines() if line.strip()]
    if not entries:
        log("❌ 未配置环境变量 YYB_SERVER")
        log("格式：YYB Go 服务地址@微信账号标识[#备注]，多账号换行分隔")
        return []
    valid = [e for e in entries if "@" in e]
    if not valid:
        log("❌ YYB_SERVER 无有效账号（格式：地址@标识[#备注]）")
        return []

    box_top(f"🍊 {APP_NAME} 动态 code 登录")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(valid)} 个")
    box_line("💾 缓存", os.path.relpath(TOKEN_CACHE_FILE, SCRIPT_DIR))
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
        title = f"标识 {ref}" + (f"（{note}）" if note else "") if ref else (r.get("source") or "-")
        if r.get("success"):
            log(f"✅ 【账号 {r.get('index')} · {title}】")
            log(f"   🔐 [登录] {r.get('loginSource') or '新登录'}")
            log(f"   🔑 [TOKEN] {r.get('token')}")
        else:
            log(f"❌ 【账号 {r.get('index')} · {title}】")
            log(f"   ⚠️ [失败] {r.get('error') or '未知错误'}")

    ok = sum(1 for r in results if r.get("success"))
    fail = len(results) - ok
    box_top(f"🏁 {APP_NAME} 执行汇总")
    box_line("📊 执行结果", f"成功 {ok} / 失败 {fail} / 共 {len(results)}")
    box_line("🔑 token 获取", f"成功 {ok} 个")
    box_bottom()

    if YYB_NOTIFY:
        content = build_notify(results)
        if send_qinglong_notify(f"{APP_NAME} token 获取结果", content):
            log("   📮 [通知] 已调用青龙 notify.py")
        else:
            log("   ℹ️ [通知] 未找到青龙 notify.py")
        if send_pushplus(f"{APP_NAME} token 获取结果", content):
            log("   📮 [通知] PushPlus 已发送")
        else:
            log("   ℹ️ [推送] 未配置 PLUSPLUS_TOKEN，跳过 PushPlus")
    else:
        log("   ℹ️ [通知] XFJ_NOTIFY=0，已关闭通知")

    return results


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"❌ 程序异常: {exc}")
