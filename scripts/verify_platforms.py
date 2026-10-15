"""Verify the deployed API with real public samples; never store media tickets or cookies.
Set SHIYING_VERIFY_URL and optional SHIYING_VERIFY_BYPASS in the process environment.
Outputs a JSON report and temporary media files; ffprobe/ffmpeg verify complete downloads.
"""
import concurrent.futures, datetime, hashlib, json, os, pathlib, subprocess, tempfile
import httpx
CASES = [
 ('domestic','抖音','https://v.douyin.com/ey2D3MfLLVs/'),
 ('domestic','今日头条','https://m.toutiao.com/is/T3IfTiM4gd4/'),
 ('domestic','小红书','https://xhslink.cn/o/2yvcfMeyqk5'),
 ('domestic','哔哩哔哩','https://www.bilibili.com/video/BV13x41117TL'),
 ('domestic','微博','https://m.weibo.cn/status/4189191225395228'),
 ('domestic','西瓜视频','https://www.ixigua.com/6996881461559165471'),
 ('international','YouTube','https://youtu.be/EgVjw_-odnE'),
 ('international','TikTok','https://www.tiktok.com/@scout2015/video/6718335390845095173'),
 ('international','Instagram','https://www.instagram.com/reel/Chunk8-jurw/'),
 ('international','X / Twitter','https://twitter.com/starwars/status/665052190608723968'),
 ('international','Vimeo','https://player.vimeo.com/video/54469442'),
 ('international','Facebook','https://www.facebook.com/radiokicksfm/videos/3676516585958356/'),
 ('international','Dailymotion','https://www.dailymotion.com/video/x5kesuj'),
 ('international','Reddit','https://www.reddit.com/r/aww/comments/90bu6w/heat_index_was_110_degrees_so_we_offered_him_a/'),
 ('international','Streamable','https://streamable.com/dnd1'),
]
def verify(case):
 group,name,url=case
 row={'group':group,'name':name,'url':url,'status':'failed','stage':'parse'}
 headers={}
 if os.environ.get('SHIYING_VERIFY_BYPASS'):headers['x-vercel-protection-bypass']=os.environ['SHIYING_VERIFY_BYPASS']
 try:
  with httpx.Client(base_url=os.environ.get('SHIYING_VERIFY_URL','http://127.0.0.1:8787'),headers=headers,timeout=180,verify=os.environ.get('SSL_CERT_FILE')or True)as c:
   r=c.post('/api/parse',json={'urls':[url]});r.raise_for_status();item=r.json()['results'][0]
   if item['status']!='success':row['error']=item.get('error','解析失败');return row
   row['title']=item.get('title');row['stage']='download'
   options=[o for o in item['options']if o['kind']=='video']
   if not options:row['error']='没有完整视频格式';return row
   option=next((o for o in options if str(o.get('codec')or'').startswith(('h264','avc'))),options[0])
   row.update(format=option['format'],height=option.get('height'),codec=option.get('codec'))
   with tempfile.TemporaryDirectory(prefix='shiying-verify-')as tmp:
    path=pathlib.Path(tmp)/('media.'+option['format']);offset=0;digest=hashlib.sha256();complete=False
    with path.open('wb')as output:
     for _ in range(87):
      r=c.post('/api/chunk',json={'ticket':option['ticket'],'offset':offset})
      if r.status_code!=200:
       row['error']=r.json().get('detail','媒体请求失败');return row
      data=r.content;output.write(data);digest.update(data);offset+=len(data)
      if r.headers.get('x-media-end')=='1':complete=True;break
      if not data:break
    if not complete or not offset:row['error']='下载没有正常结束';return row
    row.update(bytes=offset,sha256=digest.hexdigest(),stage='media_check')
    result=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,codec_name,width,height','-of','json',str(path)],capture_output=True,text=True,timeout=30,check=True)
    probe=json.loads(result.stdout);row['media']=probe
    if not any(s.get('codec_type')=='video'for s in probe.get('streams',[])):row['error']='文件没有视频轨';return row
    duration=float(probe.get('format',{}).get('duration')or 0)
    for at in (0,max(0,duration-2)):
     subprocess.run(['ffmpeg','-v','error','-xerror','-ss',str(at),'-i',str(path),'-t','1','-f','null','-'],capture_output=True,timeout=45,check=True)
    row.update(status='passed',stage='complete',decoded_start_and_end=True)
 except Exception as exc:
  # Never serialize URLs, response headers or tickets from HTTP exceptions.
  row['error']=type(exc).__name__ if not isinstance(exc,subprocess.CalledProcessError)else'媒体解码检查失败'
 return row
if __name__=='__main__':
 report={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'deployment':os.environ.get('SHIYING_VERIFY_URL','http://127.0.0.1:8787'),'scope':'一个公开样例/平台；完整下载、媒体轨检查、开头和结尾解码；不是所有链接保证','results':[]}
 with concurrent.futures.ThreadPoolExecutor(max_workers=3)as pool:
  jobs={pool.submit(verify,c):c for c in CASES}
  for job in concurrent.futures.as_completed(jobs):
   row=job.result();report['results'].append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
   pathlib.Path('docs/platform-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 report['results'].append({'group':'domestic','name':'快手','status':'unsupported','stage':'engine_check','error':'当前 yt-dlp 没有快手专用解析器，本项目也未实现快手适配，撤下支持声明。'})
 report['results'].sort(key=lambda r:(r['group'],r['name']))
 pathlib.Path('docs/platform-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print('DONE',sum(r['status']=='passed'for r in report['results']),len(report['results']),flush=True)
