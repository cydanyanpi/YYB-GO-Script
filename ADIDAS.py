#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: adidas会员中心
# cron: 8 15,3 * * *

import os
import json
import time
import base64
import random
import requests
from datetime import datetime
from urllib.parse import urlencode

APPID = "wx771a28fa51fa2b99"
ANA_URL = "https://auth.api.adidas.com.cn"
CRM_URL = "https://consumer-hub.adidas.com.cn"
ADICLUB_URL = "https://adiclub.adidas.com.cn"
WORLDCUP_URL = "https://worldcuphub.adidas.com.cn"
ANA_API_KEY = "IGKGyiqaNnLLJrvEc4k5C66VXxMSZDcx"
ANA_SOURCE = "M003"
RULE_CODE = "IP240320080"
CRM_CHANNEL = "MemberHub"
CRM_SUB_CHANNEL = "AdiClub"
DEFAULT_CAMPAIGNS = ["BABYMONSTER"]

SERVERS = [s.strip() for s in os.getenv("YYB_SERVER", "").splitlines() if s.strip()]
if not SERVERS:
    print("❌ 未配置环境变量 YYB_SERVER")
    exit(1)

UA = (
    "Mozilla/5.0 (Linux; Android 10; Redmi K30 Pro Build/QKQ1.191222.002) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Mobile Safari/537.36 "
    "MicroMessenger/8.0.50.2701(0x28003239) WeChat/arm64 Weixin NetType/WIFI "
    "MiniProgramEnv/android"
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "adidas_token_cache.json")


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
                          json={"ref": ref, "app_id": APPID},
                          timeout=20, proxies={"http": None, "https": None})
        code = r.json().get("data", {}).get("result", {}).get("code")
        return code or None
    except Exception:
        return None


def log_title():
    print()
    print("╔" + "═" * 48 + "╗")
    print("║  👟 adidas会员中心 自动签到                    ║")
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
    print("║  🏁 adidas任务完成                            ║")
    print(f"║  ✅ 成功: {str(ok).ljust(22)}║")
    print(f"║  ❌ 失败: {str(fail).ljust(22)}║")
    print(f"║  🕒 结束时间: {now_text().ljust(22)}║")
    print("╚" + "═" * 48 + "╝")


def ana_headers():
    return {
        "api-key": ANA_API_KEY, "source": ANA_SOURCE,
        "x-requested-with": "com.tencent.mm",
        "Referer": f"https://servicewechat.com/{APPID}/",
        "User-Agent": UA,
    }


def biz_headers(token):
    h = ana_headers()
    h["Authorization"] = f"Bearer {token}"
    return h


def post_json(url, payload, headers=None):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    h.update(headers or {})
    try:
        r = requests.post(url, json=payload, headers=h, timeout=20, verify=False)
        return r.status_code, r.json()
    except Exception as e:
        return None, str(e)


def get_json(url, headers=None, params=None):
    h = {"Accept": "application/json"}
    h.update(headers or {})
    try:
        r = requests.get(url, params=params, headers=h, timeout=20, verify=False)
        return r.status_code, r.json()
    except Exception as e:
        return None, str(e)


def post_form(url, payload, headers=None):
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    h.update(headers or {})
    try:
        r = requests.post(url, data=urlencode(payload), headers=h, timeout=20, verify=False)
        return r.status_code, r.json()
    except Exception as e:
        return None, str(e)


def decode_jwt(token):
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        p = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(p).decode())
    except Exception:
        return {}


class Adidas:
    def __init__(self, server, idx):
        self.server = server
        self.idx = idx
        self.token = ""
        self.member = {}

    def login(self):
        code = get_code(self.server)
        if not code:
            print("❌ [取码] 获取code失败")
            return False
        try:
            sc, data = post_form(f"{ANA_URL}/ana/v1/users/login/mini", {
                "accessCode": code, "approach": "mini",
                "crmChannel": CRM_CHANNEL, "crmSubChannel": CRM_SUB_CHANNEL,
                "crmStoreCode": "WECHAT",
            }, headers=ana_headers())
            token = (data or {}).get("data", {}).get("access_token")
            if token:
                self.token = token
                print(f"✅ [登录] 登录成功: {mask(token)}")
                return True
            print(f"❌ [登录] 登录失败: {str(data)[:150]}")
        except Exception as e:
            print(f"❌ [登录] 异常: {e}")
        return False

    def get_member(self):
        sc, data = get_json(f"{CRM_URL}/v1/adiclub/public/consumer/query",
                            headers=biz_headers(self.token),
                            params={"channel": CRM_CHANNEL, "subChannel": CRM_SUB_CHANNEL})
        if sc == 200 and str(data.get("resultCode")) == "200":
            self.member = data.get("data", {})
            pts = self.member.get("availablePoints", "?")
            tier = self.member.get("memberTier", "?")
            print(f"👤 [用户] 等级: {tier}，积分: {pts}")
            return self.member
        return None

    def daily_sign(self):
        sc, data = post_json(f"{CRM_URL}/v1/adiclub/public/points/points-add", {
            "ruleCode": RULE_CODE, "channel": CRM_CHANNEL, "subChannel": CRM_SUB_CHANNEL,
        }, headers=biz_headers(self.token))
        text = str(data)
        if "already" in text.lower() or "已签" in text:
            print("ℹ️ [签到] 今日已签到")
        elif "success" in text.lower() or str(data.get("resultCode")) == "200":
            print("✅ [签到] 签到成功")
        else:
            print(f"ℹ️ [签到] {text[:100]}")

    def worldcup_tasks(self):
        jwt = decode_jwt(self.token)
        member_id = jwt.get("member_id") or self.member.get("consumerCode", "")
        union_id = jwt.get("union_id_1", "")
        if not member_id or not union_id:
            print("ℹ️ [足球] 未解析到member_id/union_id，跳过")
            return

        wc_headers = {"userId": "", "token": "", "platform": "ADICLUB", "wmsuserid": "1"}

        def wc_post(path, data=None):
            payload = dict(data or {})
            payload["timestamp"] = int(time.time() * 1000)
            try:
                r = requests.post(f"{WORLDCUP_URL}{path}", data=payload,
                                  headers=wc_headers, timeout=20, verify=False)
                return r.json()
            except Exception:
                return {}

        # 登录足球街区
        login = wc_post("/api/user/login", {"consumerCode": member_id, "unionId": union_id})
        if login.get("code") != 200:
            print(f"ℹ️ [足球] 登录失败: {str(login)[:100]}")
            return
        wc_user_id = login.get("data", {}).get("user", {}).get("id") or login.get("data", {}).get("id")
        wc_token = login.get("data", {}).get("token", "")
        wc_headers["userId"] = str(wc_user_id)
        wc_headers["token"] = wc_token
        print(f"⚽ [足球] 足球街区登录成功 userId={wc_user_id}")

        # 任务列表
        task_info = wc_post("/api/userTask/info", {"userId": wc_user_id})
        tasks = task_info.get("data", {})

        # 分享
        if tasks.get("shareActivity", 0) == 0:
            wc_post("/api/userTask/finished", {"userId": wc_user_id, "type": 4})
            print("  ✅ [足球] 分享活动完成")
            time.sleep(2)

        # 浏览商品
        if tasks.get("visitShop", 0) == 0:
            wc_post("/api/userTask/finished", {"userId": wc_user_id, "type": 5})
            print("  ✅ [足球] 浏览商品完成")
            time.sleep(3)

        # 观看影片
        if tasks.get("playVideo", 0) == 0:
            wc_post("/api/userTask/finished", {"userId": wc_user_id, "type": 7})
            print("  ✅ [足球] 观看影片完成")
            time.sleep(3)

        # 抽奖
        user_info = wc_post("/api/user/info", {"id": wc_user_id, "refreshPoints": True})
        lottery_chance = int(user_info.get("data", {}).get("lotteryChange", 0) or 0)
        lottery_today = int(user_info.get("data", {}).get("lotteryCountToday", 0) or 0)
        if lottery_chance > 0 and lottery_today > 0:
            for i in range(min(lottery_chance, lottery_today)):
                time.sleep(3)
                result = wc_post("/api/lotteryPrizeRecord/lottery",
                                 {"activityId": 1, "poolNo": 2, "userId": wc_user_id})
                d = result.get("data", {})
                ptype = d.get("type", -1)
                title = d.get("title", "未知")
                if ptype == 0:
                    print(f"  🎰 [足球] 抽奖{i+1}: 谢谢参与")
                else:
                    print(f"  🎰 [足球] 抽奖{i+1}: {title}")
                user_info = wc_post("/api/user/info", {"id": wc_user_id, "refreshPoints": True})

    def run(self):
        s, ref = parse_yyb(self.server)
        cache = read_cache()
        cached = cache.get(ref) or {}
        if cached.get("token"):
            self.token = cached["token"]
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

                member = self.get_member()
                if not member and attempt == 0 and cached.get("token"):
                    print("🔄 [重登] 会员信息获取失败，重新登录...")
                    self.token = ""
                    continue

                self.daily_sign()
                time.sleep(1)
                self.worldcup_tasks()

                # 保存缓存
                c = read_cache()
                c[ref] = {"token": self.token}
                write_cache(c)
                return True
            except Exception as e:
                print(f"❌ [执行] 异常: {e}")
                return False
        return False


def main():
    log_title()
    ok, fail = 0, 0
    for i, srv in enumerate(SERVERS, 1):
        log_account(i, len(SERVERS), srv)
        if Adidas(srv, i).run():
            ok += 1
        else:
            fail += 1
        time.sleep(2)
    log_end(ok, fail)


if __name__ == "__main__":
    main()
#（注：内容由AI生成）
