import os
import sys
import shutil
import random
import string
import time
import webbrowser
from threading import Timer
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Determine bundle directory for PyInstaller / PyBuild
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
else:
    BUNDLE_DIR = os.path.abspath(os.path.dirname(__file__))

template_folder = os.path.join(BUNDLE_DIR, 'templates')
app = Flask(__name__, template_folder=template_folder)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'gift-bookkeeping-secret-key-2026-prod-secure'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Handle Database Location (If frozen, write to user-writable directory or local directory)
if getattr(sys, 'frozen', False):
    USER_DATA_DIR = os.path.join(os.path.expanduser('~'), '.gift_bookkeeping')
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    db_path = os.path.join(USER_DATA_DIR, 'gift_bookkeeping.db')
    bundled_db = os.path.join(BUNDLE_DIR, 'gift_bookkeeping.db')
    if not os.path.exists(db_path) and os.path.exists(bundled_db):
        shutil.copy2(bundled_db, db_path)
else:
    db_path = os.path.join(BUNDLE_DIR, 'gift_bookkeeping.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录后再访问系统。'
login_manager.login_message_category = 'warning'

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    security_question = db.Column(db.String(100), nullable=False)
    security_answer_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    records = db.relationship('GiftRecord', backref='owner', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_security_answer(self, answer):
        clean_answer = answer.strip().lower()
        self.security_answer_hash = generate_password_hash(clean_answer)

    def check_security_answer(self, answer):
        clean_answer = answer.strip().lower()
        return check_password_hash(self.security_answer_hash, clean_answer)

class OperationLog(db.Model):
    __tablename__ = 'operation_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    username = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    detail = db.Column(db.String(500), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship('User', backref=db.backref('operation_logs', lazy=True))


def log_action(action, detail="", user=None):
    try:
        if user:
            u_id = user.id
            u_name = user.username
        elif current_user and current_user.is_authenticated:
            u_id = current_user.id
            u_name = current_user.username
        else:
            u_id = None
            u_name = "未登录/系统"
        
        ip_addr = request.remote_addr if request else ""
        if request and request.headers.get('X-Forwarded-For'):
            ip_addr = request.headers.get('X-Forwarded-For').split(',')[0].strip()

        log_entry = OperationLog(
            user_id=u_id,
            username=u_name,
            action=action,
            detail=detail,
            ip_address=ip_addr
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[Log Error] 写入日志失败: {e}")

class GiftRecord(db.Model):
    __tablename__ = 'gift_records'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    age = db.Column(db.Integer, nullable=True)
    address = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    event_reason = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def cn2num(s):
    if not s:
        return 0.0
    s = str(s).strip()
    s = s.replace('元', '').replace('圆', '').replace('正', '').replace('整', '').strip()
    try:
        return float(s)
    except ValueError:
        pass
    
    num_map = {'零':0, '壹':1, '贰':2, '叁':3, '肆':4, '伍':5, '陆':6, '柒':7, '捌':8, '玖':9,
               '一':1, '二':2, '三':3, '四':4, '五':5, '六':6, '七':7, '八':8, '九':9, '两':2}
    unit_map = {'拾':10, '十':10, '佰':100, '百':100, '仟':1000, '千':1000, '万':10000, '亿':100000000}
    
    total = 0
    section = 0
    number = 0
    has_digit = False
    
    for char in s:
        if char in num_map:
            number = num_map[char]
            has_digit = True
        elif char in unit_map:
            unit = unit_map[char]
            has_digit = True
            if unit == 10000 or unit == 100000000:
                section = (section + (number if number != 0 or not section else 0)) * unit
                total += section
                section = 0
                number = 0
            else:
                if number == 0:
                    number = 1
                section += number * unit
                number = 0
    total += section + number
    return float(total) if has_digit else 0.0

def num2cn(num):
    if num is None:
        return '零元整'
    try:
        num_float = float(num)
    except (ValueError, TypeError):
        return '零元整'
    
    if num_float == 0:
        return '零元整'
        
    digits = ['零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖']
    units = ['', '拾', '佰', '仟']
    big_units = ['', '万', '亿']
    
    integer_part = int(round(num_float))
    str_val = str(integer_part)
    
    if len(str_val) > 12:
        return f'{num_float:.2f}元'
        
    groups = []
    while str_val:
        groups.insert(0, str_val[-4:])
        str_val = str_val[:-4]
        
    group_count = len(groups)
    result = ''
    
    for i, group in enumerate(groups):
        g_len = len(group)
        g_res = ''
        g_zero = False
        for j, char in enumerate(group):
            d = int(char)
            unit_idx = g_len - 1 - j
            if d != 0:
                if g_zero:
                    g_res += '零'
                    g_zero = False
                g_res += digits[d] + units[unit_idx]
            else:
                g_zero = True
        
        big_unit_idx = group_count - 1 - i
        if g_res:
            result += g_res + big_units[big_unit_idx]
        elif big_unit_idx > 0 and result and not result.endswith('零'):
            result += '零'

    return result + '元整'

@app.template_filter('num2cn')
def num2cn_filter(num):
    return num2cn(num)

def init_database():
    with app.app_context():
        db.create_all()
        admin = User.query.filter_by(is_admin=True).first()
        if not admin:
            initial_user = os.environ.get('ADMIN_USER', 'admin')
            initial_pass = os.environ.get('ADMIN_PASS', 'admin123')
            admin = User(
                username=initial_user,
                security_question='管理员安全密保问题',
                is_admin=True
            )
            admin.set_password(initial_pass)
            admin.set_security_answer('admin')
            db.session.add(admin)
            db.session.commit()
            print(f"[Init] 已创建初始管理员账号: {initial_user}")


@app.route('/')
@login_required
def index():
    query_str = request.args.get('search', '').strip() or request.args.get('q', '').strip()
    reason_filter = request.args.get('reason', '').strip()
    sort_by = request.args.get('sort', 'created_at_desc').strip()
    
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    if per_page not in [5, 10, 20, 50, 100]:
        per_page = 10

    if current_user.is_admin:
        query = GiftRecord.query
    else:
        query = GiftRecord.query.filter_by(user_id=current_user.id)

    if query_str:
        search_pattern = f"%{query_str}%"
        num_val = None
        try:
            num_val = float(query_str)
        except ValueError:
            parsed = cn2num(query_str)
            if parsed > 0:
                num_val = parsed
        except Exception:
            pass

        or_conditions = [
            GiftRecord.name.ilike(search_pattern),
            GiftRecord.address.ilike(search_pattern),
            GiftRecord.phone.ilike(search_pattern),
            GiftRecord.event_reason.ilike(search_pattern),
            GiftRecord.notes.ilike(search_pattern),
            db.cast(GiftRecord.amount, db.String).ilike(search_pattern),
            db.cast(GiftRecord.age, db.String).ilike(search_pattern)
        ]
        if num_val is not None:
            or_conditions.append(GiftRecord.amount == num_val)

        query = query.filter(db.or_(*or_conditions))

    if reason_filter:
        query = query.filter(GiftRecord.event_reason == reason_filter)

    if sort_by == 'amount_desc':
        query = query.order_by(GiftRecord.amount.desc())
    elif sort_by == 'amount_asc':
        query = query.order_by(GiftRecord.amount.asc())
    elif sort_by in ['created_at_asc', 'oldest']:
        query = query.order_by(GiftRecord.created_at.asc())
    else:
        query = query.order_by(GiftRecord.created_at.desc())

    # Get total statistics before pagination
    all_filtered_records = query.all()
    total_count = len(all_filtered_records)
    total_amount = sum(r.amount for r in all_filtered_records) if all_filtered_records else 0.0
    avg_amount = round(total_amount / total_count, 2) if total_count > 0 else 0.0
    max_amount = max((r.amount for r in all_filtered_records), default=0.0)

    # Apply pagination
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    records = pagination.items

    if current_user.is_admin:
        all_reasons_query = db.session.query(GiftRecord.event_reason).distinct().all()
    else:
        all_reasons_query = db.session.query(GiftRecord.event_reason).filter_by(user_id=current_user.id).distinct().all()
    reasons_list = [r[0] for r in all_reasons_query if r[0]]

    default_reasons = ['婚宴', '满月酒', '周岁宴', '寿宴', '升学宴', '乔迁宴', '白事人情', '其它']
    for dr in default_reasons:
        if dr not in reasons_list:
            reasons_list.append(dr)

    return render_template(
        'index.html',
        records=records,
        pagination=pagination,
        per_page=per_page,
        total_count=total_count,
        total_amount=total_amount,
        avg_amount=avg_amount,
        max_amount=max_amount,
        reasons_list=reasons_list,
        query_str=query_str,
        reason_filter=reason_filter,
        sort_by=sort_by,
        num2cn=num2cn
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        remember = True if request.form.get('remember') else False

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=remember)
            log_action('用户登录', f'用户成功登录系统', user=user)
            flash(f'欢迎回来，{user.username}！', 'success')
            return redirect(url_for('index'))
        else:
            log_action('登录失败', f'尝试登录用户名 [{username}] 失败（密码错误或账号不存在）')
            flash('用户名或密码错误，请重试。', 'danger')

    return render_template('login.html')

# Rate limiting storage (in-memory)
register_attempts = {}

def get_captcha():
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    op = random.choice(['+', '*'])
    if op == '+':
        ans = num1 + num2
        text = f"{num1} + {num2} = ?"
    else:
        ans = num1 * num2
        text = f"{num1} × {num2} = ?"
    session['captcha_ans'] = str(ans)
    return text

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    ip_addr = request.remote_addr or request.headers.get('X-Forwarded-For', '')

    if request.method == 'POST':
        # 1. IP / Rate limiting check (e.g. max 5 registrations per hour per IP)
        now = time.time()
        ip_records = register_attempts.get(ip_addr, [])
        # keep records from last 1 hour
        ip_records = [t for t in ip_records if now - t < 3600]
        register_attempts[ip_addr] = ip_records
        if len(ip_records) >= 5:
            log_action('注册被拦截', f'IP [{ip_addr}] 尝试频次超限（1小时内已尝试5次以上）')
            flash('您注册尝试过于频繁，请1小时后再试。', 'danger')
            return render_template('register.html', captcha_text=get_captcha())

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        security_question = request.form.get('security_question', '').strip()
        security_answer = request.form.get('security_answer', '').strip()
        user_captcha = request.form.get('captcha', '').strip()
        session_captcha = session.pop('captcha_ans', None)

        # Record this attempt timestamp
        register_attempts[ip_addr].append(now)

        # 2. Captcha Validation
        if not session_captcha or user_captcha != session_captcha:
            flash('验证码错误或已过期，请重新计算！', 'danger')
            return render_template('register.html', captcha_text=get_captcha())

        if not username or not password or not security_question or not security_answer:
            flash('所有必填字段均不能为空！', 'danger')
            return render_template('register.html', captcha_text=get_captcha())

        # 3. Username Format Validation (3-20 chars, letters, numbers, underscores)
        if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fa5]{3,20}$', username):
            flash('用户名格式不符合要求！长度须为 3-20 位，仅允许汉字、字母、数字及下划线。', 'danger')
            return render_template('register.html', captcha_text=get_captcha())

        # 4. Password Strength Validation (min 6 chars, containing both letters and numbers)
        if len(password) < 6 or not re.search(r'[a-zA-Z]', password) or not re.search(r'\d', password):
            flash('密码强度不足！密码长度至少为 6 位，且必须包含字母和数字的组合。', 'danger')
            return render_template('register.html', captcha_text=get_captcha())

        if password != confirm_password:
            flash('两次输入的密码不一致！', 'danger')
            return render_template('register.html', captcha_text=get_captcha())

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('该用户名已被注册，请尝试其他名称。', 'warning')
            return render_template('register.html', captcha_text=get_captcha())

        user = User(username=username, security_question=security_question)
        user.set_password(password)
        user.set_security_answer(security_answer)
        db.session.add(user)
        db.session.commit()

        log_action('用户注册', f'新用户 [{username}] 成功注册账号', user=user)
        flash('注册成功，请登录！', 'success')
        return redirect(url_for('login'))

    captcha_text = get_captcha()
    return render_template('register.html', captcha_text=captcha_text)

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        step = request.form.get('step')
        
        if step == 'find_user':
            username = request.form.get('username', '').strip()
            user = User.query.filter_by(username=username).first()
            if user:
                return render_template('forgot_password.html', user=user, step='answer_question')
            else:
                flash('找不到该用户名对应的账号！', 'danger')
                return render_template('forgot_password.html', step='find_user')

        elif step == 'reset_pass':
            username = request.form.get('username', '').strip()
            security_answer = request.form.get('security_answer', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()

            user = User.query.filter_by(username=username).first()
            if not user:
                flash('用户不存在！', 'danger')
                return redirect(url_for('forgot_password'))

            if not user.check_security_answer(security_answer):
                flash('密保问题答案验证错误！', 'danger')
                return render_template('forgot_password.html', user=user, step='answer_question')

            if new_password != confirm_password:
                flash('两次输入的强密码不一致！', 'danger')
                return render_template('forgot_password.html', user=user, step='answer_question')

            user.set_password(new_password)
            db.session.commit()

            log_action('重置密码', f'用户成功重置个人密码', user=user)
            flash('密码重置成功！请使用新密码重新登录。', 'success')
            return redirect(url_for('login'))

    return render_template('forgot_password.html', step='find_user')

@app.route('/logout')
@login_required
def logout():
    log_action('退出登录', f'用户退出系统登录')
    logout_user()
    flash('您已成功退出登录。', 'info')
    return redirect(url_for('login'))

@app.route('/record/add', methods=['POST'])
@login_required
def add_record():
    name = request.form.get('name', '').strip()
    age_str = request.form.get('age', '').strip()
    address = request.form.get('address', '').strip()
    phone = request.form.get('phone', '').strip()
    amount_str = request.form.get('amount', '').strip()
    event_reason = request.form.get('event_reason', '').strip()
    custom_reason = request.form.get('custom_reason', '').strip()
    notes = request.form.get('notes', '').strip()

    if event_reason == '其它' and custom_reason:
        event_reason = custom_reason

    if not name or not amount_str or not event_reason:
        flash('姓名、礼金数额及办席原因为必填字段！', 'danger')
        return redirect(url_for('index'))

    try:
        amount = cn2num(amount_str)
        if amount < 0:
            raise ValueError
    except Exception:
        flash('礼金数额必须是有效的数值或大写金额！', 'danger')
        return redirect(url_for('index'))

    age = int(age_str) if age_str and age_str.isdigit() else None

    record = GiftRecord(
        name=name,
        age=age,
        address=address,
        phone=phone,
        amount=amount,
        event_reason=event_reason,
        notes=notes,
        user_id=current_user.id
    )
    db.session.add(record)
    db.session.commit()

    log_action('新增记录', f'新增记录: [{name}]，金额: {amount}元，事由: {event_reason}')
    flash(f'成功保存 [{name}] 的礼金记录！', 'success')
    return redirect(url_for('index'))

@app.route('/record/edit/<int:record_id>', methods=['POST'])
@login_required
def edit_record(record_id):
    record = GiftRecord.query.get_or_404(record_id)

    if not current_user.is_admin and record.user_id != current_user.id:
        flash('您没有权限修改此记录！', 'danger')
        return redirect(url_for('index'))

    name = request.form.get('name', '').strip()
    age_str = request.form.get('age', '').strip()
    address = request.form.get('address', '').strip()
    phone = request.form.get('phone', '').strip()
    amount_str = request.form.get('amount', '').strip()
    event_reason = request.form.get('event_reason', '').strip()
    custom_reason = request.form.get('custom_reason', '').strip()
    notes = request.form.get('notes', '').strip()

    if event_reason == '其它' and custom_reason:
        event_reason = custom_reason

    if not name or not amount_str or not event_reason:
        flash('姓名、礼金数额及办席原因为必填字段！', 'danger')
        return redirect(url_for('index'))

    try:
        amount = cn2num(amount_str)
        if amount < 0:
            raise ValueError
    except Exception:
        flash('礼金数额必须是有效的数值或大写金额！', 'danger')
        return redirect(url_for('index'))

    record.name = name
    record.age = int(age_str) if age_str and age_str.isdigit() else None
    record.address = address
    record.phone = phone
    record.amount = amount
    record.event_reason = event_reason
    record.notes = notes

    db.session.commit()
    log_action('修改记录', f'修改记录 ID #{record_id}: 姓名 [{name}]，金额: {amount}元，事由: {event_reason}')
    flash(f'记录 [{name}] 修改成功！', 'success')
    return redirect(url_for('index'))

@app.route('/record/delete/<int:record_id>', methods=['POST'])
@login_required
def delete_record(record_id):
    record = db.session.get(GiftRecord, record_id)
    if not record:
        flash('未找到该记录或记录已被删除！', 'warning')
        return redirect(url_for('index'))

    if not current_user.is_admin and record.user_id != current_user.id:
        flash('您没有权限删除此记录！', 'danger')
        return redirect(url_for('index'))

    record_name = record.name
    db.session.delete(record)
    db.session.commit()
    log_action('删除记录', f'删除记录 ID #{record_id}: 姓名 [{record_name}]')
    flash('记录删除成功！', 'success')
    return redirect(url_for('index'))

@app.route('/records/batch_delete', methods=['POST'])
@login_required
def batch_delete_records():
    record_ids = request.form.getlist('record_ids')
    if not record_ids:
        flash('请选择要删除的记录！', 'warning')
        return redirect(url_for('index'))

    deleted_count = 0
    for rid in record_ids:
        try:
            record_id = int(rid)
        except ValueError:
            continue
        record = db.session.get(GiftRecord, record_id)
        if record:
            if current_user.is_admin or record.user_id == current_user.id:
                db.session.delete(record)
                deleted_count += 1

    db.session.commit()
    log_action('批量删除记录', f'成功批量删除了 {deleted_count} 条礼金记录')
    flash(f'成功批量删除 {deleted_count} 条记录！', 'success')
    return redirect(url_for('index'))

@app.route('/records/delete_all', methods=['POST'])
@login_required
def delete_all_records():
    if current_user.is_admin:
        deleted_count = db.session.query(GiftRecord).delete()
    else:
        deleted_count = db.session.query(GiftRecord).filter_by(user_id=current_user.id).delete()
    
    db.session.commit()
    log_action('清空记录', f'成功清空了 {deleted_count} 条礼金记录')
    flash(f'一次性成功清空 {deleted_count} 条所有礼金记录！', 'success')
    return redirect(url_for('index'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_password = request.form.get('old_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not current_user.check_password(old_password):
            flash('原密码输入错误！', 'danger')
            return redirect(url_for('change_password'))

        if new_password != confirm_password:
            flash('新密码两次输入不一致！', 'danger')
            return redirect(url_for('change_password'))

        current_user.set_password(new_password)
        db.session.commit()

        log_action('修改密码', f'用户成功修改个人密码')
        flash('密码修改成功，请使用新密码重新登录！', 'success')
        return redirect(url_for('login'))

    return render_template('change_password.html')

@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('权限不足！', 'danger')
        return redirect(url_for('index'))

    users = User.query.order_by(User.id.asc()).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/logs')
@login_required
def admin_logs():
    if not current_user.is_admin:
        flash('只有超级管理员才能查看审计日志！', 'danger')
        return redirect(url_for('index'))

    page = request.args.get('page', 1, type=int)
    logs = OperationLog.query.order_by(OperationLog.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('admin_logs.html', logs=logs)
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('只有超级管理员才能访问用户管理页面！', 'danger')
        return redirect(url_for('index'))

    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/user/reset_pass/<int:user_id>', methods=['POST'])
@login_required
def admin_reset_user_pass(user_id):
    if not current_user.is_admin:
        flash('权限不足！', 'danger')
        return redirect(url_for('index'))

    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()
    if new_password:
        user.set_password(new_password)
        db.session.commit()
        log_action('重置用户密码', f'管理员重置了用户 [{user.username}] 的密码')
        flash(f'用户 [{user.username}] 的密码已重置成功！', 'success')
    else:
        flash('新密码不能为空！', 'warning')

    return redirect(url_for('admin_users'))

@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        flash('权限不足！', 'danger')
        return redirect(url_for('index'))

    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('无法删除当前的管理员账号！', 'danger')
        return redirect(url_for('admin_users'))

    deleted_username = user.username
    db.session.delete(user)
    db.session.commit()
    log_action('删除用户', f'管理员删除了用户账号 [{deleted_username}]')
    flash(f'用户 [{deleted_username}] 及其关联数据已成功删除！', 'success')
    return redirect(url_for('admin_users'))
import csv
import io
from flask import Response

@app.route('/export/csv')
@login_required
def export_csv():
    if current_user.is_admin:
        records = GiftRecord.query.all()
    else:
        records = GiftRecord.query.filter_by(user_id=current_user.id).all()

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['ID', '客人姓名', '年龄', '联系电话', '礼金金额(元)', '办席原因', '联系地址', '备注说明', '登记时间', '录入用户'])

    for r in records:
        writer.writerow([
            r.id,
            r.name,
            r.age if r.age else '',
            r.phone if r.phone else '',
            f"{r.amount:.2f}",
            r.event_reason,
            r.address if r.address else '',
            r.notes if r.notes else '',
            r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else '',
            r.owner.username if r.owner else ''
        ])

    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=gift_records.csv'
    log_action('导出数据', f'用户导出了 {len(records)} 条礼金记录 CSV 文件')
    return response


@app.route('/import/csv', methods=['POST'])
@login_required
def import_csv():
    file = request.files.get('file')
    if not file or file.filename == '':
        flash('请选择要导入的 CSV 文件！', 'danger')
        return redirect(url_for('index'))

    if not file.filename.endswith('.csv'):
        flash('只支持导入 CSV 格式的文件！', 'danger')
        return redirect(url_for('index'))

    try:
        raw_bytes = file.stream.read()
        content = None
        for enc in ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'gb2312']:
            try:
                content = raw_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        
        if content is None:
            content = raw_bytes.decode('utf-8', errors='replace')

        csv_reader = csv.reader(io.StringIO(content))

        success_count = 0
        skip_count = 0
        header_map = {}

        for row in csv_reader:
            if not row or not any(row):
                skip_count += 1
                continue

            headers = [c.strip() for c in row]
            if any(h in headers for h in ['姓名', '客人姓名', '礼金金额', '礼金金额(元)', 'ID', '送礼人', '事由', '办席原因', '办事原因', '原因']):
                col_map = {}
                for idx, col in enumerate(headers):
                    col_clean = col.replace('(元)', '').strip()
                    if any(k in col_clean for k in ['姓名', '客人', '送礼人']):
                        col_map['name'] = idx
                    elif '年龄' in col_clean:
                        col_map['age'] = idx
                    elif any(k in col_clean for k in ['地址', '住址', '联系地址']):
                        col_map['address'] = idx
                    elif any(k in col_clean for k in ['电话', '手机', '联系电话']):
                        col_map['phone'] = idx
                    elif any(k in col_clean for k in ['金额', '礼金', '钱']):
                        col_map['amount'] = idx
                    elif any(k in col_clean for k in ['事由', '原因', '办席', '来意', '办事']):
                        col_map['event_reason'] = idx
                    elif any(k in col_clean for k in ['备注', '说明']):
                        col_map['notes'] = idx
                header_map = col_map
                continue

            if header_map:
                name = row[header_map['name']].strip() if 'name' in header_map and len(row) > header_map['name'] else ''
                age_str = row[header_map['age']].strip() if 'age' in header_map and len(row) > header_map['age'] else ''
                address = row[header_map['address']].strip() if 'address' in header_map and len(row) > header_map['address'] else ''
                phone = row[header_map['phone']].strip() if 'phone' in header_map and len(row) > header_map['phone'] else ''
                amount_str = row[header_map['amount']].strip() if 'amount' in header_map and len(row) > header_map['amount'] else '0'
                raw_reason = row[header_map['event_reason']].strip() if 'event_reason' in header_map and len(row) > header_map['event_reason'] else ''
                event_reason = raw_reason if raw_reason else '其它'
                notes = row[header_map['notes']].strip() if 'notes' in header_map and len(row) > header_map['notes'] else ''
            else:
                name = row[0].strip() if len(row) > 0 else ''
                if not name or name in ['ID', '客人姓名', '姓名']:
                    continue
                if name.isdigit() and len(row) > 1:
                    name = row[1].strip()
                    age_str = row[2].strip() if len(row) > 2 else ''
                    phone = row[3].strip() if len(row) > 3 else ''
                    amount_str = row[4].strip() if len(row) > 4 else '0'
                    event_reason = row[5].strip() if len(row) > 5 and row[5].strip() else '其它'
                    address = row[6].strip() if len(row) > 6 else ''
                    notes = row[7].strip() if len(row) > 7 else ''
                else:
                    age_str = row[1].strip() if len(row) > 1 else ''
                    address = row[2].strip() if len(row) > 2 else ''
                    phone = row[3].strip() if len(row) > 3 else ''
                    amount_str = row[4].strip() if len(row) > 4 else '0'
                    event_reason = row[5].strip() if len(row) > 5 and row[5].strip() else '其它'
                    notes = row[6].strip() if len(row) > 6 else ''

            if not name:
                skip_count += 1
                continue

            try:
                age = int(age_str) if age_str.isdigit() else None
            except ValueError:
                age = None

            try:
                amount = cn2num(amount_str) if amount_str else 0.0
            except Exception:
                amount = 0.0

            record = GiftRecord(
                name=name,
                age=age,
                phone=phone,
                amount=amount,
                event_reason=event_reason,
                address=address,
                notes=notes,
                user_id=current_user.id
            )
            db.session.add(record)
            success_count += 1

        db.session.commit()
        log_action('导入数据', f'成功导入 {success_count} 条礼金记录（忽略 {skip_count} 条）')
        flash(f'批量导入完成！成功导入 {success_count} 条记录' + (f'，忽略 {skip_count} 条无效数据。' if skip_count > 0 else '。'), 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'文件解析或导入失败：{str(e)}', 'danger')

    return redirect(url_for('index'))



if __name__ == '__main__':
    init_database()
    import argparse
    import os

    parser = argparse.ArgumentParser(description='礼金记账系统 Linux/云服务器启动脚本')
    parser.add_argument('--host', type=str, default=os.environ.get('HOST', '0.0.0.0'), help='监听 IP 地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 5000)), help='服务端口 (默认: 5000)')
    parser.add_argument('--admin-user', type=str, default=os.environ.get('ADMIN_USER', None), help='自定义初始管理员账号')
    parser.add_argument('--admin-pass', type=str, default=os.environ.get('ADMIN_PASS', None), help='自定义初始管理员密码')
    args = parser.parse_args()

    # 如果命令行或环境变量指定了初始管理员账号密码，重新/初始化管理员账户
    if args.admin_user and args.admin_pass:
        with app.app_context():
            admin = User.query.filter_by(username=args.admin_user).first()
            if not admin:
                admin = User(username=args.admin_user, is_admin=True)
                admin.set_password(args.admin_pass)
                db.session.add(admin)
            else:
                admin.set_password(args.admin_pass)
                admin.is_admin = True
            db.session.commit()
            print(f"[Init] 管理员账号 [{args.admin_user}] 配置/更新成功！")

    import webbrowser
    import threading
    import sys

    # If running as PyInstaller standalone exe, open browser automatically
    if getattr(sys, 'frozen', False):
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
        app.run(host=args.host, port=args.port, debug=False)
    else:
        app.run(host=args.host, port=args.port, debug=False)
