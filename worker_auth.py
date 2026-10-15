"""Server-only per-platform sessions. Credentials are read locally and never returned to the UI."""
import os
from pathlib import Path
from contextlib import contextmanager
from yt_dlp.cookies import YoutubeDLCookieJar
from engine import SafeYoutubeDL, ydl_options
from urllib.parse import urlsplit

PLATFORMS = {
 'youtube': ('youtube.com','youtu.be','google.com','googlevideo.com'),
 'bilibili': ('bilibili.com','b23.tv','bilivideo.com','hdslb.com'),
 'facebook': ('facebook.com','fb.watch','fbcdn.net'),
 'reddit': ('reddit.com','redd.it','redditmedia.com'),
 'vimeo': ('vimeo.com','vimeocdn.com'),
 'dailymotion': ('dailymotion.com','dai.ly','dmcdn.net'),
}
def platform_for(url):
 host=(urlsplit(url).hostname or '').lower()
 return next((name for name,domains in PLATFORMS.items()if any(host==d or host.endswith('.'+d)for d in domains)),None)
def cookie_file(name):
 directory=os.environ.get('SHIYING_COOKIE_DIR')
 if not directory or not name:return None
 path=Path(directory).resolve()/(name+'.txt')
 return path if path.is_file()else None

def session_status():
 return [{'platform':name,'configured':cookie_file(name)is not None,'verified':False}for name in PLATFORMS]

@contextmanager
def download_session(url, extra=None):
 with SafeYoutubeDL(ydl_options()|(extra or {})|{'max_filesize':256*1024*1024})as ydl:
  name=platform_for(url);path=cookie_file(name)
  if path:
   try:
    source=YoutubeDLCookieJar();source.load(path,ignore_discard=True,ignore_expires=False)
    jar=YoutubeDLCookieJar()
    for cookie in source:
     domain=cookie.domain.lstrip('.').lower()
     if any(domain==d or domain.endswith('.'+d)for d in PLATFORMS[name]):jar.set_cookie(cookie)
    jar.clear_expired_cookies();ydl.cookiejar=jar
   except Exception as exc:raise ValueError('登录会话文件无法读取，请在下载服务所在机器重新配置。')from exc
  yield ydl
