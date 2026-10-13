# -*- coding: utf-8 -*-
"""
数据分析看板与海报统计业务服务（V10.11.15）
负责：
  - 抽取数据看板统计业务逻辑（PF-03 投影查询优化，CQ-02 Service层抽取）
  - 优化全表全量 ORM 加载为轻量元组投影，减少对象构建与内存消耗
  - 计算收送汇总、月度趋势、年度趋势、事由分布与 TOP 亲友往来
"""
from datetime import datetime, timedelta
from models import GiftRecord, SystemSetting


def get_accessible_gift_query(user):
    """获取当前用户可访问的礼金记录基础查询对象"""
    if getattr(user, 'is_admin', False) or (hasattr(user, 'can_view_others_for') and user.can_view_others_for('ledger')):
        return GiftRecord.query.filter(GiftRecord.deleted_at.is_(None))
    return GiftRecord.query.filter(GiftRecord.deleted_at.is_(None), GiftRecord.user_id == getattr(user, 'id'))


def calculate_dashboard_stats(user, start_month=None, end_month=None, start_year=None, end_year=None):
    """计算数据看板综合统计数据（汇总/月度/年度/事由/TOP10）"""
    query = get_accessible_gift_query(user)

    # 根据月度范围筛选
    if start_month and end_month:
        try:
            start_date = datetime.strptime(start_month + '-01', '%Y-%m-%d')
            end_date = datetime.strptime(end_month + '-01', '%Y-%m-%d')
            if end_date.month == 12:
                end_date = end_date.replace(day=31)
            else:
                end_date = end_date.replace(month=end_date.month + 1, day=1) - timedelta(days=1)
            query = query.filter(GiftRecord.created_at >= start_date, GiftRecord.created_at <= end_date)
        except Exception:
            pass
    elif start_year and end_year:
        try:
            start_date = datetime(int(start_year), 1, 1)
            end_date = datetime(int(end_year), 12, 31, 23, 59, 59)
            query = query.filter(GiftRecord.created_at >= start_date, GiftRecord.created_at <= end_date)
        except Exception:
            pass

    # PF-03: 轻量字段投影查询，避免全量 ORM 实例化的昂贵开销
    rows = query.with_entities(
        GiftRecord.amount,
        GiftRecord.record_type,
        GiftRecord.event_reason,
        GiftRecord.name,
        GiftRecord.created_at
    ).order_by(GiftRecord.created_at.desc()).all()

    # 汇总统计
    total_received = sum((r.amount or 0) for r in rows if r.record_type not in ('send', 'give'))
    total_sent = sum((r.amount or 0) for r in rows if r.record_type in ('send', 'give'))
    net_amount = total_received - total_sent
    total_count = len(rows)

    # 月度趋势
    monthly_map = {}
    for r in rows:
        month_key = r.created_at.strftime('%Y-%m') if r.created_at else '未知'
        if month_key not in monthly_map:
            monthly_map[month_key] = {'month': month_key, 'received': 0, 'sent': 0}
        if r.record_type in ('send', 'give'):
            monthly_map[month_key]['sent'] += (r.amount or 0)
        else:
            monthly_map[month_key]['received'] += (r.amount or 0)
    monthly_trend = sorted(monthly_map.values(), key=lambda x: x['month'])

    # 年度趋势
    yearly_map = {}
    for r in rows:
        year_key = str(r.created_at.year) if r.created_at else '未知'
        if year_key not in yearly_map:
            yearly_map[year_key] = {'year': year_key, 'received': 0, 'sent': 0}
        if r.record_type in ('send', 'give'):
            yearly_map[year_key]['sent'] += (r.amount or 0)
        else:
            yearly_map[year_key]['received'] += (r.amount or 0)
    yearly_trend = sorted(yearly_map.values(), key=lambda x: x['year'])

    # 事由分布
    reason_map = {}
    for r in rows:
        reason = r.event_reason or '其它'
        if reason not in reason_map:
            reason_map[reason] = {'reason': reason, 'count': 0, 'amount': 0}
        reason_map[reason]['count'] += 1
        reason_map[reason]['amount'] += (r.amount or 0)
    reason_distribution = sorted(reason_map.values(), key=lambda x: x['amount'], reverse=True)

    # TOP10 亲友往来
    contact_map = {}
    for r in rows:
        name = (r.name or '').strip()
        if not name:
            continue
        if name not in contact_map:
            contact_map[name] = {'name': name, 'received': 0, 'sent': 0, 'count': 0}
        if r.record_type in ('send', 'give'):
            contact_map[name]['sent'] += (r.amount or 0)
        else:
            contact_map[name]['received'] += (r.amount or 0)
        contact_map[name]['count'] += 1
    for v in contact_map.values():
        v['total'] = v['received'] + v['sent']
    top10_contacts = sorted(contact_map.values(), key=lambda x: x['total'], reverse=True)[:10]

    return {
        'summary': {
            'total_received': round(total_received, 2),
            'total_sent': round(total_sent, 2),
            'net_amount': round(net_amount, 2),
            'total_count': total_count
        },
        'monthly_trend': monthly_trend,
        'yearly_trend': yearly_trend,
        'reason_distribution': reason_distribution,
        'top10_contacts': top10_contacts
    }


def calculate_poster_stats(user, root_url=None):
    """计算分享长图海报所需的聚合统计数据"""
    query = get_accessible_gift_query(user)
    rows = query.with_entities(
        GiftRecord.amount,
        GiftRecord.record_type,
        GiftRecord.event_reason,
        GiftRecord.name,
        GiftRecord.created_at
    ).order_by(GiftRecord.created_at.desc()).all()

    total_received = sum((r.amount or 0) for r in rows if r.record_type not in ('send', 'give'))
    total_sent = sum((r.amount or 0) for r in rows if r.record_type in ('send', 'give'))

    # TOP5
    contact_map = {}
    for r in rows:
        name = (r.name or '').strip()
        if not name:
            continue
        if name not in contact_map:
            contact_map[name] = {'name': name, 'received': 0, 'sent': 0}
        if r.record_type in ('send', 'give'):
            contact_map[name]['sent'] += (r.amount or 0)
        else:
            contact_map[name]['received'] += (r.amount or 0)
    for v in contact_map.values():
        v['total'] = v['received'] + v['sent']
    top5 = sorted(contact_map.values(), key=lambda x: x['total'], reverse=True)[:5]

    # 事由分布
    reason_map = {}
    total_reason_amount = 0
    for r in rows:
        reason = r.event_reason or '其它'
        if reason not in reason_map:
            reason_map[reason] = {'reason': reason, 'amount': 0}
        reason_map[reason]['amount'] += (r.amount or 0)
        total_reason_amount += (r.amount or 0)
    reasons = []
    for v in sorted(reason_map.values(), key=lambda x: x['amount'], reverse=True):
        v['percentage'] = round(v['amount'] / total_reason_amount * 100, 1) if total_reason_amount > 0 else 0
        reasons.append(v)

    qr_url = SystemSetting.get_val('poster_qr_url', '')
    if not qr_url:
        qr_url = (root_url or '').rstrip('/') + '/register'

    return {
        'year': datetime.now().year,
        'summary': {
            'total_received': round(total_received, 2),
            'total_sent': round(total_sent, 2),
            'net_amount': round(total_received - total_sent, 2),
            'total_count': len(rows)
        },
        'top5': top5,
        'reasons': reasons,
        'qr_url': qr_url
    }
