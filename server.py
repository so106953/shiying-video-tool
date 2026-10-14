"""Local, same-origin video parser and resumable download service."""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import shutil
import socket
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('SHIYING_DATA_DIR', ROOT / 'data')).resolve()
FILES = DATA / 'downloads'
FILES.mkdir(parents=True, exist_ok=True)
DB = DATA / 'shiying.sqlite3'
WORKERS: list[threading.Thread] = []
SHUTDOWN = threading.Event()
WAKE = threading.Event()
LOCK = threading.RLock()
ACTIVE: set[str] = set()
PARSE_SLOTS = threading.BoundedSemaphore(3)
HAS_FFMPEG = bool(shutil.which('ffmpeg'))


def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    return db


with connect() as db:
    db.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS parsed (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL);
    ''')


def task_get(ident: str):
    with connect() as db:
        row = db.execute('SELECT payload FROM tasks WHERE id=?', (ident,)).fetchone()
    if not row:
        raise HTTPException(404, '下载任务不存在')
    return json.loads(row['payload'])


def task_update(ident: str, **changes):
    with LOCK:
        task = task_get(ident)
        task.update(changes)
        with connect() as db:
            db.execute('UPDATE tasks SET payload=? WHERE id=?', (json.dumps(task, ensure_ascii=False), ident))
        return task


def tasks_all():
    with connect() as db:
        return [json.loads(r['payload']) for r in db.execute('SELECT payload FROM tasks ORDER BY created DESC LIMIT 200')]


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


def ydl_options():
    return {'quiet': True, 'no_warnings': True, 'logger': QuietLog(), 'noplaylist': True, 'compat_opts': {'no-certifi'},
            'socket_timeout': 15, 'retries': 1, 'extractor_retries': 1,
            'cachedir': False, 'restrictfilenames': False, 'windowsfilenames': True,
            'max_filesize': 8 * 1024**3, 'skip_unavailable_fragments': False}


def friendly_error(error):
    raw = re.sub(r'\x1b\[[0-9;]*m', '', str(error)).removeprefix('ERROR: ').strip()
    low = raw.lower()
    if 'unsupported url' in low:
        return '暂不支持这个链接。请使用视频详情页或 MP4/WebM 直链。'
    if any(word in low for word in ['sign in', 'login', 'cookies', 'not a bot', 'fresh cookies']):
        return '平台要求登录或人机验证，当前无法解析这个视频。可先尝试其他公开链接。'
    if any(word in low for word in ['private video', 'removed', 'not available', '404', 'unavailable']):
        return '视频不存在、已设为私密或在当前地区不可用。'
    if '403' in low:
        return '平台拒绝了请求（403），请稍后重试或重新解析链接。'
    if any(word in low for word in ['timeout', 'timed out', 'network', 'connection']):
        return '网络请求失败或超时，请检查网络后重试。'
    if 'ffmpeg' in low:
        return '这个格式需要 FFmpeg。请安装 FFmpeg 并重启服务。'
    return raw[:300] or '解析失败，请检查链接后重试。'


def metadata(info, url):
    formats = info.get('formats') or [info]
    heights = sorted({int(f['height']) for f in formats if f.get('height') and f.get('vcodec') != 'none'}, reverse=True)
    sizes = [f.get('filesize') or f.get('filesize_approx') for f in formats if f.get('vcodec') != 'none']
    platform = info.get('extractor_key') or info.get('extractor') or '媒体直链'
    platform = {'BiliBili': '哔哩哔哩', 'Youtube': 'YouTube', 'Douyin': '抖音', 'TikTok': 'TikTok', 'Generic': '媒体直链'}.get(platform, platform)
    direct = info.get('direct') or (str(info.get('extractor_key', '')).lower() == 'generic' and urlsplit(url).path.lower().endswith(('.mp4', '.webm', '.mov', '.mp3', '.m4a')))
    return {'id': uuid.uuid4().hex, 'url': url, 'title': info.get('title') or Path(urlsplit(url).path).name or '视频',
            'platform': platform, 'uploader': info.get('uploader') or info.get('channel') or urlsplit(url).hostname,
            'thumbnail': info.get('thumbnail'), 'duration': info.get('duration'), 'heights': heights,
            'size': max((s for s in sizes if s), default=None), 'ext': info.get('ext') or 'mp4',
            'direct': bool(direct), 'created': time.time(), 'status': 'success'}


def parse_one(url):
    validate_url(url)
    with SafeYoutubeDL(ydl_options()) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info or info.get('_type') in ('playlist', 'multi_video'):
        raise ValueError('请使用单个视频的详情页链接，暂不支持整份播放列表。')
    result = metadata(info, url)
    with connect() as db:
        db.execute('INSERT INTO parsed VALUES (?,?,?)', (result['id'], json.dumps(result, ensure_ascii=False), result['created']))
        db.execute('DELETE FROM parsed WHERE id IN (SELECT id FROM parsed ORDER BY created DESC LIMIT -1 OFFSET 500)')
    return result


def parse_guarded(url):
    with PARSE_SLOTS:
        try:
            return parse_one(url)
        except Exception as exc:
            return {'id': uuid.uuid4().hex, 'url': url, 'status': 'error', 'error': friendly_error(exc)}


class Interrupted(Exception): pass


def perform_download(ident):
    task = task_get(ident)
    folder = FILES / ident
    folder.mkdir(exist_ok=True)
    last_update = [0.0]
    latest_bytes = [0]

    def check_action():
        if SHUTDOWN.is_set() or task_get(ident)['status'] in ('pausing', 'cancelling'):
            raise Interrupted('任务已中断')

    def hook(progress):
        check_action()
        now = time.monotonic()
        if progress['status'] == 'downloading' and now - last_update[0] > .35:
            last_update[0] = now
            downloaded = progress.get('downloaded_bytes') or 0
            total = progress.get('total_bytes') or progress.get('total_bytes_estimate') or 0
            latest_bytes[0] = downloaded
            task_update(ident, status='downloading', downloaded=downloaded, total=total,
                        progress=min(99, round(downloaded / total * 100, 1)) if total else 0,
                        speed=progress.get('speed') or 0, eta=progress.get('eta'))
        elif progress['status'] == 'finished':
            latest_bytes[0] = progress.get('downloaded_bytes') or latest_bytes[0]
            task_update(ident, status='processing', downloaded=latest_bytes[0], speed=0, eta=None)

    opts = ydl_options() | {'outtmpl': str(folder / '%(title).160B.%(ext)s'), 'progress_hooks': [hook],
                           'continuedl': True, 'overwrites': False, 'retries': 3, 'fragment_retries': 3}
    height = task['height']
    limit = f'[height<={height}]' if height else ''
    if task['kind'] == 'audio':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': task['format'], 'preferredquality': '192'}]
    elif HAS_FFMPEG:
        if task['format'] == 'mp4':
            opts['format'] = f'bestvideo{limit}[ext=mp4]+bestaudio[ext=m4a]/best{limit}[ext=mp4]/best{limit}'
        else:
            opts['format'] = f'bestvideo{limit}+bestaudio/best{limit}'
        opts['merge_output_format'] = task['format']
        opts['postprocessors'] = [{'key': 'FFmpegVideoRemuxer', 'preferedformat': task['format']}]
    else:
        opts['format'] = f'best{limit}[ext=mp4]/best{limit}'
    try:
        check_action()
        with SafeYoutubeDL(opts) as ydl:
            ydl.download([task['url']])
        check_action()
        complete_files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ('.mp4', '.webm', '.mkv', '.mov', '.mp3', '.m4a', '.ogg', '.opus')]
        if not complete_files:
            raise RuntimeError('没有生成可下载文件，请重试。')
        output = max(complete_files, key=lambda p: p.stat().st_mtime)
        task_update(ident, status='completed', progress=100, downloaded=output.stat().st_size,
                    total=output.stat().st_size, filename=output.name, speed=0, eta=None, error=None, completed=time.time())
    except Exception as exc:
        state = task_get(ident)['status']
        if state == 'cancelling':
            shutil.rmtree(folder, ignore_errors=True)
            task_update(ident, status='cancelled', speed=0, error=None)
        elif state == 'pausing' or SHUTDOWN.is_set():
            task_update(ident, status='paused', speed=0, eta=None, error=None)
        else:
            task_update(ident, status='failed', error=friendly_error(exc), speed=0, eta=None)


def worker():
    while not SHUTDOWN.is_set():
        with LOCK:
            pending = next((t for t in reversed(tasks_all()) if t['status'] == 'queued' and t['id'] not in ACTIVE), None)
            if pending:
                ident = pending['id']
                ACTIVE.add(ident)
                task_update(ident, status='downloading')
        if not pending:
            WAKE.wait(1)
            WAKE.clear()
            continue
        try:
            perform_download(ident)
        finally:
            with LOCK:
                ACTIVE.discard(ident)


@asynccontextmanager
async def lifespan(app):
    SHUTDOWN.clear()
    for task in tasks_all():
        if task['status'] in ('downloading', 'processing', 'pausing', 'cancelling'):
            task_update(task['id'], status='paused', speed=0, error='服务已重启，可以继续下载。')
    for _ in range(2):
        thread = threading.Thread(target=worker, daemon=True)
        WORKERS.append(thread)
        thread.start()
    yield
    SHUTDOWN.set()
    WAKE.set()
    for thread in WORKERS:
        thread.join(timeout=2)
    WORKERS.clear()


app = FastAPI(title='拾影本地下载服务', lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware('http')
async def same_origin(request: Request, call_next):
    host = request.url.hostname or ''
    host_ok = host in ('localhost', 'testserver')
    if not host_ok:
        try:
            address = ipaddress.ip_address(host)
            host_ok = address.is_private or address.is_loopback
        except ValueError:
            pass
    if not host_ok:
        return JSONResponse({'detail': '请使用 localhost 或本机局域网 IP 访问'}, 403)
    origin = request.headers.get('origin')
    if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
        return JSONResponse({'detail': '拒绝跨站请求，请从拾影页面操作'}, 403)
    if request.method in ('POST', 'PATCH', 'PUT'):
        try:
            if int(request.headers.get('content-length', 0)) > 32768:
                return JSONResponse({'detail': '请求内容过大'}, 413)
        except ValueError:
            return JSONResponse({'detail': '无效的请求'}, 400)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response


class ParseBody(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)


class DownloadBody(BaseModel):
    parsed_id: str = Field(min_length=32, max_length=32)
    height: int | None = Field(default=None, ge=1, le=16384)
    kind: str = 'video'
    format: str = 'mp4'
    queued: bool = False


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '1.0.0', 'ffmpeg': HAS_FFMPEG, 'engine': yt_dlp.version.__version__,
            'download_dir': str(FILES), 'max_batch': 20, 'workers': 2}


@app.post('/api/parse')
async def parse(body: ParseBody):
    return {'results': await asyncio.gather(*(asyncio.to_thread(parse_guarded, url) for url in body.urls))}


@app.get('/api/history')
def history():
    with connect() as db:
        return {'results': [json.loads(r['payload']) for r in db.execute('SELECT payload FROM parsed ORDER BY created DESC LIMIT 100')]}


@app.delete('/api/history')
def clear_history():
    # Keep entries referenced by queued downloads; the UI history is intentionally all remaining parses.
    with connect() as db:
        db.execute('DELETE FROM parsed')
    return {'ok': True}


@app.post('/api/tasks')
def create_download(body: DownloadBody):
    if body.kind not in ('video', 'audio') or body.format not in (('mp4', 'mkv') if body.kind == 'video' else ('mp3', 'm4a')):
        raise HTTPException(400, '不支持的媒体类型或格式')
    if not HAS_FFMPEG and (body.kind == 'audio' or body.format != 'mp4'):
        raise HTTPException(400, '音频提取和格式转换需要 FFmpeg，请安装后重启服务。')
    with connect() as db:
        row = db.execute('SELECT payload FROM parsed WHERE id=?', (body.parsed_id,)).fetchone()
    if not row:
        raise HTTPException(404, '解析结果已过期，请重新解析链接。')
    parsed = json.loads(row['payload'])
    if body.height and body.height not in parsed['heights']:
        raise HTTPException(400, '此视频没有这个清晰度，请选择实际可用画质。')
    with LOCK:
        if sum(t['status'] in ('queued', 'downloading', 'processing', 'pausing') for t in tasks_all()) >= 30:
            raise HTTPException(429, '任务队列已满，请完成当前下载后再添加。')
        task = {'id': uuid.uuid4().hex, 'parsed_id': parsed['id'], 'url': parsed['url'], 'title': parsed['title'],
                'thumbnail': parsed['thumbnail'], 'platform': parsed['platform'], 'kind': body.kind,
                'format': body.format, 'height': body.height, 'status': 'paused' if body.queued else 'queued',
                'created': time.time(), 'progress': 0, 'downloaded': 0, 'total': 0, 'speed': 0, 'eta': None,
                'filename': None, 'error': None}
        with connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?)', (task['id'], json.dumps(task, ensure_ascii=False), task['created']))
    WAKE.set()
    return task


@app.get('/api/tasks')
def list_downloads():
    return {'tasks': tasks_all()}


@app.post('/api/tasks/{ident}/{action}')
def action_download(ident: str, action: str):
    with LOCK:
        task = task_get(ident)
        state = task['status']
        if action == 'pause' and state in ('queued', 'downloading'):
            task = task_update(ident, status='pausing' if ident in ACTIVE else 'paused')
        elif action in ('resume', 'retry') and state in ('paused', 'failed', 'cancelled'):
            task = task_update(ident, status='queued', error=None)
        elif action == 'cancel' and state in ('queued', 'downloading', 'paused', 'failed'):
            task = task_update(ident, status='cancelling' if ident in ACTIVE else 'cancelled', speed=0)
        else:
            raise HTTPException(409, '当前任务状态不支持此操作，请刷新后重试。')
    WAKE.set()
    return task


@app.delete('/api/tasks/{ident}')
def remove_download(ident: str):
    with LOCK:
        task = task_get(ident)
        if ident in ACTIVE or task['status'] in ('queued', 'downloading', 'processing', 'pausing', 'cancelling'):
            raise HTTPException(409, '请先暂停或取消正在进行的任务。')
        with connect() as db:
            db.execute('DELETE FROM tasks WHERE id=?', (ident,))
        shutil.rmtree(FILES / ident, ignore_errors=True)
    return {'ok': True}


@app.get('/api/tasks/{ident}/file')
def download_file(ident: str, preview: bool = False):
    task = task_get(ident)
    if task['status'] != 'completed' or not task['filename']:
        raise HTTPException(409, '文件尚未完成，请等待下载完成。')
    file = (FILES / ident / task['filename']).resolve()
    if not file.is_relative_to(FILES) or not file.is_file():
        raise HTTPException(404, '文件已被移动或删除，请重新下载。')
    return FileResponse(file, filename=task['filename'], content_disposition_type='inline' if preview else 'attachment')


if (ROOT / 'dist').exists():
    app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True), name='frontend')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='拾影：视频解析与本地下载')
    parser.add_argument('--host', default='127.0.0.1', help='局域网手机访问可使用 0.0.0.0；仅在可信网络使用')
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    import uvicorn
    print(f'拾影已启动：http://{args.host}:{args.port}（手机请使用电脑局域网 IP）')
    uvicorn.run(app, host=args.host, port=args.port)
