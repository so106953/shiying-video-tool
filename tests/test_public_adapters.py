import json
import unittest
from unittest.mock import patch
import httpx
import platform_adapters as p

MEDIA = 'https://8.8.8.8/video.mp4'


class PublicAdapterTests(unittest.TestCase):
    def test_platform_hosts_are_exact_and_unknown_hosts_do_not_fetch(self):
        self.assertIsNone(p.platform_key('https://kuaishou.com.attacker.example/video'))
        self.assertIsNone(p.platform_key('https://notkuaishou.com/video'))
        with patch.object(p, 'fetch_page') as fetch:
            self.assertIsNone(p.extract_public_extra('https://example.com/test'))
            fetch.assert_not_called()

    def test_kuaishou_mobile_state_and_desktop_fallback(self):
        state = {'detail': {'result': 1, 'photo': {'caption': 'sample', 'duration': 15000,
                 'mainMvUrls': [{'url': MEDIA}], 'width': 720, 'height': 1280}}}
        html = '<script>window.INIT_STATE = ' + json.dumps(state) + ';</script>'
        with patch.object(p, 'fetch_page', side_effect=[
            ('https://www.kuaishou.com/short-video/abc123', '{"result":2}'),
            ('https://kphm5nf3.m.chenzhongtech.com/fw/photo/abc123', html),
        ]):
            info = p.kuaishou('https://www.kuaishou.com/short-video/abc123')
        self.assertEqual(info['duration'], 15)
        self.assertEqual(info['formats'][0]['url'], MEDIA)
        self.assertEqual(info['formats'][0]['height'], 1280)

    def test_haokan_checks_identity_and_paywall(self):
        video = {'id': '123', 'title': 'sample', 'playurl': MEDIA}
        def response(): return ('https://haokan.baidu.com/v', json.dumps({'data': {'apiData': {'curVideoMeta': video}}}))
        with patch.object(p, 'fetch_page', side_effect=lambda *a: response()):
            self.assertEqual(p.haokan('https://haokan.baidu.com/v?vid=123')['id'], '123')
            video['id'] = '456'
            with self.assertRaisesRegex(ValueError, '不同作品'): p.haokan('https://haokan.baidu.com/v?vid=123')
            video.update(id='123', is_pay_column=1, is_free=0)
            with self.assertRaisesRegex(ValueError, '付费'): p.haokan('https://haokan.baidu.com/v?vid=123')

    def test_pipixia_does_not_return_an_unrelated_comment_video(self):
        item = lambda ident: {'comment_info': {'item': {'item_id_str': ident, 'content': ident,
               'video': {'video_high': {'url_list': [{'url': MEDIA}]}}}}}
        payload = {'data': {'cell_comments': [item('999'), item('123')]}}
        with patch.object(p, 'fetch_page', return_value=('https://api.pipix.com/', json.dumps(payload))):
            self.assertEqual(p.pipixia('https://h5.pipix.com/ppx/item/123')['title'], '123')

    def test_tangdou_preserves_required_referer_and_rejects_paid_content(self):
        data = {'title': 'sample', 'video_url': MEDIA, 'duration': '42'}
        with patch.object(p, 'fetch_page', side_effect=lambda *a: ('https://api-h5.tangdou.com/', json.dumps({'data': data}))):
            info = p.tangdou('https://m.tangdou.com/play/123')
            self.assertEqual(info['formats'][0]['http_headers']['Referer'], 'https://www.tangdoucdn.com/')
            self.assertEqual(info['duration'], 42)
            data['is_vip'] = 1
            with self.assertRaisesRegex(ValueError, '会员'): p.tangdou('https://m.tangdou.com/play/123')

    def test_threads_matches_exact_post_and_ignores_neighbor(self):
        data = [{'code': 'other', 'video_versions': [{'url': MEDIA}]},
                {'code': 'requested', 'video_versions': []}]
        html = '<script type="application/json">' + json.dumps(data) + '</script>'
        with patch.object(p, 'fetch_page', return_value=('https://www.threads.com/@user/post/requested', html)):
            with self.assertRaisesRegex(ValueError, '没有返回公开'): p.structured_page('https://www.threads.com/@user/post/requested', 'Threads')

    def test_media_urls_and_redirects_cannot_reach_private_network(self):
        with self.assertRaises(ValueError): p.media_info('Kuaishou', '123', 'sample', ['http://127.0.0.1/private'])
        requests = []
        def reply(request):
            requests.append(str(request.url))
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
        real_client = httpx.Client
        with patch.object(p.httpx, 'Client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(reply))), self.assertRaises(ValueError):
            p.fetch_page('https://8.8.8.8/share')
        self.assertEqual(requests, ['https://8.8.8.8/share'])


if __name__ == '__main__':
    unittest.main()
