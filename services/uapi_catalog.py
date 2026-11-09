# -*- coding: utf-8 -*-
"""
uapi_catalog.py — UApiPro（uapis.cn）全量 API 静态目录（V10.11.47 新增）

数据来源：https://uapis.cn 官方文档（2026-11-02 全量核对），共 110 个 API、21 大分类。
用途：
  1. 「外部接口服务配置」页的 uapis.cn API 目录展示（分类折叠 + 逐个一键测试）
  2. API 试验台动态参数表单（按 params 定义渲染，test_params 预填）
  3. uapi_client 统一调用引擎的路径/方法解析
  4. 天气/节假日业务适配器的协议端点映射（见 API_GROUP_BINDINGS）

字段说明（每条 API 记录）：
  id          内部唯一 ID（同时也是 catalog 内的索引键）
  name        中文名称（与官网文档一致）
  cat         分类键（CATEGORIES 的键）
  method      HTTP 方法（GET/POST）
  path        相对 base_url 的路径（base_url 默认 https://uapis.cn/api/v1）
  credits     每次调用消耗积分（0=永久免费；None=官方未公示）
  params      参数定义列表 [{name, label, type, required, example, options}]（type: text/number/bool/select）
  test_params 一键测试预置参数（None 表示无可靠预置参数，试验台可手动填参调用）
  file_type   True 表示文件上传型接口（multipart 上传图片等），本轮暂不支持在线试验，仅收录目录
  sensitive   True 表示安全敏感接口（端口扫描/在线执行代码等），测试时前端二次确认
  stream      True 表示流式/异步特殊响应接口，试验台仅提示不支持
  doc         官方文档链接
认证：全平台统一「Authorization: Bearer <API Key>」请求头；Key 可空（访客模式，
  按 IP 每月 1500 积分、4 QPS；配置 Key 后按账号 3500 积分/月、7 QPS）。
"""
import time

# ===================== 平台档案 =====================

UAPI_PLATFORM_ID = 'uapis'
UAPI_DEFAULT_BASE_URL = 'https://uapis.cn/api/v1'
UAPI_DOCS_HOME = 'https://uapis.cn/docs/api-reference'
UAPI_NAME = 'UApiPro 聚合 API 平台 (uapis.cn)'

# ===================== 分类定义（与官网侧边栏一致） =====================

CATEGORIES = [
    ('misc',      '杂项服务',   'fa-layer-group'),
    ('poem',      '一言名句',   'fa-feather'),
    ('text',      '文本工具',   'fa-font'),
    ('watermark', '数字水印与 AIGC 标识', 'fa-fingerprint'),
    ('social',    '社交平台',   'fa-users'),
    ('network',   '网络工具',   'fa-network-wired'),
    ('dictionary','词典查询',   'fa-book'),
    ('random',    '随机生成',   'fa-dice'),
    ('game',      '游戏娱乐',   'fa-gamepad'),
    ('sensitive', '敏感词检测', 'fa-shield-halved'),
    ('translate', '翻译服务',   'fa-language'),
    ('status',    '平台状态',   'fa-gauge'),
    ('image',     '图像处理',   'fa-image'),
    ('search',    '智能搜索',   'fa-magnifying-glass'),
    ('execution', '代码执行',   'fa-terminal'),
    ('webparse',  '网页解析',   'fa-globe'),
    ('daily',     '每日更新',   'fa-calendar-day'),
    ('convert',   '格式转换',   'fa-right-left'),
    ('food',      '菜谱食材',   'fa-utensils'),
    ('ai_models', 'AI 模型',   'fa-robot'),
    ('clipboard', '在线剪贴板', 'fa-clipboard'),
]


def _p(name, label, ptype='text', required=False, example='', options=None, convert=None):
    """参数定义构造器（压缩目录书写篇幅）
    ptype: text/number/bool/select/date/datetime
    convert: 前端提交值转换（'timestamp_ms' 日期时间→毫秒时间戳；None 不转换）
    date/datetime 型渲染为系统日历选择器，人类友好输入"""
    return {'name': name, 'label': label, 'type': ptype,
            'required': required, 'example': example, 'options': options or [],
            'convert': convert}


# 预置参数哨兵（resolve_test_params 运行时替换为真实值；前端日历控件同样处理）
SENTRY_NOW_MS = '__NOW_MS__'   # 当前毫秒时间戳
SENTRY_NOW_S = '__NOW_S__'     # 当前秒级时间戳（lunartime 实测参数 ts 为秒级）
SENTRY_TODAY = '__TODAY__'     # 今天 YYYY-MM-DD
SENTRY_YEAR = '__YEAR__'       # 当前年份


def resolve_test_params(api):
    """解析 API 预置测试参数：哨兵值替换为运行时真实值（今天日期/当前时间戳/年份）
    供后端一键测试与前端日历预填共用"""
    import time as _t
    lt = _t.localtime()
    out = {}
    for k, v in (api.get('test_params') or {}).items():
        if v == SENTRY_NOW_MS:
            out[k] = str(int(_t.time() * 1000))
        elif v == SENTRY_NOW_S:
            out[k] = str(int(_t.time()))
        elif v == SENTRY_TODAY:
            out[k] = '%04d-%02d-%02d' % (lt.tm_year, lt.tm_mon, lt.tm_mday)
        elif v == SENTRY_YEAR:
            out[k] = str(lt.tm_year)
        else:
            out[k] = v
    return out


# ===================== 全量 API 目录（110 个） =====================

APIS = [
    # ---------- 杂项服务 misc（18） ----------
    dict(id='misc_weather', name='查询天气', cat='misc', method='GET', path='/misc/weather', credits=2,
         desc='国内外城市实时天气：温度/湿度/风向，extended 附空气质量，forecast 附 7 天预报',
         params=[_p('city', '城市名（中文/英文）', example='北京'),
                 _p('adcode', '行政区划代码（优先于城市名）', example='110000'),
                 _p('extended', '扩展气象字段（体感/能见度/气压/UV/AQI）', 'bool'),
                 _p('forecast', '7 天预报', 'bool'), _p('hourly', '24 小时预报', 'bool'),
                 _p('minutely', '分钟级降水（仅国内）', 'bool'), _p('indices', '18 项生活指数', 'bool'),
                 _p('lang', '响应语言 zh/en', 'select', options=['zh', 'en'])],
         test_params={'city': '北京', 'extended': 'true'},
         doc='https://uapis.cn/docs/api-reference/get-misc-weather'),
    dict(id='misc_hotboard', name='查询热榜', cat='misc', method='GET', path='/misc/hotboard', credits=1,
         desc='微博/知乎/B站/抖音等 40+ 平台实时热榜聚合，含标题/热度/原文链接',
         params=[_p('type', '热榜平台（必填）', 'select', True, 'weibo',
                    options=['weibo', 'zhihu', 'bilibili', 'douyin', 'toutiao', 'baidu', 'douban', 'hupu'])],
         test_params={'type': 'weibo'},
         doc='https://uapis.cn/docs/api-reference/get-misc-hotboard'),
    dict(id='misc_worldtime', name='查询世界时间', cat='misc', method='GET', path='/misc/worldtime', credits=0,
         desc='按城市查询世界各地当前时间（城市名仅支持英文，如 Tokyo/Shanghai/Beijing）',
         params=[_p('city', '城市英文名（必填，如 Tokyo）', 'text', True, 'Shanghai'),
                 _p('timezone', 'IANA 时区名（可选，配合 city）', example='Asia/Shanghai')],
         test_params={'city': 'Shanghai'},
         doc='https://uapis.cn/docs/api-reference/get-misc-worldtime'),
    dict(id='misc_phoneinfo', name='查询手机归属地', cat='misc', method='GET', path='/misc/phoneinfo', credits=2,
         desc='大陆手机号归属省市、运营商（移动/联通/电信）与固话区号',
         params=[_p('phone', '11 位大陆手机号', 'text', True, '13800138000')],
         test_params={'phone': '13800138000'},
         doc='https://uapis.cn/docs/api-reference/get-misc-phoneinfo'),
    dict(id='history_programmer_today', name='程序员历史上的今天', cat='misc', method='GET',
         path='/history/programmer/today', credits=0,
         desc='科技/编程史上今天发生的事件',
         params=[_p('month', '月份'), _p('day', '日期')],
         test_params={},
         doc='https://uapis.cn/docs/api-reference/get-history-programmer-today'),
    dict(id='misc_lunartime', name='查询农历时间', cat='misc', method='GET', path='/misc/lunartime', credits=0,
         desc='指定日期时间对应的农历/干支/生肖信息（日历选择器选日期，提交时自动转为秒级时间戳；经实测参数名为 ts 且为秒级，官方文档的 timestamp 参数实为无效参数）',
         params=[_p('ts', '日期时间（日历选择，提交时自动转秒级时间戳）', 'datetime', True,
                    example='2026-11-03 12:00', convert='timestamp_s')],
         test_params={'ts': SENTRY_NOW_S},
         doc='https://uapis.cn/docs/api-reference/get-misc-lunartime'),
    dict(id='misc_randomnumber', name='随机数生成', cat='misc', method='GET', path='/misc/randomnumber', credits=0,
         desc='指定范围内的随机数',
         params=[_p('min', '最小值', 'number', example='1'), _p('max', '最大值', 'number', example='100')],
         test_params={'min': '1', 'max': '100'},
         doc='https://uapis.cn/docs/api-reference/get-misc-randomnumber'),
    dict(id='history_programmer', name='程序员历史事件', cat='misc', method='GET', path='/history/programmer', credits=0,
         desc='科技历史事件库查询（month/day 必填）',
         params=[_p('month', '月份（1~12，必填）', 'number', True, '11'), _p('day', '日期（1~31，必填）', 'number', True, '2')],
         test_params={'month': '11', 'day': '2'},
         doc='https://uapis.cn/docs/api-reference/get-history-programmer'),
    dict(id='misc_holiday_calendar', name='节假日与万年历', cat='misc', method='GET',
         path='/misc/holiday-calendar', credits=1,
         desc='按 date/month/year 三种模式查询班休/农历/干支/节气（date/month/year 三选一，日历选择器选日期）',
         params=[_p('date', '按日查询（日历选择）', 'date', True, '2026-10-01'),
                 _p('month', '按月查询 YYYY-MM', example='2026-10'),
                 _p('year', '按年查询 YYYY', example='2026'),
                 _p('holiday_type', '类型过滤', 'select', options=['all', 'legal', 'solar', 'lunar', 'term']),
                 _p('region', '地区 CN/HK', 'select', options=['CN', 'HK']),
                 _p('include_nearby', '含前后最近节日（仅 date 模式）', 'bool'),
                 _p('exclude_past', '过滤已过去节日', 'bool')],
         test_params={'date': SENTRY_TODAY, 'include_nearby': 'true'},
         doc='https://uapis.cn/docs/api-reference/get-misc-holiday-calendar'),
    dict(id='misc_timestamp', name='转换时间戳（旧版）', cat='misc', method='GET', path='/misc/timestamp', credits=0,
         desc='时间戳与日期互转（参数名 ts，支持时间戳或常见日期格式；官方推荐改用 /convert/unixtime）',
         params=[_p('ts', '时间戳或日期串（必填）', 'text', True, '1700000000')],
         test_params={'ts': '1700000000'},
         doc='https://uapis.cn/docs/api-reference/get-misc-timestamp'),
    dict(id='misc_tracking_query', name='快递物流查询', cat='misc', method='GET',
         path='/misc/tracking/query', credits=40,
         desc='60+ 快递公司物流轨迹查询（中通/圆通/顺丰/京东/EMS/UPS/FedEx 等），自动识别快递公司。'
              '⚠ 40 积分/次，访客每月仅免费 5 次',
         params=[_p('tracking_number', '快递单号', 'text', True, 'YT1234567890123'),
                 _p('carrier_code', '快递公司代码（可选，加速查询）', example='yuantong'),
                 _p('phone', '收件人手机后 4 位（顺丰等必填才能返回详情）', example='0000'),
                 _p('refresh', '强制刷新最新轨迹', 'bool')],
         test_params=None, sensitive=True,
         doc='https://uapis.cn/docs/api-reference/get-misc-tracking-query'),
    dict(id='misc_district', name='行政区域查询', cat='misc', method='GET', path='/misc/district', credits=2,
         desc='国内外行政区划与 adcode 编码查询',
         params=[_p('adcode', '行政区划代码', example='110000'), _p('name', '区域名称', example='北京')],
         test_params={'adcode': '110000'},
         doc='https://uapis.cn/docs/api-reference/get-misc-district'),
    dict(id='misc_date_diff', name='计算日期差值', cat='misc', method='POST', path='/misc/date-diff', credits=0,
         desc='两个日期之间的精确差值（年/月/日/天数，日历选择器选日期）',
         params=[_p('start_date', '开始日期 YYYY-MM-DD', 'date', True, '2026-01-01'),
                 _p('end_date', '结束日期 YYYY-MM-DD', 'date', True, '2026-12-31')],
         test_params={'start_date': '2026-01-01', 'end_date': SENTRY_TODAY},
         doc='https://uapis.cn/docs/api-reference/post-misc-date-diff'),
    dict(id='misc_weather_history', name='查询历史天气', cat='misc', method='GET', path='/misc/weather/history', credits=1,
         desc='指定城市与日期的历史天气数据（日历选择器选日期）',
         params=[_p('city', '城市名', 'text', True, '北京'), _p('date', '日期 YYYY-MM-DD', 'date', True, '2026-01-01')],
         test_params={'city': '北京', 'date': SENTRY_TODAY},
         doc='https://uapis.cn/docs/api-reference/get-misc-weather-history'),
    dict(id='misc_tracking_detect', name='识别快递公司', cat='misc', method='GET',
         path='/misc/tracking/detect', credits=2,
         desc='仅识别单号所属快递公司（含备选项），不做轨迹查询',
         params=[_p('tracking_number', '快递单号', 'text', True, 'YT1234567890123')],
         test_params={'tracking_number': 'YT1234567890123'},
         doc='https://uapis.cn/docs/api-reference/get-misc-tracking-detect'),
    dict(id='misc_tracking_carriers', name='快递公司列表', cat='misc', method='GET',
         path='/misc/tracking/carriers', credits=2,
         desc='全部支持的快递公司目录（建议缓存）',
         params=[], test_params={},
         doc='https://uapis.cn/docs/api-reference/get-misc-tracking-carriers'),
    dict(id='misc_movie_rating_rank', name='电影收视排行', cat='misc', method='GET',
         path='/misc/movie-rating-rank', credits=1,
         desc='电影/电视剧评分排行榜',
         params=[_p('type', '排行类型', 'select', options=['movie', 'tv'])],
         test_params={'type': 'movie'},
         doc='https://uapis.cn/docs/api-reference/get-misc-movie-rating-rank'),
    dict(id='misc_movie_box_office', name='查询电影票房', cat='misc', method='GET',
         path='/misc/movie-box-office', credits=1,
         desc='实时/每日电影票房数据',
         params=[_p('date', '日期 YYYY-MM-DD')],
         test_params={},
         doc='https://uapis.cn/docs/api-reference/get-misc-movie-box-office'),

    # ---------- 一言名句 poem（2） ----------
    dict(id='saying', name='一言', cat='poem', method='GET', path='/saying', credits=0,
         desc='随机返回一条诗词/动漫/名言（永久免费，无参数）',
         params=[], test_params={},
         doc='https://uapis.cn/docs/api-reference/get-saying'),
    dict(id='saying_random', name='一言（随机/每日/场景/此刻）', cat='poem', method='GET',
         path='/saying/random', credits=1,
         desc='一言进阶版：支持随机/每日固定/场景/此刻四种模式',
         params=[_p('mode', '模式', 'select', options=['random', 'daily', 'scene', 'moment'])],
         test_params={'mode': 'random'},
         doc='https://uapis.cn/docs/api-reference/get-saying-random'),

    # ---------- 文本工具 text（13） ----------
    dict(id='text_md5', name='MD5 哈希（GET）', cat='text', method='GET', path='/text/md5', credits=0,
         desc='文本 MD5 哈希计算',
         params=[_p('text', '原文', 'text', True, 'hello')],
         test_params={'text': 'hello'},
         doc='https://uapis.cn/docs/api-reference/get-text-md5'),
    dict(id='text_md5_post', name='MD5 哈希（POST）', cat='text', method='POST', path='/text/md5', credits=0,
         desc='文本 MD5 哈希计算（POST 版，适合长文本）',
         params=[_p('text', '原文', 'text', True, 'hello')],
         test_params={'text': 'hello'},
         doc='https://uapis.cn/docs/api-reference/post-text-md5'),
    dict(id='text_analyze', name='文本分析', cat='text', method='POST', path='/text/analyze', credits=1,
         desc='字数/词频/句子结构等文本统计分析',
         params=[_p('text', '待分析文本', 'text', True, '你好世界')],
         test_params={'text': '你好世界'},
         doc='https://uapis.cn/docs/api-reference/post-text-analyze'),
    dict(id='text_base64_decode', name='Base64 解码', cat='text', method='POST', path='/text/base64/decode', credits=0,
         desc='Base64 字符串解码（参数 text）',
         params=[_p('text', 'Base64 串', 'text', True, 'aGVsbG8=')],
         test_params={'text': 'aGVsbG8='},
         doc='https://uapis.cn/docs/api-reference/post-text-base64-decode'),
    dict(id='text_base64_encode', name='Base64 编码', cat='text', method='POST', path='/text/base64/encode', credits=0,
         desc='文本 Base64 编码（参数 text）',
         params=[_p('text', '原文', 'text', True, 'hello')],
         test_params={'text': 'hello'},
         doc='https://uapis.cn/docs/api-reference/post-text-base64-encode'),
    dict(id='text_aes_encrypt', name='AES 加密', cat='text', method='POST', path='/text/aes/encrypt', credits=0,
         desc='AES 对称加密（永久免费，参数 text + key）',
         params=[_p('text', '原文', 'text', True, 'hello'), _p('key', '密钥（16 位）', 'text', True, '1234567890abcdef')],
         test_params={'text': 'hello', 'key': '1234567890abcdef'},
         doc='https://uapis.cn/docs/api-reference/post-text-aes-encrypt'),
    dict(id='text_aes_decrypt', name='AES 解密', cat='text', method='POST', path='/text/aes/decrypt', credits=0,
         desc='AES 对称解密（参数 text + key）',
         params=[_p('text', '密文', 'text', True, '...'), _p('key', '密钥（16 位）', 'text', True, '1234567890abcdef')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-text-aes-decrypt'),
    dict(id='text_md5_verify', name='MD5 校验', cat='text', method='POST', path='/text/md5/verify', credits=0,
         desc='校验文本与 MD5 哈希是否匹配（参数 text + hash）',
         params=[_p('text', '原文', 'text', True, 'hello'),
                 _p('hash', 'MD5 哈希', 'text', True, '5d41402abc4b2a76b9719d911017c592')],
         test_params={'text': 'hello', 'hash': '5d41402abc4b2a76b9719d911017c592'},
         doc='https://uapis.cn/docs/api-reference/post-text-md5-verify'),
    dict(id='text_aes_encrypt_advanced', name='AES 高级加密', cat='text', method='POST',
         path='/text/aes-encrypt-advanced', credits=1,
         desc='支持自定 IV/模式/填充的 AES 加密',
         params=[_p('text', '原文', 'text', True, 'hello'), _p('key', '密钥', 'text', True),
                 _p('iv', '初始向量 IV'), _p('mode', '加密模式', 'select', options=['CBC', 'ECB', 'GCM'])],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-text-aes-encrypt-advanced'),
    dict(id='text_aes_decrypt_advanced', name='AES 高级解密', cat='text', method='POST',
         path='/text/aes-decrypt-advanced', credits=1,
         desc='支持自定 IV/模式/填充的 AES 解密',
         params=[_p('text', '密文', 'text', True), _p('key', '密钥', 'text', True),
                 _p('iv', '初始向量 IV'), _p('mode', '解密模式', 'select', options=['CBC', 'ECB', 'GCM'])],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-text-aes-decrypt-advanced'),
    dict(id='text_markdown_to_html', name='Markdown 转 HTML', cat='text', method='POST',
         path='/text/markdown-to-html', credits=1,
         desc='Markdown 文档转 HTML',
         params=[_p('text', 'Markdown 内容', 'text', True, '# 标题\n正文')],
         test_params={'text': '# 人情记账本\nHello'},
         doc='https://uapis.cn/docs/api-reference/post-text-markdown-to-html'),
    dict(id='text_markdown_to_pdf', name='Markdown 转 PDF', cat='text', method='POST',
         path='/text/markdown-to-pdf', credits=2,
         desc='Markdown 文档转 PDF（返回文件流）',
         params=[_p('text', 'Markdown 内容', 'text', True, '# 标题')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-text-markdown-to-pdf'),
    dict(id='text_convert', name='格式转换', cat='text', method='POST', path='/text/convert', credits=1,
         desc='文本格式转换（大小写/编码等）',
         params=[_p('text', '原文', 'text', True, 'hello'), _p('from', '源格式'), _p('to', '目标格式')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-text-convert'),

    # ---------- 数字水印与 AIGC 标识 watermark（4） ----------
    dict(id='watermark_embed', name='添加图片隐水印', cat='watermark', method='POST',
         path='/watermark/embed', credits=4, file_type=True,
         desc='图片添加不可见隐水印（文件上传型）',
         params=[], test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-watermark-embed'),
    dict(id='watermark_decode', name='提取图片隐水印', cat='watermark', method='POST',
         path='/watermark/decode', credits=4, file_type=True,
         desc='提取图片中的隐水印内容（文件上传型）',
         params=[], test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-watermark-decode'),
    dict(id='watermark_label', name='添加 AIGC 生成标识', cat='watermark', method='POST',
         path='/watermark/label', credits=4, file_type=True,
         desc='为 AI 生成图片嵌入 AIGC 内容标识（文件上传型）',
         params=[], test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-watermark-label'),
    dict(id='watermark_producer_code', name='生成 AIGC 服务提供者编码', cat='watermark', method='POST',
         path='/watermark/producer-code', credits=1,
         desc='生成 AIGC 内容标识中的服务提供者编码',
         params=[_p('type', '编码类型')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-watermark-producer-code'),

    # ---------- 社交平台 social（7） ----------
    dict(id='social_bilibili_liveroom', name='查询 B站直播间', cat='social', method='GET',
         path='/social/bilibili/liveroom', credits=4,
         desc='B站直播间实时信息（标题/人气/主播）',
         params=[_p('room_id', '直播间号', 'text', True, '6')],
         test_params={'room_id': '6'},
         doc='https://uapis.cn/docs/api-reference/get-social-bilibili-liveroom'),
    dict(id='social_bilibili_userinfo', name='查询 B站用户', cat='social', method='GET',
         path='/social/bilibili/userinfo', credits=4,
         desc='B站用户公开信息（粉丝/投稿数等）',
         params=[_p('uid', 'B站 UID', 'text', True, '2')],
         test_params={'uid': '2'},
         doc='https://uapis.cn/docs/api-reference/get-social-bilibili-userinfo'),
    dict(id='social_bilibili_archives', name='查询 B站投稿', cat='social', method='GET',
         path='/social/bilibili/archives', credits=4,
         desc='B站用户投稿视频列表',
         params=[_p('uid', 'B站 UID', 'text', True, '2'), _p('page', '页码', 'number')],
         test_params={'uid': '2'},
         doc='https://uapis.cn/docs/api-reference/get-social-bilibili-archives'),
    dict(id='social_bilibili_videoinfo', name='查询 B站视频', cat='social', method='GET',
         path='/social/bilibili/videoinfo', credits=4,
         desc='B站视频详细信息（播放/弹幕/封面/UP主）',
         params=[_p('bvid', '视频 BV 号', 'text', True, 'BV1GJ411x7h7')],
         test_params={'bvid': 'BV1GJ411x7h7'},
         doc='https://uapis.cn/docs/api-reference/get-social-bilibili-videoinfo'),
    dict(id='social_bilibili_replies', name='查询 B站评论', cat='social', method='GET',
         path='/social/bilibili/replies', credits=4,
         desc='B站视频评论列表',
         params=[_p('bvid', '视频 BV 号', example='BV1GJ411x7h7'), _p('aid', '视频 AV 号'), _p('page', '页码', 'number')],
         test_params={'bvid': 'BV1GJ411x7h7'},
         doc='https://uapis.cn/docs/api-reference/get-social-bilibili-replies'),
    dict(id='github_repo', name='查询 GitHub 仓库', cat='social', method='GET', path='/github/repo', credits=2,
         desc='GitHub 仓库公开信息（Star/Fork/语言）',
         params=[_p('repo', '仓库名 owner/repo', 'text', True, 'shuakami/uapi')],
         test_params={'repo': 'shuakami/uapi'},
         doc='https://uapis.cn/docs/api-reference/get-github-repo'),
    dict(id='github_user', name='查询 GitHub 用户', cat='social', method='GET', path='/github/user', credits=2,
         desc='GitHub 用户公开信息',
         params=[_p('username', 'GitHub 用户名', 'text', True, 'shuakami')],
         test_params={'username': 'shuakami'},
         doc='https://uapis.cn/docs/api-reference/get-github-user'),

    # ---------- 网络工具 network（9） ----------
    dict(id='network_myip', name='查询我的 IP', cat='network', method='GET', path='/network/myip', credits=1,
         desc='查询本机出口公网 IP 及归属地',
         params=[_p('source', '数据源', 'select', options=['standard', 'commercial'])],
         test_params={},
         doc='https://uapis.cn/docs/api-reference/get-network-myip'),
    dict(id='network_ipinfo', name='查询 IP', cat='network', method='GET', path='/network/ipinfo', credits=1,
         desc='IP 地址或域名归属地查询（source=commercial 更全）',
         params=[_p('ip', 'IP 或域名', 'text', True, '8.8.8.8'),
                 _p('source', '数据源', 'select', options=['standard', 'commercial'])],
         test_params={'ip': '8.8.8.8'},
         doc='https://uapis.cn/docs/api-reference/get-network-ipinfo'),
    dict(id='network_whois', name='查询 WHOIS 注册信息', cat='network', method='GET', path='/network/whois', credits=2,
         desc='域名 WHOIS 注册信息',
         params=[_p('domain', '域名', 'text', True, 'baidu.com')],
         test_params={'domain': 'baidu.com'},
         doc='https://uapis.cn/docs/api-reference/get-network-whois'),
    dict(id='network_ping', name='Ping 主机', cat='network', method='GET', path='/network/ping', credits=1,
         desc='Ping 指定主机（延迟/丢包）',
         params=[_p('host', '主机名/IP', 'text', True, 'baidu.com')],
         test_params={'host': 'baidu.com'},
         doc='https://uapis.cn/docs/api-reference/get-network-ping'),
    dict(id='network_dns', name='DNS 解析查询', cat='network', method='GET', path='/network/dns', credits=2,
         desc='域名 DNS 解析记录查询',
         params=[_p('domain', '域名', 'text', True, 'baidu.com'),
                 _p('type', '记录类型', 'select', options=['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS'])],
         test_params={'domain': 'baidu.com', 'type': 'A'},
         doc='https://uapis.cn/docs/api-reference/get-network-dns'),
    dict(id='network_urlstatus', name='检查 URL 可访问性', cat='network', method='GET',
         path='/network/urlstatus', credits=1,
         desc='URL 可访问状态检查（状态码/耗时）',
         params=[_p('url', '目标 URL', 'text', True, 'https://www.baidu.com')],
         test_params={'url': 'https://www.baidu.com'},
         doc='https://uapis.cn/docs/api-reference/get-network-urlstatus'),
    dict(id='network_portscan', name='端口扫描', cat='network', method='GET', path='/network/portscan', credits=1,
         desc='主机端口开放状态扫描。⚠ 安全敏感操作，仅对自己拥有授权的主机使用',
         params=[_p('host', '主机名/IP', 'text', True, '127.0.0.1'), _p('port', '端口', 'number', True, '80')],
         test_params=None, sensitive=True,
         doc='https://uapis.cn/docs/api-reference/get-network-portscan'),
    dict(id='network_wxdomain', name='微信域名状态检测', cat='network', method='GET',
         path='/network/wxdomain', credits=1,
         desc='检测域名在微信内是否可访问（防封检测）',
         params=[_p('domain', '域名', 'text', True, 'baidu.com')],
         test_params={'domain': 'baidu.com'},
         doc='https://uapis.cn/docs/api-reference/get-network-wxdomain'),
    dict(id='network_pingmyip', name='Ping 我的 IP', cat='network', method='GET', path='/network/pingmyip', credits=1,
         desc='Ping 本机出口公网 IP',
         params=[], test_params={},
         doc='https://uapis.cn/docs/api-reference/get-network-pingmyip'),

    # ---------- 词典查询 dictionary（3） ----------
    dict(id='dictionary_lookup', name='单词查询', cat='dictionary', method='GET', path='/dictionary/lookup', credits=2,
         desc='英汉词典单词释义查询',
         params=[_p('word', '单词', 'text', True, 'hello')],
         test_params={'word': 'hello'},
         doc='https://uapis.cn/docs/api-reference/get-dictionary-lookup'),
    dict(id='dictionary_audio', name='单词发音', cat='dictionary', method='GET', path='/dictionary/audio', credits=1,
         desc='单词发音音频（返回音频流）',
         params=[_p('word', '单词', 'text', True, 'hello')],
         test_params={'word': 'hello'},
         doc='https://uapis.cn/docs/api-reference/get-dictionary-audio'),
    dict(id='dictionary_suggest', name='词典推荐语', cat='dictionary', method='GET',
         path='/dictionary/suggest', credits=1,
         desc='单词记忆推荐语/联想',
         params=[_p('word', '单词', 'text', True, 'hello')],
         test_params={'word': 'hello'},
         doc='https://uapis.cn/docs/api-reference/get-dictionary-suggest'),

    # ---------- 随机生成 random（4） ----------
    dict(id='random_image', name='随机图片', cat='random', method='GET', path='/random/image', credits=0,
         desc='随机图片（永久免费，返回图片或 JSON）',
         params=[_p('type', '图片类型')],
         test_params={},
         doc='https://uapis.cn/docs/api-reference/get-random-image'),
    dict(id='answerbook_ask', name='答案之书', cat='random', method='GET', path='/answerbook/ask', credits=0,
         desc='答案之书：提出问题随机获得一句答案（永久免费）',
         params=[_p('question', '你的问题', 'text', True, '今天适合办酒席吗')],
         test_params={'question': '今天适合办酒席吗'},
         doc='https://uapis.cn/docs/api-reference/get-answerbook-ask'),
    dict(id='answerbook_ask_post', name='答案之书（POST）', cat='random', method='POST',
         path='/answerbook/ask', credits=0,
         desc='答案之书 POST 版（永久免费）',
         params=[_p('question', '你的问题', 'text', True, '今天适合记账吗')],
         test_params={'question': '今天适合记账吗'},
         doc='https://uapis.cn/docs/api-reference/post-answerbook-ask'),
    dict(id='random_string', name='随机字符串', cat='random', method='GET', path='/random/string', credits=0,
         desc='随机字符串生成（永久免费）',
         params=[_p('length', '长度', 'number', example='16')],
         test_params={'length': '16'},
         doc='https://uapis.cn/docs/api-reference/get-random-string'),

    # ---------- 游戏娱乐 game（9） ----------
    dict(id='game_minecraft_serverstatus', name='查询 MC 服务器', cat='game', method='GET',
         path='/game/minecraft/serverstatus', credits=1,
         desc='Minecraft Java 版服务器状态（在线人数/版本/MOTD，参数 server）',
         params=[_p('server', '服务器地址（必填）', 'text', True, 'play.hypixel.net')],
         test_params={'server': 'play.hypixel.net'},
         doc='https://uapis.cn/docs/api-reference/get-game-minecraft-serverstatus'),
    dict(id='game_steam_summary', name='查询 Steam 用户', cat='game', method='GET',
         path='/game/steam/summary', credits=2,
         desc='Steam 用户公开档案',
         params=[_p('steamid', 'Steam 64 位 ID', 'text', True, '76561197960435530')],
         test_params={'steamid': '76561197960435530'},
         doc='https://uapis.cn/docs/api-reference/get-game-steam-summary'),
    dict(id='game_minecraft_userinfo', name='查询 MC 玩家', cat='game', method='GET',
         path='/game/minecraft/userinfo', credits=1,
         desc='Minecraft 玩家档案（UUID/皮肤，参数 username）',
         params=[_p('username', '玩家名（必填）', 'text', True, 'Notch')],
         test_params={'username': 'Notch'},
         doc='https://uapis.cn/docs/api-reference/get-game-minecraft-userinfo'),
    dict(id='game_epic_free', name='Epic 免费游戏', cat='game', method='GET', path='/game/epic-free', credits=1,
         desc='Epic 本周免费游戏列表',
         params=[], test_params={},
         doc='https://uapis.cn/docs/api-reference/get-game-epic-free'),
    dict(id='game_minecraft_historyid', name='查询 MC 曾用名', cat='game', method='GET',
         path='/game/minecraft/historyid', credits=1,
         desc='Minecraft 玩家曾用名记录',
         params=[_p('name', '玩家名', 'text', True, 'Notch')],
         test_params={'name': 'Notch'},
         doc='https://uapis.cn/docs/api-reference/get-game-minecraft-historyid'),
    dict(id='game_minecraft_bedrockstatus', name='查询 MC 基岩版服务器', cat='game', method='GET',
         path='/game/minecraft/bedrockstatus', credits=1,
         desc='Minecraft 基岩版服务器状态（参数 server）',
         params=[_p('server', '服务器地址（必填）', 'text', True, 'mco.mineplex.com')],
         test_params={'server': 'mco.mineplex.com'},
         doc='https://uapis.cn/docs/api-reference/get-game-minecraft-bedrockstatus'),
    dict(id='game_minecraft_version', name='Minecraft 最新版本', cat='game', method='GET',
         path='/game/minecraft/version', credits=1,
         desc='Minecraft 最新版本号',
         params=[], test_params={},
         doc='https://uapis.cn/docs/api-reference/get-game-minecraft-version'),
    dict(id='game_steam_servers', name='查询 Steam 游戏服务器', cat='game', method='GET',
         path='/game/steam/servers', credits=1,
         desc='Steam 游戏服务器列表（参数 appid，如 730=CS2）',
         params=[_p('appid', '游戏 AppID（必填，如 730）', 'number', True, '730')],
         test_params={'appid': '730'},
         doc='https://uapis.cn/docs/api-reference/get-game-steam-servers'),
    dict(id='game_minecraft_mods', name='搜索 MC Mod/插件', cat='game', method='GET',
         path='/game/minecraft/mods', credits=1,
         desc='Minecraft Mod/插件搜索（CurseForge 等，参数 query）',
         params=[_p('query', '关键词（必填）', 'text', True, '优化')],
         test_params={'query': '优化'},
         doc='https://uapis.cn/docs/api-reference/get-game-minecraft-mods'),

    # ---------- 敏感词检测 sensitive（3） ----------
    dict(id='sensitive_word_quick_check', name='敏感词检测（快速）', cat='sensitive', method='POST',
         path='/sensitive-word/quick-check', credits=1,
         desc='文本是否含敏感词（布尔快速判定；参数名请以试验台或官方文档为准）',
         params=[_p('text', '待检测文本', 'text', True, '你好世界')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-sensitive-word-quick-check'),
    dict(id='sensitive_word_analyze', name='分析敏感词', cat='sensitive', method='POST',
         path='/sensitive-word/analyze', credits=4,
         desc='敏感词详细分析（命中词/分类/位置）',
         params=[_p('text', '待检测文本', 'text', True, '你好世界')],
         test_params={'text': '你好世界'},
         doc='https://uapis.cn/docs/api-reference/post-sensitive-word-analyze'),
    dict(id='sensitive_word_analyze_query', name='敏感词分析（GET）', cat='sensitive', method='GET',
         path='/sensitive-word/analyze-query', credits=4,
         desc='敏感词详细分析（GET 版）',
         params=[_p('text', '待检测文本', 'text', True, '你好世界')],
         test_params={'text': '你好世界'},
         doc='https://uapis.cn/docs/api-reference/get-sensitive-word-analyze-query'),

    # ---------- 翻译服务 translate（4） ----------
    dict(id='translate_text', name='翻译', cat='translate', method='POST', path='/translate/text', credits=2,
         desc='多语种文本翻译',
         params=[_p('text', '待翻译文本', 'text', True, '你好世界'),
                 _p('toLang', '目标语言（如 en/ja/ko）', 'text', True, 'en'),
                 _p('fromLang', '源语言（可省略自动检测）', 'text', False, 'zh')],
         test_params={'text': '礼轻情意重', 'toLang': 'en'},
         doc='https://uapis.cn/docs/api-reference/post-translate-text'),
    dict(id='ai_translate', name='AI 智能翻译', cat='translate', method='POST', path='/ai/translate', credits=4,
         desc='大模型翻译（更自然的译文，支持语气/风格）',
         params=[_p('text', '待翻译文本', 'text', True, '礼轻情意重'),
                 _p('to', '目标语言', 'text', True, 'en')],
         test_params={'text': '礼轻情意重', 'to': 'en'},
         doc='https://uapis.cn/docs/api-reference/post-ai-translate'),
    dict(id='ai_translate_languages', name='AI 翻译配置', cat='translate', method='GET',
         path='/ai/translate/languages', credits=1,
         desc='AI 翻译支持的语种列表',
         params=[], test_params={},
         doc='https://uapis.cn/docs/api-reference/get-ai-translate-languages'),
    dict(id='translate_stream', name='流式翻译（中英互译）', cat='translate', method='POST',
         path='/translate/stream', credits=4, stream=True,
         desc='流式翻译（SSE 流式响应，试验台暂不支持在线调用）',
         params=[_p('text', '待翻译文本', 'text', True, '你好')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-translate-stream'),

    # ---------- 平台状态 status（1） ----------
    dict(id='status_usage', name='API 端点使用统计', cat='status', method='GET', path='/status/usage', credits=0,
         desc='平台端点使用统计（永久免费）',
         params=[], test_params={},
         doc='https://uapis.cn/docs/api-reference/get-status-usage'),

    # ---------- 图像处理 image（14） ----------
    dict(id='image_bing_daily', name='获取必应每日壁纸', cat='image', method='GET',
         path='/image/bing-daily', credits=0,
         desc='必应每日高清壁纸（永久免费）',
         params=[_p('resolution', '分辨率', 'select', options=['1920x1080', 'UHD'])],
         test_params={},
         doc='https://uapis.cn/docs/api-reference/get-image-bing-daily'),
    dict(id='image_qrcode', name='生成二维码', cat='image', method='GET', path='/image/qrcode', credits=0,
         desc='文本/URL 生成二维码（永久免费）',
         params=[_p('text', '二维码内容', 'text', True, 'https://uapis.cn')],
         test_params={'text': 'https://uapis.cn'},
         doc='https://uapis.cn/docs/api-reference/get-image-qrcode'),
    dict(id='image_nsfw', name='图片敏感内容检测', cat='image', method='POST', path='/image/nsfw', credits=4,
         file_type=True,
         desc='图片 NSFW 敏感内容检测（文件上传型）',
         params=[], test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-image-nsfw'),
    dict(id='image_tobase64', name='图片转 Base64', cat='image', method='GET', path='/image/tobase64', credits=2,
         desc='在线图片 URL 转 Base64 编码',
         params=[_p('url', '图片 URL', 'text', True, 'https://www.baidu.com/img/flexible/logo/pc/result.png')],
         test_params={'url': 'https://www.baidu.com/img/flexible/logo/pc/result.png'},
         doc='https://uapis.cn/docs/api-reference/get-image-tobase64'),
    dict(id='avatar_gravatar', name='获取 Gravatar 头像', cat='image', method='GET', path='/avatar/gravatar', credits=2,
         desc='邮箱/MD5 对应的 Gravatar 全球通用头像',
         params=[_p('email', '邮箱（或 MD5）', 'text', True, 'someone@example.com')],
         test_params={'email': 'someone@example.com'},
         doc='https://uapis.cn/docs/api-reference/get-avatar-gravatar'),
    dict(id='image_motou_get', name='生成摸摸头 GIF（QQ 号）', cat='image', method='GET',
         path='/image/motou', credits=2,
         desc='按 QQ 号生成摸摸头 GIF',
         params=[_p('qq', 'QQ 号', 'text', True, '10000')],
         test_params={'qq': '10000'},
         doc='https://uapis.cn/docs/api-reference/get-image-motou'),
    dict(id='image_motou_post', name='生成摸摸头 GIF', cat='image', method='POST', path='/image/motou', credits=2,
         file_type=True,
         desc='自定图片生成摸摸头 GIF（文件上传型）',
         params=[], test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-image-motou'),
    dict(id='image_compress', name='无损压缩图片', cat='image', method='POST', path='/image/compress', credits=2,
         file_type=True,
         desc='图片无损压缩（文件上传型）',
         params=[], test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-image-compress'),
    dict(id='image_ocr', name='通用 OCR 文字识别', cat='image', method='POST', path='/image/ocr', credits=4,
         file_type=True,
         desc='图片文字 OCR 识别（文件上传型）',
         params=[], test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-image-ocr'),
    dict(id='image_bing_daily_history', name='必应壁纸历史', cat='image', method='GET',
         path='/image/bing-daily/history', credits=0,
         desc='历史必应每日壁纸（永久免费）',
         params=[_p('date', '日期 YYYY-MM-DD'), _p('page', '页码', 'number')],
         test_params={'page': '1'},
         doc='https://uapis.cn/docs/api-reference/get-image-bing-daily-history'),
    dict(id='image_speechless', name='「你们怎么不说话了」表情包', cat='image', method='POST',
         path='/image/speechless', credits=2, file_type=True,
         desc='生成整活表情包（文件上传型）',
         params=[], test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-image-speechless'),
    dict(id='image_decode', name='解码并缩放图片', cat='image', method='POST', path='/image/decode', credits=2,
         file_type=True,
         desc='图片解码与缩放（文件上传型）',
         params=[], test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-image-decode'),
    dict(id='image_svg', name='SVG 转图片', cat='image', method='POST', path='/image/svg', credits=1,
         desc='SVG 矢量图转 PNG 位图（参数名请以试验台或官方文档为准）',
         params=[_p('svg', 'SVG 源码', 'text', True, '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="red"/></svg>')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-image-svg'),
    dict(id='image_matting', name='图片抠图（背景移除）', cat='image', method='POST', path='/image/matting', credits=4,
         file_type=True,
         desc='AI 图片抠图去背景（文件上传型）',
         params=[], test_params=None,
         doc='https://uapis.cn/docs/api-reference/post-image-matting'),

    # ---------- 智能搜索 search（2） ----------
    dict(id='search_aggregate', name='智能搜索', cat='search', method='POST', path='/search/aggregate', credits=4,
         desc='聚合多搜索引擎的智能搜索结果',
         params=[_p('query', '搜索关键词', 'text', True, '人情礼金记账')],
         test_params={'query': '人情礼金记账'},
         doc='https://uapis.cn/docs/api-reference/post-search-aggregate'),
    dict(id='search_engines', name='搜索引擎配置', cat='search', method='GET', path='/search/engines', credits=0,
         desc='智能搜索支持的引擎列表（永久免费）',
         params=[], test_params={},
         doc='https://uapis.cn/docs/api-reference/get-search-engines'),

    # ---------- 代码执行 execution（1） ----------
    dict(id='execution_run', name='在线运行代码', cat='execution', method='POST', path='/execution/run', credits=4,
         desc='多语言在线代码沙箱执行。⚠ 敏感接口，谨慎使用',
         params=[_p('language', '编程语言', 'select', True, 'python',
                    options=['python', 'javascript', 'java', 'c', 'cpp', 'go', 'rust']),
                 _p('code', '代码', 'text', True, 'print("hello")')],
         test_params={'language': 'python', 'code': 'print("hello")'}, sensitive=True,
         doc='https://uapis.cn/docs/api-reference/post-execution-run'),

    # ---------- 网页解析 webparse（4） ----------
    dict(id='webparse_metadata', name='提取网页元数据', cat='webparse', method='GET',
         path='/webparse/metadata', credits=1,
         desc='网页标题/描述/图标等元数据（链接预览卡片）',
         params=[_p('url', '网页 URL', 'text', True, 'https://www.baidu.com')],
         test_params={'url': 'https://www.baidu.com'},
         doc='https://uapis.cn/docs/api-reference/get-webparse-metadata'),
    dict(id='webparse_extractimages', name='提取网页图片', cat='webparse', method='GET',
         path='/webparse/extractimages', credits=2,
         desc='提取网页中的全部图片地址',
         params=[_p('url', '网页 URL', 'text', True, 'https://www.baidu.com')],
         test_params={'url': 'https://www.baidu.com'},
         doc='https://uapis.cn/docs/api-reference/get-webparse-extractimages'),
    dict(id='web_to_markdown_async', name='网页转 Markdown', cat='webparse', method='POST',
         path='/web-to-markdown-async', credits=4,
         desc='网页正文转 Markdown（异步任务，返回 task_id 后用转换任务状态查询）',
         params=[_p('url', '网页 URL', 'text', True, 'https://www.baidu.com')],
         test_params={'url': 'https://www.baidu.com'},
         doc='https://uapis.cn/docs/api-reference/post-web-tomarkdown-async'),
    dict(id='web_tomarkdown_async_status', name='转换任务状态', cat='webparse', method='GET',
         path='/web-tomarkdown-async-status', credits=0,
         desc='查询网页转 Markdown 异步任务状态与结果（永久免费）',
         params=[_p('task_id', '任务 ID', 'text', True, '...')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/get-web-tomarkdown-async-status'),

    # ---------- 每日更新 daily（2） ----------
    dict(id='daily_news_image', name='每日新闻图', cat='daily', method='GET', path='/daily/news-image', credits=1,
         desc='今日热点新闻一张图（直接返回 JPEG 图片二进制，建议超时 ≥10s）',
         params=[], test_params={}, image_response=True,
         doc='https://uapis.cn/docs/api-reference/get-daily-news-image'),
    dict(id='daily_word', name='每日单词', cat='daily', method='GET', path='/daily/word', credits=1,
         desc='每天稳定一个英文单词（可按词库分类/含例句音标释义）',
         params=[_p('lang', '语言（当前支持 en）', 'select', options=['en']),
                 _p('category', '词库', 'select', options=['all', 'cet4', 'cet6', 'ielts', 'toefl', 'gre']),
                 _p('count', '数量 1-20', 'number', example='1'),
                 _p('example', '含例句', 'bool'), _p('phonetic', '含音标', 'bool'), _p('define', '含详细释义', 'bool')],
         test_params={'category': 'cet4', 'count': '1'},
         doc='https://uapis.cn/docs/api-reference/get-daily-word'),

    # ---------- 格式转换 convert（2） ----------
    dict(id='convert_unixtime', name='时间戳转换', cat='convert', method='GET', path='/convert/unixtime', credits=0,
         desc='时间戳 ⇄ 日期字符串双向转换（参数 time，传时间戳返回日期，传日期返回时间戳；永久免费）',
         params=[_p('time', '时间戳或日期串（必填）', 'text', True, '1700000000')],
         test_params={'time': '1700000000'},
         doc='https://uapis.cn/docs/api-reference/get-convert-unixtime'),
    dict(id='convert_json', name='JSON 格式化', cat='convert', method='POST', path='/convert/json', credits=0,
         desc='JSON 校验/格式化/压缩（参数 content，永久免费）',
         params=[_p('content', 'JSON 文本（必填）', 'text', True, '{"a": 1}')],
         test_params={'content': '{"a": 1}'},
         doc='https://uapis.cn/docs/api-reference/post-convert-json'),

    # ---------- 菜谱食材 food（4） ----------
    dict(id='food_recipe', name='菜谱搜索', cat='food', method='GET', path='/food/recipe', credits=1,
         desc='菜谱关键词搜索',
         params=[_p('keyword', '菜名关键词', 'text', True, '红烧肉')],
         test_params={'keyword': '红烧肉'},
         doc='https://uapis.cn/docs/api-reference/get-food-recipe'),
    dict(id='food_recipe_detail', name='菜谱详情', cat='food', method='GET', path='/food/recipe-detail', credits=3,
         desc='菜谱完整详情（食材/步骤）',
         params=[_p('id', '菜谱 ID', 'text', True, '...')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/get-food-recipe-detail'),
    dict(id='food_ingredient', name='食材搜索', cat='food', method='GET', path='/food/ingredient', credits=1,
         desc='食材关键词搜索',
         params=[_p('keyword', '食材关键词', 'text', True, '土豆')],
         test_params={'keyword': '土豆'},
         doc='https://uapis.cn/docs/api-reference/get-food-ingredient'),
    dict(id='food_ingredient_detail', name='食材营养详情', cat='food', method='GET',
         path='/food/ingredient-detail', credits=3,
         desc='食材营养成分详情',
         params=[_p('id', '食材 ID', 'text', True, '...')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/get-food-ingredient-detail'),

    # ---------- AI 模型 ai_models（1） ----------
    dict(id='ai_models', name='AI 模型列表', cat='ai_models', method='GET', path='/ai/models', credits=2,
         desc='主流 AI 大模型清单',
         params=[], test_params={},
         doc='https://uapis.cn/docs/api-reference/get-ai-models'),

    # ---------- 在线剪贴板 clipboard（3） ----------
    dict(id='clipzy_store', name='剪贴板·上传加密数据', cat='clipboard', method='POST', path='/clipzy/store',
         credits=None,
         desc='Clipzy 在线剪贴板第一步：上传文本（返回取件码）',
         params=[_p('text', '文本内容', 'text', True, 'hello')],
         test_params={'text': 'hello'},
         doc='https://uapis.cn/docs/api-reference/post-clipzy-store'),
    dict(id='clipzy_get', name='剪贴板·获取加密数据', cat='clipboard', method='GET', path='/clipzy/get',
         credits=None,
         desc='Clipzy 在线剪贴板第二步（方式一）：按取件码获取加密数据',
         params=[_p('key', '取件码', 'text', True, '...')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/get-clipzy-get'),
    dict(id='clipzy_raw', name='剪贴板·获取原文', cat='clipboard', method='GET', path='/clipzy/raw',
         credits=None,
         desc='Clipzy 在线剪贴板第二步（方式二）：按取件码直接获取原文',
         params=[_p('key', '取件码', 'text', True, '...')],
         test_params=None,
         doc='https://uapis.cn/docs/api-reference/get-clipzy-raw'),
]

# ===================== V10.11.51 官方 OpenAPI 校正表 =====================
# 依据：https://uapis.cn/openapi.json（OpenAPI 3.1.0，2026-11-03 全量逐条核对）
# 设计原则：不改动上方 110 条原始定义（保留历史可追溯），在读取时按本表校正，零破坏可回滚。
#   1) API_OVERRIDES：修正路径/方法/文件型标记/隐藏重复项
#   2) PARAM_RENAME：本地参数名 → 官方参数名（官方契约优先，test_params 同步改名）
#   3) PARAM_DROP：确认无效的本地参数（官方规范中不存在且非兼容别名）
#   4) PARAM_AUGMENT：补齐官方有、本地缺的参数（按官方顺序追加）

API_OVERRIDES = {
    # —— 方法与路径错误（原定义会 404 或方法不被接受）——
    'text_md5': {'method': 'POST'},                       # 官方仅 POST /text/md5
    'answerbook_ask': {'method': 'POST'},                   # 官方仅 POST /answerbook/ask
    'text_aes_encrypt_advanced': {'path': '/text/aes/encrypt-advanced'},
    'text_aes_decrypt_advanced': {'path': '/text/aes/decrypt-advanced'},
    'sensitive_word_quick_check': {'path': '/text/profanitycheck'},
    'web_to_markdown_async': {'path': '/web/tomarkdown/async'},
    'web_tomarkdown_async_status': {'path': '/web/tomarkdown/async/{task_id}'},
    'food_recipe_detail': {'path': '/food/recipe/detail'},
    'food_ingredient_detail': {'path': '/food/ingredient/detail'},
    'clipzy_store': {'path': '/api/store'},
    'clipzy_get': {'path': '/api/get'},
    'clipzy_raw': {'path': '/api/raw/{id}'},
    # —— 文件型标记校正（multipart 上传，试验台与一键测试不支持）——
    'image_svg': {'file_type': True},                      # 官方为 multipart/form-data
    'image_speechless': {'file_type': False},               # 官方为 application/json，可在线测试
    # —— 与官方 POST 版本重复的本地条目（目录中隐藏，保留定义避免旧引用失效）——
    'text_md5_post': {'hidden': True},
    'answerbook_ask_post': {'hidden': True},
}

# 本地参数名 → 官方参数名（仅列确认不一致的；兼容别名如 translate 的 fromLang 不在此列）
PARAM_RENAME = {
    'github_user': {'username': 'user'},
    'translate_text': {'toLang': 'to_lang'},
    'ai_translate': {'to': 'target_lang'},
    'dictionary_suggest': {'word': 'q'},
    'sensitive_word_analyze': {'text': 'keyword'},
    'sensitive_word_analyze_query': {'text': 'keyword'},
    'misc_district': {'name': 'keywords'},
    'misc_movie_rating_rank': {'type': 'period'},
    'watermark_producer_code': {'type': 'subject_type'},
    'social_bilibili_archives': {'uid': 'mid', 'page': 'pn'},
    'social_bilibili_replies': {'aid': 'oid', 'page': 'pn'},
    'clipzy_store': {'text': 'compressedData'},
}

# 确认无效的本地参数（官方规范无此参数且无兼容说明）
PARAM_DROP = {
    'image_svg': ['svg'],                    # 官方改为 multipart 文件上传
    'social_bilibili_replies': ['bvid'],     # 官方仅支持 oid / aid 语义的评论区 ID
    'misc_weather_history': ['date'],        # 官方改为 start_date / end_date
    'food_ingredient_detail': ['id'],        # 官方改为 name / code 二选一
    'clipzy_get': ['key'],                   # 官方参数名为 id
    'clipzy_raw': ['key'],                   # 官方参数名为 id
}

# 预置测试参数校正（None = 无可靠预置值，一键测试引导走试验台手填）
TEST_PARAMS_OVERRIDES = {
    'food_ingredient_detail': {'name': '小白菜'},
    'clipzy_store': None,                    # compressedData 需 LZString 压缩后的真实串，无法预置
    'social_bilibili_replies': None,         # oid 需真实评论区 ID
}

# 官方有、本地缺的参数（按接口补齐；已在上方重命名中覆盖的不重复列）
PARAM_AUGMENT = {
    'misc_hotboard': [
        _p('time', '时光机时间点', 'datetime', convert='timestamp_ms'),
        _p('keyword', '搜索关键词（配合起止时间）'),
        _p('time_start', '搜索起始时间', 'datetime', convert='timestamp_ms'),
        _p('time_end', '搜索结束时间', 'datetime', convert='timestamp_ms'),
        _p('limit', '搜索返回条数上限（默认 50）', 'number'),
    ],
    'misc_lunartime': [
        _p('timezone', '时区（如 Asia/Shanghai）', example='Asia/Shanghai'),
    ],
    'misc_randomnumber': [
        _p('count', '生成数量', 'number', False, '5'),
        _p('allow_repeat', '允许出现重复值', 'bool'),
        _p('allow_decimal', '允许生成小数', 'bool'),
        _p('decimal_places', '小数位数', 'number', False, '2'),
    ],
    'misc_holiday_calendar': [
        _p('timezone', '时区（默认 Asia/Shanghai）', example='Asia/Shanghai'),
        _p('nearby_limit', '邻近节日数量上限（默认 7）', 'number', False, '7'),
    ],
    'misc_district': [
        _p('lat', '纬度（与 lng 配合反查）', 'number', False, '39.9'),
        _p('lng', '经度（与 lat 配合反查）', 'number', False, '116.4'),
        _p('level', '行政级别', 'select', False, '', ['province', 'city', 'district', 'street']),
        _p('country', '国家代码', example='CN'),
        _p('limit', '返回数量上限（默认 20）', 'number', False, '20'),
    ],
    'misc_date_diff': [
        _p('format', '日期格式（可选）', example='YYYY-MM-DD'),
    ],
    'misc_weather_history': [
        _p('adcode', '6 位行政区划代码', example='110000'),
        _p('start_date', '起始日期', 'date', False, '2026-05-01'),
        _p('end_date', '结束日期', 'date', False, '2026-05-31'),
        _p('days', '回看天数（1-366）', 'number', False, '30'),
        _p('lang', '返回语言', 'select', False, '', ['zh', 'en']),
    ],
    'misc_movie_rating_rank': [
        _p('channel', '渠道', 'select', False, '', ['all', 'tv', 'web', 'cinema']),
        _p('platform', '平台关键词（如 爱奇艺）', example='爱奇艺'),
        _p('limit', '每渠道返回条数', 'number', False, '10'),
        _p('date', '历史快照日期', 'date'),
    ],
    'saying_random': [
        _p('scene', '推荐场景（mode=recommend 必填）', 'select', False, '',
           ['dawn', 'morning', 'noon', 'afternoon', 'evening', 'night', 'deep-night',
            'work', 'coding', 'meeting', 'relax', 'emo', 'philosophy']),
        _p('source', '语料来源', 'select', False, '',
           ['caoxingyu sentence', 'english historical quotes', 'quotable', 'sentences bundle']),
        _p('category', '分类', 'select', False, '',
           ['诗词', '古诗文', '文学', '哲学', '影视', '动画', '漫画', '游戏', '网络',
            '网易云', '抖机灵', '原创', '其他']),
        _p('tag', '标签', 'select', False, '',
           ['emo', '励志', '治愈', '温柔', '热血', '哲理', '禅意', '爱情', '友情', '离别',
            '相思', '怀旧', '成长', '工作', '编码', '放松', '幽默', '深夜', '清晨']),
    ],
    'text_aes_decrypt': [
        _p('nonce', 'IV/Nonce（16 字符）', example='1234567890abcdef'),
    ],
    'text_aes_encrypt_advanced': [
        _p('padding', '填充方式', 'select', False, 'PKCS7', ['PKCS7', 'ZERO', 'NONE']),
        _p('output_format', '输出格式', 'select', False, 'base64', ['base64', 'hex']),
    ],
    'text_aes_decrypt_advanced': [
        _p('padding', '填充方式（须与加密时一致）', 'select', False, 'NONE',
           ['PKCS7', 'ZERO', 'NONE']),
    ],
    'text_markdown_to_html': [
        _p('format', '响应格式', 'select', False, 'json', ['json', 'html']),
        _p('sanitize', '过滤风险脚本（默认开启）', 'bool'),
    ],
    'text_markdown_to_pdf': [
        _p('theme', '排版主题', 'select', False, 'github',
           ['github', 'minimal', 'light', 'dark']),
        _p('paper_size', '纸张大小', 'select', False, 'A4', ['A4', 'Letter']),
    ],
    'text_convert': [
        _p('options', '扩展选项（预留，当前未使用）'),
    ],
    'watermark_producer_code': [
        _p('binding', '证件类型', 'select', False, '',
           ['uscc', 'id', 'phone', 'passport', 'netid']),
        _p('identifier', '证件号', example='13800138000'),
        _p('service_type', '服务角色', 'select', False, '', ['generation', 'propagation']),
        _p('model_code', '4 位模型/应用码', example='0001'),
        _p('code', '待校验的 27 位编码'),
    ],
    'social_bilibili_liveroom': [
        _p('mid', '主播 MID（与 room_id 二选一）', example='672328094'),
    ],
    'social_bilibili_archives': [
        _p('keywords', '搜索关键词'),
        _p('orderby', '排序方式', 'select', False, 'pubdate', ['pubdate', 'views']),
        _p('ps', '每页条数（默认 20）', 'number', False, '20'),
    ],
    'social_bilibili_videoinfo': [
        _p('aid', 'AV 号（与 bvid 二选一）', example='75836761'),
    ],
    'social_bilibili_replies': [
        _p('sort', '排序方式', 'select', False, 'hot', ['time', 'like', 'reply', 'hot']),
        _p('ps', '每页条数（1-20）', 'number', False, '5'),
    ],
    'github_user': [
        _p('activity', '包含贡献活动数据', 'bool'),
        _p('activity_scope', '活动数据范围', 'select', False, '', ['all', 'organization']),
        _p('org', '组织登录名'),
        _p('pinned', '包含置顶仓库', 'bool'),
        _p('repos', '包含公开仓库列表', 'bool'),
        _p('repos_limit', '仓库数量上限', 'number'),
    ],
    'network_whois': [
        _p('format', '返回格式', 'select', False, 'text', ['text', 'json']),
    ],
    'network_portscan': [
        _p('protocol', '扫描协议', 'select', False, 'tcp', ['tcp', 'udp']),
    ],
    'dictionary_lookup': [
        _p('lang', '目标语种', 'select', False, 'en', ['en']),
        _p('engine', '查询引擎（local=高速模式）', 'select', False, '', ['local']),
    ],
    'dictionary_audio': [
        _p('accent', '口音', 'select', False, 'uk', ['uk', 'us']),
    ],
    'dictionary_suggest': [
        _p('limit', '候选词数量（默认 10）', 'number', False, '10'),
    ],
    'random_image': [
        _p('category', '图片分类', 'select', False, 'acg',
           ['acg', 'landscape', 'anime', 'pc_wallpaper', 'mobile_wallpaper',
            'general_anime', 'ai_drawing', 'bq', 'furry']),
    ],
    'random_string': [
        _p('type', '字符类型', 'select', False, 'alphanumeric',
           ['numeric', 'lower', 'upper', 'alpha', 'alphanumeric', 'hex']),
    ],
    'game_steam_summary': [
        _p('id', 'Steam 自定义 URL 名', example='gabelogannewell'),
        _p('id3', 'Steam ID3', example='STEAM_0:0:22202'),
        _p('key', 'Steam API Key（可选）'),
    ],
    'game_minecraft_historyid': [
        _p('uuid', '玩家 UUID', example='ee9b4ed1-aac1-491e-b761-1471be374b80'),
    ],
    'game_steam_servers': [
        _p('name', '服务器名称关键词', example='SCUM'),
        _p('limit', '返回数量上限（默认 20）', 'number', False, '20'),
    ],
    'game_minecraft_mods': [
        _p('source', '搜索来源', 'select', False, 'all', ['all', 'modrinth', 'spigotmc']),
        _p('type', '资源类型（mod/plugin）', example='mod'),
        _p('limit', '每来源条数（默认 10）', 'number', False, '10'),
        _p('enrich', '补全下载直链与作者（默认开启）', 'bool'),
    ],
    'ai_translate': [
        _p('source_lang', '源语言代码（留空自动检测）', example='en'),
        _p('style', '翻译风格', 'select', False, 'professional',
           ['casual', 'professional', 'academic', 'literary']),
        _p('context', '场景', 'select', False, 'general',
           ['general', 'business', 'technical', 'medical', 'legal',
            'marketing', 'entertainment', 'education', 'news']),
        _p('preserve_format', '保留原文格式', 'bool'),
    ],
    'status_usage': [
        _p('path', '端点路径（可选，如 /api/v1/image/motou）', example='/api/v1/image/motou'),
    ],
    'image_bing_daily': [
        _p('date', '壁纸日期（仅近 8 天）', 'date'),
        _p('random', '随机返回历史壁纸', 'bool'),
        _p('market', '壁纸地区', 'select', False, 'zh-CN',
           ['zh-CN', 'en-US', 'ja-JP', 'en-GB', 'de-DE', 'en-CA', 'en-IN',
            'fr-FR', 'fr-CA', 'it-IT', 'es-ES', 'pt-BR']),
        _p('format', '响应格式', 'select', False, 'image', ['image', 'json', 'redirect']),
    ],
    'image_qrcode': [
        _p('size', '边长（256-2048 像素）', 'number', False, '512'),
        _p('format', '响应格式', 'select', False, 'image', ['image', 'json', 'json_url']),
        _p('transparent', '透明背景', 'bool'),
        _p('fgcolor', '前景色（#RRGGBB）'),
        _p('bgcolor', '背景色（#RRGGBB）'),
    ],
    'avatar_gravatar': [
        _p('hash', '邮箱小写 MD5（优先于 email）'),
        _p('s', '尺寸（1-2048 像素）', 'number'),
        _p('d', '默认头像类型（mp/identicon/monsterid…）', 'select', False, 'mp',
           ['mp', 'identicon', 'monsterid', 'wavatar', 'retro', 'robohash', 'blank']),
        _p('r', '头像分级', 'select', False, 'g', ['g', 'pg', 'r', 'x']),
    ],
    'image_bing_daily_history': [
        _p('resolution', '分辨率', 'select', False, '4k', ['4k', '1080']),
        _p('page_size', '每页条数（默认 30）', 'number', False, '10'),
    ],
    'image_svg': [
        _p('format', '输出格式', 'select', False, 'png',
           ['png', 'jpeg', 'jpg', 'gif', 'tiff', 'bmp']),
        _p('width', '输出宽度（像素）', 'number'),
        _p('height', '输出高度（像素）', 'number'),
        _p('quality', 'JPEG 质量（1-100）', 'number'),
    ],
    'search_aggregate': [
        _p('site', '限定站点（不含 site: 前缀）'),
        _p('filetype', '限定文件类型（pdf/doc/xls…）'),
        _p('fetch_full', '抓取完整正文（较慢）', 'bool'),
        _p('sort', '排序方式', 'select', False, 'relevance', ['relevance', 'date']),
        _p('time_range', '时间范围', 'select', False, '',
           ['day', 'week', 'month', 'year']),
    ],
    'execution_run': [
        _p('stdin', '标准输入内容（≤65536 字节）'),
        _p('timeout_ms', '执行超时（毫秒，1-30000）', 'number', False, '10000'),
        _p('network', '沙盒网络策略（默认 offline 断网）', example='offline'),
        _p('packs', '加载依赖包（如 python-libs）', example='python-libs'),
    ],
    'daily_word': [
        _p('date', '日期（作为每日种子）', 'date'),
        _p('seed', '固定种子（可复现，与 date 互斥）', 'number'),
    ],
    'food_ingredient': [
        _p('page', '页码（1-100）', 'number', False, '1'),
    ],
    'food_ingredient_detail': [
        _p('name', '食材名称（与 code 二选一）', example='小白菜'),
        _p('code', '食材编码（与 name 二选一）'),
    ],
    'image_speechless': [
        _p('top_text', '上方文字（默认“你们怎么不说话了”）'),
        _p('bottom_text', '下方文字（默认“求求你______”）'),
    ],
    'ai_models': [
        _p('q', '搜索关键词（ID/名称/厂商/描述）'),
        _p('provider', '厂商过滤（逗号分隔多选）', example='deepseek,openai'),
        _p('type', '用途类型', 'select', False, '',
           ['language', 'embedding', 'reranking', 'image', 'video', 'speech',
            'transcription', 'ocr']),
        _p('modality', '模态', 'select', False, '',
           ['text', 'image', 'audio', 'video', 'file', 'pdf']),
        _p('capability', '进阶能力', 'select', False, '',
           ['reasoning', 'tools', 'structured_output', 'web_search', 'long_context']),
        _p('sort', '排序字段', 'select', False, '',
           ['released_at', 'name', 'provider', 'context_window']),
        _p('order', '排序方向', 'select', False, 'asc', ['asc', 'desc']),
        _p('page', '页码（默认 1）', 'number', False, '1'),
        _p('limit', '返回上限（0=不限）', 'number', False, '100'),
    ],
    'clipzy_store': [
        _p('ttl', '留存秒数（-1 永久，默认 3600）', 'number', False, '3600'),
    ],
    'clipzy_get': [
        _p('id', '片段 ID', 'text', True, 'PREF0Zv8Yj'),
    ],
    'clipzy_raw': [
        _p('id', '片段 ID', 'text', True, 'PREF0Zv8Yj'),
    ],
}


def _apply_correction(api):
    """按校正表生成 API 副本（不修改模块级原始定义，保证历史可追溯与可回滚）"""
    out = dict(api)
    fix = API_OVERRIDES.get(api['id'])
    if fix:
        out.update(fix)
    params = [dict(p) for p in (api.get('params') or [])]
    drops = set(PARAM_DROP.get(api['id']) or [])
    rename = PARAM_RENAME.get(api['id']) or {}
    params = [p for p in params if p['name'] not in drops]
    for p in params:
        if p['name'] in rename:
            p['name'] = rename[p['name']]
    existing = {p['name'] for p in params}
    for extra in (PARAM_AUGMENT.get(api['id']) or []):
        if extra['name'] not in existing:
            params.append(dict(extra))
            existing.add(extra['name'])
    out['params'] = params
    # 预置测试参数同步改名/剔除，避免提交旧参数名
    tp = dict(api.get('test_params') or {})
    if tp:
        for old, new in rename.items():
            if old in tp:
                tp[new] = tp.pop(old)
        for name in drops:
            tp.pop(name, None)
        out['test_params'] = tp
    if api['id'] in TEST_PARAMS_OVERRIDES:
        out['test_params'] = TEST_PARAMS_OVERRIDES[api['id']]
    return out


_CORRECTED_APIS = [_apply_correction(a) for a in APIS]

# ===================== 业务组绑定（组内 uapis 端点 → 目录 API 的协议映射） =====================
# 天气预报组/节假日组的端点可标记 platform=uapis；标记后按此处映射的 API 协议调用与测试。
# geocoding/air_quality 组无独立对应 API（uapis 天气一步到位无需地理编码；AQI 含在 extended 中），不做绑定。

API_GROUP_BINDINGS = {
    'forecast': 'misc_weather',      # 天气·天气预报组 → uapis 查询天气
    'holiday': 'misc_holiday_calendar',  # 法定节假日组 → uapis 节假日与万年历
    'saying': 'saying',                  # 每日一言组 → uapis 一言（可自由切换直连/平台）
}

# ===================== 索引与查询函数 =====================

_APIS_BY_ID = {a['id']: a for a in _CORRECTED_APIS}


def get_api(api_id):
    """按内部 ID 获取单条 API 定义（已应用 V10.11.51 官方 OpenAPI 校正；无此 ID 返回 None）"""
    return _APIS_BY_ID.get(api_id)


def get_group_api(group):
    """按业务组键获取绑定的目录 API（无绑定返回 None）"""
    api_id = API_GROUP_BINDINGS.get(group)
    return _APIS_BY_ID.get(api_id) if api_id else None


def get_catalog_for_frontend():
    """供配置页面/API 目录渲染：按分类分组的完整目录（含分类中文名与图标）
    V10.11.51：使用官方 OpenAPI 校正后的定义，并过滤 hidden 的重复条目"""
    grouped = []
    for cat_key, cat_name, icon in CATEGORIES:
        items = [dict(a) for a in _CORRECTED_APIS if a['cat'] == cat_key and not a.get('hidden')]
        if not items:
            continue
        grouped.append({
            'key': cat_key, 'name': cat_name, 'icon': icon, 'apis': items,
            'free_count': sum(1 for a in items if a.get('credits') == 0),
        })
    return grouped


def build_full_url(api_id, base_url=None, params=None):
    """拼接完整请求 URL：base_url（默认平台配置值）+ API 路径
    V10.11.51：支持路径占位符（如 /api/raw/{id}、/web/tomarkdown/async/{task_id}），
    传入 params 时按同名参数替换并返回（调用方需将路径参数从 query 中剔除）"""
    api = get_api(api_id)
    if not api:
        return None
    base = (base_url or UAPI_DEFAULT_BASE_URL).rstrip('/')
    path = api['path']
    if params:
        import re as _re
        for ph in _re.findall(r'\{(\w+)\}', path):
            if ph in params and params[ph] not in (None, ''):
                path = path.replace('{' + ph + '}', str(params[ph]))
    return base + path


def path_param_names(api_id):
    """返回该 API 路径中的占位符参数名集合（调用方用于从 query 中剔除）"""
    api = get_api(api_id)
    if not api:
        return set()
    import re as _re
    return set(_re.findall(r'\{(\w+)\}', api.get('path') or ''))


def summary():
    """目录统计（页面提示条用；基于校正后定义）"""
    visible = [a for a in _CORRECTED_APIS if not a.get('hidden')]
    total = len(visible)
    free = sum(1 for a in visible if a.get('credits') == 0)
    cats = len([c for c in CATEGORIES if any(a['cat'] == c[0] for a in visible)])
    testable = sum(1 for a in visible if a.get('test_params') is not None and not a.get('file_type'))
    return {'total': total, 'free': free, 'categories': cats, 'testable': testable}
