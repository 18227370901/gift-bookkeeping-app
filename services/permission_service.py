# -*- coding: utf-8 -*-
"""
新用户全局默认权限模板 (CRUD 细粒度 74项) 与权限工具服务
参考 mengya 权限矩阵架构规范
"""

import json

# ==================== 74 项全局细粒度权限分组与定义 ====================
PERMISSION_GROUPS = [
    {
        "key": "menu_access",
        "name": "页面菜单访问权限",
        "badge": "bg-primary-subtle text-primary border border-primary-subtle",
        "permissions": [
            {"key": "menu_ledger", "name": "礼金账本", "desc": "访问主账本流水与明细总览", "default": True},
            {"key": "menu_banquets", "name": "专属宴席", "desc": "访问宴席专场、席位与专场礼金", "default": True},
            {"key": "menu_reconciliation", "name": "往来对账", "desc": "访问亲友往来账单与互赠对账", "default": True},
            {"key": "menu_reminders", "name": "亲友备忘", "desc": "访问亲友纪念日、生日与随礼备忘", "default": True},
            {"key": "menu_recycle_bin", "name": "安全回收站", "desc": "访问账本与宴席删除记录及恢复中心", "default": True},
            {"key": "menu_dashboard", "name": "数据分析", "desc": "访问多维趋势分析图表与汇总大盘", "default": True},
            {"key": "menu_family", "name": "家庭账本", "desc": "访问多成员家庭协作记账", "default": True},
            {"key": "menu_weather", "name": "万年历/天气", "desc": "访问桌面生活助手与黄历天气", "default": True},
            {"key": "menu_webhooks", "name": "告警通知", "desc": "访问消息通知与系统告警记录", "default": False},
            {"key": "menu_backups", "name": "数据备份", "desc": "访问 WebDAV 云端备份与快照中心", "default": False},
        ]
    },
    {
        "key": "crud_ledger",
        "name": "礼金账本 CRUD 细粒度",
        "badge": "bg-success-subtle text-success border border-success-subtle",
        "permissions": [
            {"key": "ledger_view", "name": "查：查看账本记录", "desc": "查看礼金明细、筛选与统计", "default": True},
            {"key": "ledger_create", "name": "增：快速记一笔", "desc": "新增收礼或送礼流水记录", "default": True},
            {"key": "ledger_edit", "name": "改：编辑账本数据", "desc": "修改金额、人名、事由及备注", "default": True},
            {"key": "ledger_delete", "name": "删：移入回收站", "desc": "软删除礼金账本记录", "default": True},
            {"key": "ledger_import", "name": "导：导入账本数据", "desc": "批量导入 Excel/CSV 礼金明细", "default": True},
            {"key": "ledger_export", "name": "导：导出账本报表", "desc": "导出 Excel/CSV 财务流水台账", "default": True},
            {"key": "ledger_batch_delete", "name": "批：批量移入回收站", "desc": "勾选批量删除多笔礼金流水", "default": True},
            {"key": "ledger_batch_edit", "name": "批：批量修改事由标签", "desc": "批量维护礼金记录的分类与属性", "default": True},
        ]
    },
    {
        "key": "crud_banquets",
        "name": "专属宴席 CRUD 细粒度",
        "badge": "bg-warning-subtle text-warning-emphasis border border-warning-subtle",
        "permissions": [
            {"key": "banquet_view", "name": "查：查看宴席专场", "desc": "浏览宴席列表与详情汇总", "default": True},
            {"key": "banquet_create", "name": "增：新建专场宴席", "desc": "创建婚宴、满月、乔迁等专属场次", "default": True},
            {"key": "banquet_edit", "name": "改：编辑宴席信息", "desc": "修改场次时间、桌数、预算及宴席属性", "default": True},
            {"key": "banquet_delete", "name": "删：移入回收站", "desc": "删除宴席专场及级联归档", "default": True},
            {"key": "banquet_record_add", "name": "增：快速入账", "desc": "在宴席专场内录入到场礼金", "default": True},
            {"key": "banquet_export", "name": "导：导出专场礼单", "desc": "导出当前宴席的完整人员礼金表", "default": True},
        ]
    },
    {
        "key": "crud_reconciliation",
        "name": "往来对账中心 CRUD",
        "badge": "bg-info-subtle text-info-emphasis border border-info-subtle",
        "permissions": [
            {"key": "reconciliation_view", "name": "查：查看对账单", "desc": "查看各亲友之间的礼金差额与往来汇总", "default": True},
            {"key": "reconciliation_create", "name": "增：发起对账比对", "desc": "创建自定义双向或多向账单冲抵结算", "default": True},
            {"key": "reconciliation_edit", "name": "改：调整平账金额", "desc": "调整抵扣项或对账明细说明", "default": True},
            {"key": "reconciliation_delete", "name": "删：废弃对账单", "desc": "删除未结清或历史对账单", "default": True},
            {"key": "reconciliation_export", "name": "导：导出对账单", "desc": "导出亲友往来清算明细表", "default": True},
        ]
    },
    {
        "key": "crud_reminders",
        "name": "亲友备忘与纪念日 CRUD",
        "badge": "bg-danger-subtle text-danger border border-danger-subtle",
        "permissions": [
            {"key": "reminder_view", "name": "查：查看亲友备忘", "desc": "查看纪念日、生日与礼尚往来日程", "default": True},
            {"key": "reminder_create", "name": "增：添加纪念提醒", "desc": "登记亲友重要纪念日及提醒天数", "default": True},
            {"key": "reminder_edit", "name": "改：编辑备忘信息", "desc": "修改纪念日时间、关系人与提醒方式", "default": True},
            {"key": "reminder_delete", "name": "删：删除备忘事项", "desc": "移除已过时或不需要的备忘事项", "default": True},
            {"key": "reminder_trigger", "name": "测：立即测试触发提醒", "desc": "手动触发发送备忘提醒通知", "default": False},
        ]
    },
    {
        "key": "crud_recycle_bin",
        "name": "安全回收站管理 CRUD",
        "badge": "bg-secondary-subtle text-secondary border border-secondary-subtle",
        "permissions": [
            {"key": "recycle_bin_view", "name": "查：查看回收站列表", "desc": "查看已删除的账目与宴席条目", "default": True},
            {"key": "recycle_bin_restore", "name": "复：恢复单条记录", "desc": "从回收站还原礼金或宴席至主账本", "default": True},
            {"key": "recycle_bin_purge", "name": "清：彻底粉碎删除", "desc": "物理永久抹除所选记录（不可恢复）", "default": False},
            {"key": "recycle_bin_batch_restore", "name": "批：批量还原选中", "desc": "勾选多条软删除数据一键恢复", "default": True},
        ]
    },
    {
        "key": "crud_dashboard",
        "name": "数据分析与报表中心",
        "badge": "bg-primary-subtle text-primary border border-primary-subtle",
        "permissions": [
            {"key": "dashboard_view", "name": "查：查看分析看板", "desc": "浏览月度/年度走势与收支全景", "default": True},
            {"key": "dashboard_filter", "name": "滤：自由时间范围查询", "desc": "按起始/截止月份与年份精确切片", "default": True},
            {"key": "dashboard_drilldown", "name": "钻：深入事由二级钻取", "desc": "点击指定事由钻取穿透参与亲友与明细", "default": True},
            {"key": "dashboard_switch_view", "name": "切：环形图/条形图切换", "desc": "自由切换不同维度的可视化展示形态", "default": True},
            {"key": "dashboard_export", "name": "导：导出分析看板数据", "desc": "导出分析图表数据报表", "default": True},
        ]
    },
    {
        "key": "crud_family",
        "name": "家庭多成员协作管理",
        "badge": "bg-success-subtle text-success border border-success-subtle",
        "permissions": [
            {"key": "family_view", "name": "查：查看家庭账本", "desc": "查看家庭成员共同记录的账本数据", "default": True},
            {"key": "family_create_group", "name": "增：创建家庭协作组", "desc": "新建多用户共享的人情家庭群组", "default": True},
            {"key": "family_invite_member", "name": "邀：邀请成员加入", "desc": "生成家庭邀请码或关联其他账号", "default": True},
            {"key": "family_edit_member", "name": "改：管理成员身份", "desc": "变更群组内家庭成员的角色与权限", "default": False},
            {"key": "family_remove_member", "name": "删：移除家庭成员", "desc": "将成员移出协作组并解绑", "default": False},
        ]
    },
    {
        "key": "system_tools",
        "name": "生活工具与智能助手",
        "badge": "bg-info-subtle text-info-emphasis border border-info-subtle",
        "permissions": [
            {"key": "weather_view", "name": "查：查看天气与万年历", "desc": "查看每日天气、宜忌、吉日与黄历", "default": True},
            {"key": "weather_city_search", "name": "搜：自由切换定位城市", "desc": "搜索国内城市查看天气走势", "default": True},
            {"key": "ai_chat", "name": "用：AI 礼金智能问答", "desc": "调用 AI 顾问解答人情往来礼节礼仪", "default": False},
            {"key": "ai_analyze_record", "name": "用：AI 账本智能分析", "desc": "一键生成近期收支健康评语与分析", "default": False},
            {"key": "ai_session_manage", "name": "管：管理 AI 对话会话", "desc": "创建、重命名与清空历史会话记录", "default": False},
            {"key": "ai_config_custom", "name": "配：配置个人自定义模型", "desc": "允许用户填入自身专属 API-Key", "default": False},
        ]
    },
    {
        "key": "cross_user_perms",
        "name": "跨用户数据安全操作等级",
        "badge": "bg-warning-subtle text-warning-emphasis border border-warning-subtle",
        "permissions": [
            {"key": "cross_ledger_view", "name": "账本：查阅其他用户流水", "desc": "授权跨账号查阅其他普通用户所记账本", "default": False},
            {"key": "cross_ledger_edit", "name": "账本：修改其他用户流水", "desc": "允许修改或更正他人登记的礼金记录", "default": False},
            {"key": "cross_ledger_delete", "name": "账本：删除其他用户流水", "desc": "允许移入回收站或清理他人礼金记录", "default": False},
            {"key": "cross_banquet_view", "name": "宴席：查阅其他用户宴席", "desc": "授权跨账号查看他人主办的专场宴席", "default": False},
            {"key": "cross_banquet_edit", "name": "宴席：编辑他人专场宴席", "desc": "允许更新他人宴席详情与专场账目", "default": False},
            {"key": "cross_banquet_delete", "name": "宴席：删除他人专场宴席", "desc": "允许删除他人主办的专场宴席", "default": False},
            {"key": "cross_backup_view", "name": "备份：查看他人 WebDAV 快照", "desc": "授权跨账号查阅他人备份档案列表", "default": False},
            {"key": "cross_backup_manage", "name": "备份：操作/恢复他人快照", "desc": "允许下载、恢复或删除他人上传的备份", "default": False},
        ]
    },
    {
        "key": "admin_maintenance",
        "name": "高级运维与扩展授权",
        "badge": "bg-danger-subtle text-danger border border-danger-subtle",
        "permissions": [
            {"key": "auth_backup_manage", "name": "权：开启云端备份授权", "desc": "允许该用户使用 WebDAV 自动备份功能", "default": False},
            {"key": "auth_webhook_manage", "name": "权：开启告警通知授权", "desc": "允许该用户接收 Webhook 推送与配置告警", "default": False},
            {"key": "auth_task_manage", "name": "权：开启定时任务授权", "desc": "允许该用户创建与执行定时自动备份计划", "default": False},
            {"key": "auth_ai_manage", "name": "权：开启 AI 助手功能授权", "desc": "允许该用户调用系统预置的 AI 助手服务", "default": False},
            {"key": "menu_admin_users", "name": "管：后台用户管理菜单", "desc": "进入管理后台系统用户列表与权限管控", "default": False},
            {"key": "admin_user_view", "name": "管：查看系统用户列表", "desc": "查看所有已注册用户基本信息与风险状态", "default": False},
            {"key": "admin_user_edit", "name": "管：配置用户权限与状态", "desc": "编辑普通用户的独立权限与启停状态", "default": False},
            {"key": "admin_user_reset_pass", "name": "管：强制重置用户密码", "desc": "管理员代为重置指定账号登录凭证", "default": False},
            {"key": "admin_user_reset_sec", "name": "管：清空重置密保风控", "desc": "清除账号登录锁定与密保防爆限制", "default": False},
            {"key": "admin_reg_mode_manage", "name": "管：切换开放注册模式", "desc": "控制全站自由注册或严格邀请码机制", "default": False},
            {"key": "admin_invite_token_manage", "name": "管：生成与管理邀请链接", "desc": "签发、作废与批量删除注册邀请码", "default": False},
            {"key": "admin_permission_template", "name": "管：维护全局默认权限模板", "desc": "定制全站新用户全局默认权限规范", "default": False},
        ]
    }
]

# 扁平化映射表与默认权限字典（74 项）
ALL_PERMISSION_DEFINITIONS = {}
DEFAULT_USER_PERMISSIONS = {}

for _grp in PERMISSION_GROUPS:
    for _perm in _grp["permissions"]:
        ALL_PERMISSION_DEFINITIONS[_perm["key"]] = {
            "key": _perm["key"],
            "name": _perm["name"],
            "desc": _perm["desc"],
            "group_key": _grp["key"],
            "group_name": _grp["name"],
            "default": _perm["default"]
        }
        DEFAULT_USER_PERMISSIONS[_perm["key"]] = _perm["default"]


def get_system_default_permissions():
    """
    获取系统当前生效的「全局默认权限模板」。
    优先读取 SystemSetting 中存储的 JSON 配置；若无则降级返回内置标准 74 项默认字典。
    """
    from services.models import SystemSetting
    setting_raw = SystemSetting.get_val("default_user_permissions", "")
    perms = dict(DEFAULT_USER_PERMISSIONS)
    if setting_raw:
        try:
            custom_template = json.loads(setting_raw)
            if isinstance(custom_template, dict):
                for k, v in custom_template.items():
                    if k in perms:
                        perms[k] = bool(v)
        except Exception:
            pass
    return perms


def save_system_default_permissions(perms_dict):
    """
    持久化管理员配置的「全局默认权限模板」。
    只更新系统模板供新用户或手动重置时使用，绝对不自动覆盖已有存量用户。
    """
    from services.models import SystemSetting
    clean = {}
    for k in DEFAULT_USER_PERMISSIONS:
        clean[k] = bool(perms_dict.get(k, False))
    SystemSetting.set_val("default_user_permissions", json.dumps(clean, ensure_ascii=False))
    return clean


def apply_default_permissions_to_user(user, force_save=True):
    """
    将当前系统的「全局默认权限模板」一键覆盖应用至指定用户对象。
    实现向后兼容：同步映射 allowed_menus, menu_permissions, ai/backup/webhook/task 授权。
    """
    template = get_system_default_permissions()
    
    # 1. 计算 allowed_menus
    menus = []
    menu_keys = ['ledger', 'banquets', 'reconciliation', 'reminders', 'recycle_bin', 'dashboard', 'family', 'weather', 'webhooks', 'backups']
    for m in menu_keys:
        if template.get(f'menu_{m}', False):
            menus.append(m)
    user.allowed_menus = ",".join(menus)
    
    # 2. 计算跨用户权限级别字典
    menu_perms = {}
    for m in menu_keys:
        can_v = template.get(f'cross_{m}_view', False)
        can_e = template.get(f'cross_{m}_edit', False)
        can_d = template.get(f'cross_{m}_delete', False)
        if can_d:
            lvl = 3
        elif can_e:
            lvl = 2
        elif can_v:
            lvl = 1
        else:
            lvl = 0
        menu_perms[m] = lvl
    
    # 专门处理备份跨用户等级
    if template.get('cross_backup_manage', False):
        menu_perms['backups'] = 2
    elif template.get('cross_backup_view', False):
        menu_perms['backups'] = 1
    else:
        menu_perms['backups'] = 0

    user.set_menu_permissions(menu_perms)
    
    # 同步传统三字段
    ledger_lvl = menu_perms.get('ledger', 0)
    user.can_view_others = (ledger_lvl >= 1)
    user.can_edit_others = (ledger_lvl >= 2)
    user.can_delete_others = (ledger_lvl >= 3)
    
    # 3. 授权开关同步
    user.backup_authorized = bool(template.get('auth_backup_manage', False))
    user.webhook_authorized = bool(template.get('auth_webhook_manage', False) or ('webhooks' in menus))
    user.scheduled_task_authorized = bool(template.get('auth_task_manage', False))
    user.ai_authorized = bool(template.get('auth_ai_manage', False))

    if force_save:
        from services.models import db
        db.session.commit()
    return user


def save_system_group_permissions(group_key, group_perms_dict):
    """
    独立持久化指定分组的默认权限配置。
    读取现有模板，仅更新属于该分组的子项，保存并返回更新后的配置。
    """
    from services.models import SystemSetting
    current = get_system_default_permissions()
    target_group = next((g for g in PERMISSION_GROUPS if g["key"] == group_key), None)
    if not target_group:
        return current

    group_keys = {p["key"] for p in target_group["permissions"]}
    for k in group_keys:
        if k in group_perms_dict:
            current[k] = bool(group_perms_dict[k])
        else:
            current[k] = False

    SystemSetting.set_val("default_user_permissions", json.dumps(current, ensure_ascii=False))
    return current
