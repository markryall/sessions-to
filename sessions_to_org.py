#!/usr/bin/env python3
"""Convert Claude Code session JSONL files to Org mode files for Spacemacs/Emacs."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
OUTPUT_DIR = Path.home() / "Documents" / "chats-with-claudia"


# ── Markdown → Org mode ───────────────────────────────────────────────────────

def org_escape(text):
    """Org mode doesn't need heavy escaping — just return as-is for plain text."""
    return text


def apply_inline_org(text):
    """Convert inline markdown constructs to org markup.

    Order matters: handle bold-italic (***) before bold (**) before italic (*).
    Inline code is handled before bold/italic to avoid stomping backtick spans.
    """
    saved = []

    def save(s):
        saved.append(s)
        return f'\x00S{len(saved) - 1}\x00'

    # Inline code: `foo` → =foo=
    text = re.sub(r'`([^`\n]+)`', lambda m: save(f'={m.group(1)}='), text)

    # Bold-italic: ***text*** → */text/*  (org: bold wrapping italic)
    text = re.sub(r'\*\*\*(.+?)\*\*\*', lambda m: save(f'*/{m.group(1)}/*'), text)

    # Bold: **text** → *text*
    text = re.sub(r'\*\*(.+?)\*\*', lambda m: save(f'*{m.group(1)}*'), text)

    # Italic: *text* → /text/
    # Use a negative lookbehind/lookahead to avoid matching list markers
    text = re.sub(r'(?<!\*)\*(?!\*|\s)(.+?)(?<!\s)\*(?!\*)',
                  lambda m: save(f'/{m.group(1)}/'), text)

    # Links: [text](url) → [[url][text]]
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  lambda m: save(f'[[{m.group(2)}][{m.group(1)}]]'), text)

    for i, s in enumerate(saved):
        text = text.replace(f'\x00S{i}\x00', s)
    return text


def markdown_to_org(text, heading_offset=3):
    """Convert a markdown text block to org mode markup.

    heading_offset: level to use for top-level (#) headings. Defaults to 3
    because levels 1 and 2 are taken by session/message headings.
    """
    if not text:
        return ''

    # ── Extract fenced code blocks first so we don't mangle their contents ──
    code_blocks = []

    def save_code(m):
        lang = (m.group(1) or '').strip()
        body = m.group(2).rstrip('\n')
        if lang:
            block = f'#+BEGIN_SRC {lang}\n{body}\n#+END_SRC'
        else:
            block = f'#+BEGIN_SRC\n{body}\n#+END_SRC'
        code_blocks.append(block)
        return f'\x00CODE{len(code_blocks) - 1}\x00'

    text = re.sub(r'```(\w*)\n?(.*?)```', save_code, text, flags=re.DOTALL)

    # ── Process paragraph by paragraph ──
    paragraphs = re.split(r'\n{2,}', text.strip())
    parts = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Lone code block placeholder
        m = re.fullmatch(r'\x00CODE(\d+)\x00', para)
        if m:
            parts.append(code_blocks[int(m.group(1))])
            continue

        # ATX headings: # → level heading_offset, ## → heading_offset+1, etc.
        m = re.match(r'^(#{1,6}) (.+)$', para)
        if m:
            level = min(len(m.group(1)) + heading_offset - 1, 8)
            stars = '*' * level
            parts.append(f'{stars} {apply_inline_org(m.group(2))}')
            continue

        # Horizontal rule
        if re.match(r'^---+$', para):
            parts.append('-----')
            continue

        # Blockquote
        if para.startswith('> '):
            inner = para[2:]
            parts.append(f'#+BEGIN_QUOTE\n{apply_inline_org(inner)}\n#+END_QUOTE')
            continue

        lines = para.split('\n')

        # Unordered list block
        if all(re.match(r'^[-*+] ', l.strip()) or not l.strip() for l in lines):
            list_items = []
            for l in lines:
                l = l.strip()
                if not l:
                    continue
                item_text = re.sub(r'^[-*+] ', '', l)
                # Check for any code block placeholders inside list items
                item_text = _restore_code_inline(item_text, code_blocks)
                list_items.append(f'- {apply_inline_org(item_text)}')
            parts.append('\n'.join(list_items))
            continue

        # Ordered list block
        if all(re.match(r'^\d+\. ', l.strip()) or not l.strip() for l in lines):
            list_items = []
            for l in lines:
                l = l.strip()
                if not l:
                    continue
                item_text = re.sub(r'^\d+\. ', '', l)
                item_text = _restore_code_inline(item_text, code_blocks)
                list_items.append(f'- {apply_inline_org(item_text)}')
            parts.append('\n'.join(list_items))
            continue

        # Mixed paragraph — may contain inline code placeholders and code blocks
        pending_lines = []
        for line in lines:
            cm = re.fullmatch(r'\x00CODE(\d+)\x00', line.strip())
            if cm:
                if pending_lines:
                    joined = ' '.join(pending_lines)
                    parts.append(apply_inline_org(joined))
                    pending_lines = []
                parts.append(code_blocks[int(cm.group(1))])
            else:
                pending_lines.append(line)
        if pending_lines:
            joined = '\n'.join(pending_lines)
            parts.append(apply_inline_org(joined))

    result = '\n\n'.join(parts)

    # Final pass: restore any stray code block placeholders
    for i, block in enumerate(code_blocks):
        result = result.replace(f'\x00CODE{i}\x00', block)

    return result


def _restore_code_inline(text, code_blocks):
    """Replace code block placeholders inside inline contexts with literal text."""
    def replacer(m):
        idx = int(m.group(1))
        # Flatten to inline src or just the content — use verbatim org markup
        block = code_blocks[idx]
        # Extract inner content from #+BEGIN_SRC…#+END_SRC
        inner = re.sub(r'#\+BEGIN_SRC[^\n]*\n', '', block)
        inner = re.sub(r'\n#\+END_SRC', '', inner)
        return f'~{inner.strip()}~'
    return re.sub(r'\x00CODE(\d+)\x00', replacer, text)


# ── Content rendering ─────────────────────────────────────────────────────────

def render_content_org(content):
    """Render message content (string or list of blocks) to org markup.

    Skips tool_use, tool_result, and thinking blocks.
    """
    if isinstance(content, str):
        return markdown_to_org(content)

    parts = []
    for block in content:
        if isinstance(block, str):
            rendered = markdown_to_org(block)
            if rendered.strip():
                parts.append(rendered)
            continue

        if not isinstance(block, dict):
            continue

        btype = block.get('type', '')

        if btype == 'text':
            rendered = markdown_to_org(block.get('text', ''))
            if rendered.strip():
                parts.append(rendered)

        # Skip: thinking, tool_use, tool_result

    return '\n\n'.join(p for p in parts if p.strip())


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


def first_prompt_from_messages(messages):
    """Extract the first user text from parsed messages."""
    for m in messages:
        if m['role'] != 'user':
            continue
        c = m['content']
        if isinstance(c, str) and c.strip():
            return c.strip()
        if isinstance(c, list):
            for b in c:
                if isinstance(b, str) and b.strip():
                    return b.strip()
                if isinstance(b, dict) and b.get('type') == 'text' and b.get('text', '').strip():
                    return b['text'].strip()
    return ''


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def format_ts_human(ts_str):
    """Human-readable timestamp for display."""
    if not ts_str:
        return ''
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %a %H:%M')
    except Exception:
        return ts_str


def format_ts_org_active(ts_str):
    """Org active timestamp: <YYYY-MM-DD Day HH:MM> — shows in agenda."""
    if not ts_str:
        return ''
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime('<%Y-%m-%d %a %H:%M>')
    except Exception:
        return f'<{ts_str}>'


def format_ts_org_inactive(ts_str):
    """Org inactive timestamp: [YYYY-MM-DD Day HH:MM]"""
    if not ts_str:
        return ''
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime('[%Y-%m-%d %a %H:%M]')
    except Exception:
        return f'[{ts_str}]'


def format_ts_org_date(ts_str):
    """Just the date portion for PROPERTIES drawers: YYYY-MM-DD."""
    if not ts_str:
        return ''
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return ts_str


def project_display_name(project_dir_name):
    """Convert a filesystem-encoded project dir name to a human-readable path."""
    name = project_dir_name.lstrip('-').replace('-', '/')
    name = re.sub(r'^Users/[^/]+/', '~/', name)
    return name


# ── Org file builder ──────────────────────────────────────────────────────────

def build_org_file(project_dir_name, sessions):
    """Build a complete .org file string for all sessions in a project.

    sessions: list of dicts with keys summary, session_id, created, messages, project
    """
    display = project_display_name(project_dir_name)
    now = datetime.now().strftime('%Y-%m-%d %a')

    lines = []

    # File-level header
    lines.append(f'#+TITLE: Claude Sessions - {display}')
    lines.append(f'#+AUTHOR: Mark')
    lines.append(f'#+DATE: [{now}]')
    lines.append('#+OPTIONS: toc:2 num:nil ^:nil')
    lines.append('#+STARTUP: overview')
    lines.append('')

    if not sessions:
        lines.append('# No sessions found for this project.')
        return '\n'.join(lines)

    for session in sessions:
        summary = session['summary'] or 'Untitled Session'
        session_id = session['session_id']
        created = session['created']
        messages = session['messages']

        # ── Level-1 heading: session ──
        lines.append(f'* {summary}')

        # PROPERTIES drawer
        lines.append(':PROPERTIES:')
        lines.append(f':SESSION_ID: {session_id}')
        lines.append(f':PROJECT:   {display}')
        lines.append(':END:')
        if created:
            lines.append(f'SCHEDULED: {format_ts_org_active(created)}')
        lines.append('')

        if not messages:
            lines.append('  /No messages in this session./')
            lines.append('')
            continue

        for msg in messages:
            role = msg['role']
            ts = msg.get('timestamp', '')
            org_ts = format_ts_org_inactive(ts) if ts else ''

            if role == 'user':
                heading = '** [you]'
            else:
                heading = '** [claudia]'

            lines.append(heading)

            if org_ts:
                lines.append(org_ts)
                lines.append('')

            rendered = render_content_org(msg['content'])

            if not rendered.strip():
                # Skip empty messages entirely
                # Remove the heading we just added
                # Pop back to before the heading
                while lines and lines[-1] == '':
                    lines.pop()
                if org_ts and lines and lines[-1] == org_ts:
                    lines.pop()
                    if lines and lines[-1] == '':
                        lines.pop()
                if lines and lines[-1] == heading:
                    lines.pop()
                continue

            lines.append(rendered)
            lines.append('')

        lines.append('')

    return '\n'.join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def build_index_org(all_projects, output_dir):
    """Build index.org linking to all project files and their sessions."""
    now = datetime.now().strftime('%Y-%m-%d %a')
    lines = []
    lines.append('#+TITLE: Claude Sessions Index')
    lines.append('#+AUTHOR: Mark')
    lines.append(f'#+DATE: [{now}]')
    lines.append('#+OPTIONS: toc:1 num:nil ^:nil')
    lines.append('#+STARTUP: overview')
    lines.append('')

    for project_name, sessions in all_projects:
        display = project_display_name(project_name)
        org_file = f'{project_name}.org'
        n = len(sessions)
        lines.append(f'* [[file:{org_file}][{display}]]  ({n} session{"s" if n != 1 else ""})')
        lines.append('')
        for session in sessions:
            summary = session['summary'] or 'Untitled Session'
            created = session.get('created', '')
            date_str = format_ts_org_date(created) if created else ''
            date_part = f'  {date_str}' if date_str else ''
            lines.append(f'** [[file:{org_file}::*{summary}][{summary}]]{date_part}')
        lines.append('')

    return '\n'.join(lines)


def main():
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if not CLAUDE_DIR.exists():
        print(f'Claude projects dir not found: {CLAUDE_DIR}', file=sys.stderr)
        sys.exit(1)

    index_map = build_global_index(CLAUDE_DIR)

    total_sessions = 0
    total_projects = 0
    all_projects = []

    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name
        jsonl_files = sorted(project_dir.glob('*.jsonl'))

        if not jsonl_files:
            continue

        sessions = []

        for jsonl_file in jsonl_files:
            session_id = jsonl_file.stem
            messages = parse_session(jsonl_file)

            if not messages:
                continue

            meta = index_map.get(session_id, {})
            summary = meta.get('summary', '')
            created = meta.get('created', '')
            first_prompt = meta.get('firstPrompt', '') or first_prompt_from_messages(messages)

            if not summary:
                summary = (first_prompt[:60] + '...') if len(first_prompt) > 60 else (first_prompt or 'Untitled')

            if not created and messages:
                created = messages[0].get('timestamp', '')

            sessions.append({
                'session_id': session_id,
                'summary': summary,
                'created': created,
                'messages': messages,
                'project': project_name,
            })

        if not sessions:
            continue

        # Sort sessions by creation date, oldest first
        sessions.sort(key=lambda s: s.get('created') or '')

        org_content = build_org_file(project_name, sessions)

        out_file = output_dir / f'{project_name}.org'
        out_file.write_text(org_content, encoding='utf-8')

        n = len(sessions)
        total_sessions += n
        total_projects += 1
        all_projects.append((project_name, sessions))
        print(f'✓ {project_name} ({n} session{"s" if n != 1 else ""})')

    index_content = build_index_org(all_projects, output_dir)
    index_file = output_dir / 'index.org'
    index_file.write_text(index_content, encoding='utf-8')
    print(f'✓ index.org')

    print()
    print(f'Done. {total_sessions} sessions across {total_projects} project{"s" if total_projects != 1 else ""} → {output_dir}')


if __name__ == '__main__':
    main()
