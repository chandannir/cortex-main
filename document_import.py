"""Parse uploaded word lists / documents into library entries."""
import csv
import io
import json
import re
from ai_lessons import _extract_json, request_text

TEXT_SUFFIXES = {'.txt', '.csv', '.tsv', '.md', '.json'}
MAX_IMPORT = 1000
CHUNK_LINES = 120


def decode_upload(raw_bytes):
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030', 'latin-1'):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError('Could not read this file as text. Use UTF-8 TXT, CSV, TSV, MD, or JSON.')


def _clean_entry(item, preferred_label='English'):
    if not isinstance(item, dict):
        return None
    phrase = str(item.get('phrase') or item.get('word') or item.get('term') or '').strip()
    meaning = str(item.get('meaning') or item.get('translation') or item.get('gloss') or '').strip()
    if not phrase or not meaning or len(phrase) > 500 or len(meaning) > 1000:
        return None
    return {
        'phrase': phrase,
        'meaning': meaning,
        'romanization': str(item.get('romanization') or item.get('pinyin') or item.get('jyutping') or '').strip()[:200],
        'example': str(item.get('example') or '').strip()[:2000],
        'translation': str(item.get('example_translation') or item.get('example_meaning') or '').strip()[:2000],
        'context': str(item.get('context') or item.get('notes') or f'Imported from document ({preferred_label} gloss).').strip()[:2000],
    }


def _parse_line(line):
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    for sep in ('\t', ' — ', ' – ', ' - ', '：', ':', ',', '|', '＝', '='):
        if sep in line:
            left, right = line.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return {'phrase': left, 'meaning': right}
    # Bare word/phrase with no gloss — meaning filled later or skipped for deterministic path
    if len(line) <= 80:
        return {'phrase': line, 'meaning': ''}
    return None


def parse_structured_text(text):
    """Parse common list formats without AI."""
    text = text.strip()
    if not text:
        return []

    # JSON array / object
    if text[:1] in '[{':
        try:
            data = json.loads(text)
            if isinstance(data, dict) and isinstance(data.get('entries'), list):
                data = data['entries']
            if isinstance(data, list):
                out = []
                for item in data:
                    if isinstance(item, str):
                        parsed = _parse_line(item)
                        entry = _clean_entry(parsed) if parsed else None
                    else:
                        entry = _clean_entry(item)
                    if entry and entry['meaning']:
                        out.append(entry)
                return out[:MAX_IMPORT]
        except json.JSONDecodeError:
            pass

    # CSV / TSV
    sample = text[:4096]
    if '\t' in sample or ',' in sample:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',\t;')
            reader = csv.DictReader(io.StringIO(text), dialect=dialect)
            if reader.fieldnames and len(reader.fieldnames) >= 2:
                fields = [name.lower().strip() for name in reader.fieldnames]
                out = []
                for row in reader:
                    mapped = {k.lower().strip(): (v or '').strip() for k, v in row.items() if k}
                    phrase = mapped.get('phrase') or mapped.get('word') or mapped.get('term') or mapped.get(fields[0])
                    meaning = mapped.get('meaning') or mapped.get('translation') or mapped.get('gloss') or mapped.get('english') or mapped.get(fields[1])
                    entry = _clean_entry({
                        'phrase': phrase,
                        'meaning': meaning,
                        'romanization': mapped.get('romanization') or mapped.get('pinyin') or mapped.get('jyutping') or '',
                        'context': mapped.get('context') or mapped.get('notes') or '',
                        'example': mapped.get('example') or '',
                        'example_translation': mapped.get('example_translation') or '',
                    })
                    if entry:
                        out.append(entry)
                if out:
                    return out[:MAX_IMPORT]
        except csv.Error:
            pass

    out = []
    for line in text.splitlines():
        parsed = _parse_line(line)
        if not parsed:
            continue
        if parsed['meaning']:
            entry = _clean_entry(parsed)
            if entry:
                out.append(entry)
        # skip bare words here; AI path can gloss them
    return out[:MAX_IMPORT]


def bare_phrases(text):
    phrases = []
    for line in text.splitlines():
        parsed = _parse_line(line)
        if parsed and parsed['phrase'] and not parsed['meaning']:
            phrases.append(parsed['phrase'])
        elif parsed and parsed['phrase'] and parsed['meaning']:
            continue
    return phrases[:MAX_IMPORT]


def _ai_entries_from_chunk(chunk, language, preferred):
    instruction = (
        'Return ONLY a JSON array of objects with keys '
        'phrase, meaning, romanization, example, example_translation, context. '
        f'The learning language is {language}. Write meaning/context/example_translation in {preferred}. '
        'Extract vocabulary and short phrases from the source text. '
        'Do not invent words that are not supported by the source. '
        'romanization may be empty if unknown. Keep phrase under 80 characters. '
        'Return at most 80 items.'
    )
    raw = request_text({'language': language, 'text': chunk}, instruction, max_tokens=3500)
    data = _extract_json(raw)
    if not isinstance(data, list):
        raise ValueError('The AI did not return a word list. Try a simpler TXT or CSV file.')
    out = []
    for item in data:
        entry = _clean_entry(item, preferred)
        if entry and entry['meaning']:
            if entry['example'] and not entry['translation']:
                entry['example'] = ''
            if entry['translation'] and not entry['example']:
                entry['translation'] = ''
            out.append(entry)
    return out


def extract_entries_from_document(text, language, preferred='English', use_ai=True):
    """
    Build entry dicts from uploaded document text.
    Prefers deterministic list/CSV parsing; uses AI for prose or bare word lists.
    """
    structured = parse_structured_text(text)
    if structured:
        return structured, 'parsed'

    if not use_ai:
        raise ValueError(
            'Could not parse this file as a word list. Use lines like “词 - meaning” '
            'or a CSV with phrase,meaning columns, or enable AI import.')

    bare = bare_phrases(text)
    source_chunks = []
    if bare:
        for i in range(0, len(bare), CHUNK_LINES):
            source_chunks.append('\n'.join(bare[i:i + CHUNK_LINES]))
    else:
        # Prose / mixed document: send capped slices
        cleaned = re.sub(r'\n{3,}', '\n\n', text.strip())
        if len(cleaned) > 60000:
            cleaned = cleaned[:60000]
        step = 8000
        for i in range(0, len(cleaned), step):
            source_chunks.append(cleaned[i:i + step])
            if len(source_chunks) >= 8:
                break

    if not source_chunks:
        raise ValueError('This file looks empty.')

    collected = []
    seen = set()
    for chunk in source_chunks:
        if len(collected) >= MAX_IMPORT:
            break
        try:
            batch = _ai_entries_from_chunk(chunk, language, preferred)
        except ValueError:
            continue
        for entry in batch:
            key = entry['phrase'].casefold()
            if key in seen:
                continue
            seen.add(key)
            collected.append(entry)
            if len(collected) >= MAX_IMPORT:
                break

    if not collected:
        raise ValueError('No phrases could be extracted from this file. Try a clearer word list.')
    return collected, 'ai'
