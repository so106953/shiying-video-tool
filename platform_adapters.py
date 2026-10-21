"""Public-page adapters for platforms missing from yt-dlp.

Only public share metadata is read. No login, CAPTCHA, paid parser or DRM services.
Endpoint/schema references: wujunwei928/parse-video-py (MIT), see THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations
import html
import json
import os
import re
from urllib.parse import parse_qs, urljoin, urlsplit
import httpx

UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1'
MAX_PAGE = 6 * 1024 * 1024
ADAPTERS = {
    'Kuaishou': '快手', 'Haokan': '好看视频', 'Weishi': '微视', 'Pipixia': '皮皮虾',
    'NetEaseVideo': '网易视频', 'Tangdou': '糖豆广场舞', 'Threads': 'Threads',
    'Dongchedi': '懂车帝', 'WechatArticle': '微信公众号',
}


def platform_key(url):
    host = (urlsplit(url).hostname or '').lower().rstrip('.')
    def within(domain):
        return host == domain or host.endswith('.' + domain)
    if within('kuaishou.com') or within('kuaishou.cn') or within('chenzhongtech.com'):
        return 'Kuaishou'
    if host == 'haokan.baidu.com': return 'Haokan'
    if within('weishi.qq.com'): return 'Weishi'
    if within('pipix.com'): return 'Pipixia'
    if within('tangdou.com') or within('tangdoucdn.com'): return 'Tangdou'
    if host in ('163.com', 'www.163.com', 'm.163.com', 'v.163.com', 'c.m.163.com'):
        return 'NetEaseVideo'
    if within('threads.net') or within('threads.com'): return 'Threads'
    if within('dongchedi.com'): return 'Dongchedi'
    if host == 'mp.weixin.qq.com': return 'WechatArticle'
    return None


def fetch_page(url, referer=None):
    from engine import validate_url
    # No operator cookies are used. httpx isolates incidental anonymous cookies by domain.
    with httpx.Client(timeout=httpx.Timeout(20, connect=10), follow_redirects=False,
                      verify=os.environ.get('SSL_CERT_FILE') or True) as client:
        for _ in range(6):
            validate_url(url)
            with client.stream('GET', url, headers={'User-Agent': UA, 'Referer': referer or url}) as response:
                if response.is_redirect:
                    location = response.headers.get('location')
                    if not location: raise ValueError('平台分享链接跳转无效。')
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                data = bytearray()
                for block in response.iter_bytes():
                    data.extend(block)
                    if len(data) > MAX_PAGE: raise ValueError('平台页面过大，暂时无法处理。')
                return str(response.url), data.decode('utf-8-sig', errors='replace')
    raise ValueError('平台分享链接跳转次数过多。')


def state_value(text, marker):
    match = re.search(marker, text)
    if not match: return None
    try: return json.JSONDecoder().raw_decode(text[match.end():].lstrip())[0]
    except (ValueError, RecursionError): return None


def walk(value):
    stack = [(value, 0)]
    count = 0
    while stack and count < 30000:
        node, depth = stack.pop(); count += 1
        if depth > 48: continue
        if isinstance(node, dict):
            yield node
            stack.extend((v, depth + 1) for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            stack.extend((v, depth + 1) for v in node if isinstance(v, (dict, list)))


def first_url(value):
    if isinstance(value, str): return value
    if isinstance(value, list):
        return next((first_url(v) for v in value if first_url(v)), None)
    if isinstance(value, dict):
        return first_url(value.get('url') or value.get('url_list') or value.get('download_list'))
    return None


def media_info(key, ident, title, sources, *, uploader=None, thumbnail=None, duration=None, referer=None):
    from engine import validate_url
    formats = []; used = set()
    for source in sources:
        if isinstance(source, str): source = {'url': source}
        if not isinstance(source, dict): continue
        url = source.get('url')
        if not isinstance(url, str): continue
        url = html.unescape(url).replace('\\/', '/')
        if url.startswith('//'): url = 'https:' + url
        if url in used: continue
        validate_url(url)
        used.add(url)
        hls = '.m3u8' in urlsplit(url).path.lower()
        formats.append({'format_id': str(len(formats)), 'url': url, 'ext': 'mp4',
                        'protocol': 'm3u8_native' if hls else urlsplit(url).scheme,
                        'width': source.get('width'), 'height': source.get('height'),
                        'vcodec': source.get('vcodec') or ({'avc': 'h264', 'h264': 'h264', 'hevc': 'hevc'}.get(source.get('videoCodec'))), 'acodec': source.get('acodec'),
                        'http_headers': {'User-Agent': UA, 'Referer': referer or ''}})
    if not formats:
        raise ValueError(f'{ADAPTERS[key]}没有返回公开的视频地址，可能需要登录、链接已失效或这是图文内容。')
    return {'id': str(ident), 'title': title or ADAPTERS[key] + '视频', 'extractor_key': key,
            'extractor': key, 'webpage_url': referer, 'formats': formats, 'uploader': uploader,
            'thumbnail': thumbnail, 'duration': float(duration) if duration is not None else None}


def kuaishou(url):
    final, text = fetch_page(url)
    if platform_key(final) != 'Kuaishou': raise ValueError('快手分享链接未指向作品页面。')
    match = re.search(r'/(?:short-video|photo|long-video)/([a-zA-Z0-9]+)', urlsplit(final).path)
    ident = match[1] if match else (parse_qs(urlsplit(final).query).get('photoId') or [None])[0]
    if not ident: raise ValueError('请使用快手单个作品的分享链接。')
    state = state_value(text, r'(?:window\.)?INIT_STATE\s*=\s*')
    photos = [n['photo'] for n in walk(state) if n.get('result') == 1 and isinstance(n.get('photo'), dict)]
    if not photos:
        apollo = state_value(text, r'(?:window\.)?__APOLLO_STATE__\s*=\s*')
        client = (apollo or {}).get('defaultClient', {})
        photo = client.get('VisionVideoDetailPhoto:' + ident)
        if isinstance(photo, dict): photos = [photo]
    if not photos and '/short-video/' in urlsplit(final).path:
        return kuaishou('https://kphm5nf3.m.chenzhongtech.com/fw/photo/' + ident)
    if len(photos) != 1: raise ValueError('快手没有返回该作品的公开播放信息，请重新复制分享链接。')
    photo = photos[0]
    sources = []
    for name in ('mainMvUrls', 'photoUrl', 'playUrl'):
        value = photo.get(name)
        if isinstance(value, list): sources.extend({'url': first_url(v), 'width': photo.get('width'), 'height': photo.get('height')} for v in value)
        elif isinstance(value, str): sources.append({'url': value, 'width': photo.get('width'), 'height': photo.get('height')})
    resource = photo.get('videoResource') or photo.get('manifest') or {}
    if isinstance(resource, dict): resource = resource.get('json') or resource
    if isinstance(resource, str):
        try: resource = json.loads(resource)
        except ValueError: resource = {}
    for node in walk(resource):
        if node.get('url') and (node.get('width') or node.get('height')): sources.append(node)
    return media_info('Kuaishou', ident, photo.get('caption'), sources,
                      uploader=photo.get('userName'), thumbnail=first_url(photo.get('coverUrls')) or photo.get('coverUrl'),
                      duration=photo.get('duration', 0) / 1000 or None, referer='https://www.kuaishou.com/')


def haokan(url):
    ident = (parse_qs(urlsplit(url).query).get('vid') or [None])[0]
    if not ident:
        final, _ = fetch_page(url)
        ident = (parse_qs(urlsplit(final).query).get('vid') or [None])[0]
    if not ident or not ident.isdigit(): raise ValueError('请使用包含 vid 的好看视频详情链接。')
    _, text = fetch_page('https://haokan.baidu.com/v?_format=json&vid=' + ident)
    data = json.loads(text)
    video = (data.get('data') or {}).get('apiData', {}).get('curVideoMeta') or {}
    if video.get('id') and str(video['id']) != ident: raise ValueError('好看视频返回了不同作品，请重新解析。')
    if video.get('is_pay_column') and str(video.get('is_free')) not in ('1', 'True'): raise ValueError('这个视频需要付费权限，当前不提供下载。')
    sources = []
    for node in walk(video.get('clarityUrl') or video.get('clarityList') or []):
        if node.get('url'):
            dimensions = str(node.get('vodVideoHW', '')).split('$$')
            if len(dimensions) == 2 and all(n.isdigit() for n in dimensions):
                node = node | {'height': int(dimensions[0]), 'width': int(dimensions[1])}
            sources.append(node)
    if video.get('playurl'): sources.append({'url': video['playurl']})
    return media_info('Haokan', ident, video.get('title'), sources, uploader=video.get('mth', {}).get('author_name'),
                      thumbnail=video.get('poster'), duration=video.get('duration'), referer='https://haokan.baidu.com/')


def pipixia(url):
    ident = re.search(r'/(?:ppx/)?item/(\d+)', urlsplit(url).path)
    if not ident:
        final, _ = fetch_page(url)
        if platform_key(final) != 'Pipixia': raise ValueError('皮皮虾分享链接无效。')
        ident = re.search(r'/(?:ppx/)?item/(\d+)', urlsplit(final).path)
    if not ident: raise ValueError('请使用皮皮虾单个作品的分享链接。')
    ident = ident[1]
    _, text = fetch_page('https://api.pipix.com/bds/cell/cell_comment/?offset=0&cell_type=1&api_version=1&cell_id=' + ident + '&ac=wifi&channel=huawei_1319_64&aid=1319&app_name=super')
    data = json.loads(text)
    comments = (data.get('data') or {}).get('cell_comments') or []
    item = next((c.get('comment_info', {}).get('item', {}) for c in comments if str(c.get('comment_info', {}).get('item', {}).get('item_id_str') or c.get('comment_info', {}).get('item', {}).get('item_id')) == ident), {})
    video = item.get('video') or {}
    sources = [{'url': first_url(video.get(name)), 'width': (video.get(name) or {}).get('width') or video.get('video_width'), 'height': (video.get(name) or {}).get('height') or video.get('video_height')} for name in ('video_high', 'video_download', 'video_fallback')]
    return media_info('Pipixia', ident, item.get('content'), sources, uploader=item.get('author', {}).get('name'),
                      thumbnail=first_url(item.get('cover')), duration=video.get('duration'), referer='https://h5.pipix.com/')


def weishi(url):
    ident = (parse_qs(urlsplit(url).query).get('id') or [None])[0]
    if not ident:
        match = re.search(r'/feed/([a-zA-Z0-9]+)', urlsplit(url).path)
        ident = match[1] if match else None
    if not ident or not re.fullmatch('[a-zA-Z0-9]{5,64}', ident): raise ValueError('请使用微视单个视频的分享链接。')
    try:
        _, text = fetch_page('https://h5.weishi.qq.com/webapp/json/weishi/WSH5GetPlayPage?feedid=' + ident)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404: raise ValueError('微视公开接口当前不可用，尚未完成下载适配。') from exc
        raise
    data = json.loads(text); feeds = (data.get('data') or {}).get('feeds') or []
    video = next((v for v in feeds if str(v.get('id') or v.get('feedid')) == ident), {})
    return media_info('Weishi', ident, video.get('feed_desc_withat'), [video.get('video_url')],
                      uploader=video.get('poster', {}).get('nick'), thumbnail=first_url(video.get('images')), referer='https://h5.weishi.qq.com/')


def tangdou(url):
    query = parse_qs(urlsplit(url).query)
    ident = (query.get('vid') or [None])[0]
    if not ident:
        match = re.search(r'/play/(\d+)', urlsplit(url).path); ident = match[1] if match else None
    if not ident or not ident.isdigit(): raise ValueError('请使用糖豆视频详情页或带 vid 的分享链接。')
    _, text = fetch_page('https://api-h5.tangdou.com/sample/share/main?vid=' + ident, 'https://www.tangdoucdn.com/')
    data = json.loads(text).get('data') or {}
    if data.get('is_vip'): raise ValueError('这个糖豆视频需要会员权限，当前不提供下载。')
    return media_info('Tangdou', ident, data.get('title'), [data.get('video_url')], uploader=data.get('user_name') or data.get('name'),
                      thumbnail=data.get('pic'), duration=data.get('duration'), referer='https://www.tangdoucdn.com/')


def netease(url):
    match = re.search(r'/(V[a-zA-Z0-9]{8,})\.html', urlsplit(url).path)
    if not match: return None  # Non-video NetEase articles still use the generic extractor.
    ident = match[1]
    _, text = fetch_page('https://c.m.163.com/nc/video/detail/' + ident + '.html')
    video = json.loads(text)
    if isinstance(video.get(ident), dict): video = video[ident]
    sources = [{'url': video.get(key)} for key in ('mp4Hd_url', 'mp4Shd_url', 'mp4_url', 'm3u8Hd_url', 'm3u8_url')]
    return media_info('NetEaseVideo', ident, video.get('title'), sources, uploader=video.get('videosource'),
                      thumbnail=video.get('cover'), duration=video.get('length'), referer='https://www.163.com/')


def structured_page(url, key):
    final, text = fetch_page(url)
    if platform_key(final) != key: raise ValueError('分享链接未指向原平台作品。')
    sources = []; title = None; thumbnail = None
    # Only a page's explicitly declared video is eligible, never arbitrary URLs in scripts or recommendations.
    from html.parser import HTMLParser
    class Page(HTMLParser):
        def handle_starttag(self, tag, attrs):
            nonlocal title, thumbnail
            attrs = dict(attrs)
            if tag == 'meta':
                prop = attrs.get('property') or attrs.get('name')
                content = attrs.get('content')
                if prop in ('og:video', 'og:video:url', 'og:video:secure_url') and content: sources.append(content)
                if prop == 'og:title': title = content
                if prop == 'og:image': thumbnail = content
            if tag in ('video', 'source') and attrs.get('src') and '.mp4' in attrs['src']: sources.append(urljoin(final, attrs['src']))
    Page().feed(text)
    if key == 'Threads':
        code = re.search(r'/(?:post|t)/([a-zA-Z0-9_-]+)', urlsplit(final).path)
        if not code: raise ValueError('请使用 Threads 单条帖子的链接。')
        for match in re.finditer(r'<script\b[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', text, re.S):
            try: data = json.loads(match[1])
            except (ValueError, RecursionError): continue
            for node in walk(data):
                if node.get('code') == code[1]:
                    sources.extend(node.get('video_versions') or [])
                    title = node.get('caption', {}).get('text') or title
    if key == 'WechatArticle':
        records = state_value(text, r'["\']?mp_video_trans_info["\']?\s*[:=]\s*')
        for node in walk(records):
            if node.get('url') and node.get('width') and node.get('height'): sources.append(node)
        if not records:
            # WeChat also emits JavaScript object literals with quoted numbers multiplied by 1.
            # Read only the known video metadata fields; never evaluate JavaScript.
            videos = []
            for block in re.finditer(r'\bmp_video_trans_info\s*:\s*\[([^\]]{0,24000})\]', text, re.S):
                variants = []
                for match in re.finditer(r'\{([^{}]{0,6000})\}', block[1], re.S):
                    fields = dict((m[1], m[3]) for m in re.finditer(r'\b(url|width|height|filesize|duration_ms)\s*:\s*([\"\'])(.*?)\2', match[1], re.S))
                    raw = fields.get('url', '')
                    raw = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m[1], 16)), raw)
                    raw = html.unescape(raw)
                    if urlsplit(raw).hostname != 'mpvideo.qpic.cn': continue
                    variants.append({'url': raw, **{k: int(fields[k]) for k in ('width', 'height') if fields.get(k, '').isdigit()}})
                if variants: videos.append(variants)
            if len(videos) > 1: raise ValueError('这篇公众号文章包含多个视频，暂只支持单视频文章或单条视频消息。')
            if videos: sources.extend(videos[0])
    if key == 'Dongchedi':
        state = state_value(text, r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>\s*')
        match = re.search(r'/(?:video|article)/(\d+)', urlsplit(final).path)
        ident = match[1] if match else None
        # Match the requested article before inspecting its own video resource.
        for node in walk(state):
            if ident and str(node.get('group_id') or node.get('item_id') or node.get('id')) == ident:
                video = node.get('video') or node.get('video_detail') or node.get('video_list') or {}
                import base64
                for candidate in walk(video):
                    if candidate.get('main_url'):
                        try: sources.append({'url': base64.b64decode(candidate['main_url']).decode(), 'width': candidate.get('width'), 'height': candidate.get('height')})
                        except (ValueError, UnicodeError): continue
    return media_info(key, urlsplit(final).path.rsplit('/', 1)[-1], title, sources, thumbnail=thumbnail, referer=final)


def extract_public_extra(url):
    key = platform_key(url)
    if not key: return None
    functions = {'Kuaishou': kuaishou, 'Haokan': haokan, 'Pipixia': pipixia,
                 'Weishi': weishi, 'Tangdou': tangdou, 'NetEaseVideo': netease}
    if key in functions: return functions[key](url)
    return structured_page(url, key)
