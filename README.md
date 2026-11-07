# Commonword

### Dictionary and word questions

Dictionary searches now check exact headword membership in the bundled official Rime
Cantonese word lists under `resources/rime/` (source revision and license included).
For a match, **Get unverified AI translation** sends the
headword and sourced pronunciation to Featherless. The meaning is AI-generated,
not a Rime definition; it is saved as pending and excluded from lessons/chat until
human review. Results are cached per language, headword, and explanation language.
No AI call is made for unmatched words or on ordinary searches. This lookup expects
Chinese-character headwords; English and Jyutping searches still search saved entries.

Open a language collection and select **Dictionary · Ask about words**. The
dictionary lists verified contributions, searchable by original text, meaning,
and dictionary pronunciation. It is the collection's word section, not a complete
external dictionary of definitions. Cantonese readings use Rime via ToJyutping;
syllable details explain tone numbers and show IPA from the existing LSHK mapping.
Unknown parts now prevent incomplete readings from appearing as full pronunciation.

**Ask about this word** selects that verified entry for the corner chat. Submit a
question to call Featherless. Chat receives the dictionary reading and tone details,
and its reply includes a separate dictionary reference. Pending entries are excluded.
Meanings remain contributor-provided; the AI is instructed not to invent vocabulary.

A local language library with Flask and SQLite. Includes the contributor-provided
Cantonese entry 我 (I / me), with 我係… (I am…) as its example.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Open http://127.0.0.1:5000. Stop with Ctrl+C. The app binds to localhost only.
Entries persist in `data/languages.db`; back up this file to preserve contributions.
The sample is inserted only once. Search checks all entry fields.

Use **Add language** to create a collection and choose its browser voice language.
Entries have original writing, Latin-letter pronunciation, English meaning, examples,
and context. Existing databases are migrated automatically without removing entries.

Upload MP3, WAV, OGG, WebM, or M4A recordings (under 10 MB), or use the microphone
button to record up to 60 seconds. Recordings live in `data/audio/`; back up this
folder along with the database. Normal and slow playback use the recording first.
Without one, the app uses a matching installed browser voice. Voice availability
depends on the browser/device; some system voices require internet. Microphone
capture requires localhost or HTTPS and the user's permission.

## Featherless practice lessons

Set `AI_API_KEY` in the ignored `.env` file. Optional `FEATHERLESS_MODEL` defaults
to `Qwen/Qwen2.5-7B-Instruct`. Select **Create practice lesson** on an entry.
Only clicking the generation button calls Featherless; entry text is sent, not audio.
Output is capped at 450 tokens and cached in SQLite. Lessons are labeled as drafts.
Keys remain on the server. This cap is not a dollar-budget guarantee; check usage
in your Featherless dashboard. No automatic retries are made.

## Learning schedules

Discover lists collections saved in this local library, with search and favourites.
Choose Learn to create a two-week plan: daily, Mon/Wed/Fri, weekdays, or weekends,
at 5, 10, 20, or 30 minutes per session. Dates use America/Toronto. Basic goals are
available without AI; Generate AI coaching sends the scheduled entry text and
minutes to Featherless once (up to 1,400 output tokens), then caches the goals.
An AI failure preserves the basic plan. Mark sessions complete or undo completion.
Small collections repeat words for recall. Plans are snapshots; new entries are
included by creating a new plan. No push notifications or background AI jobs run.

This is a single local profile: favourites and learning progress are shared by
everyone using this app instance. Accounts, reviews, and revision history are not
yet implemented. Choose code and contribution-data licenses before release.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```
