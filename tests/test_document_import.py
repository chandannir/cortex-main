import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from document_import import extract_entries_from_document, parse_structured_text
from main import create_app


class DocumentImportTests(unittest.TestCase):
    def test_parse_dash_list(self):
        text = "你好 - hello\n谢谢 — thank you\n# comment\n世界: world\n"
        entries = parse_structured_text(text)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]['phrase'], '你好')
        self.assertEqual(entries[0]['meaning'], 'hello')

    def test_parse_csv(self):
        text = "phrase,meaning,pinyin\n我,I / me,wo3\n你,you,ni3\n"
        entries = parse_structured_text(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]['romanization'], 'ni3')

    def test_import_route_inserts_without_ai(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        try:
            db = Path(temp.name) / 'test.db'
            client = create_app(db).test_client()
            client.post('/languages', data=dict(name='Mandarin Chinese', voice='zh-CN'))
            payload = '水 - water\n火 - fire\n'
            response = client.post(
                '/languages/Mandarin%20Chinese/import',
                data={
                    'document': (io.BytesIO(payload.encode('utf-8')), 'words.txt'),
                    'use_ai': '0',
                },
                content_type='multipart/form-data',
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn('imported=2', response.headers['Location'])
            page = client.get('/?language=Mandarin+Chinese').get_data(as_text=True)
            self.assertIn('水', page)
            self.assertIn('火', page)
        finally:
            temp.cleanup()

    def test_delete_lesson(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        try:
            db = Path(temp.name) / 'test.db'
            client = create_app(db).test_client()
            lesson = {
                'overview': 'Overview',
                'useful_phrases': [{
                    'phrase': '我', 'romanization': '', 'translation': 'I',
                    'usage': 'Self', 'level_note': '',
                }],
                'practice': [
                    {'question': 'Q1', 'answer': 'A1'},
                    {'question': 'Q2', 'answer': 'A2'},
                ],
                'level': 'new',
            }
            with patch('main.generate_language_lesson', return_value=lesson):
                self.assertEqual(client.post('/languages/Cantonese/lesson', data={
                    'level': 'new'}).status_code, 303)
            page = client.get('/languages/Cantonese/lesson').get_data(as_text=True)
            self.assertIn('Delete this lesson', page)
            self.assertEqual(client.post('/languages/Cantonese/lesson/delete', data={
                'level': 'new', 'scope': 'current'}).status_code, 303)
            page = client.get('/languages/Cantonese/lesson').get_data(as_text=True)
            self.assertIn('Create practice lesson', page)
        finally:
            temp.cleanup()

    def test_ai_extract_uses_model(self):
        with patch('document_import.request_text', return_value='[{"phrase":"书","meaning":"book","romanization":"shu1"}]'):
            entries, mode = extract_entries_from_document('书\n', 'Mandarin Chinese', use_ai=True)
        self.assertEqual(mode, 'ai')
        self.assertEqual(entries[0]['phrase'], '书')


if __name__ == '__main__':
    unittest.main()
