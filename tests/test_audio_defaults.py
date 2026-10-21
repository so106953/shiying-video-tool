"""The first parse offers audio; failures must preserve a downloadable video."""
import unittest
from unittest.mock import patch
from api.index import ParseBody, parse_media
import worker_client


class AudioDefaultsTests(unittest.TestCase):
    def test_default_parse_prepares_video_and_audio_together(self):
        body = ParseBody(urls=['https://example.com/video'])
        self.assertTrue(body.formats)
        expected = {'status': 'success', 'options': [{'kind': 'video'}, {'kind': 'audio'}]}
        with patch('api.index.validate_url', side_effect=lambda value: value), \
                patch('worker_client.resolve', return_value=expected) as resolve:
            result = parse_media(body.urls[0], include_conversions=body.formats)
        self.assertEqual(result, expected)
        self.assertTrue(resolve.call_args.kwargs['include_conversions'])

    def test_failed_audio_service_preserves_public_video_and_retry_reason(self):
        info = {'title': 'Public video', 'url': 'https://media.example.com/video.mp4',
                'ext': 'mp4', 'vcodec': 'h264', 'acodec': 'aac', 'height': 360}
        with patch('api.index.validate_url', side_effect=lambda value: value), \
                patch('worker_client.resolve', side_effect=ValueError('音频服务暂时不可用')), \
                patch('api.index.extract_public_extra', return_value=info), \
                patch('api.index.sign_source', return_value='signed-video'):
            result = parse_media('https://example.com/video', include_conversions=True)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['options'][0]['ticket'], 'signed-video')
        self.assertEqual(result['options'][0]['kind'], 'video')
        self.assertIn('音频服务暂时不可用', result['audio_error'])

    def test_worker_share_adapter_matches_cloud_parser(self):
        from engine import extract_public_media
        info = {'title': 'Public share', 'url': 'https://media.example.com/video.mp4'}
        with patch('engine.extract_public_extra', return_value=None), \
                patch('engine.extract_public_douyin', return_value=None), \
                patch('engine.extract_public_xiaohongshu', return_value=info) as xhs, \
                patch('engine.extract_public_ixigua') as other:
            self.assertEqual(extract_public_media('https://xhslink.cn/example'), info)
        xhs.assert_called_once()
        other.assert_not_called()

    def test_one_audio_format_failure_does_not_discard_other_formats(self):
        jobs = []
        def request(method, path, body=None):
            if path == '/api/parse':
                return {'results': [{'id': 'p' * 32, 'status': 'success', 'heights': [360], 'has_audio': True}]}
            jobs.append(body)
            if body['format'] == 'mp3':
                raise ValueError('MP3 准备失败')
            return {'id': f'{len(jobs):032x}'}
        with patch('worker_client.health', return_value={'ffmpeg': True}), \
                patch('worker_client.request', side_effect=request), \
                patch('worker_client.job_source', return_value=('https://worker.example/file', {})):
            result = worker_client.resolve('https://example.com/video', lambda *a, **kw: 'sealed', True)
        self.assertEqual({option['format'] for option in result['options']}, {'mp4', 'mkv', 'm4a'})
        self.assertIn('MP3 准备失败', result['audio_error'])
        self.assertTrue(all(job['queued'] for job in jobs))


if __name__ == '__main__':
    unittest.main()
