import unittest
from phonetics import cantonese_reading, jyutping_to_ipa


class PhoneticAlphabetTests(unittest.TestCase):
    def test_cantonese_phrase(self):
        self.assertEqual(
            jyutping_to_ipa('nei5 hou2 je5 wo3'),
            'nei˩˧ hou˧˥ jɛː˩˧ wɔː˧')

    def test_initials_finals_and_syllabic(self):
        self.assertEqual(jyutping_to_ipa('ngo5'), 'ŋɔː˩˧')
        self.assertEqual(jyutping_to_ipa('m4'), 'm̩˨˩')
        self.assertEqual(jyutping_to_ipa('ceoi1 seoi2'), 't͡sʰɵy˥ sɵy˧˥')
        self.assertEqual(jyutping_to_ipa('sik6'), 'sɪk̚˨')
        self.assertEqual(jyutping_to_ipa('lek1'), 'lɛːk̚˥')

    def test_unknown_spelling_is_not_forced(self):
        self.assertIsNone(jyutping_to_ipa('hello'))
        self.assertIsNone(jyutping_to_ipa(''))

    def test_dictionary_corrects_character_readings(self):
        peanuts = cantonese_reading('食花生')
        self.assertEqual(peanuts['jyutping'], 'sik6 faa1 sang1')
        self.assertEqual(peanuts['ipa'], 'sɪk̚˨ faː˥ sɐŋ˥')
        self.assertNotIn('sek', peanuts['ipa'])
        lemon = cantonese_reading('食檸檬')
        self.assertEqual(lemon['ipa'], 'sɪk̚˨ nɪŋ˨˩ mʊŋ˥')
        mine = cantonese_reading('我')
        self.assertEqual(mine['jyutping'], 'ngo5')
        self.assertEqual(mine['ipa'], 'ŋɔː˩˧')
        slowly = cantonese_reading('你慢慢啦')
        self.assertEqual(slowly['jyutping'], 'nei5 maan6 maan2 laa1')

    def test_latin_loanword_is_not_given_a_cantonese_reading(self):
        self.assertIsNone(cantonese_reading('hea'))


if __name__ == '__main__':
    unittest.main()
