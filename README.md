# sessions-to

Convert your [Claude Code](https://claude.ai/code) conversation history into other things.

Each script reads sessions directly from `~/.claude/projects/` — no export needed.

---

## Converters

| Script | Output | What it does |
|--------|--------|-------------|
| `sessions_to_3d.py` | HTML | 3D galaxy — sessions as glowing spheres, drag to orbit |
| `sessions_to_html.py` | HTML directory | Browsable static site of all sessions |
| `sessions_to_epub.py` | `.epub` | E-reader format for reminiscing on the go |
| `sessions_to_typst.py` | `.typ` / PDF | Typeset document via [Typst](https://typst.app) |
| `sessions_to_org.py` | `.org` files | Org mode files for Emacs/Spacemacs |
| `sessions_to_sqlite.py` | `.db` | SQLite database — query your conversations |
| `sessions_to_stats.py` | HTML dashboard | Sparkly stats: message counts, timelines, top sessions |
| `sessions_to_calendar.py` | HTML calendar | Sessions laid out as a calendar heatmap |
| `sessions_to_ical.py` | `.ics` | iCalendar — import sessions as calendar events |
| `sessions_to_anki.py` | `.apkg` | Anki flashcard deck — study your own conversations |
| `sessions_to_midi.py` | `.mid` | Your chat history as a MIDI file |
| `sessions_to_sc.py` | `.scd` | SuperCollider score — generative music from your sessions |

---

## Usage

All scripts default to writing output into a `tmp/` subdirectory next to the script. Pass a path as the first argument to override.

```bash
python3 sessions_to_stats.py
python3 sessions_to_epub.py ~/Desktop/my-sessions.epub
python3 sessions_to_sqlite.py ~/sessions.db
```

### SuperCollider (`sessions_to_sc.py`)

```bash
# Standard mode — FM synths, minor-triad pads
python3 sessions_to_sc.py

# Microtonal mode — 11-limit just intonation, alien math rock
python3 sessions_to_sc.py --microtonal
```

Then open the `.scd` in SuperCollider IDE, `Cmd+A`, `Cmd+Return`.

**Microtonal mode layers:**
- **You** → golden-ratio FM + AM, right-panned
- **Claudia** → ring mod + FM + micro-pitch-drift, unravels as chaos→1
- **Tool calls** → Ringz resonator banks tuned to golden-ratio partials
- **Bass** → slow sustained FM bass walking root harmonics
- **Bells** → sparse high pings with 4–7s decay, wide stereo
- **Cowbell** → CR-78-style, retuned per session, skips beat 4-of-7
- **Counter-melody** → second voice reading messages out of order
- **Drone** → 11-limit harmonic drone blooms under the whole piece
- **Chaos** → ramps 0→1 across your full history; late sessions get weird

Each session has its own tonal centre drawn from the JI scale, its own tempo, and its own FM personality derived from message count. No two sessions sound the same.

### Anki (`sessions_to_anki.py`)

Requires the `genanki` package:

```bash
pip install genanki
```

### Typst (`sessions_to_typst.py`)

Requires [Typst](https://typst.app):

```bash
brew install typst
```

---

## Requirements

- Python 3.10+
- Claude Code with sessions in `~/.claude/projects/`
- Script-specific deps noted above

---

## How sessions are read

Claude Code stores sessions as JSONL files in `~/.claude/projects/<project-hash>/*.jsonl`. Each line is a message object with role, content, and optional tool use blocks. All scripts parse this format directly — no API calls, no exports, fully local.
