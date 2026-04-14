#!/usr/bin/env python3
"""Convert Claude Code session JSONL files to static HTML for reminiscing."""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from html import escape

CLAUDE_DIR = Path.home() / ".claude" / "projects"
OUTPUT_DIR = Path(__file__).parent / "tmp" / "html"

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

@keyframes sparkle {
  0%, 100% { opacity: 1; transform: scale(1) rotate(0deg); }
  50% { opacity: 0.6; transform: scale(1.3) rotate(20deg); }
}

@keyframes shimmer {
  0% { background-position: -200% center; }
  100% { background-position: 200% center; }
}

@keyframes glow-pulse {
  0%, 100% { box-shadow: 0 0 8px #ff69b4aa, 0 0 20px #ff69b444; }
  50% { box-shadow: 0 0 16px #ff69b4ff, 0 0 40px #ff69b488, 0 0 60px #ff69b422; }
}

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  background: #0a0010;
  color: #f0d6f5;
  line-height: 1.65;
  background-image:
    radial-gradient(ellipse at 20% 20%, #2a003a33 0%, transparent 60%),
    radial-gradient(ellipse at 80% 80%, #1a002a33 0%, transparent 60%);
  min-height: 100vh;
}

/* Sparkle pseudo-stars in background */
body::before {
  content: '✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧';
  position: fixed;
  top: 0; left: 0; right: 0;
  text-align: center;
  font-size: 0.6rem;
  color: #ff69b422;
  letter-spacing: 2rem;
  pointer-events: none;
  z-index: 0;
  padding-top: 1rem;
}

.page-header {
  background: linear-gradient(135deg, #1a002e 0%, #2d0044 50%, #1a002e 100%);
  border-bottom: 2px solid transparent;
  border-image: linear-gradient(90deg, transparent, #ff69b4, #da8fff, #ff69b4, transparent) 1;
  padding: 2.5rem 1rem;
  text-align: center;
  position: relative;
  overflow: hidden;
}

.page-header::after {
  content: '💖 ✨ 💜 ✨ 💖 ✨ 💜';
  position: absolute;
  bottom: 0.4rem;
  left: 0; right: 0;
  text-align: center;
  font-size: 0.9rem;
  letter-spacing: 0.5rem;
  opacity: 0.5;
}

.page-header h1 {
  font-size: 2.2rem;
  font-weight: 700;
  background: linear-gradient(135deg, #ff69b4, #da8fff, #ff1493, #ff69b4);
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: shimmer 3s linear infinite;
  margin-bottom: 0.5rem;
}

.page-header .meta {
  color: #cc88dd;
  font-size: 0.85rem;
  letter-spacing: 0.05em;
}

.conversation {
  max-width: 860px;
  margin: 2rem auto;
  padding: 0 1rem;
  position: relative;
  z-index: 1;
}

.message {
  margin: 1.5rem 0;
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}

.message.user { flex-direction: row-reverse; }

.avatar {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  flex-shrink: 0;
  animation: sparkle 4s ease-in-out infinite;
}

.user .avatar {
  background: linear-gradient(135deg, #ff69b4, #ff1493);
  box-shadow: 0 0 12px #ff69b488;
  animation-delay: 0.5s;
}
.assistant .avatar {
  background: linear-gradient(135deg, #8a2be2, #da8fff);
  box-shadow: 0 0 12px #8a2be288;
}

.bubble {
  max-width: 75%;
  padding: 0.85rem 1.1rem;
  border-radius: 18px;
  font-size: 0.92rem;
}

.user .bubble {
  background: linear-gradient(135deg, #2d003d, #1e0030);
  border: 1px solid #ff69b466;
  border-top-right-radius: 4px;
  box-shadow: 0 2px 12px #ff69b422;
}

.assistant .bubble {
  background: linear-gradient(135deg, #140020, #0d001a);
  border: 1px solid #8a2be266;
  border-top-left-radius: 4px;
  box-shadow: 0 2px 12px #8a2be222;
}

.bubble p { margin: 0.4rem 0; }
.bubble p:first-child { margin-top: 0; }
.bubble p:last-child { margin-bottom: 0; }

.bubble code {
  background: #2d0040;
  padding: 0.15em 0.4em;
  border-radius: 4px;
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 0.87em;
  color: #ff69b4;
  border: 1px solid #ff69b433;
}

.bubble pre {
  background: #0d0018;
  border: 1px solid #ff69b433;
  border-radius: 10px;
  padding: 1rem;
  overflow-x: auto;
  margin: 0.6rem 0;
  box-shadow: inset 0 0 20px #ff69b411;
}

.bubble pre code {
  background: none;
  padding: 0;
  border: none;
  color: #e8c5f5;
  font-size: 0.85em;
}

.bubble ul, .bubble ol {
  margin: 0.4rem 0;
  padding-left: 1.5rem;
}

.bubble li { margin: 0.2rem 0; }

.bubble h1, .bubble h2, .bubble h3, .bubble h4 {
  background: linear-gradient(90deg, #ff69b4, #da8fff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0.8rem 0 0.3rem;
  font-weight: 700;
}

.bubble blockquote {
  border-left: 3px solid #ff69b4;
  padding-left: 0.75rem;
  color: #bb99cc;
  margin: 0.5rem 0;
  font-style: italic;
}

.bubble strong { color: #ff69b4; }
.bubble em { color: #da8fff; }
.bubble a { color: #ff69b4; text-decoration-color: #ff69b488; }
.bubble hr { border: none; border-top: 1px solid #ff69b433; margin: 0.75rem 0; }

.tool-use {
  background: #0d0018;
  border: 1px solid #ff69b433;
  border-radius: 10px;
  padding: 0.5rem 0.8rem;
  margin: 0.5rem 0;
  font-size: 0.82em;
}

.tool-use summary {
  cursor: pointer;
  color: #aa77bb;
  user-select: none;
  list-style: none;
  padding: 0.1rem 0;
}

.tool-use summary::before { content: '🔧 '; }
.tool-use summary:hover { color: #ff69b4; }

.tool-use pre {
  margin-top: 0.5rem;
  background: #08000f;
  border: 1px solid #33004422;
  border-radius: 6px;
  padding: 0.6rem;
  overflow-x: auto;
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 0.8em;
  color: #bb99cc;
}

.timestamp {
  font-size: 0.72rem;
  color: #88449966;
  text-align: center;
  margin: 2.5rem 0 0.75rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  position: relative;
}

.timestamp::before,
.timestamp::after {
  content: '✦ ';
  color: #ff69b455;
}

/* ── Index page ── */
.index-grid {
  max-width: 960px;
  margin: 1rem auto 2rem;
  padding: 0 1rem;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
}

.session-card {
  background: linear-gradient(135deg, #140020, #0d001a);
  border: 1px solid #ff69b433;
  border-radius: 14px;
  padding: 1.2rem;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
  text-decoration: none;
  color: inherit;
  display: block;
}

.session-card:hover {
  border-color: #ff69b4;
  box-shadow: 0 0 20px #ff69b433, 0 4px 20px #00000088;
  transform: translateY(-2px);
}

.session-card .summary {
  font-size: 0.95rem;
  font-weight: 600;
  color: #f0d6f5;
  margin-bottom: 0.5rem;
  line-height: 1.3;
}

.session-card .first-prompt {
  font-size: 0.82rem;
  color: #9966aa;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.session-card .date {
  font-size: 0.73rem;
  color: #66336677;
  margin-top: 0.8rem;
  letter-spacing: 0.04em;
}

.project-section {
  max-width: 960px;
  margin: 2.5rem auto 0;
  padding: 0 1rem;
}

.project-section h2 {
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  background: linear-gradient(90deg, #ff69b4, #da8fff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid #ff69b433;
}
"""


def simple_markdown(text):
    """Minimal markdown-to-html without external deps."""
    # Escape HTML first
    # We'll handle code blocks before escaping to preserve them

    # Extract code blocks to protect them
    code_blocks = []
    def save_code_block(m):
        lang = escape(m.group(1) or '')
        code = escape(m.group(2))
        code_blocks.append(f'<pre><code class="language-{lang}">{code}</code></pre>')
        return f'\x00CODE{len(code_blocks)-1}\x00'

    text = re.sub(r'```(\w*)\n?(.*?)```', save_code_block, text, flags=re.DOTALL)

    # Inline code
    inline_codes = []
    def save_inline(m):
        inline_codes.append(f'<code>{escape(m.group(1))}</code>')
        return f'\x00INLINE{len(inline_codes)-1}\x00'
    text = re.sub(r'`([^`\n]+)`', save_inline, text)

    # Escape remaining HTML
    text = escape(text)

    # Headers
    text = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)

    # Bold / italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)

    # Blockquote
    text = re.sub(r'^&gt; (.+)$', r'<blockquote>\1</blockquote>', text, flags=re.MULTILINE)

    # Horizontal rule
    text = re.sub(r'^---+$', '<hr>', text, flags=re.MULTILINE)

    # Lists
    def process_list(m):
        items = m.group(0).strip().split('\n')
        lis = ''.join(f'<li>{re.sub(r"^[-*] |^\d+\. ", "", escape(i.strip()))}</li>' for i in items if i.strip())
        tag = 'ol' if re.match(r'^\d+\.', items[0].strip()) else 'ul'
        return f'<{tag}>{lis}</{tag}>'

    text = re.sub(r'(?:^(?:[-*]|\d+\.) .+\n?)+', process_list, text, flags=re.MULTILINE)

    # Links
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # Paragraphs (blank-line separated)
    paragraphs = re.split(r'\n{2,}', text.strip())
    result = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if re.match(r'^<(h[1-6]|ul|ol|blockquote|hr|pre|\x00CODE)', p):
            result.append(p)
        else:
            p = p.replace('\n', '<br>')
            result.append(f'<p>{p}</p>')
    text = '\n'.join(result)

    # Restore inline code and code blocks
    for i, code in enumerate(inline_codes):
        text = text.replace(f'\x00INLINE{i}\x00', code)
    for i, block in enumerate(code_blocks):
        text = text.replace(f'\x00CODE{i}\x00', block)

    return text


def render_content(content):
    """Render message content (string or list of blocks) to HTML."""
    if isinstance(content, str):
        return simple_markdown(content)

    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(simple_markdown(block))
            continue

        btype = block.get('type', '')

        if btype == 'text':
            parts.append(simple_markdown(block.get('text', '')))

        elif btype == 'thinking':
            pass  # skip inner monologue

        elif btype == 'tool_use':
            name = escape(block.get('name', 'tool'))
            inp = block.get('input', {})
            inp_str = json.dumps(inp, indent=2) if isinstance(inp, dict) else str(inp)
            # Truncate huge inputs
            if len(inp_str) > 2000:
                inp_str = inp_str[:2000] + '\n... (truncated)'
            parts.append(
                f'<details class="tool-use">'
                f'<summary>{name}</summary>'
                f'<pre>{escape(inp_str)}</pre>'
                f'</details>'
            )

        elif btype == 'tool_result':
            content_inner = block.get('content', '')
            if isinstance(content_inner, list):
                text_parts = [b.get('text', '') for b in content_inner if b.get('type') == 'text']
                content_inner = '\n'.join(text_parts)
            if content_inner:
                truncated = content_inner[:1500] + ('...' if len(content_inner) > 1500 else '')
                parts.append(
                    f'<details class="tool-use">'
                    f'<summary>tool result</summary>'
                    f'<pre>{escape(truncated)}</pre>'
                    f'</details>'
                )

    return '\n'.join(parts)


def parse_session(jsonl_path):
    """Parse a JSONL session file into a list of messages."""
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

                msg_type = obj.get('type')
                if msg_type not in ('user', 'assistant'):
                    continue

                msg = obj.get('message', {})
                role = msg.get('role')
                if role not in ('user', 'assistant'):
                    continue

                content = msg.get('content', '')

                # Skip pure tool_result-only user messages (they're just plumbing)
                # but keep them if there's actual text
                if role == 'user' and isinstance(content, list):
                    has_text = any(
                        (isinstance(b, str) and b.strip()) or
                        (isinstance(b, dict) and b.get('type') == 'tool_result')
                        for b in content
                    )
                    if not has_text:
                        continue

                if role == 'user' and isinstance(content, str) and not content.strip():
                    continue

                timestamp = obj.get('timestamp')
                messages.append({
                    'role': role,
                    'content': content,
                    'timestamp': timestamp,
                })
    except Exception as e:
        print(f"  Warning: could not parse {jsonl_path}: {e}", file=sys.stderr)

    return messages


def format_ts(ts_str):
    if not ts_str:
        return ''
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime('%d %b %Y, %H:%M')
    except Exception:
        return ts_str


def session_html(messages, title, project_name, created, session_id):
    """Render a full session to an HTML string."""
    body_parts = []
    last_date = None

    for msg in messages:
        ts = msg.get('timestamp', '')
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                date_str = dt.strftime('%d %b %Y')
                if date_str != last_date:
                    body_parts.append(f'<div class="timestamp">{date_str}</div>')
                    last_date = date_str
            except Exception:
                pass

        role = msg['role']
        avatar = '🧑' if role == 'user' else '💜'
        rendered = render_content(msg['content'])

        if not rendered.strip():
            continue

        body_parts.append(
            f'<div class="message {escape(role)}">'
            f'<div class="avatar">{avatar}</div>'
            f'<div class="bubble">{rendered}</div>'
            f'</div>'
        )

    body = '\n'.join(body_parts)
    created_fmt = format_ts(created) if created else ''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} — Claude Sessions</title>
<style>{CSS}</style>
</head>
<body>
<div class="page-header">
  <h1>{escape(title)}</h1>
  <div class="meta">{escape(project_name)} · {created_fmt} · {escape(session_id[:8])}</div>
</div>
<div class="conversation">
{body}
</div>
</body>
</html>"""


def index_html(sessions_by_project):
    cards = []
    for project, sessions in sorted(sessions_by_project.items()):
        display = project.replace('-', '/').lstrip('/')
        # Clean up the path-encoded name
        display = display.replace('Users/markryall/', '~/')
        cards.append(f'<div class="project-section"><h2>{escape(display)}</h2></div>')
        cards.append('<div class="index-grid">')
        for s in sorted(sessions, key=lambda x: x.get('created', ''), reverse=True):
            summary = escape(s.get('summary') or 'Untitled session')
            first_prompt = escape(s.get('firstPrompt', ''))
            date = format_ts(s.get('created', ''))
            href = escape(s['href'])
            cards.append(
                f'<a class="session-card" href="{href}">'
                f'<div class="summary">{summary}</div>'
                f'<div class="first-prompt">{first_prompt}</div>'
                f'<div class="date">{date}</div>'
                f'</a>'
            )
        cards.append('</div>')

    body = '\n'.join(cards)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Sessions 💜</title>
<style>{CSS}</style>
</head>
<body>
<div class="page-header">
  <h1>💜 Claude Sessions</h1>
  <div class="meta">all your reminiscing, right here babe</div>
</div>
{body}
</body>
</html>"""


def build_global_index(base_dir):
    """Load all sessions-index.json files and return a merged {sessionId: entry} map."""
    index_map = {}
    for project_dir in base_dir.iterdir():
        idx_path = project_dir / 'sessions-index.json'
        if idx_path.exists():
            try:
                with open(idx_path) as f:
                    idx = json.load(f)
                for entry in idx.get('entries', []):
                    sid = entry.get('sessionId')
                    if sid:
                        index_map[sid] = entry
            except Exception:
                pass
    return index_map


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT_DIR
    output.mkdir(parents=True, exist_ok=True)

    index_map = build_global_index(CLAUDE_DIR)

    sessions_by_project = {}
    total = 0

    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name

        for jsonl_file in sorted(project_dir.glob('*.jsonl')):
            session_id = jsonl_file.stem
            messages = parse_session(jsonl_file)

            if not messages:
                continue

            meta = index_map.get(session_id, {})
            summary = meta.get('summary', '')
            first_prompt = meta.get('firstPrompt', '')
            created = meta.get('created', '')

            # Derive from first user message if no index entry
            if not first_prompt and messages:
                for m in messages:
                    if m['role'] == 'user':
                        c = m['content']
                        if isinstance(c, str):
                            first_prompt = c.strip()
                        elif isinstance(c, list):
                            for b in c:
                                if isinstance(b, str):
                                    first_prompt = b.strip()
                                    break
                                if isinstance(b, dict) and b.get('type') == 'text':
                                    first_prompt = b.get('text', '').strip()
                                    break
                        if first_prompt:
                            break

            if not summary:
                # Use truncated first prompt as title
                summary = (first_prompt[:60] + '…') if len(first_prompt) > 60 else first_prompt or 'Untitled'

            # Fallback: derive created from first message timestamp
            if not created and messages:
                created = messages[0].get('timestamp', '')

            out_name = f"{project_name}__{session_id}.html"
            out_path = output / out_name

            html = session_html(messages, summary, project_name, created, session_id)
            out_path.write_text(html, encoding='utf-8')

            if project_name not in sessions_by_project:
                sessions_by_project[project_name] = []
            sessions_by_project[project_name].append({
                'summary': summary,
                'firstPrompt': first_prompt,
                'created': created,
                'href': out_name,
            })

            total += 1
            print(f"  ✓ {summary[:60]}")

    # Write index
    idx_path = output / 'index.html'
    idx_path.write_text(index_html(sessions_by_project), encoding='utf-8')

    print(f"\n✨ Done! {total} sessions exported to {output}")
    print(f"   Open: {idx_path}")


if __name__ == '__main__':
    main()
