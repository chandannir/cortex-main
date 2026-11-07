"""Turn saved Jyutping into International Phonetic Alphabet."""

_INITIALS = {
    'gw': 'kʷ',
    'kw': 'kʷʰ',
    'ng': 'ŋ',
    'b': 'p',
    'p': 'pʰ',
    'm': 'm',
    'f': 'f',
    'd': 't',
    't': 'tʰ',
    'n': 'n',
    'l': 'l',
    'g': 'k',
    'k': 'kʰ',
    'h': 'h',
    'w': 'w',
    'z': 'ts',
    'c': 'tsʰ',
    's': 's',
    'j': 'j',
}

_FINALS = {
    'aai': 'aːi', 'aau': 'aːu', 'aam': 'aːm', 'aan': 'aːn', 'aang': 'aːŋ',
    'aap': 'aːp', 'aat': 'aːt', 'aak': 'aːk', 'aa': 'aː',
    'ai': 'ɐi', 'au': 'ɐu', 'am': 'ɐm', 'an': 'ɐn', 'ang': 'ɐŋ',
    'ap': 'ɐp', 'at': 'ɐt', 'ak': 'ɐk', 'a': 'ɐ',
    'ei': 'ei', 'eu': 'ɛːu', 'em': 'ɛːm', 'eng': 'ɛːŋ', 'ep': 'ɛːp', 'ek': 'ɛːk', 'e': 'ɛː',
    'iu': 'iːu', 'im': 'iːm', 'in': 'iːn', 'ing': 'ɪŋ', 'ip': 'iːp', 'it': 'iːt', 'ik': 'ɪk', 'i': 'iː',
    'oi': 'ɔːi', 'ou': 'ou', 'on': 'ɔːn', 'ong': 'ɔːŋ', 'ot': 'ɔːt', 'ok': 'ɔːk', 'o': 'ɔː',
    'ui': 'uːi', 'un': 'uːn', 'ung': 'ʊŋ', 'ut': 'uːt', 'uk': 'ʊk', 'u': 'uː',
    'eoi': 'ɵy', 'eon': 'ɵn', 'eot': 'ɵt',
    'oeng': 'œːŋ', 'oek': 'œːk', 'oe': 'œː',
    'yun': 'yːn', 'yut': 'yːt', 'yu': 'yː',
    'm': 'm̩', 'ng': 'ŋ̍',
}

_TONES = {
    '1': '˥',
    '2': '˧˥',
    '3': '˧',
    '4': '˨˩',
    '5': '˩˧',
    '6': '˨',
}


def _syllable(token):
    token = token.strip().lower()
    if len(token) < 2 or not token[-1].isdigit() or token[-1] not in _TONES:
        return None
    body, tone = token[:-1], token[-1]
    if not body.isalpha():
        return None
    if body in ('m', 'ng'):
        initial, final = '', body
    else:
        initial = final = None
        for ini in sorted(list(_INITIALS) + [''], key=len, reverse=True):
            if ini and not body.startswith(ini):
                continue
            rest = body[len(ini):]
            if rest in _FINALS:
                initial, final = ini, rest
                break
        if final is None:
            return None
    return _INITIALS.get(initial, '') + _FINALS[final] + _TONES[tone]


def jyutping_to_ipa(text):
    """Return IPA for a Jyutping string, or None when it is not Jyutping."""
    tokens = [part for part in (text or '').split() if part]
    if not tokens:
        return None
    sounds = []
    for token in tokens:
        sound = _syllable(token)
        if not sound:
            return None
        sounds.append(sound)
    return ' '.join(sounds)
