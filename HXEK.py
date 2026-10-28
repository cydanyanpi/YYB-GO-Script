#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 鸿星尔克
# cron: 18 9,21 * * *

import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import requests

try:
    import notify
except ImportError:
    notify = None

APP_NAME = "鸿星尔克"
APP_ID = "wxa1f1fa3785a47c7d"
ENTERPRISE_ID = "ff8080817d9fbda8017dc20674f47fb6"
SECRET = "damogic8888"

SERVERS = [line.strip() for line in os.getenv("YYB_SERVER", "").splitlines() if line.strip()]
if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER")
    exit(1)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541923) XWEB/19823"
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "hxek_token_cache.json")


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
    except Exception:
        pass


def china_ts() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def mask_id(mid: str) -> str:
    mid = str(mid)
    return mid if len(mid) <= 6 else f"{mid[:3]}****{mid[-3:]}"


def parse_yyb(raw: str):
    raw = (raw or "").strip()
    if not raw or "@" not in raw:
        return None, None
    server, ref = raw.split("@", 1)
    server = server.strip().replace("http://", "").replace("https://", "").rstrip("/")
    return server, ref.strip()


def get_wx_code(server_entry: str) -> str | None:
    server, ref = parse_yyb(server_entry)
    if not server or not ref:
        return None
    try:
        resp = requests.post(
            f"http://{server}/wxapp/getCode",
            json={"ref": ref, "app_id": APP_ID},
            timeout=20, proxies={"http": None, "https": None},
        )
        data = resp.json()
        code = (((data.get("data") or {}).get("result") or {}).get("code"))
        if data.get("code") == 0 and code:
            print(f"✅ [取码] 获取code成功")
            return code
        print(f"❌ [取码] 获取code失败")
        return None
    except Exception as e:
        print(f"❌ [取码] 获取code异常: {e}")
        return None


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


def extract_member_id(data) -> str | None:
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


def login_by_code(server: str, code: str) -> str | None:
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
        "launchOptions": json.dumps({"path": "pages/authorize/authorize", "query": {}, "scene": 1027}, ensure_ascii=False, separators=(",", ":")),
    }
    headers = {
        "User-Agent": UA, "channelEntrance": "wx_app", "xweb_xhr": "1",
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "*/*",
        "Referer": f"https://servicewechat.com/{APP_ID}/89/page-frame.html",
    }
    try:
        print(f"🔐 [登录] 正在换取memberId...")
        res = requests.post("https://hope.demogic.com/gic-wx-app/on_login.json",
                            headers=headers, data=urlencode(body), timeout=30)
        data = res.json()
        mid = extract_member_id(data)
        if mid:
            print(f"✅ [登录] 登录成功: {mask_id(mid)}")
            return mid
        print(f"❌ [登录] 登录失败: {str(data)[:150]}")
        return None
    except Exception as e:
        print(f"❌ [登录] 登录异常: {e}")
        return None


def sign_once(member_id: str) -> dict:
    ts = china_ts()
    rand = random.randint(1000000, 9999999)
    trans_id = f"{APP_ID}{ts}"
    sign = make_sign(ts, rand, member_id)
    body = {
        "memberId": member_id, "cliqueId": "-1", "cliqueMemberId": "-1", "useClique": "0",
        "enterpriseId": ENTERPRISE_ID, "random": str(rand), "sign": sign,
        "timestamp": ts, "transId": trans_id, "gicWxaVersion": "3.9.74",
        "launchOptions": json.dumps({"path": "pages/authorize/authorize", "scene": 1256}, ensure_ascii=False, separators=(",", ":")),
    }
    headers = {
        "User-Agent": UA, "channelEntrance": "wx_app", "xweb_xhr": "1",
        "sign": ENTERPRISE_ID, "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*", "Referer": f"https://servicewechat.com/{APP_ID}/89/page-frame.html",
    }
    try:
        res = requests.post("https://hope.demogic.com/gic-wx-app/member_sign.json",
                            headers=headers, data=urlencode(body), timeout=30)
        if not res.ok:
            return {"ok": False, "msg": f"HTTP {res.status_code}"}
        data = res.json()
        errcode = data.get("errcode")
        if errcode == 0:
            result = data.get("response") or {}
            ms = result.get("memberSign") or {}
            integral = ms.get("integralCount", "?")
            continuous = ms.get("continuousCount", "?")
            points = result.get("points", "?")
            return {"ok": True, "msg": f"签到成功 +{integral}积分，连续{continuous}天", "points": points}
        errmsg = data.get("errmsg") or (data.get("response") or {}).get("errmsg") or ""
        # 判断是否已签到
        if "已签" in errmsg or "重复" in errmsg:
            return {"ok": True, "msg": "今日已签到", "points": "?"}
        return {"ok": False, "msg": f"签到失败: {errmsg}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


# ====================== 输出美化 ======================
def log_title():
    print()
    print("╔" + "═".repeat(48) + "╗")
    print("║  👟 鸿星尔克 自动签到                          ║")
    print(f"║  🕒 启动时间: {datetime.now().strftime('%Y/%m/%d %H:%M:%S').ljust(22)}║")
    print(f"║  🔢 账号数量: {str(len(SERVERS)).ljust(22)}║")
    print("╚" + "═".repeat(48) + "╝")


def log_account(idx, total, server):
    _, ref = parse_yyb(server)
    print()
    print("┌" + "─".repeat(48) + "┐")
    print(f"│  🧩 账号 {idx} / {total}{' '*26}│")
    print(f"│  🔑 标识: {str(ref or '-').ljust(41)}│")
    print("└" + "─".repeat(48) + "┘")


def log_end(ok, fail):
    print()
    print("╔" + "═".repeat(48) + "╗")
    print("║  🏁 鸿星尔克任务完成                          ║")
    print(f"║  ✅ 成功: {str(ok).ljust(22)}║")
    print(f"║  ❌ 失败: {str(fail).ljust(22)}║")
    print(f"║  🕒 结束时间: {datetime.now().strftime('%Y/%m/%d %H:%M:%S').ljust(22)}║")
    print("╚" + "═".repeat(48) + "╝")


def run_account(idx: int, total: int, server_entry: str) -> bool:
    server, ref = parse_yyb(server_entry)
    log_account(idx, total, server_entry)

    member_id = None
    used_cache = False

    # 读缓存
    cache = read_token_cache()
    cached = cache.get(ref) or {}
    if cached.get("memberId"):
        member_id = cached["memberId"]
        used_cache = True
        print(f"💾 [缓存] 使用缓存memberId: {mask_id(member_id)}")

    for attempt in range(2):
        try:
            if attempt == 1 or not member_id:
                if attempt == 1:
                    print(f"🔄 [重登] memberId失效，清除缓存重新登录...")
                    if ref in cache:
                        del cache[ref]
                        write_token_cache(cache)
                if not member_id:
                    code = get_wx_code(server_entry)
                    if not code:
                        return False
                    member_id = login_by_code(server, code)
                    if not member_id:
                        return False
                    cache = read_token_cache()
                    cache[ref] = {"memberId": member_id}
                    write_token_cache(cache)

            time.sleep(random.uniform(1, 2))
            result = sign_once(member_id)
            if result["ok"]:
                print(f"✅ [签到] {result['msg']}" + (f" | 余额: {result['points']}" if result.get("points") and result["points"] != "?" else ""))
                return True
            else:
                if attempt == 0 and used_cache:
                    print(f"🔄 [重登] 签到失败({result['msg']})，重新登录...")
                    continue
                print(f"❌ [签到] {result['msg']}")
                return False
        except Exception as e:
            print(f"❌ [执行] 异常: {e}")
            return False
    return False


def main():
    log_title()
    ok_count = 0
    fail_count = 0
    for i, srv in enumerate(SERVERS):
        if run_account(i + 1, len(SERVERS), srv):
            ok_count += 1
        else:
            fail_count += 1
        time.sleep(2)
    log_end(ok_count, fail_count)

    if notify:
        lines = [f"鸿星尔克签到: ✅{ok_count} ❌{fail_count}"]
        notify.send(APP_NAME, "\n".join(lines))


if __name__ == "__main__":
    main()
