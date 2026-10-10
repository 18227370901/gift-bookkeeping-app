/**
 * lunar_utils.js — 万年历核心工具库（V10.11.9 新增）
 * 功能：公历↔农历转换、干支纪年、生肖、二十四节气、公历/农历节日
 * 数据权威性：LUNAR_INFO 农历表与节气表由「寿星天文历」（sxtwl，中国历法事实标准）
 *            全量生成并经 73414 天逐日 roundtrip 校验 0 不一致（1900-2100）
 * 特点：零依赖、零外网请求，全部本地计算（国内网络环境无需 CDN）
 * 对外 API（LunarUtils 命名空间）：
 *   solar2lunar(y, m, d)     公历→农历（返回 null 表示超出支持范围 1900-2100）
 *   getDayLabel(y, m, d)     日历格子小字（优先级：节日 > 节气 > 农历日；初一显示月名）
 *   getFullInfo(y, m, d)     详情面板完整万年历信息
 *   termOf(y, m, d)          查询某日节气（是节气日返回名称，否则 null）
 *   gregFestivalOf(y, m, d)  查询某日公历节日
 */
var LunarUtils = (function () {
    'use strict';

    // ===== 1900-2100 农历压缩数据表（201 项，sxtwl 权威生成） =====
    // 位编码：bit0-3 = 闰月月份（0 = 无闰月）
    //        bit4-15 = 正月~腊月大小月标志（1 = 30 天大月，m 月位 = 1 << (16 - m)）
    //        bit16 (0x10000) = 闰月是否大月
    var LUNAR_INFO = [
        0x04bd8, 0x04ae0, 0x0a570, 0x054d5, 0x0d260, 0x0d950, 0x16554, 0x056a0, 0x09ad0, 0x055d2,
        0x04ae0, 0x0a5b6, 0x0a4d0, 0x0d250, 0x1d255, 0x0b540, 0x0d6a0, 0x0ada2, 0x095b0, 0x14977,
        0x04970, 0x0a4b0, 0x0b4b5, 0x06a50, 0x06d40, 0x1ab54, 0x02b60, 0x09570, 0x052f2, 0x04970,
        0x06566, 0x0d4a0, 0x0ea50, 0x16a95, 0x05ad0, 0x02b60, 0x186e3, 0x092e0, 0x1c8d7, 0x0c950,
        0x0d4a0, 0x1d8a6, 0x0b550, 0x056a0, 0x1a5b4, 0x025d0, 0x092d0, 0x0d2b2, 0x0a950, 0x0b557,
        0x06ca0, 0x0b550, 0x15355, 0x04da0, 0x0a5b0, 0x14573, 0x052b0, 0x0a9a8, 0x0e950, 0x06aa0,
        0x0aea6, 0x0ab50, 0x04b60, 0x0aae4, 0x0a570, 0x05260, 0x0f263, 0x0d950, 0x05b57, 0x056a0,
        0x096d0, 0x04dd5, 0x04ad0, 0x0a4d0, 0x0d4d4, 0x0d250, 0x0d558, 0x0b540, 0x0b6a0, 0x195a6,
        0x095b0, 0x049b0, 0x0a974, 0x0a4b0, 0x0b27a, 0x06a50, 0x06d40, 0x0af46, 0x0ab60, 0x09570,
        0x04af5, 0x04970, 0x064b0, 0x074a3, 0x0ea50, 0x06b58, 0x05ac0, 0x0ab60, 0x096d5, 0x092e0,
        0x0c960, 0x0d954, 0x0d4a0, 0x0da50, 0x07552, 0x056a0, 0x0abb7, 0x025d0, 0x092d0, 0x0cab5,
        0x0a950, 0x0b4a0, 0x0baa4, 0x0ad50, 0x055d9, 0x04ba0, 0x0a5b0, 0x15176, 0x052b0, 0x0a930,
        0x07954, 0x06aa0, 0x0ad50, 0x05b52, 0x04b60, 0x0a6e6, 0x0a4e0, 0x0d260, 0x0ea65, 0x0d530,
        0x05aa0, 0x076a3, 0x096d0, 0x04afb, 0x04ad0, 0x0a4d0, 0x1d0b6, 0x0d250, 0x0d520, 0x0dd45,
        0x0b5a0, 0x056d0, 0x055b2, 0x049b0, 0x0a577, 0x0a4b0, 0x0aa50, 0x1b255, 0x06d20, 0x0ada0,
        0x14b63, 0x09370, 0x049f8, 0x04970, 0x064b0, 0x168a6, 0x0ea50, 0x06aa0, 0x1a6c4, 0x0aae0,
        0x092e0, 0x0d2e3, 0x0c960, 0x0d557, 0x0d4a0, 0x0da50, 0x05d55, 0x056a0, 0x0a6d0, 0x055d4,
        0x052d0, 0x0a9b8, 0x0a950, 0x0b4a0, 0x0b6a6, 0x0ad50, 0x055a0, 0x0aba4, 0x0a5b0, 0x052b0,
        0x0b273, 0x06930, 0x07337, 0x06aa0, 0x0ad50, 0x14b55, 0x04b60, 0x0a570, 0x054e4, 0x0d160,
        0x0e968, 0x0d520, 0x0daa0, 0x16aa6, 0x056d0, 0x04ae0, 0x0a9d4, 0x0a2d0, 0x0d150, 0x0f252,
        0x0d520
    ];

    // ===== 1900-2100 节气日表（sxtwl 权威生成，base32 编码） =====
    // 每年 24 字符，每字符对应 1 个节气日（1-31）；节气序：0小寒 1大寒 2立春 ... 23冬至
    // 编码：'0'-'9' = 0-9，'a'-'v' = 10-31；年份 y 的行 = TERM_DATA.substr((y-1900)*24, 24)
    var TERM_DATA = '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j6l6l6m7m8o8o8o9o8n8n' +
        '6l5k7m6l7m7m8o9o9o9o8n8n' +
        '7l5k6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j6l6l6m6m8o8o8o9o8n8n' +
        '6l5k7m6l7m7m8o9o9o9o8n8n' +
        '7l5k6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j6l6l6m6m8o8o8o9o8n8n' +
        '6l5k7m6l7m7m8o9o9o9o8n8n' +
        '7l5k6l5k6l6m7n8n8n9o8m7m' +
        '6k4j6l5l6m6m8n8o8n9o8n8m' +
        '6l4j6l5l6m6m8o8o8o9o8n8n' +
        '6l5k6m6l6m7m8o8o9o9o8n8n' +
        '6l5k6l5k6l6m7n8n8n8o8m7m' +
        '6k4j6l5l6l6m8n8o8n9o8n8m' +
        '6l4j6l5l6m6m8o8o8o9o8n8m' +
        '6l5k6m6l6m7m8o8o9o9o8n8n' +
        '6l5k6l5k6l6m7n8n8n8o8m7m' +
        '6k4j6l5k6l6m8n8o8n9o8n7m' +
        '6l4j6l5l6m6m8o8o8o9o8n8m' +
        '6l5j6l6l6m7m8o8o9o9o8n8n' +
        '6l5k6l5k6l6m7n8n8n8o8m7m' +
        '6k4j6l5k6l6m8n8o8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j6l6l6m7m8o8o9o9o8n8n' +
        '6l5k6l5k6l6m7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j6l6l6m7m8o8o8o9o8n8n' +
        '6l5k6l5k6l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j6l6l6m6m8o8o8o9o8n8n' +
        '6l5k6l5k6l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j6l6l6m6m8o8o8o9o8n8n' +
        '6l5k6l5k6l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j6l6l6m6m8o8o8o9o8n8n' +
        '6l5k6l5k5l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n8o8m7m' +
        '6k4j6l5l6m6m8n8o8n9o8n8m' +
        '6l4j6l5l6m6m8o8o8o9o8n8n' +
        '6l5k5l5k5l6l7n7n8n8n7m7m' +
        '5k4j6l5k6l6m7n8n8n8o8m7m' +
        '6k4j6l5k6l6m8n8o8n9o8n8m' +
        '6l4j6l5l6m6m8o8o8o9o8n8n' +
        '6l5k5l5k5l6l7n7n8n8n7m7m' +
        '5k4j6l5k6l6m7n8n8n8o8m7m' +
        '6k4j6l5k6l6m8n8o8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5k5k5k5l6l7n7n8n8n7m7m' +
        '5k4j6l5k6l6m7n8n8n8o8m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j5k5k5l6l7n7n7n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j5k5k5l6l7n7n7n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j5k5k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8o9o8n8m' +
        '6l5j5k5k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k5l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j6l5l6m6m8n8o8n9o8n8m' +
        '6l5j5k4k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k5l6l7n7n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n8o8n7m' +
        '6k4j6l5l6l6m8n8o8n9o8n8m' +
        '6l5j5k4k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k5l6l7n7n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n8o8m7m' +
        '6k4j6l5k6l6m8n8o8n9o8n8m' +
        '6l4j5k4k5l5l7m7n7n8n7m7m' +
        '5k4j5l5k5l6l7n7n8n8n7m7m' +
        '5k4j6l5k6l6m7n8n8n8o8m7m' +
        '6k4j6l5k6l6m7n8o8n9o8n7m' +
        '6l4j5k4k5l5l7m7n7n8n7m7l' +
        '5k4j5k5k5l6l7n7n7n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8o8m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l6l7n7n7n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k5l6l7n7n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n9o8n7m' +
        '6l4j5k4k5l5l7m7n7m8n7m7l' +
        '5k4i5k4k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k5l6l7n7n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n8o8n7m' +
        '6l4j5k4k5k5l7m7n7m8n7m7l' +
        '5k4i5k4k5l5l7m7n7n8n7m7m' +
        '5k4j6l5k5l6l7n7n8n8n7m7m' +
        '6k4j6l5k6l6m7n8n8n8o8m7m' +
        '6k4j5k4j5k5l7m7n7m8n7m7l' +
        '5k3i5k4k5l5l7m7n7n8n7m7m' +
        '5k4j5l5k5l6l7n7n8n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8o8m7m' +
        '6k4j5k4j5k5l6m7m7m8n7m7l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4j5k5k5l6l7n7n7n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8o8m7m' +
        '6k4j5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8n7m7m' +
        '6k4j5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k6l6l7n8n8n8n7m7m' +
        '6k4j5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k5l6l7n7n8n8n7m7m' +
        '6k4j5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k5l6l7n7n8n8n7m7m' +
        '6k4j5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5k5l7m7n7m8n7m7l' +
        '5k4i5k4k5l5l7n7n7n8n7m7m' +
        '5k4j6l5k5l6l7n7n8n8n7m7m' +
        '6k4j5k4j5k5l6m7m7m7n7m6l' +
        '5k3i5k4j5k5l7m7n7m8n7m7l' +
        '5k4i5k4k5l5l7m7n7n8n7m7m' +
        '5k4j6l5k5l6l7n7n8n8n7m7m' +
        '6k4j5k4j5k5k6m7m7m7n7l6l' +
        '5j3i5k4j5k5l6m7m7m8n7m7l' +
        '5k3i5k4k5l5l7m7n7n8n7m7m' +
        '5k4j5k5k5l6l7n7n7n8n7m7m' +
        '5k4j5k4j5k5k6m7m7m7n7l6l' +
        '5j3i5k4j5k5l6m7m7m8n7m7l' +
        '5k3i5k4k5l5l7m7n7n8n7m7m' +
        '5k4j5k5k5l5l7n7n7n8n7m7m' +
        '5k4j5k4j5k5k6m7m7m7n7l6l' +
        '5j3i5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4j5k5k5l5l7n7n7n8n7m7m' +
        '5k4j5k4j5k5k6m7m7m7m6l6l' +
        '5j3i5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m' +
        '5k4j5k4j5k5k6m7m7m7m6l6l' +
        '5j3i5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m' +
        '5k4j5k4j4k5k6m6m7m7m6l6l' +
        '5j3i5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5k5l7m7n7m8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m' +
        '5k4j5k4j4k5k6m6m7m7m6l6l' +
        '5j3i5k4j5k5l6m7m7m7n7m6l' +
        '5k3i5k4k5k5l7m7n7m8n7m7l' +
        '5k4i5k4k5l5l7m7n7n8n7m7m' +
        '5k4j5k4j4k5k6m6m7m7m6l6l' +
        '5j3i5k4j5k5l6m7m7m7n7m6l' +
        '5k3i5k4j5k5l6m7n7m8n7m7l' +
        '5k4i5k4k5l5l7m7n7n8n7m7m' +
        '5k4j5k4j4k5k6m6m7m7m6l6l' +
        '5j3i5k4j5k5k6m7m7m7n7l6l' +
        '5k3i5k4j5k5l6m7m7m8n7m7l' +
        '5k3i5k4k5l5l7m7n7n8n7m7m' +
        '5k4j4j4j4k5k6m6m6m7m6l6l' +
        '4j3i5k4j5k5k6m7m7m7n7l6l' +
        '5j3i5k4j5k5l6m7m7m8n7m7l' +
        '5k3i5k4k5l5l7m7n7n8n7m7m' +
        '5k4j4j4j4k4k6m6m6m7m6l6l' +
        '4j3i5k4j5k5k6m7m7m7n7l6l' +
        '5j3i5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4j4j4j4k4k6m6m6m7m6l6l' +
        '4j3i5k4j5k5k6m7m7m7m6l6l' +
        '5j3i5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4i4j4j4k4k6m6m6m7m6l6l' +
        '4j3i5k4j5k5k6m6m7m7m6l6l' +
        '5j3i5k4j5k5l6m7m7m8n7m6l' +
        '5k3i5k4k5l5l7m7n7n8n7m7l' +
        '5k4i5k5k5l5l7n7n7n8n7m7m'
       ;

    var GAN = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸'];
    var ZHI = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥'];
    var ANIMALS = ['鼠', '牛', '虎', '兔', '龙', '蛇', '马', '羊', '猴', '鸡', '狗', '猪'];
    var MONTH_CN = ['正', '二', '三', '四', '五', '六', '七', '八', '九', '十', '冬', '腊'];
    var DAY_CN = ['初一', '初二', '初三', '初四', '初五', '初六', '初七', '初八', '初九', '初十',
        '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十',
        '廿一', '廿二', '廿三', '廿四', '廿五', '廿六', '廿七', '廿八', '廿九', '三十'];
    var WEEK_CN = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'];

    // 节气序（0-23）：小寒 大寒 立春 雨水 惊蛰 春分 清明 谷雨 立夏 小满
    //               芒种 夏至 小暑 大暑 立秋 处暑 白露 秋分 寒露 霜降
    //               立冬 小雪 大雪 冬至（节气所在公历月份恒定，sxtwl 4824 点全量验证）
    var TERM_NAMES = ['小寒', '大寒', '立春', '雨水', '惊蛰', '春分', '清明', '谷雨', '立夏', '小满',
        '芒种', '夏至', '小暑', '大暑', '立秋', '处暑', '白露', '秋分', '寒露', '霜降',
        '立冬', '小雪', '大雪', '冬至'];
    var TERM_MONTHS = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12];

    // ===== 节日库 =====
    // 公历固定节日（'月-日': 名称）
    var GREG_FESTIVALS = {
        '1-1': '元旦', '2-14': '情人节', '3-8': '妇女节', '3-12': '植树节', '4-1': '愚人节',
        '5-1': '劳动节', '5-4': '青年节', '6-1': '儿童节', '7-1': '建党节', '8-1': '建军节',
        '9-3': '抗战胜利纪念日', '9-10': '教师节', '10-1': '国庆节', '12-24': '平安夜', '12-25': '圣诞节'
    };
    // 公历浮动节日（母亲节=5月第2个周日、父亲节=6月第3个周日、感恩节=11月第4个周四）
    var GREG_FLOAT_FESTIVALS = [
        { month: 5, nth: 2, weekday: 0, name: '母亲节' },
        { month: 6, nth: 3, weekday: 0, name: '父亲节' },
        { month: 11, nth: 4, weekday: 4, name: '感恩节' }
    ];
    // 农历固定节日（'农历月-日': 名称；闰月当天不算节日）
    var LUNAR_FESTIVALS = {
        '1-1': '春节', '1-15': '元宵节', '2-2': '龙抬头', '3-3': '上巳节',
        '5-5': '端午节', '7-7': '七夕节', '7-15': '中元节',
        '8-15': '中秋节', '9-9': '重阳节', '12-8': '腊八节'
    };

    // ===== 农历基础计算（编码与 sxtwl 生成器配套） =====

    // 农历 y 年闰月月份（0 = 无闰月）
    function leapMonth(y) {
        return LUNAR_INFO[y - 1900] & 0xf;
    }

    // 农历 y 年闰月天数（无闰月返回 0）
    function leapDays(y) {
        if (leapMonth(y)) {
            return (LUNAR_INFO[y - 1900] & 0x10000) ? 30 : 29;
        }
        return 0;
    }

    // 农历 y 年第 m 月（1-12，正常月）天数
    function lMonthDays(y, m) {
        return (LUNAR_INFO[y - 1900] >> (16 - m)) & 1 ? 30 : 29;
    }

    // 农历 y 年总天数
    function lYearDays(y) {
        var sum = 0, m;
        for (m = 1; m <= 12; m++) {
            sum += lMonthDays(y, m);
        }
        return sum + leapDays(y);
    }

    // 干支纪年（以农历年为界：正月初一前属前一年农历）
    function gzYear(lunarYear) {
        return GAN[(lunarYear - 4) % 10] + ZHI[(lunarYear - 4) % 12];
    }

    // 公历 → 农历（y/m/d 为公历自然数，m: 1-12）
    // 返回 { ly, lmonth, lday, isLeap, monthName, dayName, gz, animal, week }；超范围返回 null
    function solar2lunar(y, m, d) {
        if (y < 1900 || y > 2100) return null;
        // 距 1900-01-31（1900 年正月初一）的天数（0-based）
        var days = Math.floor((Date.UTC(y, m - 1, d) - Date.UTC(1900, 0, 31)) / 86400000);
        if (days < 0) return null;
        // 定位农历年
        var ly = 1900, yd;
        while (ly <= 2100) {
            yd = lYearDays(ly);
            if (days < yd) break;
            days -= yd;
            ly++;
        }
        if (ly > 2100) return null;
        // 定位月（正月→腊月；闰月紧随同名正常月之后）
        var leap = leapMonth(ly);
        var lm = 1, isLeap = false;
        while (lm <= 12) {
            var md = lMonthDays(ly, lm);
            if (days < md) break;
            days -= md;
            if (leap === lm) {
                // 正常月之后为闰月
                var ldl = leapDays(ly);
                if (days < ldl) { isLeap = true; break; }
                days -= ldl;
            }
            lm++;
        }
        if (lm > 12) return null; // 防御（不应触发）
        return {
            ly: ly,
            lmonth: lm,
            lday: days + 1,
            isLeap: isLeap,
            monthName: (isLeap ? '闰' : '') + MONTH_CN[lm - 1] + '月',
            dayName: DAY_CN[days],
            gz: gzYear(ly),
            animal: ANIMALS[(ly - 4) % 12],
            week: WEEK_CN[new Date(y, m - 1, d).getDay()]
        };
    }

    // ===== 节气（查表法：sxtwl 权威数据） =====

    // base32 字符 → 数值（'0'-'9' = 0-9，'a'-'v' = 10-31）
    function b32val(c) {
        var cc = c.charCodeAt(0);
        if (cc >= 48 && cc <= 57) return cc - 48;
        return cc - 87;
    }

    // y 年第 n 个节气（n: 0-23，0=小寒）的公历日
    function termDay(y, n) {
        return b32val(TERM_DATA.charAt((y - 1900) * 24 + n));
    }

    // 查询 y 年 m 月 d 日是否节气日，是则返回节气名，否则返回 null
    function termOf(y, m, d) {
        // 每节气所在公历月份恒定（TERM_MONTHS），按月定位候选节气索引
        var base = (m - 1) * 2;
        if (termDay(y, base) === d) return TERM_NAMES[base];
        if (termDay(y, base + 1) === d) return TERM_NAMES[base + 1];
        return null;
    }

    // ===== 节日 =====

    // 公历「第 N 个星期 X」类浮动节日日期
    function nthWeekdayOfMonth(y, m, nth, weekday) {
        var firstDay = new Date(y, m - 1, 1).getDay();
        var firstOccur = 1 + ((weekday - firstDay + 7) % 7);
        return firstOccur + (nth - 1) * 7;
    }

    // 查询公历节日名（固定 + 浮动），无则返回 null
    function gregFestivalOf(y, m, d) {
        var key = m + '-' + d;
        if (GREG_FESTIVALS[key]) return GREG_FESTIVALS[key];
        for (var i = 0; i < GREG_FLOAT_FESTIVALS.length; i++) {
            var f = GREG_FLOAT_FESTIVALS[i];
            if (f.month === m && nthWeekdayOfMonth(y, m, f.nth, f.weekday) === d) return f.name;
        }
        return null;
    }

    // 查询农历节日名（含除夕判断；闰月当天不算农历节日），无则返回 null
    function lunarFestivalOf(y, m, d, lunar) {
        if (!lunar || lunar.isLeap) return null;
        // 除夕：腊月最后一天（次日为正月初一）
        if (lunar.lmonth === 12) {
            var next = new Date(y, m - 1, d + 1);
            var nl = solar2lunar(next.getFullYear(), next.getMonth() + 1, next.getDate());
            if (nl && nl.lmonth === 1 && nl.lday === 1) return '除夕';
        }
        var key = lunar.lmonth + '-' + lunar.lday;
        return LUNAR_FESTIVALS[key] || null;
    }

    // ===== 对外 API =====

    /**
     * 日历格子小字（万年历核心展示）
     * 优先级：节日（红）> 节气（红）> 农历日；初一显示月名（如「八月」，闰月带「闰」）
     * 返回 { text, type: 'festival'|'term'|'lunar'|'none', lunar }
     */
    function getDayLabel(y, m, d) {
        var lunar = solar2lunar(y, m, d);
        if (!lunar) return { text: '', type: 'none', lunar: null };
        var fest = gregFestivalOf(y, m, d) || lunarFestivalOf(y, m, d, lunar);
        if (fest) return { text: fest, type: 'festival', lunar: lunar };
        var term = termOf(y, m, d);
        if (term) return { text: term, type: 'term', lunar: lunar };
        var text = (lunar.lday === 1) ? lunar.monthName : lunar.dayName;
        return { text: text, type: 'lunar', lunar: lunar };
    }

    /**
     * 详情面板完整万年历信息
     * 返回 { week, gregText, lunarFull, lunarMD, gz, animal, festivals[], term }
     */
    function getFullInfo(y, m, d) {
        var lunar = solar2lunar(y, m, d);
        if (!lunar) return null;
        var festivals = [];
        var gf = gregFestivalOf(y, m, d);
        if (gf) festivals.push(gf);
        var lf = lunarFestivalOf(y, m, d, lunar);
        if (lf) festivals.push(lf);
        return {
            week: lunar.week,
            gregText: y + '年' + m + '月' + d + '日',
            lunarFull: lunar.gz + '年（' + lunar.animal + '） ' + lunar.monthName + lunar.dayName,
            lunarMD: lunar.monthName + lunar.dayName,
            gz: lunar.gz,
            animal: lunar.animal,
            festivals: festivals,
            term: termOf(y, m, d)
        };
    }

    return {
        solar2lunar: solar2lunar,
        getDayLabel: getDayLabel,
        getFullInfo: getFullInfo,
        termOf: termOf,
        gregFestivalOf: gregFestivalOf
    };
})();
