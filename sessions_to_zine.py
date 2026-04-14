#!/usr/bin/env python3
"""Convert Claude Code sessions into a lo-fi digital zine.

Looks like it was photocopied and stapled together. Intentionally rough.
Pages: cover, contents, stats spread, session pages, back cover.

Usage:
  python3 sessions_to_zine.py                  # → tmp/sessions_zine.html
  python3 sessions_to_zine.py output.html
"""

import html as html_mod
import json
import sys
from pathlib import Path

CLAUDE_DIR     = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "sessions_zine.html"

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
            if len(title) > 80:
                title = title[:80] + "…"
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


# ── Stamp helper ──────────────────────────────────────────────────────────────

def stamp(text, color="#cc0000", rotate="-8deg"):
    return (
        f'<div class="stamp" style="color:{color};transform:rotate({rotate})">'
        f'{html_mod.escape(text)}</div>'
    )


def chaos_stamp(chaos):
    if chaos > 0.8:
        return stamp("URGENT", "#cc0000", "-6deg")
    if chaos > 0.5:
        return stamp("ACTIVE", "#cc6600", "5deg")
    if chaos < 0.1:
        return stamp("CLASSIFIED", "#003399", "-4deg")
    return stamp("ON FILE", "#336600", "7deg")


# ── Page builders ─────────────────────────────────────────────────────────────

def page_cover(sessions):
    n = len(sessions)
    dated = [s for s in sessions if s["created"]]
    year  = dated[0]["created"][:4] if dated else "????"
    return f"""
<div class="page page-cover">
  <div class="cover-border">
    <div class="cover-issue">ISSUE #{n}</div>
    <div class="cover-title">CONVERSATIONS<br>WITH A<br>MACHINE</div>
    <div class="cover-sub">a zine about coding with AI</div>
    <div class="cover-meta">{year} &nbsp;·&nbsp; FREE &nbsp;·&nbsp; TAKE ONE</div>
    <div class="cover-tape tape-h"></div>
    <div class="cover-tape tape-v"></div>
  </div>
</div>"""


def page_contents(sessions):
    items = ""
    for i, s in enumerate(sessions, 1):
        items += (
            f'<div class="toc-item">'
            f'<span class="toc-num">{i:03d}</span>'
            f'<span class="toc-dots">{"." * max(1, 50 - len(s["title"][:40]))}</span>'
            f'<span class="toc-title">{html_mod.escape(s["title"][:40])}</span>'
            f'</div>'
        )
    return f"""
<div class="page">
  <div class="page-label">CONTENTS</div>
  <div class="toc">{items}</div>
</div>"""


def page_stats(sessions):
    n           = len(sessions)
    total_msgs  = sum(s["msgCount"]  for s in sessions)
    total_tools = sum(s["toolCount"] for s in sessions)
    avg_msgs    = round(total_msgs / max(n, 1))
    max_msgs    = max(s["msgCount"] for s in sessions)
    most_chaotic = max(sessions, key=lambda s: s["chaos"])

    return f"""
<div class="page page-stats">
  <div class="page-label">THE NUMBERS</div>
  <div class="stats-grid">
    <div class="big-stat" style="transform:rotate(-2deg)">
      <div class="big-num">{n}</div>
      <div class="big-lbl">SESSIONS</div>
    </div>
    <div class="big-stat" style="transform:rotate(1.5deg)">
      <div class="big-num">{total_msgs:,}</div>
      <div class="big-lbl">MESSAGES</div>
    </div>
    <div class="big-stat" style="transform:rotate(-1deg)">
      <div class="big-num">{total_tools:,}</div>
      <div class="big-lbl">TOOL CALLS</div>
    </div>
    <div class="big-stat" style="transform:rotate(2deg)">
      <div class="big-num">{avg_msgs}</div>
      <div class="big-lbl">AVG MSGS/SESSION</div>
    </div>
    <div class="big-stat" style="transform:rotate(-1.5deg)">
      <div class="big-num">{max_msgs}</div>
      <div class="big-lbl">LONGEST SESSION</div>
    </div>
  </div>
  <div class="chaos-headline">
    MOST CHAOTIC SESSION:<br>
    <em>{html_mod.escape(most_chaotic['title'][:60])}</em>
  </div>
</div>"""


def page_sessions(sessions):
    pages = ""
    # Group sessions 6 per page
    for i in range(0, len(sessions), 6):
        chunk = sessions[i:i+6]
        items = ""
        for j, s in enumerate(chunk):
            num    = i + j + 1
            rotate = ["-1deg", "0.5deg", "-0.5deg", "1deg", "-1.5deg", "0.5deg"][j % 6]
            items += f"""
<div class="session-card" style="transform:rotate({rotate})">
  {chaos_stamp(s['chaos'])}
  <div class="s-num">#{num:03d}</div>
  <div class="s-title">{html_mod.escape(s['title'])}</div>
  <div class="s-meta">{s['msgCount']} msgs &nbsp;/&nbsp; {s['toolCount']} tools</div>
  <div class="s-date">{s['created'][:10] if s['created'] else '????-??-??'}</div>
</div>"""
        pages += f'<div class="page"><div class="page-label">SESSIONS</div><div class="session-grid">{items}</div></div>'
    return pages


def page_back():
    return """
<div class="page page-back">
  <div class="back-ascii">
   _____
  /     \\
 | () () |
  \\  ^  /
   |||||
   |||||
  </div>
  <div class="back-title">CLAUDIA</div>
  <div class="back-sub">your friendly neighbourhood AI</div>
  <div class="back-rule">────────────────────────</div>
  <div class="back-text">
    PRINTED IN THE CLOUD<br>
    DISTRIBUTED EVERYWHERE<br>
    FREE AS IN FREEDOM<br>
    <br>
    no AIs were harmed<br>
    in the making of this zine<br>
    <br>
    (several bugs were)
  </div>
  <div class="back-rule">────────────────────────</div>
  <div class="back-small">~/.claude/projects/ • issue #{ISSUE}</div>
</div>"""


# ── HTML ──────────────────────────────────────────────────────────────────────

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #2a2a2a;
  padding: 40px 20px;
  font-family: 'Courier New', Courier, monospace;
}
.page {
  background: #f5f0e8;
  max-width: 680px;
  margin: 0 auto 48px;
  padding: 48px;
  position: relative;
  box-shadow: 3px 3px 0 #111, 6px 6px 0 #333;
  border: 2px solid #111;
}
/* Photocopied texture */
.page::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
  pointer-events: none;
  opacity: 0.4;
}
.page-label {
  font-size: 10px;
  letter-spacing: 4px;
  color: #888;
  text-transform: uppercase;
  margin-bottom: 24px;
  border-bottom: 1px solid #ccc;
  padding-bottom: 8px;
}

/* Cover */
.page-cover { text-align: center; background: #f0ebe0; min-height: 600px; display: flex; align-items: center; justify-content: center; }
.cover-border {
  border: 4px solid #111;
  padding: 40px;
  position: relative;
  width: 100%;
}
.cover-border::before {
  content: '';
  position: absolute;
  inset: 6px;
  border: 1px solid #111;
  pointer-events: none;
}
.cover-issue { font-size: 11px; letter-spacing: 3px; color: #666; margin-bottom: 20px; }
.cover-title { font-size: 52px; font-weight: 900; line-height: 1.0; letter-spacing: -1px; margin-bottom: 20px; color: #111; }
.cover-sub { font-size: 13px; color: #555; margin-bottom: 16px; font-style: italic; }
.cover-meta { font-size: 11px; letter-spacing: 2px; color: #888; }
.tape-h {
  position: absolute; top: -12px; left: 50%; transform: translateX(-50%);
  width: 80px; height: 22px;
  background: rgba(255,255,180,0.7);
  border: 1px solid rgba(200,200,100,0.5);
}
.tape-v {
  position: absolute; top: 50%; right: -14px; transform: translateY(-50%) rotate(90deg);
  width: 80px; height: 22px;
  background: rgba(255,255,180,0.7);
  border: 1px solid rgba(200,200,100,0.5);
}

/* TOC */
.toc { font-size: 12px; line-height: 1.8; }
.toc-item { display: flex; align-items: baseline; gap: 4px; margin-bottom: 2px; white-space: nowrap; overflow: hidden; }
.toc-num { font-weight: bold; color: #333; min-width: 36px; }
.toc-dots { color: #bbb; flex-shrink: 0; letter-spacing: 1px; }
.toc-title { color: #555; overflow: hidden; text-overflow: ellipsis; }

/* Stats */
.page-stats {}
.stats-grid { display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 32px; }
.big-stat {
  border: 3px solid #111;
  padding: 16px 20px;
  display: inline-block;
  background: #fff;
  box-shadow: 3px 3px 0 #111;
}
.big-num { font-size: 36px; font-weight: 900; color: #111; line-height: 1; }
.big-lbl { font-size: 9px; letter-spacing: 2px; color: #666; margin-top: 4px; }
.chaos-headline {
  font-size: 13px;
  border-top: 2px solid #111;
  padding-top: 16px;
  line-height: 1.6;
}
.chaos-headline em { display: block; font-size: 15px; font-weight: bold; font-style: normal; margin-top: 6px; }

/* Sessions */
.session-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.session-card {
  border: 2px solid #111;
  padding: 14px;
  background: #fff;
  position: relative;
  box-shadow: 2px 2px 0 #555;
}
.stamp {
  position: absolute;
  top: 10px; right: 10px;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 2px;
  border: 2px solid currentColor;
  padding: 2px 6px;
  opacity: 0.85;
}
.s-num { font-size: 10px; color: #aaa; margin-bottom: 6px; }
.s-title { font-size: 12px; font-weight: bold; color: #111; line-height: 1.4; margin-bottom: 8px; word-break: break-word; }
.s-meta { font-size: 10px; color: #666; margin-bottom: 2px; }
.s-date { font-size: 10px; color: #aaa; }

/* Back cover */
.page-back { text-align: center; min-height: 500px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; }
.back-ascii { font-size: 16px; line-height: 1.4; color: #555; white-space: pre; }
.back-title { font-size: 36px; font-weight: 900; letter-spacing: 4px; }
.back-sub { font-size: 13px; color: #666; font-style: italic; }
.back-rule { color: #aaa; letter-spacing: 2px; }
.back-text { font-size: 13px; color: #444; line-height: 2; }
.back-small { font-size: 10px; color: #aaa; letter-spacing: 1px; }
"""


def generate_html(sessions):
    n = len(sessions)
    cover    = page_cover(sessions)
    contents = page_contents(sessions)
    stats    = page_stats(sessions)
    sess_pgs = page_sessions(sessions)
    back     = page_back().replace("{ISSUE}", str(n))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sessions Zine</title>
<style>{CSS}</style>
</head>
<body>
{cover}
{contents}
{stats}
{sess_pgs}
{back}
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
