# -*- coding: utf-8 -*-
"""
天气查询路由模块
负责：
  - GET /weather                 天气查询页面（登录后可见）
  - GET /api/weather/query?city=  天气查询 JSON API（登录后可见）
遵循项目现有路由组织方式：模块内定义 register_weather_routes(app)，
由 app.py 在应用初始化末尾调用注册。
"""
from flask import render_template, request, jsonify, current_app
from flask_login import login_required

from weather_service import query_weather, WeatherError, CITY_NAME_MAX_LEN


def register_weather_routes(app):
    """注册天气相关路由"""

    @app.route('/weather')
    @login_required
    def weather_page():
        """天气查询页面（所有已登录用户可访问，无需菜单权限）"""
        return render_template('weather.html')

    @app.route('/api/weather/query', methods=['GET'])
    @login_required
    def api_weather_query():
        """根据城市名查询实时天气 + 未来 3 天预报，返回 JSON"""
        city = (request.args.get('city') or '').strip()
        if not city:
            return jsonify({'code': 400, 'message': '请输入城市名称'}), 400
        if len(city) > CITY_NAME_MAX_LEN:
            return jsonify({'code': 400,
                            'message': '城市名称过长（最多 {0} 个字符）'.format(CITY_NAME_MAX_LEN)}), 400

        try:
            data = query_weather(city)
        except WeatherError as e:
            # Open-Meteo 业务错误 / 网络异常：直接透传中文提示
            return jsonify({'code': e.status_code, 'message': e.message}), e.status_code
        except Exception:
            # 未知异常：记录日志，不向用户暴露堆栈细节
            current_app.logger.exception('查询天气异常: city=%s', city)
            return jsonify({'code': 500, 'message': '服务器内部错误，请稍后重试'}), 500

        return jsonify({'code': 200, 'message': 'ok', 'data': data})