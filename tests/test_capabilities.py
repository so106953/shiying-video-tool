import unittest
from unittest.mock import patch
from engine import extraction_catalog
from worker_client import resolve


class FreeCapabilityTests(unittest.TestCase):
    def test_catalog_uses_installed_registry_and_never_claims_verified(self):
        data = extraction_catalog('知乎')
        self.assertTrue(data['items'][0]['available'])
        self.assertFalse(data['items'][0]['verified'])
        self.assertIn('Zhihu', data['items'][0]['extractors'])
        self.assertGreater(data['extractor_count'], 100)
        self.assertTrue(extraction_catalog('快手')['items'][0]['available'])
        self.assertFalse(extraction_catalog('快手')['items'][0]['verified'])
        self.assertEqual(extraction_catalog('nonexistent-platform-abc')['items'], [])

    def test_expanded_formats_are_real_paused_jobs_and_keep_legacy_defaults(self):
        jobs = []
        def request(method, path, body=None):
            if path == '/api/parse':
                return {'results': [{'id': 'p' * 32, 'status': 'success', 'heights': [1080, 480]}]}
            jobs.append(body)
            return {'id': f'{len(jobs):032x}'}
        with patch('worker_client.health', return_value={'ffmpeg': True}), \
                patch('worker_client.request', side_effect=request), \
                patch('worker_client.job_source', return_value=('https://worker.example/file', {})):
            legacy = resolve('https://video.example/test', lambda *a, **kw: 'sealed')
            self.assertEqual(len(legacy['options']), 2)
            jobs.clear()
            expanded = resolve('https://video.example/test', lambda *a, **kw: 'sealed', True)
        self.assertEqual({(o['kind'], o['format']) for o in expanded['options']},
                         {('video', 'mp4'), ('video', 'mkv'), ('audio', 'mp3'), ('audio', 'm4a')})
        self.assertTrue(all(job['queued'] for job in jobs))
        self.assertTrue(all(job['height'] is None for job in jobs if job['kind'] == 'audio'))
        self.assertTrue(expanded['expanded_formats'])


if __name__ == '__main__':
    unittest.main()
