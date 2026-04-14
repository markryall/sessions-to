#!/usr/bin/env python3
"""Convert Claude Code sessions into a Major Arcana tarot reading.

Each session is assigned a card based on its characteristics —
message count, tool usage, chaos level, and position in history.

Usage:
  python3 sessions_to_tarot.py                  # → tmp/sessions_tarot.html
  python3 sessions_to_tarot.py output.html
"""

import html as html_mod
import json
import sys
from pathlib import Path

CLAUDE_DIR     = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "sessions_tarot.html"

# (number, name, symbol, one-line reading)
ARCANA = [
    (0,  "The Fool",           "🌀", "A fresh beginning. The first step into the unknown."),
    (1,  "The Magician",       "⚡", "All tools were summoned. Power flowed through every command."),
    (2,  "The High Priestess", "🌙", "Deep listening. More questions than answers — and that was wisdom."),
    (3,  "The Empress",        "🌸", "Creation flourished. Something beautiful was brought into being."),
    (4,  "The Emperor",        "🏛️", "Structure imposed. Order carved methodically from chaos."),
    (5,  "The Hierophant",     "📜", "Knowledge passed down. Systems explained, patterns understood."),
    (6,  "The Lovers",         "💞", "A true collaboration. You and Claudia, in perfect rhythm."),
    (7,  "The Chariot",        "🏆", "Victory through persistence. The problem was slain."),
    (8,  "Strength",           "🦁", "An epic undertaking. Long and demanding — but it held."),
    (9,  "The Hermit",         "🔦", "A solitary investigation. Going deep into the dark, alone."),
    (10, "Wheel of Fortune",   "⚙️", "The midpoint. Everything in balance, the great wheel turning."),
    (11, "Justice",            "⚖️", "A precise reckoning. The code was weighed and found correct."),
    (12, "The Hanged Man",     "🔄", "A different angle was required. Suspended, then reborn."),
    (13, "Death",              "💀", "Something was deleted, refactored, or fundamentally changed."),
    (14, "Temperance",         "⚗️", "Careful iteration. Testing, adjusting, finding the middle path."),
    (15, "The Devil",          "😈", "Chaos crept in. Dependencies tangled, configs cursed."),
    (16, "The Tower",          "🌩️", "Everything broke at once. A necessary destruction."),
    (17, "The Star",           "⭐", "Clear skies. A calm session that just… worked."),
    (18, "The Moon",           "🌕", "Confusing. The path was unclear, the output ambiguous."),
    (19, "The Sun",            "☀️", "Brief and bright. A small win, cleanly executed."),
    (20, "Judgement",          "📯", "A review, a reckoning, a summing up of what came before."),
    (21, "The World",          "🌍", "Completion. The most whole and integrated session of all."),
]

ROMAN = ["0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
         "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX", "XXI"]

# ── Parsing ───────────────────────────────────────────────────────────────────

def build_global_index(base_dir):
    index_map = {}
    for project_dir in base_dir.iterdir():
        idx_path = project_dir / "sessions-index.json"
        if idx_path.exists():
            try:
                with open(idx_path) as f:
                    for entry in json.load(f).get("entries", []):
                        sid = entry.get("sessionId")
                        if sid:
                            index_map[sid] = entry
            except Exception:
                pass
    return index_map


def parse_session(jsonl_path):
    msg_count  = 0
    tool_count = 0
    first_text = ""
    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") not in ("user", "assistant"):
                    continue
                msg     = obj.get("message", {})
                role    = msg.get("role")
                content = msg.get("content", "")
                if isinstance(content, str):
                    if content.strip():
                        msg_count += 1
                        if not first_text and role == "user":
                            first_text = content.strip()
                elif isinstance(content, list):
                    has_text = False
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text" and b.get("text", "").strip():
                            has_text = True
                            if not first_text and role == "user":
                                first_text = b["text"].strip()
                        elif b.get("type") == "tool_use":
                            tool_count += 1
                    if has_text:
                        msg_count += 1
    except Exception:
        pass
    return msg_count, tool_count, first_text


def load_sessions():
    index_map = build_global_index(CLAUDE_DIR)
    sessions  = []
    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            sid = jsonl.stem
            msg_count, tool_count, first_text = parse_session(jsonl)
            if msg_count == 0:
                continue
            meta    = index_map.get(sid, {})
            title   = (meta.get("summary") or meta.get("firstPrompt") or first_text or "Untitled")
            if len(title) > 70:
                title = title[:70] + "…"
            sessions.append({
                "title":     title,
                "msgCount":  msg_count,
                "toolCount": tool_count,
                "created":   meta.get("created", ""),
            })
    sessions.sort(key=lambda s: s["created"])
    n = len(sessions)
    for i, s in enumerate(sessions):
        s["chaos"] = round(i / max(n - 1, 1), 4)
    return sessions


# ── Card assignment ───────────────────────────────────────────────────────────

def assign_arcana(session, index, total):
    msg   = session["msgCount"]
    tools = session["toolCount"]
    chaos = session["chaos"]
    ratio = tools / max(msg, 1)

    if index == 0:                          return 0   # The Fool
    if index == total - 1:                  return 21  # The World
    if chaos > 0.90:                        return 16  # The Tower
    if chaos > 0.75:                        return 15  # The Devil
    if chaos < 0.05 and msg > 5:           return 17  # The Star
    if ratio > 2.0:                         return 1   # The Magician
    if msg > 60:                            return 8   # Strength
    if msg <= 3:                            return 19  # The Sun
    if ratio < 0.1 and msg > 10:           return 2   # The High Priestess
    if tools > 25:                          return 13  # Death
    if 0.48 <= chaos <= 0.52:              return 10  # Wheel of Fortune
    if ratio > 1.2 and chaos < 0.4:        return 7   # The Chariot
    if tools == 0:                          return 9   # The Hermit
    if chaos < 0.15:                        return 6   # The Lovers

    remaining = [3, 4, 5, 11, 12, 14, 18, 20]
    band = int(chaos * len(remaining))
    return remaining[min(band, len(remaining) - 1)]


# ── HTML ──────────────────────────────────────────────────────────────────────

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #0a0010;
  background-image: radial-gradient(ellipse at 50% 0%, #1a0030 0%, #0a0010 70%);
  min-height: 100vh;
  padding: 48px 24px;
  font-family: Georgia, 'Times New Roman', serif;
  color: #d4b896;
}
h1 {
  text-align: center;
  font-size: 28px;
  letter-spacing: 6px;
  color: #c9a84c;
  margin-bottom: 8px;
  text-transform: uppercase;
}
.subtitle {
  text-align: center;
  color: #7a5c8a;
  font-style: italic;
  margin-bottom: 48px;
  font-size: 15px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 24px;
  max-width: 1200px;
  margin: 0 auto;
}
.card {
  background: linear-gradient(160deg, #12001e 0%, #1e0832 100%);
  border: 1px solid #4a2c6a;
  border-radius: 8px;
  padding: 24px 18px 18px;
  cursor: default;
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
  position: relative;
  overflow: hidden;
}
.card::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 8px;
  border: 1px solid transparent;
  background: linear-gradient(135deg, #c9a84c22, transparent 60%) border-box;
  -webkit-mask: linear-gradient(#fff 0 0) padding-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: destination-out;
  mask-composite: exclude;
}
.card:hover {
  transform: translateY(-5px);
  border-color: #c9a84c;
  box-shadow: 0 8px 32px rgba(201, 168, 76, 0.2);
}
.roman {
  font-size: 11px;
  letter-spacing: 3px;
  color: #7a5c8a;
  text-align: center;
  margin-bottom: 6px;
}
.symbol {
  font-size: 36px;
  text-align: center;
  margin: 8px 0;
  line-height: 1;
}
.card-name {
  text-align: center;
  font-size: 15px;
  font-weight: bold;
  color: #c9a84c;
  letter-spacing: 1px;
  margin-bottom: 14px;
}
.divider {
  text-align: center;
  color: #4a2c6a;
  margin: 8px 0;
  font-size: 12px;
  letter-spacing: 2px;
}
.session-title {
  font-size: 12px;
  color: #b8a080;
  text-align: center;
  font-style: italic;
  margin-bottom: 10px;
  line-height: 1.4;
  min-height: 2.8em;
}
.stats {
  font-family: monospace;
  font-size: 10px;
  color: #5a4060;
  text-align: center;
  margin-bottom: 10px;
}
.reading {
  font-size: 11px;
  color: #9a7090;
  text-align: center;
  font-style: italic;
  line-height: 1.5;
  border-top: 1px solid #2a1040;
  padding-top: 10px;
}
"""


def render_card(session, arcanum):
    num, name, symbol, reading = arcanum
    title = html_mod.escape(session["title"])
    stats = f"{session['msgCount']} msgs · {session['toolCount']} tools · chaos {session['chaos']:.3f}"
    return (
        f'<div class="card">'
        f'<div class="roman">{ROMAN[num]}</div>'
        f'<div class="symbol">{symbol}</div>'
        f'<div class="card-name">{html_mod.escape(name)}</div>'
        f'<div class="divider">✦ · · · ✦</div>'
        f'<div class="session-title">{title}</div>'
        f'<div class="stats">{stats}</div>'
        f'<div class="reading">{html_mod.escape(reading)}</div>'
        f'</div>'
    )


def generate_html(sessions):
    n     = len(sessions)
    cards = []
    for i, s in enumerate(sessions):
        arcanum_idx = assign_arcana(s, i, n)
        cards.append(render_card(s, ARCANA[arcanum_idx]))

    grid = "\n".join(cards)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sessions — Tarot</title>
<style>{CSS}</style>
</head>
<body>
<h1>✦ The Reading ✦</h1>
<div class="subtitle">{n} sessions read &nbsp;·&nbsp; the cards do not lie</div>
<div class="grid">
{grid}
</div>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    print("Loading sessions…")
    sessions = load_sessions()
    if not sessions:
        print("No sessions found.")
        return
    print(f"✓ {len(sessions)} sessions")
    output.write_text(generate_html(sessions), encoding="utf-8")
    print(f"✓ Written to {output}")


if __name__ == "__main__":
    main()
