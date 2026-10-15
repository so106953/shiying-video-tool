# Run explicitly from the repository root; uses a public test video, not a platform login.
import os,sys,tempfile,pathlib,subprocess,secrets,time,httpx,hashlib,json,signal
root=pathlib.Path.cwd();token=secrets.token_hex(32);signing=secrets.token_hex(32)
with tempfile.TemporaryDirectory(prefix='shiying-worker-integration-')as directory:
 env=os.environ|{'SHIYING_WORKER_URL':'http://127.0.0.1:8788','SHIYING_WORKER_TOKEN':token,'SHIYING_SIGNING_SECRET':signing,'SHIYING_DATA_DIR':directory+'/data','SHIYING_COOKIE_DIR':directory+'/sessions'}
 processes=[]
 try:
  for app,port in [('worker:app','8788'),('api.index:app','8789')]:
   processes.append(subprocess.Popen([sys.executable,'-m','uvicorn',app,'--host','127.0.0.1','--port',port,'--log-level','warning'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE))
  c=httpx.Client(base_url='http://127.0.0.1:8789',timeout=180)
  for _ in range(100):
   try:
    r=c.get('/api/health');r.raise_for_status();break
   except Exception:time.sleep(.1)
  for _ in range(100):
   try:
    r=httpx.get('http://127.0.0.1:8788/api/health',headers={'Authorization':'Bearer '+token});r.raise_for_status();break
   except Exception:time.sleep(.1)
  assert httpx.get('http://127.0.0.1:8788/api/health').status_code==401
  status=c.get('/api/backend-status').json();assert status['connected']and status['ffmpeg'];print('CONNECTION_OK unauthorized=401 ffmpeg=true',flush=True)
  item=c.post('/api/parse',json={'urls':['https://www.w3schools.com/html/mov_bbb.mp4'],'backend':'worker'}).json()['results'][0]
  print('PARSE',item['status'],item.get('error'),flush=True);assert item['status']=='success'and item['backend']=='worker'
  option=item['options'][0];assert token not in json.dumps(item)
  state=c.post('/api/prepare',json={'ticket':option['ticket'],'action':'start'}).json()
  for _ in range(120):
   if state['status']in('completed','failed'):break
   time.sleep(.5);state=c.post('/api/prepare',json={'ticket':option['ticket'],'action':'status'}).json()
  print('PREPARE',state,flush=True);assert state['status']=='completed'
  offset=0;parts=[]
  while True:
   r=c.post('/api/chunk',json={'ticket':option['ticket'],'offset':offset});r.raise_for_status();parts.append(r.content);offset+=len(r.content)
   if r.headers.get('x-media-end')=='1':break
  path=pathlib.Path(directory)/'saved.mp4';path.write_bytes(b''.join(parts));probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(path)]));assert any(s['codec_type']=='video'for s in probe['streams'])
  subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-t','1','-f','null','-'],capture_output=True,check=True)
  r=c.post('/api/prepare',json={'ticket':option['ticket'],'action':'delete'});r.raise_for_status();assert r.json()['status']=='deleted'
  print('END_TO_END_OK',{'bytes':offset,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'duration':probe['format']['duration'],'deleted':True,'credentials_in_response':False},flush=True)
 finally:
  for p in processes:p.terminate()
  for p in processes:
   try:p.wait(timeout=10)
   except subprocess.TimeoutExpired:p.kill()
