import unittest
from ai_lessons import parse_language_lesson


class LessonParseTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {'phrase': '你好嘢喎！', 'romanization': 'nei5 hou2 je5 wo3',
             'meaning': "Well, aren't you clever!", 'context': 'Sarcasm',
             'example': '', 'translation': ''},
            {'phrase': '吹水', 'romanization': 'ceoi1 seoi2',
             'meaning': 'To chat', 'context': 'Casual talk',
             'example': '', 'translation': ''},
        ]

    def test_rejects_invented_phrases(self):
        raw = '''{
          "overview": "A short plan.",
          "useful_phrases": [
            {"phrase": "發明詞語", "romanization": "x", "translation": "Invented",
             "usage": "Should fail", "level_note": ""}
          ],
          "practice": [
            {"question": "Q1", "answer": "A1"},
            {"question": "Q2", "answer": "A2"}
          ]
        }'''
        with self.assertRaises(ValueError):
            parse_language_lesson(raw, self.entries, 'new')

    def test_accepts_collection_phrases(self):
        raw = '''{
          "overview": "Focus on sarcasm and slang.",
          "useful_phrases": [
            {"phrase": "你好嘢喎！", "romanization": "nei5 hou2 je5 wo3",
             "translation": "Well, aren't you clever!",
             "usage": "Use when someone made a foolish choice.", "level_note": "Tone first."},
            {"phrase": "吹水", "romanization": "ceoi1 seoi2",
             "translation": "Chat / shoot the breeze",
             "usage": "Casual talk with friends.", "level_note": ""}
          ],
          "practice": [
            {"question": "Is 你好嘢喎！ always praise?", "answer": "No, often sarcasm."},
            {"question": "What is 吹水?", "answer": "Casual chatting."}
          ]
        }'''
        lesson = parse_language_lesson(raw, self.entries, 'new')
        self.assertEqual(len(lesson['useful_phrases']), 2)
        first = lesson['useful_phrases'][0]
        self.assertEqual(first['phrase'], '你好嘢喎！')
        self.assertEqual(first['syllables'], ['nei5', 'hou2', 'je5', 'wo3'])

    def test_keeps_saved_phonetics_and_drops_invented_coaching(self):
        raw = '''{
          "overview": "Say the phrase.",
          "useful_phrases": [{
            "phrase": "吹水",
            "romanization": "invented1 reading2",
            "say_it": "Say chui seui, not the saved reading.",
            "translation": "To chat",
            "usage": "Casual talk.",
            "level_note": ""
          }],
          "practice": [
            {"question": "Q1", "answer": "A1"},
            {"question": "Q2", "answer": "A2"}
          ]
        }'''
        lesson = parse_language_lesson(raw, [self.entries[1]], 'new')
        phrase = lesson['useful_phrases'][0]
        self.assertEqual(phrase['romanization'], 'ceoi1 seoi2')
        self.assertEqual(phrase['say_it'], '')


if __name__ == '__main__':
    unittest.main()
