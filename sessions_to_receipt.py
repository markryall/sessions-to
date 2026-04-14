#!/usr/bin/env python3
"""Convert Claude Code sessions into thermal receipt printouts.

Each session becomes a receipt from CLAUDIA'S CODE EMPORIUM,
itemising tool calls by name, message counts, and chaos level.

Usage:
  python3 sessions_to_receipt.py                  # → tmp/sessions_receipt.html
  python3 sessions_to_receipt.py output.html
"""

import html as html_mod
import json
import sys
from pathlib import Path

CLAUDE_DIR     = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "sessions_receipt.html"

THANK_YOUS = [
    "HAVE A BLESSED DAY ✦",
    "YOUR BUGS ARE OUR BUGS",
    "PLEASE CODE AGAIN SOON",
    "WE APPRECIATE YOUR CHAOS",
    "NO REFUNDS ON BAD IDEAS",
    "KEEP SHIPPING, QUEEN",
    "THANK YOU FOR YOUR SERVICE",
    "SEE YOU IN THE NEXT SESSION",
    "MAY YOUR TESTS ALL PASS",
    "COMMIT EARLY, COMMIT OFTEN",
]

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
    user_msgs  = 0
    asst_msgs  = 0
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
                        if role == "user":
                            user_msgs += 1
                            if not first_text:
                                first_text = content.strip()
                        else:
                            asst_msgs += 1
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
                    if has_text:
                        if role == "user":
                            user_msgs += 1
                        else:
                            asst_msgs += 1
    except Exception:
        pass
    return user_msgs, asst_msgs, tools, first_text


def load_sessions():
    index_map = build_global_index(CLAUDE_DIR)
    sessions  = []
    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            sid = jsonl.stem
            user_msgs, asst_msgs, tools, first_text = parse_session(jsonl)
            if user_msgs + asst_msgs == 0:
                continue
            meta    = index_map.get(sid, {})
            title   = (meta.get("summary") or meta.get("firstPrompt") or first_text or "Untitled")
            if len(title) > 60:
                title = title[:60] + "…"
            sessions.append({
                "title":    title,
                "userMsgs": user_msgs,
                "asstMsgs": asst_msgs,
                "tools":    tools,
                "created":  meta.get("created", ""),
            })
    sessions.sort(key=lambda s: s["created"])
    n = len(sessions)
    for i, s in enumerate(sessions):
        s["chaos"] = round(i / max(n - 1, 1), 4)
    return sessions


# ── Receipt rendering ─────────────────────────────────────────────────────────

def dotted(label, value, width=26):
    label = str(label)[:18]
    value = str(value)
    dots  = "·" * max(1, width - len(label) - len(value))
    return html_mod.escape(label + dots + value)


def render_receipt(s):
    title       = html_mod.escape(s["title"][:44])
    tools       = s["tools"]
    user_msgs   = s["userMsgs"]
    asst_msgs   = s["asstMsgs"]
    total_msgs  = user_msgs + asst_msgs
    total_tools = sum(tools.values())
    chaos       = s["chaos"]
    created     = s["created"][:10] if s["created"] else "????-??-??"
    thank_you   = THANK_YOUS[abs(hash(s["title"])) % len(THANK_YOUS)]
    chaos_bar   = "█" * int(chaos * 16) + "░" * (16 - int(chaos * 16))

    tool_rows = ""
    if tools:
        top = sorted(tools.items(), key=lambda x: -x[1])[:8]
        tool_rows = (
            '<div class="div">- - - - - - - - - - - - - - -</div>'
            '<div class="lbl">TOOL CALLS</div>'
        )
        for name, count in top:
            tool_rows += f'<div class="row">{dotted(name, count)}</div>'

    return (
        '<div class="receipt">'
        '<div class="hdr">CLAUDIA\'S CODE EMPORIUM</div>'
        '<div class="tag">"We debug so you don\'t have to"</div>'
        '<div class="div">================================</div>'
        f'<div class="date">{created}</div>'
        f'<div class="ttl">{title}</div>'
        '<div class="div">- - - - - - - - - - - - - - -</div>'
        '<div class="lbl">MESSAGES</div>'
        f'<div class="row">{dotted("You", user_msgs)}</div>'
        f'<div class="row">{dotted("Claudia", asst_msgs)}</div>'
        f'{tool_rows}'
        '<div class="div">================================</div>'
        f'<div class="row tot">{dotted("TOTAL MESSAGES", total_msgs)}</div>'
        f'<div class="row tot">{dotted("TOTAL TOOL CALLS", total_tools)}</div>'
        '<div class="div">- - - - - - - - - - - - - - -</div>'
        f'<div class="row">{dotted("CHAOS LEVEL", f"{chaos*100:.1f}%")}</div>'
        f'<div class="bar">[{chaos_bar}]</div>'
        '<div class="div">================================</div>'
        f'<div class="ty">{html_mod.escape(thank_you)}</div>'
        '<div class="ft">**** HAVE A BLESSED DAY ****</div>'
        '<div class="tear"></div>'
        '</div>'
    )


# ── HTML ──────────────────────────────────────────────────────────────────────

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #1a1a1a;
  padding: 40px 20px;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
}
.page-hdr {
  text-align: center;
  color: #555;
  margin-bottom: 40px;
  font-size: 11px;
  letter-spacing: 2px;
}
.grid {
  display: flex;
  flex-wrap: wrap;
  gap: 32px;
  justify-content: center;
}
.receipt {
  background: #faf8f3;
  color: #111;
  width: 310px;
  padding: 20px 16px 0;
  box-shadow: 2px 6px 20px rgba(0,0,0,0.6);
  position: relative;
  flex-shrink: 0;
}
.receipt::before {
  content: '';
  display: block;
  height: 8px;
  background: repeating-linear-gradient(90deg, #faf8f3 0 8px, #ccc 8px 16px);
  position: absolute;
  top: -8px; left: 0; right: 0;
}
.hdr { text-align: center; font-weight: bold; font-size: 14px; letter-spacing: 1px; margin-bottom: 2px; }
.tag { text-align: center; font-size: 10px; color: #666; margin-bottom: 6px; }
.date { text-align: center; font-size: 11px; color: #777; margin: 6px 0 3px; }
.ttl { text-align: center; font-size: 11px; font-weight: bold; margin: 3px 0 5px; word-break: break-word; }
.div { color: #aaa; margin: 4px 0; font-size: 11px; }
.lbl { font-size: 10px; color: #666; letter-spacing: 1px; margin: 4px 0 2px; }
.row { font-size: 12px; white-space: pre; margin: 1px 0; }
.tot { font-weight: bold; }
.bar { font-size: 11px; margin: 2px 0; color: #333; }
.ty  { text-align: center; font-size: 11px; color: #666; margin: 8px 0 3px; }
.ft  { text-align: center; font-weight: bold; font-size: 12px; margin: 2px 0 12px; letter-spacing: 1px; }
.tear {
  height: 8px;
  background: repeating-linear-gradient(90deg, #faf8f3 0 8px, #ccc 8px 16px);
  margin: 0 -16px;
}
"""


def generate_html(sessions):
    total_msgs  = sum(s["userMsgs"] + s["asstMsgs"] for s in sessions)
    total_tools = sum(sum(s["tools"].values()) for s in sessions)
    receipts    = "\n".join(render_receipt(s) for s in sessions)
    n           = len(sessions)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sessions — Receipts</title>
<style>{CSS}</style>
</head>
<body>
<div class="page-hdr">
  CLAUDIA'S CODE EMPORIUM &nbsp;·&nbsp; {n} SESSIONS &nbsp;·&nbsp;
  {total_msgs:,} MESSAGES &nbsp;·&nbsp; {total_tools:,} TOOL CALLS
</div>
<div class="grid">
{receipts}
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
