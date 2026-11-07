"""Run the local language library with python main.py."""
from pathlib import Path
from contextlib import contextmanager
import json
import os
import sqlite3
import uuid
from threading import Lock
from ai_lessons import answer_collection_question, generate_language_lesson, lesson_from_storage
from document_import import TEXT_SUFFIXES, decode_upload, extract_entries_from_document
from learning import register_learning
from preferences import LEVELS, LANGUAGES
from i18n import UI_LANGUAGES, explanation_for, t
from phonetics import jyutping_to_ipa
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
                   WHERE entries.language=? COLLATE NOCASE ORDER BY entries.id''',
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

    @app.post('/languages/<path:language>/chat')
    def language_chat(language):
        payload = request.get_json(silent=True) or {}
        question = (payload.get('question') or '').strip()
        history = payload.get('history') or []
        if not question or len(question) > 500:
            return jsonify(error='Ask a question under 500 characters.'), 400
        if not isinstance(history, list) or len(history) > 12:
            return jsonify(error='The conversation is too long. Start again.'), 400
        preferred = g.settings['explanation_language']
        with connect() as db:
            language_row = db.execute(
                'SELECT name FROM languages WHERE name=?', (language,)).fetchone()
            entries = db.execute(
                '''SELECT phrase, romanization, meaning, context FROM entries
                   WHERE language=? COLLATE NOCASE ORDER BY id''',
                (language,)).fetchall() if language_row else []
        if not language_row:
            return jsonify(error='Language not found'), 404
        if not entries:
            return jsonify(error='Add a phrase to this language before asking about it.'), 400
        if not lesson_lock.acquire(blocking=False):
            return jsonify(error='Another AI request is running. Try again shortly.'), 429
        try:
            reply = answer_collection_question(
                language_row['name'], entries, question, history, preferred)
        except ValueError as exc:
            return jsonify(error=str(exc)), 502
        finally:
            lesson_lock.release()
        return jsonify(reply=reply, language=language_row['name'])

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
                'SELECT name FROM languages WHERE name=?', (language,)).fetchone()
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
                db.execute(
                    '''INSERT INTO entries
                       (language, phrase, meaning, example, translation, context, romanization, audio)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (language, entry['phrase'], entry['meaning'], entry['example'],
                     entry['translation'], entry['context'], entry['romanization'], ''))
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
            if any(not values[key] for key in fields[:3]):
                error = 'Please enter a language, a phrase, and its English meaning.'
            elif any(len(value) > 2000 for value in values.values()):
                error = 'Keep each field under 2,000 characters.'
            elif bool(values['example']) != bool(values['translation']):
                error = 'Include both the example and its English meaning, or leave both empty.'
            else:
                with connect() as db:
                    language = db.execute('SELECT name FROM languages WHERE name=?', (values['language'],)).fetchone()
                upload = request.files.get('audio')
                suffix = Path(upload.filename or '').suffix.lower() if upload else ''
                if not language:
                    error = 'Add the language collection first, then select it.'
                elif upload and suffix not in ('.mp3', '.wav', '.ogg', '.webm', '.m4a'):
                    error = 'Choose an MP3, WAV, OGG, WebM, or M4A recording.'
            if not error:
                values['language'] = language['name']
                filename = uuid.uuid4().hex + suffix if upload else ''
                if upload:
                    upload.save(audio_dir / filename)
                with connect() as db:
                    db.execute('''INSERT INTO entries
                        (language, phrase, meaning, example, translation, context, romanization, audio)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (*values.values(), filename))
                return redirect(url_for('index', saved='1', language=values['language']), code=303)
        with connect() as db:
            entries = db.execute('SELECT entries.*, languages.voice FROM entries JOIN languages ON entries.language=languages.name COLLATE NOCASE ORDER BY entries.id DESC').fetchall()
            collections = db.execute('SELECT languages.*, COUNT(entries.id) AS count FROM languages LEFT JOIN entries ON entries.language=languages.name COLLATE NOCASE GROUP BY languages.name ORDER BY languages.name').fetchall()
        total = len(entries)
        languages = len(collections)
        if selected:
            entries = [entry for entry in entries if entry['language'].casefold() == selected.casefold()]
        query = request.args.get('q', '').strip()
        if query:
            entries = [entry for entry in entries if any(
                query.casefold() in entry[key].casefold() for key in fields)]
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
        return render_template(
            'index.html', entries=entries, total=total,
            languages=languages, q=query, values=values,
            collections=collections, selected=selected,
            error=error or import_error,
            saved=request.args.get('saved') == '1',
            imported=int(imported) if imported and imported.isdigit() else None,
            import_mode=request.args.get('import_mode', ''),
        ), (400 if error or import_error else 200)

    register_learning(app, connect, lesson_lock)
    return app


# Vercel imports this module and requires a top-level Flask instance named app.
app = create_app()


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
