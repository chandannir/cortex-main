"""Normalize seed preference records into the library/DPO working shape."""
from annotation.scoring import CATEGORY_TARGETS

CATEGORY_ALIASES = {
    'sarcasm': 'sarcasm',
    'sarcasm_and_irony': 'sarcasm',
    'dismissive_sarcasm': 'sarcasm',
    'sarcastic_question': 'sarcasm',
    'mocking_irony': 'sarcasm',
    'sarcastic_reassurance': 'sarcasm',
    'passive_aggression': 'emotional_expressions',
    'slang': 'slang_internet',
    'idiom': 'cultural_expressions',
    'social_behaviour': 'cultural_expressions',
    'informal_vocabulary': 'informal_vocabulary',
    'cultural_expressions': 'cultural_expressions',
    'emotional_expressions': 'emotional_expressions',
    'slang_internet': 'slang_internet',
}


def normalize_seed_record(record):
    """Accept either the CANT seed shape or the full annotation schema."""
    if not isinstance(record, dict):
        raise ValueError('Record must be an object.')

    if 'expression' in record and 'chosen' in record and 'emotional_connotation' in record.get('chosen', {}):
        return record

    phrase = record.get('cantonese') or record.get('expression')
    if not phrase:
        raise ValueError('Record needs cantonese or expression.')
    chosen = dict(record.get('chosen') or {})
    rejected = dict(record.get('rejected') or {})
    if not chosen.get('translation') or not rejected.get('translation'):
        raise ValueError(f"{record.get('id', '?')}: chosen/rejected translations required.")

    emotion = chosen.get('emotion') or chosen.get('emotional_connotation') or 'contextual'
    if isinstance(emotion, str):
        emotion_list = [part.strip() for part in emotion.replace(';', ',').split(',') if part.strip()]
    else:
        emotion_list = list(emotion)
    if not emotion_list:
        emotion_list = ['contextual']

    category = record.get('category', 'sarcasm')
    mapped = CATEGORY_ALIASES.get(category, category)
    if mapped not in CATEGORY_TARGETS:
        mapped = 'sarcasm'

    tags = record.get('evaluation_tags') or []
    return {
        'id': record['id'],
        'category': mapped,
        'source_language': record.get('source_language', 'yue-Hant-HK'),
        'target_language': record.get('target_language', 'en'),
        'expression': phrase,
        'jyutping': record.get('jyutping', ''),
        'literal_translation': record.get('literal_translation') or rejected.get('translation') or '',
        'context': record.get('context', ''),
        'chosen': {
            'translation': chosen['translation'],
            'explanation': chosen.get('explanation') or record.get('preference_reason') or '',
            'emotional_connotation': emotion_list,
            'register': chosen.get('register', 'informal'),
            'cultural_context': chosen.get('cultural_context')
                or chosen.get('explanation')
                or record.get('preference_reason')
                or '',
        },
        'rejected': {
            'translation': rejected['translation'],
            'explanation': rejected.get('explanation') or '',
            'error_type': rejected.get('error_type') or tags or ['translation_error'],
        },
        'preference': record.get('preference', 1),
        'evaluation_dimensions': record.get('evaluation_dimensions') or {
            'chosen': {
                'translation_accuracy': 5,
                'cultural_context': 5,
                'emotional_depth': 5,
            },
            'rejected': {
                'translation_accuracy': 2,
                'cultural_context': 2,
                'emotional_depth': 1,
            },
        },
        'preference_reason': record.get('preference_reason', ''),
        'evaluation_tags': tags,
        'regional_variant': record.get('regional_variant', 'Hong Kong Cantonese'),
    }
