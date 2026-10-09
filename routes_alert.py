# -*- coding: utf-8 -*-
"""
告警推送路由模块（V10.11.8）
负责：
  - GET  /admin/alerts/config      告警配置 + 当前用户操作权限快照（前端三态渲染依据）
  - POST /admin/alerts/config      保存告警配置（需 can_edit 权限；保存失败保留原配置）
  - POST /admin/alerts/test        发送测试推送（需 can_test 权限）
  - GET  /admin/alerts/logs        推送日志筛选查询（需 can_view_log 权限；按类型/时间/结果筛选）
  - GET  /admin/alerts/logs/csv    推送日志导出 CSV（需 can_view_log 权限）
  - GET  /admin/alerts/run         手动触发一轮巡检（需 can_edit 权限，便于验证）
  - GET/POST /admin/alerts/grants  操作授权管理（仅超级管理员）
权限联调规则：
  - 页面入口受 /admin/backups 既有门控（is_admin 或备份授权用户）；
    本模块全部接口再做操作级实时校验，权限被回收后下一次操作即 403（前端提示并跳转）
遵循项目现有路由组织方式：register_alert_routes(app) 由 app.py 调用注册。
"""
import csv
import io

from flask import (request, jsonify, current_app, Response)
from flask_login import login_required, current_user

from models import db, AlertPushConfig, AlertPushGrant, WebhookLog, User
from alert_service import (
    get_alert_config, get_alert_config_dict, has_alert_permission,
    has_any_alert_permission, send_test_alert, run_inspection_once,
    parse_alert_cities, MAX_ALERT_CITIES, ALERT_TYPE_NAMES,
)

# 允许筛选的告警相关事件类型（推送日志 event_type 维度）
ALERT_EVENT_TYPES = list(ALERT_TYPE_NAMES.keys())


def _alert_api_deny(message):
    """操作级权限拦截统一响应（403 + 中文提示，前端据此提示权限已变更）"""
    return jsonify({'success': False, 'message': message}), 403


def register_alert_routes(app):

    @app.route('/admin/alerts/config', methods=['GET'])
    @login_required
    def admin_alerts_config():
        """告警配置 + 权限快照：前端依据权限渲染可编辑/置灰/隐藏三态"""
        if not (getattr(current_user, 'is_admin', False) or
                getattr(current_user, 'backup_authorized', False)):
            return _alert_api_deny('权限不足：无备份管理访问权限')
        # 区块可见性：超级管理员或存在任意告警授权的用户可见完整区块
        visible = has_alert_permission(current_user, 'view')
        return jsonify({
            'success': True,
            'visible': visible,
            'config': get_alert_config_dict(),
            'perms': {
                'edit': has_alert_permission(current_user, 'edit'),
                'test': has_alert_permission(current_user, 'test'),
                'view_log': has_alert_permission(current_user, 'view_log'),
                'is_admin': bool(getattr(current_user, 'is_admin', False)),
            },
        })

    @app.route('/admin/alerts/config', methods=['POST'])
    @login_required
    def admin_alerts_config_save():
        """保存告警配置（需编辑权限；参数逐项校验，任一失败整体回滚保留原配置）"""
        if not has_alert_permission(current_user, 'edit'):
            return _alert_api_deny('权限已变更：您当前无告警配置编辑权限，页面即将刷新')
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}
        if not payload:
            return jsonify({'success': False, 'message': '请求数据格式不正确'}), 400

        cfg = get_alert_config()
        try:
            if 'enabled' in payload:
                cfg.enabled = bool(payload['enabled'])
            for key in ('weather_alert_on', 'interface_error_on', 'data_integrity_on', 'task_failed_on'):
                if key in payload:
                    setattr(cfg, key, bool(payload[key]))
            if 'silence_minutes' in payload:
                try:
                    silence = int(payload['silence_minutes'])
                except (TypeError, ValueError):
                    return jsonify({'success': False, 'message': '静默期必须为整数分钟'}), 400
                if silence < 0 or silence > 24 * 60:
                    return jsonify({'success': False, 'message': '静默期范围 0~1440 分钟'}), 400
                cfg.silence_minutes = silence
            if 'merge_push' in payload:
                cfg.merge_push = bool(payload['merge_push'])
            if 'alert_cities' in payload:
                cities = parse_alert_cities(payload['alert_cities'])
                if not cities:
                    return jsonify({'success': False, 'message': '请至少填写一个天气预警巡检城市'}), 400
                cfg.alert_cities = '，'.join(cities)
            db.session.commit()
        except Exception as e:
            # 保存失败：整体回滚，保留原配置，不影响菜单权限状态
            db.session.rollback()
            current_app.logger.exception('告警配置保存失败')
            return jsonify({'success': False, 'message': '保存失败：{0}（原配置已保留）'.format(e)}), 500

        return jsonify({
            'success': True,
            'message': '告警配置已保存并立即生效（巡检线程下一轮按新配置执行）',
            'config': get_alert_config_dict(),
        })

    @app.route('/admin/alerts/test', methods=['POST'])
    @login_required
    def admin_alerts_test():
        """发送测试推送（需测试权限；走真实渠道并即时反馈成败原因）"""
        if not has_alert_permission(current_user, 'test'):
            return _alert_api_deny('权限已变更：您当前无测试推送权限，页面即将刷新')
        ok, message = send_test_alert(current_user)
        return jsonify({'success': ok, 'message': message}), (200 if ok else 400)

    @app.route('/admin/alerts/run', methods=['POST'])
    @login_required
    def admin_alerts_run():
        """手动触发一轮巡检（需编辑权限；用于配置后立即验证，不必等 30 分钟）"""
        if not has_alert_permission(current_user, 'edit'):
            return _alert_api_deny('权限已变更：您当前无告警配置编辑权限，页面即将刷新')
        ok, summary = run_inspection_once()
        return jsonify({'success': ok, 'message': summary})

    @app.route('/admin/alerts/logs', methods=['GET'])
    @login_required
    def admin_alerts_logs():
        """推送日志筛选查询（需查看日志权限；按类型/时间范围/结果筛选）"""
        if not has_alert_permission(current_user, 'view_log'):
            return _alert_api_deny('权限已变更：您当前无推送日志查看权限，页面即将刷新')

        event_type = (request.args.get('event_type') or '').strip()
        result = (request.args.get('result') or '').strip()  # all / success / failed
        page = max(1, int(request.args.get('page', 1) or 1))
        per_page = min(100, max(10, int(request.args.get('per_page', 30) or 30)))

        query = WebhookLog.query.filter(WebhookLog.event_type.in_(ALERT_EVENT_TYPES))
        if event_type and event_type in ALERT_EVENT_TYPES:
            query = query.filter(WebhookLog.event_type == event_type)
        if result == 'success':
            query = query.filter(WebhookLog.is_success == True)  # noqa: E712
        elif result == 'failed':
            query = query.filter(WebhookLog.is_success == False)  # noqa: E712

        pagination = (query.order_by(WebhookLog.created_at.desc())
                      .paginate(page=page, per_page=per_page, error_out=False))
        items = []
        for log in pagination.items:
            items.append({
                'id': log.id,
                'event_type': log.event_type,
                'event_type_name': ALERT_TYPE_NAMES.get(log.event_type, log.event_type),
                'status_code': log.status_code,
                'is_success': bool(log.is_success),
                'response_body': (log.response_body or '')[:200],
                'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '',
            })
        return jsonify({
            'success': True,
            'items': items,
            'total': pagination.total,
            'page': page,
            'per_page': per_page,
            'pages': pagination.pages,
        })

    @app.route('/admin/alerts/logs/csv', methods=['GET'])
    @login_required
    def admin_alerts_logs_csv():
        """推送日志导出 CSV（需查看日志权限；便于审计）"""
        if not has_alert_permission(current_user, 'view_log'):
            return _alert_api_deny('权限已变更：您当前无推送日志查看权限，页面即将刷新')

        event_type = (request.args.get('event_type') or '').strip()
        query = WebhookLog.query.filter(WebhookLog.event_type.in_(ALERT_EVENT_TYPES))
        if event_type and event_type in ALERT_EVENT_TYPES:
            query = query.filter(WebhookLog.event_type == event_type)
        logs = query.order_by(WebhookLog.created_at.desc()).limit(5000).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', '时间', '类型', '类型名称', 'HTTP状态码', '是否成功', '响应摘要'])
        for log in logs:
            writer.writerow([
                log.id,
                log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else '',
                log.event_type,
                ALERT_TYPE_NAMES.get(log.event_type, log.event_type),
                log.status_code,
                '是' if log.is_success else '否',
                (log.response_body or '')[:500],
            ])
        data = output.getvalue()
        return Response(
            '\ufeff' + data,  # BOM：Excel 打开中文不乱码
            mimetype='text/csv; charset=utf-8',
            headers={'Content-Disposition': 'attachment; filename=alert_push_logs.csv'})

    @app.route('/admin/alerts/grants', methods=['GET'])
    @login_required
    def admin_alerts_grants():
        """授权管理查询（仅超级管理员）：全部用户与告警操作授权状态"""
        if not getattr(current_user, 'is_admin', False):
            return _alert_api_deny('仅超级管理员可管理告警操作授权')
        grants = {g.user_id: g for g in AlertPushGrant.query.all()}
        users = []
        for u in User.query.order_by(User.id).all():
            g = grants.get(u.id)
            users.append({
                'id': u.id,
                'username': u.username,
                'is_admin': bool(u.is_admin),
                'backup_authorized': bool(getattr(u, 'backup_authorized', False)),
                'can_edit': bool(u.is_admin) or bool(g and g.can_edit),
                'can_test': bool(u.is_admin) or bool(g and g.can_test),
                'can_view_log': bool(u.is_admin) or bool(g and g.can_view_log),
                'granted': g is not None,
            })
        return jsonify({'success': True, 'users': users})

    @app.route('/admin/alerts/grants', methods=['POST'])
    @login_required
    def admin_alerts_grants_save():
        """授权管理保存（仅超级管理员）：{user_id, can_edit, can_test, can_view_log}
        权限回收后：后台巡检线程下一轮检测无授权即自动停用推送（配置保留不生效）
        """
        if not getattr(current_user, 'is_admin', False):
            return _alert_api_deny('仅超级管理员可管理告警操作授权')
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}
        user_id = payload.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': '缺少用户参数'}), 400
        target = User.query.get(int(user_id))
        if target is None:
            return jsonify({'success': False, 'message': '用户不存在'}), 404
        if getattr(target, 'is_admin', False):
            return jsonify({'success': False, 'message': '超级管理员默认拥有全部权限，无需授权'}), 400

        can_edit = bool(payload.get('can_edit'))
        can_test = bool(payload.get('can_test'))
        can_view_log = bool(payload.get('can_view_log'))
        try:
            grant = AlertPushGrant.query.filter_by(user_id=target.id).first()
            if not (can_edit or can_test or can_view_log):
                # 全部回收：删除授权记录（权限回收 → 推送任务自动停用由巡检线程判定）
                if grant:
                    db.session.delete(grant)
                db.session.commit()
                message = '已回收用户 {0} 的全部告警操作权限'.format(target.username)
            else:
                if grant is None:
                    grant = AlertPushGrant(user_id=target.id)
                    db.session.add(grant)
                grant.can_edit = can_edit
                grant.can_test = can_test
                grant.can_view_log = can_view_log
                db.session.commit()
                message = '用户 {0} 的告警操作授权已更新（保存后立即生效）'.format(target.username)
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('告警授权保存失败')
            return jsonify({'success': False, 'message': '保存失败：{0}（原授权已保留）'.format(e)}), 500

        # 附加提示：权限全部回收后的联调效果
        if not has_any_alert_permission():
            message += '；当前无任何有效授权用户，告警推送将自动停用（配置保留）'
        return jsonify({'success': True, 'message': message})
