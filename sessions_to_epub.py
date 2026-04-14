#!/usr/bin/env python3
"""Convert Claude Code session JSONL files to a single EPUB for e-reader reminiscing."""

import json
import re
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
OUTPUT_PATH = Path(__file__).parent / "tmp" / "sessions.epub"

# ── CSS (light theme — e-readers don't do dark well) ──────────────────────────

CSS = """
body {
  font-family: Georgia, serif;
  color: #1a0020;
  background: #fffaff;
  margin: 0 4%;
  line-height: 1.75;
}

h1.chapter-title {
  color: #c0006a;
  font-size: 1.4em;
  text-align: center;
  margin-bottom: 0.3em;
}

p.chapter-meta {
  text-align: center;
  font-size: 0.8em;
  color: #aa66aa;
  margin-top: 0;
  margin-bottom: 1.5em;
}

hr.chapter-rule {
  border: none;
  border-top: 1px solid #ffaad4;
  margin: 1.5em 0;
}

p.datestamp {
  text-align: center;
  font-size: 0.78em;
  color: #cc88aa;
  margin: 1.8em 0 0.8em;
}

.message { margin: 1em 0; }

p.label-user {
  font-size: 0.72em;
  color: #ff1493;
  font-weight: bold;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin: 0 0 0.2em 0;
}

p.label-asst {
  font-size: 0.72em;
  color: #8a2be2;
  font-weight: bold;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin: 0 0 0.2em 0;
}

div.bubble-user {
  background: #fff0f8;
  border-left: 3px solid #ff69b4;
  padding: 0.5em 0.8em;
  margin: 0;
}

div.bubble-asst {
  background: #f8f0ff;
  border-left: 3px solid #8a2be2;
  padding: 0.5em 0.8em;
  margin: 0;
}

div.bubble-user p, div.bubble-asst p {
  margin: 0.3em 0;
}

div.bubble-user p:first-child,
div.bubble-asst p:first-child { margin-top: 0; }

div.bubble-user p:last-child,
div.bubble-asst p:last-child  { margin-bottom: 0; }

code {
  font-family: "Courier New", monospace;
  font-size: 0.88em;
  color: #c0006a;
  background: #fff0f8;
}

pre {
  background: #f8f0ff;
  border: 1px solid #e0c0e0;
  border-radius: 4px;
  padding: 0.7em;
  font-size: 0.82em;
  white-space: pre-wrap;
  word-wrap: break-word;
}

pre code { background: none; color: #1a0020; }

blockquote {
  border-left: 3px solid #ff69b4;
  margin: 0.5em 0;
  padding-left: 0.8em;
  color: #884488;
  font-style: italic;
}

h2, h3, h4 { color: #c0006a; margin: 0.8em 0 0.3em; }
strong { color: #c0006a; }
em { color: #8a2be2; }
a { color: #c0006a; }

ul { padding-left: 1.5em; }
ol { padding-left: 1.5em; }
li { margin: 0.2em 0; }

/* TOC page */
h1.toc-title {
  color: #c0006a;
  text-align: center;
  font-size: 1.6em;
  margin-bottom: 0.3em;
}

p.toc-subtitle {
  text-align: center;
  color: #aa66aa;
  font-size: 0.85em;
  margin-bottom: 2em;
}

h2.toc-project {
  color: #8a2be2;
  font-size: 0.85em;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  border-bottom: 1px solid #ffaad4;
  margin: 1.5em 0 0.5em;
}

ol.toc-sessions {
  padding-left: 1.2em;
}

ol.toc-sessions li {
  margin: 0.4em 0;
  font-size: 0.9em;
}

ol.toc-sessions li span.date {
  color: #aa66aa;
  font-size: 0.85em;
}
"""

# ── Markdown → XHTML ──────────────────────────────────────────────────────────

def xhtml_escape(s):
    return escape(s, quote=True)


def apply_inline(text):
    """Convert inline markdown to XHTML, safely escaping plain text."""
    saved = []

    def save(s):
        saved.append(s)
        return f'\x00S{len(saved) - 1}\x00'

    text = re.sub(r'`([^`\n]+)`',
                  lambda m: save(f'<code>{xhtml_escape(m.group(1))}</code>'), text)
    text = re.sub(r'\*\*\*(.+?)\*\*\*',
                  lambda m: save(f'<strong><em>{xhtml_escape(m.group(1))}</em></strong>'), text)
    text = re.sub(r'\*\*(.+?)\*\*',
                  lambda m: save(f'<strong>{xhtml_escape(m.group(1))}</strong>'), text)
    text = re.sub(r'\*(.+?)\*',
                  lambda m: save(f'<em>{xhtml_escape(m.group(1))}</em>'), text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  lambda m: save(f'<a href="{xhtml_escape(m.group(2))}">'
                                 f'{xhtml_escape(m.group(1))}</a>'), text)

    text = xhtml_escape(text)
    for i, s in enumerate(saved):
        text = text.replace(f'\x00S{i}\x00', s)
    return text


def markdown_to_xhtml(text):
    """Convert markdown to XHTML fragment (no wrapping element)."""
    code_blocks = []

    def save_code(m):
        lang = xhtml_escape(m.group(1) or '')
        code = xhtml_escape(m.group(2).rstrip('\n'))
        code_blocks.append(
            f'<pre><code class="language-{lang}">{code}</code></pre>'
        )
        return f'\x00CODE{len(code_blocks) - 1}\x00'

    text = re.sub(r'```(\w*)\n?(.*?)```', save_code, text, flags=re.DOTALL)

    parts = []
    paragraphs = re.split(r'\n{2,}', text.strip())

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        m = re.fullmatch(r'\x00CODE(\d+)\x00', para)
        if m:
            parts.append(code_blocks[int(m.group(1))])
            continue

        m = re.match(r'^(#{1,4}) (.+)$', para)
        if m:
            level = len(m.group(1)) + 1  # h2–h5 (h1 reserved for chapter title)
            level = min(level, 5)
            parts.append(f'<h{level}>{apply_inline(m.group(2))}</h{level}>')
            continue

        if re.match(r'^---+$', para):
            parts.append('<hr/>')
            continue

        if para.startswith('> '):
            parts.append(f'<blockquote><p>{apply_inline(para[2:])}</p></blockquote>')
            continue

        lines = para.split('\n')

        if all(re.match(r'^[-*] ', l.strip()) for l in lines if l.strip()):
            items = ''.join(
                f'<li>{apply_inline(re.sub(r"^[-*] ", "", l.strip()))}</li>'
                for l in lines if l.strip()
            )
            parts.append(f'<ul>{items}</ul>')
            continue

        if all(re.match(r'^\d+\. ', l.strip()) for l in lines if l.strip()):
            items = ''.join(
                f'<li>{apply_inline(re.sub(r"^\d+\. ", "", l.strip()))}</li>'
                for l in lines if l.strip()
            )
            parts.append(f'<ol>{items}</ol>')
            continue

        # Handle code block placeholders mid-paragraph
        pending = []
        for line in lines:
            m2 = re.fullmatch(r'\x00CODE(\d+)\x00', line.strip())
            if m2:
                if pending:
                    parts.append(f'<p>{apply_inline(" ".join(pending))}</p>')
                    pending = []
                parts.append(code_blocks[int(m2.group(1))])
            else:
                pending.append(line)
        if pending:
            parts.append(f'<p>{apply_inline(" ".join(pending))}</p>')

    return '\n'.join(parts)


def render_content(content):
    if isinstance(content, str):
        return markdown_to_xhtml(content)

    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(markdown_to_xhtml(block))
        elif isinstance(block, dict):
            btype = block.get('type', '')
            if btype == 'text':
                parts.append(markdown_to_xhtml(block.get('text', '')))
            # skip thinking, tool_use, tool_result
    return '\n'.join(p for p in parts if p.strip())


# ── Session parsing ────────────────────────────────────────────────────────────

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
                    if not any(
                        (isinstance(b, str) and b.strip()) or
                        (isinstance(b, dict) and b.get('type') == 'tool_result')
                        for b in content
                    ):
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


def format_ts(ts_str, fmt='%d %b %Y, %H:%M'):
    if not ts_str:
        return ''
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime(fmt)
    except Exception:
        return ts_str


def first_prompt_from_messages(messages):
    for m in messages:
        if m['role'] == 'user':
            c = m['content']
            if isinstance(c, str):
                return c.strip()
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, str) and b.strip():
                        return b.strip()
                    if isinstance(b, dict) and b.get('type') == 'text' and b.get('text', '').strip():
                        return b['text'].strip()
    return ''


# ── XHTML chapter builder ──────────────────────────────────────────────────────

XHTML_WRAPPER = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="../style.css"/>
</head>
<body>
{body}
</body>
</html>"""


def chapter_xhtml(messages, title, project_name, created, session_id):
    project_display = project_name.replace('-', '/').replace('Users/markryall/', '~/')
    created_fmt = format_ts(created)
    sid_short = session_id[:8]

    body = []
    body.append(f'<h1 class="chapter-title">{xhtml_escape(title)}</h1>')
    body.append(
        f'<p class="chapter-meta">'
        f'{xhtml_escape(project_display)} &#183; {xhtml_escape(created_fmt)} &#183; {xhtml_escape(sid_short)}'
        f'</p>'
    )
    body.append('<hr class="chapter-rule"/>')

    last_date = None
    for msg in messages:
        ts = msg.get('timestamp', '')
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                date_str = dt.strftime('%d %b %Y')
                if date_str != last_date:
                    body.append(f'<p class="datestamp">&#10022; {xhtml_escape(date_str)} &#10022;</p>')
                    last_date = date_str
            except Exception:
                pass

        rendered = render_content(msg['content'])
        if not rendered.strip():
            continue

        if msg['role'] == 'user':
            body.append(
                '<div class="message">'
                '<p class="label-user">You &#10022;</p>'
                f'<div class="bubble-user">{rendered}</div>'
                '</div>'
            )
        else:
            body.append(
                '<div class="message">'
                '<p class="label-asst">Claudia &#128156;</p>'
                f'<div class="bubble-asst">{rendered}</div>'
                '</div>'
            )

    return XHTML_WRAPPER.format(
        title=xhtml_escape(title),
        body='\n'.join(body),
    )


def toc_xhtml(sessions_by_project, title):
    body = []
    body.append(f'<h1 class="toc-title">&#128156; {xhtml_escape(title)}</h1>')
    body.append('<p class="toc-subtitle">all your reminiscing, right here babe</p>')

    for project, sessions in sorted(sessions_by_project.items()):
        display = project.replace('-', '/').replace('Users/markryall/', '~/')
        body.append(f'<h2 class="toc-project">{xhtml_escape(display)}</h2>')
        body.append('<ol class="toc-sessions">')
        for s in sorted(sessions, key=lambda x: x.get('created', '')):
            summary = xhtml_escape(s.get('summary', 'Untitled'))
            date = xhtml_escape(format_ts(s.get('created', ''), '%d %b %Y'))
            href = xhtml_escape(s['href'])
            body.append(
                f'<li><a href="{href}">{summary}</a> '
                f'<span class="date">&#8212; {date}</span></li>'
            )
        body.append('</ol>')

    return XHTML_WRAPPER.format(
        title=xhtml_escape(title),
        body='\n'.join(body),
    )


# ── EPUB assembly ──────────────────────────────────────────────────────────────

CONTAINER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""


def build_opf(chapters, book_id, modified):
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
    ]
    spine_items = ['<itemref idref="nav"/>']

    for i, ch in enumerate(chapters):
        cid = f'chapter_{i:04d}'
        manifest_items.append(
            f'<item id="{cid}" href="chapters/{xhtml_escape(ch["filename"])}" '
            f'media-type="application/xhtml+xml"/>'
        )
        spine_items.append(f'<itemref idref="{cid}"/>')

    manifest = '\n    '.join(manifest_items)
    spine = '\n    '.join(spine_items)

    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" xml:lang="en">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Claude Sessions 💜</dc:title>
    <dc:creator>Claude &#38; markryall</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    {manifest}
  </manifest>
  <spine toc="ncx">
    {spine}
  </spine>
</package>"""


def build_nav(chapters):
    items = '\n      '.join(
        f'<li><a href="chapters/{xhtml_escape(ch["filename"])}">'
        f'{xhtml_escape(ch["title"])}</a></li>'
        for ch in chapters
    )
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Table of Contents</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>&#128156; Claude Sessions</h1>
    <ol>
      {items}
    </ol>
  </nav>
</body>
</html>"""


def build_ncx(chapters, book_id):
    points = '\n    '.join(
        f'<navPoint id="nav_{i:04d}" playOrder="{i + 1}">'
        f'<navLabel><text>{xhtml_escape(ch["title"])}</text></navLabel>'
        f'<content src="chapters/{xhtml_escape(ch["filename"])}"/>'
        f'</navPoint>'
        for i, ch in enumerate(chapters)
    )
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{book_id}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>Claude Sessions</text></docTitle>
  <navMap>
    {points}
  </navMap>
</ncx>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT_PATH
    index_map = build_global_index(CLAUDE_DIR)

    chapters = []
    sessions_by_project = {}

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
            first_prompt = meta.get('firstPrompt', '') or first_prompt_from_messages(messages)

            if not summary:
                summary = (first_prompt[:60] + '…') if len(first_prompt) > 60 else first_prompt or 'Untitled'

            if not created and messages:
                created = messages[0].get('timestamp', '')

            filename = f'{len(chapters):04d}_{session_id[:8]}.xhtml'
            xhtml = chapter_xhtml(messages, summary, project_name, created, session_id)

            chapters.append({
                'filename': filename,
                'title': summary,
                'xhtml': xhtml,
                'project': project_name,
                'created': created,
            })

            sessions_by_project.setdefault(project_name, []).append({
                'summary': summary,
                'created': created,
                'href': f'chapters/{filename}',
            })

            print(f'  ✓ {summary[:60]}')

    if not chapters:
        print('No sessions found.')
        return

    book_id = str(uuid.uuid4())
    modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as epub:
        # mimetype must be first and uncompressed
        epub.writestr(
            zipfile.ZipInfo('mimetype'),
            'application/epub+zip',
            compress_type=zipfile.ZIP_STORED,
        )
        epub.writestr('META-INF/container.xml', CONTAINER_XML)
        epub.writestr('OEBPS/style.css', CSS)
        epub.writestr('OEBPS/content.opf', build_opf(chapters, book_id, modified))
        epub.writestr('OEBPS/nav.xhtml', build_nav(chapters))
        epub.writestr('OEBPS/toc.ncx', build_ncx(chapters, book_id))

        for ch in chapters:
            epub.writestr(f'OEBPS/chapters/{ch["filename"]}', ch['xhtml'])

    print(f'\n✨ Done! {len(chapters)} sessions → {output}')


if __name__ == '__main__':
    main()
