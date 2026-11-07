"""Export annotated preference pairs into a DPO-compatible training record."""
from annotation.normalize import normalize_seed_record
from annotation.scoring import delta_s, preference_priority, weighted_score
from annotation.validate import validate_record

TRAINING_PROMPT = (
    'Translate the Cantonese expression into natural English. '
    'Explain its cultural context and emotional connotation.'
)


def _prompt(record):
    parts = [
        f"Translate and explain this Cantonese expression for English learners.",
        f"Expression: {record['expression']}",
        f"Jyutping: {record['jyutping']}",
        f"Literal gloss: {record['literal_translation']}",
        f"Situation: {record['context']}",
    ]
    if record.get('conversation_context'):
        parts.append(f"Prior conversation: {record['conversation_context']}")
    if record.get('speaker_relationship'):
        parts.append(f"Speaker relationship: {record['speaker_relationship']}")
    return '\n'.join(parts)


def _completion(side):
    connotations = side.get('emotional_connotation') or []
    lines = [
        f"Translation: {side['translation']}",
        f"Explanation: {side['explanation']}",
    ]
    if connotations:
        lines.append('Emotional connotation: ' + ', '.join(connotations))
    if side.get('register'):
        lines.append(f"Register: {side['register']}")
    if side.get('cultural_context'):
        lines.append(f"Cultural context: {side['cultural_context']}")
    return '\n'.join(lines)


def to_dpo_record(record, require_priority=False):
    """
    Build the final DPO training object from an annotated preference record.

    Each exported record contains:
    id, prompt, chosen, rejected, preference, scores, and metadata.
    """
    validate_record(record)
    dims = record['evaluation_dimensions']
    if 'chosen' in dims and 'rejected' in dims:
        chosen_score = weighted_score(dims['chosen'])
        rejected_score = weighted_score(dims['rejected'])
        margin = round(chosen_score - rejected_score, 4)
        scores = {
            'chosen': {**dims['chosen'], 'weighted': chosen_score},
            'rejected': {**dims['rejected'], 'weighted': rejected_score},
            'delta_s': margin,
        }
    else:
        chosen_score = weighted_score(dims)
        rejected_dims = record.get('rejected_evaluation_dimensions')
        scores = {'chosen': {**dims, 'weighted': chosen_score}}
        if rejected_dims:
            rejected_score = weighted_score(rejected_dims)
            scores['rejected'] = {**rejected_dims, 'weighted': rejected_score}
            scores['delta_s'] = round(chosen_score - rejected_score, 4)
        else:
            scores['delta_s'] = None

    if require_priority and not preference_priority(record):
        raise ValueError(
            f"{record['id']} is too weak for preference tuning "
            '(need clearer multi-dimension advantage).')

    return {
        'id': record['id'],
        'category': record['category'],
        'source_language': record['source_language'],
        'target_language': record['target_language'],
        'prompt': _prompt(record),
        'chosen': _completion(record['chosen']),
        'rejected': _completion({
            **record['rejected'],
            'emotional_connotation': record['rejected'].get('emotional_connotation', []),
            'register': record['rejected'].get('register', ''),
            'cultural_context': record['rejected'].get('cultural_context', ''),
        }),
        'preference': record['preference'],
        'scores': scores,
        'metadata': {
            'expression': record['expression'],
            'jyutping': record['jyutping'],
            'literal_translation': record['literal_translation'],
            'context': record['context'],
            'speaker_relationship': record.get('speaker_relationship'),
            'conversation_context': record.get('conversation_context'),
            'sarcasm_intensity': record.get('sarcasm_intensity'),
            'politeness_level': record.get('politeness_level'),
            'regional_variant': record.get('regional_variant', 'Hong Kong Cantonese'),
            'ambiguity': record.get('ambiguity'),
            'literal_vs_figurative': record.get('literal_vs_figurative'),
            'confidence': record.get('confidence'),
            'error_type': record['rejected'].get('error_type', []),
        },
    }


def _plain_completion(side):
    translation = (side.get('translation') or '').strip()
    explanation = (side.get('explanation') or '').strip()
    if explanation and translation and translation[-1] not in '.!?':
        translation += '.'
    if explanation and explanation[-1] not in '.!?':
        explanation += '.'
    return f'{translation} {explanation}'.strip() if explanation else translation


def to_training_pair(record):
    """Convert one annotation into the simplified DPO training object."""
    record = normalize_seed_record(record)
    validate_record(record)
    prompt = (
        f'{TRAINING_PROMPT}\n\n'
        f"Expression: {record['expression']}\n"
        f"Jyutping: {record['jyutping']}\n"
        f"Context: {record['context']}"
    )
    return {
        'prompt': prompt,
        'chosen': _plain_completion(record['chosen']),
        'rejected': _plain_completion(record['rejected']),
    }


def load_and_export(path, require_priority=False):
    import json
    from pathlib import Path
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    exported = to_dpo_record(record, require_priority=require_priority)
    # Attach live ΔS when both sides are scored.
    if exported['scores'].get('delta_s') is None and 'rejected' in (
            record.get('evaluation_dimensions') or {}):
        exported['scores']['delta_s'] = delta_s(record)
    return exported
