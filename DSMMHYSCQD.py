#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 袋鼠妈妈会员商场签到
# cron: 8 16,4 * * *

import json
import os
import random
import time
from datetime import datetime
from typing import Any, Dict
from urllib.parse import urlencode

import requests

APP_NAME = "袋鼠妈妈"
APPID = "wxb27b46293d405a20"
KDT_ID = "44587018"
CHECKIN_ID = "17019"

SERVERS = [s.strip() for s in os.getenv("YYB_SERVER", "").splitlines() if s.strip()]
if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER")
    exit(1)

BASE_URL = "https://h5.youzan.com"
LOGIN_URL = f"https://uic.youzan.com/passport/general/auth.json?kdt_id={KDT_ID}&app_id={APPID}"
SIGN_URL = f"{BASE_URL}/wscump/checkin/checkinV2.json"
MONTH_SIGN_URL = f"{BASE_URL}/wscump/checkin/find_checkin_info_by_month.json"
ASSET_URL = f"{BASE_URL}/retail/h5/showcase/getAssetInfo.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541923) XWEB/19899"
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "dsmmhyscqd_token_cache.json")


def read_cache() -> dict:
    try:
        if not os.path.exists(CACHE_FILE):
            return {}
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_cache(c: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mask(v: str) -> str:
    v = str(v or "")
    return v if len(v) <= 12 else f"{v[:6]}...{v[-6:]}"


def parse_yyb(raw: str):
    raw = (raw or "").strip()
    if not raw or "@" not in raw:
        return None, None
    server, ref = raw.split("@", 1)
    server = server.strip().replace("http://", "").replace("https://", "").rstrip("/")
    return server, ref.strip()


def get_code(server: str) -> str | None:
    s, ref = parse_yyb(server)
    if not s or not ref:
        return None
    try:
        r = requests.post(f"http://{s}/wxapp/getCode",
                          json={"ref": ref, "app_id": APPID},
                          timeout=20, proxies={"http": None, "https": None})
        code = r.json().get("data", {}).get("result", {}).get("code")
        if code:
            print(f"✅ [取码] 获取code成功")
            return code
        print(f"❌ [取码] 获取code失败")
        return None
    except Exception as e:
        print(f"❌ [取码] 异常: {e}")
        return None


def headers(token: str = "", session_id: str = "") -> dict:
    h = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "Referer": f"https://servicewechat.com/{APPID}/39/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        h["Extra-Data"] = json.dumps({
            "is_weapp": 1, "sid": session_id, "version": "2.232.5.101",
            "client": "weapp", "bizEnv": "wsc",
        })
    return h


def api_get(url: str, token: str, session_id: str = "", extra_params: dict = None) -> dict:
    params = {"app_id": APPID, "kdt_id": KDT_ID, "access_token": token}
    if extra_params:
        params.update(extra_params)
    try:
        r = requests.get(url, params=params, headers=headers(token, session_id),
                         timeout=30, proxies={"http": None, "https": None})
        return r.json()
    except Exception as e:
        return {"code": -1, "msg": str(e)}


def is_auth_fail(msg) -> bool:
    import re
    return bool(re.search(r'登录|未登录|授权|token|失效|过期|登录态|请重新|身份|凭证|access|invalid session|session.*invalid', str(msg), re.IGNORECASE))


# ====================== 输出美化 ======================
def log_title():
    print()
    print("╔" + "═" * 48 + "╗")
    print("║  🦘 袋鼠妈妈 自动签到                          ║")
    print(f"║  🕒 启动时间: {now_text().ljust(22)}║")
    print(f"║  🔢 账号数量: {str(len(SERVERS)).ljust(22)}║")
    print("╚" + "═" * 48 + "╝")


def log_account(idx, total, server):
    _, ref = parse_yyb(server)
    print()
    print("┌" + "─" * 48 + "┐")
    print(f"│  🧩 账号 {idx} / {total}{' ' * 26}│")
    print(f"│  🔑 标识: {str(ref or '-').ljust(41)}│")
    print("└" + "─" * 48 + "┘")


def log_end(ok, fail):
    print()
    print("╔" + "═" * 48 + "╗")
    print("║  🏁 袋鼠妈妈任务完成                          ║")
    print(f"║  ✅ 成功: {str(ok).ljust(22)}║")
    print(f"║  ❌ 失败: {str(fail).ljust(22)}║")
    print(f"║  🕒 结束时间: {now_text().ljust(22)}║")
    print("╚" + "═" * 48 + "╝")


class Daishu:
    def __init__(self, server, idx):
        self.server = server
        self.idx = idx
        self.token = ""
        self.session_id = ""

    def login(self) -> bool:
        code = get_code(self.server)
        if not code:
            return False
        try:
            payload = {
                "appId": APPID, "code": code, "platformName": "weapp",
                "signature": "windows", "clientBiz": "weapp_wsc",
                "inWsc": True, "kdtId": KDT_ID,
            }
            r = requests.post(LOGIN_URL, headers=headers(), json=payload,
                              timeout=30, proxies={"http": None, "https": None})
            data = r.json()
            token = data.get("data", {}).get("accessToken")
            if token and token != "null":
                self.token = token
                self.session_id = data.get("data", {}).get("sessionId", "")
                nickname = data.get("data", {}).get("nickname", "未知")
                print(f"✅ [登录] 登录成功: {nickname} ({mask(token)})")
                return True
            print(f"❌ [登录] 登录失败: {json.dumps(data, ensure_ascii=False)[:150]}")
            return False
        except Exception as e:
            print(f"❌ [登录] 异常: {e}")
            return False

    def run(self) -> bool:
        s, ref = parse_yyb(self.server)
        cache = read_cache()
        cached = cache.get(ref) or {}
        if cached.get("accessToken"):
            self.token = cached["accessToken"]
            self.session_id = cached.get("sessionId", "")
            print(f"💾 [缓存] 使用缓存token: {mask(self.token)}")

        for attempt in range(2):
            try:
                if attempt == 1:
                    print(f"🔄 [重登] token失效，清除缓存重新登录...")
                    c = read_cache()
                    if ref in c:
                        del c[ref]
                        write_cache(c)
                    if not self.login():
                        return False
                if not self.token:
                    if not self.login():
                        return False

                # 查资产
                asset = api_get(ASSET_URL, self.token, self.session_id)
                if asset.get("code") == 0:
                    d = asset.get("data", {})
                    points = d.get("assetInfo", {}).get("currentPoints", "?")
                    print(f"💰 [积分] 当前积分: {points}")
                else:
                    msg = asset.get("msg", "")
                    if attempt == 0 and is_auth_fail(msg):
                        print(f"🔄 [重登] 鉴权失败({msg})，重新登录...")
                        self.token = ""
                        continue

                # 查当月签到
                month = api_get(MONTH_SIGN_URL, self.token, self.session_id, {
                    "checkin_id": CHECKIN_ID,
                    "year": datetime.now().year,
                    "month": datetime.now().month,
                })
                if month.get("code") == 0:
                    dates = month.get("data", {}).get("checkin_date", [])
                    print(f"📅 [签到] 当月已签: {len(dates)}天")

                # 执行签到
                sign = api_get(SIGN_URL, self.token, self.session_id, {
                    "checkinId": CHECKIN_ID,
                })
                if sign.get("code") == 0:
                    d = sign.get("data", {})
                    if d.get("success"):
                        rewards = d.get("list", [])
                        rwd = rewards[0].get("infos", {}).get("title", "") if rewards else ""
                        print(f"✅ [签到] 签到成功: {rwd}")
                    else:
                        msg = d.get("desc", "未知")
                        if "已签" in msg or "重复" in msg:
                            print(f"ℹ️ [签到] 今日已签到")
                        else:
                            print(f"⚠️ [签到] {msg}")
                else:
                    msg = sign.get("msg", "")
                    if is_auth_fail(msg) and attempt == 0:
                        print(f"🔄 [重登] 签到鉴权失败({msg})，重新登录...")
                        self.token = ""
                        continue
                    print(f"❌ [签到] 签到失败: {msg}")

                # 保存缓存
                c = read_cache()
                c[ref] = {"accessToken": self.token, "sessionId": self.session_id}
                write_cache(c)
                return True
            except Exception as e:
                print(f"❌ [执行] 异常: {e}")
                return False
        return False


def main():
    log_title()
    ok, fail = 0, 0
    for i, srv in enumerate(SERVERS):
        log_account(i + 1, len(SERVERS), srv)
        if Daishu(srv, i + 1).run():
            ok += 1
        else:
            fail += 1
        time.sleep(1.5)
    log_end(ok, fail)


if __name__ == "__main__":
    main()
