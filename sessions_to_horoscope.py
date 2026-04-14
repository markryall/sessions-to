#!/usr/bin/env python3
"""Convert Claude Code sessions into an astrological horoscope reading.

Analyses patterns across all sessions and presents your coding behaviour
as a mystical cosmic forecast. Serious-sounding, absurd, actually accurate.

Usage:
  python3 sessions_to_horoscope.py                  # → tmp/sessions_horoscope.html
  python3 sessions_to_horoscope.py output.html
"""

import html as html_mod
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

CLAUDE_DIR     = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "sessions_horoscope.html"

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
    tools      = {}
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
                            name = b.get("name", "unknown")
                            tools[name] = tools.get(name, 0) + 1
                            tool_count += 1
                    if has_text:
                        msg_count += 1
    except Exception:
        pass
    return msg_count, tool_count, tools, first_text


def load_sessions():
    index_map = build_global_index(CLAUDE_DIR)
    sessions  = []
    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            sid = jsonl.stem
            msg_count, tool_count, tools, first_text = parse_session(jsonl)
            if msg_count == 0:
                continue
            meta    = index_map.get(sid, {})
            title   = (meta.get("summary") or meta.get("firstPrompt") or first_text or "Untitled")
            sessions.append({
                "title":     title,
                "msgCount":  msg_count,
                "toolCount": tool_count,
                "tools":     tools,
                "created":   meta.get("created", ""),
            })
    sessions.sort(key=lambda s: s["created"])
    n = len(sessions)
    for i, s in enumerate(sessions):
        s["chaos"] = round(i / max(n - 1, 1), 4)
    return sessions


# ── Astrology ─────────────────────────────────────────────────────────────────

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

SUN_SIGNS = {
    0: ("Monday Coder",   "Disciplined, burdened, caffeinated. You face each week with grim determination and a terminal window."),
    1: ("Tuesday Coder",  "The overlooked middle child of the week. You find beauty in the mundane refactor."),
    2: ("Wednesday Coder","Hump day hero. You live for the session that finally makes everything click."),
    3: ("Thursday Coder", "So close to Friday you can taste it. Your commits have a restless, urgent energy."),
    4: ("Friday Coder",   "Chaotic good. You ship things on Friday. The stars admire your courage and poor judgment."),
    5: ("Saturday Coder", "You code on weekends. This is either very dedicated or a cry for help. Possibly both."),
    6: ("Sunday Coder",   "Anxious, introspective, already dreading Monday. Your best work happens in denial."),
}

PLANETS = {
    "Bash":     ("Mars",    "god of action and destruction", "You act decisively, sometimes recklessly. The shell is your sword."),
    "Read":     ("Mercury", "messenger of knowledge",        "You seek to understand before acting. A rare and admirable trait."),
    "WebFetch": ("Neptune", "lord of the vast digital sea",  "You swim in external knowledge, always searching the horizon."),
    "Edit":     ("Venus",   "goddess of transformation",     "You shape and refine. Beauty emerges from your careful changes."),
    "Write":    ("Saturn",  "architect of structure",        "You build from nothing. Patient, methodical, occasionally verbose."),
    "Grep":     ("Uranus",  "revealer of hidden truths",     "You seek what is buried. The pattern reveals itself to you."),
    "Agent":    ("Jupiter", "ruler of delegation and empire","You command others. Power flows through distributed systems."),
}

COMPATIBLE = [
    "Rust Developer (Ascendant in Safety)",
    "TypeScript Evangelist (Moon in Strictness)",
    "Vim User (Rising in Patience)",
    "Nix Devotee (Saturn in Reproducibility)",
    "Test-Driven Developer (Jupiter in Certainty)",
    "Functional Programmer (Mercury in Purity)",
]

STRENGTHS_POOL = [
    ("tool_heavy",   "You wield tools with the precision of a cosmic engineer. The machine bends to your will."),
    ("long_session", "Your capacity for sustained focus is written in the stars. You do not give up easily."),
    ("low_chaos",    "Your early sessions radiate clarity. You approached problems with crystalline intention."),
    ("many_sessions","Consistency is your superpower. You show up, session after session, against all odds."),
    ("high_msgs",    "You communicate richly. No question goes unasked, no answer unexplored."),
]

GROWTH_POOL = [
    ("short_sessions", "The stars urge you to linger. Great work cannot always be rushed through in three messages."),
    ("high_chaos",     "Chaos has been your companion of late. Mercury urges you to slow down and read the error message."),
    ("few_tools",      "The cosmos whispers: more tools. You have been thinking when you should have been doing."),
    ("low_msgs",       "Your sessions are brief and sparse. Open your heart — and your terminal — a little wider."),
]


def build_reading(sessions):
    n           = len(sessions)
    total_msgs  = sum(s["msgCount"]  for s in sessions)
    total_tools = sum(s["toolCount"] for s in sessions)
    avg_msgs    = total_msgs  / max(n, 1)
    avg_tools   = total_tools / max(n, 1)
    max_msgs    = max(s["msgCount"] for s in sessions)
    avg_chaos   = sum(s["chaos"] for s in sessions) / max(n, 1)
    chaos_trend = sessions[-1]["chaos"] - sessions[0]["chaos"] if n > 1 else 0

    # Sun sign from most common day of week
    day_counts = Counter()
    for s in sessions:
        if s["created"]:
            try:
                dt = datetime.fromisoformat(s["created"].replace("Z", "+00:00"))
                day_counts[dt.weekday()] += 1
            except Exception:
                pass
    top_day    = day_counts.most_common(1)[0][0] if day_counts else 0
    sign_name, sign_desc = SUN_SIGNS[top_day]

    # Ruling planet from most-used tool
    all_tools = Counter()
    for s in sessions:
        all_tools.update(s.get("tools", {}))
    top_tool = all_tools.most_common(1)[0][0] if all_tools else "Bash"
    planet_name, planet_title, planet_desc = PLANETS.get(
        top_tool, ("Pluto", "lord of the unknown", "Your dominant tool defies classification. You are a mystery.")
    )

    # The reading paragraph
    tool_ratio = avg_tools / max(avg_msgs, 1)
    if tool_ratio > 1.5:
        style = "You rarely speak without acting. Every message is an instruction, every response a command executed."
    elif tool_ratio < 0.3:
        style = "You favour dialogue over action. Yours is a contemplative practice — more philosophy than engineering."
    else:
        style = "You balance thought and action in equal measure, a rare alignment in this chaotic universe."

    if avg_chaos < 0.3:
        chaos_desc = "Your sessions have been marked by calm and clarity. The cosmos smiles upon your early work."
    elif avg_chaos > 0.6:
        chaos_desc = "Chaos has been your faithful companion. Whether by design or misfortune, you dwell in disruption."
    else:
        chaos_desc = "You occupy the turbulent middle ground — neither serene nor unhinged. A relatable energy."

    reading = f"{style} {chaos_desc} Across {n} sessions and {total_msgs:,} messages, a pattern emerges: you are someone who returns. Again and again, to the terminal, to the problem, to Claudia."

    # Strengths
    strengths = []
    if avg_tools > 1.0:
        strengths.append(STRENGTHS_POOL[0][1])
    if max_msgs > 40:
        strengths.append(STRENGTHS_POOL[1][1])
    if sessions[0]["chaos"] < 0.1:
        strengths.append(STRENGTHS_POOL[2][1])
    if n > 20:
        strengths.append(STRENGTHS_POOL[3][1])
    if avg_msgs > 15:
        strengths.append(STRENGTHS_POOL[4][1])
    strengths = strengths[:3] or [STRENGTHS_POOL[3][1], STRENGTHS_POOL[4][1], STRENGTHS_POOL[0][1]]

    # Areas of growth
    growth = []
    if avg_msgs < 8:
        growth.append(GROWTH_POOL[0][1])
    if avg_chaos > 0.5:
        growth.append(GROWTH_POOL[1][1])
    if avg_tools < 0.5:
        growth.append(GROWTH_POOL[2][1])
    if avg_msgs < 5:
        growth.append(GROWTH_POOL[3][1])
    growth = growth[:2] or [GROWTH_POOL[1][1], GROWTH_POOL[2][1]]

    # Forecast
    if chaos_trend > 0.3:
        forecast = "Turbulent times approach. The chaos index is rising and Mercury appears to be in retrograde deployment. Back up your work. Trust no green light in CI."
    elif chaos_trend < -0.2:
        forecast = "The stars herald a period of consolidation. Your chaos is receding like a tide. Clarity awaits — though the codebase may still surprise you."
    else:
        forecast = "Stability, or the illusion of it. The cosmos offers no dramatic upheavals in the immediate future. Enjoy this while it lasts."

    # Compatibility (seeded by session count for determinism)
    compat = COMPATIBLE[n % len(COMPATIBLE)]

    # Lucky numbers
    lucky = [n, max_msgs, total_tools % 100, len(set(s["created"][:7] for s in sessions if s["created"]))]

    return {
        "sign_name":   sign_name,
        "sign_desc":   sign_desc,
        "day":         DAYS[top_day],
        "planet":      planet_name,
        "planet_title":planet_title,
        "planet_desc": planet_desc,
        "reading":     reading,
        "strengths":   strengths,
        "growth":      growth,
        "forecast":    forecast,
        "compat":      compat,
        "lucky":       lucky,
        "n":           n,
        "total_msgs":  total_msgs,
        "total_tools": total_tools,
    }


# ── HTML ──────────────────────────────────────────────────────────────────────

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #080414;
  background-image:
    radial-gradient(ellipse at 20% 20%, #1a0828 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, #0a1428 0%, transparent 50%);
  min-height: 100vh;
  font-family: Georgia, 'Times New Roman', serif;
  color: #c8b89a;
  padding: 48px 16px 80px;
}
.wrapper { max-width: 720px; margin: 0 auto; }
.masthead {
  text-align: center;
  margin-bottom: 48px;
}
.masthead h1 {
  font-size: 13px;
  letter-spacing: 6px;
  text-transform: uppercase;
  color: #6a4c8a;
  margin-bottom: 16px;
}
.masthead h2 {
  font-size: 40px;
  color: #c9a84c;
  font-weight: normal;
  margin-bottom: 8px;
}
.masthead .stars {
  color: #4a2c6a;
  font-size: 18px;
  letter-spacing: 4px;
  margin-bottom: 16px;
}
.masthead .subtitle {
  font-style: italic;
  color: #7a6050;
  font-size: 14px;
}
.divider {
  text-align: center;
  color: #3a1c5a;
  margin: 32px 0;
  font-size: 18px;
  letter-spacing: 4px;
}
.section { margin-bottom: 40px; }
.section-title {
  font-size: 10px;
  letter-spacing: 4px;
  text-transform: uppercase;
  color: #6a4c8a;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid #2a1040;
}
.section-body {
  font-size: 16px;
  line-height: 1.8;
  color: #c8b89a;
}
.highlight { color: #c9a84c; font-style: italic; }
.planet-name { color: #c9a84c; font-size: 20px; font-weight: bold; }
.planet-title { color: #7a5c8a; font-style: italic; font-size: 14px; }
ul { list-style: none; padding: 0; }
ul li { padding: 8px 0 8px 24px; position: relative; border-bottom: 1px solid #1a0830; font-size: 15px; line-height: 1.6; }
ul li::before { content: "✦"; position: absolute; left: 0; color: #c9a84c; }
.lucky { display: flex; gap: 16px; flex-wrap: wrap; }
.lucky-num {
  background: #1a0830;
  border: 1px solid #3a1c5a;
  border-radius: 4px;
  padding: 12px 20px;
  text-align: center;
  min-width: 80px;
}
.lucky-num .num { font-size: 28px; color: #c9a84c; font-family: monospace; display: block; }
.lucky-num .lbl { font-size: 10px; color: #5a4060; letter-spacing: 1px; display: block; margin-top: 4px; }
.forecast-box {
  background: #0e0420;
  border: 1px solid #3a1c5a;
  border-left: 3px solid #c9a84c;
  padding: 20px 24px;
  font-style: italic;
  line-height: 1.8;
  font-size: 15px;
}
"""

LUCKY_LABELS = ["total sessions", "longest session", "tool calls mod 100", "active months"]


def generate_html(r):
    strengths_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in r["strengths"])
    growth_html    = "".join(f"<li>{html_mod.escape(s)}</li>" for s in r["growth"])
    lucky_html     = "".join(
        f'<div class="lucky-num"><span class="num">{v}</span><span class="lbl">{html_mod.escape(LUCKY_LABELS[i])}</span></div>'
        for i, v in enumerate(r["lucky"])
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Your Coding Horoscope</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrapper">

  <div class="masthead">
    <div class="h1">✦ CELESTIAL CODE READING ✦</div>
    <h2>Your Coding Horoscope</h2>
    <div class="stars">✦ · · · · · ✦ · · · · · ✦</div>
    <div class="subtitle">{r['n']} sessions analysed · the cosmos has spoken</div>
  </div>

  <div class="section">
    <div class="section-title">✦ &nbsp; Sun Sign &nbsp; ✦</div>
    <div class="section-body">
      You are a <span class="highlight">{html_mod.escape(r['sign_name'])}</span>.<br>
      {html_mod.escape(r['sign_desc'])}
    </div>
  </div>

  <div class="divider">✦ ─────────── ✦ ─────────── ✦</div>

  <div class="section">
    <div class="section-title">✦ &nbsp; Ruling Planet &nbsp; ✦</div>
    <div class="section-body">
      <div class="planet-name">{html_mod.escape(r['planet'])}</div>
      <div class="planet-title">{html_mod.escape(r['planet_title'])}</div>
      <br>
      {html_mod.escape(r['planet_desc'])}
      Your most-summoned tool rules your practice and defines your cosmic signature.
    </div>
  </div>

  <div class="divider">✦ ─────────── ✦ ─────────── ✦</div>

  <div class="section">
    <div class="section-title">✦ &nbsp; This Week's Reading &nbsp; ✦</div>
    <div class="section-body">{html_mod.escape(r['reading'])}</div>
  </div>

  <div class="divider">✦ ─────────── ✦ ─────────── ✦</div>

  <div class="section">
    <div class="section-title">✦ &nbsp; Cosmic Strengths &nbsp; ✦</div>
    <ul>{strengths_html}</ul>
  </div>

  <div class="section">
    <div class="section-title">✦ &nbsp; Areas of Growth &nbsp; ✦</div>
    <ul>{growth_html}</ul>
  </div>

  <div class="divider">✦ ─────────── ✦ ─────────── ✦</div>

  <div class="section">
    <div class="section-title">✦ &nbsp; Lucky Numbers &nbsp; ✦</div>
    <div class="lucky">{lucky_html}</div>
  </div>

  <div class="section">
    <div class="section-title">✦ &nbsp; Compatibility &nbsp; ✦</div>
    <div class="section-body">
      The stars align most favourably with a <span class="highlight">{html_mod.escape(r['compat'])}</span>.<br>
      Seek them in open-source repositories and co-working spaces with good coffee.
    </div>
  </div>

  <div class="divider">✦ ─────────── ✦ ─────────── ✦</div>

  <div class="section">
    <div class="section-title">✦ &nbsp; Forecast &nbsp; ✦</div>
    <div class="forecast-box">{html_mod.escape(r['forecast'])}</div>
  </div>

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
    reading = build_reading(sessions)
    output.write_text(generate_html(reading), encoding="utf-8")
    print(f"✓ Written to {output}")
    print(f"  Your ruling planet: {reading['planet']}")
    print(f"  Your sun sign: {reading['sign_name']}")


if __name__ == "__main__":
    main()
