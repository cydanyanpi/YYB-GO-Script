#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 勇闯天涯
# cron: 44 7 * * *
"""
name: 勇闯天涯签到
cron: 44 7 * * *

勇闯天涯 superX 微信小程序「积分签到」每日签到 + 新手/每月任务自动完成，
基于 YYB-Go-Enhanced 自动取码登录，全程无需抓包。

青龙环境变量：
  YYB_SERVER           必填，YYB-Go-Enhanced地址@微信账号标识，多账号每行一条
                       例：yyb-go:8000@1
  YYB_API_KEY / YYB_PROTOCOL_TOKEN       启用协议鉴权时配置，二选一

依赖：requests
通知：优先使用青龙内置 notify.py；未配置时回落到 PushPlus / Server酱 / 企业微信 / Bark。
      通知里固定输出每个账号的「初始积分 → 最终积分」，便于对账。通知失败不影响结果。
功能：查询签到状态与任务清单 -> 每日签到 -> 自动完成可自动的新手/每月任务 -> 复查积分
      -> 汇总通知。多账号串行。

缓存：sessionKey 落盘到脚本目录 token_caches/ycty_token_cache.json，不设过期；
      执行业务时若检测到凭证失效，自动清缓存 -> 重新取码登录 -> 重跑一次（attempt 上限 2）。

# 作者：lcmovie https://github.com/lcmovie
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

try:
    import requests
except ImportError:
    print("❌ 缺少依赖：pip install requests")
    sys.exit(1)

APP_NAME = "勇闯天涯签到"
HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
APP_NO = "wx13c6d1dffe3b32ec"          # 勇闯天涯 superX 小程序 AppID
API_BASE = "https://superX.crb.cn/Api"  # 接口统一前缀

# 已实测可自动完成的任务（服务端不校验真实行为）。可通过 YCTY_AUTO_TASKS 覆盖。
DEFAULT_AUTO_TASKS = ("SHARE_APP", "ACCESS_JD", "ACCESS_BEERTOWN")

# 任务 taskType -> 中文名（用于日志/通知；未知类型兜底显示原值）
TASK_NAMES = {
    "SHARE_APP": "分享签到活动",
    "UPDATE_USERINFO": "完善个人信息",
    "SCAN_QR_CODE": "扫描瓶盖码",
    "BUG_GIFT": "参与XBOX兑换",
    "SUB_MSG": "订阅服务消息",
    "ACCESS_JD": "访问京东旗舰店",
    "ACCESS_BEERTOWN": "探索SNOWVERSE",
}

# 缓存：脚本目录下 token_caches/，不设 TTL
CACHE_DIR = HERE / "token_caches"
CACHE_FILE = CACHE_DIR / "ycty_token_cache.json"

# 凭证失效关键词（命中即判定 sessionKey 不可用）
AUTH_STRONG_KEYWORDS = (
    "未登录", "请重新登录", "请先登录", "重新登录", "登录失效", "登录过期",
    "登录已过期", "登录超时", "用户信息失效", "会话失效", "session失效",
)
AUTH_PAIR_KEYWORDS = (
    ("session", "失效"), ("session", "过期"), ("session", "无效"),
    ("sessionkey", "失效"), ("sessionkey", "过期"), ("sessionkey", "无效"),
    ("token", "失效"), ("token", "过期"), ("token", "无效"),
    ("凭证", "失效"), ("凭证", "过期"),
)

UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090a13) XWEB/8555",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Mobile/15E148 MicroMessenger/8.0.49(0x1800312b) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat XWEB/8555",
]


class SkipAccount(Exception):
    """账号本身不具备参与条件，归入「跳过」而非失败。"""


class ApiError(Exception):
    """接口返回了非预期结果。"""


class AuthExpired(Exception):
    """凭证（sessionKey）已失效，需要重新登录。"""


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def env_flag(name: str, default: str = "1") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name, "") or "").strip() or default)
    except Exception:
        return default


DRY_RUN = env_flag("YCTY_DRY_RUN", "0")
ENABLE_SIGN = env_flag("YCTY_ENABLE_SIGN", "1")
ENABLE_TASK = env_flag("YCTY_ENABLE_TASK", "1")
LOGIN_RETRY = max(1, env_int("YCTY_LOGIN_RETRY", 3))
TIMEOUT = env_int("YCTY_REQUEST_TIMEOUT", 30)
RANDOM_HEADERS = env_flag("YCTY_RANDOM_HEADERS", "1")
DEBUG = env_flag("YCTY_DEBUG", "0")

_auto_tasks_raw = (os.getenv("YCTY_AUTO_TASKS", "") or "").strip()
AUTO_TASKS = (
    tuple(t.strip() for t in _auto_tasks_raw.split(",") if t.strip())
    if _auto_tasks_raw
    else DEFAULT_AUTO_TASKS
)

_CURRENT_UA = random.choice(UAS)


def log(*args: Any) -> None:
    print(*args, flush=True)


def dbg(*args: Any) -> None:
    if DEBUG:
        print("[DEBUG]", *args, flush=True)


def clean(value: Any, limit: int = 160) -> str:
    """清洗服务端返回的文本字段（去引号/空白/零宽字符），并截断。"""
    if value is None:
        return ""
    text = str(value)
    text = text.strip("\"' \t\r\n\u200b\u200c\u200d\ufeff")
    return text[:limit]


def preview(obj: Any, limit: int = 300) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)[:limit]
    except Exception:
        return str(obj)[:limit]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pad_str(value: Any, width: int) -> str:
    """按显示宽度补齐（中文/emoji 占 2，变体选择符与零宽连接符不计宽）。"""
    text = str(value)
    length = 0
    for ch in text:
        if ch in ("\ufe0f", "\ufe0e", "\u200d"):
            continue
        length += 2 if ord(ch) > 255 else 1
    return text + " " * max(0, width - length)


def headers_json() -> Dict[str, str]:
    ua = random.choice(UAS) if RANDOM_HEADERS else _CURRENT_UA
    return {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/json",
    }


def parse_ref_list(raw: str) -> List[Tuple[str, str]]:
    """解析 YYB_SERVER：每行 `地址@账号ID`。"""
    out: List[Tuple[str, str]] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "@" not in line:
            out.append((line, "1"))
            continue
        host, _, ref = line.rpartition("@")
        host = host.strip()
        if not host.startswith("http"):
            host = "http://" + host
        out.append((host, ref.strip() or "1"))
    return out


def task_label(task_type: str) -> str:
    return TASK_NAMES.get(task_type, task_type)


# --------------------------------------------------------------------------- #
# 缓存
# --------------------------------------------------------------------------- #
def cache_key(host: str, ref: str) -> str:
    """按 地址+账号标识 做缓存键，避免同地址多账号串凭证。"""
    return f"{host.rstrip('/')}|{ref}"


def read_cache() -> Dict[str, Any]:
    try:
        if not CACHE_FILE.exists():
            return {}
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_cache(cache: Dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"⚠️ [缓存] 写入失败（不影响本次执行）：{clean(exc, 120)}")


def save_client_cache(ck: str, client: "Client") -> None:
    cache = read_cache()
    cache[ck] = {
        "session_key": client.session_key,
        "open_id": client.open_id,
        "cookies": client.s.cookies.get_dict(),
        "time": now_text(),
    }
    write_cache(cache)


def drop_client_cache(ck: str) -> None:
    cache = read_cache()
    if ck in cache:
        cache.pop(ck, None)
        write_cache(cache)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Client:
    """对 superX.crb.cn 的薄封装：登录 + 带 sessionKey 的业务请求。"""

    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update(headers_json())
        self.session_key = ""
        self.open_id = ""
        self.auth_expired = False

    @staticmethod
    def _detect_auth_fail(resp: Any) -> bool:
        """判断返回是否属于凭证失效。"""
        if not isinstance(resp, dict):
            return False
        if resp.get("code") in (401, 403, "401", "403"):
            return True
        text = ""
        for key in ("message", "msg", "error", "errMsg"):
            value = resp.get(key)
            if isinstance(value, str):
                text += value
        if not text:
            data = resp.get("data")
            if isinstance(data, dict):
                for key in ("message", "msg", "error"):
                    value = data.get(key)
                    if isinstance(value, str):
                        text += value
        if not text:
            return False
        lower = text.lower()
        for kw in AUTH_STRONG_KEYWORDS:
            if kw.lower() in lower:
                return True
        for first, second in AUTH_PAIR_KEYWORDS:
            if first in lower and second in lower:
                return True
        return False

    def _handle(self, resp: Dict[str, Any], path: str) -> Dict[str, Any]:
        # 仅在已持有 sessionKey 的业务请求上判定失效，避免登录流程误判
        if self.session_key and self._detect_auth_fail(resp):
            self.auth_expired = True
            raise AuthExpired(f"sessionKey 失效 @ {path}: {preview(resp, 160)}")
        return resp

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query = dict(params or {})
        if self.session_key:
            query["sessionKey"] = self.session_key
        url = API_BASE + "/" + path
        r = self.s.get(url, params=query, timeout=TIMEOUT)
        dbg("GET", url, "->", r.status_code, preview(r.text, 300))
        if r.status_code in (401, 403):
            if self.session_key:
                self.auth_expired = True
                raise AuthExpired(f"HTTP {r.status_code} @ {path}")
        if r.status_code != 200:
            raise ApiError(f"HTTP {r.status_code} @ {path}")
        try:
            return self._handle(r.json(), path)
        except AuthExpired:
            raise
        except Exception:
            raise ApiError(f"非 JSON 响应 @ {path}: {clean(r.text)}")

    def _post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = API_BASE + "/" + path
        if self.session_key:
            url += ("&" if "?" in url else "?") + "sessionKey=" + quote(self.session_key, safe="")
        r = self.s.post(url, json=(body or {}), timeout=TIMEOUT)
        dbg("POST", url, "->", r.status_code, preview(r.text, 300))
        if r.status_code in (401, 403):
            if self.session_key:
                self.auth_expired = True
                raise AuthExpired(f"HTTP {r.status_code} @ {path}")
        if r.status_code != 200:
            raise ApiError(f"HTTP {r.status_code} @ {path}")
        try:
            return self._handle(r.json(), path)
        except AuthExpired:
            raise
        except Exception:
            raise ApiError(f"非 JSON 响应 @ {path}: {clean(r.text)}")

    # ---------------- 业务封装 ---------------- #
    def login(self, code: str) -> Dict[str, Any]:
        return self._post("b3/OAuthProgram/Login", {"code": code})

    def user_info(self) -> Dict[str, Any]:
        return (self._get("b1/GetUserInfo").get("data") or {})

    def sign_info(self) -> Dict[str, Any]:
        return (self._post("sign/getSignInfo").get("data") or {})

    def add_sign(self) -> Dict[str, Any]:
        return self._post("sign/addSign", {})

    def do_task(self, task_type: str) -> Dict[str, Any]:
        return self._post("sign/doTask", {"taskType": task_type})


# --------------------------------------------------------------------------- #
# 登录
# --------------------------------------------------------------------------- #
def yyb_get_code(host: str, ref: str) -> Tuple[str, str]:
    """YYB 取 wx.login code → (code, openid)。"""
    url = host.rstrip("/") + "/wxapp/getCode"
    headers = {"User-Agent": _CURRENT_UA, "Content-Type": "application/json"}
    api_key = os.getenv("YYB_API_KEY", "").strip() or os.getenv("YYB_PROTOCOL_TOKEN", "").strip()
    if api_key:
        headers["Authorization"] = api_key if " " in api_key else "Bearer " + api_key
    r = requests.post(url, json={"app_id": APP_NO, "ref": str(ref)}, headers=headers, timeout=TIMEOUT)
    dbg("YYB getCode", r.status_code, preview(r.text, 300))
    if r.status_code != 200:
        raise ApiError(f"YYB 取码失败 HTTP {r.status_code}: {clean(r.text)}")
    data = r.json()
    payload = data.get("data") or {}
    if not (payload.get("result") or {}).get("code"):
        raise ApiError(f"YYB 未返回 code: {clean(r.text)}")
    return clean((payload.get("result") or {}).get("code")), clean(payload.get("openid"))


def login_once(host: str, ref: str) -> Client:
    code, openid = yyb_get_code(host, ref)
    client = Client()
    client.open_id = openid
    dbg("code =", code[:24], "...")
    resp = client.login(code)
    data = resp.get("data") or {}
    sk = clean(data.get("sessionKey"))
    if resp.get("code") != 0 or not sk:
        raise ApiError(f"Login 未返回 sessionKey: {preview(resp)}")
    client.session_key = sk
    return client


def login(host: str, ref: str) -> Client:
    last: Optional[Exception] = None
    for attempt in range(1, LOGIN_RETRY + 1):
        try:
            return login_once(host, ref)
        except Exception as exc:
            last = exc
            log(f"   ⚠️ 第 {attempt}/{LOGIN_RETRY} 次登录失败：{clean(exc, 200)}")
            if attempt < LOGIN_RETRY:
                time.sleep(1.5 * attempt)
    raise ApiError(f"登录失败：{clean(last, 200)}")


# --------------------------------------------------------------------------- #
# 业务
# --------------------------------------------------------------------------- #
def _run_business(client: Client, host: str, ref: str, label: str) -> Dict[str, Any]:
    """单账号一轮完整业务：用户信息 -> 签到 -> 任务 -> 复查。"""
    result: Dict[str, Any] = {"label": label, "ref": ref}

    # ---------------- 初始状态 ---------------- #
    try:
        user = client.user_info()
    except AuthExpired as exc:
        log(f"   🔑 凭证失效：{clean(exc, 160)}")
        result.update(error="凭证失效")
        return result
    except Exception as exc:
        log(f"   ❌ 获取用户信息失败：{clean(exc, 200)}")
        result.update(error=f"获取用户信息失败：{clean(exc, 200)}")
        return result

    name = clean(user.get("name")) or clean(user.get("nickName")) or f"账号{ref}"
    before_score = user.get("score")
    before_xmedal = user.get("xmedal")
    result["user"] = name
    result["score_before"] = before_score
    log(f"   👤 {name}　积分 {before_score}　X勋章 {before_xmedal}")

    try:
        info = client.sign_info()
    except AuthExpired as exc:
        log(f"   🔑 凭证失效：{clean(exc, 160)}")
        result.update(error="凭证失效")
        return result
    except Exception as exc:
        log(f"   ❌ 获取签到信息失败：{clean(exc, 200)}")
        result.update(error=f"获取签到信息失败：{clean(exc, 200)}")
        return result

    signed = bool(info.get("signed"))
    sign_day = info.get("signDayNum", 0)
    tasks = info.get("taskInfoList") or []
    ladder = info.get("signDaysV1") or []
    result["signed_before"] = signed
    result["sign_day"] = sign_day
    log(f"   📅 今日{'已' if signed else '未'}签到　连签 {sign_day} 天")

    # ---------------- 每日签到 ---------------- #
    sign_msg: str
    sign_ok = False
    if DRY_RUN:
        sign_msg = "干跑模式，未执行签到"
        sign_ok = True                      # 干跑只查询，视为成功
    elif not ENABLE_SIGN:
        sign_msg = "已关闭签到（YCTY_ENABLE_SIGN=0）"
        sign_ok = True                      # 主动关闭，不算失败
    elif signed:
        sign_msg = "今天已经签到"
        sign_ok = True
    else:
        try:
            resp = client.add_sign()
            if resp.get("code") == 0:
                sign_msg = "签到成功"
                sign_ok = True
            else:
                sign_msg = f"签到返回异常：{preview(resp)}"
        except AuthExpired as exc:
            sign_msg = f"签到凭证失效：{clean(exc, 160)}"
        except Exception as exc:
            sign_msg = f"签到异常：{clean(exc, 200)}"
    result["sign"] = sign_msg
    result["sign_ok"] = sign_ok
    log(f"   ✍️ 签到：{sign_msg}")

    # ---------------- 新手/每月任务 ---------------- #
    task_lines: List[str] = []
    done_auto: List[str] = []
    remain_manual: List[str] = []
    if DRY_RUN:
        # 干跑只读展示任务状态，不执行任何写操作
        for task in tasks:
            tt = clean(task.get("taskType"))
            is_done = bool(task.get("isDone"))
            if is_done:
                task_lines.append(f"✅ {task_label(tt)} 已完成")
            elif tt in AUTO_TASKS:
                task_lines.append(f"🟢 {task_label(tt)} 可自动完成（干跑未执行）")
            else:
                task_lines.append(f"⏳ {task_label(tt)} 需手动完成")
                remain_manual.append(tt)
    elif not ENABLE_TASK:
        task_lines.append("已关闭任务（YCTY_ENABLE_TASK=0）")
    else:
        for task in tasks:
            tt = clean(task.get("taskType"))
            is_done = bool(task.get("isDone"))
            if is_done:
                continue
            if tt in AUTO_TASKS:
                try:
                    resp = client.do_task(tt)
                    if resp.get("code") == 0:
                        done_auto.append(tt)
                        task_lines.append(f"✅ {task_label(tt)} +{task.get('score', '')}分")
                    else:
                        remain_manual.append(tt)
                        task_lines.append(f"⚠️ {task_label(tt)} 返回未完成：{clean(resp.get('message'))}")
                except AuthExpired as exc:
                    remain_manual.append(tt)
                    task_lines.append(f"⚠️ {task_label(tt)} 凭证失效：{clean(exc, 120)}")
                except Exception as exc:
                    remain_manual.append(tt)
                    task_lines.append(f"⚠️ {task_label(tt)} 异常：{clean(exc, 120)}")
            else:
                remain_manual.append(tt)
                task_lines.append(f"⏳ {task_label(tt)} 需手动完成")
    if not task_lines:
        task_lines.append("无待完成任务（全部已完成）")
    for line in task_lines:
        log(f"   🎯 {line}")
    result["task_done"] = done_auto
    result["task_manual"] = remain_manual

    # 凭证已失效时不再继续复查，交由外层重登
    if client.auth_expired:
        result["error"] = "凭证失效"
        return result

    # ---------------- 复查 ---------------- #
    try:
        info_after = client.sign_info()
    except Exception:
        info_after = {}
    try:
        user_after = client.user_info()
    except Exception:
        user_after = {}

    after_score = user_after.get("score", before_score)
    after_xmedal = user_after.get("xmedal", before_xmedal)
    sign_day_after = info_after.get("signDayNum", sign_day)
    result["score_after"] = after_score
    result["sign_day_after"] = sign_day_after

    delta = None
    try:
        if before_score is not None and after_score is not None:
            delta = int(after_score) - int(before_score)
    except (TypeError, ValueError):
        delta = None

    log(f"   💎 积分：{before_score} → {after_score}"
        f"{f'（本日 {delta:+}）' if delta is not None else ''}"
        f"　X勋章 {before_xmedal} → {after_xmedal}　连签 {sign_day_after} 天")

    # 连签阶梯提示
    if ladder:
        nxt = [l for l in ladder if int(l.get("day", 0)) > int(sign_day_after)]
        if nxt:
            l = nxt[0]
            log(f"   🎯 连签 {l.get('day')} 天可得 {l.get('title')}（当前 {sign_day_after} 天）")

    result["success"] = result.get("sign_ok", False)
    return result


def run_account(host: str, ref: str, label: str) -> Dict[str, Any]:
    """单账号执行入口：优先复用缓存 sessionKey，失效则清缓存重登重跑一次。"""
    ck = cache_key(host, ref)
    cached = read_cache().get(ck) or {}

    for attempt in range(2):
        if attempt == 0 and cached.get("session_key"):
            client = Client()
            client.session_key = cached["session_key"]
            client.open_id = cached.get("open_id", "")
            for k, v in (cached.get("cookies") or {}).items():
                try:
                    client.s.cookies.set(k, v)
                except Exception:
                    pass
            log("   💾 使用缓存 sessionKey")
        else:
            try:
                client = login(host, ref)
            except SkipAccount as exc:
                log(f"   ⏭️ 跳过：{exc}")
                return {"label": label, "ref": ref, "skipped": True, "sign": f"跳过：{exc}"}
            except Exception as exc:
                log(f"   ❌ 登录失败：{clean(exc, 220)}")
                return {"label": label, "ref": ref, "error": f"登录失败：{clean(exc, 220)}"}
            save_client_cache(ck, client)
            log("   🧠 登录成功，sessionKey 已写入缓存")

        result = _run_business(client, host, ref, label)

        if client.auth_expired and attempt == 0:
            log("   🔄 检测到 sessionKey 失效，清缓存重新登录后重试一次")
            drop_client_cache(ck)
            cached = {}
            continue

        return result

    return {"label": label, "ref": ref, "error": "登录失效且重新获取凭证失败"}


# --------------------------------------------------------------------------- #
# 通知
# --------------------------------------------------------------------------- #
def load_notify():
    candidates = [
        Path(HERE) / "notify.py",
        Path("/ql/data/scripts/notify.py"),
        Path("/ql/scripts/notify.py"),
        Path("/ql/data/notify.py"),
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("ycty_qinglong_notify", path)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            for name in ("send", "sendNotify"):
                func = getattr(module, name, None)
                if callable(func):
                    return func
        except Exception as exc:
            print(f"⚠️ [通知] 加载 {path} 失败：{clean(exc, 120)}")
    return None


QL_PUSH_ENVS = (
    "BARK_PUSH", "DD_BOT_TOKEN", "FSKEY", "GOBOT_URL", "IGOT_PUSH_KEY", "PUSH_KEY",
    "DEER_KEY", "CHAT_URL", "PUSH_PLUS_TOKEN", "WE_PLUS_BOT_TOKEN", "QMSG_KEY",
    "QYWX_KEY", "QYWX_AM", "TG_BOT_TOKEN", "SMTP_SERVER", "PUSHME_KEY",
    "WEBHOOK_URL", "NTFY_TOPIC", "WXPUSHER_APP_TOKEN", "OPENILINK_APP_TOKEN",
)


def send_notify(title: str, content: str) -> None:
    panel_channel = next((k for k in QL_PUSH_ENVS if (os.getenv(k) or "").strip()), "")
    sender = load_notify()
    if sender is not None:
        if panel_channel:
            try:
                sender(title, content)
                log(f"✅ [通知] 已通过青龙通知模块发送（通道 {panel_channel}）")
                return
            except Exception as exc:
                log(f"⚠️ [通知] 青龙通知发送失败（不影响结果）：{clean(exc, 120)}")
        else:
            log("ℹ️ [通知] 青龙面板未配置推送变量，改用脚本自带通道")
    else:
        log("⚠️ [通知] 未找到青龙 notify.py，使用脚本自带通道")

    sent = False
    plusplus = (os.getenv("PUSH_PLUS_TOKEN", "") or os.getenv("PLUSPLUS_TOKEN", "") or "").strip()
    if plusplus:
        try:
            r = requests.post("https://www.pushplus.plus/send",
                              json={"token": plusplus, "title": title, "content": content,
                                    "template": "txt"}, timeout=20)
            ok = r.status_code == 200 and (r.json().get("code") == 200)
            sent = sent or ok
            log(f"{'✅' if ok else '❌'} [通知] PushPlus 发送{'成功' if ok else '失败：' + clean(r.text, 120)}")
        except Exception as exc:
            log(f"❌ [通知] PushPlus 发送失败：{clean(exc, 120)}")
    server_push = (os.getenv("PUSH_KEY", "") or os.getenv("SERVERPUSHKEY", "") or "").strip()
    if server_push and not sent:
        try:
            requests.post(f"https://sctapi.ftqq.com/{server_push}.send",
                          data={"title": title, "desp": content}, timeout=15)
            sent = True
            log("✅ [通知] Server 酱发送成功")
        except Exception as exc:
            log(f"❌ [通知] Server 酱发送失败：{clean(exc, 120)}")
    qywx = (os.getenv("QYWX_KEY", "") or os.getenv("QYWX_TOKEN", "") or "").strip()
    if qywx and not sent:
        try:
            requests.post(f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={qywx}",
                          json={"msgtype": "text",
                                "text": {"content": f"{title}\n\n{content}"}}, timeout=15)
            sent = True
            log("✅ [通知] 企业微信机器人发送成功")
        except Exception as exc:
            log(f"❌ [通知] 企业微信机器人发送失败：{clean(exc, 120)}")
    bark = (os.getenv("BARK_PUSH", "") or "").strip()
    if bark and not sent:
        try:
            requests.post(bark.rstrip("/"), json={"title": title, "body": content}, timeout=15)
            sent = True
            log("✅ [通知] Bark 发送成功")
        except Exception as exc:
            log(f"❌ [通知] Bark 发送失败：{clean(exc, 120)}")
    if not sent:
        log("ℹ️ [通知] 未配置任何可用推送通道，结果仅输出到日志")


def _num(value: Any) -> str:
    try:
        f = float(value)
        return str(int(f)) if f == int(f) else f"{f:.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def build_report(results: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    ok = sum(1 for r in results if r.get("success") and not r.get("skipped") and not r.get("error"))
    skip = sum(1 for r in results if r.get("skipped"))
    fail = sum(1 for r in results if r.get("error") and not r.get("skipped"))
    lines.append(f"成功 {ok} / 跳过 {skip} / 失败 {fail}")
    lines.append("")
    for r in results:
        name = r.get("user") or r.get("label") or ""
        if r.get("skipped"):
            lines.append(f"⏭️ {name}：{r.get('sign', '跳过')}")
            continue
        if r.get("error") and not r.get("success"):
            lines.append(f"❌ {name}：{r.get('error', '失败')}")
            continue
        b, a = r.get("score_before"), r.get("score_after")
        delta = ""
        try:
            if b is not None and a is not None:
                d = int(a) - int(b)
                delta = f"（{'+' if d >= 0 else ''}{d}）"
        except (TypeError, ValueError):
            pass
        head = f"✅ {name}"
        if b is not None and a is not None:
            head += f"　积分 {_num(b)} → {_num(a)}{delta}"
        head += f"　连签 {r.get('sign_day_after', '-')} 天"
        lines.append(head)
        if r.get("task_done"):
            labels = "、".join(task_label(t) for t in r["task_done"])
            lines.append(f"   自动完成任务：{labels}")
        if r.get("task_manual"):
            labels = "、".join(task_label(t) for t in r["task_manual"])
            lines.append(f"   需手动任务：{labels}")
    return "\n".join(lines)


def _print_summary_box(results: List[Dict[str, Any]]) -> None:
    """统一结束汇总框（含逐账号明细）。"""
    ok = sum(1 for r in results if r.get("success") and not r.get("skipped") and not r.get("error"))
    skip = sum(1 for r in results if r.get("skipped"))
    fail = sum(1 for r in results if r.get("error") and not r.get("skipped"))
    total_earned = 0
    for r in results:
        try:
            b, a = r.get("score_before"), r.get("score_after")
            if b is not None and a is not None and a > b:
                total_earned += int(a) - int(b)
        except (TypeError, ValueError):
            pass

    log("")
    log("╔" + "═" * 48 + "╗")
    log("║  " + _pad_str("🏁 勇闯天涯签到 完成", 46) + "║")
    log("║  " + _pad_str(f"✅ 成功: {ok}", 46) + "║")
    log("║  " + _pad_str(f"⏭️ 跳过: {skip}", 46) + "║")
    log("║  " + _pad_str(f"❌ 失败: {fail}", 46) + "║")
    log("║  " + _pad_str(f"💎 积分: +{total_earned}", 46) + "║")
    log("║  " + _pad_str(f"🕒 结束时间: {now_text()}", 46) + "║")
    log("╚" + "═" * 48 + "╝")

    for idx, r in enumerate(results, 1):
        name = r.get("user") or r.get("label") or ""
        if r.get("skipped"):
            log(f"⏭️ 账号{idx} {name}: 跳过 - {r.get('sign', '')}")
            continue
        if r.get("error") and not r.get("success"):
            log(f"❌ 账号{idx} {name}: {r.get('error')}")
            continue
        b, a = r.get("score_before"), r.get("score_after")
        line = f"✅ 账号{idx} {name}"
        if b is not None and a is not None:
            try:
                d = int(a) - int(b)
                line += f"　积分 {_num(b)} → {_num(a)}（{'+' if d >= 0 else ''}{d}）"
            except (TypeError, ValueError):
                pass
        log(line)
        if r.get("task_done"):
            log(f"   🎯 自动完成: {'、'.join(task_label(t) for t in r['task_done'])}")
        if r.get("task_manual"):
            log(f"   ⏳ 需手动: {'、'.join(task_label(t) for t in r['task_manual'])}")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main() -> int:
    raw = (os.getenv("YYB_SERVER", "") or "").strip()
    if not raw:
        log("❌ 未配置环境变量 YYB_SERVER（格式：yyb-go:8000@1，多账号每行一条）")
        return 1
    accounts = parse_ref_list(raw)
    if not accounts:
        log("❌ YYB_SERVER 解析后没有可用账号")
        return 1

    log("")
    log("╔" + "═" * 48 + "╗")
    log("║  " + _pad_str("🍺 勇闯天涯 superX 自动签到", 46) + "║")
    log("║  " + _pad_str(f"🕒 启动时间: {now_text()}", 46) + "║")
    log("║  " + _pad_str(f"🔢 账号数量: {len(accounts)}", 46) + "║")
    log("║  " + _pad_str(f"🎯 自动任务: {len(AUTO_TASKS)} 项", 46) + "║")
    log("╚" + "═" * 48 + "╝")
    if DRY_RUN:
        log("🧪 干跑模式（YCTY_DRY_RUN=1），只查询不签到")
    log(f"   🔧 自动任务白名单：{'、'.join(task_label(t) for t in AUTO_TASKS)}")

    results: List[Dict[str, Any]] = []
    for idx, (host, ref) in enumerate(accounts, 1):
        log("")
        log("┌" + "─" * 48 + "┐")
        log("│  " + _pad_str(f"🧩 账号 {idx} / {len(accounts)}", 46) + "│")
        log("│  " + _pad_str(f"🔑 标识: {ref}", 46) + "│")
        log("└" + "─" * 48 + "┘")
        try:
            results.append(run_account(host, ref, f"[{idx}] {ref}"))
        except Exception as exc:
            log(f"   ❌ 账号 {ref} 异常：{clean(exc, 220)}")
            results.append({"label": f"[{idx}] {ref}", "ref": ref, "error": f"异常：{clean(exc, 220)}"})
        if idx < len(accounts):
            time.sleep(2)

    _print_summary_box(results)

    report = build_report(results)
    try:
        send_notify(APP_NAME, report)
    except Exception as exc:
        log(f"⚠️ 通知发送异常（不影响结果）：{clean(exc, 160)}")

    failed = [r for r in results if not r.get("skipped") and not r.get("success")]
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⏹️ 已手动中断")
        sys.exit(130)
