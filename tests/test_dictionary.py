import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from main import create_app
from phonetics import cantonese_reading, cantonese_word


class DictionaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = create_app(Path(self.directory.name) / 'test.db').test_client()

    def tearDown(self):
        self.directory.cleanup()

    def test_search_corrected_reading_and_tones(self):
        page = self.client.get('/languages/Cantonese/dictionary?q=ngo5').get_data(as_text=True)
        self.assertIn('我', page)
        self.assertIn('low rising', page)
        self.assertIn('ŋɔː˩˧', page)
        self.assertIn('Ask about this word', page)
        self.assertIn('No verified words found', self.client.get('/languages/Cantonese/dictionary?q=absent').get_data(as_text=True))

    def test_selected_chat_uses_dictionary_reference(self):
        with patch('main.answer_collection_question', return_value='A grounded answer') as answer:
            response = self.client.post('/languages/Cantonese/chat', json={
                'question': 'Explain pronunciation', 'entry_id': 1})
            self.assertEqual(response.status_code, 200)
            entries = answer.call_args.args[1]
            self.assertEqual(entries[0]['romanization'], 'ngo5')
            self.assertEqual(entries[0]['syllables'][0]['tone'], '5')
            self.assertEqual(response.json['sources'][0]['ipa'], 'ŋɔː˩˧')
        self.assertEqual(self.client.post('/languages/Cantonese/chat', json={
            'question': 'Explain', 'entry_id': 999}).status_code, 404)

    def test_pending_words_do_not_reach_dictionary_or_chat(self):
        with patch('main.generate_translation', return_value={
                'phrase': '測試', 'meaning': 'test', 'romanization': '', 'note': ''}):
            self.client.post('/languages/Cantonese/translate', json={'text': 'test'})
        self.assertNotIn('測試', self.client.get('/languages/Cantonese/dictionary').get_data(as_text=True))
        self.assertEqual(self.client.post('/languages/Cantonese/chat', json={
            'question': 'Explain', 'entry_id': 2}).status_code, 404)

    def test_incomplete_dictionary_reading_not_presented_as_complete(self):
        cantonese_reading.cache_clear()
        with patch('ToJyutping.get_jyutping_list', return_value=[('我', 'ngo5'), ('unknown', None)]):
            self.assertIsNone(cantonese_reading('我unknown'))
        cantonese_reading.cache_clear()

    def test_invalid_chat_payload(self):
        self.assertEqual(self.client.post('/languages/Cantonese/chat', json=['bad']).status_code, 400)
        self.assertEqual(self.client.post('/languages/Cantonese/chat', json={'question':'hi','history':[1]}).status_code, 400)

    def test_word_list_checks_whole_word(self):
        self.assertEqual(cantonese_word('我')['romanization'], 'ngo5')
        self.assertEqual(cantonese_word('多謝')['romanization'], 'do1 ze6')
        self.assertIsNone(cantonese_word('我我我我我我我我我我我我'))
        self.assertIsNone(cantonese_word('not-a-cantonese-word'))

    def test_ai_definition_is_pending_cached_and_sourced(self):
        result = {'phrase':'我', 'meaning':'I or me', 'note':'Pronoun.', 'romanization':'wrong'}
        with patch('main.generate_dictionary_translation', return_value=result) as translate:
            self.assertEqual(self.client.post('/languages/Cantonese/dictionary', data={'q':'我'}).status_code,303)
            self.client.post('/languages/Cantonese/dictionary', data={'q':'我'})
            self.assertEqual(translate.call_count, 1)
            self.assertEqual(translate.call_args.args[0]['source'], 'Rime Cantonese word lists')
        page = self.client.get('/languages/Cantonese/dictionary?q=我').get_data(as_text=True)
        self.assertIn('Unverified AI translation',page)
        self.assertIn('I or me',page)
        self.assertEqual(self.client.post('/languages/Cantonese/chat',json={'question':'explain','entry_id':2}).status_code,404)

    def test_unlisted_query_never_calls_ai(self):
        with patch('main.generate_dictionary_translation') as translate:
            page = self.client.post('/languages/Cantonese/dictionary',data={'q':'xyz-no-match'}).get_data(as_text=True)
            self.assertIn('No AI request was sent',page)
            translate.assert_not_called()

    def test_failed_dictionary_translation_is_retryable(self):
        with patch('main.generate_dictionary_translation',side_effect=ValueError('Provider unavailable')):
            page = self.client.post('/languages/Cantonese/dictionary',data={'q':'我'}).get_data(as_text=True)
            self.assertIn('Provider unavailable', page)
        with patch('main.generate_dictionary_translation',return_value={'meaning':'I','note':''}):
            self.assertEqual(self.client.post('/languages/Cantonese/dictionary',data={'q':'我'}).status_code,303)
