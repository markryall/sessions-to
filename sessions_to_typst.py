#!/usr/bin/env python3
"""Convert Claude Code session JSONL files to Typst documents (and optionally PDF)."""

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
OUTPUT_DIR = Path(__file__).parent / "tmp" / "typst"

PREAMBLE = r"""
#set page(
  paper: "a4",
  fill: rgb("#0a0010"),
  margin: (x: 1.8cm, y: 2cm),
)
#set text(
  fill: rgb("#f0d6f5"),
  size: 10pt,
  font: ("New Computer Modern",),
)
#set par(leading: 0.75em, justify: false)
#set list(marker: text(fill: rgb("#ff69b4"))[✦])
#set enum(numbering: n => text(fill: rgb("#ff69b4"))[#n.])

#let pink       = rgb("#ff69b4")
#let purple     = rgb("#8a2be2")
#let lavender   = rgb("#da8fff")
#let user-bg    = rgb("#2d003d")
#let asst-bg    = rgb("#0d0018")
#let muted      = rgb("#9966aa")

#let user-msg(body) = align(right,
  block(
    fill: user-bg,
    inset: (x: 0.9em, y: 0.7em),
    radius: (top-left: 10pt, bottom-left: 10pt, bottom-right: 10pt, top-right: 2pt),
    width: 84%,
    stroke: 0.5pt + pink.transparentize(55%),
  )[
    #text(size: 7pt, fill: pink, weight: "bold")[YOU ✦]
    #v(0.35em)
    #body
  ]
)

#let asst-msg(body) = align(left,
  block(
    fill: asst-bg,
    inset: (x: 0.9em, y: 0.7em),
    radius: (top-right: 10pt, bottom-left: 10pt, bottom-right: 10pt, top-left: 2pt),
    width: 84%,
    stroke: 0.5pt + purple.transparentize(55%),
  )[
    #text(size: 7pt, fill: lavender, weight: "bold")[CLAUDIA 💜]
    #v(0.35em)
    #body
  ]
)


// Datestamps are real headings so they appear in the outline
#show heading.where(level: 1): it => align(center,
  text(size: 7.5pt, fill: muted.transparentize(40%))[✦ #it.body ✦]
)
// Sub-headings from message content
#show heading.where(level: 2): it => text(size: 12pt, fill: pink, weight: "bold")[#it.body]
#show heading.where(level: 3): it => text(size: 11pt, fill: lavender, weight: "bold")[#it.body]
#show heading.where(level: 4): it => text(size: 10pt, fill: lavender, weight: "semibold")[#it.body]
"""


# ── Typst text escaping ────────────────────────────────────────────────────────

def typst_escape(s):
    """Escape plain text for Typst content mode."""
    s = s.replace('\\', '\\\\')
    s = s.replace('#',  '\\#')
    s = s.replace('@',  '\\@')
    s = s.replace('<',  '\\<')
    s = s.replace('$',  '\\$')
    s = s.replace('~',  '\\~')
    s = s.replace('*',  '\\*')
    s = s.replace('_',  '\\_')
    return s


def apply_inline(text):
    """Convert inline markdown to Typst markup, safely escaping all plain text."""
    saved = []

    def save(s):
        saved.append(s)
        return f'\x00S{len(saved) - 1}\x00'

    # Inline code — content is treated as raw (no escaping inside backticks)
    text = re.sub(r'`([^`\n]+)`', lambda m: save(f'`{m.group(1)}`'), text)

    # Bold-italic → *_..._*
    text = re.sub(r'\*\*\*(.+?)\*\*\*',
                  lambda m: save(f'*_{typst_escape(m.group(1))}_*'), text)
    # Bold → *...*
    text = re.sub(r'\*\*(.+?)\*\*',
                  lambda m: save(f'*{typst_escape(m.group(1))}*'), text)
    # Italic → _..._
    text = re.sub(r'\*(.+?)\*',
                  lambda m: save(f'_{typst_escape(m.group(1))}_'), text)

    # Links → #link("url")[label]
    text = re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        lambda m: save(f'#link("{m.group(2)}")[{typst_escape(m.group(1))}]'),
        text,
    )

    # Escape remaining plain text
    text = typst_escape(text)

    # Restore saved Typst markup
    for i, s in enumerate(saved):
        text = text.replace(f'\x00S{i}\x00', s)

    return text


def markdown_to_typst(text):
    """Convert a markdown string to a Typst content string."""
    # ── Step 1: extract fenced code blocks ──
    code_blocks = []

    def save_code(m):
        lang = m.group(1) or ''
        code = m.group(2).rstrip('\n')
        # Typst raw block syntax
        block = f'```{lang}\n{code}\n```'
        code_blocks.append(block)
        return f'\x00CODE{len(code_blocks) - 1}\x00'

    text = re.sub(r'```(\w*)\n?(.*?)```', save_code, text, flags=re.DOTALL)

    # ── Step 2: paragraph-level processing ──
    parts = []
    paragraphs = re.split(r'\n{2,}', text.strip())

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Standalone code block placeholder
        m = re.fullmatch(r'\x00CODE(\d+)\x00', para)
        if m:
            parts.append(code_blocks[int(m.group(1))])
            continue

        # Heading — shift up by 1 (level 1 reserved for datestamps in TOC)
        m = re.match(r'^(#{1,4}) (.+)$', para)
        if m:
            level = min(len(m.group(1)) + 1, 4)
            parts.append('=' * level + ' ' + apply_inline(m.group(2)))
            continue

        # Horizontal rule
        if re.match(r'^---+$', para):
            parts.append('#line(length: 100%, stroke: 0.5pt + pink)')
            continue

        # Blockquote
        if para.startswith('> '):
            inner = apply_inline(para[2:])
            parts.append(
                f'#block(inset: (left: 0.8em), stroke: (left: 2pt + pink))'
                f'[#text(fill: muted)[_{inner}_]]'
            )
            continue

        # Unordered list
        lines = para.split('\n')
        if all(re.match(r'^[-*] ', l.strip()) for l in lines if l.strip()):
            items = []
            for l in lines:
                m2 = re.match(r'^[-*] (.+)$', l.strip())
                if m2:
                    items.append(f'- {apply_inline(m2.group(1))}')
            if items:
                parts.append('\n'.join(items))
                continue

        # Ordered list
        if all(re.match(r'^\d+\. ', l.strip()) for l in lines if l.strip()):
            items = []
            for l in lines:
                m2 = re.match(r'^\d+\. (.+)$', l.strip())
                if m2:
                    items.append(f'+ {apply_inline(m2.group(1))}')
            if items:
                parts.append('\n'.join(items))
                continue

        # Mixed paragraph — handle inline code-block placeholders mid-para
        para_parts = []
        pending_lines = []

        for line in lines:
            m2 = re.fullmatch(r'\x00CODE(\d+)\x00', line.strip())
            if m2:
                if pending_lines:
                    para_parts.append(apply_inline(' '.join(pending_lines)))
                    pending_lines = []
                para_parts.append(code_blocks[int(m2.group(1))])
            else:
                pending_lines.append(line)

        if pending_lines:
            para_parts.append(apply_inline(' '.join(pending_lines)))

        parts.append('\n\n'.join(para_parts))

    return '\n\n'.join(parts)


# ── Session parsing (shared with HTML script) ──────────────────────────────────

def parse_session(jsonl_path):
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

                if obj.get('type') not in ('user', 'assistant'):
                    continue

                msg = obj.get('message', {})
                role = msg.get('role')
                if role not in ('user', 'assistant'):
                    continue

                content = msg.get('content', '')

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

                messages.append({
                    'role': role,
                    'content': content,
                    'timestamp': obj.get('timestamp'),
                })
    except Exception as e:
        print(f'  Warning: {jsonl_path.name}: {e}', file=sys.stderr)
    return messages


def render_content_typst(content):
    """Render message content to a Typst string."""
    if isinstance(content, str):
        return markdown_to_typst(content)

    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(markdown_to_typst(block))
            continue

        btype = block.get('type', '')

        if btype == 'text':
            parts.append(markdown_to_typst(block.get('text', '')))

        elif btype == 'thinking':
            pass  # skip

        elif btype == 'tool_use':
            pass  # skip — not interactive in PDF

        elif btype == 'tool_result':
            pass  # skip tool results — too noisy in print

    return '\n\n'.join(p for p in parts if p.strip())


def format_ts(ts_str):
    if not ts_str:
        return ''
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime('%d %b %Y, %H:%M')
    except Exception:
        return ts_str


# ── Document generation ────────────────────────────────────────────────────────

def session_typst(messages, title, project_name, created, session_id):
    title_escaped = typst_escape(title)
    project_escaped = typst_escape(project_name.replace('-', '/').replace('Users/markryall/', '~/'))
    created_fmt = typst_escape(format_ts(created))
    sid_short = typst_escape(session_id[:8])

    body_parts = [PREAMBLE]

    # Title block + outline
    body_parts.append(f'''
#align(center, block(
  fill: rgb("#1a002e"),
  inset: (x: 1.5em, y: 1.2em),
  radius: 8pt,
  width: 100%,
  stroke: (bottom: 1pt + pink),
)[
  #text(size: 18pt, fill: pink, weight: "bold")[{title_escaped} ✦]
  \\
  #v(0.3em)
  #text(size: 8.5pt, fill: muted)[{project_escaped} • {created_fmt} • {sid_short}]
])
#v(1em)
#outline(title: none, depth: 1)
#v(1.2em)
''')

    last_date = None

    for msg in messages:
        ts = msg.get('timestamp', '')
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                date_str = dt.strftime('%d %b %Y')
                if date_str != last_date:
                    body_parts.append(f'= {typst_escape(date_str)}\n#v(0.5em)')
                    last_date = date_str
            except Exception:
                pass

        rendered = render_content_typst(msg['content'])
        if not rendered.strip():
            continue

        if msg['role'] == 'user':
            body_parts.append(f'#user-msg[\n{rendered}\n]\n#v(0.6em)')
        else:
            body_parts.append(f'#asst-msg[\n{rendered}\n]\n#v(0.6em)')

    return '\n'.join(body_parts)


def build_global_index(base_dir):
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
    compile_pdf = '--pdf' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    output = Path(args[0]) if args else OUTPUT_DIR
    output.mkdir(parents=True, exist_ok=True)

    index_map = build_global_index(CLAUDE_DIR)
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
            created = meta.get('created', '')
            first_prompt = meta.get('firstPrompt', '')

            if not first_prompt:
                for m in messages:
                    if m['role'] == 'user':
                        c = m['content']
                        if isinstance(c, str):
                            first_prompt = c.strip()
                        elif isinstance(c, list):
                            for b in c:
                                if isinstance(b, str):
                                    first_prompt = b.strip(); break
                                if isinstance(b, dict) and b.get('type') == 'text':
                                    first_prompt = b.get('text', '').strip(); break
                        if first_prompt:
                            break

            if not summary:
                summary = (first_prompt[:60] + '…') if len(first_prompt) > 60 else first_prompt or 'Untitled'

            if not created and messages:
                created = messages[0].get('timestamp', '')

            stem = f'{project_name}__{session_id}'
            typ_path = output / f'{stem}.typ'
            doc = session_typst(messages, summary, project_name, created, session_id)
            typ_path.write_text(doc, encoding='utf-8')

            if compile_pdf:
                result = subprocess.run(
                    ['typst', 'compile', str(typ_path), str(output / f'{stem}.pdf')],
                    capture_output=True, text=True
                )
                status = '✓' if result.returncode == 0 else '✗'
                if result.returncode != 0:
                    print(f'  {status} {summary[:50]} — {result.stderr.strip()[:80]}')
                else:
                    print(f'  {status} {summary[:60]}')
            else:
                print(f'  ✓ {summary[:60]}')

            total += 1

    action = 'compiled to PDF' if compile_pdf else 'exported as .typ'
    print(f'\n✨ Done! {total} sessions {action} → {output}')
    if not compile_pdf:
        print('   Tip: pass --pdf to compile all sessions to PDF')


if __name__ == '__main__':
    main()
