"""Run the local language library with python main.py."""
from pathlib import Path
from contextlib import contextmanager
import json
import os
import sqlite3
import uuid
from threading import Lock
from ai_lessons import (
    answer_collection_question,
    generate_language_lesson,
    generate_translation,
    generate_dictionary_translation,
    lesson_from_storage,
    related_entries,
)
from document_import import TEXT_SUFFIXES, decode_upload, extract_entries_from_document
from learning import register_learning
from preferences import LEVELS, LANGUAGES
from i18n import UI_LANGUAGES, explanation_for, t
from phonetics import dictionary_ipa, dictionary_jyutping, jyutping_to_ipa, lookup_phonetic, cantonese_reading, cantonese_word
from flask import Flask, g, jsonify, redirect, render_template, request, url_for, send_from_directory

ROOT = Path(__file__).resolve().parent
DEFAULT_SETTINGS = {
    'ui_language': 'en',
}


def default_database():
    """Use a writable directory on Vercel; the project folder is read-only there."""
    if os.environ.get('VERCEL'):
        root = Path('/tmp/cortex')
    else:
        root = ROOT / 'data'
    return root / 'languages.db'


def create_app(database=None):
    app = Flask(__name__)
    app.jinja_env.filters['ipa'] = jyutping_to_ipa
    app.jinja_env.filters['dict_jyutping'] = dictionary_jyutping
    app.jinja_env.filters['dict_ipa'] = dictionary_ipa
    lesson_lock = Lock()
    app.config['DATABASE'] = str(database or default_database())
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
    audio_dir = Path(app.config['DATABASE']).parent / 'audio'
    audio_dir.mkdir(parents=True, exist_ok=True)
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect():
        db = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def load_settings():
        with connect() as db:
            rows = db.execute('SELECT key, value FROM settings').fetchall()
        settings = dict(DEFAULT_SETTINGS)
        settings.update({row['key']: row['value'] for row in rows
                         if row['key'] in DEFAULT_SETTINGS})
        if settings['ui_language'] not in UI_LANGUAGES:
            settings['ui_language'] = 'en'
        settings['explanation_language'] = explanation_for(settings['ui_language'])
        return settings

    def save_settings(values):
        with connect() as db:
            for key, value in values.items():
                db.execute(
                    'INSERT INTO settings(key, value) VALUES(?, ?) '
                    'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    (key, value))

    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY, language TEXT NOT NULL,
            phrase TEXT NOT NULL, meaning TEXT NOT NULL,
            example TEXT NOT NULL, translation TEXT NOT NULL,
            context TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY)')
        if not db.execute("SELECT 1 FROM migrations WHERE name='seed'").fetchone():
            db.execute('''INSERT INTO entries
                (language, phrase, meaning, example, translation, context)
                VALUES (?, ?, ?, ?, ?, ?)''',
                ('Cantonese', '我', 'I / me', '我係…', 'I am…',
                 '我 means I/me. 我係… starts the phrase I am….'))
            db.execute("INSERT INTO migrations VALUES ('seed')")
        columns = {row['name'] for row in db.execute('PRAGMA table_info(entries)')}
        for name in ('romanization', 'audio', 'lesson'):
            if name not in columns:
                db.execute(f"ALTER TABLE entries ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        columns = {row['name'] for row in db.execute('PRAGMA table_info(entries)')}
        if 'review_status' not in columns:
            db.execute("ALTER TABLE entries ADD COLUMN review_status TEXT NOT NULL DEFAULT 'verified'")
        db.execute('''CREATE TABLE IF NOT EXISTS languages (
            name TEXT PRIMARY KEY COLLATE NOCASE, voice TEXT NOT NULL DEFAULT '')''')
        db.execute('INSERT OR IGNORE INTO languages(name) SELECT DISTINCT language FROM entries')
        db.execute("UPDATE languages SET voice='yue-HK' WHERE name='Cantonese' AND voice=''")
        db.execute('''CREATE TABLE IF NOT EXISTS lesson_variants (
            entry_id INTEGER, level TEXT, preferred TEXT, content TEXT NOT NULL,
            PRIMARY KEY(entry_id, level, preferred))''')
        db.execute('''CREATE TABLE IF NOT EXISTS language_lesson_variants (
            language TEXT NOT NULL COLLATE NOCASE, level TEXT NOT NULL,
            preferred TEXT NOT NULL, content TEXT NOT NULL,
            PRIMARY KEY(language, level, preferred))''')
        db.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS dictionary_drafts (
            language TEXT COLLATE NOCASE, phrase TEXT, preferred TEXT, entry_id INTEGER,
            PRIMARY KEY(language, phrase, preferred))''')
        for key, value in DEFAULT_SETTINGS.items():
            db.execute('INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)', (key, value))

    @app.before_request
    def bind_settings():
        g.settings = load_settings()
        g.ui = g.settings['ui_language']

    @app.context_processor
    def inject_ui():
        settings = getattr(g, 'settings', DEFAULT_SETTINGS)
        ui = settings.get('ui_language', 'en')

        def tr(key, **kwargs):
            return t(ui, key, **kwargs)

        return {
            'settings': settings,
            'ui_languages': UI_LANGUAGES,
            'tr': tr,
            'levels': LEVELS,
            'explanation_languages': LANGUAGES,
        }

    @app.route('/settings', methods=['GET', 'POST'])
    def settings_page():
        saved = False
        error = None
        if request.method == 'POST':
            ui_language = request.form.get('ui_language', 'en')
            if ui_language not in UI_LANGUAGES:
                error = 'Choose a supported screen language.'
            else:
                save_settings({'ui_language': ui_language})
                # Drop obsolete keys from earlier settings versions.
                with connect() as db:
                    db.execute("DELETE FROM settings WHERE key IN ('learning_language','explanation_language')")
                g.settings = load_settings()
                g.ui = g.settings['ui_language']
                saved = True
        return render_template('settings.html', saved=saved, error=error), (
            400 if error else 200)

    @app.route('/languages/<path:language>/lesson', methods=['GET', 'POST'])
    def language_lesson(language):
        error = None
        status = 200
        settings = g.settings
        level = request.values.get('level', 'new')
        preferred = settings['explanation_language']
        if level not in LEVELS or preferred not in LANGUAGES:
            return 'Choose a supported level and explanation language.', 400
        with connect() as db:
            language_row = db.execute(
                'SELECT name FROM languages WHERE name=?', (language,)).fetchone()
            entries = db.execute(
                '''SELECT entries.*, languages.voice FROM entries
                   JOIN languages ON entries.language=languages.name COLLATE NOCASE
                   WHERE entries.language=? COLLATE NOCASE AND entries.review_status='verified'
                   ORDER BY entries.id''',
                (language,)).fetchall() if language_row else []
            cached = db.execute(
                '''SELECT content FROM language_lesson_variants
                   WHERE language=? COLLATE NOCASE AND level=? AND preferred=?''',
                (language, level, preferred)).fetchone() if language_row else None
        if not language_row:
            return 'Language not found', 404
        language = language_row['name']
        lesson = lesson_from_storage(cached['content']) if cached else None
        if request.method == 'POST' and not lesson:
            if not entries:
                error, status = t(g.ui, 'no_entries'), 400
            elif not lesson_lock.acquire(blocking=False):
                error, status = 'Another lesson is being created. Try again shortly.', 429
            else:
                try:
                    with connect() as db:
                        cached = db.execute(
                            '''SELECT content FROM language_lesson_variants
                               WHERE language=? COLLATE NOCASE AND level=? AND preferred=?''',
                            (language, level, preferred)).fetchone()
                    if not cached:
                        result = generate_language_lesson(language, entries, level, preferred)
                        payload = json.dumps(result, ensure_ascii=False)
                        with connect() as db:
                            db.execute(
                                '''INSERT OR REPLACE INTO language_lesson_variants
                                   (language, level, preferred, content) VALUES (?, ?, ?, ?)''',
                                (language, level, preferred, payload))
                    return redirect(
                        url_for('language_lesson', language=language, level=level),
                        code=303)
                except ValueError as exc:
                    error, status = str(exc), 502
                finally:
                    lesson_lock.release()
        return render_template(
            'lesson.html', language=language, entries=entries, lesson=lesson,
            error=error, level=level, preferred=preferred), status

    @app.route('/languages/<path:language>/dictionary', methods=['GET', 'POST'])
    def language_dictionary(language):
        with connect() as db:
            language_row = db.execute('SELECT name, voice FROM languages WHERE name=?', (language,)).fetchone()
            rows = db.execute("SELECT * FROM entries WHERE language=? COLLATE NOCASE AND review_status='verified' ORDER BY phrase", (language,)).fetchall()
        if not language_row:
            return 'Language not found', 404
        query = request.values.get('q', '').strip()[:300]
        dictionary_match = cantonese_word(query) if query and language_row['voice'] == 'yue-HK' else None
        error = None
        draft = None
        preferred = g.settings['explanation_language']
        def find_draft():
            with connect() as db:
                return db.execute('''SELECT e.* FROM dictionary_drafts d JOIN entries e ON e.id=d.entry_id
                    WHERE d.language=? COLLATE NOCASE AND d.phrase=? AND d.preferred=?''',
                    (language_row['name'], query, preferred)).fetchone()
        if dictionary_match:
            draft = find_draft()
        if request.method == 'POST' and not draft:
            if not dictionary_match:
                error = 'No exact word-list match. Enter a Cantonese word in Chinese characters. No AI request was sent.'
            elif not lesson_lock.acquire(blocking=False):
                error = 'Another AI request is running. Try again shortly.'
            else:
                try:
                    draft = find_draft()
                    if not draft:
                        result = generate_dictionary_translation(dictionary_match, preferred)
                        with connect() as db:
                            entry_id = db.execute('''INSERT INTO entries
                                (language, phrase, meaning, example, translation, context, romanization, audio, review_status)
                                VALUES (?, ?, ?, '', '', ?, ?, '', 'pending')''',
                                (language_row['name'], query, result['meaning'],
                                 'AI translation (unverified). Word-list source: Rime Cantonese word lists. '
                                 'Explanation language: ' + preferred + '. ' + result['note'],
                                 dictionary_match['romanization'])).lastrowid
                            db.execute('INSERT INTO dictionary_drafts VALUES(?,?,?,?)',
                                       (language_row['name'], query, preferred, entry_id))
                    return redirect(url_for('language_dictionary', language=language_row['name'], q=query), code=303)
                except ValueError as exc:
                    error = str(exc)
                finally:
                    lesson_lock.release()
        words = []
        for row in rows:
            word = dict(row)
            reading = cantonese_reading(word['phrase']) if language_row['voice'] == 'yue-HK' else None
            word['reading'] = reading
            word['pronunciation'] = reading['jyutping'] if reading else ('' if language_row['voice'] == 'yue-HK' else word['romanization'])
            if not query or any(query.casefold() in str(word[key]).casefold() for key in ('phrase', 'meaning', 'pronunciation', 'context')):
                words.append(word)
        return render_template('dictionary.html', language=language_row['name'],
                               voice=language_row['voice'], words=words, q=query,
                               dictionary_match=dictionary_match, draft=draft, error=error,
                               preferred=preferred)

    @app.post('/languages/<path:language>/chat')
    def language_chat(language):
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or not isinstance(payload.get('question', ''), str):
            return jsonify(error='Enter a text question.'), 400
        question = (payload.get('question') or '').strip()
        history = payload.get('history') or []
        if not question or len(question) > 500:
            return jsonify(error='Ask a question under 500 characters.'), 400
        if not isinstance(history, list) or len(history) > 12 or any(not isinstance(turn, dict) or not isinstance(turn.get('content', ''), str) for turn in history):
            return jsonify(error='The conversation is too long. Start again.'), 400
        preferred = g.settings['explanation_language']
        with connect() as db:
            language_row = db.execute(
                'SELECT name, voice FROM languages WHERE name=?', (language,)).fetchone()
            entries = db.execute(
                '''SELECT id, phrase, romanization, meaning, context FROM entries
                   WHERE language=? COLLATE NOCASE AND review_status='verified' ORDER BY id''',
                (language,)).fetchall() if language_row else []
        if not language_row:
            return jsonify(error='Language not found'), 404
        if not entries:
            return jsonify(error='Add a phrase to this language before asking about it.'), 400
        selected_id = payload.get('entry_id')
        if selected_id is not None:
            entries = [entry for entry in entries if str(entry['id']) == str(selected_id)]
            if not entries:
                return jsonify(error='That verified dictionary word was not found in this language.'), 404
        else:
            # Relevant words should not disappear behind the 250-entry prompt limit.
            entries = sorted(entries, key=lambda e: e['phrase'] not in question)
        prepared = []
        for row in entries[:250]:
            entry = dict(row)
            if language_row['voice'] == 'yue-HK':
                reading = cantonese_reading(entry['phrase'])
                entry['romanization'] = reading['jyutping'] if reading else ''
                entry['ipa'] = reading['ipa'] if reading else ''
                entry['syllables'] = reading['syllables'] if reading else []
            prepared.append(entry)
        if not lesson_lock.acquire(blocking=False):
            return jsonify(error='Another AI request is running. Try again shortly.'), 429
        try:
            reply = answer_collection_question(
                language_row['name'], prepared, question, history, preferred)
        except ValueError as exc:
            return jsonify(error=str(exc)), 502
        finally:
            lesson_lock.release()
        return jsonify(reply=reply, language=language_row['name'], sources=[{'id': e['id'], 'phrase': e['phrase'], 'romanization': e['romanization'], 'ipa': e.get('ipa', '')} for e in prepared] if selected_id is not None else [])

    def render_library(selected='', translate_query='', translate_error=None, translation=None, error=None, values=None):
        fields = ('language', 'phrase', 'meaning', 'example', 'translation', 'context', 'romanization')
        if values is None:
            values = dict.fromkeys(fields, '')
        values['language'] = selected or values.get('language', '')
        with connect() as db:
            entries = db.execute('SELECT entries.*, languages.voice FROM entries JOIN languages ON entries.language=languages.name COLLATE NOCASE ORDER BY entries.id DESC').fetchall()
            collections = db.execute('SELECT languages.*, COUNT(entries.id) AS count FROM languages LEFT JOIN entries ON entries.language=languages.name COLLATE NOCASE GROUP BY languages.name ORDER BY languages.name').fetchall()
        total = len(entries)
        language_count = len(collections)
        if selected:
            entries = [entry for entry in entries if entry['language'].casefold() == selected.casefold()]
        query = request.args.get('q', '').strip()
        if query:
            entries = [entry for entry in entries if any(
                query.casefold() in (entry[key] or '').casefold() for key in fields)]
        import_errors = {
            '1': 'Choose a document to upload.',
            'type': 'Use a TXT, CSV, TSV, MD, or JSON text file.',
            'empty': 'That file was empty.',
            'size': 'Keep import files under 2 MB.',
            'busy': 'Another AI request is running. Try again shortly.',
            'ai': request.args.get('detail') or 'Could not extract phrases from that file.',
        }
        if request.args.get('audio_error') == '1':
            import_errors['audio'] = 'Choose an MP3, WAV, OGG, WebM, or M4A recording.'
        import_error = import_errors.get(request.args.get('import_error', ''))
        if request.args.get('audio_error') == '1':
            import_error = import_errors['audio']
        imported = request.args.get('imported')
        page_error = error or import_error
        return render_template(
            'index.html', entries=entries, total=total,
            languages=language_count, q=query, values=values,
            collections=collections, selected=selected,
            error=page_error,
            saved=request.args.get('saved') == '1',
            imported=int(imported) if imported and imported.isdigit() else None,
            import_mode=request.args.get('import_mode', ''),
            translation=translation,
            translate_query=translate_query,
            translate_error=translate_error,
        ), (400 if page_error else 200)

    def _with_phonetic(result, voice):
        """Fill Jyutping and IPA from the dictionary when this language has one."""
        found = lookup_phonetic(result.get('phrase') or '', voice or '')
        if found['romanization']:
            result['romanization'] = found['romanization']
            result['ipa'] = found['ipa']
        else:
            result['ipa'] = ''
        return result

    def remember_pair(language_name, result, review_status='pending'):
        """Store a phrase pair once. Generated pairs stay pending until a person verifies them."""
        with connect() as db:
            existing = db.execute(
                '''SELECT id, review_status, romanization FROM entries
                   WHERE language=? COLLATE NOCASE AND phrase=? AND meaning=?''',
                (language_name, result['phrase'], result['meaning'])).fetchone()
            if existing:
                result['id'] = existing['id']
                result['review_status'] = existing['review_status']
                result['from_collection'] = True
                if result.get('romanization') and not existing['romanization']:
                    db.execute(
                        'UPDATE entries SET romanization=? WHERE id=?',
                        (result['romanization'], existing['id']))
                elif not result.get('romanization') and existing['romanization']:
                    result['romanization'] = existing['romanization']
                return result
            cursor = db.execute(
                '''INSERT INTO entries
                   (language, phrase, meaning, example, translation, context, romanization, audio, review_status)
                   VALUES (?, ?, ?, '', '', ?, ?, '', ?)''',
                (language_name, result['phrase'], result['meaning'],
                 (result.get('note') or '')[:2000], result.get('romanization') or '', review_status))
            result['id'] = cursor.lastrowid
            result['review_status'] = review_status
            result['from_collection'] = False
        return result

    @app.post('/languages/<path:language>/translate')
    def translate_language(language):
        payload = request.get_json(silent=True) if request.is_json else {}
        payload = payload or {}
        supplied_phrase = (payload.get('phrase') or request.form.get('phrase') or '').strip()
        supplied_meaning = (payload.get('meaning') or request.form.get('meaning') or '').strip()
        text = (payload.get('text') or request.form.get('text') or supplied_phrase or supplied_meaning).strip()
        preferred = g.settings['explanation_language']
        with connect() as db:
            language_row = db.execute(
                'SELECT name, voice FROM languages WHERE name=?', (language,)).fetchone()
            entries = db.execute(
                '''SELECT id, phrase, romanization, meaning, context, review_status FROM entries
                   WHERE language=? COLLATE NOCASE ORDER BY id''',
                (language,)).fetchall() if language_row else []
        if not language_row:
            if request.is_json:
                return jsonify(error='Language not found'), 404
            return 'Language not found', 404
        if not text or len(text) > 300:
            message = 'Enter an idea under 300 characters.'
            if request.is_json:
                return jsonify(error=message), 400
            page, _status = render_library(
                language_row['name'], translate_query=text, translate_error=message)
            return page, 400
        if supplied_phrase and supplied_meaning:
            result = {
                'phrase': supplied_phrase,
                'meaning': supplied_meaning,
                'romanization': (payload.get('romanization') or request.form.get('romanization') or '').strip(),
                'note': '',
                'from_collection': False,
            }
            result = remember_pair(language_row['name'], _with_phonetic(result, language_row['voice']), 'verified')
        else:
            if not lesson_lock.acquire(blocking=False):
                message = 'Another AI request is running. Try again shortly.'
                if request.is_json:
                    return jsonify(error=message), 429
                page, _status = render_library(
                    language_row['name'], translate_query=text, translate_error=message)
                return page, 429
            try:
                examples = [entry for entry in entries if entry['review_status'] == 'verified']
                result = generate_translation(
                    language_row['name'], text, examples, preferred,
                    keep_phrase=supplied_phrase, keep_meaning=supplied_meaning)
                if supplied_phrase:
                    result['phrase'] = supplied_phrase
                if supplied_meaning:
                    result['meaning'] = supplied_meaning
            except ValueError as exc:
                if request.is_json:
                    return jsonify(error=str(exc)), 502
                page, _status = render_library(
                    language_row['name'], translate_query=text, translate_error=str(exc))
                return page, 502
            finally:
                lesson_lock.release()
            result = remember_pair(language_row['name'], _with_phonetic(result, language_row['voice']), 'pending')
        result['query'] = text
        result['related'] = [{
            'id': entry['id'],
            'phrase': entry['phrase'],
            'meaning': entry['meaning'],
            'romanization': entry['romanization'] or '',
        } for entry in related_entries(text, entries)]
        if request.is_json:
            return jsonify(
                id=result['id'],
                phrase=result['phrase'],
                meaning=result['meaning'],
                romanization=result.get('romanization') or '',
                ipa=result.get('ipa') or '',
                review_status=result['review_status'],
                note=result.get('note') or '',
            )
        return render_library(language_row['name'], translate_query=text, translation=result)

    @app.post('/languages/<path:language>/phonetic')
    def language_phonetic(language):
        payload = request.get_json(silent=True) if request.is_json else {}
        payload = payload or {}
        phrase = (payload.get('phrase') or request.form.get('phrase') or request.form.get('text') or '').strip()
        if not phrase or len(phrase) > 300:
            return jsonify(error='Enter a phrase under 300 characters.'), 400
        with connect() as db:
            language_row = db.execute(
                'SELECT name, voice FROM languages WHERE name=?', (language,)).fetchone()
        if not language_row:
            return jsonify(error='Language not found'), 404
        found = lookup_phonetic(phrase, language_row['voice'])
        if not found['romanization']:
            return jsonify(error='No pronunciation was found for that phrase.'), 404
        return jsonify(phrase=phrase, romanization=found['romanization'], ipa=found['ipa'])

    @app.post('/entries/<int:entry_id>/review')
    def review_entry(entry_id):
        with connect() as db:
            entry = db.execute(
                'SELECT id, language FROM entries WHERE id=?', (entry_id,)).fetchone()
            if not entry:
                if request.is_json:
                    return jsonify(error='Entry not found'), 404
                return 'Entry not found', 404
            db.execute("UPDATE entries SET review_status='verified' WHERE id=?", (entry_id,))
        if request.is_json:
            return jsonify(id=entry_id, review_status='verified')
        return redirect(url_for('index', language=entry['language']), code=303)

    @app.post('/languages/<path:language>/lesson/delete')
    def delete_language_lesson(language):
        level = request.form.get('level', 'new')
        preferred = g.settings['explanation_language']
        scope = request.form.get('scope', 'current')
        if level not in LEVELS:
            return 'Choose a supported level.', 400
        with connect() as db:
            language_row = db.execute(
                'SELECT name FROM languages WHERE name=?', (language,)).fetchone()
            if not language_row:
                return 'Language not found', 404
            language = language_row['name']
            if scope == 'all':
                db.execute(
                    'DELETE FROM language_lesson_variants WHERE language=? COLLATE NOCASE',
                    (language,))
            else:
                db.execute(
                    '''DELETE FROM language_lesson_variants
                       WHERE language=? COLLATE NOCASE AND level=? AND preferred=?''',
                    (language, level, preferred))
        return redirect(url_for('language_lesson', language=language, level=level), code=303)

    @app.post('/languages/<path:language>/import')
    def import_document(language):
        preferred = g.settings['explanation_language']
        upload = request.files.get('document')
        use_ai = request.form.get('use_ai') == '1'
        with connect() as db:
            language_row = db.execute(
                'SELECT name, voice FROM languages WHERE name=?', (language,)).fetchone()
        if not language_row:
            return 'Language not found', 404
        language = language_row['name']
        if not upload or not (upload.filename or '').strip():
            return redirect(url_for('index', language=language, import_error='1'), code=303)
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            return redirect(url_for('index', language=language, import_error='type'), code=303)
        raw = upload.read()
        if not raw:
            return redirect(url_for('index', language=language, import_error='empty'), code=303)
        if len(raw) > 2 * 1024 * 1024:
            return redirect(url_for('index', language=language, import_error='size'), code=303)
        try:
            text = decode_upload(raw)
            if not lesson_lock.acquire(blocking=False):
                return redirect(url_for('index', language=language, import_error='busy'), code=303)
            try:
                entries, mode = extract_entries_from_document(
                    text, language, preferred=preferred, use_ai=use_ai)
            finally:
                lesson_lock.release()
        except ValueError as exc:
            return redirect(
                url_for('index', language=language, import_error='ai', detail=str(exc)[:180]),
                code=303)

        inserted = 0
        with connect() as db:
            existing = {
                row['phrase'].casefold()
                for row in db.execute(
                    'SELECT phrase FROM entries WHERE language=? COLLATE NOCASE',
                    (language,)).fetchall()
            }
            for entry in entries:
                key = entry['phrase'].casefold()
                if key in existing:
                    continue
                if bool(entry['example']) != bool(entry['translation']):
                    entry['example'] = ''
                    entry['translation'] = ''
                if not entry['romanization']:
                    entry['romanization'] = lookup_phonetic(entry['phrase'], language_row['voice'])['romanization']
                db.execute(
                    '''INSERT INTO entries
                       (language, phrase, meaning, example, translation, context, romanization, audio, review_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (language, entry['phrase'], entry['meaning'], entry['example'],
                     entry['translation'], entry['context'], entry['romanization'], '',
                     'pending' if mode == 'ai' else 'verified'))
                existing.add(key)
                inserted += 1
        return redirect(
            url_for('index', language=language, imported=inserted, import_mode=mode),
            code=303)

    @app.route('/entries/<int:entry_id>/lesson', methods=['GET', 'POST'])
    def lesson(entry_id):
        with connect() as db:
            entry = db.execute('SELECT language FROM entries WHERE id=?', (entry_id,)).fetchone()
        if not entry:
            return 'Entry not found', 404
        return redirect(
            url_for('language_lesson', language=entry['language'],
                    level=request.values.get('level', 'new')),
            code=303)

    @app.post('/languages')
    def add_language():
        name = request.form.get('name', '').strip()
        voice = request.form.get('voice', '')
        if not name or len(name) > 100 or voice not in ('', 'zh-CN', 'yue-HK', 'en-US', 'fr-FR', 'es-ES', 'hi-IN', 'ja-JP', 'ko-KR', 'ar-SA'):
            return 'Enter a language name (up to 100 characters) and choose a voice language.', 400
        with connect() as db:
            db.execute('INSERT OR IGNORE INTO languages(name, voice) VALUES (?, ?)', (name, voice))
        return redirect(url_for('index', language=name), code=303)

    @app.post('/entries/<int:entry_id>/audio')
    def attach_audio(entry_id):
        upload = request.files.get('audio')
        suffix = Path(upload.filename or '').suffix.lower() if upload else ''
        with connect() as db:
            entry = db.execute(
                'SELECT id, language, audio FROM entries WHERE id=?', (entry_id,)).fetchone()
        if not entry:
            return 'Entry not found', 404
        if not upload or suffix not in ('.mp3', '.wav', '.ogg', '.webm', '.m4a'):
            return redirect(url_for('index', language=entry['language'], audio_error='1'), code=303)
        filename = uuid.uuid4().hex + suffix
        upload.save(audio_dir / filename)
        old = entry['audio'] or ''
        if old and Path(old).name == old and (audio_dir / old).is_file():
            (audio_dir / old).unlink()
        with connect() as db:
            db.execute('UPDATE entries SET audio=? WHERE id=?', (filename, entry_id))
        return redirect(url_for('index', language=entry['language']), code=303)

    @app.get('/audio/<filename>')
    def audio_file(filename):
        return send_from_directory(audio_dir, filename)

    @app.errorhandler(413)
    def too_large(error):
        return 'Recording is too large. Go back and choose a file smaller than 10 MB.', 413

    @app.route('/', methods=['GET', 'POST'])
    def index():
        fields = ('language', 'phrase', 'meaning', 'example', 'translation', 'context', 'romanization')
        values = dict.fromkeys(fields, '')
        selected = request.args.get('language', '').strip()
        if selected:
            with connect() as db:
                selected_row = db.execute('SELECT name FROM languages WHERE name=?', (selected,)).fetchone()
            if not selected_row:
                return 'Language not found', 404
            selected = selected_row['name']
        values['language'] = selected
        error = None
        if request.method == 'POST':
            values = {key: request.form.get(key, '').strip() for key in fields}
            if selected:
                values['language'] = selected
            else:
                selected = values['language']
            review_status = 'verified'
            if not values['language'] or not (values['phrase'] or values['meaning']):
                error = 'Enter a language and either a phrase, a meaning, or both.'
            elif any(len(value) > 2000 for value in values.values()):
                error = 'Keep each field under 2,000 characters.'
            elif bool(values['example']) != bool(values['translation']):
                error = 'Include both the example and its English meaning, or leave both empty.'
            else:
                with connect() as db:
                    language = db.execute(
                        'SELECT name, voice FROM languages WHERE name=?', (values['language'],)).fetchone()
                upload = request.files.get('audio')
                suffix = Path(upload.filename or '').suffix.lower() if upload else ''
                if not language:
                    error = 'Add the language collection first, then select it.'
                elif upload and suffix not in ('.mp3', '.wav', '.ogg', '.webm', '.m4a'):
                    error = 'Choose an MP3, WAV, OGG, WebM, or M4A recording.'
                elif bool(values['phrase']) != bool(values['meaning']):
                    if not lesson_lock.acquire(blocking=False):
                        error = 'Another AI request is running. Try again shortly.'
                    else:
                        try:
                            with connect() as db:
                                samples = db.execute(
                                    '''SELECT phrase, romanization, meaning FROM entries
                                       WHERE language=? COLLATE NOCASE AND review_status='verified'
                                       ORDER BY id''',
                                    (language['name'],)).fetchall()
                            generated = generate_translation(
                                language['name'], values['phrase'] or values['meaning'], samples,
                                g.settings['explanation_language'],
                                keep_phrase=values['phrase'], keep_meaning=values['meaning'])
                            if values['phrase']:
                                generated['phrase'] = values['phrase']
                            if values['meaning']:
                                generated['meaning'] = values['meaning']
                            values['phrase'] = generated['phrase']
                            values['meaning'] = generated['meaning']
                            if not values['context']:
                                values['context'] = generated['note']
                            review_status = 'pending'
                        except ValueError as exc:
                            error = str(exc)
                        finally:
                            lesson_lock.release()
            if not error:
                if not values['romanization']:
                    values['romanization'] = lookup_phonetic(values['phrase'], language['voice'])['romanization']
                values['language'] = language['name']
                filename = uuid.uuid4().hex + suffix if upload else ''
                if upload:
                    upload.save(audio_dir / filename)
                with connect() as db:
                    db.execute('''INSERT INTO entries
                        (language, phrase, meaning, example, translation, context, romanization, audio, review_status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (*values.values(), filename, review_status))
                return redirect(url_for('index', saved='1', language=values['language']), code=303)
        return render_library(selected, error=error, values=values)

    register_learning(app, connect, lesson_lock)
    return app


# Vercel imports this module and requires a top-level Flask instance named app.
app = create_app()


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
