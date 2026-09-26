#!/usr/bin/env python3
# name: 国乐酱酒
# cron: 41 9,21 * * *
# -*- coding: utf-8 -*-

import os
import json
import time
import requests
from datetime import datetime

APPID = "wxeff120e4d11594c0"
APP_NAME = "国乐酱酒"
BASE = "https://member.guoyuejiu.com"
UA = "Mozilla/5.0 (Linux; Android 15; 22061218C Build/AQ3A.250226.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.177 Mobile Safari/537.36 XWEB/1460075 MMWEBSDK/20260202 MMWEBID/6435 MicroMessenger/8.0.71.3080(0x18004739) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 MiniProgramEnv/android"

# ========== 从 YYB_SERVER 读取服务地址 ==========
SERVERS = []
env_YYB_SERVER = os.getenv("YYB_SERVER", "")
if env_YYB_SERVER:
    SERVERS = [line.strip() for line in env_YYB_SERVER.splitlines() if line.strip()]
if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER")
    print("格式：地址@微信账号标识，多账号换行分隔")
    exit(1)
print(f"✅ 读取到 {len(SERVERS)} 个 YYB Go 账号")


# ============ Token 缓存 ============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "guoyue_token_cache.json")


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
    except Exception as e:
        print(f"  [缓存] 写入失败: {e}")


def parse_yyb_go_entry(raw_value: str):
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None, None
    if "@" not in raw_value:
        print(f"❌ YYB_SERVER 格式应为 地址@微信账号标识，当前值：{raw_value}")
        return None, None
    server, ref = raw_value.split("@", 1)
    server = server.strip()
    ref = ref.strip()
    if server.startswith("http://"):
        server = server[7:]
    elif server.startswith("https://"):
        server = server[8:]
    server = server.rstrip("/")
    if not server or not ref:
        return None, None
    return server, ref


def get_wx_code(server_entry: str) -> str | None:
    parsed_server, ref = parse_yyb_go_entry(server_entry)
    if not parsed_server or not ref:
        return None
    url = f"http://{parsed_server}/wxapp/getCode"
    try:
        resp = requests.post(url, json={"ref": ref, "app_id": APPID}, timeout=20,
                             proxies={"http": None, "https": None})
        data = resp.json()
        code = (((data.get("data") or {}).get("result") or {}).get("code"))
        if data.get("code") == 0 and code:
            print(f"✅ 获取code成功")
            return code
        print(f"❌ 获取code失败: {data}")
        return None
    except Exception as e:
        print(f"❌ 获取code异常: {e}")
        return None


def code_login(server_entry: str) -> str | None:
    code = get_wx_code(server_entry)
    if not code:
        return None
    try:
        payload = {
            "avatarUrl": "https://thirdwx.qlogo.cn/mmopen/vi_32/POgEwh4mIHO4nibH0KlMECNjjGxQUq24ZEaGT4poC6icRiccVGKSyXwibcPq4BWmiaIGuG1icwxaQX6grC9VemZoJ8rg/132",
            "city": "",
            "country": "",
            "gender": 0,
            "nickName": "微信用户",
            "province": "",
            "code": code,
            "source": 2
        }
        resp = requests.post(f"{BASE}/api/user/wxLogin", json=payload,
                             headers={"User-Agent": UA, "Content-Type": "application/json"},
                             timeout=10, proxies={"http": None, "https": None})
        data = resp.json()
        if data.get("code") == 0:
            print("✅ 登录成功")
            return (data.get("data") or {}).get("authorization")
        print(f"❌ 登录失败: {data.get('message', '')}")
    except Exception as e:
        print(f"❌ 登录异常: {e}")
    return None


def daily_sign(token: str) -> dict:
    result = {"success": False, "msg": "", "span_days": 0}
    try:
        resp = requests.get(f"{BASE}/api/sign/daily/sign",
                            headers={
                                "Authorization": f"Mer{token}",
                                "User-Agent": UA,
                                "Referer": f"https://servicewechat.com/{APPID}/87/page-frame.html"
                            }, timeout=10, proxies={"http": None, "https": None})
        data = resp.json()
        if data.get("code") == 0:
            result["success"] = True
            result["msg"] = "签到成功"
            result["span_days"] = (data.get("data") or {}).get("spanSumDays", 0)
            print(f"📊 签到成功 | 连续 {result['span_days']} 天")
        else:
            result["msg"] = data.get("message", "")
            print(f"❌ 签到失败：{result['msg']}")
    except Exception as e:
        result["msg"] = f"签到异常: {e}"
        print(f"❌ 签到异常: {e}")
    return result


def get_points(token: str) -> dict:
    result = {"success": False, "score": 0}
    try:
        resp = requests.get(f"{BASE}/api/user/info",
                            headers={
                                "Authorization": f"Mer{token}",
                                "User-Agent": UA
                            }, timeout=10, proxies={"http": None, "https": None})
        data = resp.json()
        if data.get("code") == 0:
            result["success"] = True
            result["score"] = (data.get("data") or {}).get("score", 0)
            print(f"💰 总积分：{result['score']}")
    except Exception as e:
        print(f"❌ 查询积分异常: {e}")
    return result


def run_account(entry: str) -> bool:
    _, wxid = parse_yyb_go_entry(entry)
    print(f"\n{'=' * 40}")
    print(f" 国乐酱酒 | {wxid} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 40}")

    time.sleep(1.5)

    cache = read_token_cache()
    cached = cache.get(wxid) or {}
    token = cached.get("authorization", "")

    def do_login():
        t = code_login(entry)
        if t:
            c = read_token_cache()
            c[wxid] = {"authorization": t}
            write_token_cache(c)
            print("  [缓存] 新登录 token 已写入缓存")
        return t

    if token:
        print(f"  [缓存] 使用缓存 token: {token[:12]}...")
        pt = get_points(token)
        if not pt.get("success"):
            print("  [重登] 缓存 token 已失效，清除缓存重新登录...")
            cache = read_token_cache()
            cache.pop(wxid, None)
            write_token_cache(cache)
            token = ""

    if not token:
        token = do_login()
        if not token:
            print("❌ 登录失败，跳过")
            return False

    daily_sign(token)
    get_points(token)
    time.sleep(1)
    return True


try:
    import notify
except ImportError:
    notify = None

if __name__ == "__main__":
    results = []
    for i, entry in enumerate(SERVERS):
        ok = run_account(entry)
        results.append(f"{entry}: {'✅' if ok else '❌'}")
        if i < len(SERVERS) - 1:
            time.sleep(5)

    print("\n".join(results))
    if notify:
        notify.send(APP_NAME, "\n".join(results))
