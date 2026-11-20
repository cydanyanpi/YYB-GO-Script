#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
name: 长虹智慧家居签到
cron: 18 8 * * *
依赖: requests；通知使用青龙自带 notify.py。
YYB_SERVER: 服务地址@账号ID或OpenID，多账号换行；可直接复用现有变量。
YYB_API_KEY / YYB_PROTOCOL_TOKEN: 启用协议鉴权时配置，二选一
CH_AGGR_ID: 可选，手动指定签到活动ID；默认从首页“签到”菜单发现。
CH_NOTIFY: 默认1，设0关闭通知。
CH_IPV4_ONLY: 默认1；规避部分容器AAAA解析失败，设0恢复双栈解析。

缓存：登录 token 落盘到脚本目录 token_caches/chzhjj_token_cache.json，按 地址|标识 隔离；
      不设固定过期，执行中若检测到登录态失效，自动清缓存 → 重新登录 → 重跑一次（attempt 上限 2）。

作者：lcmovie https://github.com/lcmovie
"""

import base64
import importlib
import json
import os
import re
import sys
import socket
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
import urllib3.util.connection

APP_ID = "wx36c3413e8fe39263"
BASE = "https://hongke.changhong.com/gw/applet"
TITLE = "长虹智慧家居签到"

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "token_caches"
CACHE_FILE = CACHE_DIR / "chzhjj_token_cache.json"

# 登录态失效关键词（命中则清缓存重登）
AUTH_HINTS = (
    "token 失效", "token失效", "token过期", "token 过期", "invalid token", "token invalid",
    "未登录", "登录失败", "登录已过期", "登录失效", "请重新登录", "请先登录",
    "未授权", "unauthorized", "401", "token无效", "凭证失效",
)


def configure_network():
    # ql2 实测：AF_UNSPEC/AAAA解析EAI_AGAIN，A记录及IPv4 HTTPS正常。
    # 仅影响当前脚本进程；不硬编码IP、不关闭TLS验证。
    if os.getenv("CH_IPV4_ONLY", "1") != "0":
        urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET


class TaskError(Exception):
    pass


# --------------------------------------------------------------------------- #
# 缓存
# --------------------------------------------------------------------------- #
def read_cache() -> dict:
    try:
        if not CACHE_FILE.exists():
            return {}
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_cache(cache: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"   ⚠️ [缓存] 写入失败（不影响本次执行）：{type(exc).__name__}")


def cache_key(server: str, ref: str) -> str:
    return f"{server}|{ref}"


def save_cache_token(ck: str, token: str) -> None:
    cache = read_cache()
    cache[ck] = {"token": token, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    write_cache(cache)


def drop_cache_token(ck: str) -> None:
    cache = read_cache()
    if ck in cache:
        cache.pop(ck, None)
        write_cache(cache)


# --------------------------------------------------------------------------- #
# 日志美化
# --------------------------------------------------------------------------- #
def _pad_str(value, width: int) -> str:
    """按显示宽度补齐（中文/emoji 占 2，变体选择符不计宽）。"""
    text = str(value)
    length = 0
    for ch in text:
        if ch in ("\ufe0f", "\ufe0e", "\u200d"):
            continue
        length += 2 if ord(ch) > 255 else 1
    return text + " " * max(0, width - length)


def box_top(title: str) -> None:
    print()
    print("╔" + "═" * 48 + "╗")
    print("║  " + _pad_str(title, 46) + "║")


def box_line(label: str, value) -> None:
    print("║  " + _pad_str(f"{label}: {value}", 46) + "║")


def box_bottom() -> None:
    print("╚" + "═" * 48 + "╝")


def account_frame(index: int, total: int, title: str, source: str) -> None:
    print()
    print("┌" + "─" * 48 + "┐")
    print("│  " + _pad_str(f"🧩 账号 {index} / {total}　{title}", 46) + "│")
    print("│  " + _pad_str(f"🔗 来源: {source}", 46) + "│")
    print("└" + "─" * 48 + "┘")


# --------------------------------------------------------------------------- #
# 请求
# --------------------------------------------------------------------------- #
def request(session, method, url, label, **kwargs):
    try:
        response = session.request(method, url, timeout=(10, 35),
                                   allow_redirects=False, **kwargs)
        if response.status_code != 200:
            raise TaskError(f"{label}：HTTP {response.status_code}")
        result = response.json()
        if not isinstance(result, dict):
            raise TaskError(f"{label}：响应格式异常")
        return result
    except (requests.RequestException, ValueError) as exc:
        # 不打印可能含 URL、凭据或个人信息的原始异常及服务端原文。
        detail = str(exc)
        reason = "DNS解析失败" if "NameResolutionError" in detail or "Failed to resolve" in detail else type(exc).__name__
        raise TaskError(f"{label}：网络或JSON异常（{reason}）") from None


def parse_entry(line):
    if "@" not in line:
        raise TaskError("YYB_SERVER 格式应为 服务地址@账号标识")
    server, ref = (part.strip() for part in line.rsplit("@", 1))
    if not server.startswith(("http://", "https://")):
        server = "http://" + server
    u = urlsplit(server)
    if not u.hostname or not ref or u.query or u.fragment or u.username:
        raise TaskError("YYB_SERVER 地址或账号标识无效")
    return server.rstrip("/"), ref


class Changhong:
    def __init__(self, server, ref):
        self.server, self.ref = server, ref
        self.token = ""
        self.auth_failed = False
        self.yyb = requests.Session()
        self.yyb.trust_env = False
        self.web = requests.Session()
        self.web.headers.update({
            "content-type": "application/json",
            "Referer": f"https://servicewechat.com/{APP_ID}/330/page-frame.html",
            "User-Agent": "Mozilla/5.0 MicroMessenger/8.0.50 MiniProgramEnv/iOS",
        })

    def close(self):
        self.yyb.close()
        self.web.close()

    def yyb_call(self, endpoint, **extra):
        headers = {
            "Content-Type": "application/json"
        }
        api_key = os.getenv("YYB_API_KEY", "").strip() or os.getenv("YYB_PROTOCOL_TOKEN", "").strip()
        if api_key:
            headers["Authorization"] = api_key if " " in api_key else "Bearer " + api_key
        body = request(self.yyb, "POST", self.server + "/wxapp/" + endpoint,
                       "YYB " + endpoint,
                       json={"ref": self.ref, "app_id": APP_ID, **extra}, headers=headers)
        result = (body.get("data") or {}).get("result")
        if body.get("code") != 0 or not isinstance(result, dict):
            raise TaskError(f"YYB {endpoint}失败，请检查账号授权及YYB日志")
        return result

    def api(self, method, path, **kwargs):
        try:
            body = request(self.web, method, BASE + path, path, **kwargs)
        except TaskError as exc:
            if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                self.auth_failed = True
            raise
        code = str(body.get("code"))
        if code != "200":
            msg = str(body.get("msg") or body.get("message") or "").strip()
            if msg and any(hint in msg.lower() for hint in AUTH_HINTS):
                self.auth_failed = True
            raise TaskError(f"{path}：{msg or '业务请求失败，请检查小程序登录/授权/活动状态'}")
        return body.get("data")

    # ---- 会话 ------------------------------------------------------------ #
    def use_token(self, token: str) -> None:
        """直接套用已有 token（缓存复用路径）。"""
        self.token = token
        self.web.headers.update({"token": token, "smarthome": token})

    def verify_login(self) -> None:
        """用业务接口确认登录态真的可用。"""
        self.api("GET", "/mine/getAppletUser")

    def login(self):
        # 用户资料为辅助字段；不把YYB宿主OpenID误当作长虹小程序OpenID。
        profile, info = {}, {}
        try:
            info = self.yyb_call("operateWxData", payload={
                "api_name": "webapi_getuserinfo", "data": {"lang": "zh_CN"},
                "with_credentials": True, "from_component": True,
                "operate_directly": False,
            })
            profile = info.get("userInfo") or {}
            if not profile and info.get("rawData"):
                profile = json.loads(info["rawData"])
            if not profile and info.get("data"):
                raw = info["data"]
                if isinstance(raw, dict):
                    profile = raw
                else:
                    try:
                        profile = json.loads(raw)
                    except (ValueError, TypeError):
                        profile = json.loads(base64.b64decode(raw))
            if not isinstance(profile, dict):
                profile = {}
        except (TaskError, ValueError, TypeError):
            print("   ℹ️ 微信资料不可用，将由长虹服务端通过新code识别账号")
        code = self.yyb_call("getCode").get("code")
        if not isinstance(code, str) or not code.strip():
            raise TaskError("YYB未返回有效的wx.login code")
        common = {
            "jsCode": code, "invitation": "", "system": "iOS 16.0",
            "userName": profile.get("nickName", ""),
            "sex": {1: "男", 2: "女"}.get(profile.get("gender"), "未知"),
            "avatarUrl": profile.get("avatarUrl", ""),
        }
        # HAR 先通过此接口换取长虹小程序身份，再提交手机号授权。
        identity = self.api("POST", "/appletUser/getTokenByJsCode", json={
            **common, "iv": info.get("iv", ""),
        }, headers={"token": "", "smarthome": ""})
        if not isinstance(identity, dict):
            raise TaskError("长虹身份响应格式异常")
        data = identity
        if not data.get("token"):
            if not identity.get("openId") or not identity.get("unionId"):
                raise TaskError("长虹未返回小程序OpenID/UnionID，请检查微信授权")
            phone = self.yyb_call("getPhoneNumber")
            encrypted = phone.get("encryptedData") or phone.get("encrypted_data")
            if not all(isinstance(v, str) and v for v in
                       (phone.get("code"), encrypted, phone.get("iv"))):
                raise TaskError("YYB手机号授权数据不完整，请先在小程序授权手机号")
            # HAR 中第二步沿用第一步jsCode，由业务端处理；不再次向微信兑换。
            data = self.api("POST", "/appletUser/getTokenByCode", json={
                **common, "encryptedData": encrypted, "iv": phone["iv"],
                "code": phone["code"], "openId": identity["openId"],
                "unionId": identity["unionId"],
            }, headers={"token": "", "smarthome": ""})
        if not isinstance(data, dict) or not isinstance(data.get("token"), str) or not data["token"]:
            raise TaskError("长虹登录未返回token，需核对授权字段")
        # 实测静默登录返回token时isRegistered=0；手机号登录HAR为1。
        # 不能把该分支标记当作登录成败，必须用token访问业务接口验证。
        self.use_token(data["token"])
        self.verify_login()

    def activity_id(self):
        explicit = os.getenv("CH_AGGR_ID", "").strip()
        if explicit:
            return explicit
        menu = self.api("POST", "/homePage/getShortcutMenuList")
        found = set()

        def walk(value):
            if isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, dict):
                if "签到" in str(value.get("name", "")):
                    match = re.search(r"activityData=([A-Za-z0-9_-]+)", str(value.get("webUrl", "")))
                    if match:
                        found.add(match.group(1))
                for item in value.values():
                    if isinstance(item, (list, dict)):
                        walk(item)

        walk(menu)
        if len(found) != 1:
            raise TaskError("首页未发现唯一签到活动，请设置 CH_AGGR_ID")
        return found.pop()

    def state(self, aggr_id):
        data = self.api("GET", "/aggr/aggregationInfo", params={"aggrId": aggr_id})
        if not isinstance(data, dict):
            raise TaskError("活动详情格式异常")
        today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        if not (str(data.get("startTime", ""))[:10] <= today <= str(data.get("endTime", ""))[:10]):
            raise TaskError("活动未开始或已结束，请更新活动入口")
        if str(data.get("status")) != "1" or str(data.get("isCan")) != "1":
            raise TaskError("当前账号无法参与该活动")
        signs = [x["aggrAssemblySignin"] for x in data.get("aggrAssemblyList", [])
                 if isinstance(x, dict) and isinstance(x.get("aggrAssemblySignin"), dict)]
        if len(signs) != 1 or signs[0].get("isSignin") not in (0, 1):
            raise TaskError("签到组件或状态无法识别")
        return signs[0]

    def run(self, aggr_id=None):
        """执行业务（登录已由外层完成）。"""
        if aggr_id is None:
            aggr_id = self.activity_id()
        before = self.state(aggr_id)
        if before["isSignin"] == 1:
            status = "今日已签到"
        else:
            error = None
            try:
                self.api("POST", "/aggr/signin", params={"aggrId": aggr_id})
            except TaskError as exc:
                error = exc
            # 签到POST超时也只查询结果，不盲目重复提交。
            if self.state(aggr_id)["isSignin"] != 1:
                raise TaskError(str(error) if error else "签到后状态未变为已签到")
            status = "签到成功（已复查）"
        try:
            points = self.api("GET", "/homePage/getUserPoint")
            # 实测刚签到时可能暂返0，稍后查询恢复实际余额。
            if before["isSignin"] == 0 and points == 0:
                for delay in (2, 4):
                    time.sleep(delay)
                    points = self.api("GET", "/homePage/getUserPoint")
                    if points != 0:
                        break
            if isinstance(points, (int, float)) and not isinstance(points, bool):
                status += f"，当前积分：{points}"
                if before["isSignin"] == 0 and points == 0:
                    status += "（接口可能尚未更新，请稍后查看）"
            else:
                status += "，积分格式无法识别"
        except TaskError:
            status += "，积分查询失败"
        return status


# --------------------------------------------------------------------------- #
# 单账号执行（缓存 + 失效重登）
# --------------------------------------------------------------------------- #
def run_account(index: int, total: int, account, allow_cache: bool = True) -> dict:
    """返回 {'success','status','error','aggr'}"""
    server, ref = account
    ck = cache_key(server, ref)
    entry = read_cache().get(ck) or {}
    result = {"success": False, "status": "", "error": "", "aggr": "-"}

    account_frame(index, total, f"账号 {ref}", f"{server}@{ref}")

    for attempt in range(2):
        client = Changhong(server, ref)
        try:
            used_cache = False
            if allow_cache and attempt == 0 and entry.get("token"):
                client.use_token(entry["token"])
                try:
                    client.verify_login()
                    used_cache = True
                    print("   💾 [缓存] 复用已保存的登录 token")
                except TaskError as exc:
                    if client.auth_failed:
                        print(f"   ♻️ [缓存] token 已失效，清理后重新登录（{exc}）")
                        drop_cache_token(ck)
                        entry = {}
                    else:
                        print(f"   ⚠️ [缓存] token 校验未通过，改为重新登录（{exc}）")

            if not used_cache:
                client.login()
                print(f"   ✅ [登录] 成功　token 已更新")

            aggr_id = client.activity_id()
            result["aggr"] = aggr_id
            status = client.run(aggr_id)
            result["status"] = status
            result["success"] = True

            save_cache_token(ck, client.token)
            return result
        except TaskError as exc:
            result["error"] = str(exc)
            # 仅在「复用缓存」这一轮触发重登，避免死循环
            if client.auth_failed and allow_cache and attempt == 0:
                print(f"   🔄 [重试] 登录态失效，清理缓存后重新登录重跑（{exc}）")
                drop_cache_token(ck)
                entry = {}
                continue
            print(f"   ❌ [执行] 失败：{exc}")
            return result
        except Exception as exc:
            result["error"] = f"处理异常（{type(exc).__name__}）"
            print(f"   ❌ [执行] {result['error']}")
            return result
        finally:
            client.close()

    return result


def notify(message):
    if os.getenv("CH_NOTIFY", "1") == "0":
        return
    for folder in (Path(__file__).resolve().parent, Path("/ql/data/scripts"), Path("/ql/scripts")):
        if str(folder) not in sys.path:
            sys.path.append(str(folder))
    try:
        importlib.import_module("notify").send(TITLE, message)
        print("   ✅ [通知] 青龙通知模块调用完成（送达情况以通知渠道为准）")
    except Exception as exc:
        print(f"   ⚠️ [通知] 不可用或调用失败（{type(exc).__name__}），不影响签到结果")


def summary_box(results, targets) -> None:
    """逐账号明细在前，汇总框收尾。"""
    print()
    for i, (r, (_, ref)) in enumerate(zip(results, targets), 1):
        icon = "✅" if r["success"] else "❌"
        print(f"{icon} 账号{i}（{ref}）：{r['status'] or r['error']}")
        if r["success"]:
            print(f"   🎯 活动ID {r['aggr']}")

    ok = sum(1 for r in results if r["success"])
    fail = len(results) - ok
    box_top("🏁 长虹智慧家居 任务完成")
    box_line("✅ 成功", ok)
    box_line("❌ 失败", fail)
    box_line("🕒 结束时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    box_bottom()


def main():
    configure_network()
    lines = [x.strip() for x in os.getenv("YYB_SERVER", "").splitlines() if x.strip()]
    if not lines:
        box_top("🚗 长虹智慧家居 自动签到")
        box_line("⚠️ 状态", "未配置 YYB_SERVER")
        box_bottom()
        print("   格式：YYB地址@账号ID，多账号每行一条")
        notify("未配置 YYB_SERVER")
        return 1

    accounts = []
    for line in lines:
        try:
            accounts.append(parse_entry(line))
        except TaskError as exc:
            print(f"   ⚠️ [配置] 忽略一行：{exc}（{line}）")

    box_top("🚗 长虹智慧家居 自动签到")
    box_line("🕒 启动时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    box_line("🔢 账号数量", len(accounts))
    box_line("🎯 活动ID", os.getenv("CH_AGGR_ID", "").strip() or "自动发现")
    box_bottom()

    results, messages = [], []
    for index, account in enumerate(accounts, 1):
        r = run_account(index, len(accounts), account)
        results.append(r)
        messages.append(f"账号{index}：{r['status'] or r['error']}")

    summary_box(results, accounts)
    notify("\n".join(messages))
    return 0 if all(r["success"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
