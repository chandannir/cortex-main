import sqlite3
import io
from unittest.mock import patch
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from main import create_app


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'test.db'
        self.client = create_app(self.db).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_seed_survives_restart_without_duplicates(self):
        self.assertIn('我係…', self.client.get('/').get_data(as_text=True))
        create_app(self.db)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM entries').fetchone()[0], 1)

    def test_save_search_persist_and_escape(self):
        self.client.post('/languages', data=dict(name='Test', voice=''))
        response = self.client.post('/', data=dict(language='Test', phrase='<script>alert(1)</script>', meaning='Unique meaning'))
        self.assertEqual(response.status_code, 303)
        client = create_app(self.db).test_client()
        page = client.get('/?q=unique').get_data(as_text=True)
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script>alert', page)
        self.assertIn('No matching entries', client.get('/?q=absent').get_data(as_text=True))

    def test_invalid_input_not_saved(self):
        self.assertEqual(self.client.post('/', data={'language': ' '}).status_code, 400)
        self.assertEqual(self.client.post('/', data=dict(language='Cantonese', phrase='我', meaning='I', example='我係…')).status_code, 400)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM entries').fetchone()[0], 1)

    def test_collections_pronunciation_and_audio(self):
        self.assertEqual(self.client.post('/languages', data=dict(name='Mandarin Chinese', voice='zh-CN')).status_code, 303)
        self.client.post('/languages', data=dict(name='mandarin chinese', voice='zh-CN'))
        response = self.client.post('/', data=dict(language='Mandarin Chinese', phrase='我', meaning='I', romanization='Wǒ', audio=(io.BytesIO(b'RIFFtest'), 'word.wav')), content_type='multipart/form-data')
        self.assertEqual(response.status_code, 303)
        page = self.client.get('/?language=Mandarin+Chinese').get_data(as_text=True)
        self.assertIn('Wǒ', page)
        self.assertNotIn('我係…', page)
        with closing(sqlite3.connect(self.db)) as db:
            filename = db.execute("SELECT audio FROM entries WHERE romanization='Wǒ'").fetchone()[0]
            self.assertEqual(db.execute('SELECT COUNT(*) FROM languages').fetchone()[0], 2)
        response = self.client.get('/audio/' + filename)
        self.assertEqual(response.data, b'RIFFtest')
        response.close()
        bad = self.client.post('/', data=dict(language='Cantonese', phrase='x', meaning='x', audio=(io.BytesIO(b'x'), 'x.html')))
        self.assertEqual(bad.status_code, 400)

    def test_old_database_migrates(self):
        old = Path(self.temp.name) / 'old.db'
        with closing(sqlite3.connect(old)) as db:
            db.execute('CREATE TABLE entries(id INTEGER PRIMARY KEY, language TEXT, phrase TEXT, meaning TEXT, example TEXT, translation TEXT, context TEXT, created_at TEXT)')
            db.execute("INSERT INTO entries VALUES(1,'Custom','word','meaning','','','',NULL)")
            db.commit()
        client = create_app(old).test_client()
        self.assertIn('word', client.get('/?language=Custom').get_data(as_text=True))

    def test_language_lesson_cached_and_escaped(self):
        form = self.client.get('/languages/Cantonese/lesson').get_data(as_text=True)
        self.assertIn('Cantonese lesson', form)
        payload = {
            'overview': 'Learn 我 carefully. Meaning: I / me <script>',
            'useful_phrases': [{
                'phrase': '我',
                'romanization': '',
                'translation': 'I / me',
                'usage': 'Use for self-reference.',
                'level_note': 'Start here.',
            }],
            'practice': [
                {'question': 'What does 我 mean?', 'answer': 'I / me'},
                {'question': 'When do you use it?', 'answer': 'To refer to yourself.'},
            ],
            'level': 'new',
        }
        with patch('main.generate_language_lesson', return_value=payload) as generate:
            self.assertEqual(self.client.post('/languages/Cantonese/lesson', data={
                'level': 'new', 'preferred': 'English'}).status_code, 303)
            self.client.post('/languages/Cantonese/lesson', data={
                'level': 'new', 'preferred': 'English'})
            self.assertEqual(generate.call_count, 1)
        page = self.client.get('/languages/Cantonese/lesson', query_string={
            'level': 'new', 'preferred': 'English'}).get_data(as_text=True)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('Useful phrases for your level', page)
        self.assertIn('我', page)

    def test_attach_audio_to_existing_entry(self):
        response = self.client.post('/entries/1/audio', data={
            'audio': (io.BytesIO(b'RIFFdemo'), 'demo.wav'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 303)
        page = self.client.get('/?language=Cantonese').get_data(as_text=True)
        self.assertIn('controls', page)
        self.assertIn('/audio/', page)
        self.assertIn('Replace demo audio', page)

    def test_settings_persist(self):
        response = self.client.post('/settings', data={'ui_language': 'fr'})
        self.assertEqual(response.status_code, 200)
        page = self.client.get('/settings').get_data(as_text=True)
        self.assertIn('Réglages', page)
        self.assertIn('selected>Français', page)
        self.assertIn('French', page)
        self.assertNotIn('learning_language', page)
        lesson = self.client.get('/languages/Cantonese/lesson').get_data(as_text=True)
        self.assertIn('French', lesson)
        self.assertNotIn('name="preferred"', lesson)

    def test_entry_lesson_redirects_to_language(self):
        response = self.client.get('/entries/1/lesson')
        self.assertEqual(response.status_code, 303)
        self.assertIn('/languages/Cantonese/lesson', response.headers['Location'])

    def test_lesson_error(self):
        with patch('main.generate_language_lesson', side_effect=ValueError('Provider unavailable')):
            self.assertEqual(self.client.post('/languages/Cantonese/lesson', data={
                'level': 'new', 'preferred': 'English'}).status_code, 502)
        self.assertEqual(self.client.get('/languages/Missing/lesson').status_code, 404)
        self.assertEqual(self.client.get('/entries/999/lesson').status_code, 404)


if __name__ == '__main__':
    unittest.main()
