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

import httpx
import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from engine import SafeYoutubeDL, validate_url, metadata, friendly_error, ydl_options, extract_public_douyin, extract_public_xiaohongshu

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


def sign_source(url, headers, ext):
    allowed = {k: v for k, v in (headers or {}).items() if k.lower() in ('user-agent', 'referer', 'origin', 'accept', 'cookie')}
    payload = json.dumps({'url': url, 'headers': allowed, 'ext': ext, 'expires': time.time() + 4 * 3600}, separators=(',', ':')).encode()
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
        validate_url(payload['url'])
        return payload
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, '无效的视频下载地址，请重新解析链接。')


def parse_media(url):
    try:
        url = validate_url(url)
        info = extract_public_douyin(url)
        if info is None:
            info = extract_public_xiaohongshu(url)
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
        result = metadata(info, url)
        sources = sorted(info.get('formats') or [info], key=lambda f: (f.get('height') or 0, 1 if str(f.get('vcodec', '')).lower().startswith(('avc', 'h264')) else 0, f.get('tbr') or 0))
        options = []
        seen = set()
        for source in reversed(sources):
            media_url = source.get('url')
            ext = source.get('ext') or info.get('ext') or 'mp4'
            protocol = source.get('protocol') or urlsplit(media_url or '').scheme
            if not media_url or protocol not in ('http', 'https') or ext not in ('mp4', 'webm', 'mov', 'm4a', 'mp3', 'opus', 'ogg'):
                continue
            kind = 'audio' if source.get('vcodec') == 'none' or ext in ('m4a', 'mp3', 'opus', 'ogg') else 'video'
            # Only offer complete media. Separate tracks cannot be merged without a worker/storage.
            if kind == 'video' and source.get('acodec') == 'none':
                # Instagram also publishes complete, intentionally silent MP4s.
                silent_progressive = str(info.get('extractor_key', '')).startswith('Instagram') and source.get('vcodec') is None and str(source.get('format_id', '')).isdigit()
                if not silent_progressive:
                    continue
            size = source.get('filesize') or source.get('filesize_approx')
            if size and size > MAX_FILE:
                continue
            height = int(source['height']) if source.get('height') and kind == 'video' else None
            key = (kind, ext, height)
            if key in seen:
                continue
            validate_url(media_url)
            seen.add(key)
            options.append({'kind': kind, 'format': ext, 'height': height, 'size': size, 'codec': source.get('vcodec'),
                            'ticket': sign_source(media_url, source.get('http_headers') or info.get('http_headers'), ext)})
            if len(options) >= 16:
                break
        if not options:
            raise ValueError('这个视频只提供分离音视频、分片流或超过 256 MB 的格式，当前 Vercel 版本无法直接保存。请尝试其他公开视频。')
        result['options'] = options
        result['heights'] = sorted({item['height'] for item in options if item['kind'] == 'video' and item['height']}, reverse=True)
        result['recommended_height'] = next((item['height'] for item in options if item['kind'] == 'video' and str(item.get('codec') or '').lower().startswith(('avc', 'h264'))), result['heights'][0] if result['heights'] else None)
        result['size'] = next((item['size'] for item in options if item['kind'] == 'video'), None)
        result['cloud'] = True
        return result
    except Exception as exc:
        return {'id': hashlib.sha256((url + str(time.time())).encode()).hexdigest()[:32], 'url': url, 'status': 'error', 'error': friendly_error(exc)}


class ParseBody(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)


class ChunkBody(BaseModel):
    ticket: str = Field(min_length=20, max_length=30000)
    offset: int = Field(default=0, ge=0, le=MAX_FILE)


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '1.0.0', 'mode': 'cloud', 'ffmpeg': False,
            'engine': yt_dlp.version.__version__, 'download_dir': '当前设备 · 浏览器文件缓存',
            'max_batch': 20, 'workers': 2, 'max_file_size': MAX_FILE, 'chunk_size': CHUNK,
            'configured': bool(os.environ.get('SHIYING_SIGNING_SECRET'))}


PLATFORM_GROUPS = {'domestic': [{'name': '今日头条',
               'hint': '完整下载 0.42 MB；开头、结尾解码通过',
               'status': '样例已通过',
               'verified': True,
               'sample_url': 'https://m.toutiao.com/is/T3IfTiM4gd4/',
               'stage': 'complete'},
              {'name': '哔哩哔哩',
               'hint': '平台暂时限制云端访问，请稍后重试。',
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
               'hint': '平台要求登录或人机验证，当前无法解析这个视频。可先尝试其他公开链接。',
               'status': '样例未通过',
               'verified': False,
               'sample_url': 'https://www.ixigua.com/6996881461559165471',
               'stage': 'parse'}],
 'international': [{'name': 'Dailymotion',
                    'hint': '这个视频只提供分离音视频、分片流或超过 256 MB 的格式，当前 Vercel 版本无法直接保存。请尝试其他公开视频。',
                    'status': '样例未通过',
                    'verified': False,
                    'sample_url': 'https://www.dailymotion.com/video/x5kesuj',
                    'stage': 'parse'},
                   {'name': 'Facebook',
                    'hint': '平台没有返回可用的视频信息。请确认链接可以公开播放，并重新复制完整分享链接后重试。',
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
                    'hint': '平台要求登录或人机验证，当前无法解析这个视频。可先尝试其他公开链接。',
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
                    'hint': '平台拒绝了请求（403），请稍后重试或重新解析链接。',
                    'status': '样例未通过',
                    'verified': False,
                    'sample_url': 'https://player.vimeo.com/video/54469442',
                    'stage': 'parse'},
                   {'name': 'X / Twitter',
                    'hint': '平台没有返回可用的视频信息。请确认链接可以公开播放，并重新复制完整分享链接后重试。',
                    'status': '样例未通过',
                    'verified': False,
                    'sample_url': 'https://twitter.com/starwars/status/665052190608723968',
                    'stage': 'parse'},
                   {'name': 'YouTube',
                    'hint': '平台要求登录或人机验证，当前无法解析这个视频。可先尝试其他公开链接。',
                    'status': '样例未通过',
                    'verified': False,
                    'sample_url': 'https://youtu.be/EgVjw_-odnE',
                    'stage': 'parse'}]}
PLATFORM_CHECKED_AT = '2026-10-15T04:42:04.842905+00:00'

@app.get('/api/platforms')
def platforms():
    return {'groups': PLATFORM_GROUPS, 'checked_at': PLATFORM_CHECKED_AT,
            'passed': 7, 'total': 16,
            'note': '本轮检查 16 个平台：7 个样例完成线上解析、完整下载及开头/结尾解码，8 个样例未通过，快手尚未适配。每个平台使用一个公开样例；结果不代表所有链接均可下载。首页仅展示本轮通过的平台。'}


@app.post('/api/parse')
async def parse(body: ParseBody):
    semaphore = asyncio.Semaphore(3)
    async def one(url):
        async with semaphore:
            return await asyncio.to_thread(parse_media, url)
    return {'results': await asyncio.gather(*(one(url) for url in body.urls))}


@app.post('/api/chunk')
async def chunk(body: ChunkBody):
    payload = await asyncio.to_thread(verify_source, body.ticket)
    headers = payload['headers'] | {'Range': f'bytes={body.offset}-{body.offset + CHUNK - 1}', 'Accept-Encoding': 'identity'}
    target = payload['url']
    async with httpx.AsyncClient(timeout=httpx.Timeout(40, connect=15), follow_redirects=False,
                                 verify=os.environ.get('SSL_CERT_FILE') or True) as client:
        for _ in range(6):
            await asyncio.to_thread(validate_url, target)
            request = client.build_request('GET', target, headers=headers)
            try:
                upstream = await client.send(request, stream=True)
            except httpx.HTTPError:
                raise HTTPException(502, '媒体服务器暂时无法连接，请暂停后重试。')
            if upstream.status_code in (301, 302, 303, 307, 308):
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


# Development only: production serves Vite assets from Vercel's CDN.
if not os.environ.get('VERCEL'):
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles
    frontend = Path(__file__).resolve().parents[1] / 'dist'
    if frontend.exists():
        app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
