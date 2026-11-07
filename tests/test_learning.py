import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
import sqlite3
from main import create_app
from learning import session_dates


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'library.db'
        self.client = create_app(self.path).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def enroll(self):
        with patch('learning.today', return_value=date(2026, 11, 7)):
            return self.client.post('/learn', data=dict(language='Cantonese', frequency='three', minutes='10', start='2026-11-07'))

    def test_dates(self):
        start = date(2026, 11, 7)
        self.assertEqual(len(session_dates(start, 'daily')), 14)
        days = session_dates(start, 'three')
        self.assertEqual(len(days), 6)
        self.assertEqual(days[0], date(2026, 11, 9))
        self.assertTrue(all(day.weekday() in (0, 2, 4) for day in days))
        self.assertEqual(len(session_dates(start, 'weekends')), 4)

    def test_favourite_persists(self):
        self.client.post('/favourite', data=dict(language='Cantonese', save='1'))
        page = create_app(self.path).test_client().get('/discover?favourites=1').get_data(as_text=True)
        self.assertIn('Cantonese', page)
        self.client.post('/favourite', data=dict(language='Cantonese', save='0'))
        self.assertIn('No favourites yet', self.client.get('/discover?favourites=1').get_data(as_text=True))

    def test_plan_coaching_cached_progress(self):
        response = self.enroll()
        self.assertEqual(response.status_code, 303)
        with patch('learning.generate_study_goals', return_value=['Practise recall.'] * 6) as generate:
            self.assertEqual(self.client.post('/study/1').status_code, 303)
            self.client.post('/study/1')
            self.assertEqual(generate.call_count, 1)
        self.client.post('/study/1/complete/1', data={'done':'1'})
        page = self.client.get('/study/1').get_data(as_text=True)
        self.assertIn('Practise recall.', page)
        self.assertIn('1 / 6', page)
        self.client.post('/study/1/complete/1', data={'done':'0'})
        self.assertIn('0 / 6', self.client.get('/study/1').get_data(as_text=True))

    def test_invalid_and_ai_failure(self):
        self.assertEqual(self.client.post('/learn', data=dict(language='Cantonese',frequency='bad',minutes='999')).status_code,400)
        self.client.post('/languages', data=dict(name='Empty', voice=''))
        self.assertEqual(self.client.post('/learn', data=dict(language='Empty')).status_code,400)
        self.enroll()
        with patch('learning.generate_study_goals', side_effect=ValueError('Provider unavailable')):
            page = self.client.post('/study/1').get_data(as_text=True)
        self.assertIn('Provider unavailable', page)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],6)
            self.assertEqual(db.execute('SELECT ai_ready FROM plans').fetchone()[0],0)
