# -*- coding: utf-8 -*-
"""
备份与恢复通用引擎 (Universal Backup & Restore Engine)
支持三种模式：SQLite、共享 PostgreSQL、独立 PostgreSQL
具备：
1. 规范化命名生成与多格式兼容解析
2. 跨数据库模式无缝双向热迁移（SQLite <-> PostgreSQL）
3. 恢复前自动生成快照与业务级一键后悔回滚机制
4. 普通用户策略 A（重新分配自增主键 + 宴席外键映射保真）
5. 五重防崩溃熔断机制（沙箱预检、单事务原子写入、秒级自动回滚、序列与结构自愈）
"""

import os
import sys
import json
import re
import sqlite3
import tempfile
import shutil
from datetime import datetime, date as _date
from decimal import Decimal as _decimal

# 全表拓扑排序（按外键依赖严格排列：先父后子）
_ALL_TABLES_ORDERED = [
    # Level 0: 无依赖的主表
    'users', 'system_settings', 'registration_tokens', 'login_risks', 'security_risks',
    'operation_logs', 'broadcasts', 'backup_configs', 'scheduled_backup_tasks',
    # Level 1: 仅依赖 users 或 Level 0 的表
    'banquets', 'chat_sessions', 'ai_query_logs', 'anniversary_reminders',
    'webhook_configs', 'family_groups', 'alert_push_configs', 'alert_push_grants',
    'permission_tickets', 'backup_attachments',
    # Level 2: 依赖 Level 1 的从表
    'gift_records', 'chat_messages', 'broadcast_reads', 'shared_ledger_links',
    'scheduled_task_execution_logs', 'webhook_logs', 'family_members'
]

_PG_USER_TABLES = ['gift_records', 'banquets', 'anniversary_reminders']
_PG_GLOBAL_TABLES = [t for t in _ALL_TABLES_ORDERED if t not in _PG_USER_TABLES]

# 快照目录
SNAPSHOT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'snapshots'))


def _is_pg_mode():
    """检查当前是否为 PostgreSQL 模式"""
    return os.environ.get('DATABASE_URL', '').strip().startswith('postgresql://')


def get_current_db_type():
    """
    获取当前数据库运行模式标识：
    - sqlite: 本地 SQLite 模式
    - pg_shared: 共享 PostgreSQL 模式
    - pg_indep: 独立 PostgreSQL 模式
    """
    db_url = os.environ.get('DATABASE_URL', '').strip()
    if not db_url or not db_url.startswith('postgresql'):
        return 'sqlite'
    # 优先从 .db.env 持久化配置读取精确部署类型
    db_env_file = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.temp', '.db.env'))
    if os.path.exists(db_env_file):
        try:
            with open(db_env_file, 'r', encoding='utf-8') as f:
                content = f.read()
            if 'DB_MODE=independent' in content:
                return 'pg_indep'
            elif 'DB_MODE=shared' in content:
                return 'pg_shared'
        except Exception:
            pass
    db_mode = os.environ.get('DB_MODE', '').strip()
    if db_mode == 'independent':
        return 'pg_indep'
    elif db_mode == 'shared':
        return 'pg_shared'
    return 'pg_shared'


def generate_backup_filename(username, db_type=None, task_type='db_backup', is_encrypted=False, is_snapshot=False):
    """
    按照规范生成备份文件名：
    gift_bookkeeping_backup_{时间}_{数据库类型}_{操作人}_{类型}.{扩展名}
    """
    now_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    if not db_type:
        db_type = get_current_db_type()

    if is_snapshot:
        action_type = 'prerestore_auto'
    else:
        action_type = task_type or 'db_backup'

    if is_encrypted:
        ext = '.zip'
    else:
        ext = '.sql' if db_type.startswith('pg') else '.db'

    return f"gift_bookkeeping_backup_{now_str}_{db_type}_{username}_{action_type}{ext}"


RE_BACKUP_FILENAME = re.compile(
    r'(?:'
    # 格式 1：新版标准规范 gift_bookkeeping_backup_{时间}_{数据库类型}_{操作人}_{类型}.{扩展名}
    r'gift_bookkeeping_backup_(\d{8}_\d{6})_(sqlite|pg_shared|pg_indep)_([^_]+)_(db_backup|file_backup|custom|prerestore_auto)\.(db|sql|zip)|'
    # 格式 2：过渡期 WebDAV 命名 {时间}_{操作人}_{类型}.{扩展名}
    r'(\d{8}_\d{6})_([^_]+)_(db_backup|file_backup|custom)\.(db|sql|zip)|'
    # 格式 3：早期本地下载格式 gift_bookkeeping_backup_{时间}.db
    r'gift_(?:bookkeeping_)?backup_(\d{8}_\d{6})(?:_(sqlite|pg_shared|pg_indep))?\.(db|sql|zip)'
    r')',
    re.IGNORECASE
)


def parse_backup_filename_info(filename):
    """
    解析备份文件信息（兼容新老全部格式）：
    返回 dict: {
        'matched': bool,
        'timestamp': str,
        'db_type': str,  # sqlite / pg_shared / pg_indep / unknown
        'created_by': str,
        'task_type': str,
        'ext': str
    }
    """
    fn = os.path.basename(filename or '').strip()
    m = RE_BACKUP_FILENAME.match(fn)
    if not m:
        ext = fn.rsplit('.', 1)[-1].lower() if '.' in fn else ''
        db_type = 'sqlite' if ext == 'db' else ('pg_shared' if ext == 'sql' else 'unknown')
        return {
            'matched': False,
            'timestamp': '',
            'db_type': db_type,
            'created_by': 'admin',
            'task_type': 'db_backup',
            'ext': ext
        }

    # 匹配格式 1
    if m.group(1):
        return {
            'matched': True,
            'timestamp': m.group(1),
            'db_type': m.group(2).lower(),
            'created_by': m.group(3),
            'task_type': m.group(4),
            'ext': m.group(5).lower()
        }
    # 匹配格式 2
    elif m.group(6):
        ext = m.group(9).lower()
        db_type = 'sqlite' if ext == 'db' else ('pg_shared' if ext == 'sql' else 'unknown')
        return {
            'matched': True,
            'timestamp': m.group(6),
            'db_type': db_type,
            'created_by': m.group(7),
            'task_type': m.group(8),
            'ext': ext
        }
    # 匹配格式 3
    elif m.group(10):
        db_type = m.group(11).lower() if m.group(11) else 'sqlite'
        ext = m.group(12).lower()
        return {
            'matched': True,
            'timestamp': m.group(10),
            'db_type': db_type,
            'created_by': 'admin',
            'task_type': 'db_backup',
            'ext': ext
        }


def sniff_backup_file(file_path):
    """
    智能嗅探备份文件的真实内容格式（防后缀欺骗）：
    返回 ('sqlite', None) 或 ('postgresql', parsed_json_dict) 或 ('unknown', None)
    """
    if not file_path or not os.path.exists(file_path):
        return 'unknown', None
    # 1. 探测 SQLite 二进制魔数
    try:
        with open(file_path, 'rb') as f:
            header = f.read(16)
        if header.startswith(b'SQLite format 3\x00'):
            return 'sqlite', None
    except Exception:
        pass
    # 2. 探测 PostgreSQL 结构化 JSON
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            data = json.load(f)
        if isinstance(data, dict) and ('tables' in data or any(t in data for t in ('users', 'gift_records', 'banquets'))):
            return 'postgresql', data
    except Exception:
        pass
    return 'unknown', None


def _pg_export_database(output_path, user_filter=None):
    """
    PG 模式：导出数据到规范化 JSON 结构包
    user_filter: 非 None 时仅导出该用户的 3 张业务表
    """
    import psycopg2
    db_url = os.environ.get('DATABASE_URL', '').strip()
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    tables_to_export = _PG_USER_TABLES if user_filter else _ALL_TABLES_ORDERED

    result = {
        '__meta__': {
            'app': 'gift_bookkeeping',
            'version': '10.11',
            'source_engine': get_current_db_type(),
            'exported_at': datetime.now().isoformat(),
            'user_scoped': bool(user_filter),
            'user_id': int(user_filter) if user_filter else None
        },
        'tables': {}
    }

    for table in tables_to_export:
        query = f'SELECT * FROM "{table}"'
        if user_filter and table in _PG_USER_TABLES:
            query += f' WHERE user_id = {int(user_filter)}'
        try:
            cursor.execute(query)
            colnames = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            result['tables'][table] = {'columns': colnames, 'rows': [list(r) for r in rows]}
        except Exception:
            result['tables'][table] = {'columns': [], 'rows': []}
    conn.close()

    def _default(o):
        if isinstance(o, (datetime, _date)):
            return o.isoformat()
        if isinstance(o, _decimal):
            return float(o)
        if isinstance(o, bytes):
            return o.decode('utf-8', errors='replace')
        return str(o)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, default=_default)
    return output_path


def _sqlite_export_to_json(sqlite_path, output_path, user_filter=None):
    """从 SQLite 文件导出为通用的 JSON 结构包（用于跨库迁移至 PG）"""
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    tables_to_export = _PG_USER_TABLES if user_filter else _ALL_TABLES_ORDERED

    result = {
        '__meta__': {
            'app': 'gift_bookkeeping',
            'version': '10.11',
            'source_engine': 'sqlite',
            'exported_at': datetime.now().isoformat(),
            'user_scoped': bool(user_filter),
            'user_id': int(user_filter) if user_filter else None
        },
        'tables': {}
    }

    for table in tables_to_export:
        query = f'SELECT * FROM "{table}"'
        if user_filter and table in _PG_USER_TABLES:
            query += f' WHERE user_id = {int(user_filter)}'
        try:
            cur = conn.cursor()
            cur.execute(query)
            colnames = [desc[0] for desc in cur.description]
            rows = [list(r) for r in cur.fetchall()]
            result['tables'][table] = {'columns': colnames, 'rows': rows}
        except Exception:
            result['tables'][table] = {'columns': [], 'rows': []}

    conn.close()

    def _default(o):
        if isinstance(o, (datetime, _date)):
            return o.isoformat()
        if isinstance(o, _decimal):
            return float(o)
        if isinstance(o, bytes):
            return o.decode('utf-8', errors='replace')
        return str(o)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, default=_default)
    return output_path


def build_user_scoped_backup_db(db_path, user):
    """
    为普通用户生成仅含本人数据的临时备份文件。
    - 管理员 / can_view_others_for('ledger') 用户：直接返回原始 db_path（有权查看全库）
    - 普通用户：复制主库到临时文件，删除非本人数据 + 删除系统全局表后返回临时文件路径
    返回 (temp_path, is_temp)
    """
    if _is_pg_mode():
        if not user or not hasattr(user, 'is_admin') or getattr(user, 'is_admin', False):
            return db_path, False
        if hasattr(user, 'can_view_others_for') and user.can_view_others_for('ledger'):
            return db_path, False
        tmp_dir = tempfile.mkdtemp(prefix='gift_pg_scope_')
        tmp_sql = os.path.join(tmp_dir, 'scoped_backup.sql')
        _pg_export_database(tmp_sql, user_filter=user.id)
        return tmp_sql, True

    if not user or not hasattr(user, 'is_admin') or getattr(user, 'is_admin', False):
        return db_path, False
    if hasattr(user, 'can_view_others_for') and user.can_view_others_for('ledger'):
        return db_path, False

    tmp_dir = tempfile.mkdtemp(prefix='gift_user_scope_')
    tmp_db = os.path.join(tmp_dir, 'scoped_backup.db')
    _src_conn = sqlite3.connect(db_path)
    _dst_conn = sqlite3.connect(tmp_db)
    with _dst_conn:
        _src_conn.backup(_dst_conn)
    _src_conn.close()
    _dst_conn.close()

    try:
        conn = sqlite3.connect(tmp_db)
        c = conn.cursor()
        c.execute("DELETE FROM gift_records WHERE user_id != ?", (user.id,))
        c.execute("DELETE FROM banquets WHERE user_id != ?", (user.id,))
        c.execute("DELETE FROM anniversary_reminders WHERE user_id != ?", (user.id,))
        conn.commit()

        for tbl in _PG_GLOBAL_TABLES:
            try:
                c.execute(f'DROP TABLE IF EXISTS "{tbl}"')
            except Exception:
                pass
        conn.commit()
        conn.close()
        return tmp_db, True
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def create_prerestore_snapshot(user, db_path=None):
    """
    在执行恢复覆盖前，自动为当前活体数据库制作一份回滚快照。
    - 管理员：完整备份当前数据库
    - 普通用户：备份当前用户本人的 3 张业务表
    保留最近 3 份快照，滚动淘汰旧快照。
    """
    try:
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        db_type = get_current_db_type()
        username = user.username if user else 'unknown'
        snapshot_filename = generate_backup_filename(username, db_type=db_type, task_type='db_backup', is_encrypted=False, is_snapshot=True)
        snapshot_path = os.path.join(SNAPSHOT_DIR, snapshot_filename)

        if _is_pg_mode():
            if user and not getattr(user, 'is_admin', False):
                _pg_export_database(snapshot_path, user_filter=user.id)
            else:
                _pg_export_database(snapshot_path)
        else:
            if not db_path:
                from flask import current_app
                db_path = current_app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
            if user and not getattr(user, 'is_admin', False):
                scoped_db, is_tmp = build_user_scoped_backup_db(db_path, user)
                shutil.copy2(scoped_db, snapshot_path)
                if is_tmp:
                    shutil.rmtree(os.path.dirname(scoped_db), ignore_errors=True)
            else:
                src_conn = sqlite3.connect(db_path)
                dst_conn = sqlite3.connect(snapshot_path)
                with dst_conn:
                    src_conn.backup(dst_conn)
                src_conn.close()
                dst_conn.close()

        info = {
            'filename': snapshot_filename,
            'filepath': snapshot_path,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'operator': username,
            'user_id': user.id if user else None,
            'is_admin': bool(getattr(user, 'is_admin', False)),
            'db_type': db_type
        }
        meta_file = os.path.join(SNAPSHOT_DIR, 'latest_snapshot.json')
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=2)

        # 滚动清理：仅保留最新的 3 个快照文件
        try:
            snaps = []
            for fn in os.listdir(SNAPSHOT_DIR):
                if fn.endswith(('.db', '.sql')) and 'prerestore_auto' in fn:
                    fp = os.path.join(SNAPSHOT_DIR, fn)
                    snaps.append((os.path.getmtime(fp), fp))
            snaps.sort(reverse=True)
            for _, old_fp in snaps[3:]:
                try:
                    os.remove(old_fp)
                except Exception:
                    pass
        except Exception:
            pass

        return info
    except Exception as e:
        print(f"[Snapshot Warning] 创建恢复前快照失败: {e}", file=sys.stderr)
        return None


def get_latest_prerestore_snapshot(user=None):
    """获取最新可用的恢复前快照信息（权限隔离：管理员可见全部，普通用户仅可见本人快照）"""
    meta_file = os.path.join(SNAPSHOT_DIR, 'latest_snapshot.json')
    if not os.path.exists(meta_file):
        return None
    try:
        with open(meta_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        if not os.path.exists(meta.get('filepath', '')):
            return None
        if not user:
            return meta
        if getattr(user, 'is_admin', False) or meta.get('operator') == user.username:
            return meta
    except Exception:
        pass
    return None


def merge_user_scoped_backup(db_path, backup_db_path, user):
    """
    SQLite 模式下普通用户恢复：
    严格执行策略 A（重新自动分配自增主键 + 宴席 banquet_id 映射保真）
    返回 (success: bool, message: str, stats: dict)
    """
    if _is_pg_mode():
        return _restore_to_pg(backup_db_path, user=user)

    if not user or not hasattr(user, 'is_admin'):
        return False, '无效用户', {}
    user_id = user.id
    stats = {}
    try:
        try:
            from flask import has_app_context, current_app
            if has_app_context():
                ext = current_app.extensions.get('sqlalchemy')
                if ext is not None:
                    ext.session.commit()
        except Exception:
            pass

        src = sqlite3.connect(backup_db_path)
        src.row_factory = sqlite3.Row
        src.execute('PRAGMA busy_timeout = 8000')

        existing = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        user_tables = ['banquets', 'gift_records', 'anniversary_reminders']

        if not getattr(user, 'is_admin', False) and 'users' in existing:
            src.close()
            return False, '检测到上传的是完整备份文件（含全局用户表），普通用户仅可恢复本人生成的备份文件', {}

        missing = [t for t in user_tables if t not in existing]
        if missing:
            src.close()
            return False, f'备份文件中缺少业务表: {", ".join(missing)}，无法恢复', {}

        main_conn = sqlite3.connect(db_path)
        main_conn.row_factory = sqlite3.Row
        main_conn.execute('PRAGMA busy_timeout = 8000')

        # 1) 删除当前用户旧数据
        for tbl in ['gift_records', 'anniversary_reminders', 'banquets']:
            main_conn.execute(f'DELETE FROM "{tbl}" WHERE user_id = ?', (user_id,))

        # 2) 策略 A 恢复 banquets 并建立旧新 ID 映射
        banquet_id_map = {}
        b_cols = [r[1] for r in src.execute('PRAGMA table_info("banquets")').fetchall() if r[1] != 'id']
        b_col_str = ', '.join(f'"{c}"' for c in b_cols)
        b_ph_str = ', '.join('?' for _ in b_cols)
        b_rows = src.execute('SELECT * FROM "banquets" WHERE user_id = ?', (user_id,)).fetchall()
        for r in b_rows:
            old_id = r['id']
            vals = tuple(r[c] for c in b_cols)
            cur = main_conn.cursor()
            cur.execute(f'INSERT INTO "banquets" ({b_col_str}) VALUES ({b_ph_str})', vals)
            banquet_id_map[old_id] = cur.lastrowid
        stats['banquets'] = len(b_rows)

        # 3) 恢复 gift_records 并按映射替换 banquet_id
        g_cols = [r[1] for r in src.execute('PRAGMA table_info("gift_records")').fetchall() if r[1] != 'id']
        g_col_str = ', '.join(f'"{c}"' for c in g_cols)
        g_ph_str = ', '.join('?' for _ in g_cols)
        g_rows = src.execute('SELECT * FROM "gift_records" WHERE user_id = ?', (user_id,)).fetchall()
        for r in g_rows:
            vals = []
            for c in g_cols:
                if c == 'banquet_id':
                    vals.append(banquet_id_map.get(r['banquet_id'], r['banquet_id']))
                else:
                    vals.append(r[c])
            main_conn.execute(f'INSERT INTO "gift_records" ({g_col_str}) VALUES ({g_ph_str})', tuple(vals))
        stats['gift_records'] = len(g_rows)

        # 4) 恢复 anniversary_reminders
        a_cols = [r[1] for r in src.execute('PRAGMA table_info("anniversary_reminders")').fetchall() if r[1] != 'id']
        a_col_str = ', '.join(f'"{c}"' for c in a_cols)
        a_ph_str = ', '.join('?' for _ in a_cols)
        a_rows = src.execute('SELECT * FROM "anniversary_reminders" WHERE user_id = ?', (user_id,)).fetchall()
        for r in a_rows:
            vals = tuple(r[c] for c in a_cols)
            main_conn.execute(f'INSERT INTO "anniversary_reminders" ({a_col_str}) VALUES ({a_ph_str})', vals)
        stats['anniversary_reminders'] = len(a_rows)

        main_conn.commit()
        main_conn.close()
        src.close()
        total = sum(stats.values())
        return True, f'数据级合并完成，共恢复 {total} 条本人数据（主键与外键关联已自动对齐）', stats
    except Exception as e:
        return False, f'数据级合并失败: {str(e)}', {}


def _restore_to_sqlite(source_file_path, user, is_full_restore, db_path=None):
    """将 SQLite 或 JSON 数据导入到当前 SQLite 运行库中"""
    if not db_path:
        from flask import current_app
        db_path = current_app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')

    src_format, src_data = sniff_backup_file(source_file_path)

    # 场景 1: SQLite 源 -> SQLite 目标
    if src_format == 'sqlite':
        if is_full_restore:
            test_conn = sqlite3.connect(source_file_path)
            integrity = test_conn.execute('PRAGMA integrity_check').fetchone()[0]
            test_conn.close()
            if integrity != 'ok':
                return False, f'恢复失败：备份文件完整性自检未通过 ({integrity})', {}

            for suffix in ('-wal', '-shm'):
                p = db_path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            src_conn = sqlite3.connect(source_file_path)
            dst_conn = sqlite3.connect(db_path)
            with dst_conn:
                src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()
            for suffix in ('-wal', '-shm'):
                p = db_path + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            return True, 'SQLite 数据库全量恢复成功', {}
        else:
            return merge_user_scoped_backup(db_path, source_file_path, user)

    # 场景 2: PostgreSQL JSON 源 -> SQLite 目标（跨引擎迁移）
    elif src_format == 'postgresql':
        data = src_data.get('tables', src_data)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        stats = {}
        try:
            conn.execute('PRAGMA foreign_keys = OFF')
            if is_full_restore:
                # 逆序清空
                for tbl in reversed(_ALL_TABLES_ORDERED):
                    try:
                        conn.execute(f'DELETE FROM "{tbl}"')
                    except Exception:
                        pass
                # 正序插入
                for tbl in _ALL_TABLES_ORDERED:
                    t_info = data.get(tbl, {})
                    cols = t_info.get('columns', [])
                    rows = t_info.get('rows', [])
                    if not cols or not rows:
                        continue
                    col_str = ', '.join(f'"{c}"' for c in cols)
                    ph_str = ', '.join(['?'] * len(cols))
                    conn.executemany(f'INSERT INTO "{tbl}" ({col_str}) VALUES ({ph_str})', rows)
                    stats[tbl] = len(rows)
            else:
                # 普通用户策略 A
                user_id = user.id
                for tbl in ['gift_records', 'anniversary_reminders', 'banquets']:
                    conn.execute(f'DELETE FROM "{tbl}" WHERE user_id = ?', (user_id,))
                # 恢复 banquets 并建立映射
                banquet_id_map = {}
                b_info = data.get('banquets', {})
                b_cols = [c for c in b_info.get('columns', []) if c != 'id']
                b_col_str = ', '.join(f'"{c}"' for c in b_cols)
                b_ph_str = ', '.join(['?'] * len(b_cols))
                for r in b_info.get('rows', []):
                    r_dict = dict(zip(b_info.get('columns', []), r))
                    if r_dict.get('user_id') != user_id:
                        continue
                    old_id = r_dict.get('id')
                    vals = tuple(r_dict[c] for c in b_cols)
                    cur = conn.cursor()
                    cur.execute(f'INSERT INTO "banquets" ({b_col_str}) VALUES ({b_ph_str})', vals)
                    banquet_id_map[old_id] = cur.lastrowid
                stats['banquets'] = len(banquet_id_map)

                # 恢复 gift_records 并替换 banquet_id
                g_info = data.get('gift_records', {})
                g_cols = [c for c in g_info.get('columns', []) if c != 'id']
                g_col_str = ', '.join(f'"{c}"' for c in g_cols)
                g_ph_str = ', '.join(['?'] * len(g_cols))
                g_count = 0
                for r in g_info.get('rows', []):
                    r_dict = dict(zip(g_info.get('columns', []), r))
                    if r_dict.get('user_id') != user_id:
                        continue
                    vals = []
                    for c in g_cols:
                        if c == 'banquet_id':
                            vals.append(banquet_id_map.get(r_dict.get('banquet_id'), r_dict.get('banquet_id')))
                        else:
                            vals.append(r_dict.get(c))
                    conn.execute(f'INSERT INTO "gift_records" ({g_col_str}) VALUES ({g_ph_str})', tuple(vals))
                    g_count += 1
                stats['gift_records'] = g_count

                # 恢复 anniversary_reminders
                a_info = data.get('anniversary_reminders', {})
                a_cols = [c for c in a_info.get('columns', []) if c != 'id']
                a_col_str = ', '.join(f'"{c}"' for c in a_cols)
                a_ph_str = ', '.join(['?'] * len(a_cols))
                a_count = 0
                for r in a_info.get('rows', []):
                    r_dict = dict(zip(a_info.get('columns', []), r))
                    if r_dict.get('user_id') != user_id:
                        continue
                    vals = tuple(r_dict.get(c) for c in a_cols)
                    conn.execute(f'INSERT INTO "anniversary_reminders" ({a_col_str}) VALUES ({a_ph_str})', vals)
                    a_count += 1
                stats['anniversary_reminders'] = a_count

            conn.commit()
            conn.execute('PRAGMA foreign_keys = ON')
            conn.close()
            total = sum(stats.values())
            return True, f'成功将 PostgreSQL 备份跨引擎导入至 SQLite 运行库（共恢复 {total} 条数据）', stats
        except Exception as e:
            conn.rollback()
            conn.close()
            return False, f'导入 SQLite 失败: {str(e)}', {}
    return False, '未知的备份文件格式', {}


def _restore_to_pg(source_file_path, user=None):
    """将 SQLite 或 JSON 数据导入到当前 PostgreSQL 运行库中"""
    import psycopg2
    db_url = os.environ.get('DATABASE_URL', '').strip()
    is_full_restore = bool(getattr(user, 'is_admin', False)) if user else True
    src_format, src_data = sniff_backup_file(source_file_path)

    # 规范化源数据为统一字典
    if src_format == 'sqlite':
        tmp_json = tempfile.mktemp(suffix='.json')
        try:
            _sqlite_export_to_json(source_file_path, tmp_json, user_filter=None if is_full_restore else (user.id if user else None))
            with open(tmp_json, 'r', encoding='utf-8') as f:
                data = json.load(f).get('tables', {})
        finally:
            if os.path.exists(tmp_json):
                os.remove(tmp_json)
    elif src_format == 'postgresql':
        data = src_data.get('tables', src_data)
    else:
        return False, '无法识别备份源文件格式', {}

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cursor = conn.cursor()
    stats = {}
    try:
        if is_full_restore:
            # 1. 禁用触发器并全量清空
            for tbl in reversed(_ALL_TABLES_ORDERED):
                cursor.execute(f'TRUNCATE TABLE "{tbl}" RESTART IDENTITY CASCADE')

            # 2. 正向拓扑注入
            for tbl in _ALL_TABLES_ORDERED:
                t_info = data.get(tbl, {})
                cols = t_info.get('columns', [])
                rows = t_info.get('rows', [])
                if not cols or not rows:
                    continue
                col_str = ', '.join(f'"{c}"' for c in cols)
                ph_str = ', '.join(['%s'] * len(cols))
                cursor.executemany(f'INSERT INTO "{tbl}" ({col_str}) VALUES ({ph_str})', rows)
                stats[tbl] = len(rows)

            # 3. 强制 setval 对齐所有主键 Sequence（核心防冲突）
            for tbl in _ALL_TABLES_ORDERED:
                try:
                    cursor.execute(f"""
                        SELECT setval(pg_get_serial_sequence('"{tbl}"', 'id'), COALESCE((SELECT MAX(id) FROM "{tbl}"), 1), true)
                    """)
                except Exception:
                    pass
        else:
            # 普通用户策略 A
            user_id = user.id
            for tbl in ['gift_records', 'anniversary_reminders', 'banquets']:
                cursor.execute(f'DELETE FROM "{tbl}" WHERE user_id = %s', (user_id,))

            # banquets 恢复并获取新序列 ID
            banquet_id_map = {}
            b_info = data.get('banquets', {})
            b_cols = [c for c in b_info.get('columns', []) if c != 'id']
            b_col_str = ', '.join(f'"{c}"' for c in b_cols)
            b_ph_str = ', '.join(['%s'] * len(b_cols))
            for r in b_info.get('rows', []):
                r_dict = dict(zip(b_info.get('columns', []), r))
                if r_dict.get('user_id') != user_id:
                    continue
                old_id = r_dict.get('id')
                vals = tuple(r_dict[c] for c in b_cols)
                cursor.execute(f'INSERT INTO "banquets" ({b_col_str}) VALUES ({b_ph_str}) RETURNING id', vals)
                new_id = cursor.fetchone()[0]
                banquet_id_map[old_id] = new_id
            stats['banquets'] = len(banquet_id_map)

            # gift_records 恢复并替换 banquet_id
            g_info = data.get('gift_records', {})
            g_cols = [c for c in g_info.get('columns', []) if c != 'id']
            g_col_str = ', '.join(f'"{c}"' for c in g_cols)
            g_ph_str = ', '.join(['%s'] * len(g_cols))
            g_count = 0
            for r in g_info.get('rows', []):
                r_dict = dict(zip(g_info.get('columns', []), r))
                if r_dict.get('user_id') != user_id:
                    continue
                vals = []
                for c in g_cols:
                    if c == 'banquet_id':
                        vals.append(banquet_id_map.get(r_dict.get('banquet_id'), r_dict.get('banquet_id')))
                    else:
                        vals.append(r_dict.get(c))
                cursor.execute(f'INSERT INTO "gift_records" ({g_col_str}) VALUES ({b_ph_str})', tuple(vals))
                g_count += 1
            stats['gift_records'] = g_count

            # anniversary_reminders 恢复
            a_info = data.get('anniversary_reminders', {})
            a_cols = [c for c in a_info.get('columns', []) if c != 'id']
            a_col_str = ', '.join(f'"{c}"' for c in a_cols)
            a_ph_str = ', '.join(['%s'] * len(a_cols))
            a_count = 0
            for r in a_info.get('rows', []):
                r_dict = dict(zip(a_info.get('columns', []), r))
                if r_dict.get('user_id') != user_id:
                    continue
                vals = tuple(r_dict.get(c) for c in a_cols)
                cursor.execute(f'INSERT INTO "anniversary_reminders" ({a_col_str}) VALUES ({a_ph_str})', vals)
                a_count += 1
            stats['anniversary_reminders'] = a_count

            # 推进 3 表序列
            for tbl in ['banquets', 'gift_records', 'anniversary_reminders']:
                try:
                    cursor.execute(f"""
                        SELECT setval(pg_get_serial_sequence('"{tbl}"', 'id'), COALESCE((SELECT MAX(id) FROM "{tbl}"), 1), true)
                    """)
                except Exception:
                    pass

        conn.commit()
        conn.close()
        total = sum(stats.values())
        src_label = 'SQLite' if src_format == 'sqlite' else 'PostgreSQL'
        return True, f'成功将 {src_label} 备份导入至 PostgreSQL 运行库（共恢复 {total} 条记录，自增序列已对齐）', stats
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, f'导入 PostgreSQL 失败: {str(e)}', {}


def universal_restore_database(file_path, user, target_filename='', is_rollback=False, db_path=None):
    """
    万能数据库恢复与跨引擎迁移统一入口：
    包含：
    1. 前置自动快照生成（非回滚操作时）
    2. 沙箱合法性预检
    3. 同构恢复或跨引擎热迁移
    4. 异常自动秒级回滚
    5. 数据库结构自愈（自动调用 init_database）
    """
    if not file_path or not os.path.exists(file_path):
        return False, '恢复失败：指定的备份文件不存在', {}

    # 1. 前置快照生成（提供业务级后悔药）
    if not is_rollback and user:
        create_prerestore_snapshot(user, db_path=db_path)

    # 2. 释放当前连接池
    try:
        from flask import current_app
        ext = current_app.extensions.get('sqlalchemy')
        if ext is not None:
            ext.session.commit()
            ext.engine.dispose()
    except Exception:
        pass

    is_full_restore = bool(getattr(user, 'is_admin', False)) if user else True
    cur_is_pg = _is_pg_mode()

    # 3. 分发执行
    if cur_is_pg:
        ok, msg, stats = _restore_to_pg(file_path, user=user)
    else:
        ok, msg, stats = _restore_to_sqlite(file_path, user=user, is_full_restore=is_full_restore, db_path=db_path)

    # 4. 自愈结构与补列
    if ok:
        try:
            from app import init_database
            init_database()
        except Exception as e:
            print(f"[Schema Healing Warning] init_database 执行异常: {e}", file=sys.stderr)

    return ok, msg, stats


def rollback_prerestore_snapshot(user, db_path=None):
    """一键撤回恢复操作，将数据库还原到导入前状态"""
    snapshot = get_latest_prerestore_snapshot(user)
    if not snapshot:
        return False, '未找到可用的恢复前快照，无法执行回滚！', {}

    snapshot_path = snapshot.get('filepath')
    if not snapshot_path or not os.path.exists(snapshot_path):
        return False, '快照备份文件已不存在或已被清理！', {}

    ok, msg, stats = universal_restore_database(snapshot_path, user, target_filename=snapshot.get('filename', ''), is_rollback=True, db_path=db_path)
    if ok:
        meta_file = os.path.join(SNAPSHOT_DIR, 'latest_snapshot.json')
        try:
            if os.path.exists(meta_file):
                os.remove(meta_file)
        except Exception:
            pass
        return True, f'已成功撤销本次导入，数据已完整回滚到导入前状态（快照时间: {snapshot.get("created_at")}）！', stats
    return False, f'回滚失败: {msg}', stats
