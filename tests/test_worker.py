import hashlib,os,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from http.cookiejar import Cookie
import httpx
from yt_dlp.cookies import YoutubeDLCookieJar
from worker_auth import download_session
import worker_client
from api.index import sign_source,verify_source
from fastapi import HTTPException

def cookie(domain,name):
 return Cookie(0,name,'test-session',None,False,domain,True,True,'/',True,False,4102444800,False,None,None,{},False)
class WorkerSessionTests(unittest.TestCase):
 def test_only_target_platform_cookies_are_loaded_without_modifying_source(self):
  with tempfile.TemporaryDirectory()as directory:
   path=Path(directory)/'youtube.txt';source=YoutubeDLCookieJar(str(path));source.set_cookie(cookie('.youtube.com','yt'));source.set_cookie(cookie('.reddit.com','unrelated'));source.save();path.chmod(0o400)
   before=path.read_bytes();fake=MagicMock();fake.__enter__.return_value=fake
   with patch.dict(os.environ,{'SHIYING_COOKIE_DIR':directory}),patch('worker_auth.SafeYoutubeDL',return_value=fake):
    with download_session('https://youtu.be/test')as ydl:self.assertEqual([c.name for c in ydl.cookiejar],['yt'])
   self.assertEqual(path.read_bytes(),before)
class WorkerConnectionTests(unittest.TestCase):
 def setUp(self):
  patcher=patch.dict(os.environ,{'SHIYING_WORKER_URL':'http://127.0.0.1:8788','SHIYING_WORKER_TOKEN':'unit-test-service-token-1234567890123456','SHIYING_SIGNING_SECRET':'unit-test-signing-key','VERCEL':''});patcher.start();self.addCleanup(patcher.stop)
 def test_worker_key_is_encrypted_and_rotated_keys_invalidate_old_ticket(self):
  ident='a'*32;url,headers=worker_client.job_source(ident);sealed=sign_source(url,headers,'mp4',worker_job=ident)
  self.assertNotIn(headers['Authorization'],sealed)
  self.assertEqual(verify_source(sealed)['worker_job'],ident)
  with patch.dict(os.environ,{'SHIYING_WORKER_TOKEN':'changed-service-token-1234567890123456789'}),self.assertRaises(HTTPException):verify_source(sealed)
 def test_redirect_never_receives_service_key(self):
  real_client=httpx.Client;requested=[]
  def reply(request):requested.append(request.url.host);return httpx.Response(302,headers={'Location':'https://other.example/private'},request=request)
  with patch('worker_client.httpx.Client',lambda **kwargs:real_client(transport=httpx.MockTransport(reply))),self.assertRaises(ValueError):worker_client.request('GET','/api/health')
  self.assertEqual(requested,['127.0.0.1'])
 def test_worker_ticket_cannot_target_another_path(self):
  with self.assertRaises(ValueError):worker_client.validate_job({'worker_job':'a'*32,'url':'http://127.0.0.1:8788/admin','headers':{}})
 def test_production_requires_https(self):
  with patch.dict(os.environ,{'VERCEL':'1'}),self.assertRaises(ValueError):worker_client.configuration()
 def test_cloud_address_cannot_recursively_proxy_into_itself(self):
  with patch('worker_client.request',return_value={'mode':'cloud'})as request,self.assertRaises(ValueError):
   worker_client.resolve('https://youtu.be/test',lambda *args:None)
  self.assertEqual(request.call_count,1)
if __name__=='__main__':unittest.main()
