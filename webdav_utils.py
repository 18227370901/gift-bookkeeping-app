# -*- coding: utf-8 -*-
"""
WebDAV 客户端工具模块
使用 requests 库实现标准 WebDAV 协议（PROPFIND、MKCOL、PUT、GET）
支持主流 WebDAV 服务（坚果云、群晖、Nextcloud、Alist、OwnCloud 等）
用于数据库的远端自动备份与一键还原
"""

import os
import io
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import urllib3

# 禁用 self-signed SSL 证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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


def _resolve_target_dir_url(webdav_url_or_config, backup_path=None):
    """
    统一解析并生成 WebDAV 远端备份目标目录 URL。
    1. 智能处理 base_url 与 backup_path 拼接；
    2. 去除多余重复斜杠；
    3. 对坚果云等特殊 WebDAV 根路径（如以 /dav 结尾）且未指定子目录时，自动智能保底挂载 /gift_backups/，避免直接往根目录写入导致 404。
    """
    if hasattr(webdav_url_or_config, 'server_url') or hasattr(webdav_url_or_config, 'webdav_url'):
        cfg = webdav_url_or_config
        raw_url = getattr(cfg, 'server_url', None) or getattr(cfg, 'webdav_url', '')
        cfg_path = getattr(cfg, 'backup_path', None) or getattr(cfg, 'remote_dir', '')
        if backup_path is None:
            backup_path = cfg_path
    else:
        raw_url = webdav_url_or_config

    base_url = _normalize_url(raw_url).rstrip('/')
    path_str = (backup_path or '').strip()

    if path_str and path_str != '/':
        clean_sub = '/' + path_str.strip('/')
        if not base_url.endswith(clean_sub):
            return base_url + clean_sub + '/'
        else:
            return base_url + '/'

    parsed = urllib.parse.urlparse(base_url)
    if parsed.path.rstrip('/') == '/dav':
        return base_url + '/gift_backups/'
    return base_url + '/'


def _get_session(username, password):
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'GiftBookkeepingWebDAV/2.0'
    })
    if username or password:
        session.auth = HTTPBasicAuth(username or '', password or '')
    return session


def ensure_remote_dir(target_dir_url, username, password):
    """
    确保远端备份目录存在，支持沿路径逐级检查并自动创建（MKCOL）。
    返回: (True, "就绪说明") 或 (False, "失败说明")
    """
    target_url = _normalize_url(target_dir_url).rstrip('/') + '/'
    session = _get_session(username, password)
    headers = {'Depth': '0'}

    try:
        # 1. 检查目标目录是否已经存在
        resp = session.request('PROPFIND', target_url, headers=headers, timeout=12, verify=False)
        if resp.status_code in (200, 207):
            return True, "目录已就绪"

        # 2. 逐级检查并创建多级路径
        parsed = urllib.parse.urlparse(target_url)
        path_parts = [p for p in parsed.path.split('/') if p]
        current_path = ''
        for part in path_parts:
            current_path += '/' + part
            if current_path in ('/dav', '/remote.php', '/remote.php/dav', '/remote.php/dav/files'):
                continue
            sub_url = f"{parsed.scheme}://{parsed.netloc}{current_path}/"
            try:
                sub_check = session.request('PROPFIND', sub_url, headers=headers, timeout=8, verify=False)
                if sub_check.status_code in (200, 207):
                    continue
                if sub_check.status_code in (404, 405):
                    session.request('MKCOL', sub_url, timeout=10, verify=False)
            except Exception:
                pass

        # 3. 最终确认
        final_resp = session.request('PROPFIND', target_url, headers=headers, timeout=10, verify=False)
        if final_resp.status_code in (200, 207):
            return True, "目录已成功创建并就绪"
        return False, f"远端目录自动创建未就绪 (HTTP {final_resp.status_code})，请在网盘手动建立对应目录"
    except requests.exceptions.Timeout:
        return False, "连接 WebDAV 超时"
    except Exception as e:
        return False, f"检测远端目录异常: {str(e)}"


def test_connection(webdav_url, username=None, password=None, backup_path=None):
    """测试 WebDAV 服务连通性与目录有效性"""
    if hasattr(webdav_url, 'server_url') or hasattr(webdav_url, 'webdav_url'):
        cfg = webdav_url
        webdav_url, username, password = _unpack_auth_params(cfg)
        if backup_path is None:
            backup_path = getattr(cfg, 'backup_path', None) or getattr(cfg, 'remote_dir', '')

    if not webdav_url or not str(webdav_url).strip():
        return False, "未配置 WebDAV 服务器地址"
    
    target_url = _resolve_target_dir_url(webdav_url, backup_path)
    session = _get_session(username, password)
    headers = {
        'Depth': '0',
        'Content-Type': 'application/xml; charset=utf-8'
    }

    try:
        resp = session.request('PROPFIND', target_url, headers=headers, timeout=12, verify=False)
        if resp.status_code in [200, 207]:
            return True, "WebDAV 连接成功，备份目录就绪！"
        if resp.status_code == 401:
            return False, "WebDAV 认证失败，请检查用户名或密码/应用密码"
        if resp.status_code == 403:
            return False, "WebDAV 访问被拒绝 (HTTP 403)，请确认账户目录访问权限"
        if resp.status_code == 404:
            ok, _ = ensure_remote_dir(target_url, username, password)
            if ok:
                return True, "WebDAV 连接成功，备份目录已自动创建就绪！"
            return False, f"WebDAV 服务连通正常，但指定目录不存在且自动创建失败：{target_url}"
        return False, f"WebDAV 响应状态码异常: HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        return False, "连接超时：无法在规定时间内连接至 WebDAV 目标地址，请检查网络或服务器端口"
    except requests.exceptions.ConnectionError as ce:
        return False, f"无法连接到 WebDAV 服务器（网络不可达或连接被拒绝）：{str(ce)}"
    except Exception as e:
        return False, f"连接异常: {str(e)}"


def upload_backup(webdav_url_or_config, username=None, password=None, local_file_path=None, remote_filename=None, backup_path=None):
    """上传本地备份文件到 WebDAV 远端"""
    if hasattr(webdav_url_or_config, 'server_url') or hasattr(webdav_url_or_config, 'webdav_url'):
        cfg = webdav_url_or_config
        if local_file_path is None and username is not None:
            local_file_path = username
            remote_filename = password
        webdav_url, username, password = _unpack_auth_params(cfg)
        if backup_path is None:
            backup_path = getattr(cfg, 'backup_path', None) or getattr(cfg, 'remote_dir', '')
    else:
        webdav_url = webdav_url_or_config

    if not webdav_url or not str(webdav_url).strip():
        return False, "未配置 WebDAV 服务器地址"
    if not local_file_path or not os.path.exists(local_file_path):
        return False, "本地数据库文件不存在"

    if not remote_filename:
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        remote_filename = f"gift_bookkeeping_backup_{timestamp_str}.db"

    target_dir_url = _resolve_target_dir_url(webdav_url, backup_path)
    ok, dir_msg = ensure_remote_dir(target_dir_url, username, password)
    if not ok:
        return False, f"远端目录准备失败: {dir_msg}"

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


def list_backups(webdav_url_or_config, username=None, password=None, backup_path=None):
    """列出 WebDAV 远端目录下的所有备份文件"""
    if hasattr(webdav_url_or_config, 'server_url') or hasattr(webdav_url_or_config, 'webdav_url'):
        cfg = webdav_url_or_config
        webdav_url, username, password = _unpack_auth_params(cfg)
        if backup_path is None:
            backup_path = getattr(cfg, 'backup_path', None) or getattr(cfg, 'remote_dir', '')
    else:
        webdav_url = webdav_url_or_config

    if not webdav_url or not str(webdav_url).strip():
        return False, "未配置 WebDAV 服务器地址"

    target_url = _resolve_target_dir_url(webdav_url, backup_path)
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


def download_backup(webdav_url_or_config, username=None, password=None, remote_filename=None, save_path=None, backup_path=None):
    """从 WebDAV 远端下载指定备份文件到本地"""
    if hasattr(webdav_url_or_config, 'server_url') or hasattr(webdav_url_or_config, 'webdav_url'):
        cfg = webdav_url_or_config
        if save_path is None and remote_filename is not None:
            save_path = password
            remote_filename = username
        webdav_url, username, password = _unpack_auth_params(cfg)
        if backup_path is None:
            backup_path = getattr(cfg, 'backup_path', None) or getattr(cfg, 'remote_dir', '')
    else:
        webdav_url = webdav_url_or_config

    if not webdav_url or not str(webdav_url).strip():
        return False, "未配置 WebDAV 服务器地址"

    target_dir_url = _resolve_target_dir_url(webdav_url, backup_path)
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
