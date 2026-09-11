# -*- coding: utf-8 -*-
"""
WebDAV 客户端工具模块
使用 requests 库实现标准 WebDAV 协议（PROPFIND、MKCOL、PUT、GET）
支持主流 WebDAV 服务（坚果云、群晖、Nextcloud、Alist、OwnCloud 等）
用于数据库的远端自动备份与一键还原
"""

import os
import io
import time
import shutil
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import urllib3

# 禁用 self-signed SSL 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 尝试导入 pyzipper 用于 AES-256 加密 zip
try:
    import pyzipper
    HAS_PYZIPPER = True
except ImportError:
    HAS_PYZIPPER = False


def _normalize_url(url):
    url = (url or '').strip()
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url
    return url


def _unpack_auth_params(webdav_url_or_config, username=None, password=None):
    """灵活解构参数：既支持 (config) 单参数对象，也支持 (url, username, password) 传统入参"""
    if hasattr(webdav_url_or_config, 'server_url') or hasattr(webdav_url_or_config, 'webdav_url'):
        cfg = webdav_url_or_config
        url = getattr(cfg, 'server_url', None) or getattr(cfg, 'webdav_url', '')
        user = getattr(cfg, 'username', None) or getattr(cfg, 'webdav_username', '')
        pwd = getattr(cfg, 'password', None) or getattr(cfg, 'webdav_password', '')
        return url, user, pwd
    return webdav_url_or_config, username, password


def _get_session(username, password):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'GiftBookkeepingWebDAV/2.0'
    })
    if username or password:
        session.auth = HTTPBasicAuth(username or '', password or '')
    return session


def test_connection(webdav_url, username=None, password=None):
    """测试 WebDAV 服务连通性与目录有效性"""
    webdav_url, username, password = _unpack_auth_params(webdav_url, username, password)
    if not webdav_url or not str(webdav_url).strip():
        return False, "未配置 WebDAV 服务器地址"
    
    target_url = _normalize_url(webdav_url)
    session = _get_session(username, password)
    headers = {
        'Depth': '0',
        'Content-Type': 'application/xml; charset=utf-8'
    }

    try:
        resp = session.request('PROPFIND', target_url, headers=headers, timeout=12, verify=False)
        if resp.status_code in [200, 207]:
            return True, "WebDAV 连接成功！"
        if resp.status_code == 401:
            return False, "WebDAV 认证失败，请检查用户名或密码/应用密码"
        if resp.status_code == 403:
            return False, "WebDAV 访问被拒绝 (HTTP 403)，请确认账户目录访问权限"
        if resp.status_code == 404:
            return False, f"WebDAV 指定路径不存在 (HTTP 404)：{target_url}"
        return False, f"WebDAV 响应状态码异常: HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        return False, "连接超时：无法在规定时间内连接至 WebDAV 目标地址，请检查网络或服务器端口"
    except requests.exceptions.ConnectionError as ce:
        return False, f"无法连接到 WebDAV 服务器（网络不可达或连接被拒绝）：{str(ce)}"
    except Exception as e:
        return False, f"连接异常: {str(e)}"


def _resolve_target_dir_url(base_url, backup_subdir=None):
    """智能标准化 WebDAV 目标目录 URL
    
    - 如果 URL 以 /dav 或 /dav/ 结尾，自动追加子目录（默认 gift_backups）
    - 确保返回的 URL 以 / 结尾
    """
    url = base_url.strip().rstrip('/')
    if not url:
        return url + '/'
    
    # 判断是否是根 /dav 路径
    path = urllib.parse.urlparse(url).path.rstrip('/')
    if path.endswith('/dav') or path == '/dav':
        subdir = (backup_subdir or 'gift_backups').strip('/')
        url = url + '/' + subdir
    elif not path:
        subdir = (backup_subdir or 'gift_backups').strip('/')
        url = url + '/' + subdir
    
    return url.rstrip('/') + '/'


def ensure_remote_dir(webdav_url, username, password, backup_subdir=None):
    """确保远端目录存在，递归创建多级子目录"""
    target_url = _resolve_target_dir_url(webdav_url, backup_subdir)
    session = _get_session(username, password)
    headers = {'Depth': '0'}
    
    # 先检查完整路径是否已存在
    try:
        resp = session.request('PROPFIND', target_url, headers=headers, timeout=12, verify=False)
        if resp.status_code in [200, 207]:
            return True
    except Exception:
        pass
    
    # 递归创建各级子目录
    parsed = urllib.parse.urlparse(target_url)
    path_parts = [p for p in parsed.path.split('/') if p]
    
    # 逐级构建路径
    current_path = ''
    base_url_base = f"{parsed.scheme}://{parsed.netloc}"
    
    for i, part in enumerate(path_parts):
        current_path = current_path + '/' + part
        current_url = base_url_base + current_path + '/'
        
        # 先检查是否存在
        try:
            resp = session.request('PROPFIND', current_url, headers=headers, timeout=10, verify=False)
            if resp.status_code in [200, 207]:
                continue  # 已存在，检查下一级
        except Exception:
            pass
        
        # 不存在则创建
        try:
            mk_resp = session.request('MKCOL', current_url, timeout=10, verify=False)
            if mk_resp.status_code in [200, 201, 204]:
                time.sleep(0.1)  # 避免触发限频
                continue
            elif mk_resp.status_code == 405:
                # 405 Method Not Allowed 通常意味着目录已存在
                continue
            elif mk_resp.status_code == 409:
                # 409 Conflict: 父目录不存在 — 不应该发生，因为我们逐级创建
                # 但某些服务器对 /dav 根目录写保护会返回 409/403
                if i == 0:
                    # 第一级目录创建失败（可能是根目录写保护）
                    # 尝试在根下直接上传，跳过目录创建
                    return False
                continue
        except Exception:
            pass
    
    # 最终验证目标目录是否可用
    try:
        resp = session.request('PROPFIND', target_url, headers=headers, timeout=10, verify=False)
        if resp.status_code in [200, 207]:
            return True
    except Exception:
        pass
    
    # 即使 PROPFIND 失败，目录可能已创建成功（某些服务器对 PROPFIND 限制）
    # 直接返回 True，让后续上传尝试
    return True


def upload_backup(webdav_url_or_config, username=None, password=None, local_file_path=None, remote_filename=None):
    """上传本地备份文件到 WebDAV 远端"""
    backup_subdir = None
    if hasattr(webdav_url_or_config, 'server_url') or hasattr(webdav_url_or_config, 'webdav_url'):
        cfg = webdav_url_or_config
        if local_file_path is None and username is not None:
            local_file_path = username
            remote_filename = password
        webdav_url, username, password = _unpack_auth_params(cfg)
        backup_subdir = getattr(cfg, 'backup_subdir', None)
    else:
        webdav_url = webdav_url_or_config

    if not webdav_url or not str(webdav_url).strip():
        return False, "未配置 WebDAV 服务器地址"
    if not local_file_path or not os.path.exists(local_file_path):
        return False, "本地数据库文件不存在！"

    if not remote_filename:
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        remote_filename = f"gift_bookkeeping_backup_{timestamp_str}.db"

    target_dir_url = _resolve_target_dir_url(webdav_url, backup_subdir)
    ensure_remote_dir(target_dir_url, username, password, backup_subdir=backup_subdir)

    file_upload_url = urllib.parse.urljoin(target_dir_url, urllib.parse.quote(remote_filename))
    session = _get_session(username, password)

    try:
        with open(local_file_path, 'rb') as f:
            data = f.read()

        headers = {
            'Content-Type': 'application/octet-stream',
            'Content-Length': str(len(data))
        }

        resp = session.put(file_upload_url, data=data, headers=headers, timeout=60, verify=False)
        if resp.status_code in (200, 201, 204):
            return True, remote_filename
        return False, f"上传失败 (HTTP {resp.status_code})"
    except requests.exceptions.Timeout:
        return False, "上传超时，网络传输中断"
    except Exception as e:
        return False, f"上传异常: {str(e)}"


def list_backups(webdav_url_or_config, username=None, password=None):
    """列出 WebDAV 远端目录下的所有备份文件"""
    backup_subdir = None
    if hasattr(webdav_url_or_config, 'server_url') or hasattr(webdav_url_or_config, 'webdav_url'):
        backup_subdir = getattr(webdav_url_or_config, 'backup_subdir', None)
    webdav_url, username, password = _unpack_auth_params(webdav_url_or_config, username, password)
    if not webdav_url or not str(webdav_url).strip():
        return False, "未配置 WebDAV 服务器地址"
    target_url = _resolve_target_dir_url(webdav_url, backup_subdir)
    session = _get_session(username, password)
    
    headers = {
        'Depth': '1',
        'Content-Type': 'application/xml; charset=utf-8'
    }
    
    propfind_xml = (
        '<?xml version="1.0" encoding="utf-8" ?>'
        '<D:propfind xmlns:D="DAV:">'
        '  <D:prop>'
        '    <D:displayname/>'
        '    <D:getcontentlength/>'
        '    <D:getlastmodified/>'
        '    <D:resourcetype/>'
        '  </D:prop>'
        '</D:propfind>'
    ).encode('utf-8')

    try:
        resp = session.request('PROPFIND', target_url, data=propfind_xml, headers=headers, timeout=15, verify=False)
        if resp.status_code not in (200, 207):
            return False, f"获取远端备份列表失败: HTTP {resp.status_code}"

        root = ET.fromstring(resp.content)
        namespaces = {'D': 'DAV:'}
        
        backups = []
        for response in root.findall('D:response', namespaces):
            href_el = response.find('D:href', namespaces)
            if href_el is None or not href_el.text:
                continue
            href = urllib.parse.unquote(href_el.text)
            
            is_dir = False
            propstat = response.find('D:propstat', namespaces)
            if propstat is not None:
                prop = propstat.find('D:prop', namespaces)
                if prop is not None:
                    resourcetype = prop.find('D:resourcetype', namespaces)
                    if resourcetype is not None and resourcetype.find('D:collection', namespaces) is not None:
                        is_dir = True

            filename = os.path.basename(href.rstrip('/'))
            if not filename or is_dir:
                continue

            if not any(filename.lower().endswith(ext) for ext in ['.db', '.sqlite', '.sqlite3', '.bak', '.zip']):
                continue

            size = 0
            last_modified = ''
            if propstat is not None and prop is not None:
                length_el = prop.find('D:getcontentlength', namespaces)
                if length_el is not None and length_el.text:
                    try:
                        size = int(length_el.text)
                    except ValueError:
                        size = 0
                modified_el = prop.find('D:getlastmodified', namespaces)
                if modified_el is not None and modified_el.text:
                    last_modified = modified_el.text

            backups.append({
                'filename': filename,
                'name': filename,
                'href': href,
                'size': size,
                'size_human': f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024*1024):.2f} MB",
                'last_modified': last_modified,
                'modified_time': last_modified
            })

        backups.sort(key=lambda x: x['filename'], reverse=True)
        return True, backups
    except requests.exceptions.Timeout:
        return False, "获取远端备份列表超时，请检查网络连接"
    except Exception as e:
        return False, f"解析远端备份列表异常: {str(e)}"


def download_backup(webdav_url_or_config, username=None, password=None, remote_filename=None, save_path=None):
    """从 WebDAV 远端下载指定备份文件到本地"""
    backup_subdir = None
    if hasattr(webdav_url_or_config, 'server_url') or hasattr(webdav_url_or_config, 'webdav_url'):
        cfg = webdav_url_or_config
        # 修正参数映射：当用 config 对象调用时，username 参数位实际传的是 remote_filename，password 位传的是 save_path
        if remote_filename is None and username is not None:
            remote_filename = username
            save_path = password
            username = None
            password = None
        webdav_url, username, password = _unpack_auth_params(cfg)
        backup_subdir = getattr(cfg, 'backup_subdir', None)
    else:
        webdav_url = webdav_url_or_config
    if not webdav_url or not str(webdav_url).strip():
        return False, "未配置 WebDAV 服务器地址"
    if not remote_filename:
        return False, "未指定要下载的文件名"

    # 修复：使用 _resolve_target_dir_url 而非 _normalize_url，确保包含 backup_subdir 子目录
    target_dir_url = _resolve_target_dir_url(webdav_url, backup_subdir)
    file_download_url = urllib.parse.urljoin(target_dir_url, urllib.parse.quote(remote_filename))
    session = _get_session(username, password)

    try:
        resp = session.get(file_download_url, stream=True, timeout=60, verify=False)
        if resp.status_code == 200:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            return True, f"成功下载备份文件：{remote_filename}"
        return False, f"下载响应异常，状态码: HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        return False, "WebDAV 下载备份文件超时"
    except Exception as e:
        return False, f"WebDAV 下载异常: {str(e)}"


def create_encrypted_zip(local_file_path, zip_password, output_path=None):
    """
    将本地文件创建为 AES-256 加密的 zip 包。
    返回 (success, zip_path_or_error_msg)
    """
    if not HAS_PYZIPPER:
        return False, "缺少 pyzipper 库，请运行 pip install pyzipper"
    if not local_file_path or not os.path.exists(local_file_path):
        return False, "本地文件不存在"
    if not zip_password:
        return False, "加密密码不能为空"

    if output_path is None:
        output_path = local_file_path + '.zip'

    try:
        with pyzipper.AESZipFile(output_path, 'w', compression=pyzipper.ZIP_LZMA, encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(zip_password.encode('utf-8'))
            zf.write(local_file_path, os.path.basename(local_file_path))
        return True, output_path
    except Exception as e:
        return False, f"创建加密 zip 失败: {str(e)}"


def upload_encrypted_backup(webdav_url_or_config, username=None, password=None, local_file_path=None, remote_filename=None, encrypt_password=None):
    """
    先将本地文件加密为 zip，再上传到 WebDAV。
    encrypt_password 为 None 时不加密，直接上传原始文件。
    """
    if not local_file_path or not os.path.exists(local_file_path):
        return False, "本地数据库文件不存在！"

    if encrypt_password and HAS_PYZIPPER:
        # 创建加密 zip 到临时目录
        tmp_dir = tempfile.mkdtemp(prefix='gift_backup_')
        tmp_zip = os.path.join(tmp_dir, os.path.basename(local_file_path) + '.zip')
        ok, result = create_encrypted_zip(local_file_path, encrypt_password, tmp_zip)
        if not ok:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return False, result
        try:
            upload_path = tmp_zip
            if not remote_filename:
                remote_filename = f"gift_bookkeeping_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            elif not remote_filename.endswith('.zip'):
                remote_filename = remote_filename + '.zip'
            success, msg = upload_backup(webdav_url_or_config, username, password, upload_path, remote_filename)
            return success, msg
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        if not remote_filename:
            remote_filename = f"gift_bookkeeping_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        return upload_backup(webdav_url_or_config, username, password, local_file_path, remote_filename)


def upload_file_to_webdav(webdav_url_or_config, username=None, password=None, local_file_path=None, remote_filename=None):
    """
    通用文件上传方法：上传任意本地文件到 WebDAV 远端。
    如果 remote_filename 包含子目录（如 attachments/xxx），自动创建远端子目录。
    """
    # 如果文件名包含子目录路径，需要先确保远端子目录存在
    if remote_filename and '/' in remote_filename:
        backup_subdir = None
        if hasattr(webdav_url_or_config, 'server_url') or hasattr(webdav_url_or_config, 'webdav_url'):
            cfg = webdav_url_or_config
            webdav_url, username, password = _unpack_auth_params(cfg)
            backup_subdir = getattr(cfg, 'backup_subdir', None)
        else:
            webdav_url = webdav_url_or_config
        # 确保 attachments 子目录存在
        subdir_name = remote_filename.split('/')[0]
        ensure_remote_dir(webdav_url, username, password, backup_subdir=backup_subdir)
        # 在子目录下再创建 attachments 子目录
        base_dir_url = _resolve_target_dir_url(webdav_url, backup_subdir)
        subdir_url = urllib.parse.urljoin(base_dir_url, subdir_name + '/')
        session = _get_session(username, password)
        try:
            resp = session.request('PROPFIND', subdir_url, headers={'Depth': '0'}, timeout=10, verify=False)
            if resp.status_code not in (200, 207):
                session.request('MKCOL', subdir_url, timeout=10, verify=False)
        except Exception:
            pass
    return upload_backup(webdav_url_or_config, username, password, local_file_path, remote_filename)


def delete_webdav_backup(webdav_url_or_config, username=None, password=None, remote_filename=None):
    """
    删除 WebDAV 远端指定备份文件。
    支持传入 config 对象或 (url, username, password, filename) 传统入参。
    返回 (success, message)
    """
    backup_subdir = None
    if hasattr(webdav_url_or_config, 'server_url') or hasattr(webdav_url_or_config, 'webdav_url'):
        cfg = webdav_url_or_config
        # 修正参数映射：config 对象调用时 remote_filename 可能在 username 参数位
        if remote_filename is None and username is not None:
            remote_filename = username
            username = None
            password = None
        webdav_url, username, password = _unpack_auth_params(cfg)
        backup_subdir = getattr(cfg, 'backup_subdir', None)
    else:
        webdav_url = webdav_url_or_config
    if not webdav_url or not str(webdav_url).strip():
        return False, "未配置 WebDAV 服务器地址"
    if not remote_filename:
        return False, "未指定要删除的文件名"

    # 修复：使用 _resolve_target_dir_url 而非 _normalize_url，确保包含 backup_subdir 子目录
    target_dir_url = _resolve_target_dir_url(webdav_url, backup_subdir)
    file_delete_url = urllib.parse.urljoin(target_dir_url, urllib.parse.quote(remote_filename))
    session = _get_session(username, password)

    try:
        resp = session.delete(file_delete_url, timeout=30, verify=False)
        if resp.status_code in (200, 204):
            return True, f"成功删除远端文件：{remote_filename}"
        if resp.status_code == 404:
            return False, f"远端文件不存在：{remote_filename}"
        return False, f"删除失败，HTTP 状态码: {resp.status_code}"
    except requests.exceptions.Timeout:
        return False, "WebDAV 删除文件超时"
    except Exception as e:
        return False, f"WebDAV 删除异常: {str(e)}"


def decrypt_encrypted_zip(zip_file_path, zip_password, output_path=None):
    """
    解密 AES-256 加密的 zip 备份文件，提取其中的 .db 文件。
    返回 (success, db_path_or_error_msg)
    """
    if not HAS_PYZIPPER:
        return False, "缺少 pyzipper 库，请运行 pip install pyzipper"
    if not zip_file_path or not os.path.exists(zip_file_path):
        return False, "加密 zip 文件不存在"
    if not zip_password:
        return False, "解密密码不能为空"

    if output_path is None:
        # 默认输出到同目录下，用 .db 替换 .zip
        output_path = zip_file_path.rsplit('.zip', 1)[0]
        if output_path == zip_file_path:
            output_path = zip_file_path + '.db'

    try:
        with pyzipper.AESZipFile(zip_file_path, 'r', compression=pyzipper.ZIP_LZMA, encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(zip_password.encode('utf-8'))
            # 获取 zip 内的第一个文件（应该是 .db 文件）
            names = zf.namelist()
            if not names:
                return False, "加密 zip 内无文件"
            # 读取第一个文件的内容并写入输出路径
            data = zf.read(names[0])
            with open(output_path, 'wb') as f:
                f.write(data)
        return True, output_path
    except RuntimeError as e:
        if 'password' in str(e).lower() or 'decrypt' in str(e).lower():
            return False, "密码错误，无法解密备份文件"
        return False, f"解密失败: {str(e)}"
    except Exception as e:
        return False, f"解密异常: {str(e)}"


def download_and_decrypt_backup(webdav_url_or_config, username=None, password=None, remote_filename=None, save_path=None, decrypt_password=None):
    """
    从 WebDAV 下载备份文件并恢复到指定路径。
    如果是 .zip 加密文件且提供了 decrypt_password，会自动解密。
    返回 (success, message)
    """
    # 先下载到临时路径
    tmp_dir = tempfile.mkdtemp(prefix='gift_restore_')
    try:
        if remote_filename and remote_filename.lower().endswith('.zip'):
            # 加密 zip 文件：先下载到临时目录，解密后再复制到目标路径
            tmp_zip = os.path.join(tmp_dir, remote_filename)
            ok, msg = download_backup(webdav_url_or_config, username, password, remote_filename, tmp_zip)
            if not ok:
                return False, msg
            if not decrypt_password:
                return False, "该备份文件是加密的，请输入加密密码"
            tmp_db = os.path.join(tmp_dir, 'restored.db')
            ok, msg = decrypt_encrypted_zip(tmp_zip, decrypt_password, tmp_db)
            if not ok:
                return False, msg
            # 复制解密后的 db 文件到目标路径
            shutil.copy2(tmp_db, save_path)
            return True, f"成功恢复加密备份：{remote_filename}"
        else:
            # 普通 .db 文件：直接下载到目标路径
            ok, msg = download_backup(webdav_url_or_config, username, password, remote_filename, save_path)
            return ok, msg
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
