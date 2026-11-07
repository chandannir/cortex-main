"""Import preference-annotation JSON into the local Commonword SQLite library."""
import argparse
import json
import sqlite3
from pathlib import Path

from annotation.normalize import normalize_seed_record
from annotation.validate import validate_record

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / 'data' / 'languages.db'
DEFAULT_DATA = Path(__file__).resolve().parent / 'data'
LANGUAGE = 'Cantonese'
VOICE = 'yue-HK'


def record_to_entry(record):
    """Map one preference record to a library entry row."""
    record = normalize_seed_record(record)
    chosen = record['chosen']
    context_parts = [
        f"[{record['id']}]",
        record.get('context', ''),
        chosen.get('explanation', ''),
        chosen.get('cultural_context', ''),
    ]
    if record.get('literal_translation'):
        context_parts.append(f"Literal gloss: {record['literal_translation']}.")
    if record.get('preference_reason'):
        context_parts.append(record['preference_reason'])
    if record.get('conversation_context'):
        context_parts.insert(2, record['conversation_context'])
    return {
        'language': LANGUAGE,
        'phrase': record['expression'],
        'meaning': chosen['translation'],
        'example': record['expression'],
        'translation': chosen['translation'],
        'context': '\n\n'.join(part for part in context_parts if part),
        'romanization': record.get('jyutping') or '',
        'audio': '',
        'lesson': '',
        'annotation_id': record['id'],
    }


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY, language TEXT NOT NULL,
        phrase TEXT NOT NULL, meaning TEXT NOT NULL,
        example TEXT NOT NULL, translation TEXT NOT NULL,
        context TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    columns = {row[1] for row in db.execute('PRAGMA table_info(entries)')}
    for name in ('romanization', 'audio', 'lesson'):
        if name not in columns:
            db.execute(f"ALTER TABLE entries ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    db.execute('''CREATE TABLE IF NOT EXISTS languages (
        name TEXT PRIMARY KEY COLLATE NOCASE, voice TEXT NOT NULL DEFAULT '')''')
    db.execute(
        'INSERT OR IGNORE INTO languages(name, voice) VALUES (?, ?)',
        (LANGUAGE, VOICE))
    db.execute(
        "UPDATE languages SET voice=? WHERE name=? AND (voice='' OR voice IS NULL)",
        (VOICE, LANGUAGE))


def already_imported(db, entry):
    marker = f"[{entry['annotation_id']}]"
    row = db.execute(
        'SELECT id FROM entries WHERE language=? COLLATE NOCASE AND context LIKE ?',
        (entry['language'], f'%{marker}%')).fetchone()
    if row:
        return True
    row = db.execute(
        '''SELECT id FROM entries WHERE language=? COLLATE NOCASE
           AND phrase=? AND romanization=?''',
        (entry['language'], entry['phrase'], entry['romanization'])).fetchone()
    return row is not None


def load_records(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    raise ValueError(f'{path} must contain a JSON object or array.')


def import_records(paths, database=DEFAULT_DB, dry_run=False):
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    inserted, skipped = [], []
    files = []
    for path in paths:
        path = Path(path)
        if path.is_dir():
            files.extend(sorted(p for p in path.glob('*.json') if not p.name.startswith('_')))
        else:
            files.append(path)

    db = sqlite3.connect(database)
    try:
        ensure_schema(db)
        for path in files:
            for raw in load_records(path):
                record = normalize_seed_record(raw)
                validate_record(record)
                entry = record_to_entry(record)
                if already_imported(db, entry):
                    skipped.append(record['id'])
                    continue
                if dry_run:
                    inserted.append(record['id'])
                    continue
                db.execute(
                    '''INSERT INTO entries
                       (language, phrase, meaning, example, translation, context,
                        romanization, audio, lesson)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (entry['language'], entry['phrase'], entry['meaning'],
                     entry['example'], entry['translation'], entry['context'],
                     entry['romanization'], entry['audio'], entry['lesson']))
                inserted.append(record['id'])
        if not dry_run:
            db.commit()
    finally:
        db.close()
    return {'inserted': inserted, 'skipped': skipped, 'database': str(database)}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Import annotation JSON into the local language library.')
    parser.add_argument(
        'paths', nargs='*', default=[str(DEFAULT_DATA)],
        help='JSON files or a directory (default: annotation/data)')
    parser.add_argument(
        '--database', default=str(DEFAULT_DB),
        help='SQLite path (default: data/languages.db)')
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Validate and report without writing')
    args = parser.parse_args(argv)
    result = import_records(args.paths, database=args.database, dry_run=args.dry_run)
    action = 'Would insert' if args.dry_run else 'Inserted'
    print(f"{action}: {', '.join(result['inserted']) or '(none)'}")
    print(f"Skipped (already present): {', '.join(result['skipped']) or '(none)'}")
    print(f"Database: {result['database']}")
    return result


if __name__ == '__main__':
    main()
