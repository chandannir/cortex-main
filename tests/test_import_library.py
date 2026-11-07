import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from annotation.import_library import import_records, record_to_entry

SEED = Path(__file__).resolve().parents[1] / 'annotation' / 'data' / 'yue_pref_001.json'


class ImportLibraryTests(unittest.TestCase):
    def test_maps_chosen_translation(self):
        record = json.loads(SEED.read_text(encoding='utf-8'))
        entry = record_to_entry(record)
        self.assertEqual(entry['phrase'], '你好叻呀！')
        self.assertEqual(entry['meaning'], "Wow, aren't you clever!")
        self.assertEqual(entry['romanization'], 'nei5 hou2 lek1 aa3')
        self.assertIn('[yue_pref_001]', entry['context'])

    def test_import_is_idempotent(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        try:
            db = Path(temp.name) / 'languages.db'
            first = import_records([SEED], database=db)
            second = import_records([SEED], database=db)
            self.assertEqual(first['inserted'], ['yue_pref_001'])
            self.assertEqual(second['skipped'], ['yue_pref_001'])
            conn = sqlite3.connect(db)
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE phrase='你好叻呀！'").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 1)
        finally:
            temp.cleanup()


if __name__ == '__main__':
    unittest.main()
