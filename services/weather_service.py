# -*- coding: utf-8 -*-
"""
天气查询服务模块（数据源：Open-Meteo）
负责：
  1. 城市名 → 经纬度/时区（Geocoding API）
  2. 实时天气 + 每日预报（Forecast API，V10.11.7 起默认 15 天）
  3. WMO weather_code → 中文描述映射
  4. 统一错误处理（网络失败 / API 返回 error / 城市未找到）
  5. V10.11.7 级联选择支持：省/市/区县 → 候选城市智能匹配
  6. V10.11.8 新增：空气质量（Air Quality API，失败降级不影响主查询）

API 参考：
  - 地理编码: GET https://geocoding-api.open-meteo.com/v1/search?name={城市}&count=10&language=zh&format=json
  - 天气预报: GET https://api.open-meteo.com/v1/forecast
              ?latitude=&longitude=&current=...&daily=...&timezone=auto&forecast_days=15
  - 空气质量: GET https://air-quality-api.open-meteo.com/v1/air-quality
              ?latitude=&longitude=&current=pm10,pm2_5,us_aqi&timezone=auto
  Open-Meteo 错误返回格式: {"error": true, "reason": "..."}
"""
import os
import json
import time
import datetime
import threading
import requests

# V10.11.20 外部接口服务配置（多端点 + 故障转移 + 重试参数），见 service_config.py
from services import service_config

# ===================== 常量 =====================
GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
# V10.11.8 空气质量接口（免费无密钥；不可达时降级为 None，不影响主查询）
AIR_QUALITY_URL = 'https://air-quality-api.open-meteo.com/v1/air-quality'
# 连接超时 5 秒 / 读取超时 8 秒，避免天气服务异常拖慢页面（实际网络策略见 _http_get）
TIMEOUT = (5, 8)
# 城市名长度上限（前端与后端双重校验）
CITY_NAME_MAX_LEN = 30
# 默认预报天数（V10.11.7：3 → 15）
DEFAULT_FORECAST_DAYS = 15
# 预报天数上限（Open-Meteo 免费档最大 16 天）
MAX_FORECAST_DAYS = 16
# 级联匹配：地理编码返回的候选数量
GEOCODE_CANDIDATES = 10

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


class ServiceDisabled(Exception):
    """V10.11.26 该组外部接口已被管理员明确停用（组内无任何启用端点）。
    与「端点启用但网络不可达」（返回 None）严格区分：
       - 明确停用 → 调用方按业务语义报错（不走缓存/离线合成兜底）
       - 网络故障   → 走原有缓存/离线合成降级链
    """

    def __init__(self, group):
        super().__init__(group)
        self.group = group


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


# 风向角度 → 中文方位（V10.11.7 新增，用于级联选择天气卡片展示）
def wind_direction_cn(deg):
    """角度转中文方位；缺值返回 None"""
    if deg is None:
        return None
    try:
        d = float(deg) % 360
    except (TypeError, ValueError):
        return None
    names = ['北', '东北', '东', '东南', '南', '西南', '西', '西北']
    # 每 45° 一个方位，22.5° 为分界偏移
    idx = int((d + 22.5) // 45) % 8
    return names[idx]


# ===================== 缓存与离线兜底常量 =====================
# V10.11.21 起归入 logs/ 目录：公开数据缓存不入库不上传（cwd 相对路径——服务以项目根为工作目录）
FORECAST_CACHE_FILE = os.path.join('logs', 'weather_forecast_cache.json')
GEOCODE_CACHE_FILE = os.path.join('logs', 'weather_geocode_cache.json')
FORECAST_CACHE_TTL = 1800  # 30 分钟缓存有效期

_mem_forecast_cache = {}
_mem_geocode_cache = {}
_weather_cache_lock = threading.Lock()

# 内置主要城市地理坐标（覆盖直辖市、各省省会及重要城市，断网/网络隔离下免地理编码）
BUILTIN_CITIES = {
    '北京': {'name': '北京市', 'latitude': 39.9042, 'longitude': 116.4074, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '北京市', 'admin2': ''},
    '上海': {'name': '上海市', 'latitude': 31.2304, 'longitude': 121.4737, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '上海市', 'admin2': ''},
    '广州': {'name': '广州市', 'latitude': 23.1291, 'longitude': 113.2644, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '广东省', 'admin2': '广州市'},
    '深圳': {'name': '深圳市', 'latitude': 22.5431, 'longitude': 114.0579, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '广东省', 'admin2': '深圳市'},
    '成都': {'name': '成都市', 'latitude': 30.5728, 'longitude': 104.0668, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '四川省', 'admin2': '成都市'},
    '杭州': {'name': '杭州市', 'latitude': 30.2741, 'longitude': 120.1551, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '浙江省', 'admin2': '杭州市'},
    '重庆': {'name': '重庆市', 'latitude': 29.5630, 'longitude': 106.5516, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '重庆市', 'admin2': ''},
    '武汉': {'name': '武汉市', 'latitude': 30.5928, 'longitude': 114.3055, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '湖北省', 'admin2': '武汉市'},
    '西安': {'name': '西安市', 'latitude': 34.3416, 'longitude': 108.9398, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '陕西省', 'admin2': '西安市'},
    '南京': {'name': '南京市', 'latitude': 32.0603, 'longitude': 118.7969, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '江苏省', 'admin2': '南京市'},
    '天津': {'name': '天津市', 'latitude': 39.1256, 'longitude': 117.1902, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '天津市', 'admin2': ''},
    '郑州': {'name': '郑州市', 'latitude': 34.7466, 'longitude': 113.6254, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '河南省', 'admin2': '郑州市'},
    '长沙': {'name': '长沙市', 'latitude': 28.2282, 'longitude': 112.9388, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '湖南省', 'admin2': '长沙市'},
    '苏州': {'name': '苏州市', 'latitude': 31.2990, 'longitude': 120.5853, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '江苏省', 'admin2': '苏州市'},
    '青岛': {'name': '青岛市', 'latitude': 36.0671, 'longitude': 120.3826, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '山东省', 'admin2': '青岛市'},
    '厦门': {'name': '厦门市', 'latitude': 24.4798, 'longitude': 118.0894, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '福建省', 'admin2': '厦门市'},
    '昆明': {'name': '昆明市', 'latitude': 25.0406, 'longitude': 102.7123, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '云南省', 'admin2': '昆明市'},
    '合肥': {'name': '合肥市', 'latitude': 31.8206, 'longitude': 117.2272, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '安徽省', 'admin2': '合肥市'},
    '福州': {'name': '福州市', 'latitude': 26.0745, 'longitude': 119.2965, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '福建省', 'admin2': '福州市'},
    '济南': {'name': '济南市', 'latitude': 36.6512, 'longitude': 117.1201, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '山东省', 'admin2': '济南市'},
    '沈阳': {'name': '沈阳市', 'latitude': 41.8057, 'longitude': 123.4315, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '辽宁省', 'admin2': '沈阳市'},
    '哈尔滨': {'name': '哈尔滨市', 'latitude': 45.8038, 'longitude': 126.5350, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '黑龙江省', 'admin2': '哈尔滨市'},
    '长春': {'name': '长春市', 'latitude': 43.8171, 'longitude': 125.3235, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '吉林省', 'admin2': '长春市'},
    '南昌': {'name': '南昌市', 'latitude': 28.6829, 'longitude': 115.8582, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '江西省', 'admin2': '南昌市'},
    '贵阳': {'name': '贵阳市', 'latitude': 26.6470, 'longitude': 106.6302, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '贵州省', 'admin2': '贵阳市'},
    '南宁': {'name': '南宁市', 'latitude': 22.8170, 'longitude': 108.3665, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '广西壮族自治区', 'admin2': '南宁市'},
    '海口': {'name': '海口市', 'latitude': 20.0440, 'longitude': 110.1999, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '海南省', 'admin2': '海口市'},
    '兰州': {'name': '兰州市', 'latitude': 36.0611, 'longitude': 103.8343, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '甘肃省', 'admin2': '兰州市'},
    '银川': {'name': '银川市', 'latitude': 38.4872, 'longitude': 106.2309, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '宁夏回族自治区', 'admin2': '银川市'},
    '西宁': {'name': '西宁市', 'latitude': 36.6171, 'longitude': 101.7782, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '青海省', 'admin2': '西宁市'},
    '呼和浩特': {'name': '呼和浩特市', 'latitude': 40.8415, 'longitude': 111.7510, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '内蒙古自治区', 'admin2': '呼和浩特市'},
    '乌鲁木齐': {'name': '乌鲁木齐市', 'latitude': 43.8256, 'longitude': 87.6168, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '新疆维吾尔自治区', 'admin2': '乌鲁木齐市'},
    '拉萨': {'name': '拉萨市', 'latitude': 29.6525, 'longitude': 91.1721, 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': '西藏自治区', 'admin2': '拉萨市'},
    '香港': {'name': '香港特别行政区', 'latitude': 22.3193, 'longitude': 114.1694, 'timezone': 'Asia/Hong_Kong', 'country': '中国', 'admin1': '香港特别行政区', 'admin2': ''},
    '澳门': {'name': '澳门特别行政区', 'latitude': 22.1987, 'longitude': 113.5439, 'timezone': 'Asia/Macau', 'country': '中国', 'admin1': '澳门特别行政区', 'admin2': ''},
    '台北': {'name': '台北市', 'latitude': 25.0330, 'longitude': 121.5654, 'timezone': 'Asia/Taipei', 'country': '中国', 'admin1': '台湾', 'admin2': '台北市'},
}


def _load_json_disk_cache(filepath):
    """读取磁盘缓存文件"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_json_disk_cache(filepath, data):
    """保存磁盘缓存文件"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


_regional_cities_cache = None
_regional_path_cache = None      # V10.11.26 全路径索引：纯地名串(省/省市/省市县) → 坐标信息
_regional_cities_lock = threading.Lock()


def _load_regional_cities():
    """懒加载全国行政区划库（static/js/china-regions.js），构建覆盖全部省、市、区县的地理坐标索引
    V10.11.26 同时构建「全路径索引」：归一化后的省/省市/省市县纯地名串 → 坐标，
    供自由文本『四川省巴中市恩阳区』等多级全名精确匹配（修复被宽松匹配误配为上级的问题）。"""
    global _regional_cities_cache, _regional_path_cache
    if _regional_cities_cache is not None:
        return _regional_cities_cache
    with _regional_cities_lock:
        if _regional_cities_cache is not None:
            return _regional_cities_cache
        index = {}
        path_index = {}

        def _add_path(key, info):
            """路径键首次写入（同名区县保留先出现的；多级全路径键天然唯一不受影响）"""
            if key and key not in path_index:
                path_index[key] = dict(info)

        for k, v in BUILTIN_CITIES.items():
            index[k] = dict(v)
            n_k = _norm_region(k)
            if n_k:
                index[n_k] = dict(v)
            _add_path(_norm_region_all(k), v)

        # V10.11.21 结构重组：本模块迁入 services/，锚点上溯一级回项目根（js 路径语义不变）
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'js', 'china-regions.js')
        if os.path.exists(js_path):
            try:
                with open(js_path, 'r', encoding='utf-8') as f:
                    js_text = f.read()
                marker = 'window.CHINA_REGIONS = '
                pos = js_text.find(marker)
                if pos != -1:
                    raw_json = js_text[pos + len(marker):].strip().rstrip(';')
                    data = json.loads(raw_json)
                    for p in data:
                        p_name = p.get('n', '')
                        p_g = p.get('g')
                        if p_name and p_g:
                            p_info = {'name': p_name, 'latitude': p_g[1], 'longitude': p_g[0], 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': p_name, 'admin2': ''}
                            index[p_name] = p_info
                            n_p = _norm_region(p_name)
                            if n_p:
                                index[n_p] = p_info
                            p_norm = _norm_region_all(p_name)
                            _add_path(p_norm, p_info)
                        for c in p.get('c', []):
                            c_name = c.get('n', '')
                            c_g = c.get('g')
                            if c_name and c_g:
                                c_info = {'name': c_name, 'latitude': c_g[1], 'longitude': c_g[0], 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': p_name, 'admin2': c_name}
                                index[c_name] = c_info
                                n_c = _norm_region(c_name)
                                if n_c:
                                    index[n_c] = c_info
                                # 省+市（或直辖市：省+区）
                                c_norm = _norm_region_all(c_name)
                                if p_norm:
                                    _add_path(p_norm + c_norm, c_info)
                                _add_path(c_norm, c_info)
                            for d in c.get('c', []):
                                d_name = d.get('n', '')
                                d_g = d.get('g')
                                if d_name and d_g:
                                    d_info = {'name': d_name, 'latitude': d_g[1], 'longitude': d_g[0], 'timezone': 'Asia/Shanghai', 'country': '中国', 'admin1': p_name, 'admin2': c_name}
                                    if d_name not in index:
                                        index[d_name] = d_info
                                    n_d = _norm_region(d_name)
                                    if n_d and n_d not in index:
                                        index[n_d] = d_info
                                    # 市县 / 省市县 全路径（直辖市 c/d 同名时只留省+区路径，避免『北京朝阳朝阳』）
                                    d_norm = _norm_region_all(d_name)
                                    if c_norm and d_norm and d_norm != c_norm:
                                        _add_path(c_norm + d_norm, d_info)
                                        if p_norm:
                                            _add_path(p_norm + c_norm + d_norm, d_info)
                                    elif d_norm:
                                        _add_path(d_norm, d_info)
            except Exception:
                pass
        _regional_cities_cache = index
        _regional_path_cache = path_index
        return _regional_cities_cache


def _match_path(city_name):
    """V10.11.26 全路径匹配：『省+市+区』/『市+区』/『省+市』完整地名串精确命中本地坐标。
    返回 dict 或 None。例：『四川省巴中市恩阳区』→ 恩阳区坐标；『巴中市恩阳区』→ 恩阳区坐标。"""
    if not city_name:
        return None
    key = _norm_region_all(str(city_name))
    if not key:
        return None
    if _regional_path_cache is None:
        _load_regional_cities()
    v = _regional_path_cache.get(key) if _regional_path_cache else None
    return dict(v) if v else None


# ===================== V10.11.27 自由搜索别名与景区兜底 =====================
# 景区通用后缀（剥离后能命中行政区划才采用）：『峨眉山风景区』→『峨眉山』
SCENIC_STRIP_SUFFIXES = (
    '风景名胜区', '风景区', '国家公园', '森林公园', '湿地公园', '地质公园',
    '度假区', '旅游区', '滑雪场', '景区', '古城', '古镇',
)

# 中文区县/地区别名表：官方区划名 ≠ 常用输入习惯的三类场景
#   ① 名胜古迹 → 所在标准区划；② 自治州俗称 → 州府/县级市（归一化仅剥『自治州』，『西双版纳』类无法直接命中）；
#   ③ 城市别称/历史旧称
DISTRICT_ALIASES = {
    # --- 名胜古迹 → 所在区划 ---
    '布达拉宫': '拉萨市', '大昭寺': '拉萨市', '纳木错': '当雄县',
    '乐山大佛': '乐山市', '峨眉山': '峨眉山市', '青城山': '都江堰市', '九寨沟': '九寨沟县',
    '黄龙': '松潘县', '稻城亚丁': '稻城县', '海螺沟': '泸定县', '四姑娘山': '小金县',
    '凤凰古城': '凤凰县', '张家界': '张家界市', '武陵源': '张家界市',
    '阳朔西街': '阳朔县', '漓江': '桂林市', '龙脊梯田': '龙胜县',
    '鼓浪屿': '厦门市', '武夷山': '武夷山市', '土楼': '永定区',
    '黄山': '黄山市', '宏村': '黟县', '西递': '黟县', '九华山': '青阳县',
    '泰山': '泰安市', '崂山': '青岛市', '蓬莱阁': '蓬莱区',
    '庐山': '庐山市', '井冈山': '井冈山市', '三清山': '玉山县', '婺源': '婺源县',
    '少林寺': '登封市', '龙门石窟': '洛阳市', '云台山': '修武县', '白云山': '洛阳市',
    '华山': '华阴市', '兵马俑': '西安市', '壶口瀑布': '吉县', '平遥古城': '平遥县',
    '五台山': '五台县', '云冈石窟': '大同市', '恒山': '浑源县', '应县木塔': '应县',
    '成吉思汗陵': '伊金霍洛旗', '呼伦贝尔': '呼伦贝尔市', '满洲里': '满洲里市',
    '长白山': '安图县', '雾凇岛': '吉林市', '雪乡': '大海林林业局',
    '莫高窟': '敦煌市', '鸣沙山': '敦煌市', '月牙泉': '敦煌市', '嘉峪关': '嘉峪关市',
    '茶卡盐湖': '乌兰县', '青海湖': '共和县', '塔尔寺': '湟中区',
    '西双版纳': '景洪市', '大理古城': '大理市', '洱海': '大理市', '丽江古城': '丽江市',
    '泸沽湖': '盐源县', '香格里拉': '香格里拉市', '玉龙雪山': '丽江市',
    '三亚湾': '三亚市', '亚龙湾': '三亚市', '天涯海角': '三亚市', '蜈支洲岛': '三亚市',
    '千岛湖': '淳安县', '西湖': '杭州市', '普陀山': '舟山市', '雁荡山': '乐清市',
    '婺州古城': '金华市', '三坊七巷': '福州市', '鼓山': '福州市',
    '三峡': '宜昌市', '神农架': '神农架林区', '武当山': '丹江口市', '恩施大峡谷': '恩施市',
    '黄果树': '镇宁县', '梵净山': '江口县', '荔波': '荔波县',
    '张家界大峡谷': '慈利县', '桂林山水': '桂林市',
    # --- 自治州俗称 → 州府/县级市 ---
    '延边': '延吉市', '凉山': '西昌市', '甘孜': '康定市', '阿坝': '马尔康市',
    '迪庆': '香格里拉市', '德宏': '芒市', '怒江': '泸水市', '大理州': '大理市',
    '湘西': '吉首市', '恩施州': '恩施市', '黔东南': '凯里市', '黔南': '都匀市',
    '黔西南': '兴义市', '临夏': '临夏市', '甘南': '合作市', '海西': '德令哈市',
    '黄南': '同仁市', '果洛': '玛沁县', '海南州': '共和县', '海北': '海晏县',
    '海东': '乐都区', '伊犁': '伊宁市', '巴州': '库尔勒市', '克州': '阿图什市',
    '博州': '博乐市', '克孜勒苏': '阿图什市', '大兴安岭': '加格达奇区',
    # --- 城市别称 / 历史旧称 ---
    '京城': '北京市', '北平': '北京市', '沪上': '上海市', '申城': '上海市',
    '金陵': '南京市', '长安': '西安市', '临安': '杭州市', '汴京': '开封市',
    '汴梁': '开封市', '羊城': '广州市', '花城': '广州市', '蓉城': '成都市',
    '锦城': '成都市', '山城': '重庆市', '渝州': '重庆市', '春城': '昆明市',
    '泉城': '济南市', '冰城': '哈尔滨市', '鹏城': '深圳市', '星城': '长沙市',
    '江城': '武汉市', '榕城': '福州市', '鹭岛': '厦门市',
}


def _alias_or_scenic_std(name):
    """别名/景区后缀 → 标准行政区划名。
    ① 直接命中别名表；② 剥离景区通用后缀后再查别名表；
    ③ 剥离后缀的原名（如『峨眉山风景区』→『峨眉山』，交由调用方再走精确/路径匹配）。
    返回 None 表示未产生任何标准名。"""
    raw = str(name or '').strip()
    if not raw:
        return None
    if raw in DISTRICT_ALIASES:
        return DISTRICT_ALIASES[raw]
    for suf in SCENIC_STRIP_SUFFIXES:
        if raw.endswith(suf) and len(raw) > len(suf):
            stripped = raw[:-len(suf)]
            if stripped in DISTRICT_ALIASES:
                return DISTRICT_ALIASES[stripped]
            return stripped
    return None


def _try_alias_match(raw, reg_index):
    """别名/景区后缀兜底：映射标准名后重走精确 + 归一化 + 全路径匹配；未命中返回 None"""
    std = _alias_or_scenic_std(raw)
    if not std or std == raw:
        return None
    if std in reg_index:
        return dict(reg_index[std])
    n2 = _norm_region(std)
    if n2 and n2 in reg_index:
        return dict(reg_index[n2])
    p2 = _match_path(std)
    if p2:
        return p2
    return None


def _region_level(info):
    """区划层级：0=区县 / 1=市 / 2=省（宽松匹配『最具体优先』排序用）
    判定依据索引条目的 admin2：为空=省级；等于 name=市级；否则=区县级"""
    adm2 = str((info or {}).get('admin2') or '')
    if not adm2:
        return 2
    return 1 if str((info or {}).get('name') or '') == adm2 else 0


def _find_cached_or_builtin_city(city_name, province=None, district_city=None):
    """从内存、磁盘缓存、全路径索引或全国行政区划索引中查找城市坐标"""
    if not city_name:
        return None
    raw = str(city_name).strip()
    norm = _norm_region(raw)

    with _weather_cache_lock:
        if raw in _mem_geocode_cache:
            return dict(_mem_geocode_cache[raw])
        if norm and norm in _mem_geocode_cache:
            return dict(_mem_geocode_cache[norm])

    disk_geo = _load_json_disk_cache(GEOCODE_CACHE_FILE)
    if raw in disk_geo:
        return dict(disk_geo[raw])
    if norm and norm in disk_geo:
        return dict(disk_geo[norm])

    reg_index = _load_regional_cities()
    if raw in reg_index:
        return dict(reg_index[raw])
    if norm and norm in reg_index:
        return dict(reg_index[norm])

    # V10.11.26 全路径匹配优先（『四川省巴中市恩阳区』等完整全名），
    # 必须在下方宽松匹配之前执行——否则『四川省巴中市恩阳区』会被『四川省』键抢先命中返回省级坐标
    path_hit = _match_path(raw)
    if path_hit:
        return path_hit

    if province or district_city:
        p_norm = _norm_region(province) if province else ''
        d_norm = _norm_region(district_city) if district_city else ''
        for k, v in reg_index.items():
            if (raw in k or (norm and norm in k)):
                adm1 = _norm_region(v.get('admin1', ''))
                adm2 = _norm_region(v.get('admin2', ''))
                if (p_norm and p_norm in adm1) or (d_norm and d_norm in adm2):
                    return dict(v)

    # V10.11.27 别名/景区后缀兜底：非常规输入（名胜古迹/自治州俗称/城市别称）映射标准名后
    # 重走精确+路径匹配——防止此类输入未命中而错误降级至地级市或走在线解析
    alias_hit = _try_alias_match(raw, reg_index)
    if alias_hit:
        return alias_hit

    # V10.11.27 宽松匹配升级：收集全部候选后按「最具体优先」排序——
    # 层级（区县>市>省）优先，同层级取命中键更长者；
    # 修复旧实现按 dict 遍历顺序返回第一个命中导致『XX景区』类输入误配上级/无关区划的问题
    loose = []
    for k, v in reg_index.items():
        hit = (k == raw or raw in k or k in raw)
        if not hit and norm:
            hit = (k == norm or norm in k or k in norm)
        if hit:
            loose.append((k, v))
    if loose:
        loose.sort(key=lambda kv: (_region_level(kv[1]), -len(kv[0])))
        return dict(loose[0][1])

    if district_city:
        d_norm = _norm_region(district_city)
        if d_norm in reg_index:
            res = dict(reg_index[d_norm])
            res['name'] = raw
            return res

    return None



def _synthesize_offline_forecast(latitude, longitude, timezone='auto', days=DEFAULT_FORECAST_DAYS):
    """外部天气 API 无法访问且无缓存时的季节性离线保底预报合成"""
    today = datetime.date.today()
    month = today.month
    try:
        lat = float(latitude)
    except Exception:
        lat = 30.0

    if lat >= 40:
        season_temps = {1: -5, 2: -2, 3: 5, 4: 13, 5: 20, 6: 25, 7: 28, 8: 27, 9: 21, 10: 13, 11: 4, 12: -3}
    elif lat >= 28:
        season_temps = {1: 6, 2: 9, 3: 14, 4: 19, 5: 24, 6: 28, 7: 32, 8: 31, 9: 26, 10: 20, 11: 14, 12: 8}
    else:
        season_temps = {1: 15, 2: 17, 3: 21, 4: 25, 5: 28, 6: 31, 7: 33, 8: 33, 9: 30, 10: 26, 11: 22, 12: 17}

    base_temp = season_temps.get(month, 20)

    daily_times = []
    daily_codes = []
    daily_max = []
    daily_min = []
    daily_precip = []
    daily_sunrise = []
    daily_sunset = []
    daily_uv = []
    daily_precip_sum = []

    for i in range(days):
        cur_d = today + datetime.timedelta(days=i)
        d_str = cur_d.strftime('%Y-%m-%d')
        daily_times.append(d_str)

        temp_jitter = ((i * 3 + int(lat)) % 7) - 3
        max_t = round(base_temp + 4.0 + temp_jitter, 1)
        min_t = round(base_temp - 4.0 + temp_jitter, 1)
        daily_max.append(max_t)
        daily_min.append(min_t)

        w_code = [1, 2, 0, 1, 3, 2, 61, 1][(i + int(lat)) % 8]
        daily_codes.append(w_code)
        daily_precip.append(60 if w_code == 61 else 10)
        daily_precip_sum.append(3.5 if w_code == 61 else 0.0)
        daily_sunrise.append(f"{d_str}T06:28")
        daily_sunset.append(f"{d_str}T17:52")
        daily_uv.append(5.0 if w_code in (0, 1) else 2.5)

    cur_temp = round(base_temp + 1.0, 1)
    return {
        '_offline_fallback': True,
        'current': {
            'temperature_2m': cur_temp,
            'apparent_temperature': cur_temp,
            'relative_humidity_2m': 58,
            'weather_code': daily_codes[0],
            'wind_speed_10m': 7.2,
            'surface_pressure': 1014.5,
            'cloud_cover': 30,
            'wind_direction_10m': 90,
            'wind_gusts_10m': 11.0,
            'time': f"{today.strftime('%Y-%m-%d')}T12:00",
        },
        'daily': {
            'time': daily_times,
            'weather_code': daily_codes,
            'temperature_2m_max': daily_max,
            'temperature_2m_min': daily_min,
            'precipitation_probability_max': daily_precip,
            'sunrise': daily_sunrise,
            'sunset': daily_sunset,
            'uv_index_max': daily_uv,
            'precipitation_sum': daily_precip_sum,
        }
    }


# 级联匹配辅助：行政区划名称归一化（去掉常见后缀，便于宽松匹配）
def _norm_region(name):
    if not name:
        return ''
    s = str(name).strip()
    # 依次去掉省/市/区/县/自治州/盟/旗等行政区划后缀词
    for suf in ('特别行政区', '维吾尔自治区', '壮族自治区', '回族自治区', '自治区',
                '省辖县级行政区划', '自治区直辖县级行政区划', '自治州', '地区',
                '自治县', '自治旗', '林区', '矿区', '新区', '县级市',
                '市辖区', '省', '市', '区', '县', '盟', '旗'):
        if s.endswith(suf) and len(s) > len(suf):
            s = s[:-len(suf)]
            break
    return s


def _norm_region_all(name):
    """V10.11.26 行政区划全后缀归一化：去除串内全部省/市/区/县等后缀，拼出纯地名路径。
    例：'四川省巴中市恩阳区' → '四川巴中恩阳'；'巴中市恩阳区' → '巴中恩阳'。
    用于自由搜索「省+市+区县」全名与内置路径索引精确匹配，修复全名被宽松匹配误配到省级的问题。
    """
    if not name:
        return ''
    s = str(name).strip()
    # 长后缀优先逐项替换（'维吾尔自治区' 必须先于 '自治区'，避免残留 '维吾尔'）
    for suf in ('特别行政区', '维吾尔自治区', '壮族自治区', '回族自治区', '自治区',
                '省辖县级行政区划', '自治区直辖县级行政区划', '自治州', '地区',
                '自治县', '自治旗', '林区', '矿区', '新区', '县级市',
                '市辖区', '省', '市', '区', '县', '盟', '旗'):
        s = s.replace(suf, '')
    # 顺带去除常见分隔符（点号/空格/短横/中括号），兼容『四川省 巴中市』等写法
    for ch in ('·', '、', ' ', '　', '-', '—', '（', '）', '(', ')'):
        s = s.replace(ch, '')
    return s


def _region_match(candidate_val, region_name):
    """候选字段与区划名宽松匹配（归一化后包含或相等）"""
    if not region_name:
        return False
    a = _norm_region(candidate_val)
    b = _norm_region(region_name)
    if not a or not b:
        return False
    return (a == b) or (a in b) or (b in a)


# ===================== Open-Meteo API 封装 =====================

# V10.11.7 网络策略：直连优先 + 系统代理兑底
# 背景：用户机器常开启梯子代理（IE/注册表级），代理不稳时 requests 默认走代理会持续超时；
#       而 Open-Meteo 国内直连通常可达。故先禁代理直连，失败再回落系统代理重试一次，
#       两种网络环境（直连可达 / 仅代理可达）均能覆盖。
HTTP_TIMEOUT = (5, 8)

# V10.11.20 端点默认值（与 service_config 默认一致；请求时以管理员配置为准）
GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
AIR_QUALITY_URL = 'https://air-quality-api.open-meteo.com/v1/air-quality'


def _http_get(url, params, timeout=HTTP_TIMEOUT):
    """GET 请求：① 禁代理直连（Session trust_env=False，绕过异常本地代理与权限限制）；② 失败回落系统代理"""
    try:
        with requests.Session() as s:
            s.trust_env = False
            return s.get(url, params=params, timeout=timeout)
    except (requests.Timeout, requests.RequestException, Exception):
        pass
    with requests.Session() as s:
        s.trust_env = True
        return s.get(url, params=params, timeout=timeout)


def _http_get_endpoint(group, params):
    """V10.11.20 多端点故障转移请求：
    按配置顺序遍历该组「启用」的端点，任一返回 HTTP 200 即成功；
    全部失败后按配置 retries 整轮重试（每轮重新遍历启用端点）；
    返回第一个 HTTP 200 的 Response；全部失败返回 None（调用方走现有降级路径）。
    超时：连接 5s + 读取 = 该组配置的 timeout（默认 8s）。
    V10.11.26：组内无任何启用端点时抛 ServiceDisabled（管理员明确停用），
    与「端点启用但网络不可达」（返回 None）严格区分——前者按业务语义报错，后者走缓存/离线合成兜底。
    """
    urls = service_config.get_enabled_urls(group)
    if not urls:
        raise ServiceDisabled(group)
    timeout = (5, service_config.get_timeout(group))
    retries = service_config.get_retries(group)
    for _round in range(retries + 1):
        for url in urls:
            try:
                resp = _http_get(url, params, timeout=timeout)
                if resp is not None and resp.status_code == 200:
                    return resp
            except Exception:
                continue
    return None


def geocode_city(city_name, province=None, district_city=None):
    """
    根据城市名解析经纬度与时区（Geocoding API）
    V10.11.7 级联模式：city_name=区县名，province/district_city=省/市名时，
    拉取多个候选并按 admin1/admin2 匹配度打分选最佳，避免同名区县错配
    返回: {name, latitude, longitude, timezone, country, admin1, admin2}
    失败: 抛出 WeatherError（未找到城市 / 服务异常 / 超时）
    具备离线与多级缓存保护：网络不可达时自动回落内置主要城市与历史查询缓存
    """
    cascade = bool(province or district_city)
    count = GEOCODE_CANDIDATES if cascade else 1

    # 先检查是否能在内存/磁盘缓存/全国权威区划索引中直接命中（0 延迟、免外网、零同名误配）
    cached_hit = _find_cached_or_builtin_city(city_name, province=province, district_city=district_city)
    if cached_hit:
        return cached_hit

    def _search(name):
        """单次地理编码请求，返回候选列表（无候选返回空列表；网络异常回落兜底）"""
        params = {
            'name': name,
            'count': count,
            'language': 'zh',
            'format': 'json',
        }
        try:
            # V10.11.20 多端点故障转移（配置的启用端点依次尝试，失败自动切换）
            resp = _http_get_endpoint('geocoding', params)
        except ServiceDisabled:
            # V10.11.26 明确停用：本地索引/缓存命中时仍可零网络解析（不依赖外部服务）；
            # 本地未命中（小地名需在线解析）时直接报错，不静默走缓存兜底
            if cached_hit:
                return [cached_hit]
            raise WeatherError('外部城市解析服务已停用，请在「系统设置 → 外部接口服务」中重新启用', 503)
        except (requests.Timeout, requests.RequestException, Exception):
            resp = None
        if resp is None:
            if cached_hit:
                return [cached_hit]
            fallback = _find_cached_or_builtin_city(name, province=province, district_city=district_city)
            if fallback:
                return [fallback]
            raise WeatherError(f'未找到该城市「{name}」，离线模式下支持国内各省市及区县查询（如北京、上海、广州等）', 404)

        try:
            data = resp.json()
        except ValueError:
            if cached_hit:
                return [cached_hit]
            raise WeatherError('城市解析服务返回数据异常', 502)

        # Open-Meteo 错误返回格式: {"error": true, "reason": "..."}
        if data.get('error'):
            if cached_hit:
                return [cached_hit]
            reason = data.get('reason') or '城市解析服务返回错误'
            raise WeatherError(reason, 502)
        return data.get('results') or []

    try:
        results = _search(city_name)
    except WeatherError as e:
        if cached_hit:
            results = [cached_hit]
        else:
            raise e

    # 级联模式 404 兜底：GeoNames 中文库部分区县需去掉「区/县/市」等后缀才能命中
    # （如「双流区」→「双流」），仅级联选择自动降级，自由文本输入保持原样提示
    if not results and cascade:
        stripped = _norm_region(city_name)
        if stripped and stripped != city_name:
            try:
                results = _search(stripped)
            except WeatherError:
                if cached_hit:
                    results = [cached_hit]

    if not results:
        if cached_hit:
            results = [cached_hit]
        else:
            raise WeatherError('未找到该城市，请检查城市名称是否正确', 404)

    # 级联模式：按省/市匹配度选最佳候选
    if cascade:
        def score(r):
            s = 0
            if _region_match(r.get('admin1'), province):
                s += 2
            if _region_match(r.get('admin2'), district_city):
                s += 2
            elif district_city and _region_match(r.get('name'), district_city):
                s += 1
            return -s
        results = sorted(results, key=score)

    r = results[0]
    # latitude / longitude 为必填字段，缺失视为数据异常
    if 'latitude' not in r or 'longitude' not in r:
        if cached_hit:
            r = cached_hit
        else:
            raise WeatherError('城市解析结果缺少坐标信息', 502)

    city_info = {
        'name': r.get('name') or city_name,
        'latitude': r['latitude'],
        'longitude': r['longitude'],
        # 时区优先使用地理编码返回值；缺失时由 Forecast 调用方回落 timezone=auto
        'timezone': r.get('timezone') or 'auto',
        'country': r.get('country') or '中国',
        'admin1': r.get('admin1') or '',
        'admin2': r.get('admin2') or '',
    }

    # 写入缓存
    try:
        with _weather_cache_lock:
            _mem_geocode_cache[city_name] = city_info
            norm_name = _norm_region(city_name)
            if norm_name:
                _mem_geocode_cache[norm_name] = city_info
        disk_geo = _load_json_disk_cache(GEOCODE_CACHE_FILE)
        disk_geo[city_name] = city_info
        if norm_name:
            disk_geo[norm_name] = city_info
        _save_json_disk_cache(GEOCODE_CACHE_FILE, disk_geo)
    except Exception:
        pass

    return city_info


def fetch_forecast(latitude, longitude, timezone='auto', days=DEFAULT_FORECAST_DAYS):
    """
    查询实时天气 + 每日预报（Forecast API，V10.11.7 起默认 15 天）
    注意: 请求 daily 数据时必须携带 timezone（auto 或地理编码返回值），否则接口报错
    返回: Open-Meteo 原始 JSON（已校验非错误响应）
    具备二级缓存（内存 TTL 30分钟 + 磁盘永久留存）与离线基线预报兜底，网络受限/不可达时不抛 503
    """
    # 天数规范化：默认 15，合法范围 [1, 16]
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = DEFAULT_FORECAST_DAYS
    days = max(1, min(MAX_FORECAST_DAYS, days))

    cache_key = f"{round(float(latitude), 2)},{round(float(longitude), 2)},{days}"
    now = time.time()

    # 1. 检查有效内存缓存（30 分钟新鲜度）
    with _weather_cache_lock:
        if cache_key in _mem_forecast_cache:
            ts, cached_obj = _mem_forecast_cache[cache_key]
            if now - ts < FORECAST_CACHE_TTL:
                return cached_obj

    params = {
        'latitude': latitude,
        'longitude': longitude,
        'current': (
            'temperature_2m,relative_humidity_2m,'
            'apparent_temperature,weather_code,wind_speed_10m,'
            'surface_pressure,cloud_cover,wind_direction_10m,wind_gusts_10m'
        ),
        'daily': (
            'weather_code,temperature_2m_max,'
            'temperature_2m_min,precipitation_probability_max,'
            'sunrise,sunset,uv_index_max,precipitation_sum'
        ),
        'timezone': timezone or 'auto',
        'forecast_days': days,
    }

    # 2. 尝试网络拉取
    network_data = None
    try:
        # V10.11.20 多端点故障转移（配置的启用端点依次尝试，失败自动切换）
        resp = _http_get_endpoint('forecast', params)
        if resp is not None and resp.status_code == 200:
            parsed = resp.json()
            if not parsed.get('error'):
                network_data = parsed
    except ServiceDisabled:
        # V10.11.26 明确停用：不走缓存/离线合成兜底，如实报错——
        # 避免管理员停用服务后天气页仍「正常」展示缓存/合成数据的假象
        raise WeatherError('外部天气预报服务已停用，请在「系统设置 → 外部接口服务」中重新启用', 503)
    except Exception:
        pass

    if network_data:
        # 网络获取成功，刷新内存缓存与磁盘缓存
        with _weather_cache_lock:
            _mem_forecast_cache[cache_key] = (now, network_data)
        try:
            d = _load_json_disk_cache(FORECAST_CACHE_FILE)
            d[cache_key] = {'ts': now, 'data': network_data}
            _save_json_disk_cache(FORECAST_CACHE_FILE, d)
        except Exception:
            pass
        return network_data

    # 3. 网络不可达/异常降级：检查内存缓存（即使过期也使用）
    with _weather_cache_lock:
        if cache_key in _mem_forecast_cache:
            _, old_data = _mem_forecast_cache[cache_key]
            res = dict(old_data)
            res['_cached'] = True
            res['_offline_fallback'] = True
            return res

    # 4. 检查磁盘缓存
    disk_data = _load_json_disk_cache(FORECAST_CACHE_FILE)
    if cache_key in disk_data and isinstance(disk_data[cache_key], dict) and 'data' in disk_data[cache_key]:
        res = dict(disk_data[cache_key]['data'])
        res['_cached'] = True
        res['_offline_fallback'] = True
        return res

    # 5. 若无任何历史缓存，启动季节性离线合成预报（保证页面永远不崩溃/不抛 503）
    return _synthesize_offline_forecast(latitude, longitude, timezone=timezone, days=days)


def fetch_air_quality(latitude, longitude):
    """
    查询空气质量（Air Quality API，V10.11.8 新增）
    返回: {'pm25': float|None, 'pm10': float|None, 'us_aqi': float|None}
    任何异常一律返回 None（空气质量为增强信息，失败不影响天气主查询）
    """
    params = {
        'latitude': latitude,
        'longitude': longitude,
        'current': 'pm10,pm2_5,us_aqi',
        'timezone': 'auto',
    }
    try:
        # V10.11.20 多端点故障转移（配置的启用端点依次尝试，失败自动切换）
        resp = _http_get_endpoint('air_quality', params)
        if resp is None:
            return None
        data = resp.json()
        if data.get('error'):
            return None
        cur = data.get('current') or {}
        return {
            'pm25': cur.get('pm2_5'),
            'pm10': cur.get('pm10'),
            'us_aqi': cur.get('us_aqi'),
        }
    except ServiceDisabled:
        # V10.11.26 空气质量为增强信息：明确停用同样静默降级（不影响主查询）
        return None
    except Exception:
        # 网络失败 / JSON 解析失败：静默降级
        return None


def _build_result(city, data, air_quality=None):
    """把 Open-Meteo forecast 原始 JSON 组装为前端结构化结果（V10.11.7 扩充指标）"""
    current = data.get('current') or {}
    daily = data.get('daily') or {}
    dates = daily.get('time') or []
    day_count = len(dates)
    # 与日期数组等长的空位占位，防止某字段缺失导致索引越界
    daily_codes = daily.get('weather_code') or [None] * day_count
    daily_max = daily.get('temperature_2m_max') or [None] * day_count
    daily_min = daily.get('temperature_2m_min') or [None] * day_count
    daily_precip = daily.get('precipitation_probability_max') or [None] * day_count
    daily_sunrise = daily.get('sunrise') or [None] * day_count
    daily_sunset = daily.get('sunset') or [None] * day_count
    daily_uv = daily.get('uv_index_max') or [None] * day_count
    daily_precip_sum = daily.get('precipitation_sum') or [None] * day_count

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
            'sunrise': daily_sunrise[i],
            'sunset': daily_sunset[i],
            'uv_index': daily_uv[i],
            'precipitation': daily_precip_sum[i],
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
            'wind_direction': current.get('wind_direction_10m'),
            'wind_direction_text': wind_direction_cn(current.get('wind_direction_10m')),
            'wind_gusts': current.get('wind_gusts_10m'),
            'pressure': current.get('surface_pressure'),
            'cloud_cover': current.get('cloud_cover'),
            'time': current.get('time'),
        },
        'daily': daily_list,
        # V10.11.8 空气质量（增强信息，接口不可达时为 None，前端降级不渲染）
        'air_quality': air_quality,
        'cached': bool(data.get('_cached')),
        'offline_fallback': bool(data.get('_offline_fallback')),
    }


def query_weather(city_name, province=None, district_city=None, days=DEFAULT_FORECAST_DAYS):
    """
    对外主入口 1：根据城市名查询天气（自由文本输入）
    （V10.11.7：15 天预报 + 级联匹配消歧 + 扩充指标）
    失败: 抛出 WeatherError（message 为中文提示，status_code 为建议 HTTP 状态码）
    """
    # 1. 城市名 → 经纬度/时区（级联模式下按省/市智能匹配候选）
    city = geocode_city(city_name, province=province, district_city=district_city)
    # 2. 查询实时 + 每日预报（必须传 timezone）
    data = fetch_forecast(city['latitude'], city['longitude'], city['timezone'], days=days)
    # 3. 空气质量（失败降级 None，不阻断主查询）
    air = fetch_air_quality(city['latitude'], city['longitude'])
    return _build_result(city, data, air_quality=air)


def query_weather_by_coords(latitude, longitude, days=DEFAULT_FORECAST_DAYS, label=''):
    """
    对外主入口 2：按经纬度直接查询天气（V10.11.7 级联选择专用）
    背景：GeoNames 中文库缺中国区县级地名（如「双流区」0 候选），
         级联选择改用「行政区划数据内置坐标」方案，选中区县后按坐标直查，
         不再依赖城市名搜索，零错配且省一次地理编码请求。
    参数：
      latitude / longitude  区县行政中心坐标（前端级联数据自带）
      label                 展示名称，如「四川省成都市双流区」
    """
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        raise WeatherError('坐标参数格式不正确', 400)
    # 中国陆域及周边粗校验：纬度 [3, 54]、经度 [73, 136]（含港澳台）
    if not (3 <= lat <= 54 and 73 <= lon <= 136):
        raise WeatherError('坐标超出中国行政区划范围', 400)

    city = {
        'name': label or '选定区域',
        'latitude': lat,
        'longitude': lon,
        'timezone': 'auto',
        'country': '中国',
        'admin1': '',
        'admin2': '',
    }
    data = fetch_forecast(lat, lon, 'auto', days=days)
    # V10.11.8 空气质量（失败降级 None，不阻断主查询）
    air = fetch_air_quality(lat, lon)
    return _build_result(city, data, air_quality=air)