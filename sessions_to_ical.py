#!/usr/bin/env python3
"""Convert Claude Code sessions to iCalendar (.ics) — one event per session."""

import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
OUTPUT_PATH = Path(__file__).parent / "tmp" / "sessions.ics"


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


def extract_plain_text(content, max_chars=500):
    """Extract plain text from message content for use in description."""
    if isinstance(content, str):
        return content.strip()[:max_chars]
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block.strip())
        elif isinstance(block, dict) and block.get('type') == 'text':
            parts.append(block.get('text', '').strip())
    text = ' '.join(parts)
    return text[:max_chars] + ('…' if len(text) > max_chars else '')


def ical_escape(s):
    """Escape text for iCalendar property values."""
    s = s.replace('\\', '\\\\')
    s = s.replace(';', '\\;')
    s = s.replace(',', '\\,')
    s = s.replace('\n', '\\n')
    s = s.replace('\r', '')
    return s


def ical_fold(line):
    """Fold long iCalendar lines at 75 octets."""
    result = []
    # Work in bytes to respect the 75-octet limit
    encoded = line.encode('utf-8')
    while len(encoded) > 75:
        # Find safe split point (don't split multi-byte sequences)
        split = 75
        while split > 0 and (encoded[split] & 0xC0) == 0x80:
            split -= 1
        result.append(encoded[:split].decode('utf-8'))
        encoded = b' ' + encoded[split:]
    result.append(encoded.decode('utf-8'))
    return '\r\n'.join(result)


def ts_to_dt(ts_str):
    """Parse ISO timestamp to datetime."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except Exception:
        return None


def dt_to_ical(dt):
    """Format datetime as iCalendar UTC datetime string."""
    utc = dt.astimezone(timezone.utc)
    return utc.strftime('%Y%m%dT%H%M%SZ')


def count_messages(messages):
    user = sum(1 for m in messages if m['role'] == 'user')
    asst = sum(1 for m in messages if m['role'] == 'assistant')
    return user, asst


def build_description(messages, summary, project_name):
    """Build a multi-line event description."""
    lines = []
    project_display = project_name.replace('-', '/').replace('Users/markryall/', '~/')
    lines.append(f'Project: {project_display}')

    user_count, asst_count = count_messages(messages)
    lines.append(f'Messages: {user_count} from you, {asst_count} from Claudia')
    lines.append('')

    # First user message as opener
    first = first_prompt_from_messages(messages)
    if first:
        opener = first[:200].replace('\n', ' ')
        lines.append(f'You: {opener}')

    # Find first assistant text reply
    for m in messages:
        if m['role'] == 'assistant':
            text = extract_plain_text(m['content'], 200)
            # Strip markdown noise
            text = re.sub(r'\*+', '', text)
            text = re.sub(r'#+\s', '', text)
            text = text.replace('\n', ' ').strip()
            if text:
                lines.append(f'Claudia: {text}')
                break

    return '\\n'.join(ical_escape(l) for l in lines)


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT_PATH
    index_map = build_global_index(CLAUDE_DIR)

    now = datetime.now(timezone.utc)
    dtstamp = dt_to_ical(now)
    cal_uid = str(uuid.uuid4())

    events = []
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
            created = meta.get('created', '') or (messages[0].get('timestamp', '') if messages else '')
            modified_ts = meta.get('modified', '') or (messages[-1].get('timestamp', '') if messages else '')
            first_prompt = meta.get('firstPrompt', '') or first_prompt_from_messages(messages)

            if not summary:
                summary = (first_prompt[:60] + '…') if len(first_prompt) > 60 else first_prompt or 'Untitled'

            dtstart = ts_to_dt(created)
            dtend = ts_to_dt(modified_ts)

            if not dtstart:
                continue  # can't make an event without a start time

            # If no end time or same as start, use start + 1 hour
            if not dtend or dtend <= dtstart:
                from datetime import timedelta
                dtend = dtstart + timedelta(hours=1)

            event_uid = f'{session_id}@claude-code'
            description = build_description(messages, summary, project_name)
            project_display = project_name.replace('-', '/').replace('Users/markryall/', '~/')
            categories = f'Claude Session,{project_display}'

            event_lines = [
                'BEGIN:VEVENT',
                ical_fold(f'UID:{event_uid}'),
                ical_fold(f'DTSTAMP:{dtstamp}'),
                ical_fold(f'DTSTART:{dt_to_ical(dtstart)}'),
                ical_fold(f'DTEND:{dt_to_ical(dtend)}'),
                ical_fold(f'SUMMARY:💜 {ical_escape(summary)}'),
                ical_fold(f'DESCRIPTION:{description}'),
                ical_fold(f'CATEGORIES:{ical_escape(categories)}'),
                ical_fold(f'LOCATION:{ical_escape(project_display)}'),
                'STATUS:CONFIRMED',
                'TRANSP:TRANSPARENT',
                'END:VEVENT',
            ]
            events.append('\r\n'.join(event_lines))
            total += 1
            print(f'  ✓ {summary[:60]}')

    if not events:
        print('No sessions found.')
        return

    cal_lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        f'PRODID:-//markryall//Claude Sessions//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'X-WR-CALNAME:💜 Claude Sessions',
        f'X-WR-CALDESC:All Claude Code sessions as calendar events',
        f'X-WR-TIMEZONE:UTC',
        '\r\n'.join(events),
        'END:VCALENDAR',
    ]

    output.write_text('\r\n'.join(cal_lines), encoding='utf-8')
    print(f'\n✨ Done! {total} sessions → {output}')
    print('   Import into Calendar.app, Google Calendar, or any CalDAV client')


if __name__ == '__main__':
    main()
