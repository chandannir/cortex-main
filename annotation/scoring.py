"""Five-point preference scoring with weighted dimensions and ΔS."""

DIMENSION_WEIGHTS = {
    'translation_accuracy': 0.40,
    'cultural_context': 0.30,
    'emotional_depth': 0.30,
}

RUBRIC = {
    5: 'Excellent; accurate, culturally grounded, emotionally nuanced.',
    4: 'Good; mostly accurate with minor omissions.',
    3: 'Acceptable; conveys basic meaning but misses nuance.',
    2: 'Weak; significant contextual or emotional errors.',
    1: 'Incorrect; literal mistranslation or reversed meaning.',
}

# Target pair counts for the 3,300-example preference corpus.
CATEGORY_TARGETS = {
    'sarcasm_and_irony': 500,
    'passive_aggression': 400,
    'informal_slang': 500,
    'figurative_idioms': 500,
    'emotional_expressions': 400,
    'hong_kong_culture': 400,
    'politeness_face': 300,
    'internet_slang': 300,
}

ERROR_TYPES = (
    'literalism',
    'tone_inversion',
    'cultural_omission',
    'emotional_flattening',
    'register_mismatch',
    'context_blindness',
)


def weighted_score(dimensions):
    """Return the weighted score for a dimension dict on the 1–5 scale."""
    missing = [name for name in DIMENSION_WEIGHTS if name not in dimensions]
    if missing:
        raise ValueError(f'Missing evaluation dimensions: {", ".join(missing)}')
    total = 0.0
    for name, weight in DIMENSION_WEIGHTS.items():
        value = dimensions[name]
        if not isinstance(value, int) or value not in RUBRIC:
            raise ValueError(f'{name} must be an integer from 1 to 5.')
        total += value * weight
    return round(total, 4)


def _pair_scores(record):
    """Extract chosen/rejected dimension maps from a preference record."""
    dims = record.get('evaluation_dimensions') or {}
    if 'chosen' in dims or 'rejected' in dims:
        chosen = dims.get('chosen')
        rejected = dims.get('rejected')
        if not chosen or not rejected:
            raise ValueError('Provide both chosen and rejected evaluation_dimensions.')
        return chosen, rejected
    rejected = record.get('rejected_evaluation_dimensions')
    if rejected:
        return dims, rejected
    return dims, None


def delta_s(record):
    """
    Preference margin ΔS = S_chosen − S_rejected.

    Supports:
    - nested evaluation_dimensions.chosen / .rejected
    - flat evaluation_dimensions plus rejected_evaluation_dimensions
    """
    chosen_dims, rejected_dims = _pair_scores(record)
    if rejected_dims is None:
        raise ValueError(
            'ΔS needs scores for both completions. Add evaluation_dimensions.rejected '
            'or rejected_evaluation_dimensions.')
    return round(weighted_score(chosen_dims) - weighted_score(rejected_dims), 4)


def preference_priority(record, min_delta=1.0, min_dims_better=2):
    """
    True when the chosen completion is demonstrably better for preference tuning.

    Requires ΔS >= min_delta and at least min_dims_better dimensions where
    chosen strictly outscores rejected.
    """
    chosen_dims, rejected_dims = _pair_scores(record)
    if rejected_dims is None:
        return False
    better = sum(
        1 for name in DIMENSION_WEIGHTS
        if chosen_dims[name] > rejected_dims[name])
    return delta_s(record) >= min_delta and better >= min_dims_better
