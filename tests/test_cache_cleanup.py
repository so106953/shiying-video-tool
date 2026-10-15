import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class CacheCleanupTests(unittest.TestCase):
    def test_expired_files_removed_but_active_and_recent_reads_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(server, 'DB', root / 'db.sqlite'), patch.object(server, 'FILES', root), \
                    patch.object(server, 'ACTIVE', {'active'}), \
                    patch.dict('os.environ', {'SHIYING_CACHE_TTL_SECONDS': '3600'}):
                with server.connect() as db:
                    db.executescript('CREATE TABLE tasks (id TEXT PRIMARY KEY, payload TEXT);'
                                     'CREATE TABLE parsed (created REAL);')
                    for ident in ('expired', 'active', 'recent', 'queued'):
                        task = {'created': time.time() - 7200, 'status': 'completed'}
                        if ident == 'recent':
                            task['last_access'] = time.time()
                        if ident == 'queued':
                            task['status'] = 'queued'
                        db.execute('INSERT INTO tasks VALUES (?, ?)', (ident, json.dumps(task)))
                        (root / ident).mkdir()
                        (root / ident / 'video.mp4').write_bytes(b'cached media')
                server.cleanup_expired()
                self.assertFalse((root / 'expired').exists())
                for ident in ('active', 'recent', 'queued'):
                    self.assertTrue((root / ident / 'video.mp4').exists())
                with server.connect() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 3)


if __name__ == '__main__':
    unittest.main()
