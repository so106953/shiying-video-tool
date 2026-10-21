# Run explicitly: python tests/integration_formats.py (FFmpeg and public network required).
import os,sys,tempfile,pathlib,subprocess,secrets,time,httpx,hashlib,json
root=pathlib.Path.cwd();records=[]
with tempfile.TemporaryDirectory(prefix='shiying-formats-')as directory:
 env=os.environ|{'SHIYING_WORKER_URL':'http://127.0.0.1:8788','SHIYING_WORKER_TOKEN':secrets.token_hex(32),'SHIYING_SIGNING_SECRET':secrets.token_hex(32),'SHIYING_DATA_DIR':directory+'/data','SHIYING_COOKIE_DIR':directory+'/sessions'}
 processes=[]
 try:
  for app,port in [('worker:app','8788'),('api.index:app','8789')]:
   processes.append(subprocess.Popen([sys.executable,'-m','uvicorn',app,'--host','127.0.0.1','--port',port,'--log-level','warning'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
  c=httpx.Client(base_url='http://127.0.0.1:8789',timeout=180)
  for _ in range(100):
   try:c.get('/api/health').raise_for_status();break
   except Exception:time.sleep(.1)
  c.get('/api/backend-status').raise_for_status()
  catalog=c.get('/api/extractors',params={'q':'知乎'}).json();assert catalog['items'][0]['available']
  response=c.post('/api/parse',json={'urls':['https://www.w3schools.com/html/mov_bbb.mp4']});response.raise_for_status()
  item=response.json()['results'][0];assert item['status']=='success',item
  assert {(o['kind'],o['format'])for o in item['options']}=={('video','mp4'),('video','mkv'),('audio','mp3'),('audio','m4a')}
  for ext in ['mp4','mkv','mp3','m4a']:
   option=next(o for o in item['options']if o['format']==ext)
   state=c.post('/api/prepare',json={'ticket':option['ticket'],'action':'start'}).json()
   for _ in range(240):
    if state['status']in('completed','failed'):break
    time.sleep(.5);state=c.post('/api/prepare',json={'ticket':option['ticket'],'action':'status'}).json()
   assert state['status']=='completed',(ext,state)
   offset=0;parts=[]
   while True:
    r=c.post('/api/chunk',json={'ticket':option['ticket'],'offset':offset});r.raise_for_status();parts.append(r.content);offset+=len(r.content)
    if r.headers.get('x-media-end')=='1':break
   path=pathlib.Path(directory)/('saved.'+ext);path.write_bytes(b''.join(parts))
   probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration,format_name:stream=codec_type,codec_name','-of','json',str(path)]))
   kinds={s['codec_type']for s in probe['streams']};assert 'audio'in kinds
   assert ('video'in kinds)==(ext in('mp4','mkv'))
   assert float(probe['format']['duration'])>9
   subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'],capture_output=True,check=True)
   c.post('/api/prepare',json={'ticket':option['ticket'],'action':'delete'}).raise_for_status()
   result={'format':ext,'bytes':offset,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'duration':probe['format']['duration'],'streams':probe['streams'],'full_decode':True};records.append(result);print('FORMAT_OK',json.dumps(result),flush=True)
  print('LOCAL_FORMATS_ALL_PASSED',flush=True)
 finally:
  for p in processes:p.terminate()
  for p in processes:
   try:p.wait(timeout=5)
   except subprocess.TimeoutExpired:p.kill()
