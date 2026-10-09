# -*- coding: utf-8 -*-
"""
天气查询服务模块（数据源：Open-Meteo）
负责：
  1. 城市名 → 经纬度/时区（Geocoding API）
  2. 实时天气 + 未来 3 天预报（Forecast API）
  3. WMO weather_code → 中文描述映射
  4. 统一错误处理（网络失败 / API 返回 error / 城市未找到）

API 参考：
  - 地理编码: GET https://geocoding-api.open-meteo.com/v1/search?name={城市}&count=1&language=zh&format=json
  - 天气预报: GET https://api.open-meteo.com/v1/forecast
              ?latitude=&longitude=&current=...&daily=...&timezone=auto&forecast_days=3
  Open-Meteo 错误返回格式: {"error": true, "reason": "..."}
"""
import requests

# ===================== 常量 =====================
GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
# 连接超时 5 秒 / 读取超时 8 秒，避免天气服务异常拖慢页面
TIMEOUT = (5, 8)
# 城市名长度上限（前端与后端双重校验）
CITY_NAME_MAX_LEN = 30

# ===================== WMO weather_code → 中文 映射表 =====================
# 参照 WMO 标准天气码（Open-Meteo 使用该标准），覆盖全部常见取值
WMO_CODE_CN = {
    0: '晴',
    1: '基本晴朗',
    2: '局部多云',
    3: '阴天',
    4: '阴天',
    45: '雾',
    48: '冻雾',
    51: '毛毛雨',
    53: '毛毛雨',
    55: '毛毛雨',
    56: '冻毛毛雨',
    57: '冻毛毛雨',
    61: '小雨',
    63: '中雨',
    65: '大雨',
    66: '冻雨',
    67: '冻雨',
    71: '小雪',
    73: '中雪',
    75: '大雪',
    77: '米雪',
    80: '阵雨',
    81: '阵雨',
    82: '阵雨',
    85: '阵雪',
    86: '阵雪',
    95: '雷阵雨',
    96: '雷暴伴小冰雹',
    99: '雷暴伴大冰雹',
}

# 天气图标映射（FontAwesome 6 类名，供前端渲染天气图标使用）
WEATHER_ICONS = {
    0: 'fa-sun',
    1: 'fa-sun',
    2: 'fa-cloud-sun',
    3: 'fa-cloud',
    4: 'fa-cloud',
    45: 'fa-smog',
    48: 'fa-smog',
    51: 'fa-cloud-rain',
    53: 'fa-cloud-rain',
    55: 'fa-cloud-rain',
    56: 'fa-cloud-rain',
    57: 'fa-cloud-rain',
    61: 'fa-cloud-showers-heavy',
    63: 'fa-cloud-showers-heavy',
    65: 'fa-cloud-showers-heavy',
    66: 'fa-cloud-rain',
    67: 'fa-cloud-rain',
    71: 'fa-snowflake',
    73: 'fa-snowflake',
    75: 'fa-snowflake',
    77: 'fa-snowflake',
    80: 'fa-cloud-showers-heavy',
    81: 'fa-cloud-showers-heavy',
    82: 'fa-cloud-showers-heavy',
    85: 'fa-snowflake',
    86: 'fa-snowflake',
    95: 'fa-cloud-bolt',
    96: 'fa-cloud-bolt',
    99: 'fa-cloud-bolt',
}


class WeatherError(Exception):
    """天气服务统一异常：message 为可直接展示给用户的中文提示"""

    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ===================== 工具函数 =====================

def weather_code_cn(code):
    """weather_code → 中文描述；未知码兜底显示（不抛异常）"""
    if code is None:
        return '未知'
    try:
        c = int(code)
    except (TypeError, ValueError):
        return '未知天气({0})'.format(code)
    return WMO_CODE_CN.get(c, '未知天气({0})'.format(c))


def weather_icon(code):
    """weather_code → FontAwesome 图标类；未知码使用默认多云图标"""
    if code is None:
        return 'fa-cloud'
    try:
        c = int(code)
    except (TypeError, ValueError):
        return 'fa-cloud'
    return WEATHER_ICONS.get(c, 'fa-cloud')


# ===================== Open-Meteo API 封装 =====================

def geocode_city(city_name):
    """
    根据城市名解析经纬度与时区（Geocoding API）
    返回: {name, latitude, longitude, timezone, country, admin1}
    失败: 抛出 WeatherError（未找到城市 / 服务异常 / 超时）
    """
    params = {
        'name': city_name,
        'count': 1,
        'language': 'zh',
        'format': 'json',
    }
    try:
        resp = requests.get(GEOCODING_URL, params=params, timeout=TIMEOUT)
    except requests.Timeout:
        raise WeatherError('城市解析服务超时，请稍后重试', 503)
    except requests.RequestException:
        raise WeatherError('城市解析服务暂时不可用，请稍后重试', 503)

    try:
        data = resp.json()
    except ValueError:
        raise WeatherError('城市解析服务返回数据异常', 502)

    # Open-Meteo 错误返回格式: {"error": true, "reason": "..."}
    if data.get('error'):
        reason = data.get('reason') or '城市解析服务返回错误'
        raise WeatherError(reason, 502)

    results = data.get('results') or []
    if not results:
        raise WeatherError('未找到该城市，请检查城市名称是否正确', 404)

    r = results[0]
    # latitude / longitude 为必填字段，缺失视为数据异常
    if 'latitude' not in r or 'longitude' not in r:
        raise WeatherError('城市解析结果缺少坐标信息', 502)
    return {
        'name': r.get('name') or city_name,
        'latitude': r['latitude'],
        'longitude': r['longitude'],
        # 时区优先使用地理编码返回值；缺失时由 Forecast 调用方回落 timezone=auto
        'timezone': r.get('timezone') or 'auto',
        'country': r.get('country') or '',
        'admin1': r.get('admin1') or '',
    }


def fetch_forecast(latitude, longitude, timezone='auto'):
    """
    查询实时天气 + 每日预报（Forecast API）
    注意: 请求 daily 数据时必须携带 timezone（auto 或地理编码返回值），否则接口报错
    返回: Open-Meteo 原始 JSON（已校验非错误响应）
    """
    params = {
        'latitude': latitude,
        'longitude': longitude,
        # 实时天气字段：温度/湿度/体感/天气码/风速
        'current': (
            'temperature_2m,relative_humidity_2m,'
            'apparent_temperature,weather_code,wind_speed_10m'
        ),
        # 每日预报字段：天气码 / 最高温 / 最低温 / 降水概率
        'daily': (
            'weather_code,temperature_2m_max,'
            'temperature_2m_min,precipitation_probability_max'
        ),
        'timezone': timezone or 'auto',
        'forecast_days': 3,
    }
    try:
        resp = requests.get(FORECAST_URL, params=params, timeout=TIMEOUT)
    except requests.Timeout:
        raise WeatherError('天气服务超时，请稍后重试', 503)
    except requests.RequestException:
        raise WeatherError('天气服务暂时不可用，请稍后重试', 503)

    try:
        data = resp.json()
    except ValueError:
        raise WeatherError('天气服务返回数据异常', 502)

    # Open-Meteo 错误响应格式: {"error": true, "reason": "..."}
    if data.get('error'):
        reason = data.get('reason') or '天气服务返回错误'
        raise WeatherError(reason, 502)
    return data


def query_weather(city_name):
    """
    对外主入口：根据城市名查询天气
    返回结构化结果:
      {
        'city': {...},
        'current': {temperature, apparent_temperature, humidity,
                    weather_code, weather_text, wind_speed, time},
        'daily': [{date, weather_code, weather_text,
                   temp_max, temp_min, precip_prob}, ...]  # 3 天
      }
    失败: 抛出 WeatherError（message 为中文提示，status_code 为建议 HTTP 状态码）
    """
    # 1. 城市名 → 经纬度/时区
    city = geocode_city(city_name)
    # 2. 查询实时 + 每日预报（必须传 timezone）
    data = fetch_forecast(city['latitude'], city['longitude'], city['timezone'])

    current = data.get('current') or {}
    daily = data.get('daily') or {}
    dates = daily.get('time') or []
    day_count = len(dates)
    # 与日期数组等长的空位占位，防止某字段缺失导致索引越界
    daily_codes = daily.get('weather_code') or [None] * day_count
    daily_max = daily.get('temperature_2m_max') or [None] * day_count
    daily_min = daily.get('temperature_2m_min') or [None] * day_count
    daily_precip = daily.get('precipitation_probability_max') or [None] * day_count

    daily_list = []
    for i in range(day_count):
        code = daily_codes[i]
        daily_list.append({
            'date': dates[i],
            'weather_code': code,
            'weather_text': weather_code_cn(code),
            'icon': weather_icon(code),
            'temp_max': daily_max[i],
            'temp_min': daily_min[i],
            'precip_prob': daily_precip[i],
        })

    cur_code = current.get('weather_code')
    return {
        'city': city,
        'current': {
            'temperature': current.get('temperature_2m'),
            'apparent_temperature': current.get('apparent_temperature'),
            'humidity': current.get('relative_humidity_2m'),
            'weather_code': cur_code,
            'weather_text': weather_code_cn(cur_code),
            'icon': weather_icon(cur_code),
            'wind_speed': current.get('wind_speed_10m'),
            'time': current.get('time'),
        },
        'daily': daily_list,
    }