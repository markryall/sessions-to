#!/usr/bin/env python3
"""Convert Claude Code session JSONL files to a single self-contained calendar HTML."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "calendar.html"


# ── Parsing helpers (same logic as other scripts, not imported) ─────────────

def build_global_index(base_dir):
    """Load all sessions-index.json files and return a merged {sessionId: entry} map."""
    index_map = {}
    for project_dir in base_dir.iterdir():
        idx_path = project_dir / "sessions-index.json"
        if idx_path.exists():
            try:
                with open(idx_path) as f:
                    idx = json.load(f)
                for entry in idx.get("entries", []):
                    sid = entry.get("sessionId")
                    if sid:
                        index_map[sid] = entry
            except Exception:
                pass
    return index_map


def first_prompt_from_messages(messages):
    """Extract the first user text from a message list (already parsed to {role, blocks})."""
    for m in messages:
        if m["role"] == "user":
            for b in m.get("blocks", []):
                if b.get("type") == "text":
                    t = b.get("content", "").strip()
                    if t:
                        return t
    return ""


def extract_blocks(content):
    """Extract message blocks: text and tool_use. Skip tool_result, thinking."""
    blocks = []
    if isinstance(content, str):
        t = content.strip()
        if t:
            blocks.append({"type": "text", "content": t})
        return blocks
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                t = block.strip()
                if t:
                    blocks.append({"type": "text", "content": t})
            elif isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "text":
                    t = block.get("text", "").strip()
                    if t:
                        blocks.append({"type": "text", "content": t})
                elif btype == "tool_use":
                    inp = block.get("input", {})
                    inp_str = json.dumps(inp, indent=2) if isinstance(inp, dict) else str(inp)
                    if len(inp_str) > 2000:
                        inp_str = inp_str[:2000] + "\n… (truncated)"
                    blocks.append({
                        "type": "tool",
                        "name": block.get("name", "tool"),
                        "input": inp_str,
                    })
    return blocks


def parse_session(jsonl_path):
    """Parse a JSONL session file into a list of {role, text, timestamp} dicts."""
    messages = []
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

                msg_type = obj.get("type")
                if msg_type not in ("user", "assistant"):
                    continue

                msg = obj.get("message", {})
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue

                content = msg.get("content", "")
                blocks = extract_blocks(content)

                if not blocks:
                    continue

                timestamp = obj.get("timestamp", "")
                messages.append({
                    "role": role,
                    "blocks": blocks,
                    "timestamp": timestamp,
                })
    except Exception as e:
        print(f"  Warning: could not parse {jsonl_path}: {e}", file=sys.stderr)
    return messages


def project_display_name(project_name):
    """Turn -Users-markryall-code-... into ~/code/..."""
    display = project_name.replace("-", "/").lstrip("/")
    display = display.replace("Users/markryall/", "~/")
    return display


# ── Load all sessions ────────────────────────────────────────────────────────

def load_all_sessions():
    sessions = []
    index_map = build_global_index(CLAUDE_DIR)

    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name

        for jsonl_file in sorted(project_dir.glob("*.jsonl")):
            session_id = jsonl_file.stem
            messages = parse_session(jsonl_file)

            if not messages:
                continue

            meta = index_map.get(session_id, {})
            summary = meta.get("summary", "")
            first_prompt = meta.get("firstPrompt", "") or first_prompt_from_messages(messages)
            created = meta.get("created", "") or (messages[0]["timestamp"] if messages else "")

            if not summary:
                summary = (first_prompt[:60] + "…") if len(first_prompt) > 60 else first_prompt or "Untitled"

            # date string YYYY-MM-DD
            date_str = ""
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

            sessions.append({
                "id": session_id,
                "title": summary,
                "project": project_name,
                "projectDisplay": project_display_name(project_name),
                "date": date_str,
                "created": created,
                "messages": messages,
            })

    return sessions


# ── HTML template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Calendar 💜</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
<style>
/* ── Reset & Base ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #0a0010;
  --bg2: #0f0018;
  --bg3: #140020;
  --pink: #ff69b4;
  --pink-dim: #ff69b488;
  --pink-faint: #ff69b422;
  --purple: #8a2be2;
  --purple-dim: #8a2be266;
  --lavender: #da8fff;
  --text: #f0d6f5;
  --text-dim: #bb99cc;
  --text-faint: #88449966;
  --border: #ff69b433;
  --border-lav: #da8fff44;
}

html, body {
  height: 100%;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  overflow: hidden;
}

/* ── Layout ── */
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.header {
  background: linear-gradient(135deg, #1a002e 0%, #2d0044 50%, #1a002e 100%);
  border-bottom: 2px solid transparent;
  border-image: linear-gradient(90deg, transparent, var(--pink), var(--lavender), var(--pink), transparent) 1;
  padding: 0.75rem 1.5rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-shrink: 0;
  z-index: 10;
}

.header h1 {
  font-size: 1.3rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--pink), var(--lavender), #ff1493, var(--pink));
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: shimmer 4s linear infinite;
}

.header .stats {
  font-size: 0.78rem;
  color: var(--text-dim);
  margin-left: auto;
}

.main {
  flex: 1;
  overflow: hidden;
  position: relative;
}

/* ── Full-width calendar ── */
.cal-panel {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.cal-nav {
  display: flex;
  align-items: center;
  padding: 0.9rem 1.25rem;
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  gap: 0.75rem;
  flex-shrink: 0;
}

.cal-nav .month-title {
  font-size: 1.1rem;
  font-weight: 700;
  flex: 1;
  text-align: center;
  background: linear-gradient(90deg, var(--pink), var(--lavender));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.nav-btn {
  background: var(--bg3);
  border: 1px solid var(--border);
  color: var(--text);
  width: 32px;
  height: 32px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
  flex-shrink: 0;
}

.nav-btn:hover {
  border-color: var(--pink);
  box-shadow: 0 0 10px var(--pink-faint);
  background: #1e0030;
}

.cal-grid-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 0.75rem 0.75rem 1rem;
}

.cal-grid-wrap::-webkit-scrollbar { width: 6px; }
.cal-grid-wrap::-webkit-scrollbar-track { background: transparent; }
.cal-grid-wrap::-webkit-scrollbar-thumb { background: var(--purple-dim); border-radius: 3px; }

.cal-week-headers {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
  margin-bottom: 4px;
}

.cal-week-header {
  text-align: center;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--lavender);
  padding: 0.3rem 0;
}

.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
}

.cal-cell {
  min-height: 90px;
  background: var(--bg2);
  border: 1px solid #1a0030;
  border-radius: 8px;
  padding: 0.35rem 0.4rem;
  transition: border-color 0.15s;
  position: relative;
  overflow: hidden;
}

.cal-cell.other-month {
  opacity: 0.3;
}

.cal-cell.has-sessions {
  border-color: var(--border);
  box-shadow: inset 0 0 12px var(--pink-faint), 0 0 6px #ff69b411;
}

.cal-cell.today {
  border-color: var(--pink) !important;
  box-shadow: 0 0 12px var(--pink-dim), inset 0 0 12px var(--pink-faint);
}

.day-num {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-dim);
  line-height: 1;
  margin-bottom: 0.3rem;
}

.cal-cell.today .day-num {
  color: var(--pink);
}

.session-pills {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pill {
  font-size: 0.64rem;
  padding: 2px 5px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: opacity 0.1s, box-shadow 0.1s, transform 0.1s;
  line-height: 1.35;
  border: 1px solid transparent;
  max-width: 100%;
}

.pill.pink-pill {
  background: linear-gradient(90deg, #2d003d, #1e0030);
  border-color: #ff69b455;
  color: var(--pink);
}

.pill.lav-pill {
  background: linear-gradient(90deg, #1a0030, #140028);
  border-color: #da8fff44;
  color: var(--lavender);
}

.pill:hover {
  opacity: 0.85;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px var(--pink-dim);
}

.pill.active {
  box-shadow: 0 0 8px var(--pink-dim);
  opacity: 1;
}

.pill.active.pink-pill {
  border-color: var(--pink);
  background: #3d0050;
}

.pill.active.lav-pill {
  border-color: var(--lavender);
  background: #28004a;
}

.pill.more-pill {
  background: #0d0018;
  border-color: #ff69b433;
  color: var(--text-dim);
  font-style: italic;
}

.pill.more-pill:hover {
  color: var(--pink);
  border-color: var(--pink);
}

.overflow-popover {
  position: fixed;
  z-index: 1000;
  background: #1a002e;
  border: 1px solid #ff69b455;
  border-radius: 10px;
  padding: 0.4rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  min-width: 200px;
  max-width: 280px;
  box-shadow: 0 8px 32px #00000088, 0 0 20px #ff69b422;
  animation: fadeIn 0.1s ease;
}

.pop-item {
  font-size: 0.72rem;
  padding: 4px 7px;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border: 1px solid transparent;
  transition: opacity 0.1s, transform 0.1s;
}

.pop-item:hover {
  opacity: 0.85;
  transform: translateX(2px);
}

/* ── Backdrop ── */
.drawer-backdrop {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.55);
  backdrop-filter: blur(2px);
  z-index: 90;
  animation: fadeIn 0.2s ease;
}

.drawer-backdrop.open { display: block; }

/* ── Slide-in drawer ── */
.reader-drawer {
  position: fixed;
  top: 0;
  right: 0;
  width: 70vw;
  height: 100vh;
  z-index: 100;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  border-left: 1px solid var(--border);
  box-shadow: -4px 0 40px #ff69b422, -2px 0 20px #8a2be233;
  transform: translateX(100%);
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.reader-drawer.open {
  transform: translateX(0);
}

.reader-header {
  padding: 0.85rem 1.25rem;
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  min-height: 70px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  position: relative;
}

.drawer-close {
  position: absolute;
  top: 50%;
  left: 1rem;
  transform: translateY(-50%);
  background: var(--bg3);
  border: 1px solid var(--border);
  color: var(--text-dim);
  width: 30px;
  height: 30px;
  border-radius: 50%;
  cursor: pointer;
  font-size: 1.1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.15s, color 0.15s, box-shadow 0.15s;
  flex-shrink: 0;
  line-height: 1;
}

.drawer-close:hover {
  border-color: var(--pink);
  color: var(--pink);
  box-shadow: 0 0 10px var(--pink-faint);
}

.reader-header-content {
  padding-left: 2.5rem;
}

.reader-title {
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.3;
  margin-bottom: 0.25rem;
}

.reader-meta {
  font-size: 0.72rem;
  color: var(--text-dim);
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.reader-meta .proj {
  color: var(--lavender);
}

.reader-body {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1.25rem 2rem;
}

.reader-body::-webkit-scrollbar { width: 6px; }
.reader-body::-webkit-scrollbar-track { background: transparent; }
.reader-body::-webkit-scrollbar-thumb { background: var(--purple-dim); border-radius: 3px; }

.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 1rem;
  color: var(--text-dim);
  text-align: center;
  padding: 2rem;
}

.placeholder .icon { font-size: 3rem; }
.placeholder p { font-size: 0.9rem; }

/* ── Messages ── */
.message {
  display: flex;
  gap: 0.75rem;
  margin: 0.85rem 0;
  align-items: flex-start;
  animation: fadeIn 0.2s ease;
}

.message.user { flex-direction: row-reverse; }

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  flex-shrink: 0;
}

.user .avatar {
  background: linear-gradient(135deg, var(--pink), #ff1493);
  box-shadow: 0 0 10px var(--pink-dim);
}

.assistant .avatar {
  background: linear-gradient(135deg, var(--purple), var(--lavender));
  box-shadow: 0 0 10px var(--purple-dim);
}

.bubble {
  width: 100%;
  padding: 0.7rem 1rem;
  border-radius: 16px;
  font-size: 0.86rem;
  line-height: 1.65;
  transition: box-shadow 0.15s;
}

.user .bubble {
  background: linear-gradient(135deg, #2d003d, #1e0030);
  border: 1px solid #ff69b455;
  border-top-right-radius: 4px;
  box-shadow: 0 2px 10px var(--pink-faint);
}

.assistant .bubble {
  background: linear-gradient(135deg, #140020, #0d001a);
  border: 1px solid var(--purple-dim);
  border-top-left-radius: 4px;
  box-shadow: 0 2px 10px #8a2be211;
}

/* Markdown in bubbles */
.bubble p { margin: 0.35rem 0; }
.bubble p:first-child { margin-top: 0; }
.bubble p:last-child { margin-bottom: 0; }

.bubble code {
  background: #2d0040;
  padding: 0.12em 0.35em;
  border-radius: 4px;
  font-family: 'Fira Code', 'Menlo', 'Monaco', monospace;
  font-size: 0.83em;
  color: var(--pink);
  border: 1px solid var(--border);
}

.bubble pre {
  background: #0d0018;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.85rem;
  overflow-x: auto;
  margin: 0.5rem 0;
  box-shadow: inset 0 0 16px var(--pink-faint);
}

.bubble pre code {
  background: none;
  padding: 0;
  border: none;
  color: #e8c5f5;
  font-size: 0.82em;
  font-family: 'Fira Code', 'Menlo', 'Monaco', monospace;
}

.bubble ul, .bubble ol {
  margin: 0.35rem 0;
  padding-left: 1.4rem;
}

.bubble li { margin: 0.15rem 0; }

.bubble h1, .bubble h2, .bubble h3, .bubble h4 {
  background: linear-gradient(90deg, var(--pink), var(--lavender));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0.75rem 0 0.25rem;
  font-weight: 700;
}

.bubble h1 { font-size: 1.1em; }
.bubble h2 { font-size: 1.0em; }
.bubble h3, .bubble h4 { font-size: 0.95em; }

.bubble blockquote {
  border-left: 3px solid var(--pink);
  padding-left: 0.7rem;
  color: var(--text-dim);
  margin: 0.4rem 0;
  font-style: italic;
}

.bubble strong { color: var(--pink); }
.bubble em { color: var(--lavender); }
.bubble a { color: var(--pink); }
.bubble hr { border: none; border-top: 1px solid var(--border); margin: 0.6rem 0; }

.msg-ts {
  font-size: 0.65rem;
  color: var(--text-faint);
  text-align: center;
  margin: 1.25rem 0 0.5rem;
  letter-spacing: 0.1em;
}

.msg-ts::before { content: '✦ '; color: #ff69b444; }
.msg-ts::after  { content: ' ✦'; color: #ff69b444; }

.bubble-wrap {
  display: flex;
  flex-direction: column;
  max-width: 75%;
}

.message.user .bubble-wrap { align-items: flex-end; }
.message.assistant .bubble-wrap { align-items: flex-start; }

.bubble-ts {
  font-size: 0.63rem;
  color: #ff69b466;
  margin-top: 0.2rem;
  letter-spacing: 0.04em;
}

.message.user .bubble-ts { text-align: right; }
.message.assistant .bubble-ts { text-align: left; }

.tool-details {
  background: #0a0015;
  border: 1px solid #ff69b422;
  border-radius: 8px;
  padding: 0.4em 0.6em;
  margin: 0.4em 0;
  font-size: 0.82em;
}

.tool-details summary {
  cursor: pointer;
  color: #9966aa;
  user-select: none;
  list-style: none;
  padding: 0.1em 0;
}

.tool-details summary:hover { color: var(--pink); }
.tool-details[open] summary { color: var(--lavender); margin-bottom: 0.4em; }

.tool-input {
  background: #06000e;
  border: 1px solid #2a003a;
  border-radius: 6px;
  padding: 0.5em;
  font-size: 0.8em;
  color: #bb99cc;
  overflow-x: auto;
  white-space: pre;
  max-height: 200px;
  overflow-y: auto;
}

/* ── Animations ── */
@keyframes shimmer {
  0% { background-position: 0% center; }
  100% { background-position: 200% center; }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0)  scale(1); }
}

@keyframes sparkle-spin {
  0%   { transform: scale(1)   rotate(0deg);   opacity: 1; }
  50%  { transform: scale(1.4) rotate(180deg); opacity: 0.6; }
  100% { transform: scale(1)   rotate(360deg); opacity: 1; }
}

@keyframes float {
  0%, 100% { transform: translateY(0px); }
  50%       { transform: translateY(-6px); }
}

@keyframes glow-pulse {
  0%, 100% { box-shadow: 0 0 6px var(--pink), 0 0 12px #ff69b422; }
  50%       { box-shadow: 0 0 14px var(--pink), 0 0 28px #ff69b455, 0 0 40px #ff69b422; }
}

@keyframes star-pop {
  0%   { transform: scale(0) rotate(-20deg); opacity: 0; }
  60%  { transform: scale(1.3) rotate(10deg); opacity: 1; }
  100% { transform: scale(1) rotate(0deg); opacity: 1; }
}

/* Floating sparkles in body background */
body::before {
  content: '✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦';
  position: fixed;
  top: 3px; left: 0; right: 0;
  text-align: center;
  font-size: 0.55rem;
  color: #ff69b418;
  letter-spacing: 1.8rem;
  pointer-events: none;
  z-index: 0;
}

body::after {
  content: '✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧';
  position: fixed;
  bottom: 3px; left: 0; right: 0;
  text-align: center;
  font-size: 0.55rem;
  color: #da8fff18;
  letter-spacing: 1.8rem;
  pointer-events: none;
  z-index: 0;
}

/* Pill hover sparkle */
.session-pill:hover {
  animation: glow-pulse 1.2s ease-in-out infinite !important;
}

/* Selected day glow */
.day-cell.has-sessions:hover { animation: glow-pulse 1.5s ease-in-out infinite; }

/* Reader placeholder floats */
.reader-placeholder { animation: float 3s ease-in-out infinite; }

/* Scrollbars (Firefox) ── */
* { scrollbar-width: thin; scrollbar-color: var(--purple-dim) transparent; }
</style>
</head>
<body>
<div class="app">
  <header class="header">
    <h1>✨ Claude Calendar 💜 ✨</h1>
    <span class="stats" id="stats"></span>
  </header>
  <div class="main">
    <!-- Full-width calendar -->
    <div class="cal-panel">
      <div class="cal-nav">
        <button class="nav-btn" id="prevYear" title="Previous year">«</button>
        <button class="nav-btn" id="prevMonth" title="Previous month">‹</button>
        <div class="month-title" id="monthTitle"></div>
        <button class="nav-btn" id="nextMonth" title="Next month">›</button>
        <button class="nav-btn" id="nextYear" title="Next year">»</button>
      </div>
      <div class="cal-grid-wrap">
        <div class="cal-week-headers">
          <div class="cal-week-header">Mon</div>
          <div class="cal-week-header">Tue</div>
          <div class="cal-week-header">Wed</div>
          <div class="cal-week-header">Thu</div>
          <div class="cal-week-header">Fri</div>
          <div class="cal-week-header">Sat</div>
          <div class="cal-week-header">Sun</div>
        </div>
        <div class="cal-grid" id="calGrid"></div>
      </div>
    </div>
  </div>

  <!-- Backdrop -->
  <div class="drawer-backdrop" id="drawerBackdrop"></div>

  <!-- Slide-in transcript drawer -->
  <div class="reader-drawer" id="readerDrawer">
    <div class="reader-header" id="readerHeader">
      <button class="drawer-close" id="drawerClose" title="Close">✕</button>
      <div class="reader-header-content">
        <div style="font-size:0.85rem; color:var(--text-dim)">select a session to reminisce 💜</div>
      </div>
    </div>
    <div class="reader-body" id="readerBody">
      <div class="placeholder">
        <div class="icon">💜</div>
        <p>pick a glowing day on the calendar<br>and tap a session pill</p>
      </div>
    </div>
  </div>
</div>

<script>
// ── Embedded session data ────────────────────────────────────────────────────
const SESSIONS = __SESSIONS_JSON__;

// ── State ────────────────────────────────────────────────────────────────────
const today = new Date();
let curYear  = today.getFullYear();
let curMonth = today.getMonth(); // 0-based
let activeSession = null;

// ── Index sessions by date ───────────────────────────────────────────────────
const byDate = {};
for (const s of SESSIONS) {
  if (!s.date) continue;
  if (!byDate[s.date]) byDate[s.date] = [];
  byDate[s.date].push(s);
}

document.getElementById('stats').textContent =
  `${SESSIONS.length} sessions · ${Object.keys(byDate).length} days`;

// ── Calendar rendering ───────────────────────────────────────────────────────
const MONTH_NAMES = ['January','February','March','April','May','June',
                     'July','August','September','October','November','December'];

function pad2(n) { return String(n).padStart(2,'0'); }
function dateKey(y, m, d) { return `${y}-${pad2(m+1)}-${pad2(d)}`; }

function renderCalendar() {
  document.getElementById('monthTitle').textContent =
    `${MONTH_NAMES[curMonth]} ${curYear}`;

  const grid = document.getElementById('calGrid');
  grid.innerHTML = '';

  // First day of month (0=Sun..6=Sat), convert to Mon-based (0=Mon..6=Sun)
  const firstDay = new Date(curYear, curMonth, 1).getDay();
  const startOffset = (firstDay === 0) ? 6 : firstDay - 1;

  const daysInMonth = new Date(curYear, curMonth + 1, 0).getDate();
  const daysInPrev  = new Date(curYear, curMonth, 0).getDate();

  const todayKey = `${today.getFullYear()}-${pad2(today.getMonth()+1)}-${pad2(today.getDate())}`;

  // Leading cells from previous month
  for (let i = 0; i < startOffset; i++) {
    const d = daysInPrev - startOffset + 1 + i;
    const prevMonth = curMonth === 0 ? 11 : curMonth - 1;
    const prevYear  = curMonth === 0 ? curYear - 1 : curYear;
    const key = dateKey(prevYear, prevMonth, d);
    grid.appendChild(buildCell(d, key, true));
  }

  // Current month cells
  for (let d = 1; d <= daysInMonth; d++) {
    const key = dateKey(curYear, curMonth, d);
    const cell = buildCell(d, key, false);
    if (key === todayKey) cell.classList.add('today');
    grid.appendChild(cell);
  }

  // Trailing cells for next month
  const total = startOffset + daysInMonth;
  const trailCount = total % 7 === 0 ? 0 : 7 - (total % 7);
  for (let d = 1; d <= trailCount; d++) {
    const nextMonth = curMonth === 11 ? 0 : curMonth + 1;
    const nextYear  = curMonth === 11 ? curYear + 1 : curYear;
    const key = dateKey(nextYear, nextMonth, d);
    grid.appendChild(buildCell(d, key, true));
  }
}

function buildCell(dayNum, dateKey, otherMonth) {
  const sessions = byDate[dateKey] || [];
  const cell = document.createElement('div');
  cell.className = 'cal-cell' +
    (otherMonth ? ' other-month' : '') +
    (sessions.length ? ' has-sessions' : '');

  const num = document.createElement('div');
  num.className = 'day-num';
  num.textContent = dayNum;
  cell.appendChild(num);

  if (sessions.length) {
    const pillsDiv = document.createElement('div');
    pillsDiv.className = 'session-pills';

    const MAX_PILLS = 4;
    const shown = sessions.slice(0, MAX_PILLS);
    for (const s of shown) {
      const isFresho = s.project.includes('Fresho-Org') || s.project.toLowerCase().includes('fresho');
      const pill = document.createElement('div');
      pill.className = 'pill ' + (isFresho ? 'lav-pill' : 'pink-pill');
      pill.title = s.title;
      pill.textContent = s.title.length > 32 ? s.title.slice(0, 31) + '…' : s.title;
      pill.dataset.sessionId = s.id;
      pill.addEventListener('click', e => {
        e.stopPropagation();
        selectSession(s.id, pill);
      });
      pillsDiv.appendChild(pill);
    }

    if (sessions.length > MAX_PILLS) {
      const overflow = sessions.slice(MAX_PILLS);
      const more = document.createElement('div');
      more.className = 'pill more-pill';
      more.textContent = `+${overflow.length} more`;
      more.addEventListener('click', e => {
        e.stopPropagation();
        showOverflowPopover(more, overflow);
      });
      pillsDiv.appendChild(more);
    }

    cell.appendChild(pillsDiv);
  }

  return cell;
}

// ── Overflow popover ──────────────────────────────────────────────────────────
let activePopover = null;

function showOverflowPopover(anchor, sessions) {
  closePopover();
  const pop = document.createElement('div');
  pop.className = 'overflow-popover';
  for (const s of sessions) {
    const isFresho = s.project.includes('Fresho-Org') || s.project.toLowerCase().includes('fresho');
    const item = document.createElement('div');
    item.className = 'pop-item ' + (isFresho ? 'lav-pill' : 'pink-pill');
    item.textContent = s.title.length > 40 ? s.title.slice(0, 39) + '…' : s.title;
    item.title = s.title;
    item.addEventListener('click', e => {
      e.stopPropagation();
      closePopover();
      selectSession(s.id, null);
    });
    pop.appendChild(item);
  }
  document.body.appendChild(pop);
  activePopover = pop;

  // Position below anchor
  const rect = anchor.getBoundingClientRect();
  pop.style.left = Math.min(rect.left, window.innerWidth - 220) + 'px';
  pop.style.top  = (rect.bottom + 4) + 'px';

  setTimeout(() => document.addEventListener('click', closePopover, { once: true }), 0);
}

function closePopover() {
  if (activePopover) { activePopover.remove(); activePopover = null; }
}

// ── Markdown renderer (regex-based, no external libs) ────────────────────────
function renderMarkdown(text) {
  // Extract fenced code blocks first
  const codeBlocks = [];
  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre><code class="lang-${esc(lang)}">${esc(code)}</code></pre>`);
    return `\x00CODE${idx}\x00`;
  });

  // Extract inline code
  const inlineCodes = [];
  text = text.replace(/`([^`\n]+)`/g, (_, c) => {
    const idx = inlineCodes.length;
    inlineCodes.push(`<code>${esc(c)}</code>`);
    return `\x00INLINE${idx}\x00`;
  });

  // Escape HTML
  text = esc(text);

  // Headers
  text = text.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // Bold / italic
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*\n]+?)\*/g, '<em>$1</em>');
  text = text.replace(/_([^_\n]+?)_/g, '<em>$1</em>');

  // Blockquote
  text = text.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

  // HR
  text = text.replace(/^---+$/gm, '<hr>');

  // Lists (simple)
  text = text.replace(/(?:^(?:[-*] .+\n?))+/gm, m => {
    const items = m.trim().split('\n').filter(Boolean);
    return '<ul>' + items.map(i => `<li>${i.replace(/^[-*] /, '')}</li>`).join('') + '</ul>';
  });
  text = text.replace(/(?:^\d+\. .+\n?)+/gm, m => {
    const items = m.trim().split('\n').filter(Boolean);
    return '<ol>' + items.map(i => `<li>${i.replace(/^\d+\. /, '')}</li>`).join('') + '</ol>';
  });

  // Links
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');

  // Paragraphs
  const paras = text.split(/\n{2,}/);
  text = paras.map(p => {
    p = p.trim();
    if (!p) return '';
    if (/^<(h[1-6]|ul|ol|blockquote|hr|pre|\x00CODE)/.test(p)) return p;
    return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
  }).filter(Boolean).join('\n');

  // Restore
  inlineCodes.forEach((c, i) => { text = text.replace(`\x00INLINE${i}\x00`, c); });
  codeBlocks.forEach((c, i) => { text = text.replace(`\x00CODE${i}\x00`, c); });

  return text;
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
const escHtml = esc;

// ── Drawer open / close ───────────────────────────────────────────────────────
function openDrawer() {
  document.getElementById('readerDrawer').classList.add('open');
  document.getElementById('drawerBackdrop').classList.add('open');
}

function closeDrawer() {
  document.getElementById('readerDrawer').classList.remove('open');
  document.getElementById('drawerBackdrop').classList.remove('open');
  document.querySelectorAll('.pill.active').forEach(p => p.classList.remove('active'));
  activeSession = null;
}

document.getElementById('drawerClose').addEventListener('click', closeDrawer);
document.getElementById('drawerBackdrop').addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

// ── Session reader ───────────────────────────────────────────────────────────
function selectSession(id, pillEl) {
  // Deactivate previous pill
  document.querySelectorAll('.pill.active').forEach(p => p.classList.remove('active'));
  if (pillEl) pillEl.classList.add('active');

  const session = SESSIONS.find(s => s.id === id);
  if (!session) return;
  activeSession = id;

  openDrawer();

  // Header
  const header = document.getElementById('readerHeader');
  const createdFmt = session.created ? formatDate(session.created) : session.date;
  header.innerHTML = `
    <button class="drawer-close" id="drawerClose" title="Close">✕</button>
    <div class="reader-header-content">
      <div class="reader-title">${esc(session.title)}</div>
      <div class="reader-meta">
        <span class="proj">📁 ${esc(session.projectDisplay)}</span>
        <span>🗓 ${esc(createdFmt)}</span>
        <span style="color:var(--text-faint);font-size:0.65rem">${esc(id.slice(0,8))}</span>
      </div>
    </div>
  `;
  document.getElementById('drawerClose').addEventListener('click', closeDrawer);

  // Messages
  const body = document.getElementById('readerBody');
  let html = '';
  let lastDate = null;

  for (const msg of session.messages) {
    if (msg.timestamp) {
      try {
        const dt = new Date(msg.timestamp);
        const ds = dt.toLocaleDateString('en-GB', { day:'2-digit', month:'short', year:'numeric' });
        if (ds !== lastDate) {
          html += `<div class="msg-ts">${ds}</div>`;
          lastDate = ds;
        }
      } catch(e) {}
    }

    const role = msg.role;
    const avatar = role === 'user' ? '🧑' : '💜';

    // Render all blocks
    let bubbleContent = '';
    for (const block of (msg.blocks || [])) {
      if (block.type === 'text') {
        bubbleContent += renderMarkdown(block.content || '');
      } else if (block.type === 'tool') {
        const name = escHtml(block.name || 'tool');
        const input = escHtml(block.input || '');
        bubbleContent += `
          <details class="tool-details">
            <summary>🔧 ${name}</summary>
            <pre class="tool-input">${input}</pre>
          </details>`;
      }
    }
    if (!bubbleContent.trim()) continue;

    let timeStr = '';
    if (msg.timestamp) {
      try {
        const dt = new Date(msg.timestamp);
        timeStr = dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
      } catch(e) {}
    }
    const timeTag = timeStr ? `<div class="bubble-ts">${timeStr}</div>` : '';

    html += `
      <div class="message ${role}">
        <div class="avatar">${avatar}</div>
        <div class="bubble-wrap">
          <div class="bubble">${bubbleContent}</div>
          ${timeTag}
        </div>
      </div>
    `;
  }

  body.innerHTML = html || '<div class="placeholder"><p style="color:var(--text-dim)">no messages to show</p></div>';
  body.scrollTop = 0;
}

function formatDate(isoStr) {
  try {
    const dt = new Date(isoStr);
    return dt.toLocaleString('en-GB', {
      day:'2-digit', month:'short', year:'numeric',
      hour:'2-digit', minute:'2-digit'
    });
  } catch(e) { return isoStr; }
}

// ── Navigation ───────────────────────────────────────────────────────────────
document.getElementById('prevMonth').addEventListener('click', () => {
  curMonth--;
  if (curMonth < 0) { curMonth = 11; curYear--; }
  renderCalendar();
});
document.getElementById('nextMonth').addEventListener('click', () => {
  curMonth++;
  if (curMonth > 11) { curMonth = 0; curYear++; }
  renderCalendar();
});
document.getElementById('prevYear').addEventListener('click', () => {
  curYear--;
  renderCalendar();
});
document.getElementById('nextYear').addEventListener('click', () => {
  curYear++;
  renderCalendar();
});

// ── Boot ─────────────────────────────────────────────────────────────────────
renderCalendar();

// Auto-navigate to most recent session's month if it's not current month
if (SESSIONS.length > 0) {
  const sorted = [...SESSIONS].filter(s => s.date).sort((a, b) => b.date.localeCompare(a.date));
  if (sorted.length > 0) {
    const latest = sorted[0].date;
    const [ly, lm] = latest.split('-').map(Number);
    // only auto-jump if current month has no sessions
    const thisMonthKey = `${today.getFullYear()}-${pad2(today.getMonth()+1)}`;
    const hasThisMonth = Object.keys(byDate).some(k => k.startsWith(thisMonthKey));
    if (!hasThisMonth) {
      curYear = ly;
      curMonth = lm - 1;
      renderCalendar();
    }
  }
}
</script>
</body>
</html>
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT

    print("Loading sessions…")
    sessions = load_all_sessions()
    print(f"✓ {len(sessions)} sessions loaded")

    # Serialize to JSON — messages contain arbitrary text so use ensure_ascii=False
    sessions_json = json.dumps(sessions, ensure_ascii=False, separators=(",", ":"))
    # Escape </ so embedded HTML in tool inputs can't break the <script> tag
    sessions_json = sessions_json.replace("</", "<\\/")

    html = HTML_TEMPLATE.replace("__SESSIONS_JSON__", sessions_json)

    output_path.write_text(html, encoding="utf-8")
    print(f"✓ Written to {output_path}")


if __name__ == "__main__":
    main()
