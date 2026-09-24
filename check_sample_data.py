# -*- coding: utf-8 -*-
"""
样例库敏感数据推送前校验脚本（项目工具，V10.10.12 建立）
用途：防止真实配置数据随样例库 gift_bookkeeping.db 推送到仓库。
背景：根目录样例库历史遗留自早期运行库路径，曾残留真实 WebDAV/Webhook 凭据、
      真实注册邀请码与用户标识，V10.10.12 已彻底清理并建立本防线。

用法:
    python check_sample_data.py            # 校验根目录 gift_bookkeeping.db
    python check_sample_data.py <db路径>   # 校验指定数据库

退出码: 0 = 校验通过，可以推送
        1 = 发现敏感数据残留，禁止推送（需先按 V10.10.12 流程清理）

约定：每次向 GitHub 推送前必须运行本脚本并通过（参见 README 样例数据章节维护约定）。
"""
import sqlite3
import sys
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DB = sys.argv[1] if len(sys.argv) > 1 else "gift_bookkeeping.db"

# 与 models.py 一致的默认密钥（用于验证分享口令密文是否为已知样例值）
DEFAULT_SECRET_KEY = 'gift-bookkeeping-secret-key-2026-prod-secure'


def decrypt_credential(cipher_text):
    key = hashlib.sha256(DEFAULT_SECRET_KEY.encode('utf-8')).digest()
    raw = base64.b64decode(cipher_text)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode('utf-8')


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    problems = []

    # 1. 禁止真实用户名出现
    cur.execute("SELECT username FROM users WHERE username IN ('ghca')")
    if cur.fetchall():
        problems.append("users 表存在真实用户名 ghca")

    # 2. 冻结演示用户必须存在且处于冻结状态
    cur.execute("SELECT id, is_active FROM users WHERE username='demo_user_frozen'")
    row = cur.fetchone()
    if not row:
        problems.append("users 表缺少冻结演示用户 demo_user_frozen")
    elif row[1] != 0:
        problems.append("demo_user_frozen 未处于冻结状态(is_active != 0)")

    # 3. 会话令牌必须全部为空
    cur.execute("SELECT id, username FROM users WHERE session_token IS NOT NULL AND session_token != ''")
    rows = cur.fetchall()
    if rows:
        problems.append(f"存在有效会话令牌: {rows}")

    # 4. WebDAV 凭据密文必须为空
    cur.execute("SELECT id FROM backup_configs WHERE webdav_password IS NOT NULL AND webdav_password != ''")
    if cur.fetchall():
        problems.append("backup_configs.webdav_password 存在密文（必须为空）")

    # 5. WebDAV 地址必须为通用公共端点
    cur.execute("SELECT id, webdav_url FROM backup_configs")
    for r in cur.fetchall():
        if r[1] and r[1] != 'https://dav.jianguoyun.com/dav/':
            problems.append(f"backup_configs id={r[0]} webdav_url 非通用端点: {r[1][:30]}...")

    # 6. Webhook 凭据密文必须为空
    cur.execute("SELECT id FROM webhook_configs WHERE (secret_token IS NOT NULL AND secret_token != '') OR (bot_secret IS NOT NULL AND bot_secret != '')")
    if cur.fetchall():
        problems.append("webhook_configs 存在 secret_token/bot_secret 密文（必须为空）")

    # 7. Webhook URL 必须含样例标记
    cur.execute("SELECT id, webhook_url FROM webhook_configs")
    for r in cur.fetchall():
        if r[1] and not any(m in r[1] for m in ('SAMPLE', 'DEMO', 'EXAMPLE')):
            problems.append(f"webhook_configs id={r[0]} webhook_url 疑似真实: {r[1][:30]}...")

    # 8. 注册邀请码表必须为空
    cur.execute("SELECT COUNT(*) FROM registration_tokens")
    if cur.fetchone()[0] > 0:
        cur.execute("SELECT token FROM registration_tokens LIMIT 3")
        problems.append(f"registration_tokens 非空: {[r[0][:8] for r in cur.fetchall()]}")

    # 9. 分享链接口令必须为已知样例口令（可解密验证）
    cur.execute("SELECT id, access_password FROM shared_ledger_links")
    for r in cur.fetchall():
        if not r[1]:
            problems.append(f"shared_ledger_links id={r[0]} 口令为空（应为样例口令密文）")
            continue
        try:
            plain = decrypt_credential(r[1])
            if plain not in ('123456', '666888'):
                problems.append(f"shared_ledger_links id={r[0]} 口令非样例值")
        except Exception:
            problems.append(f"shared_ledger_links id={r[0]} 口令密文无法解密（疑似外部密钥加密的真实数据）")

    conn.close()

    if problems:
        print("!!! 校验未通过，禁止推送：")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("校验通过：样例库无敏感数据残留，可以推送。")
    sys.exit(0)


if __name__ == '__main__':
    main()
