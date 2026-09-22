import os
import subprocess
import sys
import datetime
import ipaddress
import argparse

def ensure_ssl_directory():
    """确保 ssl 目录存在，如果不存在则创建"""
    ssl_dir = os.path.join(os.getcwd(), 'ssl')
    if not os.path.exists(ssl_dir):
        os.makedirs(ssl_dir)
        print(f"[INFO] Created ssl directory: {ssl_dir}")
    return ssl_dir

def generate_self_signed_cert(cert_file='server.crt', key_file='server.key', days=365, domain='localhost'):
    """生成用于测试/内网 HTTPS 部署的自签名 SSL 证书

    Args:
        cert_file: 证书输出文件名（相对于 ssl/ 目录）
        key_file: 私钥输出文件名（相对于 ssl/ 目录）
        days: 证书有效期（天）
        domain: 要写入 CN 和 SAN 的域名，支持空格分隔的多个域名（如 "a.com b.com"），
                第一个域名写入 CN，全部域名写入 SAN（支持域名或 IP，默认 localhost）
    """
    print("[INFO] Generating self-signed SSL certificate...")

    # 解析多域名：空格分隔，第一个为 CN（主域名），全部写入 SAN
    domains = domain.strip().split()
    if not domains:
        domains = ['localhost']
    primary_domain = domains[0]
    print(f"[INFO] Primary domain (CN): {primary_domain}")
    if len(domains) > 1:
        print(f"[INFO] All domains ({len(domains)}): {', '.join(domains)}")

    # 确保 ssl 目录存在
    ssl_dir = ensure_ssl_directory()

    # 构建完整的文件路径
    cert_path = os.path.join(ssl_dir, cert_file)
    key_path = os.path.join(ssl_dir, key_file)

    # 为每个域名判断是 IP 还是 DNS 名称
    domain_entries = []  # [(raw_value, entry_type, entry_str)]
    for d in domains:
        try:
            ipaddress.ip_address(d)
            domain_entries.append((d, 'ip', f'IP:{d}'))
        except ValueError:
            domain_entries.append((d, 'dns', f'DNS:{d}'))

    # 尝试使用 OpenSSL 命令行生成（省略 -rand /dev/urandom 保持 Windows/Linux 跨平台兼容）
    # 注意：-addext 需要 OpenSSL 1.1.1+，旧版本会执行失败并自动回退到 Python cryptography
    try:
        # 构建 SAN 值：始终包含 localhost + 127.0.0.1，再追加用户域名（去重）
        san_parts = ['DNS:localhost', 'IP:127.0.0.1']
        for raw, dtype, entry_str in domain_entries:
            if entry_str not in san_parts:
                san_parts.append(entry_str)
        san_value = ','.join(san_parts)

        cmd = [
            'openssl', 'req', '-x509', '-nodes', '-days', str(days),
            '-newkey', 'rsa:2048',
            '-keyout', key_path,
            '-out', cert_path,
            '-subj', f'/CN={primary_domain}/O=GiftBookkeeping/C=CN',
            '-addext', f'subjectAltName={san_value}'
        ]
        subprocess.run(cmd, check=True)
        print(f"[SUCCESS] SSL certificate generated successfully (domains: {', '.join(domains)}):\n  - Certificate: {cert_path}\n  - Private key: {key_path}")
        return True
    except Exception as e:
        print(f"[WARNING] OpenSSL command not found or execution failed: {e}")

    # 如果系统未安装 OpenSSL 命令行，尝试用 Python cryptography 模块生成
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend

        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )

        current_time = datetime.datetime.now(datetime.timezone.utc)

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, primary_domain),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "GiftBookkeeping")
        ])

        # 构建 SAN 列表：始终包含 localhost + 127.0.0.1，再追加用户域名（去重）
        san_names = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
        for raw, dtype, entry_str in domain_entries:
            if dtype == 'ip':
                ip_obj = ipaddress.ip_address(raw)
                # 去重：跳过已存在的 127.0.0.1
                if raw != "127.0.0.1":
                    san_names.append(x509.IPAddress(ip_obj))
            else:
                # 去重：跳过已存在的 localhost
                if raw != "localhost":
                    san_names.append(x509.DNSName(raw))

        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            current_time - datetime.timedelta(days=1)
        ).not_valid_after(
            current_time + datetime.timedelta(days=days)
        ).add_extension(
            x509.SubjectAlternativeName(san_names),
            critical=False,
        ).sign(key, hashes.SHA256())

        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        print(f"[SUCCESS] SSL certificate generated successfully using Python cryptography (domains: {', '.join(domains)}):\n  - Certificate: {cert_path}\n  - Private key: {key_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Certificate generation failed. Please install openssl or python cryptography library. Error: {e}")
        return False

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate a self-signed SSL certificate for HTTPS deployment')
    parser.add_argument('--domain', default='localhost',
                        help='SNI domain(s) to embed into certificate CN/SAN, supports space-separated multiple domains or IPs (e.g. "a.com b.com", default: localhost)')
    parser.add_argument('--days', type=int, default=365,
                        help='Certificate validity in days (default: 365)')
    args = parser.parse_args()
    generate_self_signed_cert(domain=args.domain, days=args.days)
