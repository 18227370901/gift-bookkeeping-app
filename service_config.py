# -*- coding: utf-8 -*-
"""
service_config.py — 外部接口服务配置管理（V10.11.20 新增）

集中管理各模块「内置默认调用地址但页面无配置入口」的外部服务：
  1. 天气·地理编码（Open-Meteo Geocoding）
  2. 天气·天气预报（Open-Meteo Forecast）
  3. 天气·空气质量（Open-Meteo Air Quality）
  4. 法定节假日班/休数据（timor.tech，地址变量自动补全）
  5. 企微长连接（wss://openws.work.weixin.qq.com）
  6. AI 联网搜索（DuckDuckGo，多端点 + 总开关）

统一模型：每组 = 有序端点列表 [{url, enabled}] + 重试参数（timeout 秒 / retries 轮）。
  - 故障转移：按序遍历启用端点，任一成功即返回；全败按 retries 整轮重试
  - 存储：复用 system_settings 表（key 见 _url_key/_timeout_key/_retries_key），
    实时读库（后台巡检线程每轮独立 app_context，安全），异常兜底返回默认值
  - 节假日地址：管理员只填到 .../year/ 即可，保存时自动补全 {年份} 占位符，
    调用时由业务方 replace 注入最新年份
  - 测试：test_endpoint / test_group 按各组真实协议做结构校验，供「一键测试」使用
"""
import json
import time

# ===================== 分组默认配置 =====================
# defaults 为默认端点列表；timeout/retries 为默认重试参数
DEFAULT_GROUPS = {
    'geocoding': {
        'label': '天气·地理编码',
        'defaults': [{'url': 'https://geocoding-api.open-meteo.com/v1/search', 'enabled': True}],
        'timeout': 8,
        'retries': 0,
    },
    'forecast': {
        'label': '天气·天气预报',
        'defaults': [{'url': 'https://api.open-meteo.com/v1/forecast', 'enabled': True}],
        'timeout': 8,
        'retries': 0,
    },
    'air_quality': {
        'label': '天气·空气质量',
        'defaults': [{'url': 'https://air-quality-api.open-meteo.com/v1/air-quality', 'enabled': True}],
        'timeout': 8,
        'retries': 0,
    },
    'holiday': {
        'label': '法定节假日',
        'defaults': [{'url': 'https://timor.tech/api/holiday/year/', 'enabled': True}],
        'timeout': 8,
        'retries': 0,
    },
    'wecom_ws': {
        'label': '企微长连接',
        'defaults': [{'url': 'wss://openws.work.weixin.qq.com', 'enabled': True}],
        'timeout': 10,
        'retries': 0,
    },
    'ai_search': {
        'label': 'AI 联网搜索',
        'defaults': [{'url': 'https://duckduckgo.com', 'enabled': True}],
        'timeout': 8,
        'retries': 0,
    },
}

# 节假日地址占位符（管理员无需填写，保存时自动补全）
HOLIDAY_PLACEHOLDER = '{年份}'

AI_SEARCH_ENABLED_KEY = 'ai_search_enabled'


# ===================== 存储 key =====================

def _url_key(group):
    return 'api_urls_' + group


def _timeout_key(group):
    return 'api_urls_' + group + '_timeout'


def _retries_key(group):
    return 'api_urls_' + group + '_retries'


# ===================== 读取配置 =====================

def _get_setting(key, default=None):
    """读 system_settings（无 app context / 读失败时兜底默认值，保证后台线程安全）"""
    try:
        from models import SystemSetting
        return SystemSetting.get_val(key, default)
    except Exception:
        return default


def _set_setting(key, value):
    """写 system_settings（异常静默，配置写失败不阻断主流程）"""
    try:
        from models import SystemSetting
        SystemSetting.set_val(key, value)
    except Exception:
        pass


def normalize_holiday_url(url):
    """节假日地址规范化：自动补全 {年份} 占位符（剥掉已填占位符后统一追加到末尾）
    例：https://timor.tech/api/holiday/year/      → https://timor.tech/api/holiday/year/{年份}
        https://timor.tech/api/holiday/year/{年份} → https://timor.tech/api/holiday/year/{年份}
    """
    s = (url or '').strip()
    if not s:
        s = DEFAULT_GROUPS['holiday']['defaults'][0]['url']
    # 剥掉已填写的占位符与尾部斜杠
    s = s.replace('{年份}', '').replace('{year}', '')
    s = s.rstrip('/')
    return s + '/' + HOLIDAY_PLACEHOLDER


def display_holiday_url(url):
    """页面展示用：隐藏 {年份} 占位符，只展示管理员需要编辑的地址"""
    return (url or '').replace(HOLIDAY_PLACEHOLDER, '')


def get_urls(group):
    """返回 [{url, enabled}]；库中无有效配置时回落该组默认列表"""
    default = [dict(x) for x in DEFAULT_GROUPS[group]['defaults']]
    raw = _get_setting(_url_key(group), None)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                out = []
                for item in parsed:
                    if isinstance(item, dict) and str(item.get('url', '')).strip():
                        out.append({
                            'url': str(item['url']).strip(),
                            'enabled': bool(item.get('enabled', True)),
                        })
                if out:
                    return out
        except Exception:
            pass
    return default


def get_timeout(group):
    """读取该组请求超时（秒），非法回落默认"""
    raw = _get_setting(_timeout_key(group), None)
    try:
        v = int(float(raw))
        return max(1, min(60, v))
    except Exception:
        return DEFAULT_GROUPS[group]['timeout']


def get_retries(group):
    """读取该组重试轮数，非法回落默认"""
    raw = _get_setting(_retries_key(group), None)
    try:
        v = int(float(raw))
        return max(0, min(10, v))
    except Exception:
        return DEFAULT_GROUPS[group]['retries']


def get_enabled_urls(group):
    """按配置顺序返回启用的端点 URL 列表（故障转移遍历用）"""
    return [u['url'] for u in get_urls(group) if u.get('enabled')]


def get_ai_search_enabled():
    """AI 联网搜索总开关（默认开启）"""
    raw = _get_setting(AI_SEARCH_ENABLED_KEY, '1')
    return str(raw).strip() not in ('', '0', 'false', 'False')


# ===================== 保存配置 =====================

def save_group_config(group, urls, timeout=None, retries=None, ai_search_enabled=None):
    """保存一组配置。urls: [{url, enabled}]（保存前由调用方完成规范化与校验）；
    urls 为 None 时仅更新重试参数/开关（不覆盖端点列表）"""
    if urls is not None:
        _set_setting(_url_key(group), json.dumps(urls, ensure_ascii=False))
    if timeout is not None:
        _set_setting(_timeout_key(group), str(int(timeout)))
    if retries is not None:
        _set_setting(_retries_key(group), str(int(retries)))
    if ai_search_enabled is not None and group == 'ai_search':
        _set_setting(AI_SEARCH_ENABLED_KEY, '1' if ai_search_enabled else '0')


def clear_group(group):
    """删除该组全部配置 key（读取时自动回落默认值）"""
    try:
        from models import SystemSetting, db
        for key in (_url_key(group), _timeout_key(group), _retries_key(group)):
            s = SystemSetting.query.filter_by(key=key).first()
            if s:
                db.session.delete(s)
        db.session.commit()
    except Exception:
        pass


def restore_all_defaults():
    """恢复全部组默认（删除所有 api_urls_* 配置）"""
    for group in DEFAULT_GROUPS:
        clear_group(group)
    _set_setting(AI_SEARCH_ENABLED_KEY, '1')


def get_all_config():
    """供配置页面渲染：{group: {label, urls, timeout, retries, default_urls}} + ai_search_enabled"""
    result = {}
    for group, meta in DEFAULT_GROUPS.items():
        urls = get_urls(group)
        if group == 'holiday':
            # 页面展示隐藏 {年份} 占位符（管理员只需编辑 year/ 部分）
            urls = [{'url': display_holiday_url(u['url']), 'enabled': u['enabled']} for u in urls]
        result[group] = {
            'label': meta['label'],
            'urls': urls,
            'timeout': get_timeout(group),
            'retries': get_retries(group),
            'defaults': meta['defaults'],
        }
    return {
        'groups': result,
        'ai_search_enabled': get_ai_search_enabled(),
    }


# ===================== 一键测试执行器 =====================

def _http_get_dual(url, params=None, timeout=8, headers=None):
    """禁代理直连优先 + 系统代理兜底（与 weather_service._http_get 同款双路径）"""
    import requests
    try:
        with requests.Session() as s:
            s.trust_env = False
            return s.get(url, params=params, timeout=timeout, headers=headers)
    except Exception:
        pass
    with requests.Session() as s:
        s.trust_env = True
        return s.get(url, params=params, timeout=timeout, headers=headers)


def test_endpoint(group, url, timeout=None):
    """测试单个端点地址是否有效，返回 {url, ok, message, latency_ms}
    按各组真实协议做结构校验（非仅 HTTP 200）"""
    if timeout is None:
        timeout = get_timeout(group)
    url = (url or '').strip()
    start = time.time()

    # 企微长连接：WebSocket 握手连通测试（不做机器人鉴权）
    if group == 'wecom_ws':
        return _test_ws_endpoint(url, timeout, start)

    # AI 联网搜索：DuckDuckGo 兼容端点解析测试
    if group == 'ai_search':
        return _test_search_endpoint(url, timeout, start)

    # HTTP 型各组：构造测试请求 + 结构校验
    params = None
    ok_fn = None
    fail_hint = ''
    if group == 'geocoding':
        params = {'name': '北京', 'count': 1, 'language': 'zh', 'format': 'json'}
        ok_fn = lambda d: isinstance(d, dict) and isinstance(d.get('results'), list)
        fail_hint = '响应缺少 results 数组（非 Open-Meteo Geocoding 兼容端点）'
    elif group == 'forecast':
        params = {'latitude': 39.9, 'longitude': 116.4,
                  'current': 'temperature_2m', 'timezone': 'auto'}
        ok_fn = lambda d: isinstance(d, dict) and ('current' in d or 'daily' in d)
        fail_hint = '响应缺少 current/daily 字段（非 Open-Meteo Forecast 兼容端点）'
    elif group == 'air_quality':
        params = {'latitude': 39.9, 'longitude': 116.4, 'current': 'us_aqi', 'timezone': 'auto'}
        ok_fn = lambda d: isinstance(d, dict) and isinstance(d.get('current'), dict)
        fail_hint = '响应缺少 current 字段（非 Open-Meteo Air Quality 兼容端点）'
    elif group == 'holiday':
        target = normalize_holiday_url(url).replace(HOLIDAY_PLACEHOLDER, str(time.localtime().tm_year))
        url = target
        ok_fn = lambda d: isinstance(d, dict) and d.get('code') == 0
        fail_hint = '响应缺少 code==0 字段（非 timor.tech 兼容端点）'
    else:
        return {'url': url, 'ok': False, 'message': '未知分组: %s' % group, 'latency_ms': int((time.time() - start) * 1000)}

    try:
        # timor.tech 反爬：必须模拟浏览器 UA（否则 403）
        headers = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                                  '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'),
                   'Accept': 'application/json'} if group == 'holiday' else None
        resp = _http_get_dual(url, params=params, timeout=timeout, headers=headers)
        latency_ms = int((time.time() - start) * 1000)
        try:
            data = resp.json()
        except ValueError:
            return {'url': url, 'ok': False, 'message': '响应非有效 JSON（HTTP %s）' % resp.status_code, 'latency_ms': latency_ms}
        if ok_fn(data):
            return {'url': url, 'ok': True, 'message': '连接正常（HTTP %s）' % resp.status_code, 'latency_ms': latency_ms}
        # Open-Meteo 风格错误：{"error": true, "reason": ...}
        reason = ''
        if isinstance(data, dict) and data.get('error'):
            reason = '：' + str(data.get('reason') or '接口返回错误')
        return {'url': url, 'ok': False, 'message': fail_hint + reason, 'latency_ms': latency_ms}
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return {'url': url, 'ok': False, 'message': '请求失败: %s' % str(e)[:200], 'latency_ms': latency_ms}


def _test_ws_endpoint(url, timeout, start):
    """WebSocket 握手连通测试"""
    if not (url.startswith('wss://') or url.startswith('ws://')):
        return {'url': url, 'ok': False, 'message': '地址必须以 wss:// 或 ws:// 开头', 'latency_ms': int((time.time() - start) * 1000)}
    try:
        import asyncio
        import websockets

        async def _handshake():
            async with websockets.connect(url, open_timeout=timeout, close_timeout=5) as _ws:
                return True

        asyncio.run(_handshake())
        return {'url': url, 'ok': True, 'message': 'WebSocket 握手成功', 'latency_ms': int((time.time() - start) * 1000)}
    except Exception as e:
        return {'url': url, 'ok': False, 'message': '连接失败: %s' % str(e)[:200], 'latency_ms': int((time.time() - start) * 1000)}


def _test_search_endpoint(url, timeout, start):
    """DuckDuckGo 兼容端点搜索测试（GET {url}?q=测试 + 结果解析）"""
    if not (url.startswith('http://') or url.startswith('https://')):
        return {'url': url, 'ok': False, 'message': '地址需以 http:// 或 https:// 开头', 'latency_ms': int((time.time() - start) * 1000)}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36'}
    try:
        import requests
        with requests.Session() as s:
            s.trust_env = False
            resp = s.get(url, params={'q': '测试天气'}, headers=headers, timeout=timeout)
        latency_ms = int((time.time() - start) * 1000)
        text = resp.text or ''
        if resp.status_code != 200:
            return {'url': url, 'ok': False, 'message': 'HTTP %d' % resp.status_code, 'latency_ms': latency_ms}
        if 'result__a' in text or 'result__snippet' in text or '<a' in text and len(text) > 200:
            return {'url': url, 'ok': True, 'message': '端点可达且返回正常内容（%d 字节）' % len(text), 'latency_ms': latency_ms}
        return {'url': url, 'ok': False, 'message': 'HTTP 200 但未解析出搜索结果结构（可能非 DuckDuckGo 兼容端点）', 'latency_ms': latency_ms}
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return {'url': url, 'ok': False, 'message': '请求失败: %s' % str(e)[:200], 'latency_ms': latency_ms}


def test_group(group, urls, timeout=None, retries=None):
    """按当前配置顺序与启用状态测试整组端点（模拟故障转移顺序），返回逐条结果"""
    if timeout is None:
        timeout = get_timeout(group)
    if retries is None:
        retries = get_retries(group)
    results = []
    for item in urls or []:
        if not isinstance(item, dict):
            continue
        if not item.get('enabled'):
            continue
        results.append(test_endpoint(group, item.get('url', ''), timeout=timeout))
    return results