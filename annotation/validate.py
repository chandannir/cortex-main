"""Validate preference-annotation records against the project schema."""
from annotation.normalize import CATEGORY_ALIASES
from annotation.scoring import CATEGORY_TARGETS, DIMENSION_WEIGHTS, RUBRIC

SOURCE_LANGUAGES = {'yue-Hant-HK'}
TARGET_LANGUAGES = {'en'}
REGISTERS = {'informal', 'neutral', 'conversational', 'professional', 'explanatory'}
POLITENESS = {'polite', 'neutral', 'impolite', 'vulgar'}
RELATIONSHIPS = {'friends', 'colleagues', 'strangers', 'family'}
LITERALITY = {'literal', 'figurative', 'both'}

REQUIRED_TOP = (
    'id', 'category', 'source_language', 'target_language', 'expression',
    'jyutping', 'literal_translation', 'context', 'chosen', 'rejected',
    'preference', 'evaluation_dimensions',
)
REQUIRED_CHOSEN = (
    'translation', 'explanation', 'emotional_connotation', 'register', 'cultural_context',
)
REQUIRED_REJECTED = ('translation', 'explanation', 'error_type')


def _require_str(obj, key, path):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{path}.{key} must be a non-empty string.')
    return value


def _require_str_list(obj, key, path):
    value = obj.get(key)
    if not isinstance(value, list) or not value or any(
            not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f'{path}.{key} must be a non-empty list of strings.')
    return value


def _check_dimensions(dims, path):
    if not isinstance(dims, dict):
        raise ValueError(f'{path} must be an object.')
    for name in DIMENSION_WEIGHTS:
        value = dims.get(name)
        if not isinstance(value, int) or value not in RUBRIC:
            raise ValueError(f'{path}.{name} must be an integer from 1 to 5.')


def validate_record(record):
    """Raise ValueError if the record is not a valid preference example."""
    if not isinstance(record, dict):
        raise ValueError('Record must be a JSON object.')
    missing = [key for key in REQUIRED_TOP if key not in record]
    if missing:
        raise ValueError(f'Missing fields: {", ".join(missing)}')

    _require_str(record, 'id', 'record')
    category = CATEGORY_ALIASES.get(_require_str(record, 'category', 'record'), record['category'])
    if category not in CATEGORY_TARGETS:
        raise ValueError(
            f'category must be one of: {", ".join(sorted(CATEGORY_TARGETS))}.')

    if record['source_language'] not in SOURCE_LANGUAGES:
        raise ValueError('source_language must be yue-Hant-HK.')
    if record['target_language'] not in TARGET_LANGUAGES:
        raise ValueError('target_language must be en.')
    for key in ('expression', 'jyutping', 'literal_translation', 'context'):
        _require_str(record, key, 'record')

    if record['preference'] != 1:
        raise ValueError('preference must be 1 (chosen preferred over rejected).')

    chosen = record['chosen']
    rejected = record['rejected']
    if not isinstance(chosen, dict) or not isinstance(rejected, dict):
        raise ValueError('chosen and rejected must be objects.')
    for key in REQUIRED_CHOSEN:
        if key == 'emotional_connotation':
            _require_str_list(chosen, key, 'chosen')
        else:
            _require_str(chosen, key, 'chosen')
    if chosen.get('register') not in REGISTERS:
        raise ValueError(f'chosen.register must be one of: {", ".join(sorted(REGISTERS))}.')
    for key in REQUIRED_REJECTED:
        if key == 'error_type':
            _require_str_list(rejected, key, 'rejected')
        else:
            _require_str(rejected, key, 'rejected')

    dims = record['evaluation_dimensions']
    if not isinstance(dims, dict):
        raise ValueError('evaluation_dimensions must be an object.')
    if 'chosen' in dims or 'rejected' in dims:
        _check_dimensions(dims.get('chosen'), 'evaluation_dimensions.chosen')
        _check_dimensions(dims.get('rejected'), 'evaluation_dimensions.rejected')
    else:
        _check_dimensions(dims, 'evaluation_dimensions')
        if 'rejected_evaluation_dimensions' in record:
            _check_dimensions(
                record['rejected_evaluation_dimensions'],
                'rejected_evaluation_dimensions')

    # Optional enrichment fields from the annotation framework.
    if 'speaker_relationship' in record and record['speaker_relationship'] not in RELATIONSHIPS:
        raise ValueError(f'speaker_relationship must be one of: {", ".join(sorted(RELATIONSHIPS))}.')
    if 'politeness_level' in record and record['politeness_level'] not in POLITENESS:
        raise ValueError(f'politeness_level must be one of: {", ".join(sorted(POLITENESS))}.')
    if 'literal_vs_figurative' in record and record['literal_vs_figurative'] not in LITERALITY:
        raise ValueError(f'literal_vs_figurative must be one of: {", ".join(sorted(LITERALITY))}.')
    if 'sarcasm_intensity' in record:
        intensity = record['sarcasm_intensity']
        if not isinstance(intensity, int) or not 0 <= intensity <= 5:
            raise ValueError('sarcasm_intensity must be an integer from 0 to 5.')
    if 'confidence' in record:
        confidence = record['confidence']
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError('confidence must be a number from 0 to 1.')
    if 'ambiguity' in record and not isinstance(record['ambiguity'], bool):
        raise ValueError('ambiguity must be a boolean.')
    if 'conversation_context' in record:
        _require_str(record, 'conversation_context', 'record')
    if 'regional_variant' in record:
        _require_str(record, 'regional_variant', 'record')

    return True
