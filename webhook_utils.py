# -*- coding: utf-8 -*-
"""
Webhook 与长连接通知工具模块
使用企业微信官方 Python SDK (wecom-aibot-python-sdk) 实现长连接与智能机器人对接
同时使用 requests 库提供连接池与重试，支持钉钉、飞书、Bark、PushPlus、Server酱及通用 HTTP Webhook
用于实时推送礼金记账的新增、修改、删除、纪念日到期与安全提醒
"""

import json
import urllib.parse
import threading
import time
import sqlite3
import asyncio
from datetime import datetime
import requests
import urllib3

# 禁用 self-signed SSL 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from aibot import WSClient, WSClientOptions, generate_req_id
    HAS_AIBOT_SDK = True
except ImportError:
    HAS_AIBOT_SDK = False


def _run_async(coro):
    """在同步线程中安全执行异步协程并返回结果"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _send_payload(url, payload_dict, headers=None, timeout=12):
    """底层 HTTP POST 数据投递，使用 requests 连接池，严格解析响应状态与平台错误码"""
    try:
        session = requests.Session()
        req_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "GiftBookkeepingWebhook/2.0"
        }
        if headers:
            req_headers.update(headers)

        resp = session.post(url, json=payload_dict, headers=req_headers, timeout=timeout, verify=False)
        status_code = resp.status_code
        body = resp.text

        try:
            res_data = resp.json()
            if isinstance(res_data, dict):
                if "errcode" in res_data and res_data["errcode"] != 0:
                    errmsg = res_data.get("errmsg", "未知错误")
                    return False, status_code, f"平台返回错误 [errcode: {res_data['errcode']}]: {errmsg}"
                if "code" in res_data and res_data["code"] not in (0, 200) and "msg" in res_data:
                    return False, status_code, f"平台返回错误 [code: {res_data['code']}]: {res_data['msg']}"
                if "StatusCode" in res_data and res_data["StatusCode"] != 0:
                    return False, status_code, f"平台返回错误: {res_data.get('StatusMessage', '')}"
        except Exception:
            pass

        if 200 <= status_code < 300:
            return True, status_code, body
        else:
            return False, status_code, f"HTTP {status_code}: {body[:200]}"
    except requests.exceptions.Timeout:
        return False, 504, "连接超时：无法在规定时间内连接到 Webhook 目标地址，请检查网络或目标 URL"
    except requests.exceptions.ConnectionError as ce:
        return False, 502, f"无法连接到 Webhook 目标地址（网络不可达或连接失败）：{str(ce)}"
    except Exception as e:
        return False, 0, str(e)


def _sanitize_log_data(data):
    """递归脱敏日志中的敏感字段（密码、Token、Secret等）"""
    if isinstance(data, dict):
        res = {}
        for k, v in data.items():
            kl = str(k).lower()
            if any(s in kl for s in ['secret', 'token', 'pass', 'key', 'credential', 'auth', 'webhook_url']):
                res[k] = '***MASKED***'
            else:
                res[k] = _sanitize_log_data(v)
        return res
    elif isinstance(data, list):
        return [_sanitize_log_data(x) for x in data]
    return data

def _resolve_db_file():
    """动态获取 SQLite 数据库文件路径（适配 Docker /app/data 挂载与原生环境）"""
    base = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base, 'data', 'gift_bookkeeping.db'),
        os.path.join(base, 'gift_bookkeeping.db'),
        'gift_bookkeeping.db'
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0] if os.path.isdir(os.path.join(base, 'data')) else candidates[1]

def record_webhook_log(user_id, webhook_id, event_type, payload, status_code, response_body, is_success):
    """线程安全写入 Webhook 推送日志表"""
    try:
        conn = sqlite3.connect(_resolve_db_file(), timeout=10)
        c = conn.cursor()
        c.execute(
            """INSERT INTO webhook_logs 
               (user_id, webhook_id, event_type, payload, status_code, response_body, is_success, created_at) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id or 1,
                webhook_id,
                event_type or "notify",
                json.dumps(_sanitize_log_data(payload), ensure_ascii=False)[:2000] if isinstance(payload, (dict, list)) else str(_sanitize_log_data(payload))[:2000],
                status_code or 0,
                str(response_body)[:2000],
                1 if is_success else 0,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def validate_wecom_credentials(bot_id, bot_secret):
    """验证企业微信机器人凭证格式有效性与官方 aibot SDK 长连接认证"""
    if not bot_id or not bot_secret:
        return False, "Bot ID 与 Secret 均不能为空"
    b_id = str(bot_id).strip()
    b_sec = str(bot_secret).strip()
    if len(b_id) < 8 or len(b_sec) < 8:
        return False, "Bot ID 或 Secret 长度过短，不符合企业微信机器人凭证规范（至少8位）"
    invalid_patterns = ["test", "error", "123456", "undefined", "null", "bot_id", "secret"]
    if b_id.lower() in invalid_patterns or b_sec.lower() in invalid_patterns:
        return False, "检测到测试/无效占位符，请输入真实有效的企业微信机器人 Bot ID 与 Secret"

    if not HAS_AIBOT_SDK:
        return False, "Python 环境缺少 wecom-aibot-python-sdk 库"

    async def _test_auth():
        options = WSClientOptions(bot_id=b_id, secret=b_sec)
        client = WSClient(options)
        auth_future = asyncio.get_event_loop().create_future()

        @client.on("authenticated")
        def on_auth():
            if not auth_future.done():
                auth_future.set_result(True)

        @client.on("error")
        def on_err(e):
            if not auth_future.done():
                auth_future.set_exception(e)

        await client.connect()
        try:
            await asyncio.wait_for(auth_future, timeout=8.0)
            return True, "企业微信智能机器人凭证通过官方 aibot SDK 握手认证！"
        except asyncio.TimeoutError:
            return False, "连接企业微信官方长连接服务器超时，请检查网络或稍后重试"
        except Exception as e:
            return False, f"企业微信官方 SDK 认证失败: {str(e)}"
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    try:
        return _run_async(_test_auth())
    except Exception as e:
        return False, f"官方 SDK 认证握手异常: {str(e)}"


def extract_chatid_from_url(url):
    """从存储的 webhook_url 中解析可能携带的目标会话 chatid"""
    if not url:
        return ""
    if "chatid=" in url:
        try:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            val = qs.get("chatid", [""])[0].strip()
            if val:
                return val
        except Exception:
            pass
    return ""


# 全局内存缓存，记录已捕获到的最新 chatid (bot_id -> chatid)
_cached_chatids = {}


def test_wecom_long_connection(bot_id, bot_secret, chatid=None):
    """通过官方 wecom-aibot-python-sdk 测试智能机器人凭证与长连接推送"""
    is_v, msg_v = validate_wecom_credentials(bot_id, bot_secret)
    if not is_v:
        return False, 400, f"凭证校验失败: {msg_v}"

    target_chat = chatid or _cached_chatids.get(bot_id)
    if not target_chat:
        try:
            conn = sqlite3.connect("gift_bookkeeping.db", timeout=5)
            c = conn.cursor()
            row = c.execute("SELECT webhook_url FROM webhook_configs WHERE bot_id = ? AND is_enabled = 1", (bot_id,)).fetchone()
            if row and row[0]:
                cid = extract_chatid_from_url(row[0])
                if cid:
                    target_chat = cid
                    _cached_chatids[bot_id] = cid
            conn.close()
        except Exception:
            pass

    if target_chat:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return send_wecom_long_connection_message(
            bot_id, bot_secret,
            title="【人情礼金记账】智能机器人长连接测试",
            details="这是一条通过企业微信官方 SDK (wecom-aibot-python-sdk) 发送的长连接测试消息。",
            now_str=now_str,
            chatid=target_chat
        )

    return True, 200, "企业微信智能机器人官方 SDK 认证成功！Bot ID 与 Secret 凭证有效，已成功建立 WebSocket 长连接。提示：如需接收通知消息，建议在【Webhook 配置】填写目标群聊 chatid，或直接在企微群内 @机器人 一次即可自动绑定会话！"


def send_wecom_long_connection_message(bot_id, bot_secret, title, details=None, now_str=None, event_type="notify", chatid=None):
    """使用企业微信官方 Python SDK (wecom-aibot-python-sdk) 向指定群聊/会话主动发送 Markdown 消息"""
    is_valid, val_msg = validate_wecom_credentials(bot_id, bot_secret)
    if not is_valid:
        return False, 400, f"凭证校验失败: {val_msg}"

    if not HAS_AIBOT_SDK:
        return False, 500, "Python 环境缺少 wecom-aibot-python-sdk 库"

    if not now_str:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    target_chat = chatid or _cached_chatids.get(bot_id)
    if not target_chat:
        try:
            conn = sqlite3.connect("gift_bookkeeping.db", timeout=5)
            c = conn.cursor()
            row = c.execute("SELECT webhook_url FROM webhook_configs WHERE bot_id = ? AND is_enabled = 1", (bot_id,)).fetchone()
            if row and row[0]:
                cid = extract_chatid_from_url(row[0])
                if cid:
                    target_chat = cid
                    _cached_chatids[bot_id] = cid
            conn.close()
        except Exception:
            pass

    if not target_chat:
        return False, 400, "企业微信智能机器人已完成长连接认证，但尚未配置目标群聊/会话 ID (chatid)。请在【Webhook 配置】中填入群聊 chatid，或在企微群内 @机器人 一次即可自动绑定会话！"

    if details and ("\\n" in details or chr(10) in details):
        content = f"### {title}\n> **接入方式**：<font color=\"info\">企业微信智能机器人 (aibot SDK)</font>\n> **时间**：<font color=\"comment\">{now_str}</font>\n\n{details}"
    else:
        content = f"### {title}\n> **接入方式**：<font color=\"info\">企业微信智能机器人 (aibot SDK)</font>\n> **时间**：<font color=\"comment\">{now_str}</font>\n> **详情**：<font color=\"info\">{details or '无额外说明'}</font>"

    async def _async_send():
        options = WSClientOptions(bot_id=bot_id.strip(), secret=bot_secret.strip())
        client = WSClient(options)
        auth_future = asyncio.get_event_loop().create_future()

        @client.on("authenticated")
        def on_auth():
            if not auth_future.done():
                auth_future.set_result(True)

        @client.on("error")
        def on_err(e):
            if not auth_future.done():
                auth_future.set_exception(e)

        await client.connect()
        try:
            await asyncio.wait_for(auth_future, timeout=8.0)
            res = await client.send_message(
                chatid=target_chat,
                body={
                    "msgtype": "markdown",
                    "markdown": {"content": content}
                }
            )
            return True, 200, f"企业微信官方 SDK 成功投递消息至会话 [{target_chat}]！"
        except Exception as e:
            err_str = str(e)
            if "93006" in err_str or "invalid chatid" in err_str:
                return False, 400, f"企微 SDK 推送失败: 目标会话 ID [{target_chat}] 无效或机器人不在该群内。请重新核对群聊 ID 或在群内 @机器人 一次。"
            return False, 400, f"企业微信官方 SDK 消息投递失败: {err_str}"
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    try:
        return _run_async(_async_send())
    except Exception as e:
        return False, 500, f"企业微信 SDK 发送调用异常: {str(e)}"


def test_single_webhook(wh, sender_name="admin"):
    """同步测试单条 Webhook，返回 (success, status_code, message) 并记录日志"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn_type = getattr(wh, "connection_type", "webhook_url") or "webhook_url"
    bot_id = (getattr(wh, "bot_id", "") or "").strip()
    bot_secret = (getattr(wh, "bot_secret", "") or "").strip()
    url = (getattr(wh, "webhook_url", "") or "").strip()
    title = "【Webhook 测试推送】连接验证"
    details = f"测试触发人: {sender_name} | 测试时间: {now_str}"

    if conn_type == "long_connection":
        if not bot_id or not bot_secret:
            return False, 400, "长连接模式下 Bot ID 与 Secret 不能为空"
        chatid = extract_chatid_from_url(url)
        success, code, msg = test_wecom_long_connection(bot_id, bot_secret, chatid=chatid)
        payload = {"mode": "long_connection", "bot_id": bot_id, "title": title, "chatid": chatid}
        record_webhook_log(wh.user_id, wh.id, "test", payload, code, msg, success)
        return success, code, msg

    if not url:
        return False, 400, "Webhook 目标 URL 不能为空"

    # 特殊协议与本地回调兼容
    if url.startswith("wecom://"):
        b_id = bot_id or (url.split("wecom://bot/")[1].split("?")[0] if "wecom://bot/" in url else "")
        c_id = extract_chatid_from_url(url) or _cached_chatids.get(b_id)
        if b_id and bot_secret:
            success, code, msg = test_wecom_long_connection(b_id, bot_secret, chatid=c_id)
            record_webhook_log(wh.user_id, wh.id, "test", {"mode": "wecom_url", "bot_id": b_id, "chatid": c_id}, code, msg, success)
            return success, code, msg

    if any(h in url for h in ["indevs.in", "localhost", "127.0.0.1:11443", ":15001"]) and not ("/send?" in url or "key=" in url):
        msg = "提示：当前填写的 URL 属于本系统的回调接收地址（用于在企微群内 @机器人 时接收事件并捕获 chatid）。若需向企微群推送通知，请填入标准企微群机器人 Webhook 地址（形如 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...），或选用长连接模式！"
        record_webhook_log(wh.user_id, wh.id, "test", {"url": url}, 400, msg, False)
        return False, 400, msg

    # 标准 HTTP Webhook
    payload = {
        "event": "test",
        "title": title,
        "time": now_str,
        "details": details,
        "source": "gift_bookkeeping_app"
    }
    headers = {}
    if wh.secret_token:
        headers["Authorization"] = f"Bearer {wh.secret_token}"

    if "dingtalk.com" in url:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"### {title}\n\n- **时间**: {now_str}\n- **说明**: {details}\n\n> 礼金记账系统通知"
            }
        }
    elif "feishu.cn" in url or "larksuite.com" in url:
        payload = {
            "msg_type": "text",
            "content": {"text": f"{title}\n时间: {now_str}\n详情: {details}"}
        }
    elif "qyapi.weixin.qq.com" in url:
        if details and ("\\n" in details or chr(10) in details):
            md_cnt = f"### {title}\n> 时间：<font color=\"comment\">{now_str}</font>\n\n{details}"
        else:
            md_cnt = f"### {title}\n> 时间：<font color=\"comment\">{now_str}</font>\n> 详情：<font color=\"info\">{details or '无'}</font>"
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": md_cnt}
        }
    elif "pushplus.plus" in url:
        token = wh.secret_token
        if not token and "token=" in url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            token = qs.get("token", [""])[0]
        payload = {
            "token": token,
            "title": title,
            "content": f"<h3>{title}</h3><p>时间：{now_str}</p><p>详情：{details}</p>",
            "template": "html"
        }
    elif "ftqq.com" in url:
        payload = {
            "title": title,
            "desp": f"### {title}\n\n- **时间**: {now_str}\n- **说明**: {details}"
        }
    elif "api.day.app" in url:
        payload = {
            "title": title,
            "body": f"{details}\n时间: {now_str}",
            "group": "礼金记账"
        }

    success, code, body = _send_payload(url, payload, headers, timeout=12)
    record_webhook_log(wh.user_id, wh.id, "test", payload, code, body, success)
    return success, code, body


def trigger_webhook_event(webhooks, event_type, record_title, details=None, force_channels=False):
    """异步多线程触发 Webhook 与长连接机器人通知"""
    if not webhooks:
        return

    hook_data_list = []
    for w in webhooks:
        if not getattr(w, "is_enabled", True):
            continue
        if not force_channels:
            if event_type in ("create", "record_create") and not getattr(w, "notify_on_add", False):
                continue
            if event_type in ("delete", "record_delete", "batch_delete") and not getattr(w, "notify_on_delete", False):
                continue
            if event_type == "reminder" and getattr(w, "notify_on_reminder", True) in (False, 0, "0", "false"):
                continue
            if event_type == "broadcast" and not getattr(w, "notify_on_broadcast", False):
                continue

        hook_data_list.append({
            "id": w.id,
            "user_id": w.user_id,
            "url": getattr(w, "webhook_url", "") or "",
            "secret": getattr(w, "secret_token", None),
            "connection_type": getattr(w, "connection_type", "webhook_url") or "webhook_url",
            "bot_platform": getattr(w, "bot_platform", "wecom") or "wecom",
            "bot_id": getattr(w, "bot_id", None),
            "bot_secret": getattr(w, "bot_secret", None)
        })

    if not hook_data_list:
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    type_names = {
        "create": "【记账新增提醒】",
        "record_create": "【记账新增提醒】",
        "update": "【记账变更提醒】",
        "record_update": "【记账变更提醒】",
        "delete": "【记账删除提醒】",
        "record_delete": "【记账删除提醒】",
        "batch_delete": "【批量删除提醒】",
        "security": "【安全风控警告】",
        "reminder": "【亲友重要纪念日提醒】",
        "auto_reminder": "【亲友重要纪念日提醒】",
        "broadcast": "【系统站内广播】",
        "test": "【Webhook 测试推送】"
    }
    prefix = type_names.get(event_type, "【礼金记账通知】")
    if record_title.startswith("【"):
        title = record_title
    else:
        title = f"{prefix} {record_title}"

    def _worker():
        for item in hook_data_list:
            try:
                conn_type = item.get("connection_type", "webhook_url")
                if conn_type == "long_connection":
                    b_id = item.get("bot_id", "")
                    b_sec = item.get("bot_secret", "")
                    c_id = extract_chatid_from_url(item.get("url", "")) or _cached_chatids.get(b_id)
                    if b_id and b_sec:
                        s, c, b = send_wecom_long_connection_message(b_id, b_sec, title, details, now_str, event_type, chatid=c_id)
                        record_webhook_log(item.get("user_id"), item.get("id"), event_type, {"title": title, "bot_id": b_id, "chatid": c_id, "details": details}, c, b, s)
                    continue

                url = item.get("url", "")
                if not url:
                    continue

                if "dingtalk.com" in url:
                    payload = {
                        "msgtype": "markdown",
                        "markdown": {
                            "title": title,
                            "text": f"### {title}\n\n- **时间**: {now_str}\n- **说明**: {details or '无'}\n\n> 礼金记账系统通知"
                        }
                    }
                elif "feishu.cn" in url or "larksuite.com" in url:
                    payload = {
                        "msg_type": "text",
                        "content": {
                            "text": f"{title}\n时间: {now_str}\n\n{details or '无'}"
                        }
                    }
                elif "qyapi.weixin.qq.com" in url:
                    if details and ("\\n" in details or chr(10) in details):
                        md_cnt = f"### {title}\n> 时间：<font color=\"comment\">{now_str}</font>\n\n{details}"
                    else:
                        md_cnt = f"### {title}\n> 时间：<font color=\"comment\">{now_str}</font>\n> 详情：<font color=\"info\">{details or '无'}</font>"
                    payload = {
                        "msgtype": "markdown",
                        "markdown": {"content": md_cnt}
                    }
                elif "pushplus.plus" in url:
                    token = item.get("secret")
                    if not token and "token=" in url:
                        parsed = urllib.parse.urlparse(url)
                        qs = urllib.parse.parse_qs(parsed.query)
                        token = qs.get("token", [""])[0]
                    html_details = details.replace(chr(10), "<br>").replace("\\n", "<br>") if details else "无"
                    payload = {
                        "token": token,
                        "title": title,
                        "content": f"<h3>{title}</h3><p>时间：{now_str}</p><div>{html_details}</div>",
                        "template": "html"
                    }
                elif "ftqq.com" in url:
                    payload = {
                        "title": title,
                        "desp": f"### {title}\n\n- **时间**: {now_str}\n- **说明**: {details or '无'}"
                    }
                elif "api.day.app" in url:
                    payload = {
                        "title": title,
                        "body": f"{details or '无'}\n时间: {now_str}",
                        "group": "礼金记账"
                    }
                else:
                    payload = {
                        "event": event_type,
                        "title": title,
                        "time": now_str,
                        "details": details,
                        "source": "gift_bookkeeping_app"
                    }

                headers = {}
                if item.get("secret"):
                    headers["Authorization"] = f"Bearer {item.get('secret')}"

                s, c, b = _send_payload(url, payload, headers, timeout=12)
                record_webhook_log(item.get("user_id"), item.get("id"), event_type, payload, c, b, s)
            except Exception:
                pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


_listener_thread = None
_listener_running = False

def _wecom_listener_worker():
    global _listener_running
    while _listener_running:
        try:
            conn = sqlite3.connect(_resolve_db_file(), timeout=10)
            c = conn.cursor()
            rows = c.execute("SELECT id, bot_id, bot_secret, webhook_url, connection_type FROM webhook_configs WHERE bot_id IS NOT NULL AND bot_id != '' AND is_enabled = 1").fetchall()
            conn.close()

            if not rows:
                time.sleep(10)
                continue

            for wh_id, bot_id, bot_secret, current_url, conn_type in rows:
                if not bot_id or not bot_secret or not HAS_AIBOT_SDK:
                    continue

                async def _run_bot_client(b_id, b_sec, w_id, c_type):
                    options = WSClientOptions(
                        bot_id=b_id.strip(),
                        secret=b_sec.strip(),
                        max_reconnect_attempts=3,
                        reconnect_interval=2000,
                        heartbeat_interval=30000
                    )
                    client = WSClient(options)

                    def _on_msg(frame):
                        try:
                            body = frame.get("body", {}) if isinstance(frame, dict) else {}
                            headers = frame.get("headers", {}) if isinstance(frame, dict) else {}
                            cid = body.get("chatid") or (body.get("from", {}) if isinstance(body.get("from"), dict) else {}).get("userid") or headers.get("chatid")
                            if cid:
                                _cached_chatids[b_id] = cid
                                conn_u = sqlite3.connect("gift_bookkeeping.db", timeout=10)
                                c_u = conn_u.cursor()
                                target_rows = c_u.execute("SELECT id, webhook_url, connection_type FROM webhook_configs WHERE (bot_id = ? OR id = ? OR bot_platform = 'wecom' OR webhook_url LIKE '%qyapi.weixin.qq.com%') AND is_enabled = 1", (b_id, w_id)).fetchall()
                                for tr_id, tr_url, tr_conn in target_rows:
                                    if tr_conn == "long_connection" or not tr_url or tr_url.startswith("wecom://"):
                                        new_url = f"wecom://bot/{b_id}?chatid={cid}"
                                    else:
                                        sep = "&" if "?" in tr_url else "?"
                                        new_url = tr_url if "chatid=" in tr_url else f"{tr_url}{sep}chatid={cid}"
                                    c_u.execute("UPDATE webhook_configs SET webhook_url = ? WHERE id = ?", (new_url, tr_id))
                                conn_u.commit()
                                conn_u.close()
                                record_webhook_log(1, w_id, "receive_chatid", {"bot_id": b_id, "chatid": cid}, 200, f"企微群内 @机器人 成功自动捕获群聊会话 chatid [{cid}] 并绑定到通道！", True)
                                print(f"[aibot SDK] 自动捕获群聊会话 chatid [{cid}] 并已持久化")
                        except Exception as e:
                            print(f"[aibot SDK error]: {e}")

                    client.on("message", _on_msg)
                    client.on("event", _on_msg)

                    await client.connect()
                    count = 0
                    while _listener_running and count < 60:
                        await asyncio.sleep(5)
                        count += 1
                    try:
                        await client.disconnect()
                    except Exception:
                        pass

                try:
                    _run_async(_run_bot_client(bot_id, bot_secret, wh_id, conn_type))
                except Exception:
                    pass

            time.sleep(5)
        except Exception:
            time.sleep(10)


def start_wecom_long_connection_listener():
    """启动全局企微智能机器人长连接后台监听守护线程"""
    global _listener_thread, _listener_running
    if _listener_thread and _listener_thread.is_alive():
        return
    _listener_running = True
    _listener_thread = threading.Thread(target=_wecom_listener_worker, daemon=True)
    _listener_thread.start()
