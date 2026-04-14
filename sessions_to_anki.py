#!/usr/bin/env python3
"""Convert Claude Code session JSONL files into an Anki flashcard deck (.apkg)."""

import hashlib
import html
import json
import re
import sqlite3
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "sessions.apkg"

# ── Session / index parsing ───────────────────────────────────────────────────

def parse_session(jsonl_path):
    """Parse a JSONL session file into a list of message dicts."""
    messages = []
    try:
        with open(jsonl_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get('type') not in ('user', 'assistant'):
                    continue

                msg = obj.get('message', {})
                role = msg.get('role')
                if role not in ('user', 'assistant'):
                    continue

                content = msg.get('content', '')

                # Drop user messages that are purely tool results with no text
                if role == 'user' and isinstance(content, list):
                    has_text = any(
                        (isinstance(b, str) and b.strip()) or
                        (isinstance(b, dict) and b.get('type') == 'text' and b.get('text', '').strip())
                        for b in content
                    )
                    if not has_text:
                        continue

                if role == 'user' and isinstance(content, str) and not content.strip():
                    continue

                messages.append({
                    'role': role,
                    'content': content,
                    'timestamp': obj.get('timestamp'),
                })
    except Exception as e:
        print(f'  Warning: could not parse {jsonl_path}: {e}', file=sys.stderr)

    return messages


def build_global_index(base_dir):
    """Load all sessions-index.json files and return a merged {sessionId: entry} map."""
    index_map = {}
    if not base_dir.exists():
        return index_map
    for project_dir in base_dir.iterdir():
        if not project_dir.is_dir():
            continue
        idx_path = project_dir / 'sessions-index.json'
        if idx_path.exists():
            try:
                with open(idx_path, encoding='utf-8') as f:
                    idx = json.load(f)
                for entry in idx.get('entries', []):
                    sid = entry.get('sessionId')
                    if sid:
                        index_map[sid] = entry
            except Exception:
                pass
    return index_map


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text(content):
    """Extract plain text from a message content field (str or list of blocks)."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get('type') == 'text':
                parts.append(block.get('text', ''))
    return '\n'.join(p for p in parts if p.strip())


def strip_markdown(text):
    """Remove basic markdown formatting, leaving plain text."""
    # Remove fenced code blocks (keep content)
    text = re.sub(r'```[^\n]*\n(.*?)```', r'\1', text, flags=re.DOTALL)
    # Remove inline code backticks
    text = re.sub(r'`([^`\n]+)`', r'\1', text)
    # Remove bold-italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    # Remove bold
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # Remove italic
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    # Remove markdown links, keep text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove ATX headings markers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    return text.strip()


# ── Card extraction ───────────────────────────────────────────────────────────

def project_display_name(project_dir_name):
    """Convert a filesystem-encoded project dir name to a human-readable path."""
    name = project_dir_name.lstrip('-').replace('-', '/')
    name = re.sub(r'^Users/[^/]+/', '~/', name)
    return name


def sanitise_tag(name):
    """Sanitise a project name for use as an Anki tag segment."""
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'[^a-zA-Z0-9_/~.-]', '', name)
    return name


def extract_cards_from_session(messages, project_tag):
    """Extract Q&A flashcard pairs from a parsed session's messages.

    Rules:
    - User message with '?' → pair with next assistant text response
    - Answer truncated to 2000 chars
    - Question must be 10–300 chars, answer 20–2000 chars
    - Both stripped of basic markdown
    """
    cards = []
    tags = f'claude-session {project_tag}'

    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg['role'] != 'user':
            i += 1
            continue

        user_text = extract_text(msg['content'])
        user_text = strip_markdown(user_text)

        if not user_text or '?' not in user_text:
            i += 1
            continue

        # Find the next assistant message
        j = i + 1
        while j < len(messages) and messages[j]['role'] != 'assistant':
            j += 1

        if j >= len(messages):
            i += 1
            continue

        asst_text = extract_text(messages[j]['content'])
        asst_text = strip_markdown(asst_text)

        # Use the first line of the user message that has '?' as the question
        question = ''
        for line in user_text.splitlines():
            if '?' in line:
                question = line.strip()
                break
        if not question:
            question = user_text.splitlines()[0].strip() if user_text.splitlines() else user_text

        answer = asst_text
        if len(answer) > 2000:
            answer = answer[:2000]

        question = question.strip()
        answer = answer.strip()

        if not question or not answer:
            i += 1
            continue

        if not (10 <= len(question) <= 300):
            i += 1
            continue

        if not (20 <= len(answer) <= 2000):
            i += 1
            continue

        cards.append({
            'front': question,
            'back': answer,
            'tags': tags,
        })

        i = j + 1

    return cards


# ── Anki data helpers ─────────────────────────────────────────────────────────

def make_guid(text):
    """Generate a 10-char base62-ish guid from text."""
    h = hashlib.sha1(text.encode('utf-8')).hexdigest()
    # Use a subset of the hex chars — Anki accepts any 10-char string
    return h[:10]


def make_csum(text):
    """Checksum: first 8 hex digits of sha1 of text, interpreted as int."""
    h = hashlib.sha1(text.encode('utf-8')).hexdigest()
    return int(h[:8], 16)


# ── Anki database builder ─────────────────────────────────────────────────────

ANKI_SCHEMA = """
CREATE TABLE col (
  id    INTEGER PRIMARY KEY,
  crt   INTEGER NOT NULL,
  mod   INTEGER NOT NULL,
  scm   INTEGER NOT NULL,
  ver   INTEGER NOT NULL,
  dty   INTEGER NOT NULL,
  usn   INTEGER NOT NULL,
  ls    INTEGER NOT NULL,
  conf  TEXT NOT NULL,
  models TEXT NOT NULL,
  decks TEXT NOT NULL,
  dconf TEXT NOT NULL,
  tags  TEXT NOT NULL
);

CREATE TABLE notes (
  id    INTEGER PRIMARY KEY,
  guid  TEXT NOT NULL,
  mid   INTEGER NOT NULL,
  mod   INTEGER NOT NULL,
  usn   INTEGER NOT NULL,
  tags  TEXT NOT NULL,
  flds  TEXT NOT NULL,
  sfld  TEXT NOT NULL,
  csum  INTEGER NOT NULL,
  flags INTEGER NOT NULL,
  data  TEXT NOT NULL
);

CREATE TABLE cards (
  id      INTEGER PRIMARY KEY,
  nid     INTEGER NOT NULL,
  did     INTEGER NOT NULL,
  ord     INTEGER NOT NULL,
  mod     INTEGER NOT NULL,
  usn     INTEGER NOT NULL,
  type    INTEGER NOT NULL,
  queue   INTEGER NOT NULL,
  due     INTEGER NOT NULL,
  ivl     INTEGER NOT NULL,
  factor  INTEGER NOT NULL,
  reps    INTEGER NOT NULL,
  lapses  INTEGER NOT NULL,
  left    INTEGER NOT NULL,
  odue    INTEGER NOT NULL,
  odid    INTEGER NOT NULL,
  flags   INTEGER NOT NULL,
  data    TEXT NOT NULL
);

CREATE TABLE revlog (
  id      INTEGER PRIMARY KEY,
  cid     INTEGER,
  usn     INTEGER,
  ease    INTEGER,
  ivl     INTEGER,
  lastIvl INTEGER,
  factor  INTEGER,
  time    INTEGER,
  type    INTEGER
);

CREATE TABLE graves (
  usn  INTEGER,
  oid  INTEGER,
  type INTEGER
);
"""

CARD_CSS = """\
.card {
  font-family: Arial, sans-serif;
  font-size: 18px;
  text-align: center;
  color: black;
  background-color: white;
}
"""


def build_anki2(cards, db_path):
    """Write an Anki 2 collection.anki2 SQLite file to db_path."""
    now_sec = int(time.time())
    now_ms = int(now_sec * 1000)

    deck_id = 1700000000000
    model_id = 1700000000001

    model = {
        str(model_id): {
            "id": model_id,
            "name": "Claude Sessions Basic",
            "type": 0,
            "mod": now_sec,
            "usn": -1,
            "sortf": 0,
            "did": deck_id,
            "tmpls": [{
                "name": "Card 1",
                "ord": 0,
                "qfmt": "{{Front}}",
                "afmt": "{{FrontSide}}\n<hr id=answer>\n{{Back}}",
                "bqfmt": "",
                "bafmt": "",
                "did": None,
                "bfont": "",
                "bsize": 0,
            }],
            "flds": [
                {"name": "Front", "ord": 0, "sticky": False, "rtl": False,
                 "font": "Arial", "size": 20, "media": []},
                {"name": "Back", "ord": 1, "sticky": False, "rtl": False,
                 "font": "Arial", "size": 20, "media": []},
            ],
            "css": CARD_CSS,
            "latexPre": "",
            "latexPost": "",
            "req": [[0, "any", [0]]],
            "tags": [],
            "vers": [],
        }
    }

    deck = {
        str(deck_id): {
            "id": deck_id,
            "name": "Claude Sessions",
            "desc": "Flashcards extracted from Claude Code conversations",
            "mod": now_sec,
            "usn": -1,
            "lrnToday": [0, 0],
            "revToday": [0, 0],
            "newToday": [0, 0],
            "timeToday": [0, 0],
            "collapsed": False,
            "newDayStartingHour": 4,
            "extendNew": 10,
            "extendRev": 50,
            "conf": 1,
            "dyn": 0,
        }
    }

    col_conf = json.dumps({
        "nextPos": 1,
        "estTimes": True,
        "activeDecks": [deck_id],
        "sortType": "noteFld",
        "timeLim": 0,
        "sortBackwards": False,
        "addToCur": True,
        "curDeck": deck_id,
        "newBury": True,
        "newSpread": 0,
        "dueCounts": True,
        "curModel": model_id,
        "collapseTime": 1200,
    })

    dconf = json.dumps({
        "1": {
            "id": 1,
            "mod": 0,
            "name": "Default",
            "usn": -1,
            "maxTaken": 60,
            "autoplay": True,
            "timer": 0,
            "replayq": True,
            "new": {
                "bury": False,
                "delays": [1, 10],
                "initialFactor": 2500,
                "ints": [1, 4, 0],
                "order": 1,
                "perDay": 20,
            },
            "lapse": {
                "delays": [10],
                "leechAction": 0,
                "leechFails": 8,
                "minInt": 1,
                "mult": 0,
            },
            "rev": {
                "bury": False,
                "ease4": 1.3,
                "fuzz": 0.05,
                "ivlFct": 1,
                "maxIvl": 36500,
                "minSpace": 1,
                "perDay": 200,
            },
        }
    })

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(ANKI_SCHEMA)

        conn.execute(
            "INSERT INTO col VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                1,           # id
                now_sec,     # crt
                now_sec,     # mod
                now_ms,      # scm
                11,          # ver
                0,           # dty
                0,           # usn
                0,           # ls
                col_conf,
                json.dumps(model),
                json.dumps(deck),
                dconf,
                "{}",        # tags
            )
        )

        for offset, card in enumerate(cards):
            note_id = now_ms + offset
            card_id = now_ms + offset + 1_000_000  # separate id space

            front = card['front']
            back = card['back']
            tags_str = ' ' + card['tags'] + ' '

            flds = front + '\x1f' + back
            sfld = front
            guid = make_guid(front + str(note_id))
            csum = make_csum(front)

            conn.execute(
                "INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    note_id,
                    guid,
                    model_id,
                    now_sec,
                    -1,          # usn
                    tags_str,
                    flds,
                    sfld,
                    csum,
                    0,           # flags
                    "",          # data
                )
            )

            conn.execute(
                "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    card_id,
                    note_id,
                    deck_id,
                    0,           # ord
                    now_sec,     # mod
                    -1,          # usn
                    0,           # type = new
                    0,           # queue = new
                    offset + 1,  # due (position in new queue)
                    0,           # ivl
                    0,           # factor
                    0,           # reps
                    0,           # lapses
                    0,           # left
                    0,           # odue
                    0,           # odid
                    0,           # flags
                    "",          # data
                )
            )

        conn.commit()
    finally:
        conn.close()


# ── .apkg assembly ────────────────────────────────────────────────────────────

def build_apkg(cards, output_path):
    """Build a .apkg ZIP file containing collection.anki2 and media."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "collection.anki2"
        build_anki2(cards, db_path)

        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as apkg:
            apkg.write(db_path, "collection.anki2")
            apkg.writestr("media", "{}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT

    if not CLAUDE_DIR.exists():
        print(f'Claude projects dir not found: {CLAUDE_DIR}', file=sys.stderr)
        sys.exit(1)

    index_map = build_global_index(CLAUDE_DIR)

    all_cards = []
    total_sessions = 0

    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name
        display = project_display_name(project_name)
        tag = 'claude-project:' + sanitise_tag(display)

        jsonl_files = sorted(project_dir.glob('*.jsonl'))
        if not jsonl_files:
            continue

        for jsonl_file in jsonl_files:
            messages = parse_session(jsonl_file)
            if not messages:
                continue

            total_sessions += 1
            session_cards = extract_cards_from_session(messages, tag)
            all_cards.extend(session_cards)

    print(f'✓ {len(all_cards)} cards extracted from {total_sessions} sessions')

    build_apkg(all_cards, output)

    print(f'✨ Done! {len(all_cards)} cards → {output}')
    print(f'   Import into Anki: File → Import → select the .apkg file')


if __name__ == '__main__':
    main()
