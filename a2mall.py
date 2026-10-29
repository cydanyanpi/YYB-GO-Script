#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: a2官方商城
# cron: 0 8 * * *

import os
import json
import time
import uuid
import requests
from datetime import datetime

APP_ID = "wx33cf9bf4dff9388d"
KDT_ID = "113745713"
CHECKIN_ID = "3800805"
BASE_URL = "https://h5.youzan.com"
LOGIN_URL = "https://uic.youzan.com/passport/general/auth.json"
CHECKIN_URL = f"{BASE_URL}/wscump/checkin/checkinV2.json"
ACTIVITY_URL = f"{BASE_URL}/wscump/checkin/get_activity_by_yzuid_v2.json"
USER_INFO_URL = f"{BASE_URL}/wscuser/membercenter/present.json"

SERVERS = [s.strip() for s in os.getenv("YYB_SERVER", "").splitlines() if s.strip()]
if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER")
    exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "a2mall_token_cache.json")


def read_cache():
    try:
        if not os.path.exists(CACHE_FILE):
            return {}
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_cache(c):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mask(v):
    v = str(v or "")
    return v if len(v) <= 16 else f"{v[:8]}...{v[-8:]}"


def parse_yyb(raw):
    raw = (raw or "").strip()
    if not raw or "@" not in raw:
        return None, None
    s, ref = raw.split("@", 1)
    s = s.strip().replace("http://", "").replace("https://", "").rstrip("/")
    return s, ref.strip()


def get_code(server):
    s, ref = parse_yyb(server)
    if not s or not ref:
        return None
    try:
        r = requests.post(f"http://{s}/wxapp/getCode",
                          json={"ref": ref, "app_id": APP_ID},
                          timeout=20, proxies={"http": None, "https": None})
        data = r.json()
        if data.get("code") == 0:
            result = data.get("data", {}).get("result", {})
            return result.get("code") if isinstance(result, dict) else None
    except Exception:
        pass
    return None


def log_title():
    print()
    print("╔" + "═" * 48 + "╗")
    print("║  🛍️ a2官方商城 自动签到                       ║")
    print(f"║  🕒 启动时间: {now_text().ljust(22)}║")
    print(f"║  🔢 账号数量: {str(len(SERVERS)).ljust(22)}║")
    print("╚" + "═" * 48 + "╝")


def log_account(i, total, server):
    _, ref = parse_yyb(server)
    print()
    print("┌" + "─" * 48 + "┐")
    print(f"│  🧩 账号 {i} / {total}{' ' * 26}│")
    print(f"│  🔑 标识: {str(ref or '-').ljust(41)}│")
    print("└" + "─" * 48 + "┘")


def log_end(ok, fail):
    print()
    print("╔" + "═" * 48 + "╗")
    print("║  🏁 a2商城任务完成                            ║")
    print(f"║  ✅ 成功: {str(ok).ljust(22)}║")
    print(f"║  ❌ 失败: {str(fail).ljust(22)}║")
    print(f"║  🕒 结束时间: {now_text().ljust(22)}║")
    print("╚" + "═" * 48 + "╝")


class A2Mall:
    def __init__(self, server, idx):
        self.server = server
        self.idx = idx
        self.token = ""
        self.session_id = ""
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; Redmi K30 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.50.2701 MiniProgramEnv/android",
            "Content-Type": "application/json",
            "Referer": f"https://servicewechat.com/{APP_ID}/33/page-frame.html",
        })

    def login(self):
        code = get_code(self.server)
        if not code:
            print("❌ [取码] 获取code失败")
            return False
        try:
            r = self.s.post(f"{LOGIN_URL}?kdt_id={KDT_ID}&app_id={APP_ID}", json={
                "appId": APP_ID, "code": code, "platformName": "weapp",
                "signature": "windows", "clientId": "4d65249d377b2c3ed8",
                "grantType": "yz_union", "inWsc": True, "kdtId": KDT_ID,
            }, timeout=20)
            data = r.json()
            if data.get("code") == 0:
                self.token = data.get("data", {}).get("accessToken", "")
                self.session_id = data.get("data", {}).get("sessionId", "")
                if self.token:
                    print(f"✅ [登录] 登录成功: {mask(self.token)}")
                    return True
            print(f"❌ [登录] {data.get('msg', data)}")
        except Exception as e:
            print(f"❌ [登录] {e}")
        return False

    def _url(self, url):
        return f"{url}?app_id={APP_ID}&kdt_id={KDT_ID}&access_token={self.token}"

    def get_user_info(self):
        try:
            r = self.s.get(self._url(USER_INFO_URL), timeout=20)
            data = r.json()
            if data.get("code") == 0:
                d = data.get("data")
                if isinstance(d, dict):
                    print(f"👤 [用户] {d.get('nickname', '匿名')} {d.get('levelName', '')}")
        except Exception:
            pass

    def checkin_status(self):
        try:
            r = self.s.get(self._url(ACTIVITY_URL) + f"&checkinId={CHECKIN_ID}", timeout=20)
            data = r.json()
            if data.get("code") == 0:
                d = data.get("data", {})
                return d.get("isCheckin", False), d.get("continuesDay", 0)
        except Exception:
            pass
        return None, 0

    def do_checkin(self):
        try:
            headers = {}
            if self.session_id:
                extra = {
                    "is_weapp": 1, "sid": self.session_id,
                    "version": "2.197.11.201", "client": "weapp",
                    "bizEnv": "wsc", "uuid": str(uuid.uuid4()),
                    "ftime": int(time.time() * 1000),
                }
                headers["extra-data"] = json.dumps(extra)
            r = self.s.get(self._url(CHECKIN_URL) + f"&checkinId={CHECKIN_ID}",
                           headers=headers, timeout=20)
            data = r.json()
            if data.get("code") != 0:
                msg = data.get("msg", "")
                if "已签到" in msg or "上限" in msg:
                    print("ℹ️ [签到] 今日已签到")
                    return True
                print(f"❌ [签到] {msg}")
                return False
            d = data.get("data", {})
            if d.get("success"):
                rewards = []
                for item in d.get("list", []):
                    if item.get("isSuccess"):
                        rewards.append(item.get("infos", {}).get("title", ""))
                print(f"✅ [签到] 签到成功: {', '.join(rewards) or '+'}{'，连续' + str(d.get('times', 1)) + '天' if d.get('times') else ''}")
                return True
            print("❌ [签到] 签到失败")
        except Exception as e:
            print(f"❌ [签到] {e}")
        return False

    def run(self):
        _, ref = parse_yyb(self.server)
        cache = read_cache()
        cached = cache.get(ref) or {}
        if cached.get("token"):
            self.token = cached["token"]
            self.session_id = cached.get("session_id", "")
            print(f"💾 [缓存] 使用缓存token: {mask(self.token)}")

        for attempt in range(2):
            try:
                if attempt == 1 or not self.token:
                    if attempt == 1:
                        print("🔄 [重登] token失效，重新登录...")
                        c = read_cache()
                        if ref in c:
                            del c[ref]
                            write_cache(c)
                    if not self.login():
                        return False

                self.get_user_info()
                time.sleep(1)
                is_ci, days = self.checkin_status()
                if is_ci:
                    print(f"ℹ️ [签到] 今日已签到，连续{days}天")
                    c = read_cache()
                    c[ref] = {"token": self.token, "session_id": self.session_id}
                    write_cache(c)
                    return True
                if is_ci is False:
                    print(f"📊 [签到] 当前连续{days}天")
                time.sleep(1)
                ok = self.do_checkin()
                c = read_cache()
                c[ref] = {"token": self.token, "session_id": self.session_id}
                write_cache(c)
                return ok
            except Exception as e:
                print(f"❌ [执行] {e}")
                return False
        return False


def main():
    log_title()
    ok, fail = 0, 0
    for i, srv in enumerate(SERVERS, 1):
        log_account(i, len(SERVERS), srv)
        if A2Mall(srv, i).run():
            ok += 1
        else:
            fail += 1
        time.sleep(2)
    log_end(ok, fail)


if __name__ == "__main__":
    main()
#（注：内容由AI生成）
