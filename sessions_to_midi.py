#!/usr/bin/env python3
"""Convert Claude Code sessions into a MIDI file — your chat history as music.

Encoding:
  Channel 0  — YOU       (Acoustic Grand Piano, high register, octave doublings)
  Channel 1  — CLAUDIA   (rotates through 8 instruments; minor triads + 7ths)
  Channel 9  — TOOLS     (varied percussion: hi-hat, kick, snare, cowbell)

  Pitch    → C minor pentatonic chords; diminished under heavy tool use (TENSION)
  Duration → proportional to message length
  Velocity → arcs within each session — quiet start, climactic peak, fade out
  Tempo    → per-session: short chatty messages = fast, long thoughtful = slow
  Drama    → silence before long Claudia responses; crash on session climax
  Sessions → concatenated chronologically; epic drum fill + crash between each
  Climax   → most intense session gets full-orchestra treatment
"""

import json
import struct
import sys
from pathlib import Path

CLAUDE_DIR   = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "sessions.mid"

# ── Musical constants ─────────────────────────────────────────────────────────

TICKS = 480

# C minor pentatonic scale degrees (semitones from root)
PENT = [0, 3, 5, 7, 10]

USER_ROOT = 60   # C4 — centre of keyboard; chords will reach up
ASST_ROOT = 36   # C2 — deep; triads spread up through the register

CH_USER    = 0
CH_ASST    = 1
CH_BASS    = 2
CH_RHYTHM  = 3    # Rhythm guitar
CH_LEAD    = 4    # Lead guitar
CH_TRUMPET = 5    # Trumpet — bold fanfares
CH_HORN    = 6    # French Horn — warm melody
CH_CLAR    = 7    # Clarinet — nimble counterpoint
CH_VLN1    = 8    # Violin I — main string melody
# channel 9 = drums
CH_VLN2    = 10   # Violin II — harmony
CH_VLA     = 11   # Viola — inner voice
CH_CELLO   = 12   # Cello — expressive bass melody
CH_CBASS   = 13   # Contrabass — foundation
CH_PERC    = 9    # General MIDI percussion

USER_PROGRAM    = 0    # Acoustic Grand Piano
BASS_PROGRAM    = 33   # Electric Bass (finger)
RHYTHM_PROGRAM  = 27   # Electric Guitar (clean)
LEAD_PROGRAM    = 29   # Overdriven Guitar
TRUMPET_PROGRAM = 56   # Trumpet
HORN_PROGRAM    = 60   # French Horn
CLAR_PROGRAM    = 71   # Clarinet
VLN_PROGRAM     = 40   # Violin
VLA_PROGRAM     = 41   # Viola
CELLO_PROGRAM   = 42   # Cello
CBASS_PROGRAM   = 43   # Contrabass

# Claudia rotates through disco-friendly instruments each session
ASST_PROGRAMS = [
    48,   # String Ensemble 1
    11,   # Vibraphone
    73,   # Flute
    25,   # Acoustic Guitar (steel)
    89,   # Pad 2 (warm)
    52,   # Choir Aahs
    65,   # Alto Sax
    19,   # Church Organ
]


# ── Raw MIDI helpers ──────────────────────────────────────────────────────────

def vlq(n):
    """Encode integer as MIDI variable-length quantity."""
    if n == 0:
        return b'\x00'
    result = []
    while n:
        result.append(n & 0x7f)
        n >>= 7
    result.reverse()
    for i in range(len(result) - 1):
        result[i] |= 0x80
    return bytes(result)


def note_on(ch, note, vel):
    return bytes([0x90 | ch, note & 0x7f, max(1, min(127, vel))])

def note_off(ch, note):
    return bytes([0x80 | ch, note & 0x7f, 0])

def prog_change(ch, program):
    return bytes([0xC0 | ch, program & 0x7f])

def tempo_event(bpm=100):
    t = int(60_000_000 / bpm)
    return bytes([0xff, 0x51, 0x03,
                  (t >> 16) & 0xff, (t >> 8) & 0xff, t & 0xff])

def text_event(s):
    b = s.encode('utf-8')[:127]
    return b'\xff\x01' + vlq(len(b)) + b

def track_name_event(s):
    b = s.encode('utf-8')[:127]
    return b'\xff\x03' + vlq(len(b)) + b


def abs_to_delta(abs_events):
    """Convert [(abs_tick, event_bytes)] → delta-time MIDI event bytestring."""
    out  = b''
    prev = 0
    for tick, ev in sorted(abs_events, key=lambda x: x[0]):
        out += vlq(tick - prev) + ev
        prev = tick
    return out


def wrap_track(event_bytes):
    body = event_bytes + b'\x00\xff\x2f\x00'   # delta=0 + End-of-Track
    return b'MTrk' + struct.pack('>I', len(body)) + body


def build_midi_format0(track_bytes):
    header = b'MThd' + struct.pack('>I', 6) + struct.pack('>HHH', 0, 1, TICKS)
    return header + wrap_track(track_bytes)


# ── Note/duration/tempo mappings ─────────────────────────────────────────────

def pick_chord(text_len, root, msg_idx, role, tool_count=0, is_climax=False):
    """Return a list of MIDI notes forming a chord in the pentatonic scale.

    User    → octave doubling (root + root+12) — bright, punchy
    Claudia → minor triad (root, m3, 5th); very long msgs add a ♭7
    Heavy tool use → fully diminished 7th (maximum TENSION)
    Climax  → wide voicing spanning 3 octaves (EPIC)
    """
    degree = (text_len // 40) % len(PENT)
    octave = (msg_idx // 3) % 4            # cycle through 4 octaves
    base   = max(1, min(110, root + octave * 12 + PENT[degree]))

    # Heavy tool use = DRAMA. Diminished chord = maximum tension.
    if tool_count >= 4:
        return [min(127, base + i) for i in DIM_CHORD]

    if role == "user":
        chord = [base, min(127, base + 12)]
        # Climax user messages get a 5th added — power chord energy
        if is_climax:
            chord.append(min(127, base + 7))
        return chord
    else:
        # Minor triad
        chord = [base, min(127, base + 3), min(127, base + 7)]
        # Long Claudia messages get a ♭7 for colour
        if text_len > 500:
            chord.append(min(127, base + 10))
        # Climax Claudia messages: spread across 3 octaves — orchestral
        if is_climax:
            chord += [min(127, base + 12), min(127, base + 15), min(127, base + 19)]
        return chord


def session_intensity(messages):
    """Score a session's drama level: long messages + heavy tool use = intense."""
    total_text = sum(
        sum(len(b.get("content", "")) for b in m["blocks"] if b["type"] == "text")
        for m in messages
    )
    total_tools = sum(
        sum(1 for b in m["blocks"] if b["type"] == "tool")
        for m in messages
    )
    return total_text + total_tools * 200   # tools count for a lot, darling


def pick_duration(text_len, ticks):
    if   text_len <  50:  return ticks // 2
    elif text_len < 150:  return ticks
    elif text_len < 500:  return ticks * 2
    elif text_len < 1500: return ticks * 4
    else:                 return ticks * 6


def session_bpm(messages):
    """Base BPM per session: chatty = 132, deep/long = 98.
    Wide range — sessions should feel genuinely different from each other."""
    lens = [
        sum(len(b.get("content", "")) for b in m["blocks"] if b["type"] == "text")
        for m in messages
    ]
    avg = sum(lens) / max(len(lens), 1)
    # avg 0 chars → 132 BPM, avg 800+ chars → 98 BPM
    bpm = int(132 - min(avg, 800) / 800 * 34)
    return max(98, min(132, bpm))


# ── Session parsing ───────────────────────────────────────────────────────────

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
                if obj.get("type") not in ("user", "assistant"):
                    continue
                msg = obj.get("message", {})
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue
                content = msg.get("content", "")
                blocks = []
                if isinstance(content, str):
                    if content.strip():
                        blocks.append({"type": "text", "content": content})
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, str) and b.strip():
                            blocks.append({"type": "text", "content": b})
                        elif isinstance(b, dict):
                            btype = b.get("type", "")
                            if btype == "text" and b.get("text", "").strip():
                                blocks.append({"type": "text", "content": b["text"]})
                            elif btype == "tool_use":
                                blocks.append({"type": "tool", "name": b.get("name", "")})
                if blocks:
                    messages.append({
                        "role": role,
                        "blocks": blocks,
                        "timestamp": obj.get("timestamp", ""),
                    })
    except Exception:
        pass
    return messages


def first_user_text(messages):
    for m in messages:
        if m["role"] == "user":
            for b in m["blocks"]:
                if b["type"] == "text":
                    return b["content"].strip()
    return ""


# ── Percussion note map ───────────────────────────────────────────────────────
# General MIDI drum notes (channel 9)
KICK       = 36
SNARE      = 38
HIHAT      = 42
HIHAT_OPEN = 46
RIDE       = 51
COWBELL    = 56
CRASH      = 49
TOM_HI     = 50
TOM_MID    = 47
TOM_LOW    = 45
TOM_FLOOR  = 43
BASS_DRUM2 = 35   # Acoustic Bass Drum — the CANNON

TOOL_DRUMS = [HIHAT, SNARE, COWBELL, RIDE, CRASH]   # cycle per tool index

# C diminished chord offsets (for tension under heavy tool use)
DIM_CHORD = [0, 3, 6, 9]   # fully diminished 7th — maximum drama

def drum_fill(t, ticks, epic=False):
    """Drum fill between sessions.

    Standard: 4 kick+snare hits.
    Epic (climax session boundary): 8-hit accelerating fill ending in CRASH.
    """
    evs = []
    if not epic:
        step = ticks // 4
        for i in range(4):
            hit  = t + step * i
            drum = KICK if i % 2 == 0 else SNARE
            evs.append((hit,             note_on(CH_PERC, drum, 90 - i * 10)))
            evs.append((hit + step // 2, note_off(CH_PERC, drum)))
    else:
        # Accelerating 8-hit fill: steps shrink each hit → rushes toward the crash
        pos = t
        velocity = 60
        for i in range(8):
            step = max(ticks // 16, ticks // (4 + i))   # gets faster
            drum = [KICK, SNARE, KICK, SNARE, HIHAT, SNARE, KICK, CRASH][i]
            evs.append((pos,              note_on(CH_PERC, drum, min(127, velocity + i * 8))))
            evs.append((pos + step // 2,  note_off(CH_PERC, drum)))
            pos += step
        # Crash at the very end of the fill
        evs.append((pos,          note_on(CH_PERC, CRASH, 127)))
        evs.append((pos + ticks,  note_off(CH_PERC, CRASH)))
    return evs


# ── Disco band backing tracks ─────────────────────────────────────────────────

def disco_beat(start_tick, end_tick, ticks):
    """Full disco kit: four-on-the-floor kick, snare 2&4, 16th hi-hats,
    open hi-hat on the and-of-4, ride on every beat for shimmer."""
    evs = []
    t    = start_tick
    beat = 0
    while t < end_tick:
        bar_beat = beat % 4   # 0,1,2,3

        # Four-on-the-floor kick — the disco heartbeat
        evs.append((t,               note_on(CH_PERC, KICK, 100)))
        evs.append((t + ticks // 2,  note_off(CH_PERC, KICK)))

        # Snare on 2 and 4 — the backbeat
        if bar_beat in (1, 3):
            evs.append((t,              note_on(CH_PERC, SNARE, 90)))
            evs.append((t + ticks // 2, note_off(CH_PERC, SNARE)))

        # 16th-note hi-hats — constant forward drive
        for sixteenth in range(4):
            ht   = t + sixteenth * (ticks // 4)
            # Open hi-hat on the "e" of beat 4 (sixteenth=1 of bar_beat=3) — classic disco
            if bar_beat == 3 and sixteenth == 1:
                drum, vel = HIHAT_OPEN, 75
            elif sixteenth % 2 == 0:
                drum, vel = HIHAT, 70          # on the 8th
            else:
                drum, vel = HIHAT, 55          # off-beat 16th — softer ghost

            evs.append((ht,               note_on(CH_PERC, drum, vel)))
            evs.append((ht + ticks // 8,  note_off(CH_PERC, drum)))

        # Ride cymbal on every beat — shimmer and shine
        evs.append((t,              note_on(CH_PERC, RIDE, 50)))
        evs.append((t + ticks // 2, note_off(CH_PERC, RIDE)))

        t    += ticks
        beat += 1
    return evs


def disco_bassline(start_tick, end_tick, ticks, root=36):
    """Funky disco bass: root–fifth–octave–♭7 pattern, syncopated.
    Classic Chic/Nile Rodgers energy."""
    # root=36 is C2; pattern repeats every 2 beats
    pattern = [
        # (beat_offset_in_16ths, semitone_from_root, velocity, duration_16ths)
        (0,  0,  105, 2),   # root, strong downbeat
        (2,  0,   80, 1),   # root ghost
        (3,  7,   90, 1),   # fifth — syncopated anticipation
        (4,  12, 100, 2),   # octave — beat 2
        (6,  10,  80, 1),   # ♭7 passing note
        (7,  7,   85, 1),   # fifth
        (8,  0,  100, 2),   # root — beat 3
        (10, 12,  75, 1),   # octave ghost
        (11, 10,  80, 1),   # ♭7
        (12, 7,   95, 2),   # fifth — beat 4
        (14, 0,   80, 1),   # root approach
        (15, 3,   75, 1),   # ♭3 chromatic pass
    ]
    sixteenth = ticks // 4
    evs = []
    t   = start_tick
    while t < end_tick:
        for offset_16, semitone, vel, dur_16 in pattern:
            note_t = t + offset_16 * sixteenth
            if note_t >= end_tick:
                break
            note = min(127, root + semitone)
            dur  = dur_16 * sixteenth
            evs.append((note_t,       note_on(CH_BASS,  note, vel)))
            evs.append((note_t + dur, note_off(CH_BASS, note)))
        t += ticks * 4   # pattern is 4 beats / 1 bar long
    return evs


def rhythm_guitar(start_tick, end_tick, ticks, root=60):
    """Disco rhythm guitar: clean electric, chick chick chick on the offbeats.
    Classic muted upstroke pattern — every 8th note offbeat."""
    # Chord voicing: root + 4 (major 3rd) + 7 (5th) = basic major triad
    chord = [min(127, root), min(127, root + 4), min(127, root + 7)]
    eighth = ticks // 2
    evs    = []
    t      = start_tick
    beat   = 0
    while t < end_tick:
        # Offbeat (the "and") — the disco chick
        offbeat = t + eighth
        if offbeat < end_tick:
            for note in chord:
                vel = 72 + (beat % 4) * 3   # slight accent every bar
                evs.append((offbeat,          note_on(CH_RHYTHM,  note, vel)))
                evs.append((offbeat + eighth // 2, note_off(CH_RHYTHM, note)))
        t    += ticks
        beat += 1
    return evs


def lead_guitar_lick(t, ticks, root=60, intensity="short"):
    """Pentatonic lead licks at four intensity levels.

    short  — 2-note pickup (fires on small Claudia responses)
    medium — 4-note riff   (medium responses)
    long   — 6-note run    (long responses, 500+ chars)
    climax — 10-note screaming solo (the moment, the drama, THE SONG)
    """
    sixteenth = ticks // 4

    licks = {
        "short":  [0, 3],                            # just a little wink
        "medium": [12, 10, 7, 5],                    # classic blues-minor descent
        "long":   [15, 12, 10, 12, 7, 5],            # wailing run
        "climax": [19, 17, 15, 12, 15, 12, 10, 12, 7, 5],  # FULL SEND
    }
    notes = licks.get(intensity, licks["short"])
    evs   = []
    for i, semitone in enumerate(notes):
        note = min(127, root + semitone)
        nt   = t + i * sixteenth
        # Climax notes get a tiny delay for a swing feel
        if intensity == "climax" and i % 2 == 1:
            nt += sixteenth // 3
        vel  = min(127, 90 + i * 3)
        dur  = max(sixteenth // 2, sixteenth - 10)
        evs.append((nt,       note_on(CH_LEAD,  note, vel)))
        evs.append((nt + dur, note_off(CH_LEAD, note)))
    return evs


# ── Session → absolute MIDI events ───────────────────────────────────────────

# ── Orchestra string/brass/woodwind generators ────────────────────────────────

# C minor pentatonic degrees in semitones
PENT_DEGREES = [0, 3, 5, 7, 10]

def _pent_seq(root, octave_range=2):
    """Full pentatonic scale over octave_range octaves from root."""
    return [root + o * 12 + p for o in range(octave_range) for p in PENT_DEGREES]


def violin1_part(start_tick, end_tick, ticks, section):
    """Violin I: main melodic line — character changes by section."""
    root = 67   # G4 — bright, singing register
    scale = _pent_seq(root, 2)
    evs   = []

    if section == "intro":
        # Whole notes floating — atmospheric
        motif   = [scale[0], scale[2], scale[4], scale[2]]
        dur     = ticks * 4
        vel     = 42
    elif section == "verse":
        # Singing quarter-note melody
        motif   = [scale[0], scale[2], scale[4], scale[3], scale[2], scale[0], scale[3], scale[4]]
        dur     = ticks
        vel     = 62
    elif section == "pre_chorus":
        # 8th-note ascending runs — urgency building
        motif   = [scale[0], scale[1], scale[2], scale[3], scale[4], scale[5], scale[4], scale[3]]
        dur     = ticks // 2
        vel     = 78
    elif section == "chorus":
        # High register, punchy — the TRIUMPH
        motif   = [scale[6], scale[7], scale[6], scale[5], scale[7], scale[8], scale[7], scale[6]]
        dur     = ticks
        vel     = 100
    elif section == "bridge":
        # Slow, expressive half notes — the emotional gut-punch
        motif   = [scale[4], scale[5], scale[3], scale[1], scale[2]]
        dur     = ticks * 2
        vel     = 55
    else:  # outro
        motif   = [scale[2], scale[1], scale[0]]
        dur     = ticks * 3
        vel     = 35

    t = start_tick
    i = 0
    while t + dur <= end_tick:
        note = min(127, motif[i % len(motif)])
        evs.append((t,           note_on(CH_VLN1, note, vel)))
        evs.append((t + dur - max(1, ticks // 8), note_off(CH_VLN1, note)))
        t += dur
        i += 1
    return evs


def violin2_part(start_tick, end_tick, ticks, section):
    """Violin II: harmony in 3rds/5ths below Violin I — same rhythm, lower pitch."""
    # VLN2 plays a perfect 5th below VLN1 (same melodic shape, offset pitch)
    root  = 60   # C4
    scale = _pent_seq(root, 2)
    evs   = []

    if section == "intro":
        motif, dur, vel = [scale[2], scale[0], scale[2], scale[4]], ticks * 4, 38
    elif section == "verse":
        motif = [scale[2], scale[4], scale[2], scale[0], scale[4], scale[2], scale[0], scale[2]]
        dur, vel = ticks, 55
    elif section == "pre_chorus":
        motif = [scale[5], scale[4], scale[3], scale[2], scale[3], scale[4], scale[5], scale[6]]
        dur, vel = ticks // 2, 70
    elif section == "chorus":
        motif = [scale[4], scale[5], scale[4], scale[3], scale[5], scale[6], scale[5], scale[4]]
        dur, vel = ticks, 90
    elif section == "bridge":
        motif, dur, vel = [scale[2], scale[3], scale[1], scale[0]], ticks * 2, 50
    else:
        motif, dur, vel = [scale[1], scale[0]], ticks * 3, 30

    t = start_tick
    i = 0
    while t + dur <= end_tick:
        note = min(127, motif[i % len(motif)])
        evs.append((t,           note_on(CH_VLN2, note, vel)))
        evs.append((t + dur - max(1, ticks // 8), note_off(CH_VLN2, note)))
        t += dur
        i += 1
    return evs


def viola_part(start_tick, end_tick, ticks, section):
    """Viola: sustained inner voice — holds the harmonic middle together."""
    root  = 55   # G3 — rich, dark viola register
    scale = _pent_seq(root, 2)
    evs   = []

    if section in ("intro", "outro"):
        motif, dur, vel = [scale[0], scale[2], scale[1], scale[0]], ticks * 4, 40
    elif section == "verse":
        # Steady half-note inner voice
        motif, dur, vel = [scale[2], scale[4], scale[3], scale[2], scale[4], scale[2]], ticks * 2, 58
    elif section == "pre_chorus":
        motif = [scale[3], scale[2], scale[4], scale[3], scale[5], scale[4], scale[3], scale[2]]
        dur, vel = ticks, 70
    elif section == "chorus":
        # Tremolo feel — rapid repeated notes
        motif, dur, vel = [scale[4], scale[4], scale[5], scale[5], scale[4], scale[4]], ticks // 2, 85
    else:  # bridge
        motif, dur, vel = [scale[1], scale[2], scale[0]], ticks * 3, 50

    t = start_tick
    i = 0
    while t + dur <= end_tick:
        note = min(127, motif[i % len(motif)])
        evs.append((t,           note_on(CH_VLA, note, vel)))
        evs.append((t + dur - max(1, ticks // 10), note_off(CH_VLA, note)))
        t += dur
        i += 1
    return evs


def cello_part(start_tick, end_tick, ticks, section):
    """Cello: expressive bass melody — sings in the low-mid register."""
    root  = 48   # C3 — full-bodied cello tone
    scale = _pent_seq(root, 2)
    evs   = []

    if section == "intro":
        # Long, rich pedal tones
        motif, dur, vel = [scale[0], scale[2], scale[0]], ticks * 6, 55
    elif section == "verse":
        motif = [scale[0], scale[2], scale[3], scale[2], scale[1], scale[0]]
        dur, vel = ticks * 2, 65
    elif section == "pre_chorus":
        motif = [scale[2], scale[3], scale[4], scale[5], scale[4], scale[3], scale[2], scale[1]]
        dur, vel = ticks, 78
    elif section == "chorus":
        motif = [scale[4], scale[5], scale[4], scale[3], scale[2], scale[4], scale[5], scale[3]]
        dur, vel = ticks, 92
    elif section == "bridge":
        # Solo cello melody — the tearjerker
        motif = [scale[3], scale[4], scale[5], scale[4], scale[3], scale[2], scale[0]]
        dur, vel = ticks * 2, 70
    else:  # outro
        motif, dur, vel = [scale[2], scale[1], scale[0]], ticks * 4, 45

    t = start_tick
    i = 0
    while t + dur <= end_tick:
        note = min(127, motif[i % len(motif)])
        evs.append((t,           note_on(CH_CELLO, note, vel)))
        evs.append((t + dur - max(1, ticks // 6), note_off(CH_CELLO, note)))
        t += dur
        i += 1
    return evs


def contrabass_part(start_tick, end_tick, ticks, section):
    """Contrabass: foundation pizzicato — beats 1 and 3, rock solid."""
    root = 36   # C2 — earth-shaking low end
    pent = [root + p for p in PENT_DEGREES]
    evs  = []
    t    = start_tick
    beat = 0
    vel  = {"intro": 50, "verse": 65, "pre_chorus": 75,
            "chorus": 90, "bridge": 55, "outro": 40}.get(section, 65)
    while t < end_tick:
        bar_beat = beat % 4
        if bar_beat in (0, 2):   # beats 1 and 3
            note = min(127, pent[bar_beat // 2 % len(pent)])
            dur  = ticks // 2    # pizzicato = short
            evs.append((t,       note_on(CH_CBASS,  note, vel)))
            evs.append((t + dur, note_off(CH_CBASS, note)))
        t    += ticks
        beat += 1
    return evs


def trumpet_part(start_tick, end_tick, ticks, section):
    """Trumpet: bold fanfares in chorus; triumphant calls in pre-chorus."""
    root  = 72   # C5 — brilliant trumpet register
    scale = _pent_seq(root, 2)
    evs   = []

    if section not in ("pre_chorus", "chorus"):
        return evs   # silent elsewhere — trumpet entrance is an EVENT

    if section == "pre_chorus":
        # Rising call — anticipation
        motif, dur, vel = [scale[0], scale[2], scale[4], scale[3]], ticks * 2, 80
    else:  # chorus — triumphant fanfare
        motif = [scale[4], scale[5], scale[4], scale[5], scale[3], scale[4], scale[5], scale[6]]
        dur, vel = ticks, 110

    t = start_tick
    i = 0
    while t + dur <= end_tick:
        note = min(127, motif[i % len(motif)])
        evs.append((t,           note_on(CH_TRUMPET, note, vel)))
        evs.append((t + dur - max(1, ticks // 6), note_off(CH_TRUMPET, note)))
        t += dur * 2   # trumpets rest every other phrase — makes it punchy
        i += 1
    return evs


def french_horn_part(start_tick, end_tick, ticks, section):
    """French Horn: warm sustained melody — emotional glue of the piece."""
    root  = 60   # C4 — warm mid-register
    scale = _pent_seq(root, 2)
    evs   = []

    if section not in ("verse", "pre_chorus", "bridge", "outro"):
        return evs   # horn is for the emotional sections

    motif_map = {
        "verse":      ([scale[2], scale[4], scale[3], scale[2], scale[0]], ticks * 2, 58),
        "pre_chorus": ([scale[4], scale[5], scale[7], scale[6], scale[5]], ticks * 2, 72),
        "bridge":     ([scale[5], scale[7], scale[6], scale[4], scale[3], scale[2]], ticks * 3, 75),
        "outro":      ([scale[3], scale[2], scale[0]], ticks * 4, 45),
    }
    motif, dur, vel = motif_map[section]

    t = start_tick
    i = 0
    while t + dur <= end_tick:
        note = min(127, motif[i % len(motif)])
        evs.append((t,           note_on(CH_HORN, note, vel)))
        evs.append((t + dur - max(1, ticks // 4), note_off(CH_HORN, note)))
        t += dur
        i += 1
    return evs


def clarinet_part(start_tick, end_tick, ticks, section):
    """Clarinet: nimble 16th-note runs in verse; sustained in bridge."""
    root  = 74   # D5 — sweet clarinet register
    scale = _pent_seq(root, 2)
    evs   = []

    if section not in ("verse", "pre_chorus", "bridge"):
        return evs

    if section == "verse":
        # Weaving 8th-note countermelody
        motif = [scale[1], scale[3], scale[2], scale[4], scale[3], scale[5], scale[4], scale[3]]
        dur, vel = ticks // 2, 65
    elif section == "pre_chorus":
        # Fast 16th-note ascending runs
        motif = [scale[0], scale[1], scale[2], scale[3], scale[4], scale[5], scale[6], scale[5]]
        dur, vel = ticks // 4, 72
    else:  # bridge
        motif, dur, vel = [scale[4], scale[5], scale[3], scale[2]], ticks * 2, 60

    t = start_tick
    i = 0
    while t + dur <= end_tick:
        note = min(127, motif[i % len(motif)])
        evs.append((t,           note_on(CH_CLAR, note, vel)))
        evs.append((t + dur - max(1, ticks // 10), note_off(CH_CLAR, note)))
        t += dur
        i += 1
    return evs


def cannon_fire(t, ticks):
    """1812 Overture energy — bass drum BOOM at fff. Fire on epic moments."""
    evs = [
        (t,                note_on(CH_PERC,  BASS_DRUM2, 127)),
        (t + ticks,        note_off(CH_PERC, BASS_DRUM2)),
        # Follow with crash for maximum drama
        (t,                note_on(CH_PERC,  CRASH, 127)),
        (t + ticks * 2,    note_off(CH_PERC, CRASH)),
    ]
    return evs


# ── Session → absolute MIDI events ───────────────────────────────────────────
SECTIONS = ["intro", "verse", "pre_chorus", "chorus", "bridge", "outro"]
SECTION_THRESHOLDS = [0.0, 0.15, 0.45, 0.60, 0.75, 0.87, 1.01]

def get_section(msg_idx, n_msgs):
    pos = msg_idx / max(n_msgs, 1)
    for i, thresh in enumerate(SECTION_THRESHOLDS[1:]):
        if pos < thresh:
            return SECTIONS[i]
    return "outro"


def session_to_events(session, asst_program, start_tick, is_climax_session=False):
    """Return (abs_events_list, end_tick).

    Song structure per session:
      intro      — sparse: just piano + bass, no full kit yet
      verse      — full band enters, building energy
      pre_chorus — tempo nudges up, rhythm guitar intensifies, lead teases
      chorus     — everything hits: full velocity, crashes, lead guitar wails
      bridge     — tempo drops, sparse breakdown, dramatic breath
      outro      — fade: just piano + light bass, winding down

    Lead guitar fires on every Claudia response, intensity scales with section.
    """
    messages = session["messages"]
    bpm      = session_bpm(messages)
    ticks    = TICKS

    # Identify climax message (longest Claudia response)
    max_text_len = 0
    climax_raw_idx = -1
    for i, m in enumerate(messages):
        if m["role"] == "assistant":
            tl = sum(len(b.get("content", "")) for b in m["blocks"] if b["type"] == "text")
            if tl > max_text_len:
                max_text_len = tl
                climax_raw_idx = i

    # ── Pass 1: calculate message timings to know section boundaries ──────────
    active = []
    for raw_idx, msg in enumerate(messages):
        tl = sum(len(b.get("content","")) for b in msg["blocks"] if b["type"]=="text")
        tc = sum(1 for b in msg["blocks"] if b["type"] == "tool")
        if tl + tc > 0:
            active.append((raw_idx, msg, tl, tc))

    n_msgs = max(len(active), 1)

    # Compute start tick of each active message
    msg_times = []   # (raw_idx, msg, text_len, tool_count, section, t_start, t_end)
    t = start_tick
    for seq_idx, (raw_idx, msg, text_len, tool_count) in enumerate(active):
        section = get_section(seq_idx, n_msgs)
        # Dramatic silence before big Claudia responses
        if msg["role"] == "assistant" and text_len > 800:
            t += ticks
        dur    = pick_duration(text_len, ticks)
        t_end  = t + dur
        msg_times.append((raw_idx, msg, text_len, tool_count, section, seq_idx, t, t_end))
        t = t_end + ticks // 2

    end_tick = t

    # ── Section boundary ticks ────────────────────────────────────────────────
    section_ranges = {}   # section → (first_start, last_end)
    for _, _, _, _, section, _, t_start, t_end in msg_times:
        if section not in section_ranges:
            section_ranges[section] = [t_start, t_end]
        else:
            section_ranges[section][1] = t_end

    # ── Pass 2: emit note events ──────────────────────────────────────────────
    abs_events = []

    # Program changes + initial tempo
    abs_events.append((start_tick, tempo_event(bpm)))
    abs_events.append((start_tick, text_event(f"{'★ ' if is_climax_session else ''}{session['title'][:55]} [{bpm}bpm]")))
    for ch, prog in [
        (CH_USER,    USER_PROGRAM),
        (CH_ASST,    asst_program),
        (CH_BASS,    BASS_PROGRAM),
        (CH_RHYTHM,  RHYTHM_PROGRAM),
        (CH_LEAD,    LEAD_PROGRAM),
        (CH_TRUMPET, TRUMPET_PROGRAM),
        (CH_HORN,    HORN_PROGRAM),
        (CH_CLAR,    CLAR_PROGRAM),
        (CH_VLN1,    VLN_PROGRAM),
        (CH_VLN2,    VLN_PROGRAM),
        (CH_VLA,     VLA_PROGRAM),
        (CH_CELLO,   CELLO_PROGRAM),
        (CH_CBASS,   CBASS_PROGRAM),
    ]:
        abs_events.append((start_tick, prog_change(ch, prog)))

    # Tempo changes: pre_chorus ramps up +8 BPM, chorus peaks, bridge drops -10 BPM
    if "pre_chorus" in section_ranges:
        ramp_start = section_ranges["pre_chorus"][0]
        ramp_end   = section_ranges.get("chorus", section_ranges["pre_chorus"])[0]
        steps      = max(1, (ramp_end - ramp_start) // (ticks * 4))
        for step in range(steps + 1):
            ramp_bpm = bpm + int(step / max(steps, 1) * 8)
            abs_events.append((ramp_start + step * ticks * 4, tempo_event(ramp_bpm)))
    if "bridge" in section_ranges:
        abs_events.append((section_ranges["bridge"][0], tempo_event(max(88, bpm - 10))))
    if "outro" in section_ranges:
        abs_events.append((section_ranges["outro"][0], tempo_event(bpm)))

    prev_section = None
    for raw_idx, msg, text_len, tool_count, section, seq_idx, t_msg, t_end in msg_times:
        role = msg["role"]
        ch   = CH_USER if role == "user" else CH_ASST
        root = USER_ROOT if role == "user" else ASST_ROOT
        dur  = t_end - t_msg

        # Section label text event on section change
        if section != prev_section:
            abs_events.append((t_msg, text_event(f"[{section.upper()}]")))
            prev_section = section

        # ── Velocity: arc within session, boosted by section ──────────────────
        arc_pos   = seq_idx / n_msgs
        arc_curve = 1.0 - abs(arc_pos * 2 - 1)
        section_boost = {"intro": 0, "verse": 5, "pre_chorus": 10,
                         "chorus": 25, "bridge": -10, "outro": -15}.get(section, 0)
        base_vel  = 50 if role == "user" else 40
        peak_vel  = 105 if role == "user" else 90
        vel = int(base_vel + arc_curve * (peak_vel - base_vel) + section_boost)
        vel = max(20, min(127, vel + ((seq_idx * 13 + text_len) % 14) - 7))

        is_msg_climax = (raw_idx == climax_raw_idx)

        notes = pick_chord(text_len, root, seq_idx, role,
                           tool_count=tool_count, is_climax=is_msg_climax)
        for note in notes:
            abs_events.append((t_msg,  note_on(ch,  note, vel)))
            abs_events.append((t_end,  note_off(ch, note)))

        # ── Crashes on chorus + climax; CANNONS on the climax session ─────────────
        if section == "chorus" or is_msg_climax:
            abs_events.append((t_msg,           note_on(CH_PERC,  CRASH, min(127, vel + 20))))
            abs_events.append((t_msg + ticks*2, note_off(CH_PERC, CRASH)))
        if is_msg_climax and is_climax_session:
            abs_events.extend(cannon_fire(t_msg, ticks))
            abs_events.extend(cannon_fire(t_msg + ticks * 2, ticks))  # 1812 double-cannon

        # ── Lead guitar — fires on every Claudia response, intensity by section ─
        if role == "assistant" and text_len > 0:
            lead_intensity = {
                "intro":      None,           # silence — building anticipation
                "verse":      "short",        # a little tease
                "pre_chorus": "medium",       # getting excited
                "chorus":     "climax" if is_msg_climax else "long",
                "bridge":     "short",        # sparse breakdown
                "outro":      None,           # letting it breathe
            }.get(section)
            if lead_intensity:
                abs_events.extend(lead_guitar_lick(t_msg, ticks, root=USER_ROOT,
                                                   intensity=lead_intensity))

        # ── Tool use percussion ────────────────────────────────────────────────
        if tool_count:
            step = dur // (tool_count + 1)
            for i in range(tool_count):
                hit  = t_msg + step * (i + 1)
                drum = TOOL_DRUMS[i % len(TOOL_DRUMS)]
                abs_events.append((hit,            note_on(CH_PERC, drum, min(127, vel - 10))))
                abs_events.append((hit + ticks//4, note_off(CH_PERC, drum)))

    # ── Section-aware full orchestra + band ───────────────────────────────────
    for section, (s_start, s_end) in section_ranges.items():
        if section == "intro":
            # Strings and bass only — atmospheric, sparse
            abs_events.extend(disco_bassline(s_start, s_end, ticks, root=36))
            abs_events.extend(contrabass_part(s_start, s_end, ticks, section))
            abs_events.extend(cello_part(s_start, s_end, ticks, section))
            abs_events.extend(viola_part(s_start, s_end, ticks, section))
            abs_events.extend(violin1_part(s_start, s_end, ticks, section))
            abs_events.extend(violin2_part(s_start, s_end, ticks, section))

        elif section == "verse":
            # Disco rhythm section enters + full strings + clarinet weaves
            abs_events.extend(disco_beat(s_start, s_end, ticks))
            abs_events.extend(disco_bassline(s_start, s_end, ticks, root=36))
            abs_events.extend(rhythm_guitar(s_start, s_end, ticks, root=USER_ROOT))
            abs_events.extend(contrabass_part(s_start, s_end, ticks, section))
            abs_events.extend(cello_part(s_start, s_end, ticks, section))
            abs_events.extend(viola_part(s_start, s_end, ticks, section))
            abs_events.extend(violin1_part(s_start, s_end, ticks, section))
            abs_events.extend(violin2_part(s_start, s_end, ticks, section))
            abs_events.extend(clarinet_part(s_start, s_end, ticks, section))
            abs_events.extend(french_horn_part(s_start, s_end, ticks, section))

        elif section == "pre_chorus":
            # Urgency: doubled rhythm, running clarinet, horn calls, strings accelerate
            abs_events.extend(disco_beat(s_start, s_end, ticks))
            abs_events.extend(disco_bassline(s_start, s_end, ticks, root=36))
            abs_events.extend(rhythm_guitar(s_start, s_end, ticks, root=USER_ROOT))
            abs_events.extend(rhythm_guitar(s_start, s_end, ticks, root=USER_ROOT + 12))
            abs_events.extend(contrabass_part(s_start, s_end, ticks, section))
            abs_events.extend(cello_part(s_start, s_end, ticks, section))
            abs_events.extend(viola_part(s_start, s_end, ticks, section))
            abs_events.extend(violin1_part(s_start, s_end, ticks, section))
            abs_events.extend(violin2_part(s_start, s_end, ticks, section))
            abs_events.extend(clarinet_part(s_start, s_end, ticks, section))
            abs_events.extend(french_horn_part(s_start, s_end, ticks, section))
            abs_events.extend(trumpet_part(s_start, s_end, ticks, section))

        elif section == "chorus":
            # FULL SYMPHONY ORCHESTRA + DISCO BAND — TCHAIKOVSKY MEETS CHIC
            abs_events.extend(disco_beat(s_start, s_end, ticks))
            abs_events.extend(disco_bassline(s_start, s_end, ticks, root=36))
            abs_events.extend(rhythm_guitar(s_start, s_end, ticks, root=USER_ROOT))
            abs_events.extend(rhythm_guitar(s_start, s_end, ticks, root=USER_ROOT + 7))
            abs_events.extend(contrabass_part(s_start, s_end, ticks, section))
            abs_events.extend(cello_part(s_start, s_end, ticks, section))
            abs_events.extend(viola_part(s_start, s_end, ticks, section))
            abs_events.extend(violin1_part(s_start, s_end, ticks, section))
            abs_events.extend(violin2_part(s_start, s_end, ticks, section))
            abs_events.extend(trumpet_part(s_start, s_end, ticks, section))
            abs_events.extend(french_horn_part(s_start, s_end, ticks, section))
            abs_events.extend(clarinet_part(s_start, s_end, ticks, section))

        elif section == "bridge":
            # Emotional breakdown: solo cello, sparse kick, horn carries the melody
            abs_events.extend(disco_bassline(s_start, s_end, ticks, root=36))
            abs_events.extend(contrabass_part(s_start, s_end, ticks, section))
            abs_events.extend(cello_part(s_start, s_end, ticks, section))
            abs_events.extend(french_horn_part(s_start, s_end, ticks, section))
            abs_events.extend(clarinet_part(s_start, s_end, ticks, section))
            # Sparse kit — just kick every other beat
            tb = s_start
            while tb < s_end:
                abs_events.append((tb,            note_on(CH_PERC, KICK, 75)))
                abs_events.append((tb + ticks//2, note_off(CH_PERC, KICK)))
                tb += ticks * 2

        elif section == "outro":
            # Strings fade, bass and contrabass hold the ground
            abs_events.extend(disco_bassline(s_start, s_end, ticks, root=36))
            abs_events.extend(contrabass_part(s_start, s_end, ticks, section))
            abs_events.extend(cello_part(s_start, s_end, ticks, section))
            abs_events.extend(viola_part(s_start, s_end, ticks, section))
            abs_events.extend(violin1_part(s_start, s_end, ticks, section))
            abs_events.extend(violin2_part(s_start, s_end, ticks, section))

    return abs_events, end_tick


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)

    print("Loading sessions…")
    index_map = build_global_index(CLAUDE_DIR)

    sessions = []
    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            sid      = jsonl.stem
            messages = parse_session(jsonl)
            if not messages:
                continue
            meta    = index_map.get(sid, {})
            fp      = first_user_text(messages)
            title   = meta.get("summary", "") or meta.get("firstPrompt", "") or fp or "Untitled"
            if len(title) > 60:
                title = title[:60] + "…"
            created = meta.get("created", "") or (messages[0]["timestamp"] if messages else "")
            sessions.append({
                "id": sid, "title": title,
                "created": created, "messages": messages,
            })

    sessions.sort(key=lambda s: s["created"])
    print(f"✓ {len(sessions)} sessions loaded")

    # Find the most dramatic session — it gets the climax treatment ✨
    intensities     = [session_intensity(s["messages"]) for s in sessions]
    climax_session_idx = intensities.index(max(intensities)) if intensities else -1
    print(f"★  Climax session: {sessions[climax_session_idx]['title'][:60]}" if climax_session_idx >= 0 else "")

    # Build the single master track
    abs_events = [(0, track_name_event("Claude Sessions 💜"))]

    t = 0
    for i, session in enumerate(sessions):
        asst_prog       = ASST_PROGRAMS[i % len(ASST_PROGRAMS)]
        is_climax       = (i == climax_session_idx)
        evs, t          = session_to_events(session, asst_prog, t, is_climax_session=is_climax)
        abs_events.extend(evs)
        # Epic fill before the climax session; standard fill everywhere else
        next_is_climax = (i + 1 == climax_session_idx)
        abs_events.extend(drum_fill(t, TICKS * 2, epic=next_is_climax))
        t += TICKS * 6
        bpm = session_bpm(session["messages"])
        star = "★ " if is_climax else "  "
        print(f"  ♪ {star}[{bpm:3d}bpm] {session['title'][:60]}")

    track_bytes = abs_to_delta(abs_events)
    midi        = build_midi_format0(track_bytes)
    output.write_bytes(midi)

    print(f"\n✨ Done! {len(sessions)} sessions → {output}")
    print(f"   Drag into Logic Pro for the full experience 💜")


if __name__ == "__main__":
    main()
