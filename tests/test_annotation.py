import json
import unittest
from pathlib import Path

from annotation import delta_s, preference_priority, to_dpo_record, to_training_pair, validate_record, weighted_score
from annotation.scoring import CATEGORY_TARGETS

SEED = Path(__file__).resolve().parents[1] / 'annotation' / 'data' / 'yue_pref_001.json'


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads(SEED.read_text(encoding='utf-8'))

    def test_seed_validates(self):
        self.assertTrue(validate_record(self.record))

    def test_weighted_score_and_delta(self):
        chosen = self.record['evaluation_dimensions']['chosen']
        rejected = self.record['evaluation_dimensions']['rejected']
        self.assertEqual(weighted_score(chosen), 5.0)
        self.assertEqual(weighted_score(rejected), 1.4)
        self.assertEqual(delta_s(self.record), 3.6)
        self.assertTrue(preference_priority(self.record))

    def test_flat_dimensions_still_validate(self):
        flat = dict(self.record)
        flat['evaluation_dimensions'] = {
            'translation_accuracy': 5,
            'cultural_context': 5,
            'emotional_depth': 5,
        }
        self.assertTrue(validate_record(flat))
        with self.assertRaises(ValueError):
            delta_s(flat)

    def test_dpo_export_contains_required_fields(self):
        exported = to_dpo_record(self.record)
        for key in ('id', 'prompt', 'chosen', 'rejected', 'preference', 'scores', 'metadata'):
            self.assertIn(key, exported)
        self.assertIn('你好叻呀！', exported['prompt'])
        self.assertIn("aren't you clever", exported['chosen'])
        self.assertIn('You are very smart!', exported['rejected'])
        self.assertEqual(exported['preference'], 1)
        self.assertEqual(exported['scores']['delta_s'], 3.6)
        self.assertEqual(exported['metadata']['sarcasm_intensity'], 4)

    def test_category_targets_sum_to_3300(self):
        self.assertEqual(sum(CATEGORY_TARGETS.values()), 3300)

    def test_training_pair_matches_dpo_format(self):
        pair = to_training_pair(self.record)
        self.assertEqual(set(pair), {'prompt', 'chosen', 'rejected'})
        self.assertTrue(pair['prompt'].startswith(
            'Translate the Cantonese expression into natural English. '
            'Explain its cultural context and emotional connotation.'))
        self.assertIn('Expression: 你好叻呀！', pair['prompt'])
        self.assertIn('Jyutping: nei5 hou2 lek1 aa3', pair['prompt'])
        self.assertIn("aren't you clever", pair['chosen'])
        self.assertIn('You are very smart!', pair['rejected'])

    def test_invalid_score_rejected(self):
        bad = dict(self.record)
        bad['evaluation_dimensions'] = {
            'chosen': {'translation_accuracy': 6, 'cultural_context': 5, 'emotional_depth': 5},
            'rejected': self.record['evaluation_dimensions']['rejected'],
        }
        with self.assertRaises(ValueError):
            validate_record(bad)


if __name__ == '__main__':
    unittest.main()
