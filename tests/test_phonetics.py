import unittest
from phonetics import jyutping_to_ipa


class PhoneticAlphabetTests(unittest.TestCase):
    def test_cantonese_phrase(self):
        self.assertEqual(
            jyutping_to_ipa('nei5 hou2 je5 wo3'),
            'nei˩˧ hou˧˥ jɛː˩˧ wɔː˧')

    def test_initials_finals_and_syllabic(self):
        self.assertEqual(jyutping_to_ipa('ngo5'), 'ŋɔː˩˧')
        self.assertEqual(jyutping_to_ipa('m4'), 'm̩˨˩')
        self.assertEqual(jyutping_to_ipa('ceoi1 seoi2'), 'tsʰɵy˥ sɵy˧˥')
        self.assertEqual(jyutping_to_ipa('sik6'), 'sɪk˨')

    def test_unknown_spelling_is_not_forced(self):
        self.assertIsNone(jyutping_to_ipa('hello'))
        self.assertIsNone(jyutping_to_ipa(''))


if __name__ == '__main__':
    unittest.main()
