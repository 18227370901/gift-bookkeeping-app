# -*- coding: utf-8 -*-
"""
AI 助手核心服务层
负责：配置优先级管理、System Prompt 构建、OpenAI 调用、本地兜底
"""
import os
import re
import time
from datetime import datetime

# 尝试导入 OpenAI SDK（可选依赖，未安装时降级为本地引擎）
try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    OpenAI = None
    _HAS_OPENAI = False

from models import db, User, ChatSession, ChatMessage, AIQueryLog
from models import encrypt_credential, decrypt_credential
from web_search import needs_search, search_and_summarize


# ==================== System Prompt ====================

GENERAL_CHAT_PROMPT = """你是一个乐于助人的智能助手，名字叫"礼小宝"。

## 当前日期
今天是 {today}（{weekday}）。
当用户询问日期/时间/星期/节假日等问题时，以此为准。

## 网络搜索结果
{search_context}
如果有搜索结果，优先基于搜索结果回答，末尾标注信息来源。
如显示"（无网络搜索结果）"，则按自身知识回答。

## 用户问题
{user_query}

## 输出要求
1. 语气温暖、耐心，像朋友聊天
2. 回答简洁明了，直击重点
3. 涉及人情往来、礼金、婚宴等话题时，结合中国文化习惯给出建议
4. 有搜索结果时末尾标注"（信息来源：网络搜索）"
"""

# ==================== 配置优先级体系 ====================

def _build_config_list(user=None):
    """
    构建 AI 配置优先级列表
    返回 [{name, api_key, base_url, model}] 列表（已去重）
    """
    configs = []
    seen_keys = set()

    def _add_if_unique(name, api_key, base_url, model):
        if not api_key or api_key in seen_keys:
            return
        seen_keys.add(api_key)
        configs.append({
            'name': name,
            'api_key': api_key,
            'base_url': base_url or '',
            'model': model or 'gpt-4o-mini'
        })

    # 第1优先级：用户多配置 (user.ai_configs)
    if user:
        user_configs = user.get_ai_configs()
        for cfg in user_configs:
            if cfg.get('enabled', True):
                _add_if_unique(
                    cfg.get('name', '用户配置'),
                    cfg.get('api_key', ''),
                    cfg.get('base_url', ''),
                    cfg.get('model', '')
                )

        # 第2优先级：用户旧版单配置
        if user.ai_api_key:
            _add_if_unique(
                '旧版配置',
                user.ai_api_key,
                getattr(user, 'ai_base_url', ''),
                getattr(user, 'ai_model', '')
            )

    # 第3优先级：全局配置（环境变量）
    global_key = os.environ.get('OPENAI_API_KEY', '')
    if global_key:
        _add_if_unique(
            '全局配置',
            global_key,
            os.environ.get('OPENAI_BASE_URL', ''),
            os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
        )

    # 第4优先级：管理员共享配置
    if user and not configs:
        if not getattr(user, 'is_admin', False) and getattr(user, 'ai_authorized', False):
            admin = User.query.filter_by(is_admin=True).first()
            if admin:
                admin_configs = admin.get_ai_configs()
                for cfg in admin_configs:
                    if cfg.get('enabled', True):
                        _add_if_unique(
                            '管理员共享配置',
                            cfg.get('api_key', ''),
                            cfg.get('base_url', ''),
                            cfg.get('model', '')
                        )
                # 兼容管理员旧版字段
                if not configs and admin.ai_api_key:
                    _add_if_unique(
                        '管理员共享配置',
                        admin.ai_api_key,
                        getattr(admin, 'ai_base_url', ''),
                        getattr(admin, 'ai_model', '')
                    )

    return configs


# ==================== OpenAI 调用 ====================

def _call_openai(prompt, api_key, base_url, model):
    """
    调用 OpenAI API
    返回 (success: bool, response: str, error: str)
    """
    if not _HAS_OPENAI:
        return False, '', 'OpenAI SDK 未安装'

    try:
        client_kwargs = {'api_key': api_key}
        if base_url:
            client_kwargs['base_url'] = base_url
        client = OpenAI(**client_kwargs)

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个乐于助人的智能助手，名叫礼小宝。"},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.7,
            timeout=30
        )
        content = resp.choices[0].message.content.strip()
        if content:
            return True, content, ''
        return False, '', 'API 返回空内容'
    except Exception as e:
        return False, '', str(e)


# ==================== 本地兜底引擎 ====================

_LOCAL_INTENTS = [
    ("礼金", "关于礼金金额建议：\n1. 了解当地行情：不同地区礼金标准不同，一般200-1000元不等\n2. 考虑关系亲疏：至亲好友多给，普通同事少给\n3. 参考收礼记录：如有往来记录，按对等或略高原则回礼\n4. 注意双数吉利：尽量选200、600、800等吉利数字，避开单数和含4的数字"),
    ("婚宴", "婚宴礼金建议：\n1. 普通同事/朋友：200-500元\n2. 较好朋友：500-1000元\n3. 至亲好友：1000元以上\n4. 注意当地风俗和酒店档次"),
    ("满月酒", "满月酒礼金建议：\n1. 普通朋友：200-500元\n2. 较好朋友：500-800元\n3. 亲戚：500-1000元\n4. 可搭配婴儿用品作为礼物"),
    ("寿宴", "寿宴礼金建议：\n1. 普通亲友：200-500元\n2. 较亲的亲戚：500-1000元\n3. 至亲：1000元以上\n4. 寿宴讲究吉利数字，如666、888等"),
    ("记账", "人情记账建议：\n1. 及时记录：每次收支后立即记录，避免遗忘\n2. 分类清晰：标注收礼/送礼、事由、金额、日期\n3. 关联宴席：办宴时关联到专属宴席大账本\n4. 定期对账：利用人情对账功能查看往来结余"),
    ("宴席", "办宴预算建议：\n1. 确定桌数：根据预计来宾人数确定\n2. 酒席费用：每桌单价 × 桌数\n3. 附加费用：烟酒、婚庆、场地布置等\n4. 预留弹性：总预算增加10%-15%作为机动支出"),
    ("回礼", "回礼原则：\n1. 对等原则：对方送多少回多少\n2. 略高原则：可比对方多100-200元表示诚意\n3. 及时性：对方有事时及时回礼\n4. 记录查询：查看人情对账了解往来明细"),
    ("乔迁", "乔迁之喜礼金建议：\n1. 普通朋友：200-500元\n2. 较好朋友：500-800元\n3. 亲戚：500-1000元\n4. 也可送实用家电或装饰品"),
    ("升学宴", "升学宴礼金建议：\n1. 普通朋友：200-500元\n2. 较好朋友：500-800元\n3. 亲戚：500-1000元\n4. 可搭配学习用品或红包"),
    ("白事", "白事人情建议：\n1. 金额单数：白事礼金一般用单数（如301、501）\n2. 普通朋友：300-500元\n3. 亲戚：500-1000元\n4. 不用红色信封，用白色或素色信封"),
    ("份子钱", "份子钱建议：\n1. 了解当地行情\n2. 参考往来记录\n3. 关系越近金额越高\n4. 双数为佳（200、600、800等）"),
    ("人情", "人情往来建议：\n1. 有来有往：保持收支平衡\n2. 及时记录：每次收支都记录在账\n3. 定期盘点：查看人情对账，了解结余\n4. 提前规划：看到纪念日提醒即可准备"),
]


def _local_question(query):
    """
    本地兜底回复引擎（无 API Key 时使用）
    关键词匹配 → 命中则返回对应预设回答
    未命中 → 返回通用引导消息
    """
    if not query:
        return "请输入您的问题。"

    query_lower = query.lower()
    for keyword, answer in _LOCAL_INTENTS:
        if keyword in query_lower:
            return answer

    return (
        "您好！我是礼小宝，目前在离线模式下运行。\n\n"
        "您可以问我关于礼金金额、人情往来、宴席预算等方面的问题。\n\n"
        "如需更智能的回答，请联系管理员配置 AI API Key。"
    )


# ==================== 核心 AI 聊天函数 ====================

def ai_chat(query, user, session=None):
    """
    AI 聊天核心函数
    返回 dict: {
        response, used_openai, used_config_name, used_search,
        latency_ms, suggestions, error_hint, session_id, session_title
    }
    """
    start_time = time.time()

    # 1. 判断是否需要联网搜索
    search_context = "（无网络搜索结果）"
    used_search = False
    if needs_search(query):
        search_context = search_and_summarize(query)
        used_search = "无网络搜索结果" not in search_context

    # 2. 构建 prompt
    today = datetime.now().strftime('%Y年%m月%d日')
    weekday_cn = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'][datetime.now().weekday()]
    prompt = GENERAL_CHAT_PROMPT.format(
        today=today,
        weekday=weekday_cn,
        search_context=search_context,
        user_query=query
    )

    # 3. 构建配置列表并逐个尝试
    configs = _build_config_list(user)
    response = ''
    used_openai = False
    used_config_name = ''
    error_hint = ''

    for cfg in configs:
        success, resp, err = _call_openai(
            prompt, cfg['api_key'], cfg['base_url'], cfg['model']
        )
        if success:
            response = resp
            used_openai = True
            used_config_name = cfg['name']
            break
        else:
            error_hint = f"配置[{cfg['name']}]调用失败: {err}"

    # 4. 全部失败 → 本地兜底
    if not response:
        response = _local_question(query)
        used_config_name = ''
        if configs:
            error_hint = f"所有 AI 配置均调用失败，已使用本地知识引擎回复。最后错误: {error_hint}"
        else:
            error_hint = '当前未配置 AI API Key，已使用本地知识引擎回复。请联系管理员配置 AI 以获得更智能的回答。'

    latency_ms = int((time.time() - start_time) * 1000)

    # 5. 保存消息到数据库
    session_id = None
    session_title = '新会话'
    if session:
        session_id = session.id
        session_title = session.title
    elif user:
        # 自动创建新会话
        session = ChatSession(
            user_id=user.id,
            title=query[:30] + ('...' if len(query) > 30 else '')
        )
        db.session.add(session)
        db.session.flush()
        session_id = session.id
        session_title = session.title

    # 保存用户消息
    if session:
        user_msg = ChatMessage(
            session_id=session.id,
            role='user',
            content=query
        )
        db.session.add(user_msg)

        # 保存 AI 消息
        ai_msg = ChatMessage(
            session_id=session.id,
            role='ai',
            content=response,
            used_config_name=used_config_name,
            used_search=used_search,
            error_hint=error_hint
        )
        db.session.add(ai_msg)

        # 更新会话时间
        session.updated_at = datetime.now()

    # 写入旧版日志
    if user:
        log_entry = AIQueryLog(
            user_id=user.id,
            session_id=str(session_id) if session_id else '',
            query_type='qa',
            query_text=query,
            response_text=response,
            response_time_ms=latency_ms
        )
        db.session.add(log_entry)

    db.session.commit()

    # 6. 推荐问题
    suggestions = _get_suggestions()

    return {
        'query': query,
        'response': response,
        'used_openai': used_openai,
        'used_config_name': used_config_name,
        'used_search': used_search,
        'latency_ms': latency_ms,
        'suggestions': suggestions,
        'error_hint': error_hint,
        'session_id': session_id,
        'session_title': session_title
    }


# ==================== 推荐问题 ====================

_SUGGESTIONS = [
    "婚宴礼金一般给多少合适？",
    "满月酒和周岁宴礼金有什么区别？",
    "如何做好人情往来的记账？",
    "乔迁之喜送什么礼好？",
    "白事人情有哪些讲究？",
    "办婚宴预算怎么规划？",
    "人情对账怎么算？",
    "寿宴礼金有什么讲究？",
]


def _get_suggestions():
    """返回推荐问题列表"""
    return _SUGGESTIONS
