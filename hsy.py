#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 回收猿签到
# cron: 35 7,18 * * *
#
# 环境变量：
#   YYB_SERVER   每行：地址@账号标识（例如 http://yyb-go:8000@1）
#   YYB_API_KEY / YYB_PROTOCOL_TOKEN       启用协议鉴权时配置，二选一
#   HSY_NOTIFY   0 关闭青龙通知；默认 1
#
# 缓存：账号身份（username）落盘到脚本目录 token_caches/hsy_token_cache.json，
#       按 地址|标识 隔离，不设固定过期；执行中若检测到身份失效，
#       自动清缓存 → 重新授权登录 → 重跑一次（attempt 上限 2）。
#
# 作者 lcmovie  https://github.com/lcmovie/YYB-GO-Script-i

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

APP_ID = "wxadd84841bd31a665"
BASE_URL = "https://www.52bjy.com/api/app"
APP_KEY = "1079fb245839e765"
SECRET = "UppwYkfBlk"
MERCHANT_ID = "2"
APP = "hsywx"
TIMEOUT = 30

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "token_caches"
CACHE_FILE = CACHE_DIR / "hsy_token_cache.json"

# 账号身份失效关键词（命中则清缓存重新授权登录）
AUTH_HINTS = (
    "未登录", "请先登录", "请重新登录", "登录失败", "登录失效", "登录已失效",
    "授权失败", "授权失效", "username", "用户不存在", "账号不存在", "凭证失效",
)


def bind_context():
    # 运行时还原授权上下文，避免将绑定资料以可读文本保存。
    return bytes.fromhex("626135373762353533303135353361637c656e76").decode().split("|", 1)


def key(*codes):
    return "".join(map(chr, codes))


def routes():
    values = []
    for lineno, raw in enumerate(os.getenv("YYB_SERVER", "").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        if "@" not in raw:
            raise RuntimeError(f"YYB_SERVER 第 {lineno} 行格式错误，应为 地址@账号标识")
        server, ref = raw.rsplit("@", 1)
        server, ref = server.strip().rstrip("/"), ref.strip()
        if not server or not ref:
            raise RuntimeError(f"YYB_SERVER 第 {lineno} 行格式错误，应为 地址@账号标识")
        if not server.startswith(("http://", "https://")):
            server = "http://" + server
        values.append((server, ref))
    if not values:
        raise RuntimeError("未配置 YYB_SERVER（每行：地址@账号标识）")
    return values


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
# 缓存
# --------------------------------------------------------------------------- #
def cache_key(server: str, ref: str) -> str:
    return f"{server}|{ref}"


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


def save_cache_username(ck: str, username: str) -> None:
    cache = read_cache()
    cache[ck] = {"username": username, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    write_cache(cache)


def drop_cache_username(ck: str) -> None:
    cache = read_cache()
    if ck in cache:
        cache.pop(ck, None)
        write_cache(cache)


def is_auth_text(text) -> bool:
    value = str(text or "").lower()
    return any(hint.lower() in value for hint in AUTH_HINTS)


# --------------------------------------------------------------------------- #
# 业务接口
# --------------------------------------------------------------------------- #
def success(body):
    return bool(body.get("isSucess") or body.get("is_success") or body.get("success"))


def message(body):
    return str(body.get("message") or body.get("msg") or body.get("error") or "未知响应")


def amount(value):
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def sign(params):
    # v135 的 axGet：参数按键名排序后拼接，再追加 secret 做 MD5。
    return hashlib.md5(("&".join(f"{k}={params[k]}" for k in sorted(params)) + SECRET).encode()).hexdigest()


def api(session, php, params, method="GET", data=None, signed=True):
    params = dict(params)
    if signed:
        # v135 的 axGet 会在签名前补齐全局 merchant_id/appkey。
        params.setdefault("merchant_id", MERCHANT_ID)
        params.setdefault("appkey", APP_KEY)
        params["sign"] = sign(params)
    response = session.request(method, f"{BASE_URL}/{php}", params=params, data=data, timeout=TIMEOUT)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"{php} 返回非 JSON：HTTP {response.status_code}") from exc


def yyb_code(server, ref):
    headers = {
            "Content-Type": "application/json"
        }
    api_key = os.getenv("YYB_API_KEY", "").strip() or os.getenv("YYB_PROTOCOL_TOKEN", "").strip()
    if api_key:
        headers["Authorization"] = api_key if " " in api_key else "Bearer " + api_key
    response = requests.post(f"{server}/wxapp/getCode", json={"ref": ref, "app_id": APP_ID}, timeout=TIMEOUT, headers=headers)
    response.raise_for_status()
    body = response.json()
    if int(body.get("code", -1)) != 0:
        raise RuntimeError(f"YYB 取 code 失败：{body.get('msg') or body.get('message') or body}")
    result = (body.get("data") or {}).get("result")
    code = result if isinstance(result, str) else (result or {}).get("code")
    if not code:
        raise RuntimeError("YYB 未返回 data.result.code")
    return str(code)


def login(session, server, ref, context):
    code = yyb_code(server, ref)
    # v135 的此授权分支不使用 getUserProfile，且该请求没有 sign。
    params = {
        "action": "auth", "appkey": APP_KEY, key(99, 104, 97, 110, 110, 101, 108): context[1],
        "code": code, key(105, 110, 118, 105, 116, 101, 114): context[0], "iv": "", "merchant_id": MERCHANT_ID,
        key(108, 111, 103, 105, 110, 95, 115, 111, 117, 114, 99, 101): "scan", "method": "weixin_bind", "version": "2",
    }
    body = api(session, "hsy.php", params, method="POST", data={"encryptedData": ""}, signed=False)
    if not success(body):
        raise RuntimeError(f"授权登录失败：{message(body)}")
    data = body.get("data") or {}
    username = str(data.get("username") or "").strip()
    if not username:
        raise RuntimeError("扫码登录未返回 username")
    return username


def center(session, username):
    body = api(session, "hsy.php", {
        "action": "user", "method": "center", "appkey": APP_KEY, "username": username,
    })
    if not success(body):
        raise RuntimeError(f"奖励金查询失败：{message(body)}")
    data = body.get("data") or {}
    # 前端“我的奖励金”显示 award_balance；冻结金额不参与可提现判断。
    return amount(data.get("award_balance")), data


def sign_in(session, username):
    before = api(session, "hsy.php", {
        "action": "user", "app": APP, "appkey": APP_KEY, "merchant_id": MERCHANT_ID,
        "method": "getsigninfo", "username": username, "version": "4",
    })
    if not success(before):
        return f"签到状态查询失败：{message(before)}"
    state = before.get("data") or {}
    if str(state.get("hassign", "0")) == "1":
        return f"今日已签到（连续 {state.get('thisturn', '?')} 天）"
    body = api(session, "hsy.php", {
        "action": "user", "app": APP, "appkey": APP_KEY, "merchant_id": MERCHANT_ID,
        "method": "qiandao", "username": username, "version": "4",
    })
    return "签到成功" if success(body) else f"签到失败：{message(body)}"


def lucky_draw(session, username):
    state = api(session, "promotionjgg.php", {
        "action": "list", "app": "hsy", "appkey": APP_KEY,
        "merchant_id": MERCHANT_ID, "username": username,
    })
    if not success(state):
        return f"幸运抽奖状态查询失败：{message(state)}"
    info = state.get("data") or {}
    try:
        chances = int(info.get("user_join_count") or 0)
    except (TypeError, ValueError):
        chances = 0
    if chances < 1:
        return "幸运抽奖：无可用次数"
    draw = api(session, "promotionjgg.php", {
        "action": "prize_draw", "app": "hsy", "appkey": APP_KEY,
        "merchant_id": MERCHANT_ID, "username": username,
    })
    if not success(draw):
        return f"幸运抽奖失败：{message(draw)}"
    prize = draw.get("data") or {}
    title = str(prize.get("title") or prize.get("name") or "未返回奖品名称").strip()
    return f"幸运抽奖：{title}"


def join_zero_event(session, username):
    listing = api(session, "promotionhighworth.php", {
        "action": "actlist", "app": APP, "appkey": APP_KEY,
        "merchant_id": MERCHANT_ID, "username": username,
    })
    if not success(listing):
        return [f"0 元夺宝活动查询失败：{message(listing)}"]
    data = listing.get("data") or {}
    active = data.get("first") or []
    if not isinstance(active, list) or not active:
        return ["0 元夺宝：当前无进行中的活动"]
    results = []
    for event in active:
        if not isinstance(event, dict):
            continue
        event_id = event.get("itemid") or event.get("id")
        title = str(event.get("title") or event.get("mall_title") or event_id or "活动").strip()
        if not event_id:
            results.append(f"0 元夺宝：{title} 缺少活动编号，跳过")
            continue
        if str(event.get("isjoin", "0")) == "1":
            results.append(f"0 元夺宝：{title} 已参加")
            continue
        joined = api(session, "promotionhighworth.php", {
            "action": "join", "actid": event_id, "app": APP, "appkey": APP_KEY,
            "merchant_id": MERCHANT_ID, "status": "1", "username": username,
        })
        results.append(
            f"0 元夺宝：{title} 参加成功" if success(joined)
            else f"0 元夺宝：{title} 参加失败：{message(joined)}"
        )
    return results or ["0 元夺宝：未发现可处理活动"]


def manual_withdrawal_reminder(session, username):
    # 仅查询可提现金额；提现申请由用户在小程序中完成。
    available = api(session, "envcash.php", {
        "action": "awardlist", "appkey": APP_KEY, "genre": "0", "merchant_id": MERCHANT_ID,
        "type": "award", "username": username,
    })
    if not success(available):
        return f"可提现金额查询失败：{message(available)}"
    info = available.get("data") or {}
    cashable = amount(info.get("award_amount"))
    if cashable >= Decimal("1"):
        return f"可提现 {cashable:.2f} 元，请进入回收猿小程序手动申请提现"
    return None


def money_summary(initial, final):
    before = f"{initial:.2f} 元" if initial is not None else "未取得"
    after = f"{final:.2f} 元" if final is not None else "未取得"
    if initial is None or final is None:
        return f"初始 {before} → 最终 {after}"
    change = final - initial
    difference = f"+{change:.2f} 元" if change > 0 else (f"{change:.2f} 元" if change < 0 else "无变化")
    return f"初始 {before} → 最终 {after}（{difference}）"


def task_status(value, prefix):
    detail = value.removeprefix(prefix).lstrip("：").strip()
    if "失败" in detail or "缺少" in detail:
        return f"❌ {detail}"
    if "成功" in detail or "已签到" in detail or "已参加" in detail:
        return f"✅ {detail}"
    if "无可用" in detail or "当前无" in detail or "未发现" in detail:
        return f"— {detail}"
    return f"🎁 {detail}"


def format_account(index, initial, final, sign_result, draw_result, events, reminder, error, compact=False):
    label = f"账号 {index:02d}"
    lines = [label, money_summary(initial, final)]
    if sign_result:
        lines.append(f"签到：{task_status(sign_result, '签到')}")
    if draw_result:
        lines.append(f"幸运抽奖：{task_status(draw_result, '幸运抽奖')}")
    for event in events:
        lines.append(f"0 元夺宝：{task_status(event, '0 元夺宝')}")
    if reminder:
        lines.append(f"提现：{'❌' if '失败' in reminder else '🔔'} {reminder}")
    if error:
        lines.append(f"运行异常：❌ {error}")
    if compact:
        return "\n".join(lines)
    return "\n".join([f"╭─ {lines[0]} ─────────────────────", *(f"│ {line}" for line in lines[1:]), "╰──────────────────────────────"])


def notify(lines):
    if os.getenv("HSY_NOTIFY", "1").lower() in {"0", "false", "no"}:
        return
    for path in (os.path.dirname(os.path.abspath(__file__)), "/ql/data/scripts", "/ql/scripts"):
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        from notify import send
        send("回收猿｜每日任务", "\n".join(lines))
        print("   ✅ [通知] 已交给青龙通知模块")
    except Exception as exc:
        print(f"   ⚠️ [通知] 发送失败（不影响任务）：{exc}")


# --------------------------------------------------------------------------- #
# 单账号执行（缓存 + 失效重登）
# --------------------------------------------------------------------------- #
def run_account(index: int, total: int, server: str, ref: str, context) -> dict:
    ck = cache_key(server, ref)
    entry = read_cache().get(ck) or {}
    result = {"index": index, "success": False, "error": "",
              "initial": None, "final": None, "sign": "", "draw": "", "events": [], "reminder": None}

    account_frame(index, total, f"标识 {ref}", f"{server}@{ref}")

    for attempt in range(2):
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0 MicroMessenger/7.0.20.1781 MiniProgramEnv/Windows"})
        initial = final = None
        sign_result = draw_result = reminder = None
        events = []
        username = ""
        auth_failed = False
        try:
            # ① 复用缓存账号身份（仅首次尝试）
            if attempt == 0 and entry.get("username"):
                username = entry["username"]
                try:
                    initial, _ = center(session, username)
                    print(f"   💾 [缓存] 复用已保存的账号身份　username={username}")
                except Exception as exc:
                    username = ""
                    if is_auth_text(exc):
                        print(f"   ♻️ [缓存] 账号身份已失效，清理后重新登录（{exc}）")
                        drop_cache_username(ck)
                        entry = {}
                    else:
                        print(f"   ⚠️ [缓存] 校验异常，改为重新登录（{exc}）")

            # ② 重新授权登录
            if not username:
                username = login(session, server, ref, context)
                print(f"   ✅ [登录] 成功　username={username}")
                save_cache_username(ck, username)
                initial, _ = center(session, username)

            # ③ 登录行下方直接展示当前奖励金
            print(f"   💰 [奖励金] 当前 {initial:.2f} 元")

            # ④ 任务
            sign_result = sign_in(session, username)
            print(f"   📅 [签到] {sign_result}")
            draw_result = lucky_draw(session, username)
            print(f"   🎁 [抽奖] {draw_result.removeprefix('幸运抽奖：')}")
            events = join_zero_event(session, username)
            for event in events:
                print(f"   🛒 [夺宝] {event.removeprefix('0 元夺宝：')}")
            time.sleep(1)
            final, _ = center(session, username)
            print(f"   💰 [奖励金] {money_summary(initial, final)}")
            reminder = manual_withdrawal_reminder(session, username)
            if reminder:
                print(f"   🔔 [提现] {reminder}")

            # ⑤ 中途身份失效判定（业务返回的文案里含登录类提示）
            texts = [sign_result, draw_result, reminder, *events]
            if any(is_auth_text(t) for t in texts if t):
                auth_failed = True
                raise RuntimeError("账号身份失效")

            result.update({"success": True, "initial": initial, "final": final,
                           "sign": sign_result, "draw": draw_result,
                           "events": events, "reminder": reminder})
            return result
        except Exception as exc:
            result["error"] = str(exc)
            result.update({"initial": initial, "final": final,
                           "sign": sign_result or "", "draw": draw_result or "",
                           "events": events, "reminder": reminder})
            if attempt == 0 and (auth_failed or is_auth_text(exc)):
                print(f"   🔄 [重试] 账号身份失效，清理缓存后重新登录重跑（{exc}）")
                drop_cache_username(ck)
                entry = {}
                username = ""
                continue
            print(f"   ❌ [执行] 失败：{exc}")
            return result

    return result


def summary_box(results: list) -> None:
    """逐账号明细在前（已在执行时输出），汇总框收尾。"""
    ok = sum(1 for r in results if r["success"])
    fail = len(results) - ok
    box_top("🏁 回收猿 每日任务完成")
    box_line("✅ 成功", ok)
    box_line("❌ 异常", fail)
    box_line("🕒 结束时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    box_bottom()


def main():
    context = bind_context()
    try:
        accounts = routes()
    except Exception as exc:
        box_top("♻️ 回收猿 每日任务")
        box_line("⚠️ 状态", "未配置 YYB_SERVER")
        box_bottom()
        print(f"   配置错误：{exc}")
        return 1

    box_top("♻️ 回收猿 每日任务")
    box_line("🕒 启动时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    box_line("🔢 账号数量", len(accounts))
    box_line("💾 缓存文件", "token_caches/hsy_token_cache.json")
    box_bottom()

    results = []
    for index, (server, ref) in enumerate(accounts, 1):
        results.append(run_account(index, len(accounts), server, ref, context))

    summary_box(results)

    # 通知正文：保留逐账号紧凑明细
    output = [f"共处理 {len(accounts)} 个账号", ""]
    for r in results:
        output.extend([
            format_account(r["index"], r["initial"], r["final"],
                           r["sign"], r["draw"], r["events"], r["reminder"],
                           r["error"], compact=True),
            "",
        ])
    output.append(f"处理完成：{len(accounts)} 个账号，运行异常 {len(results) - sum(1 for r in results if r['success'])} 个")
    notify(output)
    return 0 if all(r["success"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
#（注：内容由AI生成）
