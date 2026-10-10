# -*- coding: utf-8 -*-
"""
holiday_service.py — 法定节假日班/休数据服务（V10.11.10 新增）
数据源：timor.tech 聚合接口（内容与国务院办公厅放假安排公报一致，免费无需密钥，国内直连可达）
    GET https://timor.tech/api/holiday/year/{year}
    响应 holiday 字典：key 为 "MM-DD"，value:
        holiday=true  → 法定休假日（含调休连休的周末）
        holiday=false → 调休补班日（name 含「补班」）
缓存策略：
    1. 进程内存缓存（按年）
    2. 磁盘缓存 data/holiday_cache.json（进程重启免拉取；放假安排每年发布一次后不再变化，缓存长期有效）
网络策略：禁代理直连优先 + 系统代理兜底（与 weather_service._http_get 同款双路径，
    规避系统代理进程存活但出口不通时请求挂死的问题）
降级：拉取失败返回空字典（万年历主体功能不受影响，仅不显示班/休角标）
"""
import json
import os
import threading

import requests

# 支持范围（与万年历农历数据表一致）
HOLIDAY_YEAR_MIN = 1900
HOLIDAY_YEAR_MAX = 2100

# 拉取超时（连接 5s / 读取 8s——公开接口数据量小，快速失败快速降级）
HOLIDAY_HTTP_TIMEOUT = (5, 8)

# 请求头（timor.tech 反爬：屏蔽 python-requests 默认 UA 返回 403，需模拟浏览器 UA）
HOLIDAY_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'),
    'Accept': 'application/json',
}

TIMOR_API = 'https://timor.tech/api/holiday/year/{}'

# V10.11.11 内置法定节假日/调休离线兜底字典（2024~2026年，国务院办公厅官方发布）
BUILTIN_HOLIDAYS = {
    2024: {'01-01': {'holiday': True, 'name': '元旦'}, '02-10': {'holiday': True, 'name': '春节'}, '02-11': {'holiday': True, 'name': '春节'}, '02-12': {'holiday': True, 'name': '春节'}, '02-13': {'holiday': True, 'name': '春节'}, '02-14': {'holiday': True, 'name': '春节'}, '02-15': {'holiday': True, 'name': '春节'}, '02-16': {'holiday': True, 'name': '春节'}, '02-17': {'holiday': True, 'name': '春节'}, '02-04': {'holiday': False, 'name': '春节补班'}, '02-18': {'holiday': False, 'name': '春节补班'}, '04-04': {'holiday': True, 'name': '清明节'}, '04-05': {'holiday': True, 'name': '清明节'}, '04-06': {'holiday': True, 'name': '清明节'}, '04-07': {'holiday': False, 'name': '清明补班'}, '05-01': {'holiday': True, 'name': '劳动节'}, '05-02': {'holiday': True, 'name': '劳动节'}, '05-03': {'holiday': True, 'name': '劳动节'}, '05-04': {'holiday': True, 'name': '劳动节'}, '05-05': {'holiday': True, 'name': '劳动节'}, '04-28': {'holiday': False, 'name': '劳动节补班'}, '05-11': {'holiday': False, 'name': '劳动节补班'}, '06-10': {'holiday': True, 'name': '端午节'}, '09-15': {'holiday': True, 'name': '中秋节'}, '09-16': {'holiday': True, 'name': '中秋节'}, '09-17': {'holiday': True, 'name': '中秋节'}, '09-14': {'holiday': False, 'name': '中秋补班'}, '10-01': {'holiday': True, 'name': '国庆节'}, '10-02': {'holiday': True, 'name': '国庆节'}, '10-03': {'holiday': True, 'name': '国庆节'}, '10-04': {'holiday': True, 'name': '国庆节'}, '10-05': {'holiday': True, 'name': '国庆节'}, '10-06': {'holiday': True, 'name': '国庆节'}, '10-07': {'holiday': True, 'name': '国庆节'}, '09-29': {'holiday': False, 'name': '国庆补班'}, '10-12': {'holiday': False, 'name': '国庆补班'}},
    2025: {'01-01': {'holiday': True, 'name': '元旦'}, '01-28': {'holiday': True, 'name': '春节'}, '01-29': {'holiday': True, 'name': '春节'}, '01-30': {'holiday': True, 'name': '春节'}, '01-31': {'holiday': True, 'name': '春节'}, '02-01': {'holiday': True, 'name': '春节'}, '02-02': {'holiday': True, 'name': '春节'}, '02-03': {'holiday': True, 'name': '春节'}, '02-04': {'holiday': True, 'name': '春节'}, '01-26': {'holiday': False, 'name': '春节补班'}, '02-08': {'holiday': False, 'name': '春节补班'}, '04-04': {'holiday': True, 'name': '清明节'}, '04-05': {'holiday': True, 'name': '清明节'}, '04-06': {'holiday': True, 'name': '清明节'}, '05-01': {'holiday': True, 'name': '劳动节'}, '05-02': {'holiday': True, 'name': '劳动节'}, '05-03': {'holiday': True, 'name': '劳动节'}, '05-04': {'holiday': True, 'name': '劳动节'}, '05-05': {'holiday': True, 'name': '劳动节'}, '04-27': {'holiday': False, 'name': '劳动节补班'}, '05-31': {'holiday': True, 'name': '端午节'}, '06-01': {'holiday': True, 'name': '端午节'}, '06-02': {'holiday': True, 'name': '端午节'}, '10-01': {'holiday': True, 'name': '国庆中秋'}, '10-02': {'holiday': True, 'name': '国庆中秋'}, '10-03': {'holiday': True, 'name': '国庆中秋'}, '10-04': {'holiday': True, 'name': '国庆中秋'}, '10-05': {'holiday': True, 'name': '国庆中秋'}, '10-06': {'holiday': True, 'name': '国庆中秋'}, '10-07': {'holiday': True, 'name': '国庆中秋'}, '10-08': {'holiday': True, 'name': '国庆中秋'}, '09-28': {'holiday': False, 'name': '国庆补班'}, '10-11': {'holiday': False, 'name': '国庆补班'}},
    2026: {'01-01': {'holiday': True, 'name': '元旦'}, '01-02': {'holiday': True, 'name': '元旦'}, '01-03': {'holiday': True, 'name': '元旦'}, '01-04': {'holiday': False, 'name': '元旦补班'}, '02-15': {'holiday': True, 'name': '春节'}, '02-16': {'holiday': True, 'name': '春节'}, '02-17': {'holiday': True, 'name': '春节'}, '02-18': {'holiday': True, 'name': '春节'}, '02-19': {'holiday': True, 'name': '春节'}, '02-20': {'holiday': True, 'name': '春节'}, '02-21': {'holiday': True, 'name': '春节'}, '02-22': {'holiday': True, 'name': '春节'}, '02-14': {'holiday': False, 'name': '春节补班'}, '02-28': {'holiday': False, 'name': '春节补班'}, '04-04': {'holiday': True, 'name': '清明节'}, '04-05': {'holiday': True, 'name': '清明节'}, '04-06': {'holiday': True, 'name': '清明节'}, '05-01': {'holiday': True, 'name': '劳动节'}, '05-02': {'holiday': True, 'name': '劳动节'}, '05-03': {'holiday': True, 'name': '劳动节'}, '06-19': {'holiday': True, 'name': '端午节'}, '09-25': {'holiday': True, 'name': '中秋节'}, '10-01': {'holiday': True, 'name': '国庆节'}, '10-02': {'holiday': True, 'name': '国庆节'}, '10-03': {'holiday': True, 'name': '国庆节'}, '10-04': {'holiday': True, 'name': '国庆节'}, '10-05': {'holiday': True, 'name': '国庆节'}, '10-06': {'holiday': True, 'name': '国庆节'}, '10-07': {'holiday': True, 'name': '国庆节'}}
}


# 磁盘缓存路径（data/ 目录，与运行库同级的公开数据缓存）
_CACHE_FILE = os.path.join('data', 'holiday_cache.json')

# 进程内存缓存：{year(int): holiday字典}
_mem_cache = {}
_cache_lock = threading.Lock()


def _load_disk_cache():
    """读取磁盘缓存（失败返回空字典，不抛异常）"""
    try:
        with open(_CACHE_FILE, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_disk_cache(year, holiday):
    """写入磁盘缓存（尽力而为，失败不影响主流程）"""
    try:
        if not os.path.exists('data'):
            os.makedirs('data', exist_ok=True)
        data = _load_disk_cache()
        data[str(year)] = holiday
        # 防止无限膨胀：只保留 2010~2100 范围内的年份键
        keys = [k for k in data.keys() if k.isdigit() and 2010 <= int(k) <= 2100]
        data = {k: v for k, v in data.items() if k in keys or not k.isdigit()}
        with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _fetch_from_timor(year):
    """从 timor.tech 拉取某年班/休数据（双路径：禁代理直连优先 + 系统代理兜底）"""
    url = TIMOR_API.format(year)
    last_err = None
    # 路径①：禁代理直连（国内环境 timor.tech 直连可达，系统代理故障时不被拖死）
    try:
        resp = requests.get(
            url,
            timeout=HOLIDAY_HTTP_TIMEOUT,
            headers=HOLIDAY_HEADERS,
            proxies={'http': None, 'https': None},
        )
        resp.raise_for_status()
        return _parse_timor(resp)
    except Exception as e:
        last_err = e
    # 路径②：回落系统代理（默认 trust_env 行为）
    try:
        resp = requests.get(url, timeout=HOLIDAY_HTTP_TIMEOUT, headers=HOLIDAY_HEADERS)
        resp.raise_for_status()
        return _parse_timor(resp)
    except Exception as e:
        last_err = e
    # 双路径均失败：降级空字典（不抛异常，万年历主体不受影响）
    print('[Holiday] 拉取 %d 年班/休数据失败（双路径均超时或异常）: %s' % (year, last_err))
    return {}


def _parse_timor(resp):
    """解析 timor.tech 响应，返回 {MM-DD: {holiday: bool, name: str}} 精简结构"""
    data = resp.json()
    if not isinstance(data, dict) or data.get('code') != 0:
        return {}
    holiday = data.get('holiday')
    if not isinstance(holiday, dict) or not holiday:
        return {}
    result = {}
    for key, item in holiday.items():
        if not isinstance(item, dict):
            continue
        mm_dd = str(key).strip()
        if len(mm_dd) == 5 and mm_dd[2] == '-':
            result[mm_dd] = {
                'holiday': bool(item.get('holiday')),
                'name': str(item.get('name') or ''),
            }
    return result


def get_year_holidays(year):
    """
    获取某年班/休数据（缓存优先，无缓存则拉取并缓存）
    返回 {"MM-DD": {"holiday": bool, "name": str}}；无数据年份返回 {}（降级）
    """
    year = int(year)
    if year < HOLIDAY_YEAR_MIN or year > HOLIDAY_YEAR_MAX:
        return {}
    # 1. 内存缓存
    with _cache_lock:
        if year in _mem_cache:
            return _mem_cache[year]
    # 2. 磁盘缓存
    disk = _load_disk_cache()
    cached = disk.get(str(year))
    if isinstance(cached, dict) and cached:
        with _cache_lock:
            _mem_cache[year] = cached
        return cached
    # 3. 拉取（国庆节等法定节假日数据 2007 年起才有；早年份直接返回空避免无效外网请求）
    if year < 2007:
        return {}
    holiday = _fetch_from_timor(year)
    # V10.11.11 离线/弱网兜底：若远程接口不可达，且命中内置年份字典，直接使用内置数据
    if not holiday and year in BUILTIN_HOLIDAYS:
        holiday = BUILTIN_HOLIDAYS[year]
    # 只有拉到真实数据或内置数据才缓存
    if holiday:
        with _cache_lock:
            _mem_cache[year] = holiday
        _save_disk_cache(year, holiday)
    return holiday
