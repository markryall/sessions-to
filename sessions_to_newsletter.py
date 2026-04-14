#!/usr/bin/env python3
"""Convert Claude Code sessions into a weekly digest newsletter.

Sessions are grouped by ISO week and rendered as a clean HTML newsletter.

Usage:
  python3 sessions_to_newsletter.py                  # → tmp/sessions_newsletter.html
  python3 sessions_to_newsletter.py output.html
"""

import html as html_mod
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR     = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "sessions_newsletter.html"

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
            if len(title) > 90:
                title = title[:90] + "…"
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


# ── Grouping ──────────────────────────────────────────────────────────────────

def week_key(created):
    """Return (iso_year, iso_week) or None for undated."""
    if not created:
        return None
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        iso = dt.isocalendar()
        return (iso[0], iso[1])
    except Exception:
        return None


def week_label(year, week):
    try:
        # Monday of that ISO week
        monday = datetime.fromisocalendar(year, week, 1)
        return monday.strftime("Week of %B %-d, %Y")
    except Exception:
        return f"Week {week}, {year}"


# ── HTML rendering ────────────────────────────────────────────────────────────

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #f0ede8;
  font-family: Georgia, 'Times New Roman', serif;
  color: #222;
  padding: 40px 16px 80px;
}
.wrapper {
  max-width: 680px;
  margin: 0 auto;
  background: #fff;
  box-shadow: 0 2px 24px rgba(0,0,0,0.08);
}
.masthead {
  background: #1a1a2e;
  color: #fff;
  padding: 40px 48px 32px;
  text-align: center;
}
.masthead h1 {
  font-size: 32px;
  letter-spacing: 6px;
  font-weight: normal;
  text-transform: uppercase;
  color: #e8d5b0;
  margin-bottom: 8px;
}
.masthead .tagline {
  font-style: italic;
  color: #8888aa;
  font-size: 14px;
}
.stats-strip {
  display: flex;
  background: #f5f2ec;
  border-bottom: 1px solid #e0dbd0;
}
.stat-box {
  flex: 1;
  text-align: center;
  padding: 18px 8px;
  border-right: 1px solid #e0dbd0;
}
.stat-box:last-child { border-right: none; }
.stat-num {
  display: block;
  font-size: 22px;
  font-weight: bold;
  color: #1a1a2e;
  font-family: monospace;
}
.stat-lbl {
  display: block;
  font-size: 10px;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-top: 2px;
}
.content { padding: 0 48px 32px; }
.week {
  margin-top: 40px;
}
.week-hdr {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: #888;
  border-left: 3px solid #1a1a2e;
  padding-left: 12px;
  margin-bottom: 16px;
  line-height: 1.6;
}
.week-hdr strong { color: #1a1a2e; font-size: 13px; }
.session {
  padding: 12px 0;
  border-bottom: 1px solid #f0ede8;
}
.session:last-child { border-bottom: none; }
.session-title {
  font-size: 14px;
  font-weight: bold;
  color: #1a1a2e;
  margin-bottom: 6px;
  line-height: 1.4;
}
.session-meta {
  font-family: monospace;
  font-size: 11px;
  color: #888;
  margin-bottom: 6px;
}
.chaos-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chaos-label { font-size: 10px; color: #bbb; font-family: monospace; }
.chaos-bar {
  height: 6px;
  border-radius: 3px;
  background: linear-gradient(to right, #3355ff, #aa33cc, #ff3344);
}
.undated-hdr {
  margin-top: 40px;
  font-size: 11px;
  color: #aaa;
  text-transform: uppercase;
  letter-spacing: 2px;
  border-left: 3px solid #ddd;
  padding-left: 12px;
  margin-bottom: 16px;
}
.footer {
  background: #f5f2ec;
  border-top: 1px solid #e0dbd0;
  text-align: center;
  padding: 20px;
  font-size: 11px;
  color: #aaa;
  font-family: monospace;
}
"""


def render_session(s):
    title      = html_mod.escape(s["title"])
    meta       = f"{s['msgCount']} messages &nbsp;·&nbsp; {s['toolCount']} tool calls &nbsp;·&nbsp; chaos {s['chaos']:.3f}"
    bar_width  = int(s["chaos"] * 120)
    return (
        f'<div class="session">'
        f'<div class="session-title">{title}</div>'
        f'<div class="session-meta">{meta}</div>'
        f'<div class="chaos-wrap">'
        f'<span class="chaos-label">calm</span>'
        f'<div class="chaos-bar" style="width:{bar_width}px"></div>'
        f'<span class="chaos-label">chaotic</span>'
        f'</div>'
        f'</div>'
    )


def generate_html(sessions):
    n           = len(sessions)
    total_msgs  = sum(s["msgCount"]  for s in sessions)
    total_tools = sum(s["toolCount"] for s in sessions)

    # Group by week
    weeks    = defaultdict(list)
    undated  = []
    for s in sessions:
        key = week_key(s["created"])
        if key:
            weeks[key].append(s)
        else:
            undated.append(s)

    # Sort weeks newest first
    sorted_weeks = sorted(weeks.keys(), reverse=True)

    # Date range
    dated = [s for s in sessions if s["created"]]
    if dated:
        first = dated[0]["created"][:10]
        last  = dated[-1]["created"][:10]
        date_range = f"{first} – {last}"
    else:
        date_range = "unknown period"

    # Build week sections
    sections = ""
    for key in sorted_weeks:
        year, week = key
        label   = html_mod.escape(week_label(year, week))
        count   = len(weeks[key])
        session_html = "".join(render_session(s) for s in weeks[key])
        sections += (
            f'<div class="week">'
            f'<div class="week-hdr"><strong>{label}</strong> &nbsp;·&nbsp; {count} session{"s" if count != 1 else ""}</div>'
            f'{session_html}'
            f'</div>'
        )

    if undated:
        session_html = "".join(render_session(s) for s in undated)
        sections += (
            f'<div class="undated-hdr">Undated · {len(undated)} sessions</div>'
            f'{session_html}'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>The Claudia Dispatch</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrapper">
  <div class="masthead">
    <h1>The Claudia Dispatch</h1>
    <div class="tagline">Your coding conversation digest &nbsp;·&nbsp; {date_range}</div>
  </div>
  <div class="stats-strip">
    <div class="stat-box">
      <span class="stat-num">{n}</span>
      <span class="stat-lbl">Sessions</span>
    </div>
    <div class="stat-box">
      <span class="stat-num">{total_msgs:,}</span>
      <span class="stat-lbl">Messages</span>
    </div>
    <div class="stat-box">
      <span class="stat-num">{total_tools:,}</span>
      <span class="stat-lbl">Tool Calls</span>
    </div>
    <div class="stat-box">
      <span class="stat-num">{len(sorted_weeks)}</span>
      <span class="stat-lbl">Weeks</span>
    </div>
  </div>
  <div class="content">
    {sections}
  </div>
  <div class="footer">
    Generated from ~/.claude/projects/ &nbsp;·&nbsp; {n} sessions across {len(sorted_weeks)} weeks
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
    output.write_text(generate_html(sessions), encoding="utf-8")
    print(f"✓ Written to {output}")


if __name__ == "__main__":
    main()
