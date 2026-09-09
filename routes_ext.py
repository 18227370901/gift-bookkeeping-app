# -*- coding: utf-8 -*-
import os
import io
import time
import urllib.parse
import threading
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify, send_from_directory, make_response, Response, session, current_app
from flask_login import login_required, current_user
from models import (
    db, User, GiftRecord, Banquet, AnniversaryReminder, Broadcast, BroadcastRead,
    WebhookConfig, WebhookLog, SharedLedgerLink, BackupConfig, LoginRisk, SecurityRisk,
    SystemSetting
)
from webhook_utils import trigger_webhook_event, test_single_webhook, validate_wecom_credentials, extract_chatid_from_url, start_wecom_long_connection_listener, _cached_chatids, record_webhook_log, _send_payload, send_wecom_long_connection_message
from webdav_utils import (
    test_connection as test_webdav_connection,
    upload_backup as upload_backup_webdav,
    list_backups as list_webdav_backups,
    download_backup as restore_webdav_backup
)
from gift_utils import (
    parse_gift_nlp, parse_gift_nlp_multi, split_gift_nlp_text,
    get_gift_suggestion, calculate_reconciliation, cn2num
)



def parse_target_date_obj(date_val, today=None):
    if not date_val:
        return None, 9999
    if today is None:
        today = datetime.now().date()

    month, day = None, None
    if hasattr(date_val, 'month') and hasattr(date_val, 'day'):
        month, day = date_val.month, date_val.day
    else:
        s = str(date_val).strip()
        for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%m-%d', '%m/%d'):
            try:
                dt = datetime.strptime(s, fmt)
                month, day = dt.month, dt.day
                break
            except Exception:
                continue

    if not month or not day:
        return None, 9999

    try:
        this_year_date = datetime(today.year, month, day).date()
    except ValueError:
        this_year_date = datetime(today.year, month, 28).date()

    if this_year_date < today:
        try:
            this_year_date = datetime(today.year + 1, month, day).date()
        except ValueError:
            this_year_date = datetime(today.year + 1, month, 28).date()

    days_left = (this_year_date - today).days
    return this_year_date, days_left


def format_reminder_notification_content(reminders_with_days):
    """
    格式化亲友纪念日提醒通知内容（准确展示所有详细内容，消除【其它】这类模糊信息）
    reminders_with_days: list of (reminder_obj, days_left, next_date_obj)
    """
    if not reminders_with_days:
        return "【亲友重要纪念日提醒】", "当前暂无临近的亲友纪念日。", []

    count = len(reminders_with_days)
    title = f"【亲友重要纪念日提醒】 近期有 {count} 位亲友重要纪念日临近"

    md_blocks = []
    text_lines = []

    for r, days_left, next_date in reminders_with_days:
        raw_type = (r.anniversary_type or '').strip()
        type_map = {
            'birthday': '生日',
            'wedding': '结婚纪念日',
            'anniversary': '重要纪念日',
            'other': '重要纪念日'
        }
        type_cn = type_map.get(raw_type.lower(), raw_type) if raw_type else '纪念日'
        notes = (r.notes or '').strip()

        # 智能提炼具体事件名称，坚决消除【其它】这类模糊信息：
        # 如果分类是其它且有备注，直接采用备注作为事件名称；若无备注则使用亲友重要纪念日
        if type_cn in ('其它', '其他', 'other', ''):
            event_name = notes if notes else '亲友重要纪念日'
        else:
            if notes and notes != type_cn and notes not in ('生日', '结婚纪念日'):
                event_name = f"{type_cn} ({notes})"
            else:
                event_name = type_cn

        # 倒计时文案
        if days_left == 0:
            status_desc = f"🎉 <font color=\"warning\">**就是今天** ({next_date.strftime('%m-%d')})！</font>"
            short_status = f"今天({next_date.strftime('%m-%d')})！"
        else:
            status_desc = f"还有 <font color=\"warning\">**{days_left}**</font> 天 ({next_date.strftime('%m-%d')})"
            short_status = f"还有 {days_left} 天({next_date.strftime('%m-%d')})"

        relation_str = f"({r.relation})" if r.relation else ""
        adv_days = r.advance_days or 3

        # Markdown 模块排版（全要素展示：姓名、关系、具体事项、倒计时、目标日期、下次公历、预警天数、备忘说明、联系电话）
        detail_items = [
            f"  > 目标日期：{r.target_date}（下次公历：{next_date.strftime('%Y-%m-%d')}）",
            f"  > 预警提醒：已设置提前 {adv_days} 天预警"
        ]
        if notes:
            detail_items.append(f"  > 备忘说明：{notes}")
        if r.phone:
            detail_items.append(f"  > 联系电话：{r.phone}")

        block = (
            f"• **{r.name}**{relation_str} 的【{event_name}】{status_desc}\n" +
            "\n".join(detail_items)
        )
        md_blocks.append(block)

        # 纯文本摘要信息（全要素展示）
        text_parts = [
            f"目标日期: {r.target_date}",
            f"预警: 提前{adv_days}天"
        ]
        if notes:
            text_parts.append(f"备忘: {notes}")
        if r.phone:
            text_parts.append(f"电话: {r.phone}")
        text_lines.append(f"• {r.name}{relation_str} 的【{event_name}】{short_status} | " + " | ".join(text_parts))

    md_detail = "\n\n".join(md_blocks)
    return title, md_detail, text_lines


_reminder_scheduler_thread = None
_reminder_scheduler_running = False

def check_and_trigger_due_reminders(app_obj=None, specific_reminder=None):
    """检查到达设置提醒天数的纪念日并自动触发 Webhook 推送"""
    try:
        from datetime import datetime
        today = datetime.now().date()
        webhooks = WebhookConfig.query.filter_by(is_enabled=True).all()
        active_hooks = [w for w in webhooks if getattr(w, 'notify_on_reminder', True) not in (False, 0, '0', 'false')]
        if not active_hooks:
            return 0

        if specific_reminder:
            rems = [specific_reminder] if (specific_reminder.is_active and not specific_reminder.deleted_at) else []
        else:
            rems = AnniversaryReminder.query.filter(
                AnniversaryReminder.deleted_at.is_(None),
                AnniversaryReminder.is_active == True
            ).all()

        due_list = []
        for r in rems:
            next_date, days_left = parse_target_date_obj(r.target_date, today)
            if not next_date:
                continue
            adv = r.advance_days or 3
            if 0 <= days_left <= adv:
                target_cycle_str = next_date.strftime('%Y-%m-%d')
                if not specific_reminder:
                    # 到达设置阈值后默认仅推送一次（本周期内不再重复自动推送，彻底消除高频刷屏）
                    if getattr(r, 'last_notified_target', None) == target_cycle_str:
                        continue
                due_list.append((r, days_left, next_date, target_cycle_str))

        if not due_list:
            return 0

        # 即刻更新已通知目标周期，持久化到数据库
        for item in due_list:
            r_obj = item[0]
            cycle_str = item[3]
            r_obj.last_notified_target = cycle_str
        try:
            db.session.commit()
        except Exception as _ce:
            db.session.rollback()
            print(f"[Anniversary Worker Commit Warning]: {_ce}")

        title, md_detail, text_summary = format_reminder_notification_content([(x[0], x[1], x[2]) for x in due_list])
        trigger_webhook_event(active_hooks, 'auto_reminder', f"近期有 {len(due_list)} 位亲友重要纪念日临近", md_detail, force_channels=True)
        print(f"[Anniversary Worker] 发现 {len(due_list)} 条临近纪念日，已触发自动推送通知: {[x[0].name for x in due_list]}")
        return len(due_list)
    except Exception as e:
        print(f"[check_and_trigger_due_reminders error]: {e}")
        return 0


def _anniversary_reminder_worker(flask_app):
    """后台常驻守护线程：定期巡检到达提醒天数的亲友纪念日并自动推送"""
    global _reminder_scheduler_running
    time.sleep(3)
    while _reminder_scheduler_running:
        try:
            with flask_app.app_context():
                check_and_trigger_due_reminders(flask_app)
        except Exception as e:
            print(f"[Anniversary Worker Error]: {e}")
        count = 0
        while _reminder_scheduler_running and count < 6:
            time.sleep(10)
            count += 1


def start_anniversary_reminder_scheduler(flask_app):
    global _reminder_scheduler_thread, _reminder_scheduler_running
    if _reminder_scheduler_thread and _reminder_scheduler_thread.is_alive():
        return
    _reminder_scheduler_running = True
    _reminder_scheduler_thread = threading.Thread(target=_anniversary_reminder_worker, args=(flask_app,), daemon=True)
    _reminder_scheduler_thread.start()
    print("[Scheduler] 亲友纪念日自动提醒后台守护线程已成功启动")

def register_routes_ext(app, log_operation=None, get_accessible_records_query=None, get_accessible_banquets_query=None, get_accessible_reminders_query=None, can_user_view_entity=None, can_user_edit_entity=None, can_user_delete_entity=None, clear_login_risk=None, clear_forgot_security_risk=None, app_start_time=None, **kwargs):

    def safe_log(action, detail="", user=None):
        if not log_operation:
            return
        try:
            log_operation(action, detail, user=user)
        except TypeError:
            try:
                log_operation(action, detail)
            except Exception:
                pass
        except Exception:
            pass

    # --- 统一菜单访问权限控制拦截 ---
    @app.before_request
    def check_menu_permissions():
        if not current_user.is_authenticated:
            return
        if getattr(current_user, 'is_admin', False):
            return
        endpoint = request.endpoint or ''
        menu_map = {
            'banquets_view': 'banquets',
            'banquet_detail_view': 'banquets',
            'banquet_quick_add': 'banquets',
            'banquet_edit': 'banquets',
            'banquet_delete': 'banquets',
            'banquet_export_excel': 'banquets',
            'banquets_sync': 'banquets',
            'banquet_import_records': 'banquets',
            'banquet_unlink_record': 'banquets',
            'banquet_share': 'banquets',
            'banquet_share_delete': 'banquets',
            'banquets_batch_delete': 'banquets',
            'banquet_record_delete': 'banquets',
            'banquet_records_batch_delete': 'banquets',
            'banquet_records_batch_unlink': 'banquets',
            'reconciliation_view': 'reconciliation',
            'reconciliation_sync': 'reconciliation',
            'api_person_ledger': 'reconciliation',
            'reminders_view': 'reminders',
            'reminder_edit': 'reminders',
            'reminder_delete': 'reminders',
            'reminders_batch_delete': 'reminders',
            'api_trigger_reminder_push': 'reminders',
            'api_upcoming_reminders': 'reminders',
            'recycle_bin_view': 'recycle_bin',
            'restore_record': 'recycle_bin',
            'purge_record': 'recycle_bin',
            'batch_restore_records': 'recycle_bin',
            'batch_purge_records': 'recycle_bin',
            'clear_recycle_bin': 'recycle_bin',
        }
        required_menu = menu_map.get(endpoint)
        if required_menu and hasattr(current_user, 'can_access_menu'):
            if not current_user.can_access_menu(required_menu):
                menu_names = {
                    'banquets': '专属宴席',
                    'reconciliation': '人情对账',
                    'reminders': '纪念日备忘',
                    'recycle_bin': '回收站'
                }
                m_name = menu_names.get(required_menu, '该功能')
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'code': 403, 'message': f'您暂无权限访问【{m_name}】功能模块，请联系管理员分配权限！'}), 403
                flash(f'您暂无权限访问【{m_name}】功能模块，请联系管理员为您分配访问权限！', 'warning')
                return redirect(url_for('index'))

    # --- 回收站过期自动清理机制 ---
    def cleanup_expired_recycle_items():
        try:
            days_str = SystemSetting.get_val('recycle_bin_retention_days', '30')
            days_val = int(days_str) if days_str and str(days_str).isdigit() else 30
            if days_val > 0:
                cutoff = datetime.now() - timedelta(days=days_val)
                GiftRecord.query.filter(GiftRecord.deleted_at.isnot(None), GiftRecord.deleted_at < cutoff).delete(synchronize_session=False)
                Banquet.query.filter(Banquet.deleted_at.isnot(None), Banquet.deleted_at < cutoff).delete(synchronize_session=False)
                AnniversaryReminder.query.filter(AnniversaryReminder.deleted_at.isnot(None), AnniversaryReminder.deleted_at < cutoff).delete(synchronize_session=False)
                db.session.commit()
        except Exception as e:
            db.session.rollback()

    @app.route('/recycle_bin')
    @login_required
    def recycle_bin_view():
        """
        全系统统一回收站视图：
        支持跨模块软删除回收（礼金账本、专属宴席、纪念日备忘），
        显示所属标签页/模块标签，支持保留时长设置、搜索与分页。
        """
        cleanup_expired_recycle_items()

        # 1. 查询各模块软删除数据（严格遵守跨用户数据权限）
        can_view_all = current_user.is_admin or (hasattr(current_user, 'can_view_others_for') and current_user.can_view_others_for('recycle_bin'))

        q_records = GiftRecord.query.filter(GiftRecord.deleted_at.isnot(None))
        q_banquets = Banquet.query.filter(Banquet.deleted_at.isnot(None))
        q_reminders = AnniversaryReminder.query.filter(AnniversaryReminder.deleted_at.isnot(None))

        if not can_view_all:
            q_records = q_records.filter_by(user_id=current_user.id)
            q_banquets = q_banquets.filter_by(user_id=current_user.id)
            q_reminders = q_reminders.filter_by(user_id=current_user.id)

        raw_records = q_records.all()
        raw_banquets = q_banquets.all()
        raw_reminders = q_reminders.all()

        all_items = []
        for r in raw_records:
            is_send = getattr(r, 'record_type', 'receive') in ('send', 'give')
            all_items.append({
                'id': r.id,
                'entity_type': 'record',
                'module_key': 'ledger',
                'module_name': '礼金账本',
                'module_badge': 'bg-success-subtle text-success border border-success-subtle',
                'title': r.name,
                'category': r.event_reason or '礼金记录',
                'amount': r.amount,
                'type_label': '送礼' if is_send else '收礼',
                'type_badge': 'bg-danger-subtle text-danger' if is_send else 'bg-success-subtle text-success',
                'notes': r.notes or '',
                'phone': r.phone or '',
                'deleted_at': r.deleted_at,
                'owner_name': r.owner.username if r.owner else '',
                'can_delete': can_user_delete_entity(current_user, r, 'recycle_bin') if can_user_delete_entity else (current_user.is_admin or r.user_id == current_user.id),
                'can_edit': can_user_edit_entity(current_user, r, 'recycle_bin') if can_user_edit_entity else (current_user.is_admin or r.user_id == current_user.id)
            })

        for b in raw_banquets:
            all_items.append({
                'id': b.id,
                'entity_type': 'banquet',
                'module_key': 'banquets',
                'module_name': '专属宴席',
                'module_badge': 'bg-warning-subtle text-warning-emphasis border border-warning-subtle',
                'title': b.title,
                'category': b.event_type or '宴席大账本',
                'amount': b.banquet_cost,
                'type_label': '办宴成本',
                'type_badge': 'bg-warning-subtle text-dark',
                'notes': b.notes or '',
                'phone': b.venue or '',
                'deleted_at': b.deleted_at,
                'owner_name': b.owner.username if b.owner else '',
                'can_delete': can_user_delete_entity(current_user, b, 'recycle_bin') if can_user_delete_entity else (current_user.is_admin or b.user_id == current_user.id),
                'can_edit': can_user_edit_entity(current_user, b, 'recycle_bin') if can_user_edit_entity else (current_user.is_admin or b.user_id == current_user.id)
            })

        for rem in raw_reminders:
            all_items.append({
                'id': rem.id,
                'entity_type': 'reminder',
                'module_key': 'reminders',
                'module_name': '纪念日备忘',
                'module_badge': 'bg-info-subtle text-info-emphasis border border-info-subtle',
                'title': rem.name,
                'category': rem.anniversary_type or '纪念日',
                'amount': None,
                'type_label': rem.relation or '亲友',
                'type_badge': 'bg-secondary-subtle text-secondary',
                'notes': rem.notes or '',
                'phone': rem.phone or '',
                'deleted_at': rem.deleted_at,
                'owner_name': rem.owner.username if getattr(rem, 'owner', None) else '',
                'can_delete': can_user_delete_entity(current_user, rem, 'recycle_bin') if can_user_delete_entity else (current_user.is_admin or rem.user_id == current_user.id),
                'can_edit': can_user_edit_entity(current_user, rem, 'recycle_bin') if can_user_edit_entity else (current_user.is_admin or rem.user_id == current_user.id)
            })

        # 统计各模块总数
        counts = {
            'all': len(all_items),
            'ledger': len([x for x in all_items if x['module_key'] == 'ledger']),
            'banquets': len([x for x in all_items if x['module_key'] == 'banquets']),
            'reminders': len([x for x in all_items if x['module_key'] == 'reminders']),
        }

        # 2. 模块筛选 (module: all, ledger, banquets, reminders)
        module_filter = request.args.get('module', 'all').strip()
        if module_filter in ['ledger', 'banquets', 'reminders']:
            filtered_items = [x for x in all_items if x['module_key'] == module_filter]
        else:
            module_filter = 'all'
            filtered_items = all_items

        # 3. 搜索过滤
        search = request.args.get('search', '').strip()
        if search:
            s_low = search.lower()
            filtered_items = [
                x for x in filtered_items
                if (
                    s_low in x['title'].lower() or
                    s_low in x['category'].lower() or
                    s_low in x['notes'].lower() or
                    s_low in x['phone'].lower() or
                    s_low in x['owner_name'].lower()
                )
            ]

        # 4. 排序（默认按删除时间倒序）
        sort_by = request.args.get('sort', 'deleted_desc').strip()
        if sort_by == 'deleted_asc':
            filtered_items.sort(key=lambda x: x['deleted_at'] or datetime.min)
        elif sort_by == 'amount_desc':
            filtered_items.sort(key=lambda x: x['amount'] or 0.0, reverse=True)
        elif sort_by == 'amount_asc':
            filtered_items.sort(key=lambda x: x['amount'] or 0.0)
        else:
            filtered_items.sort(key=lambda x: x['deleted_at'] or datetime.min, reverse=True)

        # 5. 分页
        try:
            per_page = int(request.args.get('per_page', 10))
            if per_page not in [5, 10, 20, 50, 100]:
                per_page = 10
        except (ValueError, TypeError):
            per_page = 10

        total_count = len(filtered_items)
        total_pages = max(1, (total_count + per_page - 1) // per_page)

        try:
            page = int(request.args.get('page', 1))
            if page < 1:
                page = 1
            elif page > total_pages:
                page = total_pages
        except (ValueError, TypeError):
            page = 1

        start_idx = (page - 1) * per_page
        paged_items = filtered_items[start_idx : start_idx + per_page]

        # 读取管理员配置的保留天数
        retention_days = int(SystemSetting.get_val('recycle_bin_retention_days', '30') or 30)

        can_clear_recycle = current_user.is_admin or (hasattr(current_user, 'can_delete_others_for') and current_user.can_delete_others_for('recycle_bin'))
        can_batch_restore = current_user.is_admin or any(i.get('can_edit') for i in paged_items)
        can_batch_purge = current_user.is_admin or any(i.get('can_delete') for i in paged_items)

        return render_template(
            'recycle_bin.html',
            items=paged_items,
            counts=counts,
            module_filter=module_filter,
            search=search,
            sort_by=sort_by,
            page=page,
            per_page=per_page,
            total_count=total_count,
            total_pages=total_pages,
            retention_days=retention_days,
            can_clear_recycle=can_clear_recycle,
            can_batch_restore=can_batch_restore,
            can_batch_purge=can_batch_purge
        )

    # --- 统一单项/批量还原与删除接口 ---
    @app.route('/recycle_bin/restore/<string:entity_type>/<int:item_id>', methods=['POST'])
    @app.route('/record/restore/<int:item_id>', methods=['POST'])
    @app.route('/restore_record/<int:item_id>', methods=['POST'])
    @app.route('/restore_record', methods=['POST'])
    @login_required
    def restore_item(entity_type='record', item_id=None):
        """还原单条记录（支持礼金记录、专属宴席、纪念日）"""
        target_type = request.form.get('entity_type') or entity_type
        target_id = item_id or request.args.get('id', type=int) or request.form.get('id', type=int)

        if not target_id:
            flash('未指定需要还原的记录ID', 'warning')
            return redirect(url_for('recycle_bin_view'))

        item = None
        title = ''
        if target_type == 'banquet':
            item = db.session.get(Banquet, target_id)
            title = item.title if item else ''
        elif target_type == 'reminder':
            item = db.session.get(AnniversaryReminder, target_id)
            title = item.name if item else ''
        else:
            item = db.session.get(GiftRecord, target_id)
            title = item.name if item else ''

        if not item:
            flash('未找到指定记录或已被彻底清理！', 'warning')
            return redirect(url_for('recycle_bin_view'))

        if can_user_edit_entity and not can_user_edit_entity(current_user, item, 'recycle_bin'):
            flash('您没有权限还原此数据！', 'danger')
            return redirect(url_for('recycle_bin_view'))

        item.deleted_at = None
        db.session.commit()
        safe_log('还原回收站数据', f"还原了 [{target_type}] ID #{target_id}: [{title}]", user=current_user)
        flash(f'已成功还原 [{title}]！', 'success')
        return redirect(url_for('recycle_bin_view'))

    @app.route('/recycle_bin/purge/<string:entity_type>/<int:item_id>', methods=['POST'])
    @app.route('/record/permanent_delete/<int:item_id>', methods=['POST'])
    @app.route('/purge_record/<int:item_id>', methods=['POST'])
    @app.route('/purge_record', methods=['POST'])
    @login_required
    def purge_item(entity_type='record', item_id=None):
        """彻底删除单条记录"""
        target_type = request.form.get('entity_type') or entity_type
        target_id = item_id or request.args.get('id', type=int) or request.form.get('id', type=int)

        if not target_id:
            flash('未指定需要删除的记录ID', 'warning')
            return redirect(url_for('recycle_bin_view'))

        item = None
        title = ''
        if target_type == 'banquet':
            item = db.session.get(Banquet, target_id)
            title = item.title if item else ''
        elif target_type == 'reminder':
            item = db.session.get(AnniversaryReminder, target_id)
            title = item.name if item else ''
        else:
            item = db.session.get(GiftRecord, target_id)
            title = item.name if item else ''

        if not item:
            flash('未找到指定记录或已彻底删除！', 'warning')
            return redirect(url_for('recycle_bin_view'))

        if can_user_delete_entity and not can_user_delete_entity(current_user, item, 'recycle_bin'):
            flash('您没有权限彻底删除此数据！', 'danger')
            return redirect(url_for('recycle_bin_view'))

        db.session.delete(item)
        db.session.commit()
        safe_log('彻底删除数据', f"彻底删除了 [{target_type}] ID #{target_id}: [{title}]", user=current_user)
        flash(f'已彻底删除 [{title}]，无法恢复！', 'success')
        return redirect(url_for('recycle_bin_view'))

    @app.route('/recycle_bin/batch_restore', methods=['POST'])
    @app.route('/records/batch_restore', methods=['POST'])
    @app.route('/batch_restore_records', methods=['POST'])
    @login_required
    def batch_restore_items():
        """批量还原选中项（支持跨模块 items 混合参数如 record:12 或单独 record_ids）"""
        if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('recycle_bin') == 1:
            flash('当前页面为仅查看权限，无权还原数据！', 'danger')
            return redirect(url_for('recycle_bin_view'))
        raw_items = request.form.getlist('selected_items') or request.form.getlist('selected_items[]') or request.form.getlist('record_ids') or request.form.getlist('record_ids[]')
        if not raw_items:
            flash('未选择任何记录！', 'warning')
            return redirect(url_for('recycle_bin_view'))

        count = 0
        for token in raw_items:
            try:
                if ':' in str(token):
                    etype, iid_str = str(token).split(':', 1)
                    iid = int(iid_str)
                else:
                    etype = request.form.get('entity_type', 'record')
                    iid = int(token)

                item = None
                if etype == 'banquet':
                    item = db.session.get(Banquet, iid)
                elif etype == 'reminder':
                    item = db.session.get(AnniversaryReminder, iid)
                else:
                    item = db.session.get(GiftRecord, iid)

                if item and item.deleted_at:
                    if not can_user_edit_entity or can_user_edit_entity(current_user, item, 'recycle_bin'):
                        item.deleted_at = None
                        count += 1
            except Exception:
                continue

        if count > 0:
            db.session.commit()
            safe_log('批量还原数据', f"批量还原了 {count} 条回收站记录", user=current_user)
            flash(f'成功还原了 {count} 条记录！', 'success')
        else:
            flash('未找到可还原的记录！', 'warning')

        return redirect(url_for('recycle_bin_view'))

    @app.route('/recycle_bin/batch_purge', methods=['POST'])
    @app.route('/records/batch_permanent_delete', methods=['POST'])
    @app.route('/batch_purge_records', methods=['POST'])
    @login_required
    def batch_purge_items():
        """批量彻底删除选中项"""
        if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('recycle_bin') in (1, 2):
            flash('当前页面权限不允许彻底删除数据！', 'danger')
            return redirect(url_for('recycle_bin_view'))
        raw_items = request.form.getlist('selected_items') or request.form.getlist('selected_items[]') or request.form.getlist('record_ids') or request.form.getlist('record_ids[]')
        if not raw_items:
            flash('未选择任何记录！', 'warning')
            return redirect(url_for('recycle_bin_view'))

        count = 0
        for token in raw_items:
            try:
                if ':' in str(token):
                    etype, iid_str = str(token).split(':', 1)
                    iid = int(iid_str)
                else:
                    etype = request.form.get('entity_type', 'record')
                    iid = int(token)

                item = None
                if etype == 'banquet':
                    item = db.session.get(Banquet, iid)
                elif etype == 'reminder':
                    item = db.session.get(AnniversaryReminder, iid)
                else:
                    item = db.session.get(GiftRecord, iid)

                if item:
                    if not can_user_delete_entity or can_user_delete_entity(current_user, item, 'recycle_bin'):
                        db.session.delete(item)
                        count += 1
            except Exception:
                continue

        if count > 0:
            db.session.commit()
            safe_log('批量彻底删除', f"批量彻底删除了 {count} 条回收站数据", user=current_user)
            flash(f'已彻底删除 {count} 条数据，不可恢复！', 'success')
        else:
            flash('未找到可删除的记录！', 'warning')

        return redirect(url_for('recycle_bin_view'))

    @app.route('/recycle_bin/clear', methods=['POST'])
    @app.route('/records/clear_recycle_bin', methods=['POST'])
    @app.route('/clear_recycle_bin', methods=['POST'])
    @login_required
    def clear_recycle_bin():
        """清空回收站中用户有权删除的所有数据"""
        if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('recycle_bin') in (1, 2):
            flash('当前页面权限不允许清空回收站！', 'danger')
            return redirect(url_for('recycle_bin_view'))
        if not (current_user.is_admin or (hasattr(current_user, 'can_delete_others_for') and current_user.can_delete_others_for('recycle_bin'))):
            flash('您没有权限清空回收站！', 'danger')
            return redirect(url_for('recycle_bin_view'))
        can_view_all = current_user.is_admin or (hasattr(current_user, 'can_view_others_for') and current_user.can_view_others_for('recycle_bin'))

        q_records = GiftRecord.query.filter(GiftRecord.deleted_at.isnot(None))
        q_banquets = Banquet.query.filter(Banquet.deleted_at.isnot(None))
        q_reminders = AnniversaryReminder.query.filter(AnniversaryReminder.deleted_at.isnot(None))

        if not can_view_all:
            q_records = q_records.filter_by(user_id=current_user.id)
            q_banquets = q_banquets.filter_by(user_id=current_user.id)
            q_reminders = q_reminders.filter_by(user_id=current_user.id)

        count = 0
        for r in q_records.all():
            if not can_user_delete_entity or can_user_delete_entity(current_user, r):
                db.session.delete(r)
                count += 1
        for b in q_banquets.all():
            if not can_user_delete_entity or can_user_delete_entity(current_user, b):
                db.session.delete(b)
                count += 1
        for rem in q_reminders.all():
            if not can_user_delete_entity or can_user_delete_entity(current_user, rem):
                db.session.delete(rem)
                count += 1

        if count > 0:
            db.session.commit()
            safe_log('清空回收站', f"清空回收站数据共 {count} 条", user=current_user)
            flash(f'回收站已清空，共彻底删除 {count} 条数据！', 'success')
        else:
            flash('回收站当前为空！', 'info')

        return redirect(url_for('recycle_bin_view'))

    @app.route('/admin/recycle_bin/set_retention', methods=['POST'])
    @login_required
    def admin_set_recycle_retention():
        """管理员设置回收站数据保留时长（天数）"""
        if not current_user.is_admin:
            flash('权限不足！', 'danger')
            return redirect(url_for('recycle_bin_view'))

        days_val = request.form.get('retention_days', '30').strip()
        try:
            days = max(0, int(days_val))
        except (ValueError, TypeError):
            days = 30

        SystemSetting.set_val('recycle_bin_retention_days', str(days))
        cleanup_expired_recycle_items()
        safe_log('设置回收站策略', f"管理员将回收站数据保留时长设置为 {days} 天")
        desc = f"保留 {days} 天（超出自动彻底清理）" if days > 0 else "永久保留（不自动清理）"
        flash(f'回收站保留时长已设置为：【{desc}】！', 'success')
        return redirect(url_for('recycle_bin_view'))

    @app.route('/recycle_bin/cleanup_expired', methods=['POST'])
    @login_required
    def manual_cleanup_expired_recycle_bin():
        """手动一键清理超出时限的回收站过期数据"""
        if not current_user.is_admin:
            flash('权限不足！', 'danger')
            return redirect(url_for('recycle_bin_view'))

        cleanup_expired_recycle_items()
        flash('已执行回收站过期数据清理！', 'success')
        return redirect(url_for('recycle_bin_view'))

    @app.route('/reconciliation')
    @login_required
    def reconciliation_view():
        """人情对账汇总与往来明细（支持搜索、状态筛选、排序与自定义分页）"""
        import json
        query = get_accessible_records_query(current_user, menu_key='reconciliation')
        # 排除回收站软删除数据
        records = query.filter(GiftRecord.deleted_at.is_(None)).all()
        balance_list, total_received, total_given = calculate_reconciliation(records)

        # 1. 搜索查询（亲友姓名模糊搜索）
        search = request.args.get('search', '').strip()
        if search:
            balance_list = [item for item in balance_list if search.lower() in item['person_name'].lower()]

        # 2. 状态筛选 (status)
        status = request.args.get('status', '').strip()
        if status == 'need_return':  # 对方送我多 / 待还礼 (net_balance > 0)
            balance_list = [item for item in balance_list if item['net_balance'] > 0]
        elif status == 'need_pay':   # 我送对方多 / 待补礼 (net_balance < 0)
            balance_list = [item for item in balance_list if item['net_balance'] < 0]
        elif status == 'balanced':   # 已平账 (net_balance == 0)
            balance_list = [item for item in balance_list if item['net_balance'] == 0]

        # 3. 排序 (sort)
        sort_by = request.args.get('sort', 'diff_abs_desc').strip()
        if sort_by == 'need_return_first':
            balance_list.sort(key=lambda x: x['net_balance'], reverse=True)
        elif sort_by == 'need_pay_first':
            balance_list.sort(key=lambda x: x['net_balance'])
        elif sort_by == 'received_desc':
            balance_list.sort(key=lambda x: x['received_amount'], reverse=True)
        elif sort_by == 'given_desc':
            balance_list.sort(key=lambda x: x['given_amount'], reverse=True)
        elif sort_by == 'name_asc':
            balance_list.sort(key=lambda x: x['person_name'])
        else:
            balance_list.sort(key=lambda x: abs(x['net_balance']), reverse=True)

        # 4. 分页分条数 (默认 10 条，支持设置 10, 20, 50, 100)
        try:
            per_page = int(request.args.get('per_page', 10))
            if per_page not in [5, 10, 20, 50, 100]:
                per_page = 10
        except (ValueError, TypeError):
            per_page = 10

        total_count = len(balance_list)
        total_pages = max(1, (total_count + per_page - 1) // per_page)

        try:
            page = int(request.args.get('page', 1))
            if page < 1:
                page = 1
            if page > total_pages:
                page = total_pages
        except (ValueError, TypeError):
            page = 1

        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paged_list = balance_list[start_idx:end_idx]

        # 构造姓名对应的明细列表数据字典，供弹窗即时查阅
        records_map = {}
        for item in balance_list:
            records_map[item['person_name']] = item.get('records', [])

        return render_template(
            'reconciliation.html',
            balance_list=paged_list,
            total_count=total_count,
            total_pages=total_pages,
            page=page,
            per_page=per_page,
            search=search,
            status=status,
            sort_by=sort_by,
            total_received=total_received,
            total_given=total_given,
            records_map_json=json.dumps(records_map, ensure_ascii=False)
        )

    @app.route('/reconciliation/sync', methods=['GET', 'POST'])
    @login_required
    def reconciliation_sync():
        """手动从礼金账本拉取最新数据同步人情对账"""
        try:
            query = get_accessible_records_query(current_user, menu_key='reconciliation') if get_accessible_records_query else GiftRecord.query
            records = query.filter(GiftRecord.deleted_at.is_(None)).all()
            balance_list, total_received, total_given = calculate_reconciliation(records)
            safe_log('同步对账数据', f"从礼金账本拉取最新数据同步人情对账，共核对 {len(balance_list)} 位亲友往来")
            flash(f'已成功从礼金账本拉取最新数据完成同步！共核对 {len(balance_list)} 位亲友的人情往来。', 'success')
        except Exception as e:
            flash(f'同步人情对账数据失败：{str(e)}', 'danger')
        return redirect(url_for('reconciliation_view'))

    @app.route('/api/person_ledger/<name>')
    @login_required
    def api_person_ledger(name):
        """获取指定亲友的所有往来礼金明细（完整字段兼容）"""
        clean_name = (name or '').strip()
        query = get_accessible_records_query(current_user)
        records = query.filter(
            GiftRecord.name == clean_name,
            GiftRecord.deleted_at.is_(None)
        ).order_by(GiftRecord.created_at.desc()).all()
        data = []
        for r in records:
            r_type = getattr(r, 'record_type', 'receive')
            is_send = (r_type in ('send', 'give'))
            amt = float(r.amount) if r.amount else 0.0
            dt_str = r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''
            data.append({
                'id': r.id,
                'name': r.name,
                'type_label': '送礼(我方出)' if is_send else '收礼(对方来)',
                'gift_type': 'sent' if is_send else 'received',
                'record_type': 'send' if is_send else 'receive',
                'amount': amt,
                'event_type': r.event_reason or '礼金',
                'event_category': r.event_reason or '礼金',
                'event_reason': r.event_reason or '礼金',
                'event_date': dt_str,
                'created_at': dt_str,
                'remarks': r.notes or '',
                'notes': r.notes or ''
            })
        return jsonify({'code': 200, 'name': clean_name, 'records': data})

    @app.route('/api/gift-suggestion')
    @login_required
    def api_gift_suggestion():
        """智能还礼金额建议 API"""
        name = request.args.get('name', '').strip()
        all_records = get_accessible_records_query(current_user).all()
        result = get_gift_suggestion(all_records, name)
        return jsonify({'code': 200, **result})

    # --- 自然语言极简记账（支持分隔符多条自动拆分入库） ---
    @app.route('/api/record/parse_nlp', methods=['POST'])
    @login_required
    def api_parse_nlp():
        """自然语言解析记账信息（支持单条及多条复合语句）"""
        data = request.get_json() or {}
        text = data.get('text', '').strip()
        parsed_items = parse_gift_nlp_multi(text)
        single = parsed_items[0] if parsed_items else parse_gift_nlp(text)
        return jsonify({'code': 200, 'data': single, 'items': parsed_items, 'count': len(parsed_items)})

    @app.route('/api/record/nlp_quick_add', methods=['POST'])
    @login_required
    def api_nlp_quick_add():
        """自然语言极简一键记账（常见分割词自动分隔并生成多条记录）"""
        data = request.get_json() or {}
        text = data.get('text', '').strip()
        if not text:
            return jsonify({'code': 400, 'message': '输入文本不能为空'}), 400

        parsed_items = parse_gift_nlp_multi(text)
        if not parsed_items:
            return jsonify({'code': 400, 'message': '未能有效识别出亲友姓名或有效金额，请核对后重试'}), 400

        added_records = []
        for p in parsed_items:
            if not p.get('name') or p.get('amount', 0) <= 0:
                continue
            record = GiftRecord(
                name=p['name'],
                amount=p['amount'],
                event_reason=p.get('event_reason', '其它'),
                record_type=p.get('record_type', 'receive'),
                notes=p.get('notes', text),
                user_id=current_user.id
            )
            db.session.add(record)
            added_records.append(record)

        if not added_records:
            return jsonify({'code': 400, 'message': '未能有效识别出亲友姓名或有效金额，请核对后重试'}), 400

        db.session.commit()
        desc_list = [f"[{r.name}] {'送礼' if r.record_type == 'send' else '收礼'} {r.amount:.2f}元({r.event_reason})" for r in added_records]
        msg = f"成功入库 {len(added_records)} 条礼金记录：" + "、".join(desc_list)
        safe_log('自然语言极简记账', f"通过文本 [{text}] 批量录入 {len(added_records)} 条: " + "，".join(desc_list))

        return jsonify({
            'code': 200,
            'message': msg,
            'count': len(added_records),
            'records': [
                {
                    'id': r.id,
                    'name': r.name,
                    'amount': r.amount,
                    'event_reason': r.event_reason,
                    'record_type': r.record_type
                }
                for r in added_records
            ]
        })

    # --- 专属宴席 / 活动大账本与盈亏分析 ---
    def sync_banquets_from_ledger(user, force_restore=False):
        """
        专属宴席与礼金账本映射规范：
        原则一：专属宴席仅归集 record_type == 'receive'（收礼），彻底排除 send（送礼/随礼）
        原则二：清理历史误挂在宴席上的 send 记录（置 banquet_id = None）
        原则三：多维归集升级，按 (user_id, event_reason, 年份) 智能匹配或自动新建专属台账
        原则四：已手动关联宴席的有效收礼记录保持不变
        原则五：常规访问防自动复活；当用户显式点击【从礼金账本同步数据】(force_restore=True) 时，
               系统响应主动诉求，将已删除但在账本中仍有收礼明细的台账恢复/重新归集，并打上来源用户标识！
        """
        if not user or not user.is_authenticated:
            return 0, 0

        # 1. 彻底清理历史脏数据：送礼记录绝不可关联专属宴席
        dirty_send_records = GiftRecord.query.filter(
            GiftRecord.record_type != 'receive',
            GiftRecord.banquet_id.isnot(None)
        ).all()
        for ds in dirty_send_records:
            ds.banquet_id = None

        # 2. 检索当前用户有权访问的有效未删除收礼记录
        if get_accessible_records_query:
            records = get_accessible_records_query(user, menu_key='banquets').filter(
                GiftRecord.deleted_at.is_(None),
                GiftRecord.record_type == 'receive'
            ).all()
        else:
            base_q = GiftRecord.query if user.is_admin else GiftRecord.query.filter_by(user_id=user.id)
            records = base_q.filter(
                GiftRecord.deleted_at.is_(None),
                GiftRecord.record_type == 'receive'
            ).all()

        if not records:
            db.session.commit()
            return 0, 0

        all_banquets = Banquet.query.filter(Banquet.deleted_at.is_(None)).all()
        deleted_banquets = Banquet.query.filter(Banquet.deleted_at.isnot(None)).all()

        groups = {}
        current_year = str(datetime.now().year)

        linked_count = 0
        created_count = 0

        # 缓存用户信息避免重复查询
        user_cache = {}
        def _get_username(uid):
            if uid not in user_cache:
                u_obj = db.session.get(User, uid)
                user_cache[uid] = u_obj.username if u_obj else 'admin'
            return user_cache[uid]

        for r in records:
            if r.banquet_id:
                matched_b = next((b for b in all_banquets if b.id == r.banquet_id), None)
                if matched_b:
                    continue
                matched_deleted_b = next((b for b in deleted_banquets if b.id == r.banquet_id), None)
                if matched_deleted_b:
                    if force_restore:
                        # 主动手动同步：恢复被软删除的台账
                        matched_deleted_b.deleted_at = None
                        matched_deleted_b.creator_type = 'auto'
                        matched_deleted_b.creator_id = matched_deleted_b.user_id
                        matched_deleted_b.source_username = _get_username(matched_deleted_b.user_id)
                        all_banquets.append(matched_deleted_b)
                        deleted_banquets.remove(matched_deleted_b)
                        created_count += 1
                        continue
                    else:
                        continue
                else:
                    r.banquet_id = None

            owner_id = r.user_id or (user.id if user else 1)
            reason = (r.event_reason or '其它喜宴').strip()

            rec_year = current_year
            if r.created_at:
                rec_year = str(r.created_at.year)
            elif hasattr(r, 'date') and r.date:
                d_str = str(r.date).strip()
                if len(d_str) >= 4 and d_str[:4].isdigit():
                    rec_year = d_str[:4]

            key = (owner_id, reason, rec_year)
            if key not in groups:
                groups[key] = []
            groups[key].append(r)

        for (owner_id, reason, year_str), r_list in groups.items():
            target_b = None
            for b in all_banquets:
                if b.user_id == owner_id:
                    if b.event_type == reason or reason in (b.title or ''):
                        target_b = b
                        break

            if not target_b and deleted_banquets:
                deleted_match = None
                for db_item in deleted_banquets:
                    if db_item.user_id == owner_id:
                        if db_item.event_type == reason or reason in (db_item.title or '') or f"{year_str}年 {reason}" in (db_item.title or ''):
                            deleted_match = db_item
                            break
                if deleted_match:
                    if force_restore:
                        # 显式手动同步触发：恢复该专属台账
                        deleted_match.deleted_at = None
                        deleted_match.creator_type = 'auto'
                        deleted_match.creator_id = owner_id
                        deleted_match.source_username = _get_username(owner_id)
                        target_b = deleted_match
                        all_banquets.append(target_b)
                        deleted_banquets.remove(deleted_match)
                        created_count += 1
                    else:
                        continue

            if not target_b:
                source_user = _get_username(owner_id)
                target_b = Banquet(
                    title=f"{year_str}年 {reason}专属台账",
                    event_type=reason,
                    event_date=f"{year_str}-01-01",
                    venue="礼金账本收礼汇总",
                    budget=0.0,
                    banquet_cost=0.0,
                    notes=f"由系统自动归集【{year_str}年 {reason}】收礼记录生成",
                    user_id=owner_id,
                    creator_type='auto',
                    creator_id=owner_id,
                    source_username=source_user
                )
                db.session.add(target_b)
                db.session.flush()
                all_banquets.append(target_b)
                created_count += 1

            for r in r_list:
                if r.banquet_id != target_b.id:
                    r.banquet_id = target_b.id
                    linked_count += 1

        db.session.commit()
        return created_count, linked_count

    @app.route('/banquets', methods=['GET', 'POST'])
    @login_required
    def banquets_view():
        """宴席大账本列表与创建（自动从礼金账本获取并按办席原因生成）"""
        if request.method == 'POST':
            if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('banquets') == 1:
                flash('当前页面为仅查看权限，无权创建专属宴席！', 'danger')
                return redirect(url_for('banquets_view'))
            title = request.form.get('title', '').strip()
            event_type = request.form.get('event_type', '婚宴').strip()
            event_date_str = request.form.get('event_date', '').strip()
            venue = request.form.get('venue', '').strip()
            budget = float(request.form.get('budget', 0) or 0)
            banquet_cost = float(request.form.get('banquet_cost', 0) or 0)
            notes = request.form.get('notes', '').strip()

            if not title:
                flash('宴席/活动名称不能为空！', 'danger')
                return redirect(url_for('banquets_view'))


            event_date = None
            if event_date_str:
                try:
                    event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
                except Exception:
                    pass

            b = Banquet(
                title=title,
                event_type=event_type,
                event_date=event_date,
                venue=venue,
                budget=budget,
                banquet_cost=banquet_cost,
                notes=notes,
                user_id=current_user.id,
                creator_type='manual',
                creator_id=current_user.id,
                source_username=current_user.username
            )
            db.session.add(b)
            db.session.commit()
            safe_log('创建大账本', f"创建了专属宴席账本 [{title}]，办宴成本: {banquet_cost}元")
            flash(f'成功创建宴席账本 [{title}]！', 'success')
            return redirect(url_for('banquets_view'))

        # 页面加载时自动从礼金账本获取数据并按办席原因自动生成/更新大账本
        try:
            sync_banquets_from_ledger(current_user)
        except Exception as e:
            print(f"[Banquet Auto Sync]: {e}")

        if get_accessible_banquets_query:
            query = get_accessible_banquets_query(current_user)
        else:
            query = Banquet.query.filter(Banquet.deleted_at.is_(None))
            if not (current_user.is_admin or getattr(current_user, 'can_view_others', False)):
                query = query.filter_by(user_id=current_user.id)

        banquets = query.order_by(Banquet.created_at.desc()).all()

        # 计算每个账本的收礼总额与净盈亏（基于用户有权访问的记录）
        banquet_stats = []
        for b in banquets:
            if get_accessible_records_query:
                recs = get_accessible_records_query(current_user, menu_key='banquets').filter(GiftRecord.banquet_id == b.id, GiftRecord.deleted_at.is_(None)).all()
            else:
                recs = GiftRecord.query.filter_by(banquet_id=b.id).filter(GiftRecord.deleted_at.is_(None)).all()
            total_income = sum(r.amount for r in recs if getattr(r, 'record_type', 'receive') != 'send')
            cost = b.banquet_cost or 0.0
            net_profit = total_income - cost
            banquet_stats.append({
                'banquet': b,
                'record_count': len(recs),
                'total_income': total_income,
                'banquet_cost': cost,
                'net_profit': net_profit
            })

        return render_template('banquets.html', banquet_stats=banquet_stats)

    @app.route('/banquets/sync', methods=['GET', 'POST'])
    @login_required
    def banquets_sync():
        """管理员或用户手动从礼金账本拉取数据同步专属大账本"""
        if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('banquets') == 1:
            flash('当前页面为仅查看权限，无权从礼金账本拉取数据同步！', 'danger')
            return redirect(url_for('banquets_view'))
        try:
            created, linked = sync_banquets_from_ledger(current_user, force_restore=True)
            safe_log('同步专属大账本', f"从礼金账本手动拉取数据：自动同步/生成 {created} 个大账本，关联更新 {linked} 条记录")
            flash(f'成功从礼金账本拉取数据同步！新增/恢复了 {created} 个专属大账本，关联更新 {linked} 条礼金记录。', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'同步专属大账本失败：{str(e)}', 'danger')
        return redirect(url_for('banquets_view'))

    @app.route('/banquet/<int:banquet_id>')
    @login_required
    def banquet_detail_view(banquet_id):
        """专属宴席大账本详情、现场快速录入台账与盈亏分析"""
        b = db.session.get(Banquet, banquet_id)
        if not b or b.deleted_at:
            flash('该宴席账本不存在或已被删除！', 'warning')
            return redirect(url_for('banquets_view'))

        if can_user_view_entity and not can_user_view_entity(current_user, b, 'banquets'):
            flash('您没有权限查看该专属宴席！', 'danger')
            return redirect(url_for('banquets_view'))

        if get_accessible_records_query:
            records = get_accessible_records_query(current_user).filter(GiftRecord.banquet_id == b.id, GiftRecord.deleted_at.is_(None)).order_by(GiftRecord.created_at.desc()).all()
        else:
            records = GiftRecord.query.filter_by(banquet_id=b.id).filter(GiftRecord.deleted_at.is_(None)).order_by(GiftRecord.created_at.desc()).all()
        total_income = sum(r.amount for r in records if getattr(r, 'record_type', 'receive') != 'send')
        cost = b.banquet_cost or 0.0
        net_profit = total_income - cost
        recovery_rate = (total_income / cost * 100) if cost > 0 else 0

        # 候选收礼记录（仅未删除、收礼类型、当前未归属于本宴席的记录供引入）
        if get_accessible_records_query:
            cand_query = get_accessible_records_query(current_user)
        else:
            cand_query = GiftRecord.query.filter(GiftRecord.deleted_at.is_(None))
            if not (current_user.is_admin or getattr(current_user, 'can_view_others', False)):
                cand_query = cand_query.filter_by(user_id=current_user.id)
        
        available_records = cand_query.filter(
            GiftRecord.record_type == 'receive',
            GiftRecord.deleted_at.is_(None),
            db.or_(GiftRecord.banquet_id.is_(None), GiftRecord.banquet_id != b.id)
        ).order_by(GiftRecord.created_at.desc()).all()

        # 分享链接信息
        share = SharedLedgerLink.query.filter_by(banquet_id=b.id, is_active=True).first()

        return render_template(
            'banquet_detail.html',
            banquet=b,
            records=records,
            available_records=available_records,
            total_income=total_income,
            banquet_cost=cost,
            net_profit=net_profit,
            recovery_rate=recovery_rate,
            share=share
        )

    @app.route('/banquet/edit/<int:banquet_id>', methods=['POST'])
    @login_required
    def banquet_edit(banquet_id):
        """编辑宴席账本基本信息与成本"""
        b = db.session.get(Banquet, banquet_id)
        if not b or b.deleted_at:
            flash('账本不存在', 'danger')
            return redirect(url_for('banquets_view'))

        if can_user_edit_entity and not can_user_edit_entity(current_user, b, 'banquets'):
            flash('您没有权限修改该专属宴席！', 'danger')
            return redirect(url_for('banquets_view'))

        b.title = request.form.get('title', b.title).strip()
        b.event_type = request.form.get('event_type', b.event_type).strip()
        b.venue = request.form.get('venue', b.venue).strip()
        try:
            b.budget = float(request.form.get('budget', b.budget) or 0)
            b.banquet_cost = float(request.form.get('banquet_cost', b.banquet_cost) or 0)
        except ValueError:
            pass
        b.notes = request.form.get('notes', b.notes).strip()
        db.session.commit()
        safe_log('修改大账本', f"更新了宴席账本 [{b.title}] 的信息与成本支出")
        flash('宴席账本已更新！', 'success')
        return redirect(url_for('banquet_detail_view', banquet_id=b.id))

    @app.route('/banquet/delete/<int:banquet_id>', methods=['POST'])
    @login_required
    def banquet_delete(banquet_id):
        """删除专属宴席大账本（软删除至回收站）"""
        b = db.session.get(Banquet, banquet_id)
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        if not b or b.deleted_at:
            if is_ajax:
                return jsonify({'code': 404, 'message': '宴席账本不存在或已被删除！'}), 404
            flash('宴席账本不存在或已被删除！', 'warning')
            return redirect(url_for('banquets_view'))

        if can_user_delete_entity and not can_user_delete_entity(current_user, b, 'banquets'):
            if is_ajax:
                return jsonify({'code': 403, 'message': '您没有权限删除该专属宴席！'}), 403
            flash('您没有权限删除该专属宴席！', 'danger')
            return redirect(url_for('banquets_view'))

        b_title = b.title
        b.deleted_at = datetime.now()
        db.session.commit()
        safe_log('删除大账本', f"软删除了宴席账本 ID #{banquet_id}: [{b_title}]")
        if is_ajax:
            return jsonify({'code': 200, 'message': f'宴席账本 [{b_title}] 已成功移入回收站！'})
        flash(f'宴席账本 [{b_title}] 已成功移入回收站！', 'success')
        return redirect(url_for('banquets_view'))

    @app.route('/banquets/batch_delete', methods=['POST'])
    @login_required
    def banquets_batch_delete():
        """批量软删除专属宴席大账本至回收站"""
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('banquets') in (1, 2):
            if is_ajax:
                return jsonify({'code': 403, 'message': '当前页面权限不允许删除专属宴席！'}), 403
            flash('当前页面权限不允许删除专属宴席！', 'danger')
            return redirect(url_for('banquets_view'))

        if request.is_json:
            data = request.get_json(silent=True) or {}
            banquet_ids = data.get('banquet_ids', [])
        else:
            banquet_ids = request.form.getlist('banquet_ids') or request.form.getlist('banquet_ids[]')

        if not banquet_ids:
            if is_ajax:
                return jsonify({'code': 400, 'message': '请至少选择一个要删除的专属宴席！'}), 400
            flash('请至少选择一个要删除的专属宴席！', 'warning')
            return redirect(url_for('banquets_view'))

        count = 0
        for b_id in banquet_ids:
            try:
                b_id_int = int(b_id)
                b = db.session.get(Banquet, b_id_int)
                if b and not b.deleted_at:
                    if can_user_delete_entity and not can_user_delete_entity(current_user, b, 'banquets'):
                        continue
                    b.deleted_at = datetime.now()
                    count += 1
            except (ValueError, TypeError):
                continue

        db.session.commit()
        safe_log('批量删除大账本', f"批量移入回收站了 {count} 个专属宴席")
        if is_ajax:
            return jsonify({'code': 200, 'message': f'成功将 {count} 个专属宴席移入回收站！', 'count': count})
        flash(f'成功将 {count} 个专属宴席移入回收站！', 'success')
        return redirect(url_for('banquets_view'))

    @app.route('/banquet/<int:banquet_id>/record/delete/<int:record_id>', methods=['POST'])
    @login_required
    def banquet_record_delete(banquet_id, record_id):
        """删除专属宴席中的单笔礼金明细（软删除至回收站）"""
        b = db.session.get(Banquet, banquet_id)
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        if not b or b.deleted_at:
            if is_ajax:
                return jsonify({'code': 404, 'message': '宴席账本不存在！'}), 404
            flash('专属宴席不存在或已被删除！', 'warning')
            return redirect(url_for('banquets_view'))

        r = db.session.get(GiftRecord, record_id)
        if not r or r.deleted_at:
            if is_ajax:
                return jsonify({'code': 404, 'message': '明细记录不存在或已被删除！'}), 404
            flash('该明细记录不存在或已被删除！', 'warning')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        if can_user_delete_entity and not can_user_delete_entity(current_user, r, 'banquets'):
            if is_ajax:
                return jsonify({'code': 403, 'message': '您没有权限删除该记录！'}), 403
            flash('您没有权限删除该记录！', 'danger')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        rec_name = r.name
        r.deleted_at = datetime.now()
        db.session.commit()
        safe_log('删除宴席明细', f"在专属宴席 [{b.title}] 中软删除了记录 ID #{record_id}: [{rec_name}]")
        if is_ajax:
            return jsonify({'code': 200, 'message': f'客人 [{rec_name}] 的记录已移入回收站！'})
        flash(f'客人 [{rec_name}] 的记录已成功移入回收站！', 'success')
        return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

    @app.route('/banquet/<int:banquet_id>/records/batch_delete', methods=['POST'])
    @login_required
    def banquet_records_batch_delete(banquet_id):
        """在专属宴席详情页批量软删除明细记录（移入回收站）"""
        b = db.session.get(Banquet, banquet_id)
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        if not b or b.deleted_at:
            if is_ajax:
                return jsonify({'code': 404, 'message': '宴席账本不存在！'}), 404
            flash('专属宴席不存在或已被删除！', 'warning')
            return redirect(url_for('banquets_view'))

        if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('banquets') in (1, 2):
            if is_ajax:
                return jsonify({'code': 403, 'message': '当前页面权限不允许删除记录！'}), 403
            flash('当前页面权限不允许删除记录！', 'danger')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        if request.is_json:
            data = request.get_json(silent=True) or {}
            record_ids = data.get('record_ids', [])
        else:
            record_ids = request.form.getlist('record_ids') or request.form.getlist('record_ids[]')

        if not record_ids:
            if is_ajax:
                return jsonify({'code': 400, 'message': '请至少选择一条要删除的明细记录！'}), 400
            flash('请至少选择一条要删除的明细记录！', 'warning')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        count = 0
        for r_id in record_ids:
            try:
                r_id_int = int(r_id)
                r = db.session.get(GiftRecord, r_id_int)
                if r and not r.deleted_at and r.banquet_id == b.id:
                    if can_user_delete_entity and not can_user_delete_entity(current_user, r, 'banquets'):
                        continue
                    r.deleted_at = datetime.now()
                    count += 1
            except (ValueError, TypeError):
                continue

        db.session.commit()
        safe_log('批量删除宴席明细', f"在专属宴席 [{b.title}] 中批量删除了 {count} 条明细至回收站")
        if is_ajax:
            return jsonify({'code': 200, 'message': f'成功将选中的 {count} 笔明细移入回收站！', 'count': count})
        flash(f'成功将选中的 {count} 笔明细移入回收站！', 'success')
        return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

    @app.route('/banquet/<int:banquet_id>/records/batch_unlink', methods=['POST'])
    @login_required
    def banquet_records_batch_unlink(banquet_id):
        """在专属宴席详情页批量移出明细记录（解除关联，保留在主账本中）"""
        b = db.session.get(Banquet, banquet_id)
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        if not b or b.deleted_at:
            if is_ajax:
                return jsonify({'code': 404, 'message': '宴席账本不存在！'}), 404
            flash('专属宴席不存在或已被删除！', 'warning')
            return redirect(url_for('banquets_view'))

        if (hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('banquets') == 1) or (can_user_edit_entity and not can_user_edit_entity(current_user, b, 'banquets')):
            if is_ajax:
                return jsonify({'code': 403, 'message': '当前页面为仅查看权限，无权移出记录！'}), 403
            flash('当前页面为仅查看权限，无权移出记录！', 'danger')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        if request.is_json:
            data = request.get_json(silent=True) or {}
            record_ids = data.get('record_ids', [])
        else:
            record_ids = request.form.getlist('record_ids') or request.form.getlist('record_ids[]')

        if not record_ids:
            if is_ajax:
                return jsonify({'code': 400, 'message': '请至少选择一条要移出的明细记录！'}), 400
            flash('请至少选择一条要移出的明细记录！', 'warning')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        count = 0
        for r_id in record_ids:
            try:
                r_id_int = int(r_id)
                r = db.session.get(GiftRecord, r_id_int)
                if r and not r.deleted_at and r.banquet_id == b.id:
                    r.banquet_id = None
                    count += 1
            except (ValueError, TypeError):
                continue

        db.session.commit()
        safe_log('批量移出宴席明细', f"从专属宴席 [{b.title}] 中批量移出了 {count} 笔记录（保留在主账本中）")
        if is_ajax:
            return jsonify({'code': 200, 'message': f'成功将选中的 {count} 笔明细移出此专属宴席（数据仍保留在主账本）！', 'count': count})
        flash(f'成功将选中的 {count} 笔明细移出此专属宴席（数据仍保留在主账本）！', 'success')
        return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

    @app.route('/banquet/<int:banquet_id>/quick_add', methods=['POST'])
    @login_required
    def banquet_quick_add(banquet_id):
        """现场快速录入收礼台账（支持 AJAX 与原生表单无缝双向兼容）"""
        b = db.session.get(Banquet, banquet_id)
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        if not b or b.deleted_at:
            if is_ajax:
                return jsonify({'code': 404, 'message': '宴席账本不存在'}), 404
            flash('宴席账本不存在或已被删除！', 'danger')
            return redirect(url_for('banquets_view'))

        if (hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('banquets') == 1) or (can_user_edit_entity and not can_user_edit_entity(current_user, b, 'banquets')):
            if is_ajax:
                return jsonify({'code': 403, 'message': '当前页面为仅查看权限，无权向此专属宴席登记收礼！'}), 403
            flash('当前页面为仅查看权限，无权向此专属宴席登记收礼！', 'danger')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        name = request.form.get('name', '').strip()
        amount_str = request.form.get('amount', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        notes = request.form.get('notes', '').strip()

        if not name or not amount_str:
            if is_ajax:
                return jsonify({'code': 400, 'message': '客人姓名与礼金金额为必填项！'}), 400
            flash('客人姓名与礼金金额为必填项！', 'danger')
            return redirect(url_for('banquet_detail_view', banquet_id=b.id))

        try:
            amount = cn2num(amount_str)
            if amount <= 0:
                raise ValueError
        except Exception:
            if is_ajax:
                return jsonify({'code': 400, 'message': '请输入有效的礼金金额！'}), 400
            flash('请输入有效的礼金金额！', 'danger')
            return redirect(url_for('banquet_detail_view', banquet_id=b.id))

        record = GiftRecord(
            name=name,
            amount=amount,
            phone=phone,
            address=address,
            event_reason=b.event_type or b.title,
            record_type='receive',
            notes=notes,
            banquet_id=b.id,
            user_id=current_user.id
        )
        db.session.add(record)
        db.session.commit()
        safe_log('现场快速录入', f"在宴席 [{b.title}] 中录入: [{name}] 金额: {amount}元")
        if not is_ajax:
            flash(f"成功登记客人 [{name}] 礼金 ¥{amount:.2f}！", 'success')
            return redirect(url_for('banquet_detail_view', banquet_id=b.id))
        return jsonify({
            'code': 200,
            'message': f"成功录入 [{name}] 礼金 ¥{amount:.2f}！",
            'record': {
                'id': record.id,
                'name': record.name,
                'amount': record.amount,
                'phone': record.phone or '',
                'address': record.address or '',
                'notes': record.notes or '',
                'created_at': record.created_at.strftime('%Y-%m-%d %H:%M')
            }
        })

    @app.route('/banquet/<int:banquet_id>/export_excel')
    @login_required
    def banquet_export_excel(banquet_id):
        """专属宴席一键导出台账 Excel / CSV"""
        b = db.session.get(Banquet, banquet_id)
        if not b or b.deleted_at:
            flash('账本不存在', 'danger')
            return redirect(url_for('banquets_view'))

        if can_user_edit_entity and not can_user_edit_entity(current_user, b, 'banquets'):
            flash('您没有权限修改该专属宴席！', 'danger')
            return redirect(url_for('banquets_view'))

        records = GiftRecord.query.filter_by(banquet_id=b.id).filter(GiftRecord.deleted_at.is_(None)).order_by(GiftRecord.created_at.asc()).all()

        output = io.StringIO()
        output.write('\ufeff')
        import csv
        writer = csv.writer(output)
        writer.writerow([f"【{b.title}】收礼台账与盈亏简报"])
        writer.writerow([f"活动类型: {b.event_type or '宴席'}", f"举办日期: {b.event_date or '未定'}", f"地点: {b.venue or '无'}"])
        total_income = sum(r.amount for r in records if getattr(r, 'record_type', 'receive') != 'send')
        cost = b.banquet_cost or 0.0
        writer.writerow([f"总收礼金额: ¥{total_income:.2f}", f"办宴成本: ¥{cost:.2f}", f"净盈亏: ¥{total_income - cost:.2f}"])
        writer.writerow([])
        writer.writerow(['序号', '客人姓名', '礼金金额(元)', '联系电话', '联系地址', '备注说明', '登记时间'])

        for idx, r in enumerate(records, start=1):
            writer.writerow([
                idx,
                r.name,
                f"{r.amount:.2f}",
                r.phone or '',
                r.address or '',
                r.notes or '',
                r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''
            ])

        response = Response(output.getvalue(), mimetype='text/csv; charset=utf-8')
        filename = f"banquet_{b.id}_{b.title}_ledger.csv"
        response.headers['Content-Disposition'] = f"attachment; filename={urllib.parse.quote(filename)}"
        safe_log('导出宴席台账', f"导出了宴席 [{b.title}] 的全部礼金记录")
        return response

    @app.route('/banquet/<int:banquet_id>/import_records', methods=['POST'])
    @login_required
    def banquet_import_records(banquet_id):
        """从礼金账本批量引入收礼明细记录到当前宴席"""
        b = db.session.get(Banquet, banquet_id)
        if not b or b.deleted_at:
            flash('专属宴席不存在或已被删除！', 'warning')
            return redirect(url_for('banquets_view'))
        if (hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('banquets') == 1) or (can_user_edit_entity and not can_user_edit_entity(current_user, b, 'banquets')):
            flash('当前页面为仅查看权限，无权引入记录！', 'danger')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        record_ids = request.form.getlist('record_ids') or request.form.getlist('record_ids[]')
        if not record_ids:
            flash('请勾选需要引入的礼金记录！', 'warning')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        count = 0
        for rid_str in record_ids:
            try:
                rid = int(rid_str)
                r = db.session.get(GiftRecord, rid)
                if r and not r.deleted_at and getattr(r, 'record_type', 'receive') == 'receive':
                    if can_user_edit_entity and not can_user_edit_entity(current_user, r, 'ledger'):
                        continue
                    r.banquet_id = b.id
                    count += 1
            except Exception:
                continue

        if count > 0:
            db.session.commit()
            safe_log('引入宴席明细', f"为专属宴席 [{b.title}] 引入了 {count} 笔收礼记录")
            flash(f'成功从礼金账本引入 {count} 笔收礼明细！', 'success')
        else:
            flash('未成功引入任何记录（仅收礼记录且有编辑权限的记录支持引入）！', 'warning')
        return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

    @app.route('/banquet/<int:banquet_id>/unlink_record/<int:record_id>', methods=['POST'])
    @login_required
    def banquet_unlink_record(banquet_id, record_id):
        """将明细记录移出当前宴席（解除关联，置 banquet_id=None，保留在主账本中）"""
        b = db.session.get(Banquet, banquet_id)
        if not b or b.deleted_at:
            flash('专属宴席不存在！', 'warning')
            return redirect(url_for('banquets_view'))
        if (hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('banquets') == 1) or (can_user_edit_entity and not can_user_edit_entity(current_user, b, 'banquets')):
            flash('当前页面为仅查看权限，无权移出记录！', 'danger')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        r = db.session.get(GiftRecord, record_id)
        if r and r.banquet_id == b.id:
            r.banquet_id = None
            db.session.commit()
            safe_log('移出宴席明细', f"将客人 [{r.name}] 的记录移出专属宴席 [{b.title}]（保留在主账本中）")
            flash(f'已将客人 [{r.name}] 的记录移出专属宴席（主账本数据仍完好保留）！', 'success')
        return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

    @app.route('/banquet/<int:banquet_id>/share', methods=['POST'])
    @login_required
    def banquet_share(banquet_id):
        """生成或配置宴席账本免登录只读分享链接（支持自定义有效期、自动更新新链接、停留在当前窗口）"""
        b = db.session.get(Banquet, banquet_id)
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        if not b or b.deleted_at:
            if is_ajax:
                return jsonify({'code': 404, 'success': False, 'message': '宴席不存在'}), 404
            flash('宴席不存在', 'danger')
            return redirect(url_for('banquets_view'))

        if (hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('banquets') == 1) or (can_user_edit_entity and not can_user_edit_entity(current_user, b, 'banquets')):
            if is_ajax:
                return jsonify({'code': 403, 'success': False, 'message': '当前页面为仅查看权限，无权配置分享！'}), 403
            flash('当前页面为仅查看权限，无权配置分享！', 'danger')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        import secrets
        password = request.form.get('access_password', '').strip()
        expire_days = request.form.get('expire_days', 'permanent').strip()
        hide_notes = bool(request.form.get('hide_notes'))
        hide_amount = bool(request.form.get('hide_amount'))

        expires_at = None
        expire_label = '永久有效'
        if expire_days == '1':
            expires_at = datetime.now() + timedelta(days=1)
            expire_label = '1天内有效'
        elif expire_days == '7':
            expires_at = datetime.now() + timedelta(days=7)
            expire_label = '7天内有效'
        elif expire_days == '30':
            expires_at = datetime.now() + timedelta(days=30)
            expire_label = '30天内有效'

        # 点击生成/更新时，重新生成全新的 token，确保链接地址真正更新发生改变
        new_token = secrets.token_urlsafe(16)
        share = SharedLedgerLink.query.filter_by(banquet_id=b.id).first()
        if not share:
            share = SharedLedgerLink(
                share_token=new_token,
                title=f"{b.title} 只读礼金单",
                user_id=current_user.id,
                banquet_id=b.id,
                access_password=password,
                hide_notes=hide_notes,
                hide_amount=hide_amount,
                expires_at=expires_at,
                is_active=True
            )
            db.session.add(share)
        else:
            share.share_token = new_token
            share.access_password = password
            share.hide_notes = hide_notes
            share.hide_amount = hide_amount
            share.expires_at = expires_at
            share.is_active = True

        db.session.commit()
        share_url = url_for('shared_ledger_view', token=share.share_token, _external=True)
        safe_log('配置分享链接', f"更新了宴席 [{b.title}] 的专属分享链接 (有效期: {expire_label})")

        if not is_ajax:
            flash(f'专属免登录只读分享链接已更新并生效（有效期: {expire_label}）！', 'success')
            return redirect(url_for('banquet_detail_view', banquet_id=b.id))
        return jsonify({
            'code': 200,
            'success': True,
            'message': f'专属免登录只读分享链接已成功生成并更新（有效期: {expire_label}）！',
            'share_url': share_url,
            'token': share.share_token,
            'expire_label': expire_label,
            'expires_at_str': expires_at.strftime('%Y-%m-%d %H:%M') if expires_at else '永久有效',
            'has_password': bool(password)
        })

    @app.route('/banquet/<int:banquet_id>/share/delete', methods=['POST'])
    @login_required
    def banquet_share_delete(banquet_id):
        """删除/作废宴席账本免登录只读分享链接"""
        b = db.session.get(Banquet, banquet_id)
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        if not b or b.deleted_at:
            if is_ajax:
                return jsonify({'code': 404, 'success': False, 'message': '宴席不存在'}), 404
            flash('宴席不存在', 'danger')
            return redirect(url_for('banquets_view'))

        if (hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('banquets') == 1) or (can_user_edit_entity and not can_user_edit_entity(current_user, b, 'banquets')):
            if is_ajax:
                return jsonify({'code': 403, 'success': False, 'message': '当前页面为仅查看权限，无权删除分享！'}), 403
            flash('当前页面为仅查看权限，无权删除分享！', 'danger')
            return redirect(url_for('banquet_detail_view', banquet_id=banquet_id))

        share = SharedLedgerLink.query.filter_by(banquet_id=b.id).first()
        if share:
            db.session.delete(share)
            db.session.commit()
            safe_log('删除分享链接', f"删除了宴席 [{b.title}] 的免登录分享链接")

        if not is_ajax:
            flash('专属分享链接已成功删除作废！', 'success')
            return redirect(url_for('banquet_detail_view', banquet_id=b.id))
        return jsonify({'code': 200, 'success': True, 'message': '专属分享链接已成功删除作废！'})




    @app.route('/reminders', methods=['GET', 'POST'])
    @login_required
    def reminders_view():
        """纪念日备忘列表与添加"""
        if request.method == 'POST':
            if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('reminders') == 1:
                flash('当前页面为仅查看权限，无权添加纪念日提醒！', 'danger')
                return redirect(url_for('reminders_view'))
            name = request.form.get('name', '').strip()
            relation = request.form.get('relation', '').strip()
            phone = request.form.get('phone', '').strip()
            target_date_str = request.form.get('target_date', '').strip()
            anniversary_type = request.form.get('anniversary_type', '生日').strip()
            advance_days = int(request.form.get('advance_days', 3) or 3)
            notes = request.form.get('notes', '').strip()

            if not name or not target_date_str:
                flash('姓名与纪念日日期不能为空！', 'danger')
                return redirect(url_for('reminders_view'))

            rem = AnniversaryReminder(
                name=name,
                relation=relation,
                phone=phone,
                target_date=target_date_str,
                anniversary_type=anniversary_type,
                advance_days=advance_days,
                notes=notes,
                user_id=current_user.id
            )
            db.session.add(rem)
            db.session.commit()
            safe_log('添加纪念日', f"添加了 [{name}] 的 {anniversary_type} 提醒（提前 {advance_days} 天）")
            try:
                triggered = check_and_trigger_due_reminders(current_app._get_current_object(), specific_reminder=rem)
                if triggered:
                    flash(f'成功添加 [{name}] 的纪念日提醒，该纪念日已进入预警期，系统已自动向 Webhook 机器人推送提醒通知！', 'success')
                else:
                    flash(f'成功添加 [{name}] 的纪念日提醒！', 'success')
            except Exception as e:
                flash(f'成功添加 [{name}] 的纪念日提醒！', 'success')
            return redirect(url_for('reminders_view'))

        query = get_accessible_reminders_query(current_user) if get_accessible_reminders_query else AnniversaryReminder.query.filter_by(user_id=current_user.id)
        query = query.filter(AnniversaryReminder.deleted_at.is_(None), AnniversaryReminder.is_active == True)
        search = request.args.get('search', '').strip()
        if search:
            search_pat = f"%{search}%"
            query = query.filter(db.or_(
                AnniversaryReminder.name.ilike(search_pat),
                AnniversaryReminder.relation.ilike(search_pat),
                AnniversaryReminder.anniversary_type.ilike(search_pat),
                AnniversaryReminder.notes.ilike(search_pat),
                AnniversaryReminder.phone.ilike(search_pat)
            ))
        reminders = query.all()
        today = datetime.now().date()
        reminders_data = []
        for r in reminders:
            next_date, days_left = parse_target_date_obj(r.target_date, today)
            if not next_date:
                continue
            adv_days = r.advance_days or 3
            is_upcoming = (0 <= days_left <= adv_days)
            reminders_data.append({
                'reminder': r,
                'next_date': next_date,
                'days_left': days_left,
                'is_upcoming': is_upcoming
            })
        reminders_data.sort(key=lambda x: x['days_left'])
        available_webhooks = WebhookConfig.query.filter_by(is_enabled=True).all()
        return render_template('reminders.html', reminders_data=reminders_data, reminders=reminders, search=search, available_webhooks=available_webhooks)

    @app.route('/reminder/edit/<int:reminder_id>', methods=['POST'])
    @login_required
    def reminder_edit(reminder_id):
        """编辑纪念日备忘"""
        rem = db.session.get(AnniversaryReminder, reminder_id)
        if not rem:
            flash('纪念日记录不存在！', 'danger')
            return redirect(url_for('reminders_view'))

        if can_user_edit_entity and not can_user_edit_entity(current_user, rem, 'reminders'):
            flash('您没有权限修改该纪念日！', 'danger')
            return redirect(url_for('reminders_view'))

        rem.name = request.form.get('name', rem.name).strip()
        rem.relation = request.form.get('relation', rem.relation).strip()
        rem.phone = request.form.get('phone', rem.phone).strip()
        target_date_str = request.form.get('target_date', '').strip()
        if target_date_str and target_date_str != rem.target_date:
            rem.target_date = target_date_str
            rem.last_notified_target = None
        rem.anniversary_type = request.form.get('anniversary_type', rem.anniversary_type).strip()
        try:
            rem.advance_days = int(request.form.get('advance_days', rem.advance_days) or 3)
        except Exception:
            pass
        rem.notes = request.form.get('notes', rem.notes).strip()
        db.session.commit()
        safe_log('修改纪念日', f"修改了亲友 [{rem.name}] 的纪念日信息")
        try:
            triggered = check_and_trigger_due_reminders(current_app._get_current_object(), specific_reminder=rem)
            if triggered:
                flash(f'亲友 [{rem.name}] 的纪念日提醒已更新，且已处于预警期内，系统已自动向 Webhook 机器人推送提醒通知！', 'success')
            else:
                flash(f'亲友 [{rem.name}] 的纪念日提醒已更新！', 'success')
        except Exception:
            flash(f'亲友 [{rem.name}] 的纪念日提醒已更新！', 'success')
        return redirect(url_for('reminders_view'))

    @app.route('/reminder/delete/<int:reminder_id>', methods=['POST'])
    @login_required
    def reminder_delete(reminder_id):
        """删除纪念日（移入回收站）"""
        rem = db.session.get(AnniversaryReminder, reminder_id)
        if not rem:
            flash('纪念日记录不存在！', 'warning')
            return redirect(url_for('reminders_view'))
        if can_user_delete_entity and not can_user_delete_entity(current_user, rem, 'reminders'):
            flash('您没有权限删除此纪念日！', 'danger')
            return redirect(url_for('reminders_view'))
        rem.deleted_at = datetime.now()
        db.session.commit()
        safe_log('移入回收站', f"软删除了亲友 [{rem.name}] 的纪念日 (ID #{reminder_id})", user=current_user)
        flash(f'亲友 [{rem.name}] 的纪念日已移入回收站！', 'success')
        return redirect(url_for('reminders_view'))

    @app.route('/reminders/batch_delete', methods=['POST'])
    @login_required
    def reminders_batch_delete():
        """批量软删除纪念日"""
        if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('reminders') in (1, 2):
            flash('当前页面权限不允许删除纪念日提醒！', 'danger')
            return redirect(url_for('reminders_view'))
        reminder_ids = request.form.getlist('reminder_ids') or request.form.getlist('reminder_ids[]')
        if not reminder_ids:
            flash('请勾选需要删除的纪念日！', 'warning')
            return redirect(url_for('reminders_view'))
        count = 0
        now = datetime.now()
        for rid_str in reminder_ids:
            try:
                rid = int(rid_str)
                rem = db.session.get(AnniversaryReminder, rid)
                if rem and (not can_user_delete_entity or can_user_delete_entity(current_user, rem, 'reminders')):
                    rem.deleted_at = now
                    count += 1
            except Exception:
                continue
        if count > 0:
            db.session.commit()
            safe_log('批量移入回收站', f"批量软删除了 {count} 条纪念日记录", user=current_user)
            flash(f'已成功将选中的 {count} 条纪念日移入回收站！', 'success')
        else:
            flash('未找到可删除的纪念日记录！', 'warning')
        return redirect(url_for('reminders_view'))

    @app.route('/api/reminders/trigger_push', methods=['POST'])
    @login_required
    def api_trigger_reminder_push():
        """手动或外部触发即将到期的亲友纪念日 Webhook 推送"""
        if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('reminders') == 1:
            return jsonify({'code': 403, 'message': '您当前对【纪念日备忘】页面为仅查看权限，无权发起手动推送提醒！'}), 403

        query = get_accessible_reminders_query(current_user) if get_accessible_reminders_query else AnniversaryReminder.query.filter_by(user_id=current_user.id)
        rems = query.filter(AnniversaryReminder.deleted_at.is_(None), AnniversaryReminder.is_active == True).all()
        today = datetime.now().date()
        upcoming = []
        for r in rems:
            this_year_date, days_left = parse_target_date_obj(r.target_date, today)
            if not this_year_date:
                continue
            adv_days = r.advance_days or 3
            if 0 <= days_left <= adv_days:
                upcoming.append((r, days_left, this_year_date))

        webhooks = WebhookConfig.query.filter_by(is_enabled=True).all()
        if not webhooks:
            return jsonify({
                'code': 400,
                'message': '当前未启用任何 Webhook 机器人，请先在【系统管理 -> Webhook 通知】中配置并启用企微/钉钉/飞书/Server酱通道！'
            }), 400

        if not upcoming:
            if rems:
                all_with_days = []
                for r in rems:
                    this_year_date, days_left = parse_target_date_obj(r.target_date, today)
                    if this_year_date:
                        all_with_days.append((r, days_left, this_year_date))
                all_with_days.sort(key=lambda x: x[1])
                nearest = all_with_days[:3]
                title, detail_msg, lines = format_reminder_notification_content(nearest)
                trigger_webhook_event(webhooks, 'reminder', f"{title}（测试推送最近 {len(nearest)} 条）", detail_msg)
                safe_log('推送纪念日提醒', f"Webhook 测试推送了最近 {len(nearest)} 条纪念日", user=current_user)
                return jsonify({
                    'code': 200,
                    'message': f'当前无预警期内的临近纪念日，已向启用的 Webhook 成功测试推送最近 {len(nearest)} 条亲友纪念日！',
                    'count': len(nearest),
                    'details': lines
                })
            return jsonify({'code': 200, 'message': '当前暂无任何有效的亲友纪念日记录，请先添加纪念日！', 'count': 0})

        title, detail_msg, lines = format_reminder_notification_content(upcoming)
        trigger_webhook_event(webhooks, 'reminder', title, detail_msg)
        safe_log('推送纪念日提醒', f"向 Webhook 推送了 {len(upcoming)} 条即将到期的纪念日", user=current_user)

        unbound_names = []
        for wh in webhooks:
            if wh.connection_type == 'long_connection':
                cid = extract_chatid_from_url(wh.webhook_url) or _cached_chatids.get(wh.bot_id)
                if not cid:
                    unbound_names.append(wh.channel_name)

        push_msg = f'成功向 Webhook 通道推送 {len(upcoming)} 条即将到期的亲友纪念日提醒！'
        if unbound_names:
            push_msg += f'【提示：检测到长连接机器人 [{", ".join(unbound_names)}] 尚未配置目标会话 chatid，请在管理后台填入群聊 chatid 或在企微群内 @机器人 一次完成绑定】'

        return jsonify({
            'code': 200,
            'message': push_msg,
            'count': len(upcoming),
            'details': lines
        })

    @app.route('/api/reminders/custom_push', methods=['POST'])
    @login_required
    def api_custom_reminder_push():
        """用户对单条或多条记录发起自定义手动推送提醒（可设置提醒次数与间隔时长）"""
        if hasattr(current_user, 'can_view_menu') and not current_user.can_view_menu('reminders'):
            return jsonify({'code': 403, 'message': '您没有【纪念日备忘】页面的访问权限！'}), 403
        if hasattr(current_user, 'get_menu_perm') and current_user.get_menu_perm('reminders') == 1:
            return jsonify({'code': 403, 'message': '您当前对【纪念日备忘】页面为仅查看权限，无权发起手动推送提醒！'}), 403

        data = request.get_json(silent=True) or {}
        reminder_ids = data.get('reminder_ids') or []
        if not reminder_ids and request.form.get('reminder_ids'):
            try:
                reminder_ids = [int(x.strip()) for x in request.form.get('reminder_ids').split(',') if x.strip().isdigit()]
            except Exception:
                reminder_ids = []

        repeat_count = int(data.get('repeat_count') or request.form.get('repeat_count') or 1)
        interval_seconds = int(data.get('interval_seconds') or request.form.get('interval_seconds') or 0)
        custom_note = (data.get('custom_note') or request.form.get('custom_note') or '').strip()

        repeat_count = max(1, min(5, repeat_count))
        interval_seconds = max(0, min(300, interval_seconds))

        query = get_accessible_reminders_query(current_user) if get_accessible_reminders_query else AnniversaryReminder.query.filter_by(user_id=current_user.id)
        query = query.filter(AnniversaryReminder.deleted_at.is_(None), AnniversaryReminder.is_active == True)

        if reminder_ids:
            rems = query.filter(AnniversaryReminder.id.in_(reminder_ids)).all()
        else:
            rems = query.all()

        if not rems:
            return jsonify({'code': 400, 'message': '未找到有效的纪念日记录，请确认记录是否存在或已被删除！'}), 400

        webhook_ids = data.get('webhook_ids') or []
        if not webhook_ids and request.form.get('webhook_ids'):
            try:
                webhook_ids = [int(x.strip()) for x in request.form.get('webhook_ids').split(',') if x.strip().isdigit()]
            except Exception:
                webhook_ids = []

        if webhook_ids:
            webhooks = WebhookConfig.query.filter(WebhookConfig.id.in_(webhook_ids), WebhookConfig.is_enabled == True).all()
        else:
            webhooks = WebhookConfig.query.filter_by(is_enabled=True).all()

        if not webhooks:
            return jsonify({'code': 400, 'message': '未选择或未找到启用的 Webhook 通知通道，请在弹窗中勾选至少一个有效通道！'}), 400

        today = datetime.now().date()
        rem_with_days = []
        for r in rems:
            next_date, days_left = parse_target_date_obj(r.target_date, today)
            if next_date:
                rem_with_days.append((r, days_left, next_date))

        if not rem_with_days:
            return jsonify({'code': 400, 'message': '所选纪念日的日期格式无效，无法计算到期时间！'}), 400

        custom_content = (data.get('custom_content') or request.form.get('custom_content') or '').strip()
        title, default_md, text_summary = format_reminder_notification_content(rem_with_days)
        if custom_content:
            md_detail = custom_content
        else:
            md_detail = default_md
            if custom_note:
                md_detail += "\n\n> 💡 **发起人特别附言**：" + custom_note
        if custom_note and custom_note not in md_detail:
            md_detail += "\n\n> 💡 **发起人特别附言**：" + custom_note

        target_app = current_app._get_current_object()
        wh_targets = [{
            'id': w.id,
            'user_id': w.user_id,
            'channel_name': w.channel_name,
            'url': getattr(w, 'webhook_url', '') or '',
            'secret': getattr(w, 'secret_token', None),
            'connection_type': getattr(w, 'connection_type', 'webhook_url') or 'webhook_url',
            'bot_platform': getattr(w, 'bot_platform', 'wecom') or 'wecom',
            'bot_id': getattr(w, 'bot_id', None),
            'bot_secret': getattr(w, 'bot_secret', None)
        } for w in webhooks]

        def _execute_push_round(round_idx, total_rounds):
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            sub_title = title if total_rounds == 1 else f"{title} (第{round_idx}/{total_rounds}次提醒)"
            for item in wh_targets:
                try:
                    conn_type = item.get('connection_type', 'webhook_url')
                    if conn_type == 'long_connection':
                        b_id = item.get('bot_id', '')
                        b_sec = item.get('bot_secret', '')
                        c_id = extract_chatid_from_url(item.get('url', '')) or _cached_chatids.get(b_id)
                        if b_id and b_sec:
                            s, c, b = send_wecom_long_connection_message(b_id, b_sec, sub_title, md_detail, now_str, 'reminder', chatid=c_id)
                            record_webhook_log(item.get('user_id'), item.get('id'), 'reminder', {"title": sub_title, "bot_id": b_id, "chatid": c_id, "details": md_detail}, c, b, s)
                        continue

                    url = item.get('url', '')
                    if not url:
                        continue

                    if 'dingtalk.com' in url:
                        payload = {
                            "msgtype": "markdown",
                            "markdown": {
                                "title": sub_title,
                                "text": f"### {sub_title}\n\n- **时间**: {now_str}\n- **说明**: {md_detail}\n\n> 礼金记账系统通知"
                            }
                        }
                    elif 'feishu.cn' in url or 'larksuite.com' in url:
                        payload = {
                            "msg_type": "text",
                            "content": {"text": f"{sub_title}\n时间: {now_str}\n\n{md_detail}"}
                        }
                    elif 'qyapi.weixin.qq.com' in url:
                        if md_detail and ('\n' in md_detail or chr(10) in md_detail):
                            md_cnt = f"### {sub_title}\n> 时间：<font color=\"comment\">{now_str}</font>\n\n{md_detail}"
                        else:
                            md_cnt = f"### {sub_title}\n> 时间：<font color=\"comment\">{now_str}</font>\n> 详情：<font color=\"info\">{md_detail or '无'}</font>"
                        payload = {
                            "msgtype": "markdown",
                            "markdown": {"content": md_cnt}
                        }
                    elif 'pushplus.plus' in url:
                        token = item.get('secret')
                        if not token and 'token=' in url:
                            parsed = urllib.parse.urlparse(url)
                            qs = urllib.parse.parse_qs(parsed.query)
                            token = qs.get('token', [''])[0]
                        html_details = md_detail.replace('\n', '<br>').replace(chr(10), '<br>') if md_detail else '无'
                        payload = {
                            "token": token,
                            "title": sub_title,
                            "content": f"<h3>{sub_title}</h3><p>时间：{now_str}</p><div>{html_details}</div>",
                            "template": "html"
                        }
                    elif 'ftqq.com' in url:
                        payload = {
                            "title": sub_title,
                            "desp": f"### {sub_title}\n\n- **时间**: {now_str}\n- **说明**: {md_detail}"
                        }
                    elif 'api.day.app' in url:
                        payload = {
                            "title": sub_title,
                            "body": f"{md_detail}\n时间: {now_str}",
                            "group": "礼金记账"
                        }
                    else:
                        payload = {
                            "event": "reminder",
                            "title": sub_title,
                            "time": now_str,
                            "details": md_detail,
                            "source": "gift_bookkeeping_app"
                        }

                    headers = {}
                    if item.get('secret'):
                        headers['Authorization'] = f"Bearer {item.get('secret')}"

                    s, c, b = _send_payload(url, payload, headers, timeout=12)
                    record_webhook_log(item.get('user_id'), item.get('id'), 'reminder', payload, c, b, s)
                except Exception as e:
                    print(f"[_execute_push_round error]: {e}")

        channel_names = [w.channel_name for w in webhooks]
        channel_str = '、'.join(channel_names)

        if repeat_count > 1:
            def _background_repeat_task():
                for r_idx in range(1, repeat_count + 1):
                    _execute_push_round(r_idx, repeat_count)
                    if r_idx < repeat_count:
                        time.sleep(max(1, interval_seconds))
            threading.Thread(target=_background_repeat_task, daemon=True).start()
            msg = f"已启动多轮定时推送任务：将累计向 [{channel_str}] 推送 {repeat_count} 次（每隔 {interval_seconds} 秒一次），共涵盖 {len(rem_with_days)} 条纪念日！"
        else:
            _execute_push_round(1, 1)
            msg = f"成功向 [{channel_str}] 推送 {len(rem_with_days)} 条亲友重要纪念日提醒！"
        safe_log('手动推送纪念日', f"推送了 {len(rem_with_days)} 条纪念日，次数: {repeat_count}, 间隔: {interval_seconds}秒", user=current_user)
        return jsonify({
            'code': 200,
            'message': msg,
            'count': len(rem_with_days),
            'repeat_count': repeat_count,
            'interval_seconds': interval_seconds,
            'details': text_summary
        })

    @app.route('/api/reminders/upcoming')
    @login_required
    def api_upcoming_reminders():
        """获取近期（3~7天内）的纪念日提醒"""
        rems = AnniversaryReminder.query.filter_by(user_id=current_user.id, is_active=True).all()
        today = datetime.now().date()
        upcoming = []

        for r in rems:
            this_year_date, days_left = parse_target_date_obj(r.target_date, today)
            if not this_year_date:
                continue
            adv_days = r.advance_days or 3
            if 0 <= days_left <= adv_days:
                upcoming.append({
                    'id': r.id,
                    'name': r.name,
                    'relation': r.relation or '',
                    'anniversary_type': r.anniversary_type or '纪念日',
                    'date': this_year_date.strftime('%m月%d日'),
                    'days_left': days_left,
                    'notes': r.notes or ''
                })

        return jsonify({'code': 200, 'reminders': upcoming})

    @app.route('/share/toggle', methods=['POST'])
    @login_required
    def toggle_share_ledger():
        """生成或切换免登录共享账本链接"""
        data = request.get_json() or {}
        share = SharedLedgerLink.query.filter_by(user_id=current_user.id).first()
        
        if not share:
            share = SharedLedgerLink.generate_new(current_user.id)
            db.session.add(share)
        else:
            if 'is_active' in data:
                share.is_active = bool(data['is_active'])
            else:
                share.is_active = not share.is_active
                
        db.session.commit()
        return jsonify({
            'success': True,
            'is_active': share.is_active,
            'token': share.token,
            'share_url': url_for('shared_ledger_view', token=share.token, _external=True)
        })


    @app.route('/admin/broadcasts', methods=['GET', 'POST'])
    @login_required
    def admin_broadcasts():
        """管理员系统广播管理"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))
            
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            level = request.form.get('level', 'info').strip()
            scope = request.form.get('scope', 'all').strip() or 'all'
            
            is_active_val = request.form.get('is_active')
            if is_active_val is not None:
                is_active = is_active_val in ('1', 'on', 'true', 'True')
            else:
                is_active = True  # 新增广播默认上线发布
            
            if not content:
                flash('广播内容不能为空', 'warning')
            else:
                bc = Broadcast(
                    title=title or '系统公告',
                    content=content,
                    level=level,
                    scope=scope,
                    is_active=is_active,
                    created_by_user_id=current_user.id
                )
                db.session.add(bc)
                db.session.commit()
                safe_log('创建系统广播', f"标题: {title or '无标题'}，等级: {level}，范围: {scope}，状态: {'上线' if is_active else '下线'}", user=current_user)
                flash('系统广播已成功发布！', 'success')
                return redirect(url_for('admin_broadcasts'))
                
        broadcasts = Broadcast.query.order_by(Broadcast.created_at.desc()).all()
        return render_template('admin_broadcasts.html', broadcasts=broadcasts)

    @app.route('/admin/broadcast/toggle/<int:broadcast_id>', methods=['GET', 'POST'])
    @login_required
    def admin_toggle_broadcast(broadcast_id):
        """切换广播状态（支持 AJAX 与普通表单重定向，杜绝裸露出 JSON）"""
        is_ajax = (request.headers.get('X-Requested-With') == 'XMLHttpRequest') or (request.is_json)
        if not current_user.is_admin:
            if is_ajax:
                return jsonify({'success': False, 'message': '权限不足'}), 403
            flash('权限不足', 'danger')
            return redirect(url_for('admin_broadcasts'))
        bc = db.session.get(Broadcast, broadcast_id)
        if not bc:
            if is_ajax:
                return jsonify({'success': False, 'message': '广播不存在'}), 404
            flash('广播不存在', 'warning')
            return redirect(url_for('admin_broadcasts'))
        bc.is_active = not bc.is_active
        db.session.commit()
        safe_log('切换系统广播状态', f"ID: {broadcast_id} -> {'上线' if bc.is_active else '下线'}", user=current_user)
        if is_ajax:
            return jsonify({'success': True, 'is_active': bc.is_active})
        flash(f"系统广播已{'上线展示' if bc.is_active else '下线暂不展示'}！", 'success')
        return redirect(url_for('admin_broadcasts'))

    @app.route('/admin/broadcast/delete/<int:broadcast_id>', methods=['POST'])
    @login_required
    def admin_delete_broadcast(broadcast_id):
        """删除广播"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))
        bc = db.session.get(Broadcast, broadcast_id)
        if bc:
            db.session.delete(bc)
            db.session.commit()
            safe_log('删除系统广播', f"ID: {broadcast_id}", user=current_user)
            flash('广播已彻底删除', 'success')
        return redirect(url_for('admin_broadcasts'))

    @app.route('/api/broadcasts')
    @app.route('/api/broadcasts/active')
    @login_required
    def api_active_broadcasts():
        """获取当前所有有效系统广播及当前用户的已读/未读状态"""
        active_bcs = Broadcast.query.filter_by(is_active=True).order_by(Broadcast.created_at.desc()).all()
        read_bc_ids = set(
            row[0] for row in db.session.query(BroadcastRead.broadcast_id).filter_by(user_id=current_user.id).all()
        )
        data = []
        unread_count = 0
        for bc in active_bcs:
            if bc.scope == 'admin' and not current_user.is_admin:
                continue
            if bc.scope == 'user' and current_user.is_admin:
                continue
            is_read = (bc.id in read_bc_ids)
            if not is_read:
                unread_count += 1
            data.append({
                'id': bc.id,
                'title': bc.title or '系统通知',
                'content': bc.content,
                'level': bc.level or 'info',
                'scope': bc.scope or 'all',
                'created_at': bc.created_at.strftime('%Y-%m-%d %H:%M') if bc.created_at else '',
                'is_read': is_read
            })
        return jsonify({'code': 200, 'broadcasts': data, 'unread_count': unread_count})

    @app.route('/api/broadcast/mark_read/<int:bc_id>', methods=['POST'])
    @login_required
    def api_mark_broadcast_read(bc_id):
        """标记单条广播为当前用户已读"""
        existing = BroadcastRead.query.filter_by(broadcast_id=bc_id, user_id=current_user.id).first()
        if not existing:
            br = BroadcastRead(broadcast_id=bc_id, user_id=current_user.id)
            db.session.add(br)
            db.session.commit()
        return jsonify({'code': 200, 'message': '已标记为已读'})

    @app.route('/api/broadcast/mark_all_read', methods=['POST'])
    @login_required
    def api_mark_all_broadcast_read():
        """一键将所有有效广播标记为当前用户已读"""
        active_bcs = Broadcast.query.filter_by(is_active=True).all()
        read_bc_ids = set(
            row[0] for row in db.session.query(BroadcastRead.broadcast_id).filter_by(user_id=current_user.id).all()
        )
        for bc in active_bcs:
            if bc.id not in read_bc_ids:
                db.session.add(BroadcastRead(broadcast_id=bc.id, user_id=current_user.id))
        db.session.commit()
        return jsonify({'code': 200, 'message': '所有通知已全部标记为已读'})

    @app.route('/admin/webhooks', methods=['GET'])
    @login_required
    def admin_webhooks():
        """管理员 Webhook 与长连接机器人配置及推送日志"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))

        webhooks = WebhookConfig.query.order_by(WebhookConfig.created_at.desc()).all()
        logs = WebhookLog.query.order_by(WebhookLog.created_at.desc()).limit(500).all()
        return render_template('admin_webhooks.html', webhooks=webhooks, logs=logs)

    @app.route('/admin/webhooks/create', methods=['POST'])
    @login_required
    def admin_create_webhook():
        """添加 Webhook 或企业微信长连接机器人"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))

        connection_type = request.form.get('connection_type', 'webhook_url').strip()
        bot_platform = request.form.get('bot_platform', 'wecom').strip()
        name = request.form.get('name', '').strip()
        url = request.form.get('url', '').strip()
        secret = request.form.get('secret', '').strip()
        bot_id = request.form.get('bot_id', '').strip()
        bot_secret = request.form.get('bot_secret', '').strip()
        chatid = request.form.get('chatid', '').strip()

        notify_on_add = bool(request.form.get('notify_on_add'))
        notify_on_delete = bool(request.form.get('notify_on_delete'))
        notify_on_reminder = bool(request.form.get('notify_on_reminder'))
        notify_on_broadcast = bool(request.form.get('notify_on_broadcast'))

        if not name:
            flash('渠道名称不能为空！', 'warning')
            return redirect(url_for('admin_webhooks'))

        if connection_type == 'long_connection':
            if not bot_id or not bot_secret:
                flash('长连接模式必须填写 Bot ID 和 Secret 两个凭证！', 'warning')
                return redirect(url_for('admin_webhooks'))
            is_v, msg_v = validate_wecom_credentials(bot_id, bot_secret)
            if not is_v:
                flash(f'企业微信机器人凭证校验未通过：{msg_v}', 'danger')
                return redirect(url_for('admin_webhooks'))
            if not url or url.startswith('wecom://bot/'):
                url = f"wecom://bot/{bot_id}?chatid={chatid}" if chatid else f"wecom://bot/{bot_id}"
        else:
            if not url:
                flash('标准 Webhook 模式的目标 URL 不能为空！', 'warning')
                return redirect(url_for('admin_webhooks'))

        hook = WebhookConfig(
            user_id=current_user.id,
            channel_name=name,
            connection_type=connection_type,
            bot_platform=bot_platform,
            bot_id=bot_id if connection_type == 'long_connection' else None,
            bot_secret=bot_secret if connection_type == 'long_connection' else None,
            webhook_url=url,
            secret_token=secret if connection_type == 'webhook_url' else None,
            notify_on_add=notify_on_add,
            notify_on_delete=notify_on_delete,
            notify_on_reminder=notify_on_reminder,
            notify_on_broadcast=notify_on_broadcast,
            is_enabled=True
        )
        db.session.add(hook)
        db.session.commit()
        safe_log('添加Webhook', f"名称: {name}, 连接方式: {connection_type}")
        flash(f'Webhook / 机器人通道 [{name}] 配置添加成功！', 'success')
        return redirect(url_for('admin_webhooks'))

    @app.route('/admin/webhooks/edit/<int:webhook_id>', methods=['POST'])
    @login_required
    def admin_edit_webhook(webhook_id):
        """编辑 Webhook 或企业微信长连接机器人配置"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))

        hook = db.session.get(WebhookConfig, webhook_id)
        if not hook:
            flash('Webhook 配置不存在', 'danger')
            return redirect(url_for('admin_webhooks'))

        connection_type = request.form.get('connection_type', 'webhook_url').strip()
        bot_platform = request.form.get('bot_platform', 'wecom').strip()
        name = request.form.get('name', '').strip()
        url = request.form.get('url', '').strip()
        secret = request.form.get('secret', '').strip()
        bot_id = request.form.get('bot_id', '').strip()
        bot_secret = request.form.get('bot_secret', '').strip()
        chatid = request.form.get('chatid', '').strip()

        if not name:
            flash('渠道名称不能为空！', 'warning')
            return redirect(url_for('admin_webhooks'))

        if connection_type == 'long_connection':
            if not bot_id or not bot_secret:
                flash('长连接模式必须填写 Bot ID 和 Secret 两个凭证！', 'warning')
                return redirect(url_for('admin_webhooks'))
            is_v, msg_v = validate_wecom_credentials(bot_id, bot_secret)
            if not is_v:
                flash(f'企业微信机器人凭证校验未通过：{msg_v}', 'danger')
                return redirect(url_for('admin_webhooks'))
            if not chatid and hook.webhook_url:
                chatid = extract_chatid_from_url(hook.webhook_url) or ''
            url = f"wecom://bot/{bot_id}?chatid={chatid}" if chatid else f"wecom://bot/{bot_id}"
            hook.bot_id = bot_id
            hook.bot_secret = bot_secret
            hook.secret_token = None
        else:
            if not url:
                flash('标准 Webhook 模式的目标 URL 不能为空！', 'warning')
                return redirect(url_for('admin_webhooks'))
            hook.secret_token = secret
            hook.bot_id = None
            hook.bot_secret = None

        hook.channel_name = name
        hook.connection_type = connection_type
        hook.bot_platform = bot_platform
        hook.webhook_url = url
        hook.notify_on_add = bool(request.form.get('notify_on_add'))
        hook.notify_on_delete = bool(request.form.get('notify_on_delete'))
        hook.notify_on_reminder = bool(request.form.get('notify_on_reminder'))
        hook.notify_on_broadcast = bool(request.form.get('notify_on_broadcast'))

        db.session.commit()
        safe_log('编辑Webhook', f"ID: {webhook_id}, 名称: {name}, 连接方式: {connection_type}")
        flash(f'Webhook [{name}] 配置已成功更新！', 'success')
        return redirect(url_for('admin_webhooks'))

    @app.route('/admin/webhooks/toggle/<int:webhook_id>', methods=['POST'])
    @app.route('/admin/webhook/toggle/<int:webhook_id>', methods=['POST'])
    @login_required
    def admin_toggle_webhook(webhook_id):
        """切换 Webhook 激活状态"""
        if not current_user.is_admin:
            return jsonify({'success': False, 'message': '权限不足'}), 403
        hook = db.session.get(WebhookConfig, webhook_id)
        if not hook:
            flash('Webhook不存在', 'danger')
            return redirect(url_for('admin_webhooks'))
        hook.is_enabled = not hook.is_enabled
        db.session.commit()
        flash(f"Webhook [{hook.channel_name}] 状态已更新！", 'success')
        return redirect(url_for('admin_webhooks'))

    @app.route('/admin/webhooks/delete/<int:webhook_id>', methods=['POST'])
    @app.route('/admin/webhook/delete/<int:webhook_id>', methods=['POST'])
    @login_required
    def admin_delete_webhook(webhook_id):
        """删除 Webhook 配置"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))
        hook = db.session.get(WebhookConfig, webhook_id)
        if hook:
            db.session.delete(hook)
            safe_log('删除Webhook', f"ID: {webhook_id}")
            db.session.commit()
            flash('Webhook 配置已删除', 'success')
        return redirect(url_for('admin_webhooks'))

    @app.route('/admin/webhooks/test/<int:webhook_id>', methods=['POST'])
    @app.route('/admin/webhook/test/<int:webhook_id>', methods=['POST'])
    @login_required
    def admin_test_webhook(webhook_id):
        """测试 Webhook 或长连接机器人发送"""
        if not current_user.is_admin:
            return jsonify({'success': False, 'message': '权限不足'}), 403
        hook = db.session.get(WebhookConfig, webhook_id)
        if not hook:
            return jsonify({'success': False, 'message': 'Webhook不存在'}), 404

        try:
            success, code, msg = test_single_webhook(hook, sender_name=current_user.username)
            return jsonify({
                'success': bool(success),
                'code': 200 if success else 500,
                'status_code': code,
                'message': msg
            })
        except Exception as e:
            return jsonify({'success': False, 'code': 500, 'message': str(e)}), 500

    @app.route('/admin/webhook/logs/delete/<int:log_id>', methods=['POST'])
    @login_required
    def admin_delete_webhook_log(log_id):
        """删除单条 Webhook 推送日志"""
        if not current_user.is_admin:
            return jsonify({'code': 403, 'message': '权限不足'}), 403
        log_item = db.session.get(WebhookLog, log_id)
        if not log_item:
            return jsonify({'code': 404, 'message': '日志不存在或已被删除'}), 404
        db.session.delete(log_item)
        db.session.commit()
        return jsonify({'code': 200, 'message': '推送日志已成功删除！'})

    @app.route('/admin/webhook/logs/batch_delete', methods=['POST'])
    @login_required
    def admin_batch_delete_webhook_logs():
        """批量删除 Webhook 推送日志"""
        if not current_user.is_admin:
            return jsonify({'code': 403, 'message': '权限不足'}), 403
        data = request.get_json(silent=True) or {}
        ids = data.get('log_ids') or []
        if not ids and request.form.get('log_ids'):
            try:
                ids = [int(x.strip()) for x in request.form.get('log_ids').split(',') if x.strip().isdigit()]
            except Exception:
                ids = []
        if not ids:
            return jsonify({'code': 400, 'message': '请先勾选需要删除的日志记录！'}), 400

        deleted_count = WebhookLog.query.filter(WebhookLog.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({'code': 200, 'message': f'已成功删除 {deleted_count} 条推送日志！', 'deleted_count': deleted_count})

    @app.route('/admin/webhook/logs/clear', methods=['POST'])
    @login_required
    def admin_clear_webhook_logs():
        """清空全部 Webhook 推送日志"""
        if not current_user.is_admin:
            return jsonify({'code': 403, 'message': '权限不足'}), 403
        count = WebhookLog.query.delete(synchronize_session=False)
        db.session.commit()
        return jsonify({'code': 200, 'message': f'已成功清空全部 {count} 条推送日志！'})

    @app.route('/api/wecom/callback', methods=['GET', 'POST'])
    @app.route('/webhook/callback', methods=['GET', 'POST'])
    @app.route('/wecom/callback', methods=['GET', 'POST'])
    @app.route('/api/wecom', methods=['GET', 'POST'])
    @app.route('/webhook', methods=['GET', 'POST'])
    @app.route('/wecom', methods=['GET', 'POST'])
    @app.route('/callback', methods=['GET', 'POST'])
    @app.route('/api/wecom/webhook', methods=['GET', 'POST'])
    @app.route('/wechat/callback', methods=['GET', 'POST'])
    def wecom_http_callback():
        """
        企业微信群机器人 / 智能机器人 HTTP 回调接口
        支持 GET 验证 echostr，支持 POST 接收群内 @机器人 消息并提取目标 chatid
        """
        # 1. 企微 GET 回调验证
        echostr = request.args.get('echostr', '').strip()
        if request.method == 'GET':
            if echostr:
                return echostr, 200, {'Content-Type': 'text/plain; charset=utf-8'}
            return jsonify({'code': 200, 'status': 'ok', 'message': 'WeCom callback endpoint is active'}), 200

        # 2. 企微 POST 回调消息
        try:
            raw_body = request.get_data(as_text=True)
            chatid = None
            sender = None
            content = None
            bot_id = request.args.get('bot_id', '')

            # 尝试 JSON 解析
            if request.is_json or (raw_body and raw_body.strip().startswith('{')):
                try:
                    data = json.loads(raw_body)
                    chatid = data.get('chatid') or data.get('ChatId')
                    if not chatid and isinstance(data.get('from'), dict):
                        chatid = data['from'].get('userid') or data['from'].get('id')
                    sender = (data.get('from', {}) if isinstance(data.get('from'), dict) else {}).get('name') or '用户'
                    content = (data.get('text', {}) if isinstance(data.get('text'), dict) else {}).get('content') or ''
                    if not bot_id:
                        bot_id = data.get('aibot_id') or data.get('bot_id') or ''
                except Exception:
                    pass

            # 尝试 XML 解析
            elif raw_body and '<xml>' in raw_body:
                import re
                cid_match = re.search(r'<ChatId><!\[CDATA\[(.*?)\]\]></ChatId>', raw_body) or re.search(r'<ChatId>(.*?)</ChatId>', raw_body)
                if cid_match:
                    chatid = cid_match.group(1).strip()
                from_match = re.search(r'<FromUserName><!\[CDATA\[(.*?)\]\]></FromUserName>', raw_body) or re.search(r'<FromUserName>(.*?)</FromUserName>', raw_body)
                if from_match:
                    sender = from_match.group(1).strip()
                cnt_match = re.search(r'<Content><!\[CDATA\[(.*?)\]\]></Content>', raw_body) or re.search(r'<Content>(.*?)</Content>', raw_body)
                if cnt_match:
                    content = cnt_match.group(1).strip()

            # 正则兜底解析
            if not chatid and raw_body:
                import re
                m = re.search(r'["\']chatid["\']\s*:\s*["\']([^"\']+)["\']', raw_body, re.IGNORECASE)
                if m:
                    chatid = m.group(1).strip()

            if chatid:
                if bot_id:
                    _cached_chatids[bot_id] = chatid
                wh_list = WebhookConfig.query.filter_by(is_enabled=True).all()
                bound_names = []
                for wh in wh_list:
                    if wh.bot_platform == 'wecom' or (bot_id and wh.bot_id == bot_id) or (wh.webhook_url and 'wecom' in wh.webhook_url):
                        if wh.bot_id:
                            _cached_chatids[wh.bot_id] = chatid
                        if not wh.webhook_url or wh.webhook_url.startswith('wecom://') or wh.connection_type == 'long_connection':
                            wh.webhook_url = f"wecom://bot/{wh.bot_id or 'aibot'}?chatid={chatid}"
                        elif 'chatid=' in wh.webhook_url:
                            wh.webhook_url = re.sub(r'chatid=[^&]+', f'chatid={chatid}', wh.webhook_url)
                        else:
                            sep = '&' if '?' in wh.webhook_url else '?'
                            wh.webhook_url = f"{wh.webhook_url}{sep}chatid={chatid}"
                        bound_names.append(wh.channel_name)
                db.session.commit()

                record_webhook_log(
                    1,
                    wh_list[0].id if wh_list else 1,
                    'receive_chatid',
                    {"chatid": chatid, "sender": sender, "content": content},
                    200,
                    f"成功从企业微信 HTTP 回调中捕获群聊会话 chatid [{chatid}]，已自动绑定渠道: {', '.join(bound_names) or '企微渠道'}",
                    True
                )
                if raw_body and ('<xml' in raw_body.lower()):
                    reply_xml = f"""<xml>
<ToUserName><![CDATA[{sender or ''}]]></ToUserName>
<FromUserName><![CDATA[bot]]></FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[【人情礼金记账系统】已成功捕获并绑定本群聊会话(chatid: {chatid})！后续重要纪念日与记账提醒将自动推送到本群。]]></Content>
</xml>"""
                    return reply_xml, 200, {'Content-Type': 'application/xml; charset=utf-8'}
                return jsonify({'errcode': 0, 'errmsg': 'ok', 'chatid': chatid, 'message': f'已成功绑定群聊会话 [{chatid}]'}), 200

            return jsonify({'errcode': 0, 'errmsg': 'received'}), 200
        except Exception as e:
            return jsonify({'errcode': 0, 'errmsg': str(e)}), 200


    @app.route('/admin/backups', methods=['GET'])
    @login_required
    def admin_backups():
        """WebDAV 备份与恢复管理（瞬间响应，列表通过前端异步拉取）"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))

        config = BackupConfig.get_config()
        return render_template(
            'admin_backups.html',
            config=config,
            config_data=config,
            backups=[],
            backup_files=[]
        )

    @app.route('/admin/backups/list_ajax', methods=['GET'])
    @login_required
    def admin_backups_list_ajax():
        """异步拉取远端 WebDAV 备份文件列表，带5秒超时与安全容灾"""
        if not current_user.is_admin:
            return jsonify({'success': False, 'message': '权限不足'}), 403
        config = BackupConfig.get_config()
        if not config.server_url or not config.username:
            return jsonify({'success': True, 'configured': False, 'backups': [], 'message': '未配置 WebDAV'})
        try:
            ok, res = list_webdav_backups(config)
            if ok:
                return jsonify({'success': True, 'configured': True, 'backups': res})
            else:
                return jsonify({'success': False, 'configured': True, 'message': str(res), 'backups': []})
        except Exception as e:
            return jsonify({'success': False, 'configured': True, 'message': f'拉取备份异常: {str(e)}', 'backups': []})

    @app.route('/admin/backups/save_config', methods=['POST'])
    @app.route('/admin/backup/config', methods=['POST'])
    @login_required
    def admin_save_webdav_config():
        """保存 WebDAV 配置"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))

        config = BackupConfig.get_config()
        server_url = request.form.get('webdav_url', '').strip() or request.form.get('server_url', '').strip()
        username = request.form.get('webdav_username', '').strip() or request.form.get('username', '').strip()
        password = request.form.get('webdav_password', '').strip() or request.form.get('password', '').strip()
        remote_dir = request.form.get('remote_dir', '').strip() or request.form.get('backup_path', '').strip()

        config.webdav_url = server_url
        config.webdav_username = username
        if password:
            config.set_webdav_password(password)
        if remote_dir:
            config.backup_path = remote_dir

        db.session.commit()
        safe_log('更新WebDAV配置', f"服务器: {server_url}")
        flash('WebDAV 备份配置已保存！', 'success')
        return redirect(url_for('admin_backups'))

    @app.route('/admin/backups/trigger', methods=['POST'])
    @app.route('/admin/backup/create', methods=['POST'])
    @login_required
    def admin_trigger_webdav_backup():
        """手动触发创建 WebDAV 备份"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))

        config = BackupConfig.get_config()
        if not config.server_url or not config.username:
            flash('请先完善 WebDAV 配置！', 'warning')
            return redirect(url_for('admin_backups'))

        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        success, msg = upload_backup_webdav(config, db_path)
        if success:
            config.last_backup_time = datetime.now()
            config.last_status = '备份成功'
            db.session.commit()
            safe_log('创建WebDAV备份', f"文件名: {msg}")
            flash(f'备份成功上传至 WebDAV: {msg}', 'success')
        else:
            config.last_status = f'失败: {msg}'
            db.session.commit()
            flash(f'备份失败: {msg}', 'danger')
        return redirect(url_for('admin_backups'))

    @app.route('/admin/backup/download_local')
    @login_required
    def admin_download_local_backup():
        """一键下载当前本地 SQLite 数据库文件（离线备份）"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))

        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        if not os.path.exists(db_path):
            flash('数据库文件不存在！', 'danger')
            return redirect(url_for('admin_backups'))

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"gift_bookkeeping_backup_{timestamp}.db"
        safe_log('下载本地备份', f"下载了当前数据库备份文件: {filename}")
        return send_from_directory(
            os.path.dirname(os.path.abspath(db_path)),
            os.path.basename(db_path),
            as_attachment=True,
            download_name=filename
        )

    @app.route('/admin/backup/upload_local', methods=['POST'])
    @login_required
    def admin_upload_local_backup():
        """上传本地 .db 备份文件并恢复"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))

        file = request.files.get('backup_file')
        if not file or not file.filename:
            flash('请选择需要上传恢复的 .db 备份文件！', 'warning')
            return redirect(url_for('admin_backups'))

        if not file.filename.endswith('.db'):
            flash('仅支持恢复 SQLite 数据库文件 (.db)！', 'danger')
            return redirect(url_for('admin_backups'))

        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        try:
            # 备份现有数据库防止损坏
            if os.path.exists(db_path):
                shutil.copy2(db_path, db_path + f".bak_{int(time.time())}")
            file.save(db_path)
            safe_log('上传恢复本地备份', f"成功恢复了上传的数据库文件: {file.filename}")
            flash('本地数据库备份文件已成功恢复生效！', 'success')
        except Exception as e:
            flash(f'恢复数据库文件失败: {e}', 'danger')

        return redirect(url_for('admin_backups'))

    @app.route('/admin/backups/restore', methods=['POST'])
    @app.route('/admin/backup/restore', methods=['POST'])
    @app.route('/admin/backups/restore/<path:filename>', methods=['POST'])
    @login_required
    def admin_restore_webdav_backup(filename=None):
        """从 WebDAV 恢复备份"""
        if not current_user.is_admin:
            flash('权限不足', 'danger')
            return redirect(url_for('index'))

        target_filename = filename or request.form.get('filename', '').strip() or request.args.get('filename', '').strip()
        if not target_filename:
            flash('未指定备份文件', 'warning')
            return redirect(url_for('admin_backups'))

        config = BackupConfig.get_config()
        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        success, msg = restore_webdav_backup(config, target_filename, db_path)
        if success:
            safe_log('恢复WebDAV备份', f"文件名: {target_filename}")
            flash('备份已成功恢复！', 'success')
        else:
            flash(f'恢复失败: {msg}', 'danger')
        return redirect(url_for('admin_backups'))

    @app.route('/admin/backups/test_connection', methods=['POST'])
    @login_required
    def admin_test_webdav():
        """测试 WebDAV 连接（兼容 JSON 与 Form 表单格式）"""
        if not current_user.is_admin:
            return jsonify({'success': False, 'message': '权限不足'}), 403
        config = BackupConfig.get_config()
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form
        server_url = (data.get('webdav_url') or data.get('server_url') or '').strip() or config.server_url
        username = (data.get('webdav_username') or data.get('username') or '').strip() or config.webdav_username
        password = (data.get('webdav_password') or data.get('password') or '').strip() or config.password
        backup_path = (data.get('backup_path') or data.get('remote_dir') or '').strip() or getattr(config, 'backup_path', '')
        ok, msg = test_webdav_connection(server_url, username, password, backup_path=backup_path)
        return jsonify({'success': ok, 'message': msg})

    @app.route('/manifest.json')
    def pwa_manifest():
        """PWA 清单文件"""
        return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

    @app.route('/sw.js')
    def pwa_sw():
        """Service Worker 脚本"""
        response = make_response(send_from_directory('static', 'sw.js', mimetype='application/javascript'))
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.route('/shared/<token>', methods=['GET', 'POST'])
    def shared_ledger_view(token):
        """免登录只读共享视图"""
        share = SharedLedgerLink.query.filter_by(share_token=token, is_active=True).first()

        if not share:
            flash('共享链接已失效或不存在', 'danger')
            return redirect(url_for('login'))

        if share.expires_at and share.expires_at < datetime.now():
            flash('该分享链接已超时失效', 'warning')
            return redirect(url_for('login'))

        # 校验访问密码
        needs_password = False
        if share.access_password:
            auth_key = f'shared_auth_{token}'
            if request.method == 'POST':
                pwd = request.form.get('access_password', '').strip()
                if pwd == share.access_password:
                    session[auth_key] = True
                else:
                    flash('访问密码错误，请重新输入！', 'danger')
            if not session.get(auth_key):
                needs_password = True
                return render_template(
                    'shared_ledger.html',
                    share=share,
                    share_title=share.title or '专属共享账本',
                    needs_password=True,
                    records=[],
                    owner_name='',
                    total_received=0,
                    total_given=0
                )

        if share.banquet_id:
            b = db.session.get(Banquet, share.banquet_id)
            records = GiftRecord.query.filter_by(banquet_id=b.id).filter(GiftRecord.deleted_at.is_(None)).order_by(GiftRecord.created_at.asc()).all()
            owner = getattr(share, 'owner', getattr(share, 'user', None))
            share_title = b.title
        else:
            owner = db.session.get(User, share.user_id)
            records = GiftRecord.query.filter_by(user_id=owner.id).filter(GiftRecord.deleted_at.is_(None)).order_by(GiftRecord.created_at.desc()).all()
            share_title = share.title or f"{owner.username} 的礼金账本"

        total_received = sum(r.amount for r in records if getattr(r, 'record_type', 'receive') != 'send')
        total_given = sum(r.amount for r in records if getattr(r, 'record_type', 'receive') == 'send')

        return render_template(
            'shared_ledger.html',
            owner=owner,
            owner_name=owner.username if owner else '系统用户',
            records=records,
            share=share,
            share_title=share_title,
            total_received=total_received,
            total_given=total_given,
            needs_password=False
        )

    # 启动企业微信智能机器人长连接后台监听守护线程与亲友纪念日自动提醒后台调度器
    try:
        start_wecom_long_connection_listener()
    except Exception as e:
        print(f"[Init Warning] start_wecom_long_connection_listener: {e}")

    try:
        start_anniversary_reminder_scheduler(app)
    except Exception as e:
        print(f"[Init Warning] start_anniversary_reminder_scheduler: {e}")




