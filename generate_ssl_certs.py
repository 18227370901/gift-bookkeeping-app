import os
import subprocess
import sys

def generate_self_signed_cert(cert_file='server.crt', key_file='server.key', days=365):
    """生成用于测试/内网 HTTPS 部署的自签名 SSL 证书"""
    print("🔐 正在生成自签名 SSL 证书...")
    
    # 尝试使用 OpenSSL 命令行生成
    try:
        cmd = [
            'openssl', 'req', '-x509', '-nodes', '-days', str(days),
            '-newkey', 'rsa:2048',
            '-keyout', key_file,
            '-out', cert_file,
            '-subj', '/CN=localhost/O=GiftBookkeeping/C=CN'
        ]
        subprocess.run(cmd, check=True)
        print(f"✅ 成功生成 SSL 证书：\n  - 公钥/证书: {os.path.abspath(cert_file)}\n  - 私钥: {os.path.abspath(key_file)}")
        return True
    except Exception as e:
        print(f"⚠️ 未找到 OpenSSL 命令行或执行失败: {e}")
        
    # 如果系统未安装 OpenSSL 命令行，尝试用 Python cryptography 模块生成
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"GiftBookkeeping")
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
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=days)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
            critical=False,
        ).sign(key, hashes.SHA256())

        with open(key_file, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        print(f"✅ 成功生成 Python 自签名 SSL 证书：\n  - 证书: {os.path.abspath(cert_file)}\n  - 私钥: {os.path.abspath(key_file)}")
        return True
    except Exception as e:
        print(f"❌ 证书生成失败，请在系统中安装 openssl 或 python cryptography 库。错误信息: {e}")
        return False

if __name__ == '__main__':
    generate_self_signed_cert()
