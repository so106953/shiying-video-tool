"""Vercel-to-worker connection. Only operator-configured origins receive the service credential."""
import os,re,json
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from engine import validate_url

def configuration():
 base=os.environ.get('SHIYING_WORKER_URL','').rstrip('/')
 token=os.environ.get('SHIYING_WORKER_TOKEN','')
 if not base and not token:return None
 parts=urlsplit(base)
 if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ('','/')or len(token)<32 or not token.isascii() or any(char.isspace() for char in token):
  raise ValueError('独立下载服务配置无效，请检查地址和服务密钥。')
 if os.environ.get('VERCEL'):
  if parts.scheme!='https':raise ValueError('线上独立下载服务必须使用 HTTPS。')
  validate_url(base)
 elif parts.scheme not in ('http','https'):
  raise ValueError('独立下载服务地址必须使用 HTTP 或 HTTPS。')
 return base,token

def configured():
 return bool(os.environ.get('SHIYING_WORKER_URL')and os.environ.get('SHIYING_WORKER_TOKEN'))

def preferred(url):
 host=(urlsplit(url).hostname or '').lower()
 return configured() and any(host==domain or host.endswith('.'+domain)for domain in ('youtube.com','youtu.be','bilibili.com','b23.tv','facebook.com','fb.watch','reddit.com','redd.it','vimeo.com','dailymotion.com','dai.ly'))

def request(method,path,body=None):
 config=configuration()
 if not config:raise ValueError('尚未连接独立下载服务，请先完成服务配置。')
 base,token=config
 try:
  with httpx.Client(timeout=httpx.Timeout(120,connect=15),follow_redirects=False,verify=os.environ.get('SSL_CERT_FILE')or True)as client:
   response=client.request(method,base+path,headers={'Authorization':'Bearer '+token},json=body)
  if response.is_redirect:raise ValueError('下载服务返回跳转，请配置最终 HTTPS 地址。')
  data=response.json()
  if response.status_code in (401,403):raise ValueError('独立下载服务密钥不匹配，请检查服务配置。')
  if response.status_code>=400:raise ValueError(data.get('detail')if isinstance(data.get('detail'),str)else'独立下载服务暂时不可用。')
  return data
 except httpx.HTTPError as exc:raise ValueError('独立下载服务无法连接或请求超时。')from exc
 except (TypeError,AttributeError,json.JSONDecodeError):raise ValueError('独立下载服务返回了无效响应。')

def job_source(ident):
 if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('下载任务编号无效。')
 base,token=configuration()
 return base+'/api/tasks/'+ident+'/file',{'Authorization':'Bearer '+token}

def health():
 data=request('GET','/api/health')
 if not isinstance(data,dict)or data.get('mode')!='worker':raise ValueError('配置地址不是独立下载服务，请勿填写拾影网页地址。')
 return {'ffmpeg':bool(data.get('ffmpeg')),'sessions':[{'platform':str(item.get('platform','')),'configured':bool(item.get('configured')),'verified':False}for item in data.get('sessions',[])if isinstance(item,dict)]}

def validate_job(payload):
 ident=payload.get('worker_job')
 expected,headers=job_source(ident or '')
 if payload.get('url')!=expected or payload.get('headers')!=headers:raise ValueError('独立下载服务凭据已变更，请重新解析。')
 return ident

def resolve(url,sign,include_conversions=False):
 if not health()['ffmpeg']:raise ValueError('独立下载服务尚未安装 FFmpeg，无法处理需要合并的视频。')
 parsed=request('POST','/api/parse',{'urls':[url]})['results'][0]
 if parsed.get('status')!='success':raise ValueError(parsed.get('error')or'独立下载服务没有获取到视频。')
 heights=sorted({int(h)for h in parsed.get('heights',[])if h},reverse=True)
 suitable=[h for h in heights if h<=1080]
 recommended=suitable[0]if suitable else heights[-1]if heights else None
 selected=[recommended]
 smaller=next((h for h in suitable if h<=480 and h!=recommended),None)
 if smaller:selected.append(smaller)
 options=[]
 specifications=[('video',ext,height)for height in selected for ext in (('mp4','mkv')if include_conversions else ('mp4',))]
 if include_conversions and parsed.get('has_audio',True):
  specifications.extend(('audio',ext,None)for ext in ('mp3','m4a'))
 for kind,ext,height in specifications:
  task=request('POST','/api/tasks',{'parsed_id':parsed['id'],'kind':kind,'format':ext,'height':height,'queued':True})
  source,headers=job_source(task['id'])
  options.append({'kind':kind,'format':ext,'height':height,'size':None,'codec':None,'delivery':'worker','ticket':sign(source,headers,ext,worker_job=task['id'])})
 return parsed|{'cloud':True,'options':options,'heights':[h for h in selected if h],'recommended_height':recommended,'size':None,'backend':'worker','expanded_formats':include_conversions}

def prepare(payload,action):
 ident=validate_job(payload)
 tasks=request('GET','/api/tasks')['tasks'];task=next((t for t in tasks if t['id']==ident),None)
 if not task:raise ValueError('独立下载任务已清理，请重新解析。')
 state=task['status']
 if action=='start'and state in ('paused','failed','cancelled'):task=request('POST',f'/api/tasks/{ident}/resume')
 elif action in ('pause','cancel'):
  accepted=('queued','downloading')if action=='pause'else('queued','downloading','paused','failed')
  if state in accepted:task=request('POST',f'/api/tasks/{ident}/{action}')
 elif action=='delete':
  request('DELETE',f'/api/tasks/{ident}');return {'status':'deleted'}
 if task.get('total',0)>256*1024*1024:raise ValueError('独立下载文件超过 256 MB，请选择较低画质。')
 return {key:task.get(key)for key in ('status','progress','downloaded','total','speed','eta','error')}
