# -*- coding: utf-8 -*-
"""
service_config.py — 外部接口服务配置管理（V10.11.20 新增，V10.11.47 平台化升级）

集中管理各模块「内置默认调用地址但页面无配置入口」的外部服务：
  1. 天气·地理编码（Open-Meteo Geocoding）
  2. 天气·天气预报（Open-Meteo Forecast / UApiPro 查询天气 双协议）
  3. 天气·空气质量（Open-Meteo Air Quality）
  4. 法定节假日班/休数据（timor.tech / UApiPro 节假日万年历 双协议）
  5. 企微长连接（wss://openws.work.weixin.qq.com）
  6. AI 联网搜索（DuckDuckGo，多端点 + 总开关）

统一模型：每组 = 有序端点列表 [{url, enabled, platform}] + 重试参数（timeout 秒 / retries 轮）。
  - 故障转移：按序遍历启用端点，任一成功即返回；全败按 retries 整轮重试
  - 存储：复用 system_settings 表（key 见 _url_key/_timeout_key/_retries_key），
    实时读库（后台巡检线程每轮独立 app_context，安全），异常兑底返回默认值
  - 节假日地址：管理员只填到 .../year/ 即可，保存时自动补全 {年份} 占位符，
    调用时由业务方 replace 注入最新年份
  - 测试：test_endpoint / test_group 按各组真实协议做结构校验，供「一键测试」使用

V10.11.47 平台化升级（多平台 API 接入，首接 UApiPro uapis.cn）：
  - 端点记录新增可选 platform 字段：空 = 无认证直连（与旧版行为完全一致）；
    'uapis' = UApiPro 平台端点，调用时自动附加平台级认证头（Bearer Key）
  - 新增「API 平台」注册表（api_platforms）：平台级一份 API Key 集中管理，
    支持四种认证方式 none/bearer/header/query；内置 UApiPro 默认档案（访客模式可免 Key）
  - 天气/节假日组内可混排两种协议端点，按端点顺序自动分发对应适配器
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
    'saying': {
        'label': '每日一言',
        'defaults': [
            {'url': 'https://v1.hitokoto.cn', 'enabled': True, 'platform': ''},
            {'url': 'https://uapis.cn/api/v1/saying', 'enabled': True, 'platform': 'uapis'},
        ],
        'timeout': 5,
        'retries': 1,
    },
}

# 节假日地址占位符（管理员无需填写，保存时自动补全）
HOLIDAY_PLACEHOLDER = '{年份}'

AI_SEARCH_ENABLED_KEY = 'ai_search_enabled'

# ===================== V10.11.47/48 API 平台注册表 =====================
# 多平台多 Key 架构：平台注册表支持任意多平台并存，每平台一个有序 Key 池。
# Key 池按序轮换：调用时依次尝试，401（Key 无效）/402（额度不足）/访客额度耗尽自动切换下一个 Key，
# 全部 Key 失败才返回错误；Key 行支持上移/下移/启停/测试（前端与端点行同构交互）。
# 存储：system_settings 表 'api_platforms' 键，JSON 列表：
#   [{id, name, base_url, auth_type, auth_key_name, api_keys: [{key, label, enabled}], enabled}]
# 认证方式 auth_type：none=无认证 | bearer=Authorization: Bearer <key>（UApiPro）| header=自定义头（auth_key_name 为头名）| query=URL 参数（auth_key_name 为参数名）

PLATFORMS_KEY = 'api_platforms'

# 内置默认平台档案（库中无配置时自动生效；UApiPro 支持「访客模式」：Key 池为空也可调用，按 IP 月 1500 积分/4QPS）
DEFAULT_PLATFORMS = [
    {
        'id': 'uapis',
        'name': 'UApiPro 聚合 API 平台 (uapis.cn)',
        'base_url': 'https://uapis.cn/api/v1',
        'auth_type': 'bearer',
        'auth_key_name': '',
        'api_keys': [],        # Key 池（空 = 访客模式）
        'enabled': True,
        'builtin': True,      # 内置平台不可删除
    },
]

# 支持的认证方式（前端下拉 + 后端白名单校验）
AUTH_TYPES = ('none', 'bearer', 'header', 'query')
# 端点可绑定的平台 ID 白名单（当前内置平台；自定义平台由管理员动态添加）
KNOWN_PLATFORM_IDS = ('uapis',)
# 单平台 Key 池上限（防误粘贴巨量行）
MAX_KEYS_PER_PLATFORM = 10
# V10.11.51 单平台自定义/导入 API 上限与字段长度限制（防超大 JSON 撑库）
MAX_APIS_PER_PLATFORM = 200
MAX_API_PATH_LEN = 500
MAX_API_DESC_LEN = 500
MAX_API_PARAMS = 40


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
        from services.models import SystemSetting
        return SystemSetting.get_val(key, default)
    except Exception:
        return default


def _set_setting(key, value):
    """写 system_settings（异常静默，配置写失败不阻断主流程）"""
    try:
        from services.models import SystemSetting
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
    """返回 [{url, enabled, platform}]；库中无有效配置时回落该组默认列表
    V10.11.47：端点记录新增可选 platform 字段——空 = 无认证直连（与旧版完全一致），
    'uapis' = UApiPro 平台端点（调用时自动附加平台认证头，按平台协议解析）。
    老数据无 platform 字段自动补空串，零迁移。"""
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
                            'platform': str(item.get('platform', '') or '').strip(),
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
    """按配置顺序返回启用的「无认证直连」端点 URL 列表（传统协议故障转移遍历用）
    V10.11.47：排除 platform 非空的平台端点——平台端点按各自协议由业务适配器
    单独消费（如 weather_service 的 UApiPro 适配器），不参与传统协议遍历。"""
    return [u['url'] for u in get_urls(group) if u.get('enabled') and not u.get('platform')]


def get_enabled_endpoints(group):
    """V10.11.47 新增：返回该组全部启用端点 [{url, enabled, platform}]（含平台端点）
    业务适配器按端点顺序混排分发协议时使用"""
    return [u for u in get_urls(group) if u.get('enabled')]


def get_enabled_platform_endpoints(group):
    """V10.11.48 新增：返回该组启用的「平台端点」[(url, platform_id)]（任意平台，按序）
    V10.11.47 仅支持 uapis；多平台升级后自定义平台端点同样返回（协议解析均按 UApiPro 兼容适配器）"""
    return [(u['url'], u.get('platform', '')) for u in get_urls(group)
            if u.get('enabled') and u.get('platform')]


def get_enabled_uapi_endpoints(group):
    """V10.11.47：返回该组启用的 UApiPro 平台端点 URL 列表（故障转移遍历用）
    V10.11.48 多平台升级：保留向后兼容（仅 uapis 平台），新调用方建议改用
    get_enabled_platform_endpoints（返回 url+platform_id 元组列表）"""
    return [u['url'] for u in get_urls(group) if u.get('enabled') and u.get('platform')]


def get_first_enabled_platform(group):
    """V10.11.47 新增：返回该组第一个启用端点的 platform（空串 = 传统直连优先；
    'uapis' = UApiPro 平台协议优先）。组内无任何启用端点返回 None。"""
    for u in get_urls(group):
        if u.get('enabled'):
            return u.get('platform', '') or ''
    return None


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
        from services.models import SystemSetting, db
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
            urls = [{'url': display_holiday_url(u['url']), 'enabled': u['enabled'],
                     'platform': u.get('platform', '')} for u in urls]
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


def test_endpoint(group, url, timeout=None, platform=''):
    """测试单个端点地址是否有效，返回 {url, ok, message, latency_ms}
    按各组真实协议做结构校验（非仅 HTTP 200）
    V10.11.47：platform 非空时按对应平台协议测试（组绑定的目录 API 真实调用）"""
    if timeout is None:
        timeout = get_timeout(group)
    url = (url or '').strip()
    start = time.time()

    # V10.11.47 平台端点：按组绑定的 UApiPro 目录 API 真实调用并校验响应结构
    if platform:
        return _test_platform_endpoint(group, url, timeout, platform, start)

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
    elif group == 'saying':
        params = {}
        ok_fn = lambda d: True
        fail_hint = '未能解析出一言名句文本'
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
        if group == 'saying':
            from services.uapi_client import parse_saying_payload
            parsed = parse_saying_payload(resp.text, json_obj=data if isinstance(data, (dict, list)) else None)
            if parsed and parsed.get('text'):
                txt = parsed['text']
                disp = (txt[:24] + '...') if len(txt) > 24 else txt
                src = (' —— ' + parsed['source']) if parsed.get('source') else ''
                return {'url': url, 'ok': True, 'message': '解析成功：“%s”%s（HTTP %s）' % (disp, src, resp.status_code), 'latency_ms': latency_ms}
            return {'url': url, 'ok': False, 'message': 'HTTP %s 但未能从响应中提取出名句内容（建议检查响应格式）' % resp.status_code, 'latency_ms': latency_ms}
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


def _test_platform_endpoint(group, url, timeout, platform, start):
    """V10.11.47/48 平台端点测试：按组绑定的目录 API 真实调用 + 响应结构校验
    - forecast 组 → 查询天气（city=Shanghai 英文名）：校验 weather/temperature 字段
    - holiday 组 → 节假日万年历（date=今天）：校验 days/holidays 字段
    - 平台 id 按端点绑定分发（认证从对应平台 Key 池注入）
    - 未绑定平台 API 的组（geocoding/air_quality/wecom_ws/ai_search）：明确不支持"""
    def _res(ok, message):
        return {'url': url, 'ok': ok, 'message': message,
                'latency_ms': int((time.time() - start) * 1000)}

    # 延迟导入避免循环依赖（uapi_client 依赖 service_config 平台认证）
    from services import uapi_catalog
    api = uapi_catalog.get_group_api(group)
    if not api:
        return _res(False, '该组未绑定平台 API（%s 组不支持平台端点，请使用无认证直连端点）' % group)

    from services import uapi_client
    import time as _t
    params = dict(uapi_catalog.resolve_test_params(api))
    if group == 'forecast':
        # V10.11.48：worldtime 教训——城市名用英文（避免 TIMEZONE_NOT_FOUND 类问题）
        params.update({'city': 'Shanghai', 'extended': 'true'})
    elif group == 'holiday':
        params = {'date': '%04d-%02d-%02d' % (_t.localtime().tm_year, _t.localtime().tm_mon, _t.localtime().tm_mday)}

    ok, payload, status, message = uapi_client.call_uapi(
        api['id'], params=params, timeout=max(timeout, 8),
        full_url=url or None, platform_id=platform or None)
    if not ok or not isinstance(payload, dict):
        return _res(False, 'HTTP %s：%s' % (status, message or '平台接口调用失败')[:200])
    if group == 'forecast':
        if 'weather' in payload and 'temperature' in payload:
            city = payload.get('city') or ''
            return _res(True, '平台天气协议正常（%s：%s %s°C，HTTP %s）' % (
                city, payload.get('weather', ''), payload.get('temperature'), status))
        return _res(False, '响应缺少 weather/temperature 字段（非 UApiPro 天气兼容端点）')
    if group == 'holiday':
        if isinstance(payload.get('days'), list) or isinstance(payload.get('holidays'), list):
            day0 = (payload.get('days') or [{}])[0] or {}
            hm = day0.get('weekday_cn') or day0.get('date') or ''
            return _res(True, '平台万年历协议正常（%s，HTTP %s）' % (hm, status))
        return _res(False, '响应缺少 days/holidays 字段（非 UApiPro 万年历兼容端点）')
    if group == 'saying':
        from services.uapi_client import parse_saying_payload
        parsed = parse_saying_payload('', json_obj=payload)
        if parsed and parsed.get('text'):
            txt = parsed['text']
            disp = (txt[:24] + '...') if len(txt) > 24 else txt
            return _res(True, '平台一言协议正常：“%s”（HTTP %s）' % (disp, status))
        return _res(False, '平台响应未能提取出名句文本（非 UApiPro 一言兼容端点）')
    return _res(True, '平台接口调用成功（HTTP %s）' % status)


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
    """按当前配置顺序与启用状态测试整组端点（模拟故障转移顺序），返回逐条结果
    V10.11.47：urls 项可携带 platform 字段，平台端点按对应平台协议测试"""
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
        results.append(test_endpoint(group, item.get('url', ''),
                                     timeout=timeout, platform=str(item.get('platform', '') or '')))
    return results


# ===================== V10.11.47/48 API 平台注册表 =====================

def _normalize_key_pool(raw_keys):
    """Key 池规范化：[{key, label, enabled, uid}] 列表清洗
    - uid：每 Key 唯一标识（新 Key 自动生成；前端「保持原值」提交 key='__KEEP__' + uid，
      由 save_platform 按 uid 回填明文，明文不出库不回传）
    - 空 Key 行剔除、label/enabled 补默认、限长上限（MAX_KEYS_PER_PLATFORM）"""
    import uuid as _uuid
    pool = []
    if not isinstance(raw_keys, list):
        return pool
    for item in raw_keys:
        if isinstance(item, dict):
            k = str(item.get('key') or '').strip()
            if not k:
                continue
            rec = {
                'key': k,
                'label': str(item.get('label') or 'Key %d' % (len(pool) + 1))[:30],
                'enabled': bool(item.get('enabled', True)),
                'uid': str(item.get('uid') or '')[:40] or _uuid.uuid4().hex[:12],
            }
            pool.append(rec)
        elif isinstance(item, str) and item.strip():
            # V10.11.47 旧格式：纯字符串 Key 列表
            pool.append({'key': item.strip(), 'label': 'Key %d' % (len(pool) + 1),
                         'enabled': True, 'uid': _uuid.uuid4().hex[:12]})
        if len(pool) >= MAX_KEYS_PER_PLATFORM:
            break
    return pool


# ===================== V10.11.51 平台 API 目录（自定义 / OpenAPI 导入） =====================
# 存储：平台档案内嵌 apis 数组（与平台同生命周期，删除平台自动清理）。
# 用途：管理员为任意平台补充官方目录之外的接口；内置 uapis 的 apis 作为「扩展条目」
# 与静态 110 条目录合并展示。调用链路见 uapi_client.resolve_api_def / call_platform_api。
# 安全：path 仅允许站内相对路径（禁止协议、反斜杠、上跳），调用时二次校验 origin 防 SSRF。

API_METHODS = ('GET', 'POST', 'PUT', 'DELETE', 'PATCH')
API_PARAM_TYPES = ('text', 'number', 'bool', 'select', 'date', 'datetime')


def _api_error(msg):
    return False, msg


def _validate_api_entry(item):
    """校验单条平台 API 定义，返回 (ok, err)"""
    import re as _re
    if not isinstance(item, dict):
        return _api_error('API 记录格式不正确')
    name = str(item.get('name') or '').strip()
    if not name:
        return _api_error('API 名称不能为空')
    if len(name) > 50:
        return _api_error('API 名称最多 50 字')
    method = str(item.get('method') or 'GET').strip().upper()
    if method not in API_METHODS:
        return _api_error('请求方法非法（仅支持 %s）' % '/'.join(API_METHODS))
    path = str(item.get('path') or '').strip()
    if not path:
        return _api_error('接口路径不能为空')
    if len(path) > MAX_API_PATH_LEN:
        return _api_error('接口路径最多 %d 字符' % MAX_API_PATH_LEN)
    if not _re.fullmatch(r'^/[A-Za-z0-9_\-./{}]*$', path):
        return _api_error('接口路径必须以 / 开头，仅允许字母/数字/下划线/连字符/点/斜杠/花括号占位符')
    if '..' in path or '//' in path or '\\' in path:
        return _api_error('接口路径不能包含 ..、// 或反斜杠')
    desc = str(item.get('desc') or '').strip()
    if len(desc) > MAX_API_DESC_LEN:
        return _api_error('接口说明最多 %d 字' % MAX_API_DESC_LEN)
    params = item.get('params')
    if params is not None and not isinstance(params, list):
        return _api_error('参数定义格式不正确')
    if isinstance(params, list):
        if len(params) > MAX_API_PARAMS:
            return _api_error('参数最多 %d 个' % MAX_API_PARAMS)
        seen = set()
        for p in params:
            if not isinstance(p, dict):
                return _api_error('参数项格式不正确')
            pname = str(p.get('name') or '').strip()
            if not pname:
                return _api_error('参数名不能为空')
            if not _re.fullmatch(r'^[A-Za-z_][A-Za-z0-9_.\-]{0,49}$', pname):
                return _api_error('参数名「%s」不合法（字母开头，仅字母/数字/下划线/点/连字符）' % pname)
            if pname in seen:
                return _api_error('参数名重复：%s' % pname)
            seen.add(pname)
            ptype = str(p.get('type') or 'text').strip()
            if ptype not in API_PARAM_TYPES:
                return _api_error('参数「%s」类型非法' % pname)
    credits = item.get('credits')
    if credits not in (None, ''):
        try:
            credits = float(credits)
            if credits < 0:
                return _api_error('积分不能为负数')
        except (TypeError, ValueError):
            return _api_error('积分需为数字')
    fmt = str(item.get('formatter') or '').strip()
    if fmt:
        try:
            from services.uapi_client import FORMATTERS
            if fmt not in FORMATTERS:
                return _api_error('格式化器「%s」不存在' % fmt)
        except Exception:
            pass
    return True, ''


def _normalize_api_entry(item, source='manual'):
    """把提交/导入的 API 定义规范化为统一结构（调用前需先 _validate_api_entry）"""
    import uuid as _uuid
    name = str(item.get('name') or '').strip()[:50]
    method = str(item.get('method') or 'GET').strip().upper()
    path = str(item.get('path') or '').strip()
    desc = str(item.get('desc') or '').strip()[:MAX_API_DESC_LEN]
    credits = item.get('credits')
    if credits in (None, ''):
        credits = None
    else:
        try:
            credits = int(float(credits))
        except (TypeError, ValueError):
            credits = None
    params = []
    for p in (item.get('params') or []):
        if not isinstance(p, dict):
            continue
        pname = str(p.get('name') or '').strip()
        if not pname:
            continue
        params.append({
            'name': pname[:50],
            'label': str(p.get('label') or pname)[:60],
            'type': str(p.get('type') or 'text').strip() or 'text',
            'required': bool(p.get('required')),
            'example': str(p.get('example') or '')[:200],
            'options': [str(x)[:60] for x in (p.get('options') or [])][:60],
            'convert': str(p.get('convert') or '').strip(),
        })
    test_params = item.get('test_params') if isinstance(item.get('test_params'), dict) else {}
    test_params = {str(k)[:50]: str(v)[:200] for k, v in test_params.items() if v is not None}
    return {
        'id': str(item.get('id') or ('c' + _uuid.uuid4().hex[:10]))[:60],
        'name': name,
        'method': method,
        'path': path,
        'desc': desc,
        'credits': credits,
        'params': params,
        'test_params': test_params,
        'formatter': str(item.get('formatter') or '').strip()[:60],
        'source': str(item.get('source') or source)[:20],
    }


def _normalize_api_list(raw):
    """读取时的轻量清洗：只保留结构完整的条目，不做严格校验（避免历史脏数据导致整页不可用）"""
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        if not str(item.get('path') or '').strip() or not str(item.get('name') or '').strip():
            continue
        out.append(_normalize_api_entry(item, source=str(item.get('source') or 'manual')))
        if len(out) >= MAX_APIS_PER_PLATFORM:
            break
    return out


def get_platform_apis(pid):
    """返回平台自定义/导入的 API 列表（副本，避免调用方误改缓存）"""
    p = get_platform(pid)
    if not p:
        return []
    return [dict(a) for a in (p.get('apis') or [])]


def get_platform_api(pid, api_id):
    """按平台内 API ID 获取单条定义"""
    for a in get_platform_apis(pid):
        if a['id'] == api_id:
            return a
    return None


def _save_platform_apis(pid, apis):
    """把 API 列表写回平台档案（内部函数）"""
    platforms = get_platforms()
    target = None
    for p in platforms:
        if p['id'] == pid:
            target = p
            break
    if target is None:
        return False
    target['apis'] = apis
    _persist_platforms(platforms)
    return True


def save_platform_api(pid, item, original_id=None):
    """新增或更新一条平台 API（original_id 非空 = 更新该条，否则新增）
    返回 (ok, err, entry)"""
    pid = str(pid or '').strip()
    if not get_platform(pid):
        return False, '平台不存在', None
    ok, err = _validate_api_entry(item)
    if not ok:
        return False, err, None
    entry = _normalize_api_entry(item, source=str(item.get('source') or 'manual'))
    apis = get_platform_apis(pid)
    if original_id:
        idx = next((i for i, a in enumerate(apis) if a['id'] == original_id), -1)
        if idx < 0:
            return False, '原 API 不存在', None
        entry['id'] = original_id
        # 更新时若 method+path 与其他条目冲突则拒绝
        for i, a in enumerate(apis):
            if i != idx and a['method'] == entry['method'] and a['path'] == entry['path']:
                return False, '已存在相同方法与路径的接口：%s %s' % (entry['method'], entry['path']), None
        apis[idx] = entry
    else:
        for a in apis:
            if a['method'] == entry['method'] and a['path'] == entry['path']:
                return False, '已存在相同方法与路径的接口：%s %s' % (entry['method'], entry['path']), None
        if len(apis) >= MAX_APIS_PER_PLATFORM:
            return False, '单平台最多 %d 个自定义接口' % MAX_APIS_PER_PLATFORM, None
        apis.append(entry)
    if not _save_platform_apis(pid, apis):
        return False, '保存失败（平台档案写入异常）', None
    return True, '', entry


def delete_platform_api(pid, api_id):
    """删除一条平台 API，返回 (ok, err)"""
    pid = str(pid or '').strip()
    apis = get_platform_apis(pid)
    remain = [a for a in apis if a['id'] != api_id]
    if len(remain) == len(apis):
        return False, 'API 不存在'
    if not _save_platform_apis(pid, remain):
        return False, '删除失败（平台档案写入异常）'
    return True, ''


def import_platform_apis(pid, items, source='openapi'):
    """批量导入 API（按 method+path 去重），返回 {added, skipped, errors, total}"""
    pid = str(pid or '').strip()
    if not get_platform(pid):
        return {'added': 0, 'skipped': 0, 'errors': ['平台不存在'], 'total': 0}
    apis = get_platform_apis(pid)
    existing = {(a['method'], a['path']) for a in apis}
    added, skipped, errors = 0, 0, []
    batch_keys = set()
    for raw in (items or []):
        if not isinstance(raw, dict):
            skipped += 1
            continue
        ok, err = _validate_api_entry(raw)
        if not ok:
            errors.append('%s %s：%s' % (raw.get('method') or 'GET', raw.get('path') or '?', err))
            continue
        entry = _normalize_api_entry(raw, source=source)
        key = (entry['method'], entry['path'])
        if key in existing or key in batch_keys:
            skipped += 1
            continue
        if len(apis) >= MAX_APIS_PER_PLATFORM:
            errors.append('已达单平台上限 %d 条，其余未导入' % MAX_APIS_PER_PLATFORM)
            break
        apis.append(entry)
        batch_keys.add(key)
        added += 1
    if added:
        _save_platform_apis(pid, apis)
    return {'added': added, 'skipped': skipped, 'errors': errors[:20], 'total': added + skipped + len(errors)}


def reveal_platform_key(pid, uid):
    """读取指定 Key 明文（仅供路由层在管理员二次确认后调用；调用方必须写审计日志）
    返回 {key, label} 或 None"""
    p = get_platform(pid)
    if not p:
        return None
    uid = str(uid or '').strip()
    for k in (p.get('api_keys') or []):
        if str(k.get('uid') or '') == uid and str(k.get('key') or '').strip():
            return {'key': str(k['key']), 'label': str(k.get('label') or '')}
    return None


def get_platforms():
    """读取全部平台档案：库中记录与内置默认档案合并（内置平台缺失项由默认档案补全）
    V10.11.47 旧档案的单一 api_key 字符串自动升级为 Key 池 [{key, label:'默认', enabled:True}]（读取兼容，零迁移）
    返回 [{id, name, base_url, auth_type, auth_key_name, api_keys:[{key,label,enabled}], enabled, builtin}]"""
    raw = _get_setting(PLATFORMS_KEY, None)
    stored = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and str(item.get('id', '')).strip():
                        stored[str(item['id']).strip()] = item
        except Exception:
            pass
    result = []
    for d in DEFAULT_PLATFORMS:
        rec = dict(d)
        rec['api_keys'] = list(d.get('api_keys') or [])
        rec['apis'] = list(d.get('apis') or [])
        s = stored.pop(d['id'], None)
        if isinstance(s, dict):
            for k in ('name', 'base_url', 'auth_type', 'auth_key_name', 'enabled'):
                if k in s:
                    rec[k] = s[k]
            # Key 池：新列表 > 旧单 Key 字符串（升级兼容，同步补 uid 供明文不回传协议使用）
            if isinstance(s.get('api_keys'), list) and s.get('api_keys'):
                rec['api_keys'] = _normalize_key_pool(s.get('api_keys'))
            elif s.get('api_key'):
                _uid = __import__('uuid').uuid4().hex[:12]
                rec['api_keys'] = [{'key': str(s['api_key']), 'label': '默认', 'enabled': True, 'uid': _uid}]
            # V10.11.51 平台 API 目录（自定义/导入条目）
            if isinstance(s.get('apis'), list):
                rec['apis'] = _normalize_api_list(s.get('apis'))
        result.append(rec)
    # 其余自定义平台（非内置）按库中记录原样加入
    for pid, s in stored.items():
        pool = []
        if isinstance(s.get('api_keys'), list):
            pool = _normalize_key_pool(s.get('api_keys'))
        elif s.get('api_key'):
            _uid = __import__('uuid').uuid4().hex[:12]
            pool = [{'key': str(s['api_key']), 'label': '默认', 'enabled': True, 'uid': _uid}]
        result.append({
            'id': pid,
            'name': str(s.get('name') or pid),
            'base_url': str(s.get('base_url') or ''),
            'auth_type': str(s.get('auth_type') or 'none'),
            'auth_key_name': str(s.get('auth_key_name') or ''),
            'api_keys': pool,
            'apis': _normalize_api_list(s.get('apis')),
            'enabled': bool(s.get('enabled', True)),
            'builtin': False,
        })
    return result


def get_platform(pid):
    """按平台 ID 获取单条档案（未配置返回 None）"""
    for p in get_platforms():
        if p['id'] == pid:
            return p
    return None


def save_platform(pid, name=None, base_url=None, auth_type=None,
                  auth_key_name=None, api_keys=None, api_key=None, enabled=None, new_id=None):
    """保存平台档案（增量合并：仅更新传入的非 None 字段）
    - api_keys：Key 池整池覆盖提交（[{key, label, enabled}]，Key 行式管理与端点组同构）
    - api_key：V10.11.47 单 Key 兼容入参（None=不动；''=清空池）
    - new_id：V10.11.53 平台 ID 改名（级联）——格式/冲突/内置禁改校验由路由层前置完成；
      此处级联更新全部端点组的 platform 引用（天气/节假日等绑定不断链），再改写档案主键
    内置平台（uapis）不允许删除，只允许改连接参数与 Key 池"""
    pid = str(pid or '').strip()
    if not pid:
        return False
    platforms = get_platforms()
    target = None
    for p in platforms:
        if p['id'] == pid:
            target = p
            break
    if target is None:
        # 新平台仅允许两种来源：内置白名单（builtin）或管理员添加自定义平台（不带 builtin）
        if pid not in KNOWN_PLATFORM_IDS:
            return False
        target = {'id': pid, 'name': pid, 'base_url': '', 'auth_type': 'none',
                  'auth_key_name': '', 'api_keys': [], 'enabled': True, 'builtin': True}
        platforms.append(target)
    if name is not None:
        target['name'] = str(name).strip() or target['name']
    if base_url is not None:
        target['base_url'] = str(base_url).strip()
    if auth_type is not None:
        v = str(auth_type).strip()
        if v in AUTH_TYPES:
            target['auth_type'] = v
    if auth_key_name is not None:
        target['auth_key_name'] = str(auth_key_name).strip()
    if api_keys is not None:
        # V10.11.48 明文不回传协议：前端未编辑的已保存行提交 key='__KEEP__'+uid，
        # 此处按 uid 从现有池回填原明文（明文仅存库不回传不失联）；
        # uid 失配兜底（V10.11.47 旧数据无 uid）：按 label 唯一匹配回填
        old_pool = {str(k.get('uid') or ''): str(k.get('key') or '')
                    for k in (target.get('api_keys') or []) if isinstance(k, dict)}
        old_by_label = {}
        for k in (target.get('api_keys') or []):
            if isinstance(k, dict):
                old_by_label.setdefault(str(k.get('label') or ''), str(k.get('key') or ''))
        merged = []
        for item in (api_keys if isinstance(api_keys, list) else []):
            # V10.11.48b 占位符防线：'已保存' 是前端只读行的显示值，绝不可能是真实 Key 明文；
            # 若误提交（前端 dataset 属性名错误等），按 __KEEP__ 语义回填原值/跳过，防止覆盖真实 Key
            _raw_key = str(item.get('key') or '').strip() if isinstance(item, dict) else ''
            if isinstance(item, dict) and _raw_key in ('__KEEP__', '已保存'):
                uid = str(item.get('uid') or '')[:40]
                label = str(item.get('label') or '').strip()
                filled = None
                if uid and uid in old_pool:
                    filled = old_pool[uid]
                elif label and label in old_by_label:
                    filled = old_by_label[label]
                if filled and filled not in ('__KEEP__', '已保存'):
                    patched = dict(item)
                    patched['key'] = filled
                    merged.append(patched)
                # uid 与 label 均失配（或原值本身已损坏）→ 跳过该行（不误存占位符）
            else:
                merged.append(item)
        target['api_keys'] = _normalize_key_pool(merged)
    elif api_key is not None:
        target['api_keys'] = ([{'key': str(api_key).strip(), 'label': '默认', 'enabled': True}]
                              if str(api_key).strip() else [])
    if enabled is not None:
        target['enabled'] = bool(enabled)
    # V10.11.53 平台 ID 改名（级联）：仅自定义平台；内置 uapis 被调用引擎硬编码依赖禁改
    if new_id:
        new_id = str(new_id or '').strip().lower()
        if new_id and new_id != pid and not target.get('builtin'):
            for g in DEFAULT_GROUPS:
                urls = get_urls(g)
                changed = False
                for u in urls:
                    if str(u.get('platform', '') or '') == pid:
                        u['platform'] = new_id
                        changed = True
                if changed:
                    _set_setting(_url_key(g), json.dumps(urls, ensure_ascii=False))
            target['id'] = new_id
    _persist_platforms(platforms)
    return True


def add_custom_platform(pid, name, base_url, auth_type='bearer', auth_key_name='', api_keys=None, enabled=True):
    """新增自定义平台（V10.11.48）：管理员可接入任意自有平台（须与 UApiPro 协议兼容才能用于
    天气/节假日端点组；试验台仅支持 UApiPro 目录平台）。
    pid 白名单校验：小写字母/数字/连字符 2~30 位且不与已有平台冲突"""
    import re as _re
    pid = str(pid or '').strip().lower()
    if not _re.fullmatch(r'[a-z][a-z0-9-]{1,29}', pid):
        return False, '平台 ID 需 2~30 位小写字母/数字/连字符，且以字母开头'
    if any(p['id'] == pid for p in get_platforms()):
        return False, '平台 ID 已存在：%s' % pid
    name = str(name or '').strip()
    base_url = str(base_url or '').strip()
    if not name:
        return False, '平台名称不能为空'
    if not (base_url.startswith('http://') or base_url.startswith('https://')):
        return False, '平台地址必须以 http:// 或 https:// 开头'
    auth_type = str(auth_type or 'none').strip()
    if auth_type not in AUTH_TYPES:
        return False, '认证方式非法'
    platforms = get_platforms()
    platforms.append({
        'id': pid, 'name': name, 'base_url': base_url, 'auth_type': auth_type,
        'auth_key_name': str(auth_key_name or '').strip(),
        'api_keys': _normalize_key_pool(api_keys or []),
        'enabled': bool(enabled), 'builtin': False,
    })
    _persist_platforms(platforms)
    return True, ''


def delete_platform(pid):
    """删除自定义平台（内置平台 uapis 不允许删除）。平台被端点引用时不阻断删除——
    端点的 platform 引用会自动回落为无认证直连语义（调用方对未知平台不注入认证）。"""
    pid = str(pid or '').strip()
    platforms = get_platforms()
    if not any(p['id'] == pid for p in platforms):
        return False, '平台不存在'
    if pid in KNOWN_PLATFORM_IDS:
        return False, '内置平台 UApiPro 不允许删除'
    platforms = [p for p in platforms if p['id'] != pid]
    _persist_platforms(platforms)
    return True, ''


def _persist_platforms(platforms):
    """平台列表持久化（builtin 标记不入库，读取时由默认档案补全）"""
    stored = []
    for p in platforms:
        stored.append({
            'id': p['id'], 'name': p['name'], 'base_url': p['base_url'],
            'auth_type': p['auth_type'], 'auth_key_name': p['auth_key_name'],
            'api_keys': p.get('api_keys') or [], 'enabled': bool(p.get('enabled', True)),
            'apis': p.get('apis') or [],
        })
    _set_setting(PLATFORMS_KEY, json.dumps(stored, ensure_ascii=False))


def get_platform_keys(pid):
    """返回平台启用的 Key 池 [{key, label, uid}]（按配置顺序，轮换遍历用；池空返回 [] = 访客模式）"""
    p = get_platform(pid)
    if not p or not p.get('enabled'):
        return []
    return [{'key': k['key'], 'label': k['label'], 'uid': str(k.get('uid') or '')}
            for k in (p.get('api_keys') or []) if k.get('enabled') and str(k.get('key') or '').strip()]


def mask_platform_key(key):
    """API Key 脱敏展示：末 4 位可见，星号数与真实长度联动（上限 12）
    V10.11.53：固定 4 星改为 min(长度-4, 12) 星——45 位 Key 显示 12 星+末 4 位，
    长度感知且不撑爆 Key 行限宽输入框；≤8 位短 Key 保持末 2 位可见"""
    k = str(key or '')
    if not k:
        return ''
    if len(k) <= 8:
        return '*' * 4 + k[-2:]
    return '*' * min(len(k) - 4, 12) + k[-4:]


def get_auth_headers(pid, key=None):
    """构造平台认证请求头（V10.11.48 支持指定具体 Key，供 Key 轮换引擎使用）
    - key=None：取 Key 池第一个启用的 Key；池空返回 {}（访客模式）
    - bearer：{'Authorization': 'Bearer <key>'}；header：{<auth_key_name>: <key>}
    - none/query 或平台停用/不存在：返回 {}（query 型认证由调用方拼 URL 参数）"""
    p = get_platform(pid)
    if not p or not p.get('enabled'):
        return {}
    if key is None:
        pool = get_platform_keys(pid)
        if not pool:
            return {}
        key = pool[0]['key']
    if not key:
        return {}
    at = p.get('auth_type') or 'none'
    if at == 'bearer':
        return {'Authorization': 'Bearer ' + key}
    if at == 'header':
        hname = p.get('auth_key_name') or 'X-API-Key'
        return {hname: key}
    return {}


def uapi_catalog_total():
    """内置 UApiPro 静态目录可见条目数（延迟导入避免模块级循环依赖；异常时返回 0）"""
    try:
        from services import uapi_catalog as _uc
        return int(_uc.summary().get('total') or 0)
    except Exception:
        return 0


def get_platforms_for_display():
    """供配置页面渲染：平台列表（Key 池脱敏回显 + 状态汇总），V10.11.48 含 Key 明细与 uid
    （uid 供前端「保持原值」提交协议使用，不含明文）
    V10.11.52 目录归属平台化：增加 builtin_catalog_count / custom_api_count /
    catalog_count_total 三个计数字段（官方目录归入平台卡后徽章按合计显示）"""
    out = []
    for p in get_platforms():
        pool = p.get('api_keys') or []
        out.append({
            'id': p['id'], 'name': p['name'], 'base_url': p['base_url'],
            'auth_type': p['auth_type'], 'auth_key_name': p['auth_key_name'],
            'keys': [{'label': k['label'], 'key_masked': mask_platform_key(k['key']),
                      'key_set': bool(str(k.get('key') or '').strip()),
                      'enabled': bool(k.get('enabled')), 'uid': str(k.get('uid') or '')}
                     for k in pool],
            'key_count': len(pool),
            'key_enabled_count': sum(1 for k in pool if k.get('enabled')),
            'apis': [dict(a) for a in (p.get('apis') or [])],
            'api_count': len(p.get('apis') or []),
            # V10.11.52 目录归属平台化：目录计数三口径——官方内置目录数（仅内置平台）、
            # 自定义/导入条目数、合计（平台卡「平台 API 目录」徽章按合计显示）
            'builtin_catalog_count': (uapi_catalog_total() if p.get('builtin') else 0),
            'custom_api_count': len(p.get('apis') or []),
            'catalog_count_total': ((uapi_catalog_total() if p.get('builtin') else 0)
                                     + len(p.get('apis') or [])),
            'enabled': p['enabled'], 'builtin': p.get('builtin', False),
        })
    return out