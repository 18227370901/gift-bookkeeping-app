# -*- coding: utf-8 -*-
"""
uapi_client.py — UApiPro（uapis.cn）统一调用引擎（V10.11.47 新增，V10.11.48 多 Key 轮换升级）

全站调用 uapis.cn 平台 110 个 API 的唯一出入口，能力：
  1. 认证注入：自动读取「API 平台」注册表的 base_url 与平台 Key 池（V10.11.48 多 Key）
     （Authorization: Bearer <key>；池空 = 访客模式直连）
  2. **Key 轮换（V10.11.48）**：按 Key 池顺序依次尝试——401（Key 无效）/402（额度不足）/
     访客额度耗尽自动切换下一个 Key 重试；全部 Key 失败才返回错误。单 Key 场景行为与旧版一致
  3. 双路径网络：禁代理直连优先 + 系统代理兜底（与 weather_service._http_get 同款策略）
  4. 限流退避：429 尊重 Retry-After 头，否则按 0.5s/1s/2s 指数退避；
     5xx/超时/网络异常退避重试；400/401/402/403/404 属客户端错误不重试（Key 级错误切 Key）
  5. 错误标准化：兼容 {code, message} 与 {error, ...} 双格式错误体（官方 FAQ Q32）
  6. **响应美化（V10.11.48）**：format_uapi_result() 把常用 API 的 JSON 响应转为
     人类可读中文摘要（目录一键测试与试验台展示用）
  7. 试验台原始调用：识别非 JSON 响应（图片/音频/文件流）并 base64 回传展示

对外主入口（业务便捷函数）：
  get_daily_saying()          一言（登录页/首页装饰，免费接口，进程级缓存 1 小时）
  query_express(no, phone)    快递物流查询（40 积分/次，缓存 10 分钟控积分消耗）
  lookup_phone(phone)         手机归属地（2 积分/次，缓存 24 小时）
  search_hotboard(type)       热榜（1 积分/次，缓存 5 分钟）
  get_daily_word(category)    每日单词（1 积分/次，缓存 6 小时）
  call_uapi(...)              通用调用（weather/holiday 适配器与试验台使用）
  format_uapi_result(...)     响应美化（目录测试/试验台展示）
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
# Key 级失败错误码集：出现这些情况时自动切换 Key 池下一个 Key 重试（V10.11.48）
KEY_FATAL_CODES = (VISITOR_QUOTA_CODE, 'UNAUTHORIZED', 'INSUFFICIENT_CREDITS', 'AUTHENTICATION_REQUIRED')


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
                m = method.upper()
                if m in ('POST', 'PUT', 'PATCH'):
                    return s.request(m, url, params=params, json=json_body,
                                     timeout=timeout or DEFAULT_TIMEOUT, headers=headers)
                if m == 'DELETE':
                    return s.delete(url, params=params,
                                    timeout=timeout or DEFAULT_TIMEOUT, headers=headers)
                return s.get(url, params=params,
                             timeout=timeout or DEFAULT_TIMEOUT, headers=headers)
        except Exception as e:
            last_err = e
    raise last_err


def _platform_headers(platform_id=uapi_catalog.UAPI_PLATFORM_ID, key=None):
    """平台认证头：从注册表读取（V10.11.48 指定具体 Key，供轮换引擎用；池空 = 访客模式无认证头）"""
    return dict(service_config.get_auth_headers(platform_id, key=key))


def _platform_base_url(platform_id=uapi_catalog.UAPI_PLATFORM_ID):
    """平台 base_url：注册表优先；内置平台缺省回落官方默认，自定义平台无地址返回空串（由调用方报错）"""
    p = service_config.get_platform(platform_id)
    if p and str(p.get('base_url') or '').strip():
        return str(p['base_url']).strip()
    if platform_id == uapi_catalog.UAPI_PLATFORM_ID:
        return uapi_catalog.UAPI_DEFAULT_BASE_URL
    return ''


def _platform_enabled(platform_id=uapi_catalog.UAPI_PLATFORM_ID):
    """平台是否启用（管理员停用后全站该平台调用静默降级）"""
    p = service_config.get_platform(platform_id)
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


def _request_with_key_rotation(method, url, params=None, json_body=None, timeout=None,
                               platform_id=None):
    """V10.11.48 Key 轮换请求循环（替代 V10.11.47 单 Key 版）：
    外层按 Key 池顺序轮换（池空 = 单轮访客模式），内层做退避重试。
    Key 级失败（401 Key 无效 / 402 额度不足 / 429 访客额度耗尽 / 速率限流重试仍败）
    自动切换下一个 Key；平台级/网络错误（5xx 重试仍败、连接失败）也换 Key 兜底再试
    （多 Key 请求路径可能不同，切换无害且提高成功率）；全部 Key 失败返回最后一个错误。
    返回 (ok, payload, status, message, key_label)——key_label 为成功所用 Key 标签
    （访客模式返回 '访客模式'；多 Key 仅展示用，不回传明文）"""
    platform_id = platform_id or uapi_catalog.UAPI_PLATFORM_ID
    keys = service_config.get_platform_keys(platform_id)
    # 轮换序列：启用的 Key 池（每项 {key, label}）；池空 = 单轮访客模式 (None, '访客模式')
    rotation = [(k['key'], k['label']) for k in keys] or [(None, '访客模式')]

    last_status, last_message = 0, ''
    for key, label in rotation:
        headers = _platform_headers(platform_id, key=key)
        headers.setdefault('Accept', 'application/json')
        ok, payload, status, message = _request_single_with_backoff(
            method, url, params=params, json_body=json_body, timeout=timeout, headers=headers)
        if ok:
            return True, payload, status, '', label
        last_status, last_message = status, message
        # Key 级失败：切换下一个 Key（信息附 Key 标签便于排查）
        if _is_key_level_failure(status, payload):
            print('[UapiClient] Key「%s」调用失败（HTTP %s：%s），自动切换下一个 Key' % (
                (label or '未命名')[:30], status, (message or '')[:80]))
            continue
        # 网络级/平台级失败：也尝试下一个 Key（不同 Key 独立限流桶，切换可能恢复）
        if status == 0 or status >= 500 or status == 429 or status == 408:
            continue
        # 其他客户端错误（400 参数错 / 404 资源不存在等）：与 Key 无关，直接返回
        return False, payload, status, message, label
    # 全部 Key 失败：返回最后错误（多 Key 轮换尽力信息）
    if len(rotation) > 1:
        last_message = ('已按序轮换 %d 个 Key 均失败，最后错误：%s' % (len(rotation), last_message or '未知')) \
            if last_message else ('已按序轮换 %d 个 Key 均失败' % len(rotation))
    return False, None, last_status, last_message, rotation[-1][1]


def _is_key_level_failure(status, payload):
    """判定失败是否 Key 级（切换 Key 可能恢复）：401/402/访客额度耗尽/认证要求"""
    if status in (401, 402):
        return True
    if isinstance(payload, dict):
        code = str(payload.get('code') or payload.get('error') or '')
        if code in KEY_FATAL_CODES:
            return True
        msg = str(payload.get('message') or '')
        if VISITOR_QUOTA_CODE in msg:
            return True
    return False


def _request_single_with_backoff(method, url, params=None, json_body=None, timeout=None, headers=None):
    """单 Key 带退避的请求循环（轮换引擎内层）：429/5xx/超时按 BACKOFF_SCHEDULE 退避重试，
    客户端错误立即返回。返回 (ok, payload_dict|None, status, message)"""
    last_status, last_payload, last_message = 0, None, ''
    for round_idx in range(MAX_BACKOFF_ROUNDS):
        try:
            resp = _http_request(method, url, params=params, json_body=json_body,
                                 timeout=timeout, headers=headers)
        except Exception as e:
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
        if resp.status_code in NO_RETRY_STATUS:
            break
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

def call_uapi(api_id, params=None, timeout=None, full_url=None,
              platform_id=None, return_key=False):
    """按目录 API ID 调用 UApiPro 接口
    - api_id：uapi_catalog 目录内部 ID（如 misc_weather）
    - params：GET 拼 query / POST 作 JSON body（值统一转字符串）
    - full_url：非空时直接使用该完整地址（组内端点故障转移遍历用），认证照常注入
    - platform_id：V10.11.48 平台 ID（默认 uapis；端点适配器按端点 platform 分发）
    - return_key：True 时返回 5 元组（附成功所用 Key 标签）；默认 4 元组向后兼容
    返回 (ok, payload_dict|None, status, message[, key_label])；平台停用返回 503"""
    api = uapi_catalog.get_api(api_id)
    if not api:
        result = (False, None, 400, '未知 API：%s' % api_id)
        return result + (None,) if return_key else result
    platform_id = platform_id or uapi_catalog.UAPI_PLATFORM_ID
    if not _platform_enabled(platform_id):
        result = (False, None, 503, 'API 平台「%s」已停用，请在「系统设置 → 外部接口服务 → API 平台」重新启用' % platform_id)
        return result + (None,) if return_key else result

    method = (api.get('method') or 'GET').upper()

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

    # V10.11.51：路径占位符（/api/raw/{id} 等）先替换进 URL，再从 query 剔除
    url = full_url or uapi_catalog.build_full_url(
        api_id, base_url=_platform_base_url(platform_id), params=clean)
    if not url:
        result = (False, None, 500, 'API 地址构造失败（平台 base_url 未配置）')
        return result + (None,) if return_key else result
    path_params = uapi_catalog.path_param_names(api_id)
    if path_params and not full_url:
        clean = {k: v for k, v in clean.items() if k not in path_params}

    if method == 'POST':
        ok, payload, status, message, key_label = _request_with_key_rotation(
            'POST', url, params=None, json_body=clean, timeout=timeout, platform_id=platform_id)
    else:
        ok, payload, status, message, key_label = _request_with_key_rotation(
            'GET', url, params=clean, timeout=timeout, platform_id=platform_id)
    return (ok, payload, status, message, key_label) if return_key else (ok, payload, status, message)


def call_uapi_raw(api_id, params=None, timeout=None, platform_id=None):
    """试验台原始调用：返回响应元信息 + 内容（JSON 文本化 / 图片 base64 / 其他文本）
    不做退避重试与 Key 轮换（管理员调试需要看到单次真实失败，Key 问题由平台测试按钮验证），
    返回 {status, content_type, is_json, json, is_image, image_b64, body_text, message}"""
    api = uapi_catalog.get_api(api_id)
    if not api:
        return {'status': 400, 'message': '未知 API：%s' % api_id, 'is_json': False,
                'is_image': False, 'content_type': '', 'json': None, 'image_b64': '', 'body_text': ''}
    platform_id = platform_id or uapi_catalog.UAPI_PLATFORM_ID
    if not _platform_enabled(platform_id):
        return {'status': 503, 'message': 'API 平台已停用', 'is_json': False,
                'is_image': False, 'content_type': '', 'json': None, 'image_b64': '', 'body_text': ''}
    method = (api.get('method') or 'GET').upper()
    clean = {}
    for k, v in (params or {}).items():
        if v is None or v == '':
            continue
        clean[k] = ('true' if v else 'false') if isinstance(v, bool) else str(v)
    # V10.11.51：路径占位符替换（{id}/{task_id}）并从 query 剔除
    url = uapi_catalog.build_full_url(api_id, base_url=_platform_base_url(platform_id), params=clean)
    path_params = uapi_catalog.path_param_names(api_id)
    if path_params:
        clean = {k: v for k, v in clean.items() if k not in path_params}
    out = {'status': 0, 'content_type': '', 'is_json': False, 'json': None,
           'is_image': False, 'image_b64': '', 'body_text': '', 'message': ''}
    try:
        resp = _http_request(method, url, params=(clean if method == 'GET' else None),
                             json_body=(clean if method == 'POST' else None),
                             timeout=timeout or (5, 15),
                             headers=_platform_headers(platform_id))
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


# ===================== V10.11.51 平台自定义 API 调用 =====================

def resolve_api_def(platform_id, api_id):
    """统一解析 API 定义：先查内置静态目录，再查平台自定义/导入条目
    返回 API 定义 dict 或 None（供一键测试与试验台共用）"""
    api = uapi_catalog.get_api(api_id)
    if api:
        return api
    try:
        return service_config.get_platform_api(platform_id, api_id)
    except Exception:
        return None


def _join_platform_url(base_url, path, params=None):
    """平台 base_url + 自定义 path 拼接（支持 {id} 类路径占位符）"""
    import re as _re
    base = str(base_url or '').rstrip('/')
    p = str(path or '')
    if not p.startswith('/'):
        p = '/' + p
    if params:
        for ph in _re.findall(r'\{(\w+)\}', p):
            if ph in params and params[ph] not in (None, ''):
                p = p.replace('{' + ph + '}', str(params[ph]))
    return base + p


def _same_origin(url, base_url):
    """SSRF 防线：最终 URL 的 scheme+host 必须与平台 base_url 完全一致"""
    from urllib.parse import urlparse
    u = urlparse(str(url or ''))
    b = urlparse(str(base_url or ''))
    return (u.scheme in ('http', 'https') and u.scheme == b.scheme and u.netloc == b.netloc)


def call_platform_api(platform_id, api_def, params=None, timeout=None, return_key=False):
    """调用平台自定义/导入的 API（脱离静态目录 api_id）
    - 认证与 Key 轮换复用现有引擎（与 call_uapi 行为一致）
    - 返回 (ok, payload, status, message[, key_label])；平台停用返回 503"""
    platform_id = platform_id or uapi_catalog.UAPI_PLATFORM_ID
    if not _platform_enabled(platform_id):
        result = (False, None, 503, 'API 平台「%s」已停用，请先启用' % platform_id)
        return result + (None,) if return_key else result
    if not isinstance(api_def, dict):
        result = (False, None, 400, '未知 API 定义')
        return result + (None,) if return_key else result

    method = str(api_def.get('method') or 'GET').upper()
    is_body_method = method in ('POST', 'PUT', 'PATCH')
    clean = _prepare_platform_params(api_def, params, for_json_body=is_body_method)

    base_url = _platform_base_url(platform_id)
    url = _join_platform_url(base_url, api_def.get('path'), clean)
    if not _same_origin(url, base_url):
        result = (False, None, 400, '接口地址越界（最终 URL 与平台地址不同源，已拦截）')
        return result + (None,) if return_key else result
    path_params = service_config_path_params(api_def.get('path'))
    if path_params:
        clean = {k: v for k, v in clean.items() if k not in path_params}

    if is_body_method:
        ok, payload, status, message, key_label = _request_with_key_rotation(
            method, url, params=None, json_body=clean, timeout=timeout, platform_id=platform_id)
    else:
        ok, payload, status, message, key_label = _request_with_key_rotation(
            method, url, params=clean, timeout=timeout, platform_id=platform_id)
    return (ok, payload, status, message, key_label) if return_key else (ok, payload, status, message)


def _coerce_json_param(ptype, value):
    import json as _json
    t = str(ptype or '').strip().lower()
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bool):
        return value if t in ('bool', 'boolean') else ('true' if value else 'false')
    sv = str(value).strip()
    if t in ('int', 'integer', 'long', 'int64', 'int32', 'timestamp'):
        try:
            return int(sv)
        except ValueError:
            return sv
    if t in ('float', 'double', 'decimal', 'number'):
        try:
            if t == 'number' and sv.lstrip('-').isdigit():
                return int(sv)
            return float(sv)
        except ValueError:
            return sv
    if t in ('bool', 'boolean'):
        low = sv.lower()
        if low in ('true', '1', 'yes'):
            return True
        if low in ('false', '0', 'no'):
            return False
        return sv
    if t in ('array', 'list'):
        if sv.startswith('['):
            try:
                parsed = _json.loads(sv)
                if isinstance(parsed, list):
                    return parsed
            except ValueError:
                pass
        return [x.strip() for x in sv.replace('，', ',').split(',') if x.strip()]
    if t in ('object', 'json', 'dict', 'map'):
        try:
            parsed = _json.loads(sv)
            if isinstance(parsed, (dict, list)):
                return parsed
        except ValueError:
            pass
    return str(value)


def _prepare_platform_params(api_def, params, for_json_body=False):
    type_map = {str(p.get('name') or ''): str(p.get('type') or '') for p in (api_def.get('params') or []) if isinstance(p, dict)}
    clean = {}
    for k, v in (params or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and v == '':
            continue
        if for_json_body:
            clean[k] = _coerce_json_param(type_map.get(k, ''), v)
        else:
            if isinstance(v, bool):
                clean[k] = 'true' if v else 'false'
            elif isinstance(v, (dict, list)):
                import json as _json
                clean[k] = _json.dumps(v, ensure_ascii=False)
            else:
                clean[k] = str(v)
    return clean


def service_config_path_params(path):
    """提取 path 中的 {xxx} 占位符名（局部实现，避免循环依赖 service_config）"""
    import re as _re
    return set(_re.findall(r'\{(\w+)\}', str(path or '')))


def call_platform_api_raw(platform_id, api_def, params=None, timeout=None):
    """平台自定义 API 的试验台原始调用（单次、不轮换、不重试，便于定位真实错误）
    返回结构与 call_uapi_raw 一致"""
    platform_id = platform_id or uapi_catalog.UAPI_PLATFORM_ID
    empty = {'status': 0, 'content_type': '', 'is_json': False, 'json': None,
             'is_image': False, 'image_b64': '', 'body_text': '', 'message': ''}
    if not _platform_enabled(platform_id):
        empty.update({'status': 503, 'message': 'API 平台已停用'})
        return empty
    if not isinstance(api_def, dict):
        empty.update({'status': 400, 'message': '未知 API 定义'})
        return empty
    method = str(api_def.get('method') or 'GET').upper()
    is_body_method = method in ('POST', 'PUT', 'PATCH')
    clean = _prepare_platform_params(api_def, params, for_json_body=is_body_method)
    base_url = _platform_base_url(platform_id)
    url = _join_platform_url(base_url, api_def.get('path'), clean)
    if not _same_origin(url, base_url):
        empty.update({'status': 400, 'message': '接口地址越界（最终 URL 与平台地址不同源，已拦截）'})
        return empty
    path_params = service_config_path_params(api_def.get('path'))
    if path_params:
        clean = {k: v for k, v in clean.items() if k not in path_params}
    out = dict(empty)
    try:
        resp = _http_request(method, url, params=(None if is_body_method else clean),
                             json_body=(clean if is_body_method else None),
                             timeout=timeout or (5, 15),
                             headers=_platform_headers(platform_id))
        out['status'] = resp.status_code
        ctype = (resp.headers.get('Content-Type') or '').lower()
        out['content_type'] = ctype
        if 'image/' in ctype:
            out['is_image'] = True
            out['image_b64'] = base64.b64encode(resp.content or b'').decode('ascii')
        else:
            text = (resp.text or '')[:60000]
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


# ===================== V10.11.48 响应美化层（人类可读格式化器） =====================
# 每个 formatter: (payload_dict) -> 中文人读摘要字符串；字段缺失时容错跳过，无法格式化返回 None

def _fmt_worldtime(d):
    parts = []
    if d.get('query'):
        parts.append('📍 %s' % d['query'])
    if d.get('timezone'):
        parts.append('时区 %s' % d['timezone'])
    if d.get('datetime'):
        parts.append('当地时间 %s %s' % (d['datetime'], d.get('weekday') or ''))
    if d.get('offset_string'):
        parts.append('UTC%s' % str(d['offset_string']).replace('UTC', ''))
    return '　|　'.join(parts)


def _fmt_lunartime(d):
    parts = []
    if d.get('datetime'):
        parts.append('公历 %s %s' % (d['datetime'], d.get('weekday_cn') or ''))
    if d.get('lunar_month_cn') and d.get('lunar_day_cn'):
        leap = '（闰）' if d.get('is_leap_month') else ''
        parts.append('农历%s年%s%s%s（%s年）' % (d.get('ganzhi_year') or '', d['lunar_month_cn'],
                                              leap, d['lunar_day_cn'],
                                              d.get('lunar_year_cn') or d.get('lunar_year') or ''))
    if d.get('zodiac'):
        parts.append('生肖%s' % d['zodiac'])
    if d.get('ganzhi_day'):
        parts.append('日干支 %s' % d['ganzhi_day'])
    return '　·　'.join(parts)


def _fmt_weather(d):
    parts = []
    if d.get('city'):
        parts.append('📍 %s%s' % (str((d.get('province') or '') + ' ' if d.get('province') else '')[:12], d['city']))
    if d.get('weather'):
        parts.append(d['weather'])
    if d.get('temperature') is not None:
        parts.append('%s°C' % d['temperature'])
    if d.get('humidity') is not None:
        parts.append('湿度 %s%%' % d['humidity'])
    if d.get('wind_direction') or d.get('wind_power'):
        parts.append('%s%s' % (d.get('wind_direction') or '', d.get('wind_power') or ''))
    if d.get('aqi') is not None:
        parts.append('AQI %s（%s）' % (d.get('aqi'), d.get('aqi_category') or ''))
    if d.get('temp_max') is not None or d.get('temp_min') is not None:
        parts.append('今日 %s°C / %s°C' % (d.get('temp_max', '-'), d.get('temp_min', '-')))
    if d.get('report_time'):
        parts.append('更新 %s' % d['report_time'])
    return '　|　'.join(parts)


def _fmt_hotboard(d):
    items = d.get('list') or []
    if not items:
        return None
    lines = ['📊 %s热榜（更新 %s）' % (d.get('type') or '', str((d.get('update_time') or ''))[:19])]
    for it in items[:10]:
        hot = it.get('hot_value')
        lines.append('%d. %s%s' % (it.get('index') or 0, it.get('title') or '',
                                   ('（热度 %s）' % hot) if hot else ''))
    return '\n'.join(lines)


def _fmt_phoneinfo(d):
    return '📱 %s %s · %s · 区号 %s' % (d.get('province') or '--', d.get('city') or '--',
                                      d.get('sp') or '--', d.get('area_code') or '--')


def _fmt_date_diff(d):
    if d.get('human_readable'):
        return '📅 相差 %s（%d 天 / %d 周）' % (d['human_readable'], d.get('days') or 0, d.get('weeks') or 0)
    if d.get('days') is not None:
        return '📅 相差 %d 天（%d 周）' % (d['days'], d.get('weeks') or 0)
    return None


def _fmt_unixtime(d):
    if d.get('datetime') and d.get('timestamp'):
        return '🕓 时间戳 %d = %s' % (d['timestamp'], d['datetime'])
    return None


def _fmt_daily_word(d):
    words = d.get('words') or []
    if not words:
        return None
    w = words[0]
    lines = ['📖 %s %s' % (w.get('word') or '', w.get('phonetic') or '')]
    if w.get('translation'):
        lines.append('释义：%s' % w['translation'])
    exs = w.get('examples') or []
    if exs:
        e = exs[0]
        lines.append('例句：%s' % e.get('text') or '')
        if e.get('translation'):
            lines.append('　　译文：%s' % e['translation'])
    return '\n'.join(lines)


def _fmt_programmer(d):
    events = d.get('events') or []
    if not events:
        return None
    lines = ['💻 %s 月 %s 日科技史（%d 条）' % (d.get('date') or '', '', len(events))]
    for e in events[:6]:
        lines.append('%d年 [%s] %s' % (e.get('year') or 0, e.get('category') or '', e.get('title') or ''))
    return '\n'.join(lines)


def _fmt_ip(d):
    region = ' '.join(str(x) for x in [d.get('country') or d.get('region') or '', d.get('city') or ''] if x)
    return '🌐 IP %s · %s%s' % (d.get('ip') or '--', region or '未知',
                                (' · %s' % d['llc']) if d.get('llc') else '')


def _fmt_translate(d):
    if d.get('translate'):
        return '🌐 %s → %s' % (d.get('text') or '', d['translate'])
    return None


def _fmt_saying(d):
    return '💬 %s' % d.get('text') if d.get('text') else None


def _fmt_kv_wrapper(field, prefix):
    def _f(d):
        if d.get(field):
            return '%s%s' % (prefix, d[field])
        return None
    return _f


def _fmt_holiday_calendar(d):
    days = d.get('days') or []
    if not days:
        return None
    day = days[0]
    lines = ['📅 %s（%s）' % (day.get('date') or '', day.get('weekday_cn') or '')]
    names = []
    if day.get('legal_holiday_name'):
        marks = '休' if day.get('legal_holiday_type') == 'rest' else '补班'
        names.append('%s（%s）' % (day['legal_holiday_name'], marks))
    for f in ('solar_festival', 'lunar_festival', 'solar_term'):
        if day.get(f):
            names.append(day[f])
    if names:
        lines.append('　' + ' · '.join(names))
    lines.append('　农历 %s年%s月%s' % (day.get('ganzhi_year') or '', day.get('lunar_month_name') or '',
                                       day.get('lunar_day_name') or ''))
    if day.get('is_rest_day') is not None:
        lines.append('　%s' % ('今日休息日' if day.get('is_rest_day') else '今日工作日'))
    return '\n'.join(lines)


def _fmt_github_repo(d):
    if not d.get('full_name'):
        return None
    return '🐙 %s ⭐%s 🍴%s · %s' % (d.get('full_name'), d.get('stargazers_count', '-'),
                                  d.get('forks_count', '-'), d.get('language') or '')


def _fmt_epic_free(d):
    games = d.get('games') or d.get('list') or d.get('data') or []
    if isinstance(games, list) and games:
        lines = ['🎮 Epic 免费游戏']
        for g in games[:5]:
            name = g.get('title') or g.get('name') or ''
            lines.append('　· %s' % name)
        return '\n'.join(lines)
    return None


# 格式化器注册表：API ID → formatter 映射（未注册的 API 返回 None 走原始 JSON 展示）
FORMATTERS = {
    'misc_worldtime': _fmt_worldtime,
    'misc_lunartime': _fmt_lunartime,
    'misc_weather': _fmt_weather,
    'misc_weather_history': _fmt_weather,
    'misc_hotboard': _fmt_hotboard,
    'misc_phoneinfo': _fmt_phoneinfo,
    'misc_date_diff': _fmt_date_diff,
    'convert_unixtime': _fmt_unixtime,
    'misc_timestamp': _fmt_unixtime,
    'misc_holiday_calendar': _fmt_holiday_calendar,
    'daily_word': _fmt_daily_word,
    'history_programmer': _fmt_programmer,
    'history_programmer_today': _fmt_programmer,
    'network_myip': _fmt_ip,
    'network_ipinfo': _fmt_ip,
    'network_pingmyip': _fmt_ip,
    'translate_text': _fmt_translate,
    'saying': _fmt_saying,
    'saying_random': _fmt_saying,
    'answerbook_ask': _fmt_kv_wrapper('answer', '🔮 '),
    'random_string': _fmt_kv_wrapper('result', '🎲 '),
    'misc_randomnumber': _fmt_kv_wrapper('result', '🎲 随机数：'),
    'text_md5': _fmt_kv_wrapper('md5', '🔑 MD5：'),
    'text_md5_post': _fmt_kv_wrapper('md5', '🔑 MD5：'),
    'text_base64_encode': _fmt_kv_wrapper('encoded', '🔐 Base64：'),
    'text_base64_decode': _fmt_kv_wrapper('decoded', '🔓 解码：'),
    'github_repo': _fmt_github_repo,
    'game_epic_free': _fmt_epic_free,
    'dictionary_lookup': _fmt_kv_wrapper('translation', '📖 '),
    'misc_tracking_detect': _fmt_kv_wrapper('carrier_name', '📦 该单号快递公司：'),
}

# V10.11.52 格式化器中文说明：供「新增平台 API」编辑模态下拉展示（键（说明）形式）
# 未在此登记的键在前端按「（未说明）」兜底显示
FORMATTER_LABELS = {
    'misc_worldtime': '世界时间：转目标时区中文时刻',
    'misc_lunartime': '农历时间：转农历/干支/生肖',
    'misc_weather': '查询天气：温度/湿度/风向中文摘要',
    'misc_weather_history': '历史天气：同天气摘要',
    'misc_hotboard': '热榜：取榜首平台与第一名标题',
    'misc_phoneinfo': '手机归属地：省市区/运营商摘要',
    'misc_date_diff': '日期差值：转相差天数中文',
    'convert_unixtime': '时间戳转换：转日期时间',
    'misc_timestamp': '时间戳转换（旧版）：转日期时间',
    'misc_holiday_calendar': '节假日万年历：节日/班休摘要',
    'daily_word': '每日单词：单词与释义',
    'history_programmer': '程序员历史事件：事件摘要',
    'history_programmer_today': '程序员历史上的今天：事件摘要',
    'network_myip': '我的 IP：IP 与归属地摘要',
    'network_ipinfo': 'IP 信息：IP 与归属地摘要',
    'network_pingmyip': 'Ping IP：IP 摘要',
    'translate_text': '翻译：译文摘要',
    'saying': '一言：名句文本',
    'saying_random': '一言（随机/每日/场景）：名句文本',
    'answerbook_ask': '答案之书：答案文本',
    'random_string': '随机字符串：生成结果',
    'misc_randomnumber': '随机数：生成结果',
    'text_md5': 'MD5 哈希：哈希值',
    'text_md5_post': 'MD5 哈希（POST）：哈希值',
    'text_base64_encode': 'Base64 编码：编码结果',
    'text_base64_decode': 'Base64 解码：解码结果',
    'github_repo': 'GitHub 仓库：星标/语言/简介摘要',
    'game_epic_free': 'Epic 免费游戏：游戏名与领取期限',
    'dictionary_lookup': '单词查询：释义摘要',
    'misc_tracking_detect': '快递公司识别：公司名称',
}


def format_uapi_result(api_id, payload):
    """响应美化：把常用 API 的 JSON 响应转为人类可读中文摘要
    返回格式化文本；未注册格式化器或字段不匹配返回 None（前端回落原始 JSON 展示）"""
    if not isinstance(payload, dict):
        return None
    fn = FORMATTERS.get(api_id)
    if not fn:
        return None
    try:
        text = str(fn(payload) or '').strip()
        return text or None
    except Exception:
        return None


# ===================== 每日一言解析器与业务便捷函数 =====================

def parse_saying_payload(raw_text, json_obj=None):
    """通用一言/名句响应自适应解析引擎（兼容器容各类开放 API 与自建服务）：
    - 兼容 Hitokoto (hitokoto, from, from_who)
    - 兼容 UApiPro / 多数通用聚合 API (text)
    - 兼容 今日诗词 / 韩小韩 (data.content / content, origin/author)
    - 兼容 英文 Quotable / 句子 API (quote, author)
    - 兼容 纯文本 text/plain
    返回 {'text': str, 'source': str, 'provider': str}"""
    import json
    if json_obj is None and raw_text:
        try:
            json_obj = json.loads(raw_text)
        except Exception:
            pass

    text = ''
    source = ''

    if isinstance(json_obj, dict):
        inner = json_obj.get('data') or json_obj.get('result') or json_obj
        if not isinstance(inner, dict):
            if isinstance(inner, str):
                text = inner.strip()
            inner = json_obj

        # 候选文本字段
        candidates = ['hitokoto', 'text', 'content', 'saying', 'sentence', 'quote', 'msg', 'word']
        for k in candidates:
            val = inner.get(k)
            if isinstance(val, str) and val.strip():
                text = val.strip()
                break

        # 候选来源字段
        src_candidates = ['from', 'origin', 'source', 'from_who', 'author', 'creator']
        for sk in src_candidates:
            sval = inner.get(sk)
            if isinstance(sval, str) and sval.strip():
                source = sval.strip()
                break

        # 若命中多项出处（如 Hitokoto 出处与作者），智能拼接
        if inner.get('from_who') and inner.get('from') and inner.get('from_who') != inner.get('from'):
            source = f"{inner['from_who']} · 《{inner['from']}》"
    elif isinstance(json_obj, list) and json_obj and isinstance(json_obj[0], (str, dict)):
        item = json_obj[0]
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            return parse_saying_payload('', json_obj=item)
    elif isinstance(raw_text, str) and raw_text.strip():
        t = raw_text.strip().strip('\"\'')
        if 2 <= len(t) <= 300:
            text = t

    return {'text': text, 'source': source}


def get_daily_saying(force=False):
    """每日一言（多端点故障转移 + 进程级缓存 1 小时，全站共享）：
    登录页与首页横幅装饰位共用。
    - 优先读取 service_config.get_urls('saying') 启用的端点列表（支持直连端点与平台端点混排）
    - 端点依次遍历重试，自适应解析各类响应格式
    - 成功返回 {'text': str, 'source': str, 'provider': str}；失败回落历史缓存或静默降级 None"""
    if not force:
        cached = _cache_get('saying')
        if cached is not None:
            return cached

    from services import service_config
    endpoints = [u for u in service_config.get_urls('saying') if u.get('enabled')]
    timeout = service_config.get_timeout('saying')
    retries = service_config.get_retries('saying')

    # 若未配置或全部停用，返回 None 触发静默隐藏
    if not endpoints:
        return None

    # 多轮重试 + 有序端点故障转移
    for attempt in range(max(1, retries + 1)):
        for ep in endpoints:
            url = str(ep.get('url') or '').strip()
            platform = str(ep.get('platform') or '').strip()
            if not url:
                continue

            try:
                if platform:
                    # 走平台端点（带 Key 轮换与平台鉴权）
                    ok, payload, status, msg = call_uapi(
                        'saying', timeout=(5, max(timeout, 8)), full_url=url, platform_id=platform)
                    if ok and payload:
                        parsed = parse_saying_payload('', json_obj=payload)
                        if parsed.get('text'):
                            plat_obj = service_config.get_platform(platform)
                            pname = (plat_obj or {}).get('name') or platform
                            result = {
                                'text': parsed['text'],
                                'source': parsed.get('source') or '',
                                'provider': pname
                            }
                            _cache_put('saying', result, _CACHE_TTLS['saying'])
                            return result
                else:
                    # 走直连端点（无认证，双路径直连网络）
                    resp = service_config._http_get_dual(url, timeout=timeout)
                    if resp and resp.status_code == 200:
                        parsed = parse_saying_payload(resp.text)
                        if parsed.get('text'):
                            # 提取域名作为 provider
                            import urllib.parse
                            domain = urllib.parse.urlparse(url).netloc or '外部接口'
                            result = {
                                'text': parsed['text'],
                                'source': parsed.get('source') or '',
                                'provider': domain
                            }
                            _cache_put('saying', result, _CACHE_TTLS['saying'])
                            return result
            except Exception:
                continue

    # 接口拉取失败时尝试用过期缓存兜底
    return _cache_get('saying')


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
