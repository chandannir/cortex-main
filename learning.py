"""Local learner favourites and dated, two-week learning plans."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import Blueprint, g, render_template, request, redirect, url_for
from ai_lessons import generate_study_goals
from preferences import LEVELS, LANGUAGES
from i18n import explanation_for

FREQUENCIES = {'daily': ('Daily', set(range(7))),
               'three': ('3 times a week · Mon / Wed / Fri', {0, 2, 4}),
               'weekdays': ('Weekdays · Mon–Fri', {0, 1, 2, 3, 4}),
               'weekends': ('Weekends · Sat / Sun', {5, 6})}


def today():
    try:
        return datetime.now(ZoneInfo('America/Toronto')).date()
    except ZoneInfoNotFoundError:
        return datetime.now(timezone.utc).date()


def session_dates(start, frequency):
    return [start + timedelta(days=i) for i in range(14)
            if (start + timedelta(days=i)).weekday() in FREQUENCIES[frequency][1]]


def register_learning(app, connect, lock):
    bp = Blueprint('learning', __name__)
    app.jinja_env.filters['study_date'] = lambda value: date.fromisoformat(value).strftime('%A, %B %d, %Y')
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS favourites(language TEXT PRIMARY KEY COLLATE NOCASE);
        CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, language TEXT NOT NULL,
            frequency TEXT NOT NULL, minutes INTEGER NOT NULL, start TEXT NOT NULL,
            ai_ready INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL,
            due TEXT NOT NULL, entry_id INTEGER NOT NULL, goal TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0);
        ''')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(plans)')}
        for column, default in (('level', 'new'), ('preferred', 'English')):
            if column not in columns:
                db.execute(f"ALTER TABLE plans ADD COLUMN {column} TEXT NOT NULL DEFAULT '{default}'")

    @bp.get('/discover')
    def discover():
        query = request.args.get('q', '').strip()
        only = request.args.get('favourites') == '1'
        with connect() as db:
            languages = db.execute('''SELECT l.name, COUNT(e.id) AS count,
                EXISTS(SELECT 1 FROM favourites f WHERE f.language=l.name) AS favourite
                FROM languages l LEFT JOIN entries e ON e.language=l.name COLLATE NOCASE
                GROUP BY l.name ORDER BY l.name''').fetchall()
        languages = [l for l in languages if query.casefold() in l['name'].casefold()
                     and (not only or l['favourite'])]
        return render_template('discover.html', languages=languages, q=query, only=only)

    @bp.post('/favourite')
    def favourite():
        with connect() as db:
            row = db.execute('SELECT name FROM languages WHERE name=?', (request.form.get('language', ''),)).fetchone()
            if not row:
                return 'Language not found', 404
            if request.form.get('save') == '1':
                db.execute('INSERT OR IGNORE INTO favourites VALUES (?)', (row['name'],))
            else:
                db.execute('DELETE FROM favourites WHERE language=?', (row['name'],))
        return redirect(url_for('learning.discover', favourites=request.form.get('filter', '')), code=303)

    @bp.route('/learn', methods=['GET', 'POST'])
    def learn():
        name = request.values.get('language', '')
        with connect() as db:
            language = db.execute('SELECT name FROM languages WHERE name=?', (name,)).fetchone()
            entries = db.execute(
                "SELECT * FROM entries WHERE language=? COLLATE NOCASE AND review_status='verified' ORDER BY id",
                (name,)).fetchall()
        if not language:
            return 'Language not found', 404
        error = None
        if request.method == 'POST':
            frequency = request.form.get('frequency')
            minutes = request.form.get('minutes')
            level = request.form.get('level', 'new')
            ui = getattr(g, 'settings', {}).get('ui_language', 'en')
            preferred = explanation_for(ui)
            try:
                start = date.fromisoformat(request.form.get('start', ''))
            except ValueError:
                start = None
            if not entries:
                error = 'Add at least one word to this language before creating a plan.'
            elif level not in LEVELS or preferred not in LANGUAGES or frequency not in FREQUENCIES or minutes not in ('5', '10', '20', '30') or not start or not today() <= start <= today() + timedelta(days=366):
                error = 'Choose a valid frequency, study time, and a start date within the next year.'
            else:
                with connect() as db:
                    plan_id = db.execute('INSERT INTO plans(language,frequency,minutes,start,level,preferred) VALUES(?,?,?,?,?,?)',
                        (language['name'], frequency, int(minutes), start.isoformat(), level, preferred)).lastrowid
                    for i, due in enumerate(session_dates(start, frequency)):
                        entry = entries[i % len(entries)]
                        action = 'Learn' if i < len(entries) else 'Review'
                        tasks = {'new': 'Read the meaning, cover it and recall it, then check your answer.',
                                 'intermediate': 'Recall the meaning without looking. Explain its supplied usage context and check the example.',
                                 'everyday': 'Practise choosing when to use this phrase based on its contributed context. Note any missing usage information.'}
                        goal = f"{action} {entry['phrase']} ({entry['meaning']}). {tasks[level]} Spend {minutes} minutes practising."
                        db.execute('INSERT INTO sessions(plan_id,due,entry_id,goal) VALUES(?,?,?,?)',
                            (plan_id, due.isoformat(), entry['id'], goal))
                return redirect(url_for('learning.plan', plan_id=plan_id), code=303)
        return render_template('learn.html', language=language['name'], count=len(entries),
            frequencies=FREQUENCIES, today=today().isoformat(), error=error,
            levels=LEVELS, explanation_languages=LANGUAGES), 400 if error else 200

    @bp.get('/study')
    def study():
        with connect() as db:
            plans = db.execute('''SELECT p.*, COUNT(s.id) AS total, SUM(s.completed) AS done
                FROM plans p JOIN sessions s ON s.plan_id=p.id GROUP BY p.id ORDER BY p.id DESC''').fetchall()
        return render_template('study.html', plans=plans, frequencies=FREQUENCIES)

    @bp.route('/study/<int:plan_id>', methods=['GET', 'POST'])
    def plan(plan_id):
        error = None
        with connect() as db:
            plan = db.execute('SELECT * FROM plans WHERE id=?', (plan_id,)).fetchone()
            sessions = db.execute('''SELECT s.*, e.language, e.phrase, e.meaning, e.romanization,
                e.example, e.translation, e.context FROM sessions s JOIN entries e ON e.id=s.entry_id
                WHERE plan_id=? ORDER BY s.due''', (plan_id,)).fetchall()
        if not plan:
            return 'Plan not found', 404
        if request.method == 'POST' and not plan['ai_ready']:
            if not lock.acquire(blocking=False):
                error = 'Another AI request is running. Please try again shortly.'
            else:
                try:
                    with connect() as db:
                        ready = db.execute('SELECT ai_ready FROM plans WHERE id=?', (plan_id,)).fetchone()[0]
                    if not ready:
                        source = [{k: s[k] for k in ('due', 'language', 'phrase', 'meaning', 'romanization', 'example', 'translation', 'context')} for s in sessions]
                        goals = generate_study_goals(source, plan['minutes'], plan['level'], plan['preferred'])
                        with connect() as db:
                            for session, goal in zip(sessions, goals):
                                db.execute('UPDATE sessions SET goal=? WHERE id=?', (goal, session['id']))
                            db.execute('UPDATE plans SET ai_ready=1 WHERE id=?', (plan_id,))
                    return redirect(url_for('learning.plan', plan_id=plan_id), code=303)
                except ValueError as exc:
                    error = str(exc)
                finally:
                    lock.release()
        return render_template('plan.html', plan=plan, sessions=sessions, error=error,
            today=today().isoformat(), frequencies=FREQUENCIES,
            done=sum(s['completed'] for s in sessions))

    @bp.post('/study/<int:plan_id>/complete/<int:session_id>')
    def complete(plan_id, session_id):
        with connect() as db:
            db.execute('UPDATE sessions SET completed=? WHERE id=? AND plan_id=?',
                       (1 if request.form.get('done') == '1' else 0, session_id, plan_id))
        return redirect(url_for('learning.plan', plan_id=plan_id), code=303)

    app.register_blueprint(bp)
