# -*- coding: utf-8 -*-
"""
告警消息推送服务（V10.11.8）
职责：
  1. 告警配置读写（AlertPushConfig 单行全局）与操作授权检查（AlertPushGrant 按用户授权）
  2. 四类触发条件检测：
     - weather_alert  天气预警：巡检配置城市，自研阈值规则
                      （强降温 ≥8℃ / 日降水概率 ≥70% / 阵风 ≥50km/h / 最低温 ≤0℃ / 最高温 ≥38℃）
     - interface_error 接口异常：巡检时天气/空气质量 API 调用失败
     - data_integrity 数据完整性：静态资源与关键文件存在性/非空检查
     - task_failed    定时任务失败：扫描巡检周期内失败的定时任务执行记录
  3. 频率控制：同类型告警静默期内不重复推送 + 一次巡检多告警合并为一条（防告警风暴）
  4. 推送执行：复用 webhook_utils.trigger_webhook_event（force_channels 走已启用通道，
     钉钉/飞书/企微长连接/pushplus/通用 Webhook 全部天然支持）
  5. 后台巡检守护线程（默认 30 分钟一轮；权限全部回收后自动停用推送，配置保留不生效）
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta

from flask import current_app

from models import db, AlertPushConfig, AlertPushGrant, WebhookConfig, ScheduledTaskExecutionLog, User

# ===================== 常量 =====================
# 告警类型 → 中文名（推送标题与日志分类共用）
ALERT_TYPE_NAMES = {
    'weather_alert': '天气预警',
    'interface_error': '接口异常',
    'data_integrity': '数据完整性',
    'task_failed': '定时任务失败',
    'alert_test': '测试推送',
}

# 巡检线程轮询间隔（秒）
INSPECT_INTERVAL_SECONDS = 30 * 60
# 定时任务失败回溯窗口（秒）：略大于巡检间隔，避免边界漏检
TASK_FAIL_LOOKBACK_SECONDS = INSPECT_INTERVAL_SECONDS + 5 * 60
# 天气预警巡检城市上限
MAX_ALERT_CITIES = 5

# 数据完整性检查的关键文件清单（相对应用根目录；缺失或空文件即告警）
INTEGRITY_FILES = [
    os.path.join('static', 'js', 'china-regions.js'),      # 行政区划数据（级联/本地匹配依赖）
    os.path.join('static', 'js', 'lunar_utils.js'),        # V10.11.9 万年历核心库（农历/干支/节气/节日，sxtwl 权威数据）
    os.path.join('static', 'js', 'table-resizer.js'),      # 表格列宽调整
    os.path.join('static', 'vendor', 'echarts', '5.5.0', 'echarts.min.js'),  # 图表（本地化）
    os.path.join('templates', 'weather.html'),
    os.path.join('templates', 'base.html'),
    'weather_service.py',
    'routes_weather.py',
    'alert_service.py',
]

# 巡检线程全局句柄（防重复启动）
_inspector_thread = None
_inspector_lock = threading.Lock()


# ===================== 配置与授权 =====================

def get_alert_config():
    """读取告警配置（无则初始化默认单行，默认全部关闭由管理员开启）"""
    cfg = AlertPushConfig.query.filter_by(id=1).first()
    if cfg is None:
        cfg = AlertPushConfig(id=1, enabled=False, weather_alert_on=False,
                              interface_error_on=False, data_integrity_on=False,
                              task_failed_on=False, silence_minutes=30,
                              merge_push=True, alert_cities='北京',
                              last_push_at='{}')
        db.session.add(cfg)
        db.session.commit()
    return cfg


def get_alert_config_dict():
    """配置 + 权限快照（前端渲染用；权限三态：可编辑/置灰/隐藏依据此判定）"""
    cfg = get_alert_config()
    return {
        'enabled': bool(cfg.enabled),
        'weather_alert_on': bool(cfg.weather_alert_on),
        'interface_error_on': bool(cfg.interface_error_on),
        'data_integrity_on': bool(cfg.data_integrity_on),
        'task_failed_on': bool(cfg.task_failed_on),
        'silence_minutes': cfg.silence_minutes or 30,
        'merge_push': bool(cfg.merge_push),
        'alert_cities': cfg.alert_cities or '北京',
        'last_inspect_time': cfg.last_inspect_time.strftime('%Y-%m-%d %H:%M:%S') if cfg.last_inspect_time else '',
        'updated_at': cfg.updated_at.strftime('%Y-%m-%d %H:%M:%S') if cfg.updated_at else '',
    }


def has_alert_permission(user, action):
    """操作权限检查
    action: 'edit'（可编辑配置）/ 'test'（可测试推送）/ 'view_log'（可查日志）/ 'view'（可见配置区块）
    规则：超级管理员（is_admin）默认全部权限；其他用户按 AlertPushGrant 判定
    """
    if user is None:
        return False
    if getattr(user, 'is_admin', False):
        return True
    grant = AlertPushGrant.query.filter_by(user_id=user.id).first()
    if grant is None:
        return False
    if action == 'edit':
        return bool(grant.can_edit)
    if action == 'test':
        return bool(grant.can_test)
    if action == 'view_log':
        return bool(grant.can_view_log)
    if action == 'view':
        return True  # 存在任意授权记录即可见区块
    return False


def has_any_alert_permission():
    """是否存在有效授权对象（超级管理员或任一授权记录）
    「权限被动态回收 → 后台告警任务同步停用」：无任何有效授权时巡检只跳过推送，配置保留不生效
    """
    if User.query.filter_by(is_admin=True).first() is not None:
        return True
    return AlertPushGrant.query.first() is not None


def get_active_webhooks():
    """已启用的 Webhook 通道（告警推送目标；告警为系统级通知，取全部启用通道）"""
    return WebhookConfig.query.filter_by(is_enabled=True).all()


def parse_alert_cities(raw):
    """解析巡检城市串（逗号/顿号分隔），去重限上限"""
    if not raw:
        return []
    seen, result = set(), []
    for part in str(raw).replace('，', ',').replace('、', ',').split(','):
        city = part.strip()
        if city and city not in seen:
            seen.add(city)
            result.append(city)
        if len(result) >= MAX_ALERT_CITIES:
            break
    return result


# ===================== 频率控制 =====================

def _load_last_push(cfg):
    try:
        data = json.loads(cfg.last_push_at or '{}')
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def should_push(cfg, alert_type):
    """静默期判定：同类型告警在 silence_minutes 内不重复推送"""
    last = _load_last_push(cfg).get(alert_type)
    if not last:
        return True
    try:
        last_dt = datetime.strptime(str(last), '%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return True
    silence = max(0, int(cfg.silence_minutes or 0))
    if silence == 0:
        return True
    return (datetime.now() - last_dt).total_seconds() >= silence * 60


def mark_pushed(cfg, alert_type):
    """记录该类型本次推送时间（持久化，服务重启后静默期依然有效）"""
    data = _load_last_push(cfg)
    data[alert_type] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cfg.last_push_at = json.dumps(data, ensure_ascii=False)
    db.session.commit()


# ===================== 推送执行 =====================

def push_alert(alert_type, title, details, operator_id=None, skip_silence=False):
    """推送单条告警
    返回 (ok: bool, message: str)
    """
    from webhook_utils import trigger_webhook_event

    cfg = get_alert_config()
    if not cfg.enabled and not skip_silence:
        return False, '告警推送总开关已关闭'
    if not skip_silence and not should_push(cfg, alert_type):
        return False, '该类型告警处于静默期内，本次不重复推送'

    webhooks = get_active_webhooks()
    if not webhooks:
        return False, '无已启用的 Webhook 通道，请先在「Webhook通知」页配置并启用'

    try:
        # force_channels=True：系统告警为强制推送，跳过事件开关/页面矩阵/用户监控过滤
        trigger_webhook_event(
            webhooks, alert_type, title, details,
            force_channels=True, operator_id=operator_id,
        )
    except Exception as e:
        return False, '推送执行异常: {0}'.format(e)
    if not skip_silence:
        mark_pushed(cfg, alert_type)
    return True, '已推送至 {0} 个启用通道'.format(len(webhooks))


def send_test_alert(user):
    """测试推送（仅测试权限角色可见入口；走真实渠道，即时反馈成败）"""
    webhooks = get_active_webhooks()
    if not webhooks:
        return False, '无已启用的 Webhook 通道，请先在「Webhook通知」页配置并启用'
    title = '【系统告警·测试推送】'
    details = ('测试触发人: {0} | 测试时间: {1} | 说明: 本消息为告警推送配置测试，'
               '收到即表示通道正常。').format(
        getattr(user, 'username', 'admin'),
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    try:
        from webhook_utils import trigger_webhook_event
        trigger_webhook_event(
            webhooks, 'alert_test', title, details,
            force_channels=True, operator_id=getattr(user, 'id', None),
        )
    except Exception as e:
        return False, '测试推送异常: {0}'.format(e)
    return True, '测试消息已发送至 {0} 个启用通道，请到对应群/客户端查收'.format(len(webhooks))


# ===================== 四类触发条件检测 =====================

def check_weather_alerts(cfg):
    """天气预警检测（巡检配置城市，自研阈值规则）
    返回 (alerts: list[str], interface_errors: list[str])
    """
    alerts, interface_errors = [], []
    cities = parse_alert_cities(cfg.alert_cities)
    if not cities:
        return alerts, interface_errors

    from weather_service import query_weather

    for city in cities:
        try:
            data = query_weather(city, days=8)
        except Exception as e:
            # 巡检发现天气接口异常 → 供 interface_error 告警使用
            interface_errors.append('{0}: {1}'.format(city, str(e)[:120]))
            continue

        daily = (data or {}).get('daily') or []
        current = (data or {}).get('current') or {}
        if not daily:
            continue

        # 规则 1：强降温（当日最高温与未来 7 日内最低温落差 ≥8℃）
        try:
            today_max = daily[0].get('temp_max')
            future_mins = [d.get('temp_min') for d in daily[1:7] if d.get('temp_min') is not None]
            if today_max is not None and future_mins and (float(today_max) - min(future_mins)) >= 8:
                alerts.append('{0}：未来一周强降温（最高 {1}℃ → 最低 {2}℃，降幅 {3}℃）'.format(
                    city, today_max, min(future_mins), round(float(today_max) - min(future_mins), 1)))
        except (TypeError, ValueError):
            pass

        # 规则 2：强降水（任一日降水概率 ≥70%）
        rain_days = [d for d in daily[:7] if d.get('precip_prob') is not None and float(d['precip_prob']) >= 70]
        if rain_days:
            first = rain_days[0]
            alerts.append('{0}：{1} 强降水（降水概率 {2}%）'.format(city, str(first.get('date', ''))[5:], first.get('precip_prob')))

        # 规则 3：大风（阵风 ≥50 km/h）
        gust = current.get('wind_gusts')
        if gust is not None:
            try:
                if float(gust) >= 50:
                    alerts.append('{0}：当前大风（阵风 {1} km/h）'.format(city, gust))
            except (TypeError, ValueError):
                pass

        # 规则 4：冰冻（任一日最低温 ≤0℃）
        freeze_days = [d for d in daily[:7] if d.get('temp_min') is not None and float(d['temp_min']) <= 0]
        if freeze_days:
            alerts.append('{0}：{1} 低温冰冻（最低 {2}℃）'.format(city, str(freeze_days[0].get('date', ''))[5:], freeze_days[0].get('temp_min')))

        # 规则 5：高温（任一日最高温 ≥38℃）
        hot_days = [d for d in daily[:7] if d.get('temp_max') is not None and float(d['temp_max']) >= 38]
        if hot_days:
            alerts.append('{0}：{1} 高温（最高 {2}℃）'.format(city, str(hot_days[0].get('date', ''))[5:], hot_days[0].get('temp_max')))

    return alerts, interface_errors


def check_data_integrity():
    """数据完整性检测：关键静态资源/文件存在性与非空检查（本项无外部网络依赖）"""
    issues = []
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in INTEGRITY_FILES:
        path = os.path.join(base_dir, rel)
        try:
            if not os.path.exists(path) or os.path.getsize(path) <= 0:
                issues.append('文件缺失或为空: {0}'.format(rel))
        except OSError:
            issues.append('文件不可访问: {0}'.format(rel))
    return issues


def check_task_failures():
    """定时任务失败检测：扫描回溯窗口内失败的执行记录（去重：同窗口内已推送过的不再报）"""
    try:
        since = datetime.now() - timedelta(seconds=TASK_FAIL_LOOKBACK_SECONDS)
        failed_logs = (ScheduledTaskExecutionLog.query
                       .filter(ScheduledTaskExecutionLog.status == 'failed')
                       .filter(ScheduledTaskExecutionLog.end_time >= since)
                       .order_by(ScheduledTaskExecutionLog.end_time.desc())
                       .all())
    except Exception:
        return []
    alerts = []
    seen_tasks = set()
    for log in failed_logs:
        task_id = log.task_id
        if task_id in seen_tasks:
            continue
        seen_tasks.add(task_id)
        output = (log.output_log or '').strip()
        if len(output) > 80:
            output = output[:80] + '…'
        when = log.end_time.strftime('%H:%M') if log.end_time else '未知时间'
        alerts.append('任务#{0} 失败（{1}）：{2}'.format(task_id, when, output or '未记录原因'))
    return alerts


# ===================== 巡检主流程与守护线程 =====================

def run_inspection_once():
    """执行一轮巡检（由守护线程调用；也可手动触发用于验证）
    联调规则：
      - 总开关关闭 → 跳过
      - 无任何有效授权（权限全部回收）→ 跳过推送（配置保留不生效，不产生孤儿任务）
      - 各类型分别受独立开关 + 静默期控制
    返回 (ok, summary)
    """
    cfg = get_alert_config()
    if not cfg.enabled:
        return False, '告警推送总开关已关闭，本轮巡检跳过'
    if not has_any_alert_permission():
        return False, '无有效告警授权用户（权限已全部回收），推送自动停用'

    collected = []  # [(alert_type, message)]

    # 1) 天气预警 + 接口异常（巡检天气接口本身，失败即接口异常事件源）
    weather_alerts, interface_errors = [], []
    if cfg.weather_alert_on or cfg.interface_error_on:
        weather_alerts, interface_errors = check_weather_alerts(cfg)
    if cfg.weather_alert_on:
        for msg in weather_alerts:
            collected.append(('weather_alert', msg))
    if cfg.interface_error_on:
        for msg in interface_errors:
            collected.append(('interface_error', '天气接口调用失败 - ' + msg))

    # 2) 数据完整性
    if cfg.data_integrity_on:
        for msg in check_data_integrity():
            collected.append(('data_integrity', msg))

    # 3) 定时任务失败
    if cfg.task_failed_on:
        for msg in check_task_failures():
            collected.append(('task_failed', msg))

    # 记录巡检时间（供前端展示）
    try:
        cfg.last_inspect_time = datetime.now()
        db.session.commit()
    except Exception:
        db.session.rollback()

    if not collected:
        return True, '巡检完成，无告警事件'

    # 静默期过滤（逐类型判定，静默期内的告警丢弃）
    audible = []
    for alert_type, msg in collected:
        if should_push(cfg, alert_type):
            audible.append((alert_type, msg))

    if not audible:
        return True, '发现 {0} 条告警事件，但均处于静默期内未推送'.format(len(collected))

    # 推送执行：按类型分组，同类型多条在 merge_push 开启时合并为一条消息
    # （跨类型分别推送，保证推送日志 event_type 分类准确、静默期按类型独立记录）
    by_type = {}
    for alert_type, msg in audible:
        by_type.setdefault(alert_type, []).append(msg)

    success_count, total_msgs = 0, 0
    for alert_type, msgs in by_type.items():
        cn = ALERT_TYPE_NAMES.get(alert_type, alert_type)
        if cfg.merge_push and len(msgs) > 1:
            title = '【系统告警·{0}】巡检发现 {1} 条告警'.format(cn, len(msgs))
            details = '\n'.join('- {0}'.format(m) for m in msgs)
            ok, _ = push_alert(alert_type, title, details, skip_silence=True)
            if ok:
                mark_pushed(cfg, alert_type)
                success_count += len(msgs)
            total_msgs += len(msgs)
        else:
            for msg in msgs:
                ok, _ = push_alert(alert_type, '【系统告警·{0}】'.format(cn), msg, skip_silence=True)
                if ok:
                    mark_pushed(cfg, alert_type)
                    success_count += 1
                total_msgs += 1
    return True, '推送完成：{0}/{1} 条告警成功（其余为通道异常或无启用通道）'.format(success_count, total_msgs)


def start_alert_inspector(app):
    """启动告警巡检守护线程（daemon；进程退出自动结束，不产生孤儿任务）
    与备份调度线程同模式：每轮独立 app_context，异常不中断线程
    """
    global _inspector_thread
    with _inspector_lock:
        if _inspector_thread is not None and _inspector_thread.is_alive():
            return
        _inspector_thread = threading.Thread(
            target=_inspector_loop, args=(app,), daemon=True, name='alert-inspector')
        _inspector_thread.start()


def _inspector_loop(app):
    """巡检循环：首轮延迟 60 秒（避开启动高峰），此后每 30 分钟一轮"""
    time.sleep(60)
    count = 0
    while True:
        try:
            with app.app_context():
                ok, summary = run_inspection_once()
                print('[Alert Inspector] 第 {0} 轮巡检: {1}'.format(count + 1, summary))
        except Exception as e:
            # 单轮异常不影响后续巡检
            try:
                print('[Alert Inspector Error] {0}'.format(e))
            except Exception:
                pass
        count += 1
        time.sleep(INSPECT_INTERVAL_SECONDS)
