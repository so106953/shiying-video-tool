"""Playlist rewriting must preserve media access without admitting live/encrypted/internal URLs."""
import asyncio, os, unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
import httpx
from fastapi import HTTPException
from api.index import hls_manifest,sign_source,verify_source
from engine import validate_url

class HlsManifestTests(unittest.TestCase):
 def setUp(self):
  validator=patch('api.index.validate_url',side_effect=lambda url:validate_url(url,resolve=False))
  validator.start();self.addCleanup(validator.stop)
 def request(self,text,status=200,headers=None):
  real_client=httpx.AsyncClient
  def reply(request):return httpx.Response(status,headers=headers,text=text,request=request)
  with patch.dict(os.environ,{'SHIYING_SIGNING_SECRET':'unit-test-only'}), patch('api.index.httpx.AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(reply))):
   ticket=sign_source('https://example.com/video/index.m3u8',{},'m3u8')
   return asyncio.run(hls_manifest(ticket))
 def test_vod_rewrites_segments_into_sealed_resources(self):
  with patch.dict(os.environ,{'SHIYING_SIGNING_SECRET':'unit-test-only'}):
   result=self.request('#EXTM3U\n#EXTINF:2,\nfirst.ts\n#EXT-X-ENDLIST\n')
   resource=next(line for line in result.body.decode().splitlines()if not line.startswith('#'))
   self.assertTrue(resource.startswith('/api/media?ticket=v2.'))
   payload=verify_source(parse_qs(urlsplit(resource).query)['ticket'][0])
   self.assertEqual(payload['url'],'https://example.com/video/first.ts')
 def test_encrypted_and_live_streams_are_rejected(self):
  for text in ('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXT-X-ENDLIST', '#EXTM3U\n#EXTINF:2,\nfirst.ts'):
   with self.subTest(text=text),self.assertRaises(HTTPException)as error:self.request(text)
   self.assertEqual(error.exception.status_code,422)
 def test_internal_child_and_redirect_are_rejected(self):
  for text,status,headers in (('#EXTM3U\n#EXTINF:2,\nhttp://127.0.0.1/private\n#EXT-X-ENDLIST',200,None),('',302,{'Location':'http://127.0.0.1/private'})):
   with self.subTest(status=status),self.assertRaises(ValueError):self.request(text,status,headers)
if __name__=='__main__':unittest.main()
