#!/usr/bin/env python3
# name: 捷停车
# cron: 16 13,1 * * *
# -*- coding: utf-8 -*-
# ==============================================
# 捷停车自动任务脚本（青龙面板专用版）
# 功能: 自动完成每日签到、浏览车位优选、浏览找优惠、领取奖励
# 适配: 捷停车小程序 v312 | 品赞代理 | PushPlus推送
# ==============================================
#
# 【青龙环境变量说明】
# YYB_SERVER 必填：wxcode服务地址，多地址换行填写
# PROXY_API 可选：品赞代理提取链接
# PROXY_TYPE 可选：http / socks5，默认http
# PLUSPLUS_TOKEN 可选：推送token
#

import os
import sys
import asyncio
import json
import random
import hashlib
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# 强制全局禁用所有系统代理环境变量
for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
                'ALL_PROXY', 'all_proxy', 'NO_PROXY', 'no_proxy']:
    os.environ.pop(env_var, None)

# ===================== JWT库自动检测与修复 =====================
try:
    import jwt
    if not hasattr(jwt, 'decode'):
        raise ImportError("安装的是错误的jwt库，不是pyjwt")
except ImportError as e:
    print("❌ JWT库错误！请在青龙依赖管理执行以下命令：")
    print("pip uninstall -y jwt PyJWT")
    print("pip install pyjwt")
    sys.exit(1)

try:
    import httpx
    from httpx import AsyncHTTPTransport
    from httpx_socks import AsyncProxyTransport
except ImportError:
    print("❌ 缺少依赖库，请执行：")
    print("pip install httpx[http2] httpx-socks python-dotenv pycryptodome")
    sys.exit(1)

# ===================== 配置项 =====================
# 从环境变量 YYB_SERVER 读取wxcode服务地址，多行换行分隔
SERVERS = []
env_YYB_SERVER = os.getenv("YYB_SERVER", "")
if env_YYB_SERVER:
    raw_lines = env_YYB_SERVER.splitlines()
    SERVERS = [line.strip() for line in raw_lines if line.strip()]

# 账号校验放到 main() 里做，避免模块级打印破坏日志版式

# PushPlus 通知Token（环境变量，可选）
PLUSPLUS_TOKEN = (os.getenv("PLUSPLUS_TOKEN") or os.getenv("PUSHPLUS_TOKEN")
                  or os.getenv("PUSH_PLUS_TOKEN") or "").strip()
# 通知总开关：JTC_NOTIFY=0 关闭青龙 notify.py + PushPlus
NOTIFY_ENABLED = os.getenv("JTC_NOTIFY", "1").strip() != "0"

# 品赞代理配置（环境变量，可选）
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http")
PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"

# 核心代理开关
ENABLE_PER_ACCOUNT_PROXY = True
PROXY_FETCH_INTERVAL = 5000  # 代理提取间隔（毫秒）
ENABLE_DIRECT_FALLBACK = True

# 固定配置（2026-05-13最新抓包）
APPID = "wx24b70f0ad2a9a89a"
APP_VERSION = "312"
XWEB_VERSION = "19823"
TOKEN_BASE_URL = "https://www.jslife.com.cn/wxhttp/weixin/xcx/get_openid_by_code"
BASE_URL = "https://sytgate.jslife.com.cn"
REPORT_URL = "https://etgw.jparking.cn/data-report-gateway/syt-data-report/receive"
TASK_QUERY_URL = "/base-gateway/integral/v2/task/query-new"

# UA池
USER_AGENT_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823",
    f"Mozilla/5.0 (Linux; Android 14; 2512BPNDAC Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.153 Mobile Safari/537.36 XWEB/{XWEB_VERSION} MMWEBSDK/20251006 MiniProgramEnv/android"
]

# 只保留指定的2个浏览任务，其他全部跳过
SKIP_TASKS = {"T02", "T03", "T04", "T05", "T06", "T07", "T08", "T09", "T10",
              "T11", "T12", "T46", "T48", "T49", "T50", "T81", "T87"}

# 强制执行的核心任务
FORCE_EXECUTE_TASKS = [
    ("T01", "浏览找优惠"),
    ("T47", "浏览车位优选")
]

# ===================== 工具函数 =====================
def sleep(ms: int) -> asyncio.Future:
    return asyncio.sleep(ms / 1000)

def random_int(min_val: int, max_val: int) -> int:
    return random.randint(min_val, max_val)


def to_number(value, default=-1):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default

def get_ua() -> str:
    return random.choice(USER_AGENT_LIST)

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

_LOCATION_CACHE: Optional[Tuple[float, float]] = None


def brief_error(value, limit=60):
    text = str(value or "").replace("\n", " ")
    return text[: limit - 1] + "…" if len(text) > limit else text


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def mask(value):
    value = str(value or "")
    if len(value) <= 4:
        return "***"
    if len(value) <= 10:
        return f"{value[:2]}***{value[-2:]}"
    return f"{value[:5]}***{value[-3:]}"

BOX_WIDTH = 48
BOX_INNER = 46

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

def log_title():
    box_top("🅿️ 捷停车 每日任务")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(SERVERS)} 个")
    box_line("💾 缓存", "token_caches/jtc_token_cache.json")
    box_line("🌐 代理", "品赞代理" if PROXY_API else "直连")
    box_bottom()

def log_footer(success_count, fail_count, total_reward):
    box_top("🏁 捷停车 执行汇总")
    box_line("📊 执行结果", f"成功 {success_count} / 失败 {fail_count} / 共 {len(SERVERS)}")
    box_line("🎯 任务奖励", f"{total_reward} 捷停币")
    box_line("🕒 结束时间", now_text())
    box_bottom()

def build_direct_transport() -> AsyncHTTPTransport:
    return AsyncHTTPTransport(verify=False)

def parse_entry(raw_value: str) -> Tuple[str, str, str]:
    """解析 地址@标识[#备注] → (地址, 标识, 备注)"""
    import re
    value = str(raw_value or "").strip()
    if not value or "@" not in value:
        return "", "", ""
    note = ""
    hash_pos = value.rfind("#")
    at_pos = value.rfind("@")
    if hash_pos > at_pos:
        note = value[hash_pos + 1:].strip()
        value = value[:hash_pos].strip()
    at_pos = value.rfind("@")
    server = re.sub(r"^https?://", "", value[:at_pos].strip()).rstrip("/")
    ref = value[at_pos + 1:].strip()
    return server, ref, note


def parse_yyb_go_entry(raw_value: str) -> Tuple[str, str]:
    server, ref, _ = parse_entry(raw_value)
    return server, ref


# ===================== Token 缓存（不过期，鉴权失败自动重登）=====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "jtc_token_cache.json")


def read_token_cache() -> Dict[str, Any]:
    try:
        if not os.path.exists(TOKEN_CACHE_FILE):
            return {}
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_token_cache(cache: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"⚠️ [缓存] 写入失败: {exc}")


def ckey(server: str, ref: str) -> str:
    return f"{server}|{ref}"


def _entry_token(value) -> str:
    if isinstance(value, dict):
        return str(value.get("token") or "").strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _cache_matches(key, server: str, ref: str) -> bool:
    """判断缓存键是否属于该账号（含旧版裸标识/地址@标识/地址@标识#备注）"""
    key = str(key or "").strip()
    if key in (f"{server}|{ref}", ref, f"{server}@{ref}"):
        return True
    if "|" in key:
        left, right = key.rsplit("|", 1)
        return left.strip() == server and right.strip() == ref
    if "@" in key:
        tail = key.split("@", 1)[1].split("#", 1)[0].strip()
        return tail == ref
    return False


def load_cache_entry(server: str, ref: str, raw: str) -> Optional[Dict[str, Any]]:
    """按「地址|标识」取缓存；同账号的旧键按 updatedAt 取最新一条，其余清理"""
    cache = read_token_cache()
    key = ckey(server, ref)
    candidates = []
    for old_key, value in cache.items():
        if not _cache_matches(old_key, server, ref):
            continue
        token = _entry_token(value)
        if not token:
            continue
        updated = str(value.get("updatedAt", "")) if isinstance(value, dict) else ""
        candidates.append((updated, old_key, token))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    updated, best_key, token = candidates[0]
    if best_key != key or len(candidates) > 1:
        cache[key] = {"token": token, "updatedAt": updated or now_text()}
        for _, old_key, _ in candidates:
            if old_key != key:
                cache.pop(old_key, None)
        write_token_cache(cache)
        print("   🗂️ [缓存] 已将旧缓存键迁移为「地址|标识」")
    entry = cache.get(key)
    if isinstance(entry, dict) and entry.get("token"):
        return entry
    return {"token": token, "updatedAt": updated or now_text()}


def save_cache_entry(server: str, ref: str, token: str) -> None:
    cache = read_token_cache()
    cache[ckey(server, ref)] = {"token": token, "updatedAt": now_text()}
    write_token_cache(cache)


def drop_cache_entry(server: str, ref: str) -> None:
    cache = read_token_cache()
    for old_key in list(cache.keys()):
        if _cache_matches(old_key, server, ref):
            cache.pop(old_key, None)
    write_token_cache(cache)


AUTH_PATTERN = None

def is_auth_fail_msg(msg: Any) -> bool:
    global AUTH_PATTERN
    import re
    if AUTH_PATTERN is None:
        AUTH_PATTERN = re.compile(
            r'登录已失效|登录已过期|登录态失效|登录态过期|请重新登录|请先登录|未登录'
            r'|token\s*(失效|过期|无效)|授权失效|授权过期|身份验证失败|凭证失效'
            r'|unauthorized|-401|\b401\b|\b403\b', re.IGNORECASE)
    return bool(AUTH_PATTERN.search(str(msg)))


async def get_code_via_yyb(server_entry: str, appid: str) -> Optional[str]:
    server, ref = parse_yyb_go_entry(server_entry)
    if not server:
        print(f"❌ [取码] [{server_entry}] 获取code失败 | 服务地址为空")
        return None
    if not ref:
        print(f"❌ [取码] [{server_entry}] 获取code失败 | 缺少openid/ref")
        return None

    url = f"http://{server}/wxapp/getCode"
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=False, trust_env=False) as client:
            response = await client.post(url, json={"ref": ref, "app_id": appid})
            res = response.json()

        payload = res.get("data") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        result_obj = (payload or {}).get("result")
        if isinstance(result_obj, str):
            try:
                result_obj = json.loads(result_obj)
            except Exception:
                result_obj = {}
        code = (result_obj or {}).get("code")
        if to_number(res.get("code")) != 0 or not code:
            print(f"❌ [取码] [{server_entry}] 获取code失败 | 返回异常: {str(res)[:200]}")
            return None

        print("   ✅ [取码] code 获取成功")
        return code
    except json.JSONDecodeError:
        print(f"❌ [取码] [{server_entry}] 获取code失败 | 响应不是JSON格式")
        return None
    except Exception as e:
        print(f"❌ [取码] [{server_entry}] 获取code异常 | 原因: {str(e)}")
        return None

# ===================== 品赞代理系统 =====================
def parse_proxy_response(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if not text:
        return None

    try:
        data = json.loads(text)
        proxy_obj = None
        if data.get("data") and isinstance(data["data"], list) and len(data["data"]) > 0:
            proxy_obj = data["data"][0]
        elif data.get("ip") and data.get("port"):
            proxy_obj = data
        elif data.get("result") and data.get("result").get("ip") and data.get("result").get("port"):
            proxy_obj = data["result"]

        if proxy_obj:
            return {
                "host": proxy_obj["ip"],
                "port": int(proxy_obj["port"]),
                "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                "password": proxy_obj.get("pass") or proxy_obj.get("password") or ""
            }
    except json.JSONDecodeError:
        if ":" in text:
            parts = text.split(":")
            if len(parts) >= 2:
                return {
                    "host": parts[0],
                    "port": int(parts[1]),
                    "username": parts[2] if len(parts) >= 3 else "",
                    "password": parts[3] if len(parts) >= 4 else ""
                }
    return None

async def validate_proxy(proxy_info: Dict[str, Any]) -> bool:
    if not proxy_info:
        return False

    try:
        transport = build_proxy_transport(proxy_info)
        async with httpx.AsyncClient(transport=transport, timeout=15.0, verify=False) as client:
            response = await client.get(PROXY_VALIDATE_URL)
            if response.status_code == 200:
                ip = response.json().get("origin", "未知")
                print(f"✅ [代理] 验证通过 | 出口IP: {ip} | 预计有效期: 5分钟")
                return True
    except Exception as e:
        print(f"⚠️ [代理] 验证失败 | 原因: {str(e)}")
    return False

def build_proxy_transport(proxy_info: Dict[str, Any]) -> Optional[AsyncProxyTransport]:
    if not proxy_info:
        return None

    host = proxy_info["host"]
    port = proxy_info["port"]
    username = proxy_info["username"]
    password = proxy_info["password"]

    try:
        if PROXY_TYPE == "socks5":
            proxy_url = f"socks5://{username}:{password}@{host}:{port}" if username and password else f"socks5://{host}:{port}"
        else:
            proxy_url = f"http://{username}:{password}@{host}:{port}" if username and password else f"http://{host}:{port}"

        return AsyncProxyTransport.from_url(proxy_url, verify=False)
    except Exception as e:
        print(f"❌ [代理] 生成失败 | 原因: {str(e)}")
        return None

async def get_valid_proxy(account_name: str) -> Optional[Dict[str, Any]]:
    if not PROXY_API:
        print(f"ℹ️ [代理] [{account_name}] 未配置代理 | 使用直连模式")
        return None

    print(f"🔌 [代理] [{account_name}] 正在获取专属代理...")

    for i in range(PROXY_RETRY_TIMES):
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=build_direct_transport()) as client:
                response = await client.get(PROXY_API)
            proxy_info = parse_proxy_response(response.text)

            if not proxy_info:
                print(f"⚠️ [代理] [{account_name}] 第{i+1}次获取代理失败 | 响应格式错误")
                continue

            if await validate_proxy(proxy_info):
                return proxy_info
            else:
                print(f"⚠️ [代理] [{account_name}] 第{i+1}次代理不可用 | 重试中...")

        except Exception as e:
            print(f"⚠️ [代理] [{account_name}] 第{i+1}次获取代理异常 | 原因: {str(e)}")

        if i < PROXY_RETRY_TIMES - 1:
            await sleep(2000)

    print(f"❌ [代理] [{account_name}] 代理获取失败 | 切换直连模式")
    return None

# ===================== 智能代理管理器（新增） =====================
class ProxyManager:
    def __init__(self, account_name: str):
        self.account_name = account_name
        self.proxy_info: Optional[Dict[str, Any]] = None
        self.rebuild_count = 0
        self.max_rebuild = 3  # 单账号最多重建3次代理
        self.last_rebuild_time = 0

    async def get_proxy(self) -> Optional[Dict[str, Any]]:
        """获取有效代理（首次获取或重建时调用）"""
        if not PROXY_API:
            return None

        # 防止频繁重建
        if time.time() - self.last_rebuild_time < 5:
            await sleep(2000)

        self.proxy_info = await get_valid_proxy(self.account_name)
        self.last_rebuild_time = time.time()
        return self.proxy_info

    async def rebuild(self) -> bool:
        """重建代理（失败时自动降级为直连）"""
        if self.rebuild_count >= self.max_rebuild:
            print(f"❌ [代理] [{self.account_name}] 代理重建次数已达上限，切换为直连模式")
            self.proxy_info = None
            return False

        self.rebuild_count += 1
        print(f"🔄 [代理] [{self.account_name}] 正在重建代理（第{self.rebuild_count}次）...")

        # 关闭旧代理连接
        if self.proxy_info:
            self.proxy_info = None

        new_proxy = await self.get_proxy()
        if new_proxy:
            print(f"✅ [代理] [{self.account_name}] 代理重建成功 | 新出口IP: {new_proxy['host']}:{new_proxy['port']}")
            return True
        else:
            print(f"⚠️ [代理] [{self.account_name}] 代理重建失败，切换为直连模式")
            return False

    def is_proxy_error(self, e: Exception) -> bool:
        """判断是否为代理相关错误"""
        error_str = str(e).lower()
        proxy_error_keywords = [
            "invalid proxy response",
            "proxy connection failed",
            "socks error",
            "connection reset by peer",
            "connection refused",
            "timeout",
            "proxy",
            "transport closed"
        ]
        return any(keyword in error_str for keyword in proxy_error_keywords)

# ===================== PushPlus推送函数 =====================
async def send_plusplus_notification(title: str, content: str) -> None:
    if not PLUSPLUS_TOKEN:
        return

    try:
        async with httpx.AsyncClient(timeout=5.0, transport=build_direct_transport()) as client:
            response = await client.post(
                "https://www.pushplus.plus/send",
                json={
                    "token": PLUSPLUS_TOKEN,
                    "title": title,
                    "content": content,
                    "template": "txt"
                }
            )
        if response.status_code == 200:
            print(f"✅ [推送] 通知推送成功")
    except Exception as e:
        print(f"❌ [推送] 通知推送失败 | 原因: {str(e)}")

# ===================== 数据上报生成器 =====================
class DataReportGenerator:
    def __init__(self):
        self.secret_key = "GaT92Kf6cbDc1Pea9S720GJnL56A14x3R"

    def generate_nonce(self, timestamp=None):
        if timestamp is None:
            timestamp = int(datetime.now().timestamp() * 1000)
        random_7_digits = str(random.randint(1000000, 9999999))
        return f"{random_7_digits}{timestamp}", timestamp

    def generate_sign(self, data):
        sorted_params = []
        for key in sorted(data.keys()):
            value = data[key]
            if value is not None:
                sorted_params.append(f"{key}={value}")
        sign_string = "&".join(sorted_params) + "&" + self.secret_key
        return hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()

    def create_report_data(self, user_id, open_id, event_name="ShowGoToClaim", page_event_name="RentalPage", task_info=None, extra_props=None):
        timestamp = int(datetime.now().timestamp() * 1000)
        nonce, _ = self.generate_nonce(timestamp)

        event_property = {"pageEventName": page_event_name}
        if extra_props and isinstance(extra_props, dict):
            event_property.update(extra_props)

        if event_name == "GoToFinishClick" and task_info:
            event_property.update({
                "TaskName": task_info.get("showTitle", ""),
                "TaskNo": task_info.get("taskNo", ""),
                "pageEventName": "PointsTaskPage",
                "referrer": "pages/my/my",
                "curPgUrl": "subPkg/tcb/index"
            })
        elif event_name in ("TaskStart", "TaskAction", "TaskProgress", "TaskFinish", "TaskReceive") and task_info:
            event_property.update({
                "TaskName": task_info.get("showTitle", ""),
                "TaskNo": task_info.get("taskNo", ""),
                "stage": event_name,
                "pageEventName": "PointsTaskPage",
            })

        data = {
            "opSystem": "windows",
            "opSystemVersion": "Windows 10 x64",
            "phoneModel": "microsoft",
            "brand": "microsoft",
            "language": "zh_CN",
            "userAgent": "",
            "deviceId": "",
            "screenResolution": "415*800",
            "longitude": None,
            "latitude": None,
            "serviceProviders": "",
            "netType": "unknown",
            "productName": "捷停车微信小程序",
            "productVersion": "4.0.6.26",
            "dataSourceType": "JTC_WX_MINI",
            "userId": user_id,
            "openId": open_id,
            "eventStartTime": timestamp,
            "MaterialId": "",
            "SourceId": "",
            "eventType": "activity",
            "eventName": event_name,
            "eventProperty": json.dumps(event_property, ensure_ascii=False),
            "signType": "MD5",
            "timestamp": timestamp,
            "nonce": nonce
        }

        data["sign"] = self.generate_sign(data)
        return data

# ===================== 核心业务类（代理自动重连版） =====================
class JtcBot:
    def __init__(self, server: str, proxy_manager: Optional[ProxyManager] = None):
        self.server = server
        self.proxy_manager = proxy_manager
        self.token = None
        self.user_id = None
        self.open_id = None
        self.longitude = None
        self.latitude = None
        self.ua = get_ua()
        self.device_id = hashlib.md5(str(random.random()).encode()).hexdigest()
        self.client: Optional[httpx.AsyncClient] = None
        self.report_generator = DataReportGenerator()
        self.task_browse_seconds = {}
        self._last_error = ""

    async def __aenter__(self):
        # 初始化代理管理器
        if not self.proxy_manager:
            self.proxy_manager = ProxyManager(self.server)
            await self.proxy_manager.get_proxy()

        # 首次创建客户端
        await self._rebuild_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def _rebuild_client(self) -> None:
        """重建客户端（代理变更时自动调用）"""
        # 关闭旧客户端
        if self.client:
            await self.client.aclose()

        # 根据当前代理状态创建新transport
        if self.proxy_manager and self.proxy_manager.proxy_info:
            transport = build_proxy_transport(self.proxy_manager.proxy_info)
            mode = "代理"
        else:
            transport = build_direct_transport()
            mode = "直连"

        # 创建新客户端，保留所有已有的请求头和token
        self.client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=self._get_base_headers(),
            transport=transport,
            http2=True,
            timeout=30.0,
            verify=False
        )

        if mode == "代理":
            print(f"   🔌 [代理] 客户端已重建 | 当前模式: 代理")

    def _get_base_headers(self) -> Dict[str, Any]:
        headers = {
            "Host": "sytgate.jslife.com.cn",
            "Connection": "keep-alive",
            "applicationVersion": "1.0.1",
            "User-Agent": self.ua,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Referer": f"https://servicewechat.com/{APPID}/{APP_VERSION}/page-frame.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        return headers

    # 通用请求包装器（自动处理代理错误）
    async def _safe_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """安全请求：代理异常时重建代理，再降级直连，最多 3 次"""
        headers = dict(kwargs.get("headers") or {})
        if self.token and not any(k.lower() == "authorization" for k in headers):
            headers["Authorization"] = f"Bearer {self.token}"
        if headers:
            kwargs["headers"] = headers
        last_error = None
        for attempt in range(3):
            try:
                return await self.client.request(method, url, **kwargs)
            except Exception as exc:
                last_error = exc
                is_proxy = self.proxy_manager and self.proxy_manager.is_proxy_error(exc)
                if not is_proxy:
                    raise
                if attempt == 0 and self.proxy_manager and self.proxy_manager.proxy_info:
                    print(f"   ⚠️ [请求] 代理异常：{brief_error(exc)}")
                    await self.proxy_manager.rebuild()
                    await self._rebuild_client()
                    continue
                if attempt == 1 and self.proxy_manager and self.proxy_manager.proxy_info:
                    print("   ⚠️ [请求] 代理仍异常，切换直连重试")
                    self.proxy_manager.proxy_info = None
                    await self._rebuild_client()
                    continue
                raise
        raise last_error or Exception("请求失败")

    async def get_code(self) -> Optional[str]:
        """从本地 YYB 服务获取 code，失败重试一次"""
        for attempt in range(2):
            code = await get_code_via_yyb(self.server, APPID)
            if code:
                return code
            if attempt == 0:
                print("   🔁 [取码] 失败，2 秒后重试")
                await sleep(2000)
        return None

    async def get_token_by_code(self, code: str) -> Optional[str]:
        """通过code换取token（适配最新obj响应格式）"""
        print(f"   🔑 [登录] 正在换取token...")

        timestamp = int(time.time() * 1000)
        token_url = f"{TOKEN_BASE_URL}?t={timestamp}"

        headers = {
            "Host": "www.jslife.com.cn",
            "Connection": "keep-alive",
            "applicationVersion": "1.0.1",
            "User-Agent": self.ua,
            "xweb_xhr": "1",
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "*/*",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": f"https://servicewechat.com/{APPID}/{APP_VERSION}/page-frame.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }

        payload = {
            "code": code,
            "userType": "WX_XCX_JTC",
            "appId": APPID
        }

        mode = "代理" if (self.proxy_manager and self.proxy_manager.proxy_info) else "直连"
        try:
            transport = build_proxy_transport(self.proxy_manager.proxy_info) if self.proxy_manager and self.proxy_manager.proxy_info else build_direct_transport()

            async with httpx.AsyncClient(
                transport=transport,
                headers=headers,
                timeout=20.0,
                http2=True,
                verify=False
            ) as client:
                response = await client.post(token_url, json=payload)

            if response.status_code != 200:
                raise Exception(f"HTTP错误: {response.status_code}")

            res = response.json()
            # 适配最新响应格式（resultCode=0表示成功，token在obj字段）
            if res.get("resultCode") == "0" and res.get("obj") and res["obj"].get("token"):
                self.token = res["obj"]["token"]
                print(f"   ✅ [登录] 获取token成功 | 模式: {mode}")
                return self.token
            # 兼容旧格式
            elif (res.get("success") and res.get("data") and res["data"].get("token")):
                self.token = res["data"]["token"]
                print(f"   ✅ [登录] 获取token成功（旧格式）| 模式: {mode}")
                return self.token
            else:
                raise Exception(f"业务错误: {res.get('message', '未知错误')}")
        except Exception as e:
            print(f"   ⚠️ [登录] {mode}获取token失败 | 原因: {str(e)}")

            if self.proxy_manager.proxy_info and ENABLE_DIRECT_FALLBACK:
                print(f"   🌐 [登录] 切换直连重试...")
                try:
                    async with httpx.AsyncClient(
                        headers=headers,
                        timeout=20.0,
                        http2=True,
                        transport=build_direct_transport(),
                        verify=False
                    ) as client:
                        response = await client.post(token_url, json=payload)

                    res = response.json()
                    if res.get("resultCode") == "0" and res.get("obj") and res["obj"].get("token"):
                        self.token = res["obj"]["token"]
                        print(f"   ✅ [登录] 直连获取token成功")
                        return self.token
                    elif (res.get("success") and res.get("data") and res["data"].get("token")):
                        self.token = res["data"]["token"]
                        print(f"   ✅ [登录] 直连获取token成功（旧格式）")
                        return self.token
                    else:
                        raise Exception(f"直连业务错误: {res.get('message', '未知错误')}")
                except Exception as e2:
                    print(f"   ❌ [登录] 直连获取token失败 | 原因: {str(e2)}")

        return None

    def parse_jwt(self):
        """解析JWT获取用户信息（兼容新token格式）"""
        try:
            decoded = jwt.decode(self.token, options={"verify_signature": False}, algorithms=["HS256"])
            sub_data = json.loads(decoded.get("sub", "{}"))
            self.user_id = sub_data.get("userId")
            self.open_id = sub_data.get("id")
            exp = decoded.get("exp")
            return exp
        except Exception as e:
            print(f"   ❌ [登录] JWT解析失败 | 原因: {str(e)}")
            return None

    async def get_location_info(self):
        """获取经纬度坐标信息（同一次运行内复用）"""
        global _LOCATION_CACHE
        if _LOCATION_CACHE:
            self.longitude, self.latitude = _LOCATION_CACHE
            print(f"   📍 [定位] 复用坐标 | 经度: {self.longitude:.6f} | 纬度: {self.latitude:.6f}")
            return True
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=build_direct_transport(), verify=False) as client:
                response = await client.get("https://ipinfo.io/json")
                data = response.json()

            loc = data.get("loc", "")
            if loc and "," in loc:
                lat_str, lon_str = loc.split(",")
                base_lat = float(lat_str.strip())
                base_lon = float(lon_str.strip())

                self.longitude = base_lon + random.randint(0, 9999999999999) / 10**16
                self.latitude = base_lat + random.randint(0, 999999999999999) / 10**18

                _LOCATION_CACHE = (self.longitude, self.latitude)
                print(f"   📍 [定位] 经纬度已补全 | 经度: {self.longitude:.6f} | 纬度: {self.latitude:.6f}")
                return True
            else:
                raise Exception("无法解析经纬度")
        except Exception as e:
            print(f"   ℹ️ [定位] 使用默认北京坐标 | 原因: {str(e)}")
            self.longitude = 116.413384
            self.latitude = 39.910925
            _LOCATION_CACHE = (self.longitude, self.latitude)
            return True

    async def send_data_report(self, event_name="ShowGoToClaim", task_info=None, extra_props=None):
        """异步埋点数据上报（使用安全请求）"""
        try:
            report_data = self.report_generator.create_report_data(
                self.user_id, self.open_id, event_name, "RentalPage", task_info, extra_props
            )
            report_data["longitude"] = self.longitude
            report_data["latitude"] = self.latitude

            headers = {
                "Host": "etgw.jparking.cn",
                "applicationVersion": "1.0.0",
                "User-Agent": self.ua,
                "xweb_xhr": "1",
                "Content-Type": "application/json",
                "uc_id": self.open_id,
                "Accept": "*/*",
                "Referer": f"https://servicewechat.com/{APPID}/{APP_VERSION}/page-frame.html",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "zh-CN,zh;q=0.9"
            }

            transport = build_proxy_transport(self.proxy_manager.proxy_info) if self.proxy_manager.proxy_info else build_direct_transport()

            async with httpx.AsyncClient(
                transport=transport,
                timeout=15.0,
                verify=False
            ) as client:
                await client.post(REPORT_URL, headers=headers, json=report_data)
            return True
        except Exception as e:
            return False

    def check_response(self, response_data):
        """检查响应是否正常（resultCode / code 可能是字符串或数字）"""
        if not isinstance(response_data, dict):
            self._last_error = "响应不是JSON对象"
            return False
        ok_code = to_number(response_data.get("resultCode"), -999) == 0 \
            or to_number(response_data.get("code"), -999) == 0
        if not ok_code:
            error_msg = response_data.get("message") or "未知错误"
            self._last_error = error_msg
            # 特殊处理："已达到最大领取次数"视为成功
            if "已达到最大领取次数" in str(error_msg):
                print(f"   ℹ️ [请求] {error_msg}")
                return True
            print(f"   ❌ [请求] 请求失败 | 原因: {error_msg}")
            return False
        return True

    def safe_get_reward(self, data, default=0):
        if data is None:
            return default
        if isinstance(data, (int, float)):
            return int(data)
        if isinstance(data, str):
            try:
                return int(float(data))
            except:
                return default
        if isinstance(data, dict):
            for key in ("amount", "value", "points", "integral", "data", "reward", "cnt", "count"):
                if key in data:
                    return self.safe_get_reward(data.get(key), default)
        return default

    def format_phone(self, phone):
        phone = str(phone or "未知").strip() or "未知"
        if len(phone) == 11:
            return f"{phone[:3]}****{phone[-4:]}"
        return phone

    async def get_user_info(self):
        """获取用户信息（使用安全请求）"""
        try:
            response = await self._safe_request(
                "POST",
                "/core-gateway/user/query/attention/info",
                json={"h5Source": "WX_XCX_JTC", "openId": self.open_id}
            )
            if response.status_code in (401, 403):
                self._last_error = f"HTTP {response.status_code}"
                return None
            response_data = response.json()

            if self.check_response(response_data):
                return response_data.get("obj", {})
            return None
        except Exception as e:
            print(f"   ❌ [用户] 获取用户信息失败 | 原因: {str(e)}")
            return None

    async def perform_sign_in(self):
        """执行签到操作（使用安全请求）"""
        print(f"   📝 [签到] 开始执行签到...")

        try:
            # 签到任务查询
            await self._safe_request(
                "POST",
                "/base-gateway/integral/v2/sign-in-task/query",
                json={"userId": self.user_id, "platformType": "WX_XCX_JTC"}
            )
            await sleep(1000)

            # 气泡奖励查询
            await self._safe_request(
                "POST",
                "/base-gateway/integral/v2/show/header-pop/query",
                json={"userId": self.user_id, "platformType": "WX_XCX_JTC", "osType": "ANDROID", "reqVersion": "V2.0"}
            )
            await sleep(1000)

            # 领取签到奖励
            response = await self._safe_request(
                "POST",
                "/base-gateway/integral/v2/task/receive",
                json={
                    "userId": self.user_id,
                    "taskNo": "T00",
                    "reqSource": "WX_XCX_JTC",
                    "platformType": "WX_XCX_JTC",
                    "osType": "ANDROID",
                    "deviceId": self.device_id,
                    "token": self.token
                }
            )
            response_data = response.json()

            message = response_data.get("message") or ""
            text = str(message)
            if any(word in text for word in ("今日已签到", "已签到", "重复签到", "已达到最大领取次数")):
                self._last_error = ""
                print(f"   ℹ️ [签到] 今日已签到")
                return True, "今日已签到", False
            if self.check_response(response_data):
                reward = self.safe_get_reward(response_data.get("data"), 0)
                msg = f"签到成功（+{reward} 捷停币）" if reward > 0 else "签到成功"
                print(f"   ✅ [签到] {msg}")
                return True, msg, False
            print(f"   ❌ [签到] 签到失败 | {message}")
            return False, f"签到失败：{message}", is_auth_fail_msg(message)
        except Exception as exc:
            print(f"   ❌ [签到] 签到异常 | 原因: {exc}")
            return False, f"签到异常：{exc}", is_auth_fail_msg(exc)

    async def get_task_list(self):
        """获取任务列表（使用安全请求）"""
        try:
            task_headers = {
                **self._get_base_headers(),
                "applicationVersion": "1.0.0",
                "UC_ID": self.open_id
            }

            payload = {
                "userId": self.user_id,
                "platformType": "WX_XCX_JTC",
                "osType": "ANDROID",
                "reqVersion": "V2.0"
            }

            response = await self._safe_request(
                "POST",
                TASK_QUERY_URL,
                headers=task_headers,
                json=payload
            )
            response_data = response.json()

            if self.check_response(response_data):
                task_data = response_data.get("data", [])
                for task in task_data:
                    task_no = task.get("taskNo")
                    self.task_browse_seconds[task_no] = task.get("browseSeconds", 10)
                pending_receive = sum(1 for t in task_data if t.get("taskStatus") == "RECEIVE")
                pending_do = sum(1 for t in task_data if t.get("taskStatus") == "GOTO")
                skipped = sum(1 for t in task_data if t.get("taskNo") in SKIP_TASKS)
                print(f"   📋 [任务] 共 {len(task_data)} 个｜待领取 {pending_receive}｜待完成 {pending_do}｜跳过 {skipped}")
                return task_data
            return []
        except Exception as e:
            print(f"   ❌ [任务] 获取任务列表失败 | 原因: {str(e)}")
            return []

    async def receive_task_reward(self, task_no, task_info=None):
        """领取任务奖励（使用安全请求）"""
        show_title = task_info.get("showTitle", "") if task_info else ""

        await self.send_data_report("GoToClaimClick", task_info)
        await sleep(200)
        await self.send_data_report("TaskReceive", task_info, extra_props={"step": "receive_start"})
        await sleep(200)
        await self.send_data_report("ClaimClick", task_info)
        await sleep(300)

        try:
            response = await self._safe_request(
                "POST",
                "/base-gateway/integral/v2/task/receive",
                json={
                    "userId": self.user_id,
                    "taskNo": task_no,
                    "reqSource": "WX_XCX_JTC",
                    "platformType": "WX_XCX_JTC",
                    "osType": "ANDROID"
                }
            )
            response_data = response.json()

            if self.check_response(response_data):
                reward = self.safe_get_reward(response_data.get("data", 0))
                if reward > 0:
                    print(f"   ✅ [奖励] 领取【{show_title}】奖励 | +{reward}捷停币")
                return reward
            return 0
        except Exception as e:
            print(f"   ❌ [奖励] 领取【{show_title}】奖励失败 | 原因: {str(e)}")
            return 0

    async def simulate_task_action(self, task_no, task_info=None):
        """模拟任务操作（自动适配接口要求的停留时间）"""
        await self.send_data_report("TaskStart", {"taskNo": task_no, "showTitle": ""}, extra_props={"step": "start"})
        await sleep(200)

        # 获取接口要求的停留时间，默认10秒
        stay_seconds = max(self.task_browse_seconds.get(task_no, 10) - 2, 5)

        if task_no == "T01":  # 浏览找优惠
            print(f"   ⏳ [浏览] 进入【找优惠】页面，停留{stay_seconds}秒...")
            await self.send_data_report("PageView")
            await sleep(1000)
            await self.send_data_report("FindDiscountClick")
            await sleep(1000)
            # 严格按照接口要求停留
            await sleep(stay_seconds * 1000)
            await self.send_data_report("TaskAction", {"taskNo": task_no}, extra_props={"action": "find_discount"})
            await sleep(500)

        elif task_no == "T47":  # 浏览车位优选（已更新为最新编号）
            print(f"   ⏳ [浏览] 进入【车位优选】页面，停留{stay_seconds}秒...")
            await self.send_data_report("PageView")
            await sleep(1000)
            await self.send_data_report("ParkingSpaceClick")
            await sleep(1000)
            # 严格按照接口要求停留
            await sleep(stay_seconds * 1000)
            await self.send_data_report("TaskAction", {"taskNo": task_no}, extra_props={"action": "view_parking"})
            await sleep(500)

        await self.send_data_report("TaskProgress", {"taskNo": task_no}, extra_props={"progress": "100%"})
        await sleep(200)

    async def complete_task(self, task_no, task_info=None):
        """完成任务（使用安全请求，自动处理代理错误）"""
        show_title = task_info.get("showTitle", "") if task_info else ""

        if task_info and task_info.get("taskStatus") == "DOWN":
            print(f"   ℹ️ [任务] 【{show_title}】已完成，跳过执行")
            return True

        print(f"   🔄 [任务] 正在完成【{show_title}】")

        try:
            await self.simulate_task_action(task_no, task_info)

            if task_info:
                await self.send_data_report("GoToFinishClick", task_info)
                await sleep(500)

            await self.send_data_report("TaskProgress", task_info, extra_props={"progress": "near_finish"})
            await sleep(300)

            response = await self._safe_request(
                "POST",
                "/base-gateway/integral/v2/task/complete",
                json={
                    "userId": self.user_id,
                    "taskNo": task_no,
                    "receiveTag": True,
                    "reqSource": "WX_XCX_JTC",
                    "platformType": "WX_XCX_JTC",
                    "osType": "IOS",
                    "token": self.token
                }
            )
            response_data = response.json()

            if self.check_response(response_data):
                await sleep(500)
                await self.send_data_report("TaskFinish", task_info, extra_props={"stage": "finish"})
                await sleep(200)
                await self.send_data_report("ShowGoToClaim", task_info)

                reward = self.safe_get_reward(response_data.get("data", 0))
                if reward > 0:
                    print(f"   ✅ [任务] 完成【{show_title}】| +{reward}捷停币")
                return True
            else:
                print(f"   ❌ [任务] 完成【{show_title}】失败")
                return False
        except Exception as e:
            print(f"   ❌ [任务] 完成【{show_title}】异常 | 原因: {str(e)}")
            return False

    async def get_balance(self):
        """获取账户余额（使用安全请求）"""
        try:
            response = await self._safe_request(
                "POST",
                "/base-gateway/integral/v2/balance/query",
                json={"reqSource": "WX_XCX_JTC", "userId": self.user_id, "openId": self.open_id}
            )
            response_data = response.json()

            if self.check_response(response_data):
                return response_data.get("data", {})
            return {}
        except Exception as e:
            print(f"   ❌ [余额] 获取余额失败 | 原因: {str(e)}")
            return {}

    async def run(self) -> Dict[str, Any]:
        """运行主流程：缓存校验 → 登录 → 签到 → 任务 → 余额"""
        result = {
            "server": self.server,
            "success": False,
            "login_source": "",
            "proxy_status": "直连" if not (self.proxy_manager and self.proxy_manager.proxy_info) else "专属代理",
            "phone": "未知",
            "sign_msg": "",
            "task_count": 0,
            "total_reward": 0,
            "balance": "未知",
            "deduct_amount": 0,
            "error": ""
        }

        server, ref, _ = parse_entry(self.server)
        cache_invalidated = False

        try:
            await sleep(random_int(2000, 5000))

            entry = load_cache_entry(server, ref, self.server)
            self.token = entry.get("token", "") if entry else ""
            if self.token:
                print(f"   💾 [缓存] 复用已保存的 token（{mask(self.token)}）")

            for relogin_attempt in range(2):
                # ---------- ① 缓存：JWT + 用户信息（只读）作为开跑前校验 ----------
                if relogin_attempt == 0 and self.token:
                    self.parse_jwt()
                    if not self.user_id or not self.open_id:
                        print("   ♻️ [缓存] token 结构异常（JWT 解析失败），清理缓存后重新登录")
                        drop_cache_entry(server, ref)
                        self.token = ""
                        cache_invalidated = True
                    else:
                        user_info = await self.get_user_info()
                        if user_info is not None:
                            user_info = user_info or {}
                            result["login_source"] = "缓存"
                            result["phone"] = self.format_phone(user_info.get("telephone", "未知"))
                            print("   ✅ [校验] 登录凭证校验通过（用户信息接口）")
                        elif is_auth_fail_msg(self._last_error):
                            print(f"   ♻️ [缓存] 登录凭证失效（{self._last_error}），清理缓存后重新登录")
                            drop_cache_entry(server, ref)
                            self.token = ""
                            cache_invalidated = True
                        else:
                            print(f"   ❌ [用户] 缓存 token 校验失败，保留缓存不删除：{self._last_error}")
                            result["error"] = f"缓存 token 校验失败（{self._last_error}）"
                            return result

                # ---------- ② 登录 ----------
                if not self.token:
                    if relogin_attempt == 1:
                        print("   ♻️ [登录] 重新登录后再试一次")
                    code = await self.get_code()
                    if not code:
                        result["error"] = "取码失败（检查 YYB 服务地址与账号标识）"
                        return result
                    token = await self.get_token_by_code(code)
                    if not token:
                        result["error"] = "获取 token 失败"
                        return result
                    self.token = token
                    save_cache_entry(server, ref, self.token)
                    result["login_source"] = "缓存失效重登" if cache_invalidated else "新登录"

                    self.parse_jwt()
                    if not self.user_id or not self.open_id:
                        result["error"] = "JWT 解析失败（token 无法解出用户信息）"
                        print("   ❌ [登录] JWT 解析失败")
                        return result
                    user_info = await self.get_user_info()
                    if user_info is not None:
                        user_info = user_info or {}
                    if user_info is None:
                        if is_auth_fail_msg(self._last_error) and relogin_attempt == 0:
                            print("   ♻️ [登录] 新 token 校验未通过，清理缓存后重登一次")
                            drop_cache_entry(server, ref)
                            self.token = ""
                            continue
                        result["error"] = f"登录后用户信息查询失败（{self._last_error}）"
                        print(f"   ❌ [用户] {result['error']}")
                        return result
                    result["phone"] = self.format_phone(user_info.get("telephone", "未知"))
                    print("   ✅ [校验] 登录凭证校验通过（用户信息接口）")

                if cache_invalidated and result["login_source"] == "缓存":
                    result["login_source"] = "缓存失效重登"
                result["login_source"] = result["login_source"] or "缓存"
                print(f"   👤 [用户] {result['phone']}")

                # ---------- ③ 余额（登录行下紧跟币值） ----------
                await self.get_location_info()
                balance_info = await self.get_balance()
                balance_before = balance_info.get("accountAmt", 0) if balance_info else 0
                result["balance"] = balance_before
                result["deduct_amount"] = balance_info.get("deductAmount", 0) if balance_info else 0
                print(f"   💰 [余额] 当前 {balance_before} 捷停币｜可抵扣 {result['deduct_amount']} 元")

                # ---------- ④ 签到 ----------
                sign_ok, sign_msg, sign_auth = await self.perform_sign_in()
                result["sign_msg"] = sign_msg
                if not sign_ok and sign_auth and result["login_source"] == "缓存" and relogin_attempt == 0:
                    print(f"   ♻️ [签到] 鉴权失败（{sign_msg}），清理缓存后重登重跑")
                    drop_cache_entry(server, ref)
                    self.token = ""
                    cache_invalidated = True
                    continue
                await sleep(1000)

                # ---------- ⑤ 任务 ----------
                task_data = await self.get_task_list()
                receivable_tasks = []
                incomplete_tasks = []
                task_info_map = {}

                if task_data:
                    for task in task_data:
                        task_no = task.get("taskNo")
                        task_status = task.get("taskStatus")
                        show_title = task.get("showTitle", "")
                        task_info_map[task_no] = task
                        if task_no in SKIP_TASKS:
                            print(f"   ⏭️ [任务] 跳过：{show_title}")
                            continue
                        if task_status == "RECEIVE":
                            receivable_tasks.append((task_no, show_title))
                        elif task_status == "GOTO":
                            incomplete_tasks.append((task_no, show_title))

                print(f"   🔧 [任务] 检查强制核心任务...")
                for task_no, show_title in FORCE_EXECUTE_TASKS:
                    if task_no not in task_info_map and task_no not in SKIP_TASKS:
                        print(f"   ➕ [任务] 添加强制任务：{show_title}")
                        incomplete_tasks.append((task_no, show_title))
                        task_info_map[task_no] = {"taskNo": task_no, "showTitle": show_title, "taskStatus": "GOTO"}

                for task_no, show_title in receivable_tasks:
                    reward = await self.receive_task_reward(task_no, task_info_map.get(task_no))
                    result["total_reward"] += reward
                    await sleep(1000)

                for task_no, show_title in incomplete_tasks:
                    success = await self.complete_task(task_no, task_info_map.get(task_no))
                    if success:
                        result["task_count"] += 1
                        await sleep(1000)
                        await sleep(3000)
                        reward = await self.receive_task_reward(task_no, task_info_map.get(task_no))
                        result["total_reward"] += reward

                # ---------- ⑥ 复查余额 ----------
                balance_info = await self.get_balance()
                if balance_info:
                    balance_after = balance_info.get("accountAmt", 0)
                    result["balance"] = f"{balance_before} → {balance_after}"
                    result["deduct_amount"] = balance_info.get("deductAmount", 0)
                    print(f"   💰 [余额] {balance_before} → {balance_after} 捷停币")

                result["success"] = bool(sign_ok)
                if sign_ok:
                    print("   ✅ [完成] 该账号任务执行完成")
                else:
                    result["error"] = result["error"] or sign_msg
                    print(f"   ⚠️ [完成] {sign_msg}")
                return result

        except Exception as exc:
            result["error"] = str(exc)
            print(f"   ❌ [异常] 执行异常 | 原因: {exc}")

        return result

# ===================== 通知 =====================
def send_qinglong_notify(title: str, content: str) -> bool:
    import importlib.util
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


def build_notify(results):
    ok = sum(1 for r in results if r.get("success"))
    lines = [f"【捷停车】每日任务", f"成功 {ok} / 失败 {len(results) - ok} / 共 {len(results)}", ""]
    for r in results:
        flag = "✅" if r.get("success") else "❌"
        lines.append(f"{flag} {r.get('server')}（{r.get('phone')}）")
        lines.append(f"   登录：{r.get('login_source') or '-'}")
        lines.append(f"   签到：{r.get('sign_msg') or '-'}")
        lines.append(f"   任务：处理 {r.get('task_count')} 个，今日 +{r.get('total_reward')} 捷停币")
        lines.append(f"   余额：{r.get('balance')} 捷停币，可抵扣 {r.get('deduct_amount')} 元")
        if not r.get("success"):
            lines.append(f"   失败：{r.get('error') or '-'}")
        lines.append("")
    return "\n".join(lines)


# ===================== 主程序 =====================
async def main():
    if not SERVERS:
        print("❌ 未配置环境变量 YYB_SERVER")
        print("格式：YYB Go 服务地址@微信账号标识[#备注]，多账号换行分隔")
        return []
    valid = [item for item in SERVERS if "@" in item]
    invalid = [item for item in SERVERS if "@" not in item]
    if not valid:
        print("❌ YYB_SERVER 无有效账号（格式：地址@标识[#备注]）")
        return []
    for line in invalid:
        print(f"   ❌ [账号] 格式应为 地址@标识[#备注]，已跳过：{brief_error(line)}")

    SERVERS[:] = valid
    log_title()

    results = []
    for index, server in enumerate(SERVERS):
        server_addr, ref, note = parse_entry(server)
        title = f"标识 {ref}" + (f"（{note}）" if note else "")
        source = f"{server_addr}@{ref}" + (f"#{note}" if note else "")
        account_frame(index + 1, len(SERVERS), title, source)

        try:
            proxy_manager = ProxyManager(server)
            if ENABLE_PER_ACCOUNT_PROXY and PROXY_API:
                await proxy_manager.get_proxy()
                await sleep(PROXY_FETCH_INTERVAL)

            async with JtcBot(server, proxy_manager) as bot:
                result = await bot.run()
                results.append(result)
        except Exception as exc:
            print(f"   ❌ [执行] 账号 {index + 1} 未捕获异常：{exc}")
            results.append({
                "server": server, "success": False, "login_source": "", "phone": "未知",
                "proxy_status": "-", "sign_msg": "", "task_count": 0, "total_reward": 0,
                "balance": "未知", "deduct_amount": 0, "error": f"异常 {exc}"
            })

        hr()
        if index < len(SERVERS) - 1:
            print("   ⏳ 等待2秒后执行下一个账号...")
            await sleep(2000)

    # 明细在前，汇总框在后
    print()
    for idx, res in enumerate(results, 1):
        ref = parse_entry(res.get("server", ""))[1] or res.get("server")
        title = f"账号 {idx} · 标识 {ref}"
        if res.get("success"):
            print(f"✅ 【{title} · {res.get('phone')}】")
            print(f"   🔐 [登录] {res.get('login_source') or '-'}")
            print(f"   📅 [签到] {res.get('sign_msg') or '-'}")
            print(f"   🎯 [任务] 处理 {res.get('task_count')} 个，今日 +{res.get('total_reward')} 捷停币")
            print(f"   💰 [余额] {res.get('balance')} 捷停币｜可抵扣 {res.get('deduct_amount')} 元")
        else:
            print(f"❌ 【{title}】")
            print(f"   🔐 [登录] {res.get('login_source') or '-'}")
            print(f"   📅 [签到] {res.get('sign_msg') or '-'}")
            print(f"   💰 [余额] {res.get('balance')} 捷停币")
            print(f"   ⚠️ [失败] {res.get('error') or '未知错误'}")

    success_count = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - success_count
    total_reward = sum(r.get("total_reward", 0) for r in results if r.get("success"))
    log_footer(success_count, fail_count, total_reward)

    if NOTIFY_ENABLED:
        content = build_notify(results)
        if send_qinglong_notify("捷停车每日任务完成", content):
            print("   📮 [通知] 已调用青龙 notify.py")
        else:
            print("   ℹ️ [通知] 未找到青龙 notify.py")
        if PLUSPLUS_TOKEN:
            await send_plusplus_notification("捷停车每日任务完成", content)
    else:
        print("   ℹ️ [通知] JTC_NOTIFY=0，已关闭通知")

    return results

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ 用户中断执行")
    except Exception as e:
        print(f"\n❌ 程序异常: {str(e)}")
