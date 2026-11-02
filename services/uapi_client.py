# -*- coding: utf-8 -*-
"""
uapi_client.py — UApiPro（uapis.cn）统一调用引擎（V10.11.47 新增）

全站调用 uapis.cn 平台 110 个 API 的唯一出入口，能力：
  1. 认证注入：自动读取「API 平台」注册表的 base_url 与平台级 API Key
     （Authorization: Bearer <key>；Key 为空 = 访客模式直连，按 IP 月 1500 积分 / 4 QPS）
  2. 双路径网络：禁代理直连优先 + 系统代理兜底（与 weather_service._http_get 同款策略，
     覆盖「直连可达」与「仅代理可达」两种网络环境）
  3. 限流退避：429 尊重 Retry-After 头，否则按 0.5s/1s/2s 指数退避；
     5xx/超时/网络异常退避重试；400/401/402/403/404 属客户端错误不重试
  4. 错误标准化：兼容 {code, message} 与 {error, ...} 双格式错误体（官方 FAQ Q32）
  5. 试验台原始调用：识别非 JSON 响应（图片/音频/文件流）并 base64 回传展示

对外主入口（业务便捷函数）：
  get_daily_saying()          一言（登录页/首页装饰，免费接口，进程级缓存 1 小时）
  query_express(no, phone)    快递物流查询（40 积分/次，缓存 10 分钟控积分消耗）
  lookup_phone(phone)         手机归属地（2 积分/次，缓存 24 小时）
  search_hotboard(type)       热榜（1 积分/次，缓存 5 分钟）
  get_daily_word(category)    每日单词（1 积分/次，缓存 6 小时）
  call_uapi(...)              通用调用（weather/holiday 适配器与试验台使用）
"""
import base64
import json
import threading
import time

from services import uapi_catalog
from services import service_config

# ===================== 常量 =====================

DEFAULT_TIMEOUT = (5, 10)          # 连接 5s + 读取 10s（官方建议部分接口 ≥10s）
MAX_BACKOFF_ROUNDS = 3             # 限流/服务端错误最多退避重试 3 轮
BACKOFF_SCHEDULE = (0.5, 1.0, 2.0) # 指数退避间隔（秒）
# 不重试的客户端错误（重试也不会成功，按官方错误处理指南）
NO_RETRY_STATUS = (400, 401, 402, 403, 404, 405, 413)

# 访客月额度耗尽错误码（官方 FAQ Q14：访客额度用尽返回 429 + 该错误码）
VISITOR_QUOTA_CODE = 'VISITOR_MONTHLY_QUOTA_EXHAUSTED'


class UapiError(Exception):
    """UApiPro 调用异常：message 中文提示 + status HTTP 状态码"""

    def __init__(self, message, status=502, code=''):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


# ===================== 进程级轻量缓存（减少积分消耗） =====================

_cache_lock = threading.Lock()
_cache = {}  # {key: (过期时间戳, 数据)}

_CACHE_TTLS = {
    'saying': 3600,          # 一言：1 小时（全站共享一句）
    'express': 600,          # 快递轨迹：10 分钟
    'phone': 86400,          # 手机归属地：24 小时（基本不变）
    'hotboard': 300,         # 热榜：5 分钟
    'daily_word': 21600,     # 每日单词：6 小时
    'news_image': 3600,      # 每日新闻图：1 小时
}


def _cache_get(key):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
    return None


def _cache_put(key, data, ttl):
    now = time.time()
    with _cache_lock:
        # 简单容量治理：超 500 条先清过期项，仍超则淘汰最旧 20%
        if len(_cache) > 500:
            expired = [k for k, v in _cache.items() if v[0] <= now]
            for k in expired:
                _cache.pop(k, None)
            if len(_cache) > 500:
                for k in list(_cache.keys())[:100]:
                    _cache.pop(k, None)
        _cache[key] = (now + ttl, data)


def clear_cache(prefix=None):
    """清空缓存（前缀过滤可选）——配置页保存 Key 后调用，避免新旧认证结果混存"""
    with _cache_lock:
        if prefix is None:
            _cache.clear()
        else:
            for k in [k for k in _cache if str(k).startswith(prefix)]:
                _cache.pop(k, None)


# ===================== 内部请求核心 =====================

def _http_request(method, url, params=None, json_body=None, timeout=None, headers=None):
    """双路径网络请求：① 禁代理直连（Session trust_env=False）；② 失败回落系统代理。
    返回 requests.Response；两条路径均失败抛最后异常。"""
    import requests
    last_err = None
    for trust_env in (False, True):
        try:
            with requests.Session() as s:
                s.trust_env = trust_env
                if method.upper() == 'POST':
                    return s.post(url, params=params, json=json_body,
                                  timeout=timeout or DEFAULT_TIMEOUT, headers=headers)
                return s.get(url, params=params,
                             timeout=timeout or DEFAULT_TIMEOUT, headers=headers)
        except Exception as e:
            last_err = e
    raise last_err


def _platform_headers():
    """平台认证头：从注册表读取（Key 空 = 访客模式，无认证头）"""
    return dict(service_config.get_auth_headers(uapi_catalog.UAPI_PLATFORM_ID))


def _platform_base_url():
    """平台 base_url：注册表优先，缺省回落官方默认"""
    p = service_config.get_platform(uapi_catalog.UAPI_PLATFORM_ID)
    return (p or {}).get('base_url') or uapi_catalog.UAPI_DEFAULT_BASE_URL


def _platform_enabled():
    """平台是否启用（管理员停用后全站 uapis 调用静默降级）"""
    p = service_config.get_platform(uapi_catalog.UAPI_PLATFORM_ID)
    return bool((p or {}).get('enabled', True))


def extract_error_message(status, payload):
    """错误信息标准化：兼容 {code, message}、{error, ...}、{code:数字} 三种格式（FAQ Q32）"""
    if not isinstance(payload, dict):
        return 'HTTP %s：响应非 JSON 对象' % status
    code = payload.get('code')
    err = payload.get('error')
    message = str(payload.get('message') or payload.get('details') or '')
    # code 可能是字符串错误码或数字（限流类 {code: 429, message: ...}）
    code_str = str(code) if code not in (None, '') else str(err or '')
    if isinstance(code, int):
        code_str = ''
    if not message:
        message = str(err) if err and not isinstance(err, bool) else ''
    # 访客额度耗尽：给出可操作指引（FAQ Q14/Q16）
    if VISITOR_QUOTA_CODE in (code_str, message):
        return '访客本月免费额度已用尽（每月 1 号自动重置）；如需立即恢复，请在「API 平台」配置 UApiPro API Key'
    if status == 401:
        return 'API Key 无效、已过期或已被删除（HTTP 401），请检查平台 Key 配置'
    if status == 402:
        return '平台积分/余额已用尽（HTTP 402），请前往 uapis.cn 充值或等待月初额度重置'
    if status == 403:
        return '访问被拒绝（HTTP 403）：跨域未带 Key / IP 白名单 / 接口白名单不匹配'
    if status == 429:
        return ('请求过于频繁被限流（429）' + ('：%s' % message if message else '') +
                '；已按指数退避重试仍受限，请稍后再试')
    return ('HTTP %s：%s' % (status, message)) if message else 'HTTP %s：接口调用失败' % status


def _request_with_backoff(method, url, params=None, json_body=None, timeout=None):
    """带退避的请求循环：429/5xx/超时按 BACKOFF_SCHEDULE 退避重试，客户端错误立即返回。
    返回 (ok, payload_dict|None, status, message)"""
    headers = _platform_headers()
    headers.setdefault('Accept', 'application/json')
    last_status, last_payload, last_message = 0, None, ''
    for round_idx in range(MAX_BACKOFF_ROUNDS):
        try:
            resp = _http_request(method, url, params=params, json_body=json_body,
                                 timeout=timeout, headers=headers)
        except Exception as e:
            # 网络层异常（超时/连接失败）：退避后重试
            last_status, last_payload = 0, None
            last_message = '网络请求失败：%s' % str(e)[:150]
            if round_idx < MAX_BACKOFF_ROUNDS - 1:
                time.sleep(BACKOFF_SCHEDULE[round_idx])
                continue
            break
        last_status = resp.status_code
        try:
            last_payload = resp.json() if resp.content else None
        except ValueError:
            last_payload = None
        if 200 <= resp.status_code < 300:
            return True, (last_payload if isinstance(last_payload, dict) else
                          {'_raw_non_dict': True, '_status': resp.status_code}), resp.status_code, ''
        last_message = extract_error_message(resp.status_code, last_payload)
        # 客户端错误（400/401/402/403/404…）：修正请求后才可能成功，不重试
        if resp.status_code in NO_RETRY_STATUS:
            break
        # 限流：优先尊重服务端 Retry-After
        if resp.status_code == 429 or resp.status_code >= 500 or resp.status_code == 408:
            retry_after = resp.headers.get('Retry-After')
            wait = None
            try:
                wait = float(retry_after) if retry_after else None
            except (TypeError, ValueError):
                wait = None
            if wait is None:
                wait = BACKOFF_SCHEDULE[min(round_idx, len(BACKOFF_SCHEDULE) - 1)]
            if round_idx < MAX_BACKOFF_ROUNDS - 1:
                time.sleep(min(wait, 8))
                continue
            break
        break
    return False, last_payload, last_status, last_message


# ===================== 通用调用入口 =====================

def call_uapi(api_id, params=None, timeout=None, full_url=None):
    """按目录 API ID 调用 UApiPro 接口，返回 (ok, payload_dict|None, status, message)
    - api_id：uapi_catalog 目录内部 ID（如 misc_weather）
    - params：GET 拼 query / POST 作 JSON body（值统一转字符串）
    - full_url：非空时直接使用该完整地址（组内端点故障转移遍历用，认证头照常注入），
      为空时按 平台 base_url + API path 拼接
    - 平台被管理员停用时返回 (False, None, 503, 提示)"""
    api = uapi_catalog.get_api(api_id)
    if not api:
        return False, None, 400, '未知 API：%s' % api_id
    if not _platform_enabled():
        return False, None, 503, 'UApiPro 平台已停用，请在「系统设置 → 外部接口服务 → API 平台」重新启用'

    method = (api.get('method') or 'GET').upper()
    url = full_url or uapi_catalog.build_full_url(api_id, base_url=_platform_base_url())
    if not url:
        return False, None, 500, 'API 地址构造失败（base_url 未配置）'

    # 参数清洗：None/空串剔除，bool 转 'true'/'false'，其余转字符串
    clean = {}
    for k, v in (params or {}).items():
        if v is None:
            continue
        if isinstance(v, bool):
            clean[k] = 'true' if v else 'false'
        elif isinstance(v, str):
            if v != '':
                clean[k] = v
        else:
            clean[k] = str(v)

    if method == 'POST':
        return _request_with_backoff('POST', url, params=None,
                                     json_body=clean, timeout=timeout)
    return _request_with_backoff('GET', url, params=clean, timeout=timeout)


def call_uapi_raw(api_id, params=None, timeout=None):
    """试验台原始调用：返回响应元信息 + 内容（JSON 文本化 / 图片 base64 / 其他文本）
    不做退避重试（管理员调试需要看到真实失败），返回
    {status, content_type, is_json, json, is_image, image_b64, body_text, message}"""
    api = uapi_catalog.get_api(api_id)
    if not api:
        return {'status': 400, 'message': '未知 API：%s' % api_id, 'is_json': False,
                'is_image': False, 'content_type': '', 'json': None, 'image_b64': '', 'body_text': ''}
    if not _platform_enabled():
        return {'status': 503, 'message': 'UApiPro 平台已停用', 'is_json': False,
                'is_image': False, 'content_type': '', 'json': None, 'image_b64': '', 'body_text': ''}
    method = (api.get('method') or 'GET').upper()
    url = uapi_catalog.build_full_url(api_id, base_url=_platform_base_url())
    clean = {}
    for k, v in (params or {}).items():
        if v is None or v == '':
            continue
        clean[k] = ('true' if v else 'false') if isinstance(v, bool) else str(v)
    out = {'status': 0, 'content_type': '', 'is_json': False, 'json': None,
           'is_image': False, 'image_b64': '', 'body_text': '', 'message': ''}
    try:
        resp = _http_request(method, url, params=(clean if method == 'GET' else None),
                             json_body=(clean if method == 'POST' else None),
                             timeout=timeout or (5, 15), headers=_platform_headers())
        out['status'] = resp.status_code
        ctype = (resp.headers.get('Content-Type') or '').lower()
        out['content_type'] = ctype
        if 'image/' in ctype:
            out['is_image'] = True
            out['image_b64'] = base64.b64encode(resp.content or b'').decode('ascii')
        else:
            text = (resp.text or '')[:60000]  # 防超长响应撑爆页面
            out['body_text'] = text
            if 'json' in ctype:
                try:
                    out['is_json'] = True
                    out['json'] = resp.json()
                except ValueError:
                    pass
            elif not out['body_text']:
                out['body_text'] = '（空响应体）'
        if not (200 <= resp.status_code < 300):
            out['message'] = extract_error_message(resp.status_code,
                                                   out['json'] if out['is_json'] else None)
    except Exception as e:
        out['status'] = 0
        out['message'] = '网络请求失败：%s' % str(e)[:150]
    return out


# ===================== 业务便捷函数（带进程级缓存） =====================

def get_daily_saying(force=False):
    """一言（免费接口）：登录页/首页装饰用。进程级缓存 1 小时（全站共享一句）。
    返回 {'text': str} 或 None（失败静默降级，装饰位不显示）"""
    if not force:
        cached = _cache_get('saying')
        if cached is not None:
            return cached
    ok, payload, status, message = call_uapi('saying', timeout=(5, 8))
    data = {'text': str((payload or {}).get('text') or '')} if ok and payload else None
    if data and data['text']:
        _cache_put('saying', data, _CACHE_TTLS['saying'])
        return data
    return _cache_get('saying')  # 拉取失败时用过期缓存兜底


def query_express(tracking_number, phone=None, force=False):
    """快递物流查询（40 积分/次，访客月免费 5 次）：轨迹缓存 10 分钟控消耗。
    返回 (ok, payload, message)；payload: {carrier_name, tracks:[{time,context}], ...}"""
    key = 'express:%s:%s' % (str(tracking_number).strip(), str(phone or '').strip())
    if not force:
        cached = _cache_get(key)
        if cached is not None:
            return True, cached, '（缓存 10 分钟内的最新轨迹）'
    params = {'tracking_number': str(tracking_number).strip()}
    if phone:
        params['phone'] = str(phone).strip()
    ok, payload, status, message = call_uapi('misc_tracking_query', params=params,
                                            timeout=(5, 15))
    if ok and isinstance(payload, dict):
        _cache_put(key, payload, _CACHE_TTLS['express'])
    return ok, payload, message


def detect_express_carrier(tracking_number):
    """识别快递公司（2 积分/次）：返回 (ok, payload, message)"""
    return call_uapi('misc_tracking_detect',
                    params={'tracking_number': str(tracking_number).strip()},
                    timeout=(5, 10))


def lookup_phone(phone, force=False):
    """手机归属地（2 积分/次）：缓存 24 小时（归属地基本不变）。
    返回 (ok, payload, message)；payload: {province, city, sp, area_code}"""
    key = 'phone:%s' % str(phone).strip()
    if not force:
        cached = _cache_get(key)
        if cached is not None:
            return True, cached, ''
    ok, payload, status, message = call_uapi('misc_phoneinfo',
                                             params={'phone': str(phone).strip()},
                                             timeout=(5, 8))
    if ok and isinstance(payload, dict):
        _cache_put(key, payload, _CACHE_TTLS['phone'])
    return ok, payload, message


def search_hotboard(board_type='weibo', force=False):
    """热榜（1 积分/次）：缓存 5 分钟。返回 (ok, payload, message)"""
    key = 'hotboard:%s' % str(board_type).strip()
    if not force:
        cached = _cache_get(key)
        if cached is not None:
            return True, cached, ''
    ok, payload, status, message = call_uapi('misc_hotboard',
                                             params={'type': str(board_type).strip()},
                                             timeout=(5, 10))
    if ok and isinstance(payload, dict):
        _cache_put(key, payload, _CACHE_TTLS['hotboard'])
    return ok, payload, message


def get_daily_word(category='cet4', force=False):
    """每日单词（1 积分/次）：同日稳定结果，缓存 6 小时。返回 (ok, payload, message)"""
    key = 'daily_word:%s' % str(category).strip()
    if not force:
        cached = _cache_get(key)
        if cached is not None:
            return True, cached, ''
    ok, payload, status, message = call_uapi('daily_word',
                                             params={'category': category, 'count': '1'},
                                             timeout=(5, 10))
    if ok and isinstance(payload, dict):
        _cache_put(key, payload, _CACHE_TTLS['daily_word'])
    return ok, payload, message
