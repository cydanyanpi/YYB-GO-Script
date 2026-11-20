#!/usr/bin/env python3
# name: 雀巢
# cron: 40 9,21 * * *
# -*- coding: utf-8 -*-
# ==============================================
# 雀巢会员俱乐部自动任务脚本（青龙面板专用版）
# 版本: v2.2.0
# 更新日期: 2026-11-20
# 功能: 自动完成每日签到、浏览官网、浏览视频号任务
# 适配: 雀巢小程序  | 品赞代理 | PushPlus推送
# ==============================================
#
# 【使用前必读】
# 1. 必须先部署好code获取服务（本地/远程均可）
# 2. 品赞代理为可选配置，无代理可使用直连模式
# 3. 脚本仅用于学习交流，请勿用于商业用途
#
# ==============================================
# 【一、依赖安装】
# 青龙面板执行以下命令安装依赖：
# pip install httpx[http2] httpx-socks python-dotenv
# ==============================================
#
# 【二、环境变量配置（青龙面板-环境变量）】
# ┌───────────────┬──────────┬─────────────────────────────────────┐
# │ 变量名         │ 必填/可选 │ 说明                                │
# ├───────────────┼──────────┼─────────────────────────────────────┤
# │ PROXY_API     │ 可选     │ 品赞代理提取API链接                  │
# │ PROXY_TYPE    │ 可选     │ 代理类型：http(默认) 或 socks5       │
# │ PLUSPLUS_TOKEN│ 可选     │ PushPlus推送Token，用于接收任务结果  │
# │ YYB_SERVER         │ 必填     │ 内网wxcode服务地址，多个换行分隔     │
# └───────────────┴──────────┴─────────────────────────────────────┘
#
# YYB_SERVER示例值（多行换行）：
# 127.0.0.1:8088
# 192.168.1.21:8088
# 10.30.9.49:8088
#
# ==============================================
#
# 【三、青龙面板部署步骤】
# 1. 上传脚本：进入青龙面板-脚本管理-新建脚本，粘贴全部代码保存
# 2. 配置环境变量：进入环境变量-添加变量，按上面表格配置
# 3. 设置定时任务：进入定时任务-添加任务，命令填写：python3 quechao.py
#    推荐定时：0 8 * * * （每天早上8点执行）
# 4. 测试运行：点击任务右侧的运行按钮，查看日志确认是否正常执行
#
# ==============================================
#
# 【四、自定义配置说明（脚本内修改）】
# 1. 代理开关：
#    ENABLE_PER_ACCOUNT_PROXY = True  # 每个账号独立代理（推荐）
#    ENABLE_DIRECT_FALLBACK = True    # 代理失败自动切换直连
#
# 2. 关闭代理：清空PROXY_API环境变量即可自动使用直连模式
#
# ==============================================
#
# 【五、常见问题排查】
# 1. ❌ 获取code失败
#    - 检查code服务是否正常运行
#    - 确认YYB_SERVER内服务器地址和端口是否正确
#    - 测试配置格式：YYB_SERVER=yyb-go:8000@你的openid
#
# 2. ❌ 获取token失败
#    - 确认code未过期（有效期5分钟）
#    - 检查网络是否能访问 crm.nestlechinese.com
#    - 关闭系统代理，使用脚本内置代理或直连
#
# 3. ❌ 代理相关问题
#    - 确认品赞API链接是否正确
#    - 检查代理IP是否有剩余
#    - 尝试切换代理类型为socks5
#
# ==============================================
#
# 【六、更新日志】
# v2.2.0 (2026-11-20)
# - 修复首次运行（无缓存）时跳过登录、直接返回“获取初始积分失败”且不打印任何日志的问题
# - 修复所有静默 return：登录失败/取码失败/换 token 失败现在都有明确提示
# - 缓存键改为“地址|标识”，避免同一标识在不同 YYB 地址下串号；旧缓存自动迁移
# - 日志美化：启动横幅、账号框、逐账号明细（汇总框上方）、积分贴账号登录行
# - 新增青龙 notify.py 推送（QC_NOTIFY=0 可关闭），保留 PushPlus
#
# v2.1.0 (2026-05-13)
# - 优化青龙面板日志格式，code参数专业打印
# - 恢复品赞代理系统，支持单账号独立代理
# - 移除失效的2026年签到接口，解决多余错误提示
# - 精简代码，移除所有失效的抽奖功能
#
# v2.0.0 (2026-05-12)
# - 修复displayVersion大小写错误
# - 新增token有效性验证
# - 同步最新抓包的接口和请求头
#
# ==============================================
#
# 【七、免责声明】
# 本脚本仅供个人学习和研究使用，请勿用于商业用途
# 使用本脚本产生的任何风险由使用者自行承担
# 如有侵权，请联系作者删除
#
# ==============================================

import os
import sys
import asyncio
import json
import random
import importlib.util
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# 强制全局禁用所有系统代理环境变量
for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
                'ALL_PROXY', 'all_proxy', 'NO_PROXY', 'no_proxy']:
    os.environ.pop(env_var, None)

try:
    import httpx
    from httpx import AsyncHTTPTransport
    from httpx_socks import AsyncProxyTransport
except ImportError:
    print("❌ 缺少依赖库，请执行：pip install httpx[http2] httpx-socks python-dotenv")
    sys.exit(1)

# ===================== 配置项 =====================
# 从环境变量 YYB_SERVER 读取内网wxcode服务地址，多条换行分隔
SERVERS = []
env_YYB_SERVER = os.getenv("YYB_SERVER", "")
if env_YYB_SERVER:
    raw_lines = env_YYB_SERVER.splitlines()
    SERVERS = [line.strip() for line in raw_lines if line.strip()]

# 无有效地址直接退出并提示
if len(SERVERS) == 0:
    print("❌ 未配置环境变量 YYB_SERVER")
    print("格式：yyb-go:8000@账号ID或OpenID，多账号换行分隔")
    sys.exit(1)

def parse_yyb_go_entry(raw_value: str) -> Tuple[str, str]:
    value = str(raw_value or "").strip()
    if not value:
        return "", ""
    at_index = value.rfind("@")
    if at_index == -1:
        return value, ""
    server = value[:at_index].strip()
    ref = value[at_index + 1:].strip()
    server = server.removeprefix("http://").removeprefix("https://").rstrip("/")
    return server, ref


async def get_code_via_yyb(server_entry: str, appid: str) -> Optional[str]:
    server, ref = parse_yyb_go_entry(server_entry)
    if not server:
        print(f"❌ [{server_entry}] 获取code失败 | 服务地址为空")
        return None
    if not ref:
        print(f"❌ [{server_entry}] 获取code失败 | 缺少openid/ref")
        return None

    url = f"http://{server}/wxapp/getCode"
    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            response = await client.post(url, json={"ref": ref, "app_id": appid})
            res = response.json()

        code = (((res.get("data") or {}).get("result") or {}).get("code"))
        if res.get("code") != 0 or not code:
            print(f"❌ [{server_entry}] 获取code失败 | 返回异常: {str(res)[:200]}")
            return None

        print(f"✅ [{server}] 获取code成功")
        return code
    except json.JSONDecodeError:
        print(f"❌ [{server_entry}] 获取code失败 | 响应不是JSON格式")
        return None
    except Exception as e:
        print(f"❌ [{server_entry}] 获取code异常 | 原因: {str(e)}")
        return None


PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")

# 品赞代理配置（环境变量，可选）
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http")
PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"

# 核心代理开关
ENABLE_PER_ACCOUNT_PROXY = True
PROXY_FETCH_INTERVAL = 3000
ENABLE_DIRECT_FALLBACK = True

# 固定配置
APPID = "wxc5db704249c9bb31"
APP_VERSION = "491"
XWEB_VERSION = "19823"
TOKEN_CLIENT_ID = "wechatMini"
TOKEN_CLIENT_SECRET = "secret"
TOKEN_GRANT_TYPE = "wechat_auth_code"
TOKEN_GRANT_TYPE_REFRESH = "refresh_token"
TOKEN_URL = "https://crm.nestlechinese.com/openapi/identityservice/connect/token"

# UA池
USER_AGENT_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541923) XWEB/19823",
    f"Mozilla/5.0 (Linux; Android 14; 2512BPNDAC Build/UKQ1.230917.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/146.0.7680.153 Mobile Safari/537.36 XWEB/{XWEB_VERSION} MMWEBSDK/20251006 MiniProgramEnv/android"
]

# 跳过的任务GUID
SKIP_TASK_GUIDS = {"38C8BBDA3DAE4CD685B270D939E5063D", "36EFECD2AD8C44278317ED567EB24DD9"}

# ===================== 工具函数 =====================
def sleep(ms: int) -> asyncio.Future:
    return asyncio.sleep(ms / 1000)

def random_int(min_val: int, max_val: int) -> int:
    return random.randint(min_val, max_val)

def get_ua() -> str:
    return random.choice(USER_AGENT_LIST)


# ===================== 日志美化 =====================
def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def mask_token(token: str) -> str:
    value = str(token or "")
    if len(value) <= 16:
        return value or "-"
    return f"{value[:8]}...{value[-6:]}"


# ===================== Token 缓存（不过期，失效自动重登） =====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "token_caches", "qc_token_cache.json")


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
        print(f"   ⚠️ [缓存] 写入失败（不影响本次执行）: {exc}")


def cache_key(server: str, ref: str) -> str:
    """缓存键：地址|标识，避免不同 YYB 地址下同名标识串号。"""
    return f"{server}|{ref}" if ref else server


def read_cache_entry(ck: str, ref: str) -> Dict[str, Any]:
    cache = read_token_cache()
    entry = cache.get(ck)
    if isinstance(entry, dict) and entry.get("access_token"):
        return entry
    # 兼容旧版仅按 ref 存的缓存：首次读到就迁移到新键
    legacy = cache.get(ref)
    if isinstance(legacy, dict) and legacy.get("access_token"):
        cache[ck] = legacy
        cache.pop(ref, None)
        write_token_cache(cache)
        return legacy
    return {}


def save_cache_entry(ck: str, token: str, refresh: str) -> None:
    cache = read_token_cache()
    cache[ck] = {
        "access_token": token,
        "refresh_token": refresh or "",
        "updated_at": now_text(),
    }
    write_token_cache(cache)


def drop_cache_entry(ck: str) -> None:
    cache = read_token_cache()
    if ck in cache:
        cache.pop(ck, None)
        write_token_cache(cache)

def build_direct_transport() -> AsyncHTTPTransport:
    return AsyncHTTPTransport()

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
        elif data.get("result") and data["result"].get("ip") and data["result"].get("port"):
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
        async with httpx.AsyncClient(transport=transport, timeout=15.0) as client:
            response = await client.get(PROXY_VALIDATE_URL)
            if response.status_code == 200:
                ip = response.json().get("origin", "未知")
                print(f"✅ 代理验证通过 | 出口IP: {ip}")
                return True
    except Exception as e:
        print(f"⚠️ 代理验证失败 | 原因: {str(e)}")
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

        return AsyncProxyTransport.from_url(proxy_url)
    except Exception as e:
        print(f"❌ 代理生成失败 | 原因: {str(e)}")
        return None

async def get_valid_proxy(account_name: str) -> Optional[Dict[str, Any]]:
    if not PROXY_API:
        print(f"ℹ️ [代理] {account_name} 未配置代理 | 使用直连模式")
        return None

    print(f"🔌 [代理] {account_name} 正在获取专属代理...")

    for i in range(PROXY_RETRY_TIMES):
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=build_direct_transport()) as client:
                response = await client.get(PROXY_API)
            proxy_info = parse_proxy_response(response.text)

            if not proxy_info:
                print(f"⚠️ [{account_name}] 第{i+1}次获取代理失败 | 响应格式错误")
                continue

            if await validate_proxy(proxy_info):
                return proxy_info
            else:
                print(f"⚠️ [{account_name}] 第{i+1}次代理不可用 | 重试中...")

        except Exception as e:
            print(f"⚠️ [{account_name}] 第{i+1}次获取代理异常 | 原因: {str(e)}")

        if i < PROXY_RETRY_TIMES - 1:
            await sleep(2000)

    print(f"❌ [{account_name}] 代理获取失败 | 切换直连模式")
    return None

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
            print("✅ 通知推送成功")
    except Exception as e:
        print(f"❌ 通知推送失败 | 原因: {str(e)}")

# ===================== 青龙通知（notify.py） =====================
def send_qinglong_notify(title: str, content: str) -> bool:
    """优先调用青龙自带的 notify.py（send / sendNotify），找不到就跳过。"""
    candidates = [
        "/ql/data/scripts/notify.py",
        "/ql/scripts/notify.py",
        "/ql/data/notify.py",
        os.path.join(SCRIPT_DIR, "notify.py"),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location("qc_ql_notify", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "send"):
                module.send(title, content)
                return True
            if hasattr(module, "sendNotify"):
                module.sendNotify(title, content)
                return True
        except Exception as exc:
            print(f"   ⚠️ [通知] 加载 {path} 失败: {exc}")
    return False

# ===================== 核心业务类 =====================
class QueChaoBot:
    def __init__(self, server: str, proxy_info: Optional[Dict[str, Any]] = None):
        self.server = server
        self.proxy_info = proxy_info
        self.base_url = "https://crm.nestlechinese.com"
        self.token = None
        self.refresh_token = ""
        self.ua = get_ua()
        self.client = None

    async def get_code(self) -> Optional[str]:
        """从本地服务获取code（青龙优化版日志）"""
        return await get_code_via_yyb(self.server, APPID)

    async def get_token_by_code(self, code: str) -> Optional[str]:
        """通过code换取token（简洁日志）"""
        print(f"🔑 正在换取token...")

        headers = {
            "Host": "crm.nestlechinese.com",
            "Connection": "keep-alive",
            "User-Agent": self.ua,
            "xweb_xhr": "1",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": f"https://servicewechat.com/{APPID}/{APP_VERSION}/page-frame.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }

        form_data = {
            "client_id": TOKEN_CLIENT_ID,
            "client_secret": TOKEN_CLIENT_SECRET,
            "grant_type": TOKEN_GRANT_TYPE,
            "auth_code": code
        }

        try:
            transport = build_proxy_transport(self.proxy_info) if self.proxy_info else build_direct_transport()
            mode = "代理" if self.proxy_info else "直连"

            async with httpx.AsyncClient(
                transport=transport,
                headers=headers,
                timeout=20.0,
                http2=True
            ) as client:
                response = await client.post(TOKEN_URL, data=form_data)

            if response.status_code != 200:
                raise Exception(f"HTTP错误: {response.status_code}")

            res = response.json()
            if res.get("access_token") and res.get("token_type", "Bearer").lower() == "bearer":
                self.token = res["access_token"]
                self.refresh_token = res.get("refresh_token", "")
                print(f"✅ [登录] 获取token成功 | 模式: {mode}")
                return self.token
            else:
                raise Exception(f"业务错误: {res.get('error', '未知错误')}")
        except Exception as e:
            print(f"⚠️ {mode}获取token失败 | 原因: {str(e)}")

            if self.proxy_info and ENABLE_DIRECT_FALLBACK:
                print(f"🌐 切换直连重试...")
                try:
                    async with httpx.AsyncClient(
                        headers=headers,
                        timeout=20.0,
                        http2=True,
                        transport=build_direct_transport()
                    ) as client:
                        response = await client.post(TOKEN_URL, data=form_data)

                    res = response.json()
                    if res.get("access_token"):
                        self.token = res["access_token"]
                        self.refresh_token = res.get("refresh_token", "")
                        print(f"✅ [登录] 直连获取token成功")
                        return self.token
                    else:
                        raise Exception(f"直连业务错误: {res.get('error', '未知错误')}")
                except Exception as e2:
                    print(f"❌ 直连获取token失败 | 原因: {str(e2)}")

        return None

    async def refresh_token_by_refresh(self) -> bool:
        """用refresh_token换新的access_token，不用重新走微信授权码"""
        if not self.refresh_token:
            return False

        print(f"🔄 [续期] 使用refresh_token换新access_token...")

        headers = {
            "Host": "crm.nestlechinese.com",
            "Connection": "keep-alive",
            "User-Agent": self.ua,
            "xweb_xhr": "1",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": f"https://servicewechat.com/{APPID}/{APP_VERSION}/page-frame.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }

        form_data = {
            "client_id": TOKEN_CLIENT_ID,
            "client_secret": TOKEN_CLIENT_SECRET,
            "grant_type": TOKEN_GRANT_TYPE_REFRESH,
            "refresh_token": self.refresh_token
        }

        try:
            transport = build_proxy_transport(self.proxy_info) if self.proxy_info else build_direct_transport()
            async with httpx.AsyncClient(
                transport=transport,
                headers=headers,
                timeout=20.0,
                http2=True
            ) as client:
                response = await client.post(TOKEN_URL, data=form_data)

            if response.status_code != 200:
                print(f"⚠️ [续期] refresh_token已失效 (HTTP {response.status_code})")
                return False

            res = response.json()
            if res.get("access_token"):
                self.token = res["access_token"]
                self.refresh_token = res.get("refresh_token", self.refresh_token)
                print(f"✅ [续期] refresh_token续期成功")
                return True
            else:
                print(f"⚠️ [续期] refresh_token返回异常: {res.get('error', '未知')}")
                return False
        except Exception as e:
            print(f"⚠️ [续期] refresh_token续期失败: {str(e)}")
            return False

    async def ensure_token(self) -> bool:
        """确保手里有可用 token：先试 refresh_token 续期，再走微信取码完整登录。"""
        if self.token:
            return True

        if self.refresh_token and await self.refresh_token_by_refresh():
            return True

        code = await self.get_code()
        if not code:
            print("   ❌ [登录] 取码失败（检查 YYB 服务地址 / 标识是否正确）")
            return False

        token = await self.get_token_by_code(code)
        if not token:
            print("   ❌ [登录] code 换 token 失败（确认 code 未过期）")
            return False
        return True

    async def __aenter__(self):
        transport = build_proxy_transport(self.proxy_info) if self.proxy_info else build_direct_transport()
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._get_base_headers(),
            transport=transport,
            http2=True,
            timeout=30.0
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    def _get_base_headers(self) -> Dict[str, str]:
        headers = {
            "Host": "crm.nestlechinese.com",
            "displayVersion": "0",
            "User-Agent": self.ua,
            "xweb_xhr": "1",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Referer": f"https://servicewechat.com/{APPID}/{APP_VERSION}/page-frame.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9"
        }

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        return headers

    def check_response(self, response_data: Dict[str, Any]) -> bool:
        if response_data.get("errcode") != 200:
            print(f"❌ [接口] 请求失败 | 原因: {response_data.get('errmsg', '未知错误')}")
            return False
        return True

    async def get_user_balance(self, retries: int = 2) -> Tuple[Optional[int], str]:
        """返回 (积分, 错误类型)。错误类型: "ok" / "network" / "token_invalid" / "biz_error" """
        last_err = ""
        for attempt in range(retries + 1):
            try:
                response = await self.client.post(
                    "/openapi/pointsservice/api/Points/getuserbalance",
                    content="{}"
                )
                # HTTP 401/403 才是真 token 失效
                if response.status_code in (401, 403):
                    return None, "token_invalid"
                # 空 body 或非 JSON -> 网络/网关错误，重试
                if not response.text or not response.text.strip():
                    last_err = f"空响应(HTTP {response.status_code})"
                    raise ValueError(last_err)
                response_data = response.json()
                errcode = response_data.get("errcode")
                # 业务码里明确 token 失效
                if errcode in (401, 403, 40001, 40002) or "token" in str(response_data.get("errmsg", "")).lower():
                    return None, "token_invalid"
                if errcode == 200:
                    return response_data.get("data"), "ok"
                # 其他业务错误不删缓存，直接报错
                return None, "biz_error"
            except (json.JSONDecodeError, ValueError) as e:
                last_err = str(e)
                if attempt < retries:
                    wait = 1500 * (attempt + 1)
                    print(f"⚠️ [积分] 积分接口返回非JSON/空响应，{wait//1000}s后第{attempt+1}次重试... ({last_err})")
                    await sleep(wait)
            except Exception as e:
                last_err = str(e)
                if attempt < retries:
                    wait = 1500 * (attempt + 1)
                    print(f"⚠️ [积分] 积分接口网络异常，{wait//1000}s后第{attempt+1}次重试... ({last_err})")
                    await sleep(wait)
        print(f"❌ [积分] 获取积分失败 | 原因: {last_err}（已重试{retries}次）")
        return None, "network"

    async def daily_sign(self) -> Tuple[bool, str]:
        try:
            response = await self.client.post(
                "/openapi/activityservice/api/sign2025/sign",
                content='{"rule_id":1,"goods_rule_id":1}'
            )
            response_data = response.json()

            if response_data.get("errcode") == 201:
                sign_msg = "今日已签到"
                print(f"ℹ️ [签到] {sign_msg}")
                return True, sign_msg

            if self.check_response(response_data):
                data = response_data.get("data", {})
                sign_day = data.get("sign_day", 0)
                sign_points = data.get("sign_points", 0)
                sign_msg = f"签到成功 | 连续{sign_day}天 | +{sign_points}积分"
                print(f"✅ [签到] {sign_msg}")
                return True, sign_msg
            else:
                sign_msg = f"签到失败: {response_data.get('errmsg', '未知错误')}"
                print(f"❌ [签到] {sign_msg}")
                return False, sign_msg

        except Exception as e:
            sign_msg = f"签到异常: {str(e)}"
            print(f"❌ [签到] {sign_msg}")
            return False, sign_msg

    async def get_task_list(self) -> List[Dict[str, Any]]:
        try:
            response = await self.client.post(
                "/openapi/activityservice/api/task/getlist",
                content="{}"
            )
            response_data = response.json()

            if self.check_response(response_data):
                tasks = response_data.get("data", [])
                uncompleted_tasks = [
                    task for task in tasks
                    if task.get("task_status") == 0
                    and task.get("task_guid") not in SKIP_TASK_GUIDS
                ]
                print(f"📋 [任务] 待完成任务: {len(uncompleted_tasks)}个")
                return uncompleted_tasks
            return []
        except Exception as e:
            print(f"❌ [任务] 获取任务列表失败 | 原因: {str(e)}")
            return []

    async def complete_task(self, task_guid: str, task_desc: str) -> Tuple[bool, str]:
        try:
            response = await self.client.post(
                "/openapi/activityservice/api/task/add",
                content=f'{{"task_guid":"{task_guid}"}}'
            )
            response_data = response.json()

            if self.check_response(response_data):
                msg = f"完成【{task_desc}】 | +2积分"
                print(f"✅ [任务] {msg}")
                return True, msg
            else:
                msg = f"【{task_desc}】失败: {response_data.get('errmsg', '未知错误')}"
                print(f"❌ [任务] {msg}")
                return False, msg

        except Exception as e:
            msg = f"【{task_desc}】异常: {str(e)}"
            print(f"❌ [任务] {msg}")
            return False, msg

    async def run(self, index: int = 1, total: int = 1) -> Dict[str, Any]:
        server, ref = parse_yyb_go_entry(self.server)
        display = f"{server}@{ref}" if ref else server

        account_frame(index, total, f"标识 {ref or '-'}", display)

        result = {
            "index": index,
            "server": self.server,
            "display": display,
            "success": False,
            "used_cache": False,
            "proxy_status": "直连" if not self.proxy_info else "专属代理",
            "sign_msg": "",
            "task_msgs": [],
            "initial_score": None,
            "final_score": None,
            "gained_score": 0,
            "error": ""
        }
        print(f"   🌐 [代理] {result['proxy_status']}")

        ck = cache_key(server, ref)
        entry = read_cache_entry(ck, ref)

        try:
            await sleep(random_int(2000, 4000))
            initial = None

            for attempt in range(2):
                # ---------- ① 首次尝试复用缓存 token ----------
                if attempt == 0 and entry.get("access_token"):
                    self.token = entry["access_token"]
                    self.refresh_token = entry.get("refresh_token", "") or ""
                    balance, err = None, ""
                    try:
                        async with self:
                            balance, err = await self.get_user_balance(retries=1)
                    except Exception as exc:
                        balance, err = None, f"network({exc})"

                    if balance is not None:
                        initial = balance
                        result["used_cache"] = True
                        print(f"   💾 [缓存] 复用已保存的登录 token（{mask_token(self.token)}）")
                    elif err == "token_invalid":
                        print("   ♻️ [缓存] token 已失效，清理缓存后重新登录")
                        drop_cache_entry(ck)
                        entry = {}
                        self.token = None
                        self.refresh_token = ""
                    else:
                        print(f"   ❌ [积分] 初始积分校验失败（{err}），保留缓存不删除")
                        result["error"] = f"获取初始积分失败({err})"
                        return result

                # ---------- ② 没有可用 token → 登录 ----------
                if initial is None:
                    if not await self.ensure_token():
                        result["error"] = "登录失败（取码或换 token 未通过，详见上方日志）"
                        print("   ❌ [登录] 失败，跳过该账号")
                        return result

                    save_cache_entry(ck, self.token, self.refresh_token)
                    print("   🔑 [登录] token 获取成功（已写入缓存）")

                    balance, err = None, ""
                    try:
                        async with self:
                            balance, err = await self.get_user_balance(retries=2)
                    except Exception as exc:
                        balance, err = None, f"network({exc})"

                    if balance is None:
                        result["error"] = f"获取初始积分失败({err})"
                        print(f"   ❌ [积分] 初始积分获取失败（{err}）")
                        return result
                    initial = balance

                # ---------- ③ 登录行下面直接显示当前积分 ----------
                result["initial_score"] = initial
                print(f"   💰 [积分] 当前 {initial} 分")

                # ---------- ④ 执行业务 ----------
                async with self:
                    sign_ok, sign_msg = await self.daily_sign()
                    result["sign_msg"] = sign_msg
                    await sleep(1000)

                    tasks = await self.get_task_list()
                    task_msgs = []
                    for task in tasks:
                        task_guid = task.get("task_guid", "")
                        task_desc = task.get("task_sub_desc", task.get("task_title", "未知任务"))
                        if task_guid:
                            ok, msg = await self.complete_task(task_guid, task_desc)
                            task_msgs.append(("✅ " if ok else "❌ ") + msg)
                            await sleep(1000)
                    result["task_msgs"] = task_msgs

                    final, ferr = await self.get_user_balance(retries=1)

                # 执行途中 token 失效（极少见）→ 清缓存重登重跑一次
                if final is None and ferr == "token_invalid" and attempt == 0:
                    print("   🔄 [重试] 执行中 token 失效，清理缓存重新登录重跑")
                    drop_cache_entry(ck)
                    entry = {}
                    self.token = None
                    await sleep(1000)
                    continue

                if final is not None:
                    result["final_score"] = final
                    gained = final - initial
                    result["gained_score"] = gained
                    sign_txt = "+" if gained >= 0 else ""
                    print(f"   💰 [积分] 当前 {final} 分（本次 {sign_txt}{gained}）")
                else:
                    print(f"   ⚠️ [积分] 最终积分获取失败（{ferr}），本次数据仍按成功处理")

                result["success"] = True
                print("   ✅ [完成] 该账号任务执行完成")
                return result

            result["error"] = "重试后仍未完成（详见上方日志）"
            return result

        except Exception as e:
            result["error"] = str(e)
            print(f"   ❌ [异常] 执行异常 | 原因: {str(e)}")
            return result

# ===================== 主程序 =====================
async def main():
    box_top("☕ 雀巢会员俱乐部 每日任务")
    box_line("🕒 启动时间", now_text())
    box_line("🔢 账号数量", f"{len(SERVERS)} 个")
    box_line("🌐 代理模式", "单账号独立代理" if ENABLE_PER_ACCOUNT_PROXY else "全局共用代理")
    box_line("💾 缓存文件", "token_caches/qc_token_cache.json")
    box_bottom()

    global_proxy_info = None
    if not ENABLE_PER_ACCOUNT_PROXY and PROXY_API:
        global_proxy_info = await get_valid_proxy("全局共用")

    results = []
    for index, server in enumerate(SERVERS, 1):
        proxy_info = global_proxy_info
        if ENABLE_PER_ACCOUNT_PROXY:
            proxy_info = await get_valid_proxy(server)
            await sleep(PROXY_FETCH_INTERVAL)

        bot = QueChaoBot(server, proxy_info)
        try:
            res = await bot.run(index, len(SERVERS))
        except Exception as e:
            _, ref = parse_yyb_go_entry(server)
            res = {
                "index": index, "server": server,
                "display": f"{server}@{ref}" if ref else server,
                "success": False, "used_cache": False, "proxy_status": "未知",
                "sign_msg": "", "task_msgs": [],
                "initial_score": None, "final_score": None,
                "gained_score": 0, "error": f"执行异常: {e}"
            }
            print(f"   ❌ [异常] 该账号执行异常: {e}")
        results.append(res)

        if index < len(SERVERS):
            print("\n   ⏳ 等待2秒后执行下一个账号...")
            await sleep(2000)

    # ---------- 明细（汇总框上方） ----------
    for res in results:
        icon = "✅" if res["success"] else "❌"
        print(f"\n{icon} 【账号 {res['index']} · {res['display']}】")
        if res["success"]:
            cache_txt = "（登录态来源：缓存）" if res["used_cache"] else "（登录态来源：新登录）"
            print(f"   📅 [签到] {res['sign_msg']}{cache_txt}")
            task_txt = "\n              ".join(res["task_msgs"]) if res["task_msgs"] else "无未完成任务"
            print(f"   📋 [任务] {task_txt}")
            print(f"   💰 [积分] {res['initial_score']} → {res['final_score']}（{res['gained_score']:+d}）")
        else:
            print(f"   ⚠️ [失败] {res['error']}")

    ok_count = sum(1 for r in results if r["success"])
    total_gained = sum(r["gained_score"] for r in results if r["success"])

    box_top("🏁 雀巢会员俱乐部 执行汇总")
    box_line("✅ 成功账号", f"{ok_count} / {len(results)}")
    box_line("❌ 失败账号", f"{len(results) - ok_count} / {len(results)}")
    box_line("💰 今日总新增", f"{total_gained} 积分")
    box_line("🕒 结束时间", now_text())
    box_bottom()

    # ---------- 通知 ----------
    notify_content = "### 雀巢会员俱乐部每日任务\n"
    for res in results:
        notify_content += f"\n#### 账号 {res['index']} · {res['display']}\n"
        if res["success"]:
            notify_content += f"- 签到：{res['sign_msg']}\n"
            notify_content += f"- 任务：{'; '.join(res['task_msgs']) if res['task_msgs'] else '无未完成任务'}\n"
            notify_content += f"- 积分：{res['initial_score']} → {res['final_score']}（{res['gained_score']:+d}）\n"
        else:
            notify_content += f"- 失败原因：{res['error']}\n"

    if os.getenv("QC_NOTIFY", "1") != "0":
        if send_qinglong_notify("雀巢会员俱乐部", notify_content):
            print("   ✅ [通知] 青龙通知模块调用完成（送达情况以通知渠道为准）")
    await send_plusplus_notification("雀巢会员俱乐部每日任务", notify_content)



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ 用户中断执行")
    except Exception as e:
        print(f"\n❌ 程序异常: {str(e)}")
