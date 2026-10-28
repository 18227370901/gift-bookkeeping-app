# -*- coding: utf-8 -*-
"""
数据分析看板与海报统计业务服务（V10.11.15）
负责：
  - 抽取数据看板统计业务逻辑（PF-03 投影查询优化，CQ-02 Service层抽取）
  - 优化全表全量 ORM 加载为轻量元组投影，减少对象构建与内存消耗
  - 计算收送汇总、月度趋势、年度趋势、事由分布与 TOP 亲友往来
"""
from datetime import datetime, timedelta
from services.models import GiftRecord, SystemSetting


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

    net_rate = round((net_amount / total_received * 100), 1) if total_received > 0 else 0.0
    if total_count == 0:
        health_comment = "当前筛选周期内暂无记账数据，快去记录第一笔人情礼金吧！"
    elif net_amount > 0:
        health_comment = f"人情往来资金流良好，收礼大于随礼支出，实现人情顺差结余 ¥{net_amount:,.2f}（留存结余率 {net_rate}%）。"
    elif net_amount == 0:
        health_comment = "人情往来收支完全相抵平衡，礼尚往来，恰到好处。"
    else:
        health_comment = f"近期随礼支出相对集中，人情结余为逆差 ¥{abs(net_amount):,.2f}，属于正常的人情走动周期，建议关注短期资金流。"

    return {
        'summary': {
            'total_received': round(total_received, 2),
            'total_sent': round(total_sent, 2),
            'net_amount': round(net_amount, 2),
            'net_rate': net_rate,
            'health_comment': health_comment,
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


def calculate_reason_drilldown_stats(user, reason, start_month=None, end_month=None, start_year=None, end_year=None):
    """
    事由二级深度钻取分析：
    展示指定事由（如乔迁之喜、升学宴等）下的收礼/送礼金额、收支差额、参与亲友TOP10、时间走势与代表性明细
    """
    query = get_accessible_gift_query(user)
    if not reason:
        reason = "未分类"
    if reason == "其他" or reason == "未分类":
        query = query.filter((GiftRecord.event_reason == reason) | (GiftRecord.event_reason == None) | (GiftRecord.event_reason == ""))
    else:
        query = query.filter(GiftRecord.event_reason == reason)

    # 日期范围筛选
    if start_month and end_month:
        try:
            start_date = datetime.strptime(start_month + "-01", "%Y-%m-%d")
            end_date = datetime.strptime(end_month + "-01", "%Y-%m-%d")
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

    records = query.order_by(GiftRecord.created_at.desc()).all()

    total_received = 0.0
    total_sent = 0.0
    received_count = 0
    sent_count = 0

    contacts_map = {}
    monthly_trend_map = {}

    recent_items = []
    for r in records:
        amt = float(r.amount or 0.0)
        is_give = (r.record_type in ("send", "give"))
        if is_give:
            total_sent += amt
            sent_count += 1
        else:
            total_received += amt
            received_count += 1

        # 联系人统计
        cname = (r.name or "匿名").strip() or "匿名"
        if cname not in contacts_map:
            contacts_map[cname] = {"name": cname, "received": 0.0, "sent": 0.0, "count": 0}
        if is_give:
            contacts_map[cname]["sent"] += amt
        else:
            contacts_map[cname]["received"] += amt
        contacts_map[cname]["count"] += 1

        # 月度时间走势
        mkey = r.created_at.strftime("%Y-%m") if r.created_at else "未知"
        if mkey not in monthly_trend_map:
            monthly_trend_map[mkey] = {"month": mkey, "received": 0.0, "sent": 0.0}
        if is_give:
            monthly_trend_map[mkey]["sent"] += amt
        else:
            monthly_trend_map[mkey]["received"] += amt

        # 前 20 笔明细
        if len(recent_items) < 20:
            recent_items.append({
                "id": r.id,
                "name": r.name or "匿名",
                "record_type": r.record_type or "receive",
                "amount": round(amt, 2),
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
                "notes": r.notes or ""
            })

    for v in contacts_map.values():
        v["total"] = round(v["received"] + v["sent"], 2)
        v["received"] = round(v["received"], 2)
        v["sent"] = round(v["sent"], 2)
    top_contacts = sorted(contacts_map.values(), key=lambda x: x["total"], reverse=True)[:10]

    trend_list = sorted(monthly_trend_map.values(), key=lambda x: x["month"])
    for t in trend_list:
        t["received"] = round(t["received"], 2)
        t["sent"] = round(t["sent"], 2)

    net_amount = total_received - total_sent

    return {
        "reason": reason,
        "summary": {
            "total_count": len(records),
            "received_count": received_count,
            "sent_count": sent_count,
            "total_received": round(total_received, 2),
            "total_sent": round(total_sent, 2),
            "net_amount": round(net_amount, 2),
            "avg_amount": round((total_received + total_sent) / len(records), 2) if records else 0.0
        },
        "top_contacts": top_contacts,
        "monthly_trend": trend_list,
        "recent_items": recent_items
    }
