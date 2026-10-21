"""Stateless Vercel API. Media goes straight to the browser in bounded chunks."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import time
from Cryptodome.Cipher import AES
from urllib.parse import urljoin, urlsplit
from typing import Literal

import httpx
import yt_dlp
import worker_client
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from engine import extract_public_extra, extraction_catalog, SafeYoutubeDL, validate_url, metadata, friendly_error, ydl_options, extract_public_douyin, extract_public_xiaohongshu, extract_public_ixigua, extract_public_twitter

app = FastAPI(docs_url=None, redoc_url=None)
CHUNK = 3 * 1024 * 1024
MAX_FILE = 256 * 1024 * 1024


@app.middleware('http')
async def routing_and_origin(request: Request, next_handler):
    route = request.query_params.get('route')
    if route:
        request.scope['path'] = '/api/' + route.strip('/')
    if request.method == 'POST':
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': '请从拾影页面操作'}, 403)
        if int(request.headers.get('content-length', 0)) > 65536:
            return JSONResponse({'detail': '请求内容过大'}, 413)
    response = await next_handler(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def secret():
    value = os.environ.get('SHIYING_SIGNING_SECRET')
    if not value:
        raise HTTPException(503, '部署配置尚未完成，请稍后重试。')
    return value.encode()


def sign_source(url, headers, ext, worker_job=None):
    allowed = {k: v for k, v in (headers or {}).items() if k.lower() in ('user-agent', 'referer', 'origin', 'accept', 'cookie') or (worker_job and k.lower() == 'authorization')}
    source = {'url': url, 'headers': allowed, 'ext': ext, 'expires': time.time() + 4 * 3600}
    if worker_job:
        source['worker_job'] = worker_job
    payload = json.dumps(source, separators=(',', ':')).encode()
    cipher = AES.new(hashlib.sha256(secret()).digest(), AES.MODE_GCM)
    ciphertext, tag = cipher.encrypt_and_digest(payload)
    return 'v2.' + base64.urlsafe_b64encode(cipher.nonce + tag + ciphertext).decode().rstrip('=')



def verify_source(ticket):
    try:
        if ticket.startswith('v2.'):
            encoded = ticket[3:]
            sealed = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
            cipher = AES.new(hashlib.sha256(secret()).digest(), AES.MODE_GCM, nonce=sealed[:16])
            payload = json.loads(cipher.decrypt_and_verify(sealed[32:], sealed[16:32]))
        else:
            encoded, signature = ticket.rsplit('.', 1)
            if not hmac.compare_digest(signature, hmac.new(secret(), encoded.encode(), hashlib.sha256).hexdigest()):
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        if payload['expires'] < time.time():
            raise HTTPException(410, '视频下载地址已过期，请重新解析链接。')
        if payload.get('worker_job'):
            worker_client.validate_job(payload)
        else:
            validate_url(payload['url'])
        return payload
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, '无效的视频下载地址，请重新解析链接。')


def parse_media(url, prefer_worker=False, include_conversions=False):
    attempted_worker = False
    try:
        url = validate_url(url)
        if prefer_worker or include_conversions or worker_client.preferred(url):
            attempted_worker = True
            return worker_client.resolve(url, sign_source, include_conversions=include_conversions)
        info = extract_public_extra(url)
        if info is None:
            info = extract_public_douyin(url)
        if info is None:
            info = extract_public_xiaohongshu(url)
        if info is None:
            info = extract_public_ixigua(url)
        if info is None:
            info = extract_public_twitter(url)
        if info is None:
            with SafeYoutubeDL(ydl_options() | {'format': 'best/bestvideo+bestaudio'}) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    for source in info.get('formats') or [info]:
                        media_url = source.get('url')
                        if not media_url:
                            continue
                        cookie = ydl.cookiejar.get_cookie_header(media_url)
                        if cookie:
                            source['http_headers'] = dict(source.get('http_headers') or info.get('http_headers') or {})
                            source['http_headers']['Cookie'] = cookie
        if not info or info.get('_type') in ('playlist', 'multi_video'):
            raise ValueError('请使用单个视频详情页，暂不支持播放列表。')
        if info.get('has_drm'):
            raise ValueError('这个视频受 DRM 内容保护，当前不能下载。')
        result = metadata(info, url)
        sources = sorted(info.get('formats') or [info], key=lambda f: (f.get('height') or 0, 1 if str(f.get('vcodec', '')).lower().startswith(('avc', 'h264')) else 0, 1 if (f.get('protocol') or urlsplit(f.get('url') or '').scheme) in ('http', 'https') else 0, f.get('tbr') or 0))
        options = []
        seen = set()
        for source in reversed(sources):
            media_url = source.get('url')
            ext = source.get('ext') or info.get('ext') or 'mp4'
            protocol = source.get('protocol') or urlsplit(media_url or '').scheme
            hls = protocol in ('m3u8', 'm3u8_native') and str(source.get('vcodec') or '').startswith(('avc', 'h264')) and source.get('acodec') not in (None, 'none')
            if not media_url or (protocol not in ('http', 'https') and not hls) or ext not in ('mp4', 'webm', 'mov', 'm4a', 'mp3', 'opus', 'ogg'):
                continue
            kind = 'audio' if source.get('vcodec') == 'none' or ext in ('m4a', 'mp3', 'opus', 'ogg') else 'video'
            # Only offer complete media. Separate tracks cannot be merged without a worker/storage.
            if kind == 'video' and source.get('acodec') == 'none':
                # Instagram also publishes complete, intentionally silent MP4s.
                silent_progressive = str(info.get('extractor_key', '')).startswith('Instagram') and source.get('vcodec') is None and str(source.get('format_id', '')).isdigit()
                if not silent_progressive:
                    continue
            size = source.get('filesize') or source.get('filesize_approx')
            if size and size > (64 * 1024 * 1024 if hls else MAX_FILE):
                continue
            height = int(source['height']) if source.get('height') and kind == 'video' else None
            key = (kind, ext, height)
            if key in seen:
                continue
            validate_url(media_url)
            seen.add(key)
            options.append({'kind': kind, 'format': ext, 'height': height, 'size': size, 'codec': source.get('vcodec'),
                            'delivery': 'hls' if hls else 'direct',
                            'ticket': sign_source(media_url, source.get('http_headers') or info.get('http_headers'), 'm3u8' if hls else ext)})
            if len(options) >= 16:
                break
        if not options:
            raise ValueError('这个视频没有当前可保存的格式，可能需要合并分离音视频、使用不兼容的分片编码或超过 256 MB。')
        if worker_client.configured() and (any(option.get('delivery') == 'hls' for option in options) or (not any(option['kind'] == 'video' for option in options) and any(source.get('vcodec') not in (None, 'none') for source in sources))):
            raise ValueError('这个视频需要独立下载服务合并音视频。')
        result['options'] = options
        result['heights'] = sorted({item['height'] for item in options if item['kind'] == 'video' and item['height']}, reverse=True)
        result['recommended_height'] = next((item['height'] for item in options if item['kind'] == 'video' and str(item.get('codec') or '').lower().startswith(('avc', 'h264'))), result['heights'][0] if result['heights'] else None)
        result['size'] = next((item['size'] for item in options if item['kind'] == 'video'), None)
        result['cloud'] = True
        return result
    except Exception as exc:
        if worker_client.configured() and not attempted_worker:
            try:
                return worker_client.resolve(validate_url(url), sign_source, include_conversions=include_conversions)
            except Exception as worker_error:
                return {'id': hashlib.sha256((url + str(time.time())).encode()).hexdigest()[:32], 'url': url, 'status': 'error', 'error': friendly_error(worker_error)}
        return {'id': hashlib.sha256((url + str(time.time())).encode()).hexdigest()[:32], 'url': url, 'status': 'error', 'error': friendly_error(exc)}


class ParseBody(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)
    backend: Literal['auto', 'worker'] = 'auto'
    formats: bool = False


class ChunkBody(BaseModel):
    ticket: str = Field(min_length=20, max_length=30000)
    offset: int = Field(default=0, ge=0, le=MAX_FILE)


class PrepareBody(BaseModel):
    ticket: str = Field(min_length=20, max_length=30000)
    action: str = 'status'


@app.post('/api/prepare')
async def prepare_download(body: PrepareBody):
    if body.action not in ('start', 'status', 'pause', 'cancel', 'delete'):
        raise HTTPException(400, '无效的下载操作。')
    payload = await asyncio.to_thread(verify_source, body.ticket)
    if not payload.get('worker_job'):
        raise HTTPException(400, '这个任务不需要独立下载服务。')
    try:
        return await asyncio.to_thread(worker_client.prepare, payload, body.action)
    except ValueError as exc:
        raise HTTPException(502, str(exc))


@app.get('/api/backend-status')
async def backend_status():
    if not worker_client.configured():
        return {'configured': False, 'connected': False, 'message': '尚未连接独立下载服务', 'sessions': []}
    try:
        data = await asyncio.to_thread(worker_client.health)
        return {'configured': True, 'connected': True, 'ffmpeg': bool(data.get('ffmpeg')), 'sessions': data.get('sessions', []), 'public_adapters': data.get('public_adapters', []), 'message': '独立下载服务已连接'}
    except ValueError as exc:
        return {'configured': True, 'connected': False, 'message': str(exc), 'sessions': []}


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '1.0.0', 'mode': 'cloud', 'ffmpeg': False,
            'engine': yt_dlp.version.__version__, 'download_dir': '当前设备 · 浏览器文件缓存',
            'max_batch': 20, 'workers': 2, 'max_file_size': MAX_FILE, 'chunk_size': CHUNK,
            'configured': bool(os.environ.get('SHIYING_SIGNING_SECRET')), 'worker_configured': worker_client.configured()}


@app.get('/api/extractors')
def extractors(q: str = ''):
    return extraction_catalog(q[:128])


PLATFORM_GROUPS = {'domestic': [{'name': '今日头条',
               'hint': '完整下载 0.42 MB；开头、结尾解码通过',
               'status': '样例已通过',
               'verified': True,
               'sample_url': 'https://m.toutiao.com/is/T3IfTiM4gd4/',
               'stage': 'complete'},
              {'name': '哔哩哔哩',
               'hint': '当前 Vercel 云端访问公开视频页与接口均返回 412，未取得视频。',
               'status': '样例未通过',
               'verified': False,
               'sample_url': 'https://www.bilibili.com/video/BV13x41117TL',
               'stage': 'parse'},
              {'name': '小红书',
               'hint': '完整下载 21.71 MB；开头、结尾解码通过',
               'status': '样例已通过',
               'verified': True,
               'sample_url': 'https://xhslink.cn/o/2yvcfMeyqk5',
               'stage': 'complete'},
              {'name': '微博',
               'hint': '完整下载 1.81 MB；开头、结尾解码通过',
               'status': '样例已通过',
               'verified': True,
               'sample_url': 'https://m.weibo.cn/status/4189191225395228',
               'stage': 'complete'},
              {'name': '快手',
               'hint': '当前 yt-dlp 没有快手专用解析器，本项目也未实现快手适配，撤下支持声明。',
               'status': '尚未适配',
               'verified': False,
               'sample_url': None,
               'stage': 'engine_check'},
              {'name': '抖音',
               'hint': '完整下载 6.06 MB；开头、结尾解码通过',
               'status': '样例已通过',
               'verified': True,
               'sample_url': 'https://v.douyin.com/ey2D3MfLLVs/',
               'stage': 'complete'},
              {'name': '西瓜视频',
               'hint': '完整下载 239.26 MB；开头、结尾解码通过',
               'status': '样例已通过',
               'verified': True,
               'sample_url': 'https://www.ixigua.com/6996881461559165471/',
               'stage': 'complete'}],
 'international': [{'name': 'Dailymotion',
                    'hint': '分片合并能力已增加并通过固定媒体回归测试，但本轮新部署未能稳定取得平台分片，线上实测仍未通过。',
                    'status': '样例未通过',
                    'verified': False,
                    'sample_url': 'https://www.dailymotion.com/video/x5kesuj',
                    'stage': 'parse'},
                   {'name': 'Facebook',
                    'hint': '追加公开样例仍要求注册账号；未取得可下载媒体。',
                    'status': '样例未通过',
                    'verified': False,
                    'sample_url': 'https://www.facebook.com/radiokicksfm/videos/3676516585958356/',
                    'stage': 'parse'},
                   {'name': 'Instagram',
                    'hint': '完整下载 0.92 MB；开头、结尾解码通过；此样例无音轨',
                    'status': '样例已通过',
                    'verified': True,
                    'sample_url': 'https://www.instagram.com/reel/Chunk8-jurw/',
                    'stage': 'complete'},
                   {'name': 'Reddit',
                    'hint': '当前云端请求要求账号认证；未取得可下载媒体。',
                    'status': '样例未通过',
                    'verified': False,
                    'sample_url': 'https://www.reddit.com/r/aww/comments/90bu6w/heat_index_was_110_degrees_so_we_offered_him_a/',
                    'stage': 'parse'},
                   {'name': 'Streamable',
                    'hint': '完整下载 19.29 MB；开头、结尾解码通过',
                    'status': '样例已通过',
                    'verified': True,
                    'sample_url': 'https://streamable.com/dnd1',
                    'stage': 'complete'},
                   {'name': 'TikTok',
                    'hint': '完整下载 2.95 MB；开头、结尾解码通过',
                    'status': '样例已通过',
                    'verified': True,
                    'sample_url': 'https://www.tiktok.com/@scout2015/video/6718335390845095173',
                    'stage': 'complete'},
                   {'name': 'Vimeo',
                    'hint': '追加测试仍要求登录或拒绝云端访问，未取得可下载媒体。',
                    'status': '样例未通过',
                    'verified': False,
                    'sample_url': 'https://player.vimeo.com/video/54469442',
                    'stage': 'parse'},
                   {'name': 'X / Twitter',
                    'hint': '完整下载 1.40 MB；开头、结尾解码通过',
                    'status': '样例已通过',
                    'verified': True,
                    'sample_url': 'https://x.com/historyinmemes/status/1790637656616943991',
                    'stage': 'complete'},
                   {'name': 'YouTube',
                    'hint': 'YouTube 要求登录并确认不是机器人，当前云端无法完成此验证。',
                    'status': '样例未通过',
                    'verified': False,
                    'sample_url': 'https://youtu.be/EgVjw_-odnE',
                    'stage': 'parse'},
                   {'name': 'Pinterest',
                    'hint': '完整下载 3.24 MB；开头、结尾解码通过',
                    'status': '样例已通过',
                    'verified': True,
                    'sample_url': 'https://www.pinterest.com/pin/664281013778109217/',
                    'stage': 'complete'}]}
PLATFORM_CHECKED_AT = '2026-10-21T08:53:22.057165+00:00'

@app.get('/api/platforms')
def platforms():
    return {'groups': PLATFORM_GROUPS, 'checked_at': PLATFORM_CHECKED_AT,
            'passed': 10, 'total': 17,
            'note': '已核查 17 个平台：10 个样例完成线上解析、完整下载及开头/结尾解码，6 个样例未通过，1 个尚未适配。通过不代表任意链接均可下载；首页仅展示已通过的平台。本次复验 Pinterest，其余为历史样例记录。'}


@app.post('/api/parse')
async def parse(body: ParseBody):
    semaphore = asyncio.Semaphore(3)
    async def one(url):
        async with semaphore:
            return await asyncio.to_thread(parse_media, url, body.backend == 'worker', body.formats)
    return {'results': await asyncio.gather(*(one(url) for url in body.urls))}


@app.post('/api/chunk')
async def chunk(body: ChunkBody):
    payload = await asyncio.to_thread(verify_source, body.ticket)
    headers = payload['headers'] | {'Range': f'bytes={body.offset}-{body.offset + CHUNK - 1}', 'Accept-Encoding': 'identity'}
    target = payload['url']
    async with httpx.AsyncClient(timeout=httpx.Timeout(40, connect=15), follow_redirects=False,
                                 verify=os.environ.get('SSL_CERT_FILE') or True) as client:
        for _ in range(6):
            if not payload.get('worker_job'):
                await asyncio.to_thread(validate_url, target)
            request = client.build_request('GET', target, headers=headers)
            try:
                upstream = await client.send(request, stream=True)
            except httpx.HTTPError:
                raise HTTPException(502, '媒体服务器暂时无法连接，请暂停后重试。')
            if upstream.status_code in (301, 302, 303, 307, 308):
                if payload.get('worker_job'):
                    await upstream.aclose()
                    raise HTTPException(502, '独立下载服务不允许文件跳转，请检查连接地址。')
                location = upstream.headers.get('location')
                await upstream.aclose()
                if not location:
                    raise HTTPException(502, '媒体服务器返回了无效跳转。')
                next_target = urljoin(target, location)
                if urlsplit(next_target).hostname != urlsplit(target).hostname:
                    headers = {key: value for key, value in headers.items() if key.lower() != 'cookie'}
                target = next_target
                continue
            break
        else:
            raise HTTPException(502, '媒体地址跳转次数过多。')
        try:
            if upstream.status_code == 416:
                return Response(b'', headers={'X-Media-End': '1', 'X-Media-Total': str(body.offset)})
            if upstream.status_code not in (200, 206):
                raise HTTPException(502, f'媒体服务器拒绝了下载（{upstream.status_code}），请重新解析。')
            content_range = upstream.headers.get('content-range', '')
            match = re.match(r'bytes (\d+)-(\d+)/(\d+|\*)', content_range)
            total = int(match[3]) if match and match[3] != '*' else int(upstream.headers.get('content-length', 0)) if upstream.status_code == 200 else 0
            if total > MAX_FILE:
                raise HTTPException(413, '文件超过当前 Vercel 版本的 256 MB 上限。')
            if upstream.status_code == 206 and (not match or int(match[1]) != body.offset):
                raise HTTPException(502, '媒体服务器返回了错误的分段位置。')
            data = bytearray()
            skip = body.offset if upstream.status_code == 200 else 0
            async for block in upstream.aiter_raw():
                if skip:
                    skipped = min(skip, len(block))
                    skip -= skipped
                    block = block[skipped:]
                if block:
                    data.extend(block[:CHUNK - len(data)])
                if len(data) == CHUNK:
                    break
            ended = len(data) < CHUNK or bool(total and body.offset + len(data) >= total)
            media_type = upstream.headers.get('content-type', 'application/octet-stream').split(';')[0]
            return Response(bytes(data), media_type=media_type, headers={'X-Media-Total': str(total), 'X-Media-End': '1' if ended else '0'})
        except httpx.HTTPError:
            raise HTTPException(502, '媒体分段传输超时或中断，请暂停后重试，已下载的分段会保留。')
        finally:
            await upstream.aclose()


@app.get('/api/media')
async def media(ticket: str, request: Request):
    raw_range = request.headers.get('range', '')
    match = re.fullmatch(r'bytes=(\d+)-(\d*)', raw_range)
    offset = int(match[1]) if match else 0
    if offset > MAX_FILE:
        raise HTTPException(416, '预览位置超出文件范围。')
    result = await chunk(ChunkBody(ticket=ticket, offset=offset))
    data = result.body
    total = int(result.headers.get('x-media-total') or 0)
    if match and match[2]:
        data = data[:max(0, int(match[2]) - offset + 1)]
    headers = {'Accept-Ranges': 'bytes', 'Cache-Control': 'private, no-store'}
    if match and total:
        headers['Content-Range'] = f'bytes {offset}-{offset + len(data) - 1}/{total}'
    return Response(data, status_code=206 if match and total else 200,
                    media_type=result.headers.get('content-type', 'video/mp4'), headers=headers)


@app.get('/api/hls')
async def hls_manifest(ticket: str):
    """Rewrite an unencrypted VOD playlist to bounded, authenticated same-origin resources."""
    payload = await asyncio.to_thread(verify_source, ticket)
    if payload.get('ext') != 'm3u8':
        raise HTTPException(400, '无效的分片播放列表。')
    target, headers = payload['url'], payload['headers']
    async with httpx.AsyncClient(timeout=30, follow_redirects=False,
                                 verify=os.environ.get('SSL_CERT_FILE') or True) as client:
        for _ in range(6):
            await asyncio.to_thread(validate_url, target)
            async with client.stream('GET', target, headers=headers) as upstream:
                if upstream.status_code in (301, 302, 303, 307, 308):
                    location = upstream.headers.get('location')
                    if not location:
                        raise HTTPException(502, '播放列表跳转无效。')
                    next_target = urljoin(target, location)
                    if urlsplit(next_target).hostname != urlsplit(target).hostname:
                        headers = {k: v for k, v in headers.items() if k.lower() != 'cookie'}
                    target = next_target
                    continue
                if upstream.status_code != 200:
                    raise HTTPException(502, f'平台拒绝播放列表请求（{upstream.status_code}）。')
                content = bytearray()
                async for block in upstream.aiter_bytes():
                    content.extend(block)
                    if len(content) > 1024 * 1024:
                        raise HTTPException(413, '播放列表过大。')
                text = content.decode('utf-8-sig')
                break
        else:
            raise HTTPException(502, '播放列表跳转次数过多。')
    if not text.lstrip().startswith('#EXTM3U'):
        raise HTTPException(502, '平台没有返回有效播放列表。')
    if any(line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')) and 'METHOD=NONE' not in line for line in text.splitlines()):
        raise HTTPException(422, '暂不下载加密或受保护的分片视频。')
    if '#EXT-X-ENDLIST' not in text and '#EXT-X-STREAM-INF' not in text:
        raise HTTPException(422, '暂不下载直播或尚未结束的分片视频。')
    def resource(value):
        url = urljoin(target, value)
        validate_url(url)
        playlist = urlsplit(url).path.lower().endswith('.m3u8')
        sealed = sign_source(url, {k: v for k, v in headers.items() if k.lower() != 'cookie' or urlsplit(url).hostname == urlsplit(target).hostname}, 'm3u8' if playlist else 'segment')
        return '/api/' + ('hls' if playlist else 'media') + '?ticket=' + sealed
    lines = []
    for line in text.splitlines():
        if line.startswith('#'):
            line = re.sub(r'URI="([^"]+)"', lambda match: 'URI="' + resource(match[1]) + '"', line)
        elif line.strip():
            line = resource(line.strip())
        lines.append(line)
    return Response('\n'.join(lines) + '\n', media_type='application/vnd.apple.mpegurl')


# Development only: production serves Vite assets from Vercel's CDN.
if not os.environ.get('VERCEL'):
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    frontend = Path(__file__).resolve().parents[1] / 'dist'
    if frontend.exists():
        app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
