# -*- coding: utf-8 -*-
"""
AI 助手联网搜索模块
基于 DuckDuckGo Search 实现，用于判断是否需要联网搜索以及搜索结果注入 prompt

V10.11.20 增强（外部接口服务配置）：
  - 总开关：service_config.ai_search_enabled 关闭时完全不做联网搜索
  - 多端点：ai_search_urls 有序端点列表，按序故障转移，失败自动切换下一个
  - 重试参数：ai_search_timeout（单次请求超时秒数）/ ai_search_retries（整轮重试次数）
  - 默认端点 https://duckduckgo.com 走官方库调用（行为与历史完全一致）；
    自定义端点按 DuckDuckGo 兼容 HTML 格式请求（GET {url}?q=... + 结果解析）
"""
import html
import re

# 延迟导入 DuckDuckGo Search（可选依赖，未安装时降级）
# V10.10.16 性能优化：duckduckgo_search 含 primp Rust 扩展 + lxml ~12-20MB，
# 移至首次实际搜索时才加载
DDGS = None
_HAS_DDS = None  # None=未检测, True/False=已检测

# V10.11.20 外部接口服务配置（总开关 / 多端点 / 重试参数）
from services import service_config

# 默认搜索端点（对应官方库调用）
_DEFAULT_SEARCH_URL = 'https://duckduckgo.com'

# 模拟浏览器 UA（自定义端点请求防反爬）
_SEARCH_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml',
}


def _ensure_dds():
    """首次调用时延迟导入 DDGS，后续从 sys.modules 缓存获取"""
    global DDGS, _HAS_DDS
    if _HAS_DDS is not None:
        return DDGS
    try:
        from duckduckgo_search import DDGS as _DDGS
        DDGS = _DDGS
        _HAS_DDS = True
    except ImportError:
        try:
            from ddgs import DDGS as _DDGS
            DDGS = _DDGS
            _HAS_DDS = True
        except ImportError:
            _HAS_DDS = False
    return DDGS


# 需要联网搜索的关键词正则模式
_SEARCH_PATTERNS = [
    r"天气|气温|温度|下雨|下雪|台风|雾霾|空气质量",
    r"新闻|最新|最近|今天.*发生|热点|事件|时事",
    r"现在|目前|当前|实时|今天|今日|本月|近期",
    r"搜一下|搜索|查一下|帮我查|查询",
    r"股价|汇率|油价|金价|比特币|基金|股票|理财|利率",
    r"是谁|谁.*说|谁.*做|发生了什么",
    r"几号|星期几|节假日|放假|调休|农历|阴历|阳历|节气",
]


def needs_search(query):
    """判断用户问题是否需要联网搜索"""
    if not query:
        return False
    for pattern in _SEARCH_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            return True
    return False


def _search_via_custom(url, query, max_results, timeout):
    """按 DuckDuckGo 兼容 HTML 格式请求自定义端点（GET {url}?q=...）
    返回 [{title, body, href}]；网络失败 / 格式不兼容返回 []（优雅降级）"""
    try:
        import requests
        with requests.Session() as s:
            s.trust_env = False
            resp = s.get(url, params={'q': query}, headers=_SEARCH_HEADERS, timeout=timeout)
    except Exception as e:
        print(f"[Web Search Custom Error] {e}")
        return []
    if resp.status_code != 200:
        return []
    return _parse_ddg_html(resp.text, max_results)


def _parse_ddg_html(page_text, max_results):
    """解析 DuckDuckGo HTML 搜索结果（result__a 标题/链接 + result__snippet 摘要）"""
    results = []
    # 标题与链接：<a class="result__a" href="...">标题</a>
    for m in re.finditer(
            r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            page_text, re.S):
        href = m.group(1)
        title = re.sub(r'<[^>]+>', '', m.group(2))
        title = html.unescape(title).strip()
        if not title:
            continue
        results.append({'title': title, 'body': '', 'href': href})
        if len(results) >= max_results:
            break
    # 摘要：result__snippet
    snippets = re.findall(
        r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', page_text, re.S)
    for i, sn in enumerate(snippets):
        if i < len(results):
            txt = re.sub(r'<[^>]+>', '', sn)
            results[i]['body'] = html.unescape(txt).strip()
    return results


def web_search(query, max_results=5):
    """
    DuckDuckGo 搜索（V10.11.20 多端点故障转移 + 重试参数）
    返回 [{title, body, href}] 列表
    """
    # 总开关关闭：完全不做联网搜索
    if not service_config.get_ai_search_enabled():
        return []
    urls = service_config.get_enabled_urls('ai_search')
    if not urls:
        return []
    timeout = service_config.get_timeout('ai_search')
    retries = service_config.get_retries('ai_search')

    for _round in range(retries + 1):
        for url in urls:
            # 默认端点 → 官方库调用（行为与历史完全一致）
            if url.rstrip('/') == _DEFAULT_SEARCH_URL:
                _ensure_dds()
                if not _HAS_DDS:
                    continue
                try:
                    results = []
                    with DDGS() as ddgs:
                        for r in ddgs.text(query, max_results=max_results):
                            results.append({
                                'title': r.get('title', ''),
                                'body': r.get('body', ''),
                                'href': r.get('href', r.get('link', ''))
                            })
                    if results:
                        return results
                except Exception as e:
                    print(f"[Web Search Error] {e}")
                    continue
            # 自定义端点：DuckDuckGo 兼容 HTML 格式请求
            else:
                results = _search_via_custom(url, query, max_results, timeout)
                if results:
                    return results
    return []


def search_and_summarize(query):
    """
    搜索并格式化为 prompt 注入文本
    返回格式化字符串，搜索失败返回"无网络搜索结果"占位
    """
    if not service_config.get_ai_search_enabled():
        return "（无网络搜索结果）"
    _ensure_dds()
    if not _HAS_DDS and not service_config.get_enabled_urls('ai_search'):
        return "（无网络搜索结果）"

    results = web_search(query, max_results=5)
    if not results:
        return "（无网络搜索结果）"

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get('title', '')
        body = r.get('body', '')
        lines.append(f"{i}. {title}\n   {body}")

    return "\n".join(lines)