"""Pronunciation for saved phrases.

Cantonese readings come from ToJyutping, which uses the Rime Cantonese
dictionary (Linguistic Society of Hong Kong Jyutping, CC BY 4.0).
Saved Jyutping is only a fallback, converted with the LSHK sound chart.
"""
import unicodedata
from pathlib import Path
from functools import lru_cache

TONE_NAMES = {'1': 'high level', '2': 'high rising', '3': 'mid level',
              '4': 'low falling', '5': 'low rising', '6': 'mid-low level'}

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
    'z': 't͡s',
    'c': 't͡sʰ',
    's': 's',
    'j': 'j',
}

_FINALS = {
    'aai': 'aːi', 'aau': 'aːu', 'aam': 'aːm', 'aan': 'aːn', 'aang': 'aːŋ',
    'aap': 'aːp̚', 'aat': 'aːt̚', 'aak': 'aːk̚', 'aa': 'aː',
    'ai': 'ɐi', 'au': 'ɐu', 'am': 'ɐm', 'an': 'ɐn', 'ang': 'ɐŋ',
    'ap': 'ɐp̚', 'at': 'ɐt̚', 'ak': 'ɐk̚', 'a': 'ɐ',
    'ei': 'ei', 'eu': 'ɛːu', 'em': 'ɛːm', 'eng': 'ɛːŋ', 'ep': 'ɛːp̚', 'et': 'ɛːt̚', 'ek': 'ɛːk̚', 'e': 'ɛː',
    'iu': 'iːu', 'im': 'iːm', 'in': 'iːn', 'ing': 'ɪŋ', 'ip': 'iːp̚', 'it': 'iːt̚', 'ik': 'ɪk̚', 'i': 'iː',
    'oi': 'ɔːi', 'ou': 'ou', 'on': 'ɔːn', 'ong': 'ɔːŋ', 'ot': 'ɔːt̚', 'ok': 'ɔːk̚', 'o': 'ɔː',
    'ui': 'uːi', 'un': 'uːn', 'ung': 'ʊŋ', 'ut': 'uːt̚', 'uk': 'ʊk̚', 'u': 'uː',
    'eoi': 'ɵy', 'eon': 'ɵn', 'eot': 'ɵt̚',
    'oeng': 'œːŋ', 'oet': 'œːt̚', 'oek': 'œːk̚', 'oe': 'œː',
    'yun': 'yːn', 'yut': 'yːt̚', 'yu': 'yː',
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


@lru_cache(maxsize=512)
def cantonese_reading(text):
    """Return dictionary Jyutping, with IPA from the LSHK sound chart.

    The dictionary chooses the syllables. Its own phonetic spelling is not
    used, because it rewrites vowels the Jyutping letters do not have
    (sik as sek, ung as oŋ).
    """
    try:
        import ToJyutping
    except ImportError:
        return None
    syllables = []
    breakdown = []
    for char, syllable in ToJyutping.get_jyutping_list(text or ''):
        if not str(char).strip():
            continue
        if not syllable:
            # Never present a partial reading as the pronunciation of a full word.
            if any(unicodedata.category(c)[0] in ('L', 'N') for c in str(char)):
                return None
            continue
        syllables.append(syllable)
        for token in syllable.split():
            sound = jyutping_to_ipa(token)
            breakdown.append({'text': str(char), 'jyutping': token,
                              'ipa': sound or '', 'tone': token[-1:] if sound else '',
                              'tone_name': TONE_NAMES.get(token[-1:], '') if sound else ''})
    if not syllables:
        return None
    jyutping = ' '.join(syllables)
    return {'jyutping': jyutping, 'ipa': jyutping_to_ipa(jyutping) or '', 'syllables': breakdown}


def dictionary_jyutping(text, voice=''):
    if voice != 'yue-HK':
        return ''
    reading = cantonese_reading(text)
    return reading['jyutping'] if reading else ''


@lru_cache(maxsize=512)
def cantonese_word(text):
    """Check full headwords against the attributed, bundled upstream word lists."""
    candidates = _rime_words().get(text)
    if not candidates:
        return None
    reading = cantonese_reading(text)
    pronunciation = reading['jyutping'] if reading and reading['jyutping'] in candidates else candidates[0]
    return {'phrase': text, 'romanization': pronunciation,
            'ipa': jyutping_to_ipa(pronunciation) or '' if not any(c.isascii() and c.isalpha() for c in text) else '',
            'source': 'Rime Cantonese word lists',
            'source_url': 'https://github.com/rime/rime-cantonese'}


@lru_cache(maxsize=1)
def _rime_words():
    words = {}
    directory = Path(__file__).parent / 'resources' / 'rime'
    for filename in ('jyut6ping3.chars.dict.yaml', 'jyut6ping3.words.dict.yaml',
                     'jyut6ping3.phrase.dict.yaml', 'jyut6ping3.lettered.dict.yaml'):
        path = directory / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if not line or line.startswith('#'):
                continue
            columns = line.split('\t')
            if len(columns) < 2 or not columns[0] or not columns[1].strip():
                continue
            pronunciation = columns[1].strip()
            variants = words.setdefault(columns[0], [])
            if pronunciation not in variants:
                variants.append(pronunciation)
    return words


def dictionary_ipa(text, voice=''):
    if voice != 'yue-HK':
        return ''
    reading = cantonese_reading(text)
    return reading['ipa'] if reading else ''


def lookup_phonetic(text, voice=''):
    """Find Jyutping and IPA for a phrase. Cantonese uses the Rime dictionary."""
    if voice == 'yue-HK':
        reading = cantonese_reading(text)
        if reading:
            return {'romanization': reading['jyutping'], 'ipa': reading['ipa']}
    ipa = jyutping_to_ipa(text)
    if ipa:
        return {'romanization': (text or '').strip(), 'ipa': ipa}
    return {'romanization': '', 'ipa': ''}
