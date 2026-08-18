import os
import subprocess
import sys
import datetime
import random
import ipaddress

def ensure_ssl_directory():
    """确保 ssl 目录存在，如果不存在则创建"""
    ssl_dir = os.path.join(os.getcwd(), 'ssl')
    if not os.path.exists(ssl_dir):
        os.makedirs(ssl_dir)
        print(f"[INFO] Created ssl directory: {ssl_dir}")
    return ssl_dir

def generate_self_signed_cert(cert_file='server.crt', key_file='server.key', days=365):
    """生成用于测试/内网 HTTPS 部署的自签名 SSL 证书"""
    print("[INFO] Generating self-signed SSL certificate...")
    
    # 确保 ssl 目录存在
    ssl_dir = ensure_ssl_directory()
    
    # 构建完整的文件路径
    cert_path = os.path.join(ssl_dir, cert_file)
    key_path = os.path.join(ssl_dir, key_file)
    
    # 生成随机序列号，确保每次不同
    serial = random.getrandbits(64)
    
    # 尝试使用 OpenSSL 命令行生成（省略 -rand /dev/urandom 保持 Windows/Linux 跨平台兼容）
    try:
        cmd = [
            'openssl', 'req', '-x509', '-nodes', '-days', str(days),
            '-newkey', 'rsa:2048',
            '-keyout', key_path,
            '-out', cert_path,
            '-subj', f'/CN=localhost-{serial}/O=GiftBookkeeping/C=CN'
        ]
        subprocess.run(cmd, check=True)
        print(f"[SUCCESS] SSL certificate generated successfully:\n  - Certificate: {cert_path}\n  - Private key: {key_path}")
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
            x509.NameAttribute(NameOID.COMMON_NAME, f"localhost-{serial}"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, f"GiftBookkeeping-{serial}")
        ])
        
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
            x509.SubjectAlternativeName([
                x509.DNSName(u"localhost"),
                x509.DNSName(f"localhost-{serial}"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
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

        print(f"[SUCCESS] SSL certificate generated successfully using Python cryptography:\n  - Certificate: {cert_path}\n  - Private key: {key_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Certificate generation failed. Please install openssl or python cryptography library. Error: {e}")
        return False

if __name__ == '__main__':
    generate_self_signed_cert()

