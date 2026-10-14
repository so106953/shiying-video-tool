from __future__ import annotations
import ipaddress, json, os, re, socket, time, uuid
from pathlib import Path
from urllib.parse import urlsplit
import yt_dlp
def validate_url(value: str, resolve=True) -> str:
    value = value.strip()
    if len(value) > 4096:
        raise ValueError('链接过长')
    parts = urlsplit(value)
    if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password:
        raise ValueError('请输入有效的 http 或 https 视频链接')
    host = parts.hostname.lower().rstrip('.')
    if host in ('localhost', 'metadata.google.internal') or host.endswith(('.localhost', '.local', '.internal')):
        raise ValueError('不支持本机或内网地址，请使用公开视频链接')
    if parts.port and parts.port not in (80, 443):
        raise ValueError('仅支持标准 http/https 端口')
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        if not resolve:
            return value
        try:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)]
        except socket.gaierror as exc:
            # Some environments have incomplete DNS for overseas CDN domains.
            # Resolve through HTTPS, then apply the same public-address validation.
            try:
                import httpx
                response = httpx.get('https://cloudflare-dns.com/dns-query',
                    params={'name': host, 'type': 'A'}, headers={'Accept': 'application/dns-json'},
                    timeout=8, verify=os.environ.get('SSL_CERT_FILE') or True)
                response.raise_for_status()
                records = response.json().get('Answer') or []
                addresses = [ipaddress.ip_address(record['data']) for record in records if record.get('type') == 1]
                if not addresses:
                    raise ValueError('DNS returned no public addresses')
            except Exception:
                raise ValueError('无法找到这个网站，请检查链接或网络') from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError('不支持本机或内网地址，请使用公开视频链接')
    return value

class SafeYoutubeDL(yt_dlp.YoutubeDL):
    def urlopen(self, req):
        target = req if isinstance(req, str) else getattr(req, 'url', None) or getattr(req, 'full_url', '')
        validate_url(target)
        return super().urlopen(req)

class QuietLog:
    def debug(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass

def _node_executable():
    try:
        from nodejs_wheel import executable
        return str(Path(executable.ROOT_DIR) / ('node.exe' if os.name == 'nt' else 'bin/node'))
    except ImportError:
        import shutil
        return shutil.which('node') or 'node'

def ydl_options():
    return {'quiet': True, 'no_warnings': True, 'logger': QuietLog(), 'noplaylist': True, 'compat_opts': {'no-certifi'},
            'socket_timeout': 15, 'retries': 1, 'extractor_retries': 1,
            'cachedir': False, 'restrictfilenames': False, 'windowsfilenames': True,
            'max_filesize': 8 * 1024**3, 'skip_unavailable_fragments': False,
            'js_runtimes': {'node': {'path': _node_executable()}}}

def friendly_error(error):
    raw = re.sub(r'\x1b\[[0-9;]*m', '', str(error)).removeprefix('ERROR: ').strip()
    low = raw.lower()
    if 'no video formats' in low or 'no formats found' in low:
        return '没有获取到可下载的视频。请确认这是视频作品，并重新复制完整分享链接；图文作品、失效链接和访问限制也可能导致此问题。'
    if '412' in low or '429' in low:
        return '平台暂时限制云端访问，请稍后重试。'
    if 'drm' in low:
        return '这个视频受内容保护，当前不能下载。'
    if 'unsupported url' in low:
        return '暂不支持这个链接。请使用视频详情页或 MP4/WebM 直链。'
    if any(word in low for word in ['sign in', 'login', 'cookies', 'not a bot', 'fresh cookies']):
        return '平台要求登录或人机验证，当前无法解析这个视频。可先尝试其他公开链接。'
    if any(word in low for word in ['private video', 'removed', 'not available', '404', 'unavailable', 'geo-restricted', 'geo restricted']):
        return '视频不存在、已设为私密或在当前地区不可用。'
    if '403' in low:
        return '平台拒绝了请求（403），请稍后重试或重新解析链接。'
    if any(word in low for word in ['timeout', 'timed out', 'network', 'connection']):
        return '网络请求失败或超时，请检查网络后重试。'
    if 'ffmpeg' in low:
        return '这个格式需要 FFmpeg。请安装 FFmpeg 并重启服务。'
    if re.search(r'[\u4e00-\u9fff]', raw):
        return raw[:300]
    return '平台没有返回可用的视频信息。请确认链接可以公开播放，并重新复制完整分享链接后重试。'

def metadata(info, url):
    formats = info.get('formats') or [info]
    heights = sorted({int(f['height']) for f in formats if f.get('height') and f.get('vcodec') != 'none'}, reverse=True)
    sizes = [f.get('filesize') or f.get('filesize_approx') for f in formats if f.get('vcodec') != 'none']
    platform = info.get('extractor_key') or info.get('extractor') or '媒体直链'
    platform = {'BiliBili': '哔哩哔哩', 'Youtube': 'YouTube', 'Douyin': '抖音', 'TikTok': 'TikTok', 'Generic': '媒体直链', 'XiaoHongShu': '小红书', 'Instagram': 'Instagram', 'Twitter': 'X / Twitter', 'Vimeo': 'Vimeo', 'Toutiao': '今日头条', 'Ixigua': '西瓜视频'}.get(platform, platform)
    direct = info.get('direct') or (str(info.get('extractor_key', '')).lower() == 'generic' and urlsplit(url).path.lower().endswith(('.mp4', '.webm', '.mov', '.mp3', '.m4a')))
    return {'id': uuid.uuid4().hex, 'url': url, 'title': info.get('title') or Path(urlsplit(url).path).name or '视频',
            'platform': platform, 'uploader': info.get('uploader') or info.get('channel') or urlsplit(url).hostname,
            'thumbnail': info.get('thumbnail'), 'duration': info.get('duration'), 'heights': heights,
            'size': max((s for s in sizes if s), default=None), 'ext': info.get('ext') or 'mp4',
            'direct': bool(direct), 'created': time.time(), 'status': 'success'}

DOUYIN_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1'

def extract_public_douyin(url):
    """Read the public share page's SSR data; no login cookies or challenge automation."""
    host = (urlsplit(url).hostname or '').lower()
    if host not in ('v.douyin.com', 'www.douyin.com', 'douyin.com', 'www.iesdouyin.com', 'iesdouyin.com'):
        return None
    import httpx
    from urllib.parse import urljoin, parse_qs
    headers = {'User-Agent': DOUYIN_UA, 'Referer': 'https://www.douyin.com/'}
    def get_public(client, target):
        for _ in range(6):
            validate_url(target)
            response = client.get(target)
            if response.status_code in (301, 302, 303, 307, 308):
                if not response.headers.get('location'):
                    raise ValueError('抖音分享链接返回了无效跳转。')
                target = urljoin(target, response.headers['location'])
                continue
            response.raise_for_status()
            return response
        raise ValueError('抖音分享链接跳转次数过多，请重新复制链接。')
    with httpx.Client(headers=headers, timeout=20, follow_redirects=False,
                      verify=os.environ.get('SSL_CERT_FILE') or True) as client:
        match = re.search(r'/(?:share/)?video/(\d+)', url)
        if not match:
            resolved = get_public(client, url)
            match = re.search(r'/(?:share/)?video/(\d+)', str(resolved.url))
        ident = match[1] if match else (parse_qs(urlsplit(url).query).get('modal_id') or [None])[0]
        if not ident or not str(ident).isdigit():
            raise ValueError('未能找到抖音视频编号，请重新复制单个视频的分享链接。')
        canonical = f'https://www.iesdouyin.com/share/video/{ident}/'
        detail = None
        for share_url in (canonical, canonical + '?from_ssr=1', canonical + '?from_ssr=1&app=douyin_lite'):
            response = get_public(client, share_url)
            marker = re.search(r'(?:window\.)?_ROUTER_DATA\s*=\s*', response.text)
            if not marker:
                continue
            try:
                data, _ = json.JSONDecoder().raw_decode(response.text[marker.end():].lstrip())
            except json.JSONDecodeError:
                continue
            for page in (data.get('loaderData') or {}).values():
                if not isinstance(page, dict):
                    continue
                video_info = page.get('videoInfoRes') or {}
                items = video_info.get('item_list') or []
                detail = next((item for item in items if str(item.get('aweme_id')) == str(ident)), None)
                if detail:
                    break
            if detail:
                break
        if not detail:
            raise ValueError('抖音分享页没有返回此视频，可能已删除、设为私密或受访问限制。')
        if (detail.get('risk_infos') or {}).get('reflow_unplayable'):
            raise ValueError('此视频不允许在公开网页播放，当前无法下载。')
        video = detail.get('video') or {}
        media_urls = (video.get('play_addr') or {}).get('url_list') or []
        if not media_urls:
            raise ValueError('这个抖音作品没有可用的视频地址，可能是图文作品。')
        formats = []
        for index, media in enumerate(media_urls):
            validate_url(media)
            formats.append({'format_id': f'share-{index}', 'url': media, 'ext': 'mp4',
                            'protocol': urlsplit(media).scheme, 'vcodec': 'h264', 'acodec': 'aac',
                            'width': video.get('width'), 'height': video.get('height'),
                            'http_headers': headers})
        author = detail.get('author') or {}
        cover = (video.get('cover') or {}).get('url_list') or []
        return {'id': str(ident), 'title': detail.get('desc') or f'抖音视频 {ident}',
                'uploader': author.get('nickname') or '抖音作者', 'duration': (video.get('duration') or 0) / 1000,
                'thumbnail': cover[0] if cover else None, 'formats': formats, 'ext': 'mp4',
                'extractor_key': 'Douyin', 'webpage_url': canonical, 'http_headers': headers}


def extract_public_xiaohongshu(url):
    """Parse a public note/share URL, keeping its signed share query parameters."""
    from urllib.parse import urljoin, parse_qs
    host = (urlsplit(url).hostname or '').lower()
    if host not in ('xiaohongshu.com', 'www.xiaohongshu.com', 'xhslink.com', 'www.xhslink.com', 'xhslink.cn', 'www.xhslink.cn'):
        return None
    import httpx
    from yt_dlp.utils import js_to_json
    headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1',
               'Referer': 'https://www.xiaohongshu.com/'}
    target = url
    with httpx.Client(headers=headers, timeout=20, follow_redirects=False,
                      verify=os.environ.get('SSL_CERT_FILE') or True) as client:
        for _ in range(6):
            validate_url(target)
            response = client.get(target)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get('location')
                if not location:
                    raise ValueError('小红书分享链接跳转异常，请重新复制。')
                target = urljoin(target, location)
                continue
            break
        else:
            raise ValueError('小红书分享链接跳转次数过多，请重新复制。')
        if urlsplit(target).path.rstrip('/') == '/login' and (urlsplit(target).hostname or '') in ('www.xiaohongshu.com', 'xiaohongshu.com'):
            raise ValueError('这条小红书链接跳转到了登录页，平台未返回公开视频内容，当前无法下载。请确认笔记无需登录即可在网页播放。')
        if response.status_code in (401, 403, 412, 429) or '/404/' in urlsplit(target).path:
            has_token = bool(parse_qs(urlsplit(target).query).get('xsec_token') or parse_qs(urlsplit(url).query).get('xsec_token'))
            if not has_token:
                raise ValueError('小红书未返回笔记内容。请从小红书重新复制完整分享链接，保留链接中的验证参数，不要只复制笔记编号。')
            raise ValueError('这条小红书链接被平台限制访问。请重新复制最新分享链接，并确认笔记可以公开浏览。')
        response.raise_for_status()
        match = re.search(r'/(?:explore|discovery/item)/([a-f0-9]+)', target)
        ident = match[1] if match else None
        state = None
        marker = re.search(r'window\.__INITIAL_STATE__\s*=\s*', response.text)
        if marker:
            expression = response.text[marker.end():].split('</script>', 1)[0]
            try:
                state, _ = json.JSONDecoder().raw_decode(js_to_json(expression).lstrip())
            except (ValueError, json.JSONDecodeError):
                pass
        note = None
        details = ((state or {}).get('note') or {}).get('noteDetailMap') or {}
        mobile_note = (((state or {}).get('noteData') or {}).get('data') or {}).get('noteData')
        if isinstance(mobile_note, dict) and (not ident or str(mobile_note.get('noteId') or mobile_note.get('id')) == ident):
            note = mobile_note
        if ident and isinstance(details.get(ident), dict):
            note = details[ident].get('note')
        if not note:
            for detail in details.values():
                candidate = detail.get('note') if isinstance(detail, dict) else None
                if candidate and (not ident or str(candidate.get('noteId') or candidate.get('id')) == ident):
                    note = candidate
                    break
        if not note:
            raise ValueError('小红书分享页没有返回视频内容，请使用带验证参数的完整分享链接。')
        video = note.get('video') or {}
        if note.get('type') in ('normal', 'image') and not video:
            raise ValueError('这是一篇图文笔记，没有视频可下载。')
        media = video.get('media') or {}
        stream = media.get('stream') or video.get('stream') or {}
        formats = []
        for codec, variants in stream.items():
            if isinstance(variants, dict):
                variants = [variants]
            if not isinstance(variants, list):
                continue
            for index, variant in enumerate(variants):
                if not isinstance(variant, dict):
                    continue
                urls = [variant.get('masterUrl') or variant.get('master_url') or variant.get('url')]
                urls.extend(variant.get('backupUrls') or variant.get('backup_urls') or [])
                for media_url in urls:
                    if not isinstance(media_url, str) or not media_url.startswith(('http://', 'https://')):
                        continue
                    if media_url.startswith('http://') and (urlsplit(media_url).hostname or '').endswith('.xhscdn.com'):
                        media_url = 'https://' + media_url[7:]
                    validate_url(media_url)
                    formats.append({'format_id': f'{codec}-{index}', 'url': media_url, 'ext': 'mp4',
                                    'protocol': urlsplit(media_url).scheme, 'vcodec': variant.get('videoCodec') or codec,
                                    'acodec': variant.get('audioCodec') or 'aac', 'width': variant.get('width'),
                                    'height': variant.get('height'), 'filesize': variant.get('size'), 'http_headers': headers})
        origin = (video.get('consumer') or {}).get('originVideoKey') or video.get('originVideoKey')
        if not formats and origin and re.fullmatch(r'[A-Za-z0-9_./-]+', str(origin)):
            formats.append({'format_id': 'original', 'url': f'https://sns-video-bd.xhscdn.com/{str(origin).lstrip("/")}',
                            'ext': 'mp4', 'protocol': 'https', 'vcodec': 'h264', 'acodec': 'aac', 'http_headers': headers})
        if not formats:
            if note.get('imageList') and not video:
                raise ValueError('这是一篇图文笔记，没有视频可下载。')
            raise ValueError('笔记已识别，但小红书没有返回视频地址。请重新复制最新的完整分享链接。')
        images = note.get('imageList') or []
        thumbnail = next((image.get('urlDefault') or image.get('urlPre') or image.get('url') for image in images if isinstance(image, dict)), None)
        if thumbnail and thumbnail.startswith('http://') and (urlsplit(thumbnail).hostname or '').endswith('.xhscdn.com'):
            thumbnail = 'https://' + thumbnail[7:]
        user = note.get('user') or {}
        length = video.get('duration')
        duration = float(length) / 1000 if length else (media.get('video') or {}).get('duration') or (video.get('capa') or {}).get('duration')
        return {'id': ident or note.get('noteId'), 'title': note.get('title') or note.get('desc') or '小红书视频',
                'uploader': user.get('nickname') or user.get('nickName') or '小红书作者',
                'thumbnail': thumbnail, 'duration': duration,
                'formats': formats, 'ext': 'mp4', 'extractor_key': 'XiaoHongShu', 'webpage_url': target, 'http_headers': headers}
