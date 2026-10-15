import unittest
from unittest.mock import patch,MagicMock
from engine import extract_public_ixigua
from yt_dlp.utils import DownloadError
class IxiguaFallbackTests(unittest.TestCase):
 def test_falls_back_to_native_page_without_losing_video_id(self):
  ydl=MagicMock();ydl.__enter__.return_value=ydl
  ydl.extract_info.side_effect=[DownloadError('public player unavailable'),{'id':'6996881461559165471','formats':[]}]
  with patch('engine.SafeYoutubeDL',return_value=ydl):
   result=extract_public_ixigua('https://www.ixigua.com/6996881461559165471?source=share')
  self.assertEqual(result['extractor_key'],'Ixigua')
  self.assertEqual(ydl.extract_info.call_args.args[0],'https://www.ixigua.com/6996881461559165471/?source=share')
 def test_rejects_different_video_from_public_player(self):
  ydl=MagicMock();ydl.__enter__.return_value=ydl;ydl.extract_info.return_value={'id':'111111'}
  with patch('engine.SafeYoutubeDL',return_value=ydl),self.assertRaises(ValueError):
   extract_public_ixigua('https://www.ixigua.com/6996881461559165471')
if __name__=='__main__':unittest.main()
