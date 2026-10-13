# -*- coding: utf-8 -*-
"""
天气查询路由模块
 负责：
    - GET /weather                 天气查询页面（V10.11.6 起受「天气」菜单权限管控）
    - GET /api/weather/query       天气查询 JSON API（V10.11.7：days 天数参数 + 级联省/市参数）
    - GET /api/holiday/year/<y>    法定节假日班/休 JSON API（V10.11.10：万年历模块班休角标）
    - GET /api/home/weather        首页背景横幅轻量天气 JSON API（V10.11.12，登录即可不挂 menu_map）
参数说明：
    - city        城市名/区县名（自由文本或级联的末级地名，必填；/api/home/weather 中为可选的“当前用户自己记忆的城市”）
    - province    级联模式下的省名（可选，如「四川省」，用于候选城市智能匹配）
    - city2       级联模式下的市名（可选，如「成都市」）
    - days        预报天数（可选，默认 15，范围 1~16）
遵循项目现有路由组织方式：模块内定义 register_weather_routes(app)，
由 app.py 在应用初始化末尾调用注册。
"""
import time as _time
from datetime import date as _date

from flask import render_template, request, jsonify, current_app
from flask_login import login_required, current_user

from weather_service import (
    query_weather, query_weather_by_coords, WeatherError, CITY_NAME_MAX_LEN,
    DEFAULT_FORECAST_DAYS,
)
from holiday_service import get_year_holidays, HOLIDAY_YEAR_MIN, HOLIDAY_YEAR_MAX
from models import SystemSetting

# ===================== V10.11.12 首页背景横幅天气 =====================
# 管理员从未查过天气时的兜底城市（V10.11.12 需求确认：默认成都）
_HOME_WEATHER_DEFAULT_CITY = '成都'
# 模块级轻量缓存：城市名 → (过期时间戳, 数据字典)；TTL 30 分钟（天气变化频率低，多用户常查同一城市命中率高）
_HOME_WEATHER_CACHE = {}
_HOME_WEATHER_TTL = 30 * 60


def _build_home_weather(city=None, lat=None, lon=None, label=None):
    """首页横幅轻量查询（当前实况 + 今明两日高低温，days=2 不拉全量预报）
    支持 coordinates 坐标直查 与 city 文本查询。失败返回 None。"""
    now = _time.time()
    cache_key = f"coords:{lat}:{lon}:{label}" if (lat and lon) else f"city:{city}"
    hit = _HOME_WEATHER_CACHE.get(cache_key)
    if hit and hit[0] > now:
        return hit[1]
    data = None
    try:
        if lat and lon:
            data = query_weather_by_coords(lat, lon, days=2, label=label or "")
        elif city:
            data = query_weather(city, days=2)
    except Exception:
        return None
    if not data:
        return None

    current = (data or {}).get("current") or {}
    daily = (data or {}).get("daily") or []
    city_info = (data or {}).get("city") or {}
    display_city = label or city_info.get("name") or city or "选定区域"
    payload = {
        "city": display_city,
        "temp": current.get("temperature"),
        "desc": current.get("weather_text") or "",
        "icon": current.get("icon") or "",
        "code": current.get("weather_code"),
        "today_max": (daily[0] or {}).get("temp_max") if daily else None,
        "today_min": (daily[0] or {}).get("temp_min") if daily else None,
        "tomorrow_max": (daily[1] or {}).get("temp_max") if len(daily) > 1 else None,
        "tomorrow_min": (daily[1] or {}).get("temp_min") if len(daily) > 1 else None,
        "update_time": current.get("time") or "",
    }
    _HOME_WEATHER_CACHE[cache_key] = (now + _HOME_WEATHER_TTL, payload)
    return payload


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
            # V10.11.16 管理员级联查询同步到系统设置，供无天气权限用户共享
            if getattr(current_user, "is_admin", False):
                try:
                    label_val = label or (data.get("city") or {}).get("name") or "选定区域"
                    SystemSetting.set_val("admin_weather_mode", "coords")
                    SystemSetting.set_val("admin_weather_city", label_val)
                    SystemSetting.set_val("admin_weather_lat", str(lat))
                    SystemSetting.set_val("admin_weather_lon", str(lon))
                except Exception:
                    current_app.logger.warning("admin_weather 级联落库失败", exc_info=True)
            return jsonify({"code": 200, "message": "ok", "data": data})

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

        # V10.11.12 首页背景横幅：管理员用自由输入框查询成功时，
        # 同步城市名到系统设置（供无天气权限用户背景共享；失败不影响本接口返回）
        if getattr(current_user, "is_admin", False):
            try:
                SystemSetting.set_val("admin_weather_mode", "text")
                SystemSetting.set_val("admin_weather_city", city)
                SystemSetting.set_val("admin_weather_lat", "")
                SystemSetting.set_val("admin_weather_lon", "")
            except Exception:
                current_app.logger.warning("admin_weather_city 落库失败: %s", city, exc_info=True)

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

    @app.route('/api/home/weather', methods=['GET'])
    @login_required
    def api_home_weather():
        """首页背景横幅轻量天气 JSON API（V10.11.12；登录即可访问，不挂 menu_map）
        城市决策（三层严格分流，服务端判定）：
          1. 当前用户有 weather 菜单权限 且 传入合法 city（自己记忆的自由输入城市）
             → 用该城市（source='user'，与天气页「城市名自由查询」记忆一致）
          2. 无权限 / 无 city / 参数非法
             → 管理员自由输入框记忆的城市（SystemSetting 'admin_weather_city'，
             由管理员在天气页每次成功查询时自动同步；source='admin'）
          3. 管理员从未查过天气
             → 兜底成都（source='default'）
        安全：无权限用户传入的任何 city 参数一律忽略
        （禁止无权限用户借本接口绕过 weather 菜单权限查任意城市）。
        附加：今日班/休徽章由服务端直接调用 holiday_service（模块函数）读取，
        避免前端调 /api/holiday/year（该接口挂 weather 权限门控）产生 403。
        降级：天气拉取失败 weather=null（前端隐藏天气区，横幅其余部分不受影响）。
        """
        # 1. 权限与地点分流解析
        has_perm = getattr(current_user, "is_admin", False) or (
            hasattr(current_user, "can_access_menu") and
            current_user.can_access_menu("weather"))

        raw_city = (request.args.get("city") or "").strip()
        raw_lat = (request.args.get("lat") or "").strip()
        raw_lon = (request.args.get("lon") or "").strip()
        raw_label = (request.args.get("label") or "").strip()

        target_city = None
        target_lat = None
        target_lon = None
        target_label = None
        source = "default"

        # 若当前用户有天气权限：优先采用用户最后一次查询的地点（不区分省市区级联或自由搜索）
        if has_perm:
            if raw_lat and raw_lon:
                try:
                    f_lat = float(raw_lat)
                    f_lon = float(raw_lon)
                    if 3 <= f_lat <= 54 and 73 <= f_lon <= 136:
                        target_lat = f_lat
                        target_lon = f_lon
                        target_label = raw_label[:CITY_NAME_MAX_LEN * 2] if raw_label else ""
                        source = "user"
                except (ValueError, TypeError):
                    pass
            elif raw_city and len(raw_city) <= CITY_NAME_MAX_LEN:
                target_city = raw_city
                source = "user"

        # 若当前用户无天气权限，或有权限但尚未有个人查询记录：默认回退到管理员预设地点
        if not target_city and not (target_lat and target_lon):
            admin_mode = (SystemSetting.get_val("admin_weather_mode") or "").strip()
            admin_city = (SystemSetting.get_val("admin_weather_city") or "").strip()
            admin_lat = (SystemSetting.get_val("admin_weather_lat") or "").strip()
            admin_lon = (SystemSetting.get_val("admin_weather_lon") or "").strip()
            if admin_mode == "coords" and admin_lat and admin_lon:
                try:
                    f_lat = float(admin_lat)
                    f_lon = float(admin_lon)
                    if 3 <= f_lat <= 54 and 73 <= f_lon <= 136:
                        target_lat = f_lat
                        target_lon = f_lon
                        target_label = admin_city or "选定区域"
                        source = "admin"
                except (ValueError, TypeError):
                    pass
            elif admin_city and len(admin_city) <= CITY_NAME_MAX_LEN:
                target_city = admin_city
                source = "admin"
            else:
                target_city = _HOME_WEATHER_DEFAULT_CITY
                source = "default"

        # 2. 轻量天气查询（30 分钟缓存 + 失败降级 None）
        weather = _build_home_weather(city=target_city, lat=target_lat, lon=target_lon, label=target_label)

        # 3. 今日班/休徽章
        badge = None
        try:
            today = _date.today()
            holidays = get_year_holidays(today.year) or {}
            info = holidays.get("%02d-%02d" % (today.month, today.day))
            if info:
                badge = {"holiday": bool(info.get("holiday")), "name": info.get("name") or ""}
        except Exception:
            pass

        # 4. 本月人情往来摘要
        ledger_summary = None
        try:
            from models import GiftRecord
            today = _date.today()
            first_day = today.replace(day=1)
            if today.month == 12:
                next_month = today.replace(year=today.year + 1, month=1, day=1)
            else:
                next_month = today.replace(month=today.month + 1, day=1)

            if getattr(current_user, "is_admin", False) or (hasattr(current_user, "can_view_others_for") and current_user.can_view_others_for("ledger")):
                l_q = GiftRecord.query.filter(GiftRecord.deleted_at.is_(None))
            else:
                l_q = GiftRecord.query.filter(GiftRecord.deleted_at.is_(None), GiftRecord.user_id == current_user.id)

            m_rows = l_q.with_entities(GiftRecord.amount, GiftRecord.record_type).filter(
                GiftRecord.created_at >= first_day,
                GiftRecord.created_at < next_month
            ).all()

            rec = sum((r.amount or 0) for r in m_rows if r.record_type not in ("send", "give"))
            snt = sum((r.amount or 0) for r in m_rows if r.record_type in ("send", "give"))
            ledger_summary = {
                "received": round(rec, 2),
                "sent": round(snt, 2),
                "net": round(rec - snt, 2),
                "count": len(m_rows)
            }
        except Exception:
            pass

        display_name = (weather.get("city") if weather else None) or target_label or target_city or _HOME_WEATHER_DEFAULT_CITY
        return jsonify({
            "code": 200,
            "message": "ok",
            "data": {
                "city": display_name,
                "source": source,
                "has_weather_permission": has_perm,
                "is_admin_preset": (not has_perm),
                "preset_notice": "这是管理员预设的地址" if not has_perm else None,
                "weather": weather,
                "badge": badge,
                "ledger": ledger_summary,
            }
        })
