"""Run explicitly on your own machine. Save only the selected platform's browser session."""
import argparse,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from yt_dlp.cookies import extract_cookies_from_browser,YoutubeDLCookieJar
from worker_auth import PLATFORMS
parser=argparse.ArgumentParser(description='从自己的浏览器读取会话，只保存选定平台的域名；不会上传。')
parser.add_argument('platform',choices=PLATFORMS)
parser.add_argument('--browser',choices=['chrome','chromium','edge','firefox','brave','opera','vivaldi','safari'],required=True)
parser.add_argument('--profile',help='选填：本机浏览器配置目录')
parser.add_argument('--output-dir',default='sessions')
args=parser.parse_args()
source=extract_cookies_from_browser(args.browser,profile=args.profile)
output=Path(args.output_dir).resolve();output.mkdir(mode=0o700,parents=True,exist_ok=True)
jar=YoutubeDLCookieJar(str(output/(args.platform+'.txt')))
for cookie in source:
 domain=cookie.domain.lstrip('.').lower()
 if any(domain==d or domain.endswith('.'+d)for d in PLATFORMS[args.platform]):jar.set_cookie(cookie)
jar.clear_expired_cookies()
if not len(jar):raise SystemExit('没有找到这个平台的有效会话，请先在自己的浏览器登录该平台。')
# Create permissions before writing, including on shared machines.
fd=os.open(jar.filename,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600);os.close(fd);os.chmod(jar.filename,0o600)
jar.save(ignore_discard=True,ignore_expires=False)
print('会话已保存到本机受限目录；未上传，也未验证平台实际下载。')
