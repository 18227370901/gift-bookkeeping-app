# -*- coding: utf-8 -*-
"""
天气查询路由模块
 负责：
   - GET /weather                 天气查询页面（V10.11.6 起受「天气」菜单权限管控）
   - GET /api/weather/query       天气查询 JSON API（V10.11.7：days 天数参数 + 级联省/市参数）
   - GET /api/holiday/year/<y>    法定节假日班/休 JSON API（V10.11.10：万年历模块班休角标）
参数说明：
   - city        城市名/区县名（自由文本或级联的末级地名，必填）
   - province    级联模式下的省名（可选，如「四川省」，用于候选城市智能匹配）
   - city2       级联模式下的市名（可选，如「成都市」）
   - days        预报天数（可选，默认 15，范围 1~16）
遵循项目现有路由组织方式：模块内定义 register_weather_routes(app)，
由 app.py 在应用初始化末尾调用注册。
"""
from flask import render_template, request, jsonify, current_app
from flask_login import login_required

from weather_service import (
    query_weather, query_weather_by_coords, WeatherError, CITY_NAME_MAX_LEN,
    DEFAULT_FORECAST_DAYS,
)
from holiday_service import get_year_holidays, HOLIDAY_YEAR_MIN, HOLIDAY_YEAR_MAX


def register_weather_routes(app):
    """注册天气相关路由"""

    @app.route('/weather')
    @login_required
    def weather_page():
        """天气查询页面（V10.11.6 起受「天气」菜单权限管控，拦截见 routes_ext.menu_map）"""
        return render_template('weather.html')

    @app.route('/api/weather/query', methods=['GET'])
    @login_required
    def api_weather_query():
        """天气查询 JSON API：默认 15 天预报
        两种查询模式（V10.11.7）：
          - 坐标模式（级联选择）：lat + lon + label，按区划内置坐标直查，零错配
          - 文本模式（自由输入）：city（可选 province/city2 消歧），走 Geocoding
        """
        # V10.11.7 预报天数：默认 15，后端再 clamp 一次防御
        days = request.args.get('days') or DEFAULT_FORECAST_DAYS

        lat = (request.args.get('lat') or '').strip()
        lon = (request.args.get('lon') or '').strip()

        # ---- 坐标模式（级联选择） ----
        if lat and lon:
            label = (request.args.get('label') or '').strip()
            if len(label) > CITY_NAME_MAX_LEN * 2:
                # label 为「省+市+区县」拼接串，放宽为 2 倍长度上限
                return jsonify({'code': 400, 'message': '地区名称过长'}), 400
            try:
                data = query_weather_by_coords(lat, lon, days=days, label=label)
            except WeatherError as e:
                return jsonify({'code': e.status_code, 'message': e.message}), e.status_code
            except Exception:
                current_app.logger.exception('查询天气异常: lat=%s lon=%s', lat, lon)
                return jsonify({'code': 500, 'message': '服务器内部错误，请稍后重试'}), 500
            return jsonify({'code': 200, 'message': 'ok', 'data': data})

        # ---- 文本模式（自由输入，兼容旧版） ----
        city = (request.args.get('city') or '').strip()
        if not city:
            return jsonify({'code': 400, 'message': '请输入城市名称'}), 400
        if len(city) > CITY_NAME_MAX_LEN:
            return jsonify({'code': 400,
                            'message': '城市名称过长（最多 {0} 个字符）'.format(CITY_NAME_MAX_LEN)}), 400

        # V10.11.7 级联消歧参数（可选，用于同名城市智能匹配）
        province = (request.args.get('province') or '').strip() or None
        city2 = (request.args.get('city2') or '').strip() or None

        try:
            data = query_weather(city, province=province, district_city=city2, days=days)
        except WeatherError as e:
            # Open-Meteo 业务错误 / 网络异常：直接透传中文提示
            return jsonify({'code': e.status_code, 'message': e.message}), e.status_code
        except Exception:
            # 未知异常：记录日志，不向用户暴露堆栈细节
            current_app.logger.exception('查询天气异常: city=%s', city)
            return jsonify({'code': 500, 'message': '服务器内部错误，请稍后重试'}), 500

        return jsonify({'code': 200, 'message': 'ok', 'data': data})

    @app.route('/api/holiday/year/<int:year>', methods=['GET'])
    @login_required
    def api_holiday_year(year):
        """法定节假日班/休 JSON API（V10.11.10：万年历模块班/休角标数据源）
        返回 {"MM-DD": {"holiday": bool, "name": str}}；
        holiday=true 为休假日（含调休连休），holiday=false 为调休补班日；
        拉取失败/无数据年份返回空字典（降级，前端仅不显示角标不影响万年历主体）。
        """
        if year < HOLIDAY_YEAR_MIN or year > HOLIDAY_YEAR_MAX:
            return jsonify({'code': 400, 'message': '年份超出支持范围（{0}~{1}）'.format(
                HOLIDAY_YEAR_MIN, HOLIDAY_YEAR_MAX)}), 400
        try:
            holiday = get_year_holidays(year)
        except Exception:
            current_app.logger.exception('获取 %d 年班/休数据异常', year)
            holiday = {}
        return jsonify({'code': 200, 'message': 'ok', 'data': {'year': year, 'holiday': holiday}})
