# -*- coding: utf-8 -*-
"""
uapi_openapi.py — 第三方平台 OpenAPI 规范探测与解析（V10.11.51 新增）

用途：管理员在「多平台接口广场」为任意平台一键获取 API 目录时，自动探测该平台
是否对外提供标准 OpenAPI/Swagger 规范，并解析为系统内的平台 API 条目。

探测顺序（均只读 GET，超时 4+8 秒，响应上限 3 MB，禁止跨域重定向）：
  1. {origin}/openapi.json          ← UApiPro 实际可用（OpenAPI 3.1.0，112 条）
  2. {base_url}/openapi.json
  3. {base_url}/docs/openapi.json
  4. {base_url}/swagger.json
  5. {base_url}/v3/api-docs
  6. {base_url}/api-docs

解析能力：
  - OpenAPI 3.x / Swagger 2.0 的 paths（GET/POST/PUT/DELETE/PATCH）
  - 参数：parameters（query/path）+ requestBody 的 application/json schema 属性
  - 积分：x-uapi-pricing-credits 扩展字段
  - 路径前缀自动剥离（base_url 含 /api/v1 时，规范内的 /api/v1/xxx 会还原为 /xxx）
  - 跳过 multipart 文件上传型接口（系统不支持在线文件上传）
  - 解析条数上限 300，防止异常规范撑爆页面

安全：不解析 YAML、不跟随重定向、不访问非 http(s) 地址、响应体大小硬限制。
"""
import json
import re
from urllib.parse import urlparse

MAX_SPEC_BYTES = 3 * 1024 * 1024
DISCOVER_TIMEOUT = (4, 8)
MAX_APIS_PARSE = 300
_USER_AGENT = 'GiftBookkeepingApp/1.0 (+OpenAPI discovery)'


def _http_get(url, timeout=DISCOVER_TIMEOUT):
    """双路径只读请求（禁代理直连优先 + 系统代理兜底），不跟随重定向"""
    import requests
    for trust_env in (False, True):
        try:
            with requests.Session() as s:
                s.trust_env = trust_env
                return s.get(url, timeout=timeout, allow_redirects=False,
                             headers={'Accept': 'application/json', 'User-Agent': _USER_AGENT})
        except Exception:
            continue
    return None


def candidate_urls(base_url):
    """按优先级生成候选规范地址（去重）
    V10.11.52 候选扩充 6→13：覆盖 SpringDoc/SpringFox(.NET)与常见网关路径；
    实测国内多数 API 商城（天行/聚合/showapi 等）为网页文档站、无机器可读规范，
    全部候选落空时由调用方引导用户「指定规范地址/粘贴 JSON/单条录入」"""
    base_url = str(base_url or '').strip()
    p = urlparse(base_url)
    if p.scheme not in ('http', 'https') or not p.netloc:
        return []
    origin = '%s://%s' % (p.scheme, p.netloc)
    base = base_url.rstrip('/')
    urls = [
        origin + '/openapi.json',            # OpenAPI 根路径（UApiPro 实测可用）
        base + '/openapi.json',
        origin + '/swagger.json',            # Swagger 根路径
        base + '/docs/openapi.json',
        base + '/swagger.json',
        base + '/v3/api-docs',               # SpringDoc（Spring Boot 3 默认）
        base + '/v2/api-docs',               # SpringFox 2.x（Spring Boot 2 常用）
        base + '/v3/api-docs/swagger.json',  # SpringDoc 分组规范兜底
        base + '/swagger/v1/swagger.json',   # ASP.NET Core 默认
        base + '/api-docs',
        base + '/api/openapi.json',
        base + '/api/swagger.json',
        base + '/docs/swagger.json',
    ]
    out = []
    for u in urls:
        if u not in out:
            out.append(u)
    return out


def _deref(spec, node, depth=0):
    """极简 $ref 解析（仅本地 #/ 引用，最多 6 层）"""
    if depth > 6 or not isinstance(node, dict):
        return node
    ref = node.get('$ref')
    if ref and str(ref).startswith('#/'):
        cur = spec
        for part in str(ref)[2:].split('/'):
            cur = cur.get(part, {}) if isinstance(cur, dict) else {}
        return _deref(spec, cur, depth + 1)
    return node


def _schema_type(schema):
    schema = schema or {}
    if schema.get('enum'):
        return 'select'
    t = schema.get('type')
    if isinstance(t, list):
        non_null = [x for x in t if x != 'null']
        t = non_null[0] if non_null else (t[0] if t else None)
    fmt = str(schema.get('format') or '').lower()
    if t == 'boolean':
        return 'bool'
    if t == 'integer':
        return 'long' if fmt == 'int64' else 'int'
    if t == 'number':
        return 'float'
    if t == 'array':
        return 'array'
    if t == 'object':
        return 'object'
    if t == 'string':
        if fmt == 'date':
            return 'date'
        if fmt == 'date-time':
            return 'datetime'
        if fmt == 'time':
            return 'time'
        if fmt == 'email':
            return 'email'
        if fmt in ('uri', 'url'):
            return 'url'
        if fmt == 'password':
            return 'password'
        return 'string'
    return 'string'


def _short_label(desc, name):
    """官方描述 → 精炼参数标签（去 Markdown、取首句、截断 18 字）"""
    s = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', str(desc or ''))
    s = re.sub(r'[`*#>]', '', s).strip()
    s = re.split(r'[。；;\n]', s)[0].strip()
    s = re.split(r'[，,]', s)[0].strip().strip('：: ')
    return (s[:18] or name)


def _extract_params(spec, op):
    """提取操作参数（query/path + JSON body 属性），跳过 header/cookie 认证参数"""
    out, seen = [], set()
    for p in op.get('parameters') or []:
        p = _deref(spec, p)
        name = p.get('name')
        loc = str(p.get('in') or 'query')
        if not name or name in seen or loc in ('header', 'cookie'):
            continue
        seen.add(name)
        sch = _deref(spec, p.get('schema') or {})
        opts = sch.get('enum') or []
        out.append({
            'name': str(name)[:50],
            'label': _short_label(p.get('description'), str(name))[:60],
            'type': _schema_type(sch),
            'required': bool(p.get('required')),
            'example': str(sch.get('example') or '')[:200],
            'options': [str(x)[:60] for x in opts][:60],
        })
    body = _deref(spec, op.get('requestBody') or {})
    content = body.get('content') or {}
    for ctype, cval in content.items():
        if 'json' not in str(ctype).lower():
            continue
        sch = _deref(spec, cval.get('schema') or {})
        props = sch.get('properties') or {}
        required = set(sch.get('required') or [])
        for pname, pschema in props.items():
            if pname in seen:
                continue
            seen.add(pname)
            pschema = _deref(spec, pschema)
            opts = pschema.get('enum') or []
            out.append({
                'name': str(pname)[:50],
                'label': _short_label(pschema.get('description'), str(pname))[:60],
                'type': _schema_type(pschema),
                'required': pname in required,
                'example': str(pschema.get('example') or '')[:200],
                'options': [str(x)[:60] for x in opts][:60],
            })
    return out[:40]


def _path_param_names(path):
    return set(re.findall(r'\{(\w+)\}', path or ''))


def _strip_base_prefix(path, base_url):
    """剥离 base_url 的路径前缀：base_url=/api/v1 且 path=/api/v1/foo → /foo"""
    bp = urlparse(str(base_url or '')).path.rstrip('/')
    if bp and path.startswith(bp + '/'):
        return path[len(bp):]
    return path


def _is_multipart(op):
    body = op.get('requestBody') or {}
    for ctype in (body.get('content') or {}):
        if 'multipart' in str(ctype).lower():
            return True
    return False


def parse_spec(spec, base_url='', source_url=''):
    """解析 OpenAPI/Swagger 规范为平台 API 条目列表
    返回 (apis, stats)；apis 未做严格校验，交由 service_config.import_platform_apis 处理"""
    if not isinstance(spec, dict):
        return [], {'total': 0, 'skipped_file': 0, 'skipped_method': 0}
    paths = spec.get('paths')
    if not isinstance(paths, dict) or not paths:
        return [], {'total': 0, 'skipped_file': 0, 'skipped_method': 0}

    apis, skipped_file, skipped_method = [], 0, 0
    for raw_path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        path = _strip_base_prefix(str(raw_path), base_url)
        if not path.startswith('/'):
            path = '/' + path.lstrip('/')
        for method, op in methods.items():
            if method.lower() not in ('get', 'post', 'put', 'delete', 'patch'):
                skipped_method += 1
                continue
            if not isinstance(op, dict):
                continue
            if _is_multipart(op):
                skipped_file += 1
                continue
            if len(apis) >= MAX_APIS_PARSE:
                break
            name = (str(op.get('summary') or '').strip()
                    or str(op.get('operationId') or '').strip()
                    or path.rstrip('/').split('/')[-1] or 'API')
            credits = op.get('x-uapi-pricing-credits')
            try:
                credits = int(float(credits)) if credits is not None else None
            except (TypeError, ValueError):
                credits = None
            params = _extract_params(spec, op)
            test_params = {}
            for p in params:
                if p.get('example') and len(test_params) < 5:
                    test_params[p['name']] = p['example']
            apis.append({
                'name': name[:50],
                'method': method.upper(),
                'path': path,
                'desc': re.sub(r'\s+', ' ', str(op.get('description') or '')).strip()[:500],
                'credits': credits,
                'params': params,
                'test_params': test_params,
                'source': 'openapi',
                '_source_url': source_url,
            })
        if len(apis) >= MAX_APIS_PARSE:
            break
    return apis, {'total': len(apis), 'skipped_file': skipped_file,
                  'skipped_method': skipped_method}


def _classify_attempt(url, resp):
    """V10.11.52 失败原因归类：给前端展示每个候选地址的落空原因"""
    if resp is None:
        return '无法连接（超时/拒绝/证书错误）'
    code = resp.status_code
    if code in (301, 302, 307, 308):
        return '返回重定向（HTTP %s）' % code
    if code == 403:
        return '拒绝访问（HTTP 403，可能需登录）'
    if code == 404:
        return '该地址无文档（HTTP 404）'
    if code != 200:
        return 'HTTP %s' % code
    ctype = (resp.headers.get('Content-Type') or '').lower()
    raw = resp.content or b''
    if len(raw) > MAX_SPEC_BYTES:
        return '响应过大（>3MB）'
    text = raw.decode('utf-8', errors='replace').strip()
    if 'html' in ctype or not text.startswith('{'):
        return '返回网页/非 JSON 内容'
    try:
        spec = json.loads(text)
    except ValueError:
        return '返回 JSON 但解析失败'
    if isinstance(spec, dict) and isinstance(spec.get('paths'), dict):
        return '可解析但无有效接口'
    return '返回 JSON 但不含 paths（接口定义）'


def _fetch_spec(url, base_url, attempts):
    """拉取并解析单个规范地址，成功返回 (apis, stats)，失败记 attempts 并返回 None
    安全边界：仅只读 GET、禁重定向、3MB 上限、仅解析 JSON 结构（原始内容不回传前端）；
    允许跨源拉取——平台文档站的规范链接常位于子域（如 docs.xxx.com），由管理员自行输入可信地址"""
    from urllib.parse import urlparse as _up
    u = _up(url)
    if u.scheme not in ('http', 'https') or not u.netloc:
        attempts.append({'url': url[:120], 'reason': '地址非法（需 http/https）'})
        return None
    resp = _http_get(url)
    if resp is None or resp.status_code != 200:
        attempts.append({'url': url[:120], 'reason': _classify_attempt(url, resp)})
        return None
    ctype = (resp.headers.get('Content-Type') or '').lower()
    raw = resp.content or b''
    if 'html' in ctype or len(raw) > MAX_SPEC_BYTES or not raw:
        attempts.append({'url': url[:120], 'reason': _classify_attempt(url, resp)})
        return None
    text = raw.decode('utf-8', errors='replace').strip()
    if not text.startswith('{'):
        attempts.append({'url': url[:120], 'reason': _classify_attempt(url, resp)})
        return None
    try:
        spec = json.loads(text)
    except ValueError:
        attempts.append({'url': url[:120], 'reason': _classify_attempt(url, resp)})
        return None
    if not isinstance(spec, dict) or not isinstance(spec.get('paths'), dict):
        attempts.append({'url': url[:120], 'reason': _classify_attempt(url, resp)})
        return None
    apis, stats = parse_spec(spec, base_url=base_url, source_url=url)
    if not apis:
        attempts.append({'url': url[:120], 'reason': '解析出 0 个有效接口'})
        return None
    return apis, stats


def discover(base_url, spec_url=''):
    """探测并解析平台的 OpenAPI 规范
    V10.11.52：spec_url 非空时优先拉取该指定地址（平台文档站提供的规范下载链接），
    仍按同源/大小/解析白名单校验；全部落空时返回 attempts 明细供前端展示失败原因
    返回 {ok, source_url, apis, message, tried, attempts, stats}"""
    base_url = str(base_url or '').strip()
    attempts = []
    order = []
    spec_url = str(spec_url or '').strip()
    if spec_url:
        order.append(spec_url)
        got = _fetch_spec(spec_url, base_url, attempts)
        if got:
            apis, stats = got
            msg = '发现 %d 个接口' % stats['total']
            if stats['skipped_file']:
                msg += '，跳过 %d 个文件上传型' % stats['skipped_file']
            return {'ok': True, 'source_url': spec_url, 'apis': apis, 'message': msg,
                    'tried': order, 'attempts': attempts, 'stats': stats}
    for url in candidate_urls(base_url):
        if url in order:
            continue
        order.append(url)
        got = _fetch_spec(url, base_url, attempts)
        if got:
            apis, stats = got
            msg = '发现 %d 个接口' % stats['total']
            if stats['skipped_file']:
                msg += '，跳过 %d 个文件上传型' % stats['skipped_file']
            return {'ok': True, 'source_url': url, 'apis': apis, 'message': msg,
                    'tried': order, 'attempts': attempts, 'stats': stats}
    return {'ok': False, 'source_url': '', 'apis': [],
            'message': '未发现可用的 OpenAPI 文档（已尝试 %d 个地址）' % len(order),
            'tried': order, 'attempts': attempts[:13],
            'stats': {'total': 0, 'skipped_file': 0, 'skipped_method': 0}}


def parse_pasted(text, base_url=''):
    """解析手动粘贴的规范文本（仅 JSON）
    返回 {ok, apis, message, stats}"""
    text = str(text or '').strip()
    if not text:
        return {'ok': False, 'apis': [], 'message': '请粘贴 OpenAPI/Swagger JSON 内容',
                'stats': {'total': 0, 'skipped_file': 0, 'skipped_method': 0}}
    if len(text.encode('utf-8', errors='ignore')) > MAX_SPEC_BYTES:
        return {'ok': False, 'apis': [], 'message': '内容过大（上限 3 MB）',
                'stats': {'total': 0, 'skipped_file': 0, 'skipped_method': 0}}
    try:
        spec = json.loads(text)
    except ValueError:
        return {'ok': False, 'apis': [], 'message': '不是合法的 JSON 文本',
                'stats': {'total': 0, 'skipped_file': 0, 'skipped_method': 0}}
    if not isinstance(spec, dict) or not isinstance(spec.get('paths'), dict):
        return {'ok': False, 'apis': [], 'message': '缺少 paths 字段（非 OpenAPI/Swagger 规范）',
                'stats': {'total': 0, 'skipped_file': 0, 'skipped_method': 0}}
    apis, stats = parse_spec(spec, base_url=base_url, source_url='pasted')
    if not apis:
        return {'ok': False, 'apis': [], 'message': '未解析出可用接口',
                'stats': stats}
    msg = '解析出 %d 个接口' % stats['total']
    if stats['skipped_file']:
        msg += '，跳过 %d 个文件上传型' % stats['skipped_file']
    return {'ok': True, 'apis': apis, 'message': msg, 'stats': stats}