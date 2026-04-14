#!/usr/bin/env python3
"""Convert Claude Code session JSONL files into a SQLite database."""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "sessions.db"


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id           INTEGER PRIMARY KEY,
  name         TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id                TEXT PRIMARY KEY,
  project_id        INTEGER REFERENCES projects(id),
  title             TEXT,
  created_at        TEXT,
  date              TEXT,
  user_message_count  INTEGER DEFAULT 0,
  asst_message_count  INTEGER DEFAULT 0,
  tool_use_count      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT REFERENCES sessions(id),
  role       TEXT NOT NULL,
  timestamp  TEXT,
  seq        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS blocks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id INTEGER REFERENCES messages(id),
  type       TEXT NOT NULL,
  content    TEXT,
  tool_name  TEXT,
  tool_input TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_date  ON sessions(date);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_blocks_message ON blocks(message_id);
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def project_display_name(name):
    d = name.replace("-", "/").lstrip("/")
    return d.replace("Users/markryall/", "~/")


def build_global_index(base_dir):
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


def parse_session(jsonl_path):
    """Parse a JSONL session file.

    Returns a list of message dicts, each with keys:
        role, timestamp, seq, blocks
    where blocks is a list of block dicts.
    """
    messages = []
    seq = 0
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
                msg = obj.get("message", {})
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue

                ts = obj.get("timestamp")
                content = msg.get("content", "")
                blocks = []

                if isinstance(content, str):
                    if content:
                        blocks.append({"type": "text", "content": content})
                elif isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        btype = item.get("type")
                        if btype == "text":
                            blocks.append({
                                "type": "text",
                                "content": item.get("text", ""),
                            })
                        elif btype == "tool_use":
                            raw_input = json.dumps(
                                item.get("input", {}), ensure_ascii=False
                            )
                            blocks.append({
                                "type": "tool",
                                "tool_name": item.get("name", ""),
                                "tool_input": raw_input[:4000],
                            })
                        elif btype == "thinking":
                            blocks.append({
                                "type": "thinking",
                                "content": item.get("thinking", ""),
                            })

                messages.append({
                    "role": role,
                    "timestamp": ts,
                    "seq": seq,
                    "blocks": blocks,
                })
                seq += 1
    except Exception:
        pass
    return messages


def derive_title(messages, index_entry):
    """Return a session title from the index or first user message."""
    title = (index_entry or {}).get("title", "")
    if title:
        return title

    for msg in messages:
        if msg["role"] != "user":
            continue
        for block in msg["blocks"]:
            if block["type"] == "text" and block.get("content", "").strip():
                text = block["content"].strip()
                if len(text) > 60:
                    return text[:60] + "…"
                return text
    return "Untitled"


def derive_created(messages, index_entry):
    """Return an ISO timestamp for session creation."""
    created = (index_entry or {}).get("created", "")
    if created:
        return created
    for msg in messages:
        if msg.get("timestamp"):
            return msg["timestamp"]
    return None


def derive_date(created_at):
    """Return YYYY-MM-DD from an ISO timestamp string, or None."""
    if not created_at:
        return None
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


# ── Database writes ───────────────────────────────────────────────────────────

def ensure_project(cur, name):
    """Insert or fetch a project row; return its id."""
    display = project_display_name(name)
    cur.execute(
        "INSERT OR IGNORE INTO projects (name, display_name) VALUES (?, ?)",
        (name, display),
    )
    cur.execute("SELECT id FROM projects WHERE name = ?", (name,))
    return cur.fetchone()[0]


def write_session(cur, sid, project_id, messages, index_entry):
    title      = derive_title(messages, index_entry)
    created_at = derive_created(messages, index_entry)
    date       = derive_date(created_at)

    user_count = sum(1 for m in messages if m["role"] == "user")
    asst_count = sum(1 for m in messages if m["role"] == "assistant")
    tool_count = sum(
        1 for m in messages
        for b in m["blocks"] if b["type"] == "tool"
    )

    cur.execute(
        """INSERT OR REPLACE INTO sessions
           (id, project_id, title, created_at, date,
            user_message_count, asst_message_count, tool_use_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (sid, project_id, title, created_at, date,
         user_count, asst_count, tool_count),
    )

    # Remove old messages/blocks for this session (covers the REPLACE case)
    cur.execute(
        "SELECT id FROM messages WHERE session_id = ?", (sid,)
    )
    old_msg_ids = [r[0] for r in cur.fetchall()]
    if old_msg_ids:
        placeholders = ",".join("?" * len(old_msg_ids))
        cur.execute(
            f"DELETE FROM blocks WHERE message_id IN ({placeholders})",
            old_msg_ids,
        )
        cur.execute(
            "DELETE FROM messages WHERE session_id = ?", (sid,)
        )

    for msg in messages:
        cur.execute(
            """INSERT INTO messages (session_id, role, timestamp, seq)
               VALUES (?, ?, ?, ?)""",
            (sid, msg["role"], msg["timestamp"], msg["seq"]),
        )
        msg_id = cur.lastrowid
        for block in msg["blocks"]:
            cur.execute(
                """INSERT INTO blocks
                   (message_id, type, content, tool_name, tool_input)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    msg_id,
                    block["type"],
                    block.get("content"),
                    block.get("tool_name"),
                    block.get("tool_input"),
                ),
            )

    return title


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)

    index_map = build_global_index(CLAUDE_DIR)

    con = sqlite3.connect(output)
    cur = con.cursor()
    cur.executescript(SCHEMA)
    con.commit()

    total_sessions = total_messages = total_blocks = 0

    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        pname = project_dir.name

        for jsonl in sorted(project_dir.glob("*.jsonl")):
            sid = jsonl.stem
            messages = parse_session(jsonl)
            if not messages:
                continue

            project_id = ensure_project(cur, pname)
            index_entry = index_map.get(sid)
            title = write_session(cur, sid, project_id, messages, index_entry)
            con.commit()

            msg_count   = len(messages)
            block_count = sum(len(m["blocks"]) for m in messages)
            total_sessions  += 1
            total_messages  += msg_count
            total_blocks    += block_count

            short_title = title[:50] + ("…" if len(title) > 50 else "")
            print(f"✓ {pname}/{sid[:8]} – {short_title}")

    con.close()
    print(
        f"\n✓ Done! {total_sessions} sessions, "
        f"{total_messages} messages, "
        f"{total_blocks} blocks → {output}"
    )


if __name__ == "__main__":
    main()
