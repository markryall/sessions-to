#!/usr/bin/env python3
"""sessions_to_sc.py — Convert Claude Code sessions into a SuperCollider score.

Reads every session from ~/.claude/projects/ and renders your conversation
history as a generative piece of music. Each message, tool call, and session
boundary becomes a sonic event.

Usage:
  python3 sessions_to_sc.py                  # standard mode → tmp/sessions.scd
  python3 sessions_to_sc.py --microtonal     # alien math rock mode
  python3 sessions_to_sc.py out.scd          # custom output path

Then open the .scd in SuperCollider IDE (brew install --cask supercollider),
select all (Cmd+A), and run (Cmd+Return).

────────────────────────────────────────────────────────────────────────────────
Standard mode encoding:
  YOU        → bright FM synth, high register, right-panned
  CLAUDIA    → FM synth with LFO wobble, left-panned; chaos grows over time
  TOOL USES  → bandpass noise bursts, fired concurrently
  SESSIONS   → separated by reverberant minor-triad pads

Microtonal mode (--microtonal):
  Scale      → 11-limit just intonation — none of these intervals exist in 12-TET
  YOU        → golden-ratio FM + AM (modulator at freq/φ), right-panned
  CLAUDIA    → ring mod + FM + micro-pitch-drift, left-panned; unravels as chaos→1
  TOOL USES  → Ringz resonator banks tuned to golden-ratio partials
  SESSIONS   → 11-limit cluster pads; each session has its own tonal centre
  DRONE      → 11-limit harmonic drone blooms under the whole piece
  BASS       → slow sustained FM bass walking root harmonics
  BELLS      → sparse high Ringz pings, 4–7s decay, wide stereo
  COWBELL    → CR-78-style, retuned per session, skips beat 4-of-7 for swing
  COUNTER    → second melodic voice reading messages out of order
  RHYTHM     → prime-spaced durations — no 4/4 allowed in this venue
  CHAOS      → ramps 0→1 across conversation history; late sessions get weird
────────────────────────────────────────────────────────────────────────────────
"""

import argparse
import json
import sys
from pathlib import Path

CLAUDE_DIR     = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "sessions.scd"


# ── Parsing ───────────────────────────────────────────────────────────────────

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
    """Return (messages, first_user_text).

    messages: list of [role_int, text_len, tool_count]
      role_int: 0 = user, 1 = assistant
    """
    messages = []
    first_user_text = ""
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

                content    = msg.get("content", "")
                text_len   = 0
                tool_count = 0
                first_text = ""   # first text chunk in this message

                if isinstance(content, str):
                    text_len   = len(content.strip())
                    first_text = content.strip()
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, str) and b.strip():
                            text_len  += len(b.strip())
                            if not first_text:
                                first_text = b.strip()
                        elif isinstance(b, dict):
                            btype = b.get("type", "")
                            if btype == "text":
                                t = b.get("text", "").strip()
                                text_len += len(t)
                                if not first_text:
                                    first_text = t
                            elif btype == "tool_use":
                                tool_count += 1

                if text_len == 0 and tool_count == 0:
                    continue

                role_int = 0 if role == "user" else 1
                if role_int == 0 and not first_user_text and first_text:
                    first_user_text = first_text

                messages.append([role_int, text_len, tool_count])
    except Exception:
        pass
    return messages, first_user_text


def load_all_sessions():
    index_map = build_global_index(CLAUDE_DIR)
    sessions  = []

    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            sid = jsonl.stem
            messages, first_user_text = parse_session(jsonl)
            if not messages:
                continue

            meta    = index_map.get(sid, {})
            title   = (meta.get("summary", "")
                       or meta.get("firstPrompt", "")
                       or first_user_text
                       or "Untitled")
            if len(title) > 60:
                title = title[:60] + "…"

            created = (meta.get("created", "")
                       or next((obj.get("timestamp", "") for obj in [{}]), ""))
            # fallback: just use sid for sorting if no created
            sessions.append({
                "title":    title,
                "created":  created,
                "messages": messages,
            })

    sessions.sort(key=lambda s: s["created"])
    return sessions


# ── SC code generation ────────────────────────────────────────────────────────

def sc_str(s):
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", " ").replace("\r", "")
    return f'"{s}"'


def build_sessions_sc(sessions):
    n = len(sessions)
    sess_parts = []
    for i, s in enumerate(sessions):
        chaos    = round(i / max(n - 1, 1), 4)
        title_sc = sc_str(s["title"])
        msgs_sc  = ", ".join(f"[{m[0]}, {m[1]}, {m[2]}]" for m in s["messages"])
        sess_parts.append(f"  [{title_sc}, [{msgs_sc}], {chaos}]")
    return "[\n" + ",\n".join(sess_parts) + "\n]"


def generate_sc(sessions):
    n           = len(sessions)
    total_msgs  = sum(len(s["messages"]) for s in sessions)
    sessions_sc = build_sessions_sc(sessions)

    return f"""\
// ✨ Claude Sessions — SuperCollider Score
// {n} sessions · {total_msgs} messages
//
// 1. Install SuperCollider:  brew install --cask supercollider
// 2. Open this file in the SuperCollider IDE (scide)
// 3. Cmd+A to select all, then Cmd+Return to run
//
// Encoding:
//   YOU      → bright FM synth, high register, right channel
//   CLAUDIA  → warm FM synth with LFO wobble, left channel
//              chaos parameter ramps from 0→1 over the full history
//   TOOLS    → bandpass noise bursts, fired concurrently via fork
//   SESSION  → transition chord (reverberant minor triad)

(
// All vars must be declared before any statements in SC
var sessions = {sessions_sc};
var pent     = [261.63, 311.13, 349.23, 392.00, 466.16];  // C minor pentatonic
var pickFreq = {{ |textLen, isUser|
  var note = pent[textLen % 5];
  var oct  = ((textLen / 200).asInteger % 3) + 1;
  note * oct.asFloat * (if(isUser, 2.0, 1.0))
}};
var pickDur = {{ |textLen|
  case
    {{ textLen < 50   }} {{ 0.15 }}
    {{ textLen < 150  }} {{ 0.35 }}
    {{ textLen < 500  }} {{ 0.7  }}
    {{ textLen < 1500 }} {{ 1.4  }}
    {{ true           }} {{ 2.8  }}
}};

s.waitForBoot({{

  // ── YOU: bright FM, snappy envelope ────────────────────────────────────────
  SynthDef(\\you, {{
    |out=0, freq=880, amp=0.3, dur=0.4, modRatio=2.01, modIdx=1.0, pan=0.6|
    var env = EnvGen.kr(Env.perc(0.008, dur, 1, -4), doneAction: 2);
    var mod = SinOsc.ar(freq * modRatio, 0, freq * modIdx);
    var sig = SinOsc.ar(freq + mod, 0, amp) * env;
    Out.ar(out, Pan2.ar(sig, pan));
  }}).add;

  // ── CLAUDIA: FM with LFO, grows wilder as chaos approaches 1.0 ─────────────
  SynthDef(\\claudia, {{
    |out=0, freq=220, amp=0.25, dur=1.0, modRatio=1.4142, modIdx=2.0,
     chaos=0.0, pan= -0.6|
    var lfo = SinOsc.kr(0.2 + (chaos * 4.0), 0, chaos * freq * 0.15);
    var env = EnvGen.kr(Env.perc(0.04, dur, 1, -2), doneAction: 2);
    var mod = SinOsc.ar((freq + lfo) * modRatio, 0, freq * modIdx * (1.0 + (chaos * 2.5)));
    var sig = SinOsc.ar(freq + mod, 0, amp) * env;
    sig = FreeVerb.ar(sig, 0.2 + (chaos * 0.6), 0.75 + (chaos * 0.2));
    Out.ar(out, Pan2.ar(sig, pan));
  }}).add;

  // ── TOOL: bandpass noise burst ─────────────────────────────────────────────
  SynthDef(\\tool, {{
    |out=0, amp=0.5, freq=3000|
    var env = EnvGen.kr(Env.perc(0.001, 0.07), doneAction: 2);
    var sig = BPF.ar(WhiteNoise.ar(amp), freq, 0.25) * env;
    Out.ar(out, Pan2.ar(sig, 0));
  }}).add;

  // ── PAD: session transition — minor triad with reverb ──────────────────────
  SynthDef(\\pad, {{
    |out=0, freq=130, amp=0.12, dur=1.5, chaos=0.0|
    var env = EnvGen.kr(Env.linen(0.35, dur, 0.65), doneAction: 2);
    var det = LFNoise1.kr(0.5) * chaos * freq * 0.05;
    var sig = (SinOsc.ar(freq       + det) * 0.5)
            + (SinOsc.ar(freq * 1.189 + det) * 0.3)
            + (SinOsc.ar(freq * 1.498 + det) * 0.2);
    sig = FreeVerb.ar(sig * amp * env, 0.5 + (chaos * 0.35), 0.9);
    Out.ar(out, sig ! 2);
  }}).add;

  s.sync;

  // ── Playback routine ────────────────────────────────────────────────────────
  Routine({{
    sessions.do({{ |session|
      var title    = session[0];
      var messages = session[1];
      var chaos    = session[2];

      ("\\n♪  " ++ title).postln;

      // Transition pad chord
      Synth(\\pad, [
        \\freq,  pent[messages.size % 5] * 0.5,
        \\amp,   0.1,
        \\dur,   1.2,
        \\chaos, chaos,
      ]);
      1.2.wait;

      messages.do({{ |msg|
        var role      = msg[0];   // 0 = you, 1 = claudia
        var textLen   = msg[1];
        var toolCount = msg[2];
        var isUser    = role == 0;
        var freq      = pickFreq.(textLen, isUser);
        var dur       = pickDur.(textLen);
        var modIdx    = 0.5 + ((textLen % 20) * 0.1);

        // Tool hits fire concurrently across the note's duration
        if(toolCount > 0, {{
          fork {{
            toolCount.do({{ |i|
              (dur / (toolCount + 1)).wait;
              Synth(\\tool, [
                \\amp,  0.45,
                \\freq, 1500 + (i * 800) + (chaos * 2500).asInteger,
              ]);
            }});
          }};
        }});

        if(isUser, {{
          Synth(\\you, [
            \\freq,     freq,
            \\amp,      0.32,
            \\dur,      dur,
            \\modRatio, 2.0 + (chaos * 0.7),
            \\modIdx,   modIdx,
            \\pan,      0.4 + (chaos * 0.4),
          ]);
        }}, {{
          Synth(\\claudia, [
            \\freq,     freq,
            \\amp,      0.26,
            \\dur,      dur,
            \\modRatio, 1.4142 + (chaos * 0.5),
            \\modIdx,   modIdx * (1.0 + (chaos * 3.0)),
            \\chaos,    chaos,
            \\pan,      -0.4 - (chaos * 0.4),
          ]);
        }});

        dur.wait;
        0.04.wait;
      }});

      2.0.wait;
    }});

    "\\n✨ Done! All Claude sessions played.".postln;
  }}).play;

}});
)
"""


def generate_sc_microtonal(sessions):
    n           = len(sessions)
    total_msgs  = sum(len(s["messages"]) for s in sessions)
    sessions_sc = build_sessions_sc(sessions)

    return f"""\
// 👽 Claude Sessions — Microtonal SuperCollider Score
// {n} sessions · {total_msgs} messages
// 11-limit just intonation · golden-ratio FM · prime-spaced rhythms
// per-session tonal centres · parallel groove loops · overlapping voices
//
// 1. brew install --cask supercollider
// 2. Open in SuperCollider IDE
// 3. Cmd+A → Cmd+Return

(
var sessions = {sessions_sc};

// 11-limit JI scale — 7 pitches, none of them in 12-TET
var root  = 110.0;
var scale = [
  root * 1.000,   // 1/1   unison
  root * 1.125,   // 9/8   large whole tone
  root * 1.200,   // 6/5   minor third
  root * 1.375,   // 11/8  raised fourth (the genuinely alien one)
  root * 1.500,   // 3/2   perfect fifth
  root * 1.600,   // 8/5   minor sixth
  root * 1.750,   // 7/4   harmonic seventh (beautifully flat)
];

// Prime-duration palette — no 4/4 allowed in this venue
var primes = [0.11, 0.13, 0.17, 0.19, 0.23, 0.29, 0.31, 0.37];

// rootMult remaps scale to session's tonal centre
var pickFreq = {{|textLen, isUser, rootMult|
  var note = scale[textLen % 7] * rootMult;
  var oct  = ((textLen / 150).asInteger % 4) + (if(isUser, 2, 1));
  note * oct.asFloat
}};

var pickDur = {{|textLen|
  primes[textLen % 8] * (((textLen / 100).asInteger % 5) + 1) * 2.5
}};

s.waitForBoot({{

  // YOU: golden-ratio FM + AM — modDepth controls how unhinged the FM index is
  SynthDef(\\you_mt, {{
    |out=0, freq=440, amp=0.3, dur=0.3, chaos=0.0, pan=0.6, modDepth=1.0|
    var phi    = 1.6180339887;
    var detune = LFNoise0.kr(7) * chaos * freq * 0.02;
    var env    = EnvGen.kr(Env([0,1,0.3,0], [0.005, dur*0.3, dur*0.65]), doneAction:2);
    var mod    = SinOsc.ar((freq + detune) * phi, 0, freq * modDepth * (1.5 + (chaos * 3.0)));
    var car    = SinOsc.ar(freq + mod + detune);
    var am     = SinOsc.kr(freq / phi) * 0.5 + 0.5;
    var sig    = car * am * amp * env;
    Out.ar(out, Pan2.ar(sig, pan + (chaos * 0.3)));
  }}).add;

  // CLAUDIA: ring mod + FM + drift — speed warps LFO rates, modDepth warps FM
  SynthDef(\\claudia_mt, {{
    |out=0, freq=110, amp=0.25, dur=1.0, chaos=0.0, pan= -0.6, modDepth=1.0, speed=1.0|
    var drift = LFNoise1.kr((0.3 + (chaos * 3.0)) * speed) * chaos * freq * 0.09;
    var lfo   = SinOsc.kr((chaos * 11.0 + 0.1) * speed, 0, chaos * freq * 0.15);
    var env   = EnvGen.kr(Env.perc(0.02, dur, 1, -1.5 + (chaos * -2.0)), doneAction:2);
    var mod   = SinOsc.ar((freq + drift + lfo) * 1.4142, 0, freq * modDepth * (2.0 + (chaos * 6.0)));
    var car   = SinOsc.ar(freq + mod + drift);
    var rm    = SinOsc.ar(freq * 0.5 + (drift * 1.618));
    var sig   = (car * rm * 0.7 + (car * 0.3)) * amp * env;
    sig       = FreeVerb.ar(sig, 0.4 + (chaos * 0.5), 0.85 + (chaos * 0.14), 0.3);
    Out.ar(out, Pan2.ar(sig, pan - (chaos * 0.35)));
  }}).add;

  // TOOL: Ringz bank with golden-ratio partial spacing — metallic, wrong, perfect
  SynthDef(\\tool_mt, {{
    |out=0, amp=0.5, freq=500, chaos=0.0|
    var exc = Impulse.ar(0) + (WhiteNoise.ar(0.08) * EnvGen.kr(Env.perc(0, 0.015)));
    var env = EnvGen.kr(Env.perc(0.001, 0.6 + (chaos * 0.8)), doneAction:2);
    var sig = (Ringz.ar(exc, freq,         0.90) * 0.35)
            + (Ringz.ar(exc, freq * 1.618, 0.55) * 0.28)
            + (Ringz.ar(exc, freq * 2.618, 0.35) * 0.20)
            + (Ringz.ar(exc, freq * 4.236, 0.20) * 0.12)
            + (Ringz.ar(exc, freq * 6.854, 0.12) * 0.05);
    Out.ar(out, Pan2.ar(sig * amp * env, LFNoise0.kr(1)));
  }}).add;

  // BASS: slow sustained FM bass — harmonically anchors each session
  SynthDef(\\bass_mt, {{
    |out=0, freq=55, amp=0.18, dur=3.0, chaos=0.0|
    var drift = LFNoise1.kr(0.08) * chaos * freq * 0.04;
    var mod   = SinOsc.ar(freq * 1.5 + drift, 0, freq * (0.4 + (chaos * 0.8)));
    var sig   = SinOsc.ar(freq + mod + drift) * amp;
    var env   = EnvGen.kr(Env.linen(0.15, dur - 0.6, 0.45), doneAction:2);
    sig       = FreeVerb.ar(sig * env, 0.25, 0.7, 0.6);
    Out.ar(out, sig ! 2);
  }}).add;

  // BELL: long-decay Ringz pings — high shimmer layer, very sparse
  SynthDef(\\bell_mt, {{
    |out=0, freq=880, amp=0.12, chaos=0.0, pan=0.0|
    var phi = 1.6180339887;
    var exc = Impulse.ar(0);
    var env = EnvGen.kr(Env.perc(0.001, 4.0 + (chaos * 3.0)), doneAction:2);
    var sig = (Ringz.ar(exc, freq,         2.5) * 0.50)
            + (Ringz.ar(exc, freq * phi,   1.5) * 0.30)
            + (Ringz.ar(exc, freq * 2.618, 0.8) * 0.20);
    Out.ar(out, Pan2.ar(sig * amp * env, pan));
  }}).add;

  // COWBELL: i got a fever, and the only prescription is more cowbell
  // classic two-oscillator synthesis (CR-78 style), slightly retuned per session
  SynthDef(\\cowbell_mt, {{
    |out=0, freq=562, amp=0.35, chaos=0.0, pan=0.0|
    var sig = (Pulse.ar(freq, 0.5) + Pulse.ar(freq * 1.5028, 0.5)) * 0.5;
    var env = EnvGen.kr(Env.perc(0.001, 0.12 + (chaos * 0.09), 1, -12), doneAction:2);
    sig     = BPF.ar(sig, 2500, 0.6) * env * amp;
    Out.ar(out, Pan2.ar(sig, pan));
  }}).add;

  // PAD: 7-partial 11-limit cluster, each partial drifting independently
  SynthDef(\\pad_mt, {{
    |out=0, freq=55, amp=0.1, dur=2.5, chaos=0.0|
    var d0  = LFNoise1.kr(0.07) * chaos * freq * 0.06;
    var d1  = LFNoise1.kr(0.18) * chaos * freq * 0.06;
    var d2  = LFNoise1.kr(0.25) * chaos * freq * 0.06;
    var d3  = LFNoise1.kr(0.36) * chaos * freq * 0.06;
    var d4  = LFNoise1.kr(0.43) * chaos * freq * 0.06;
    var d5  = LFNoise1.kr(0.51) * chaos * freq * 0.06;
    var d6  = LFNoise1.kr(0.62) * chaos * freq * 0.06;
    var sig = (SinOsc.ar(freq * 1.000 + d0)
             + SinOsc.ar(freq * 1.125 + d1)
             + SinOsc.ar(freq * 1.200 + d2)
             + SinOsc.ar(freq * 1.375 + d3)
             + SinOsc.ar(freq * 1.500 + d4)
             + SinOsc.ar(freq * 1.600 + d5)
             + SinOsc.ar(freq * 1.750 + d6)) * (amp / 7);
    var env = EnvGen.kr(Env.linen(0.6, dur, 1.2), doneAction:2);
    sig     = FreeVerb.ar(sig * env, 0.75, 0.95, 0.2);
    Out.ar(out, sig ! 2);
  }}).add;

  // DRONE: harmonic series with beating partials — blooms under everything
  SynthDef(\\drone_mt, {{
    |out=0, freq=55, amp=0.05, dur=60, chaos=0.0|
    var b0  = LFNoise1.kr(0.04) * chaos * 3.0;
    var b1  = LFNoise1.kr(0.06) * chaos * 3.0;
    var b2  = LFNoise1.kr(0.05) * chaos * 3.0;
    var b3  = LFNoise1.kr(0.03) * chaos * 3.0;
    var b4  = LFNoise1.kr(0.07) * chaos * 3.0;
    var sig = (SinOsc.ar(freq * 1.000 + b0) * 0.50)
            + (SinOsc.ar(freq * 1.500 + b1) * 0.25)
            + (SinOsc.ar(freq * 1.750 + b2) * 0.17)
            + (SinOsc.ar(freq * 1.375 + b3) * 0.12)
            + (SinOsc.ar(freq * 2.000 + b4) * 0.08);
    var env = EnvGen.kr(Env.linen(4.0, dur - 8.0, 4.0), doneAction:2);
    sig     = FreeVerb.ar(sig * amp * env, 0.8, 0.97, 0.4);
    Out.ar(out, sig ! 2);
  }}).add;

  s.sync;

  Routine({{
    // Drone blooms first
    Synth(\\drone_mt, [
      \\freq,  55,
      \\amp,   0.05,
      \\dur,   sessions.size * 9.0,
      \\chaos, 0.3,
    ]);
    2.5.wait;

    sessions.do({{|session, sessionIdx|
      var title    = session[0];
      var messages = session[1];
      var chaos    = session[2];

      // Each session has its own tonal centre
      var sessionRoot = scale[sessionIdx % 7] * 0.5;
      var rootMult    = sessionRoot / root;

      // Personality derived from message count — chatty ≠ quiet
      var density  = messages.size;
      var modDepth = 0.7 + ((density % 7) * 0.2);
      var speed    = 0.4 + ((density % 5) * 0.35);
      var pulse    = primes[(sessionIdx + 2) % 8] * 4.0;

      // Five independent layer forks
      var percActive = true;
      var bassActive = true;
      var bellActive = true;
      var cmActive   = true;
      var cowActive  = true;
      var percIdx    = 0;
      var bassIdx    = 0;
      var bellIdx    = 0;
      var cmIdx      = 0;
      var cowIdx     = 0;

      ("\\n👽  " ++ title ++ "  [" ++ sessionRoot.round(0.1).asString ++ " Hz  " ++ pulse.round(0.01).asString ++ "s pulse]").postln;

      Synth(\\pad_mt, [\\freq, sessionRoot * 0.5, \\amp, 0.08, \\dur, 2.2, \\chaos, chaos]);
      2.2.wait;

      // Layer 1: percussion groove — steady pulse, pitch walks JI scale
      fork {{
        while {{ percActive }} {{
          Synth(\\tool_mt, [
            \\amp,   0.15 + (chaos * 0.10),
            \\freq,  scale[(percIdx + sessionIdx) % 7] * rootMult * (2 ** (percIdx % 3)),
            \\chaos, chaos,
          ]);
          pulse.wait;
          percIdx = percIdx + 1;
        }};
      }};

      // Layer 2: bass — slow sustained notes walking root harmonics
      fork {{
        var bassNotes = [1.0, 1.5, 0.667, 0.75];
        while {{ bassActive }} {{
          Synth(\\bass_mt, [
            \\freq,  sessionRoot * bassNotes[bassIdx % 4],
            \\amp,   0.15,
            \\dur,   pulse * 4,
            \\chaos, chaos,
          ]);
          (pulse * 4).wait;
          bassIdx = bassIdx + 1;
        }};
      }};

      // Layer 3: bell shimmer — sparse high pings, long decay, wide stereo
      fork {{
        while {{ bellActive }} {{
          Synth(\\bell_mt, [
            \\freq,  scale[(bellIdx + sessionIdx + 3) % 7] * rootMult * 4,
            \\amp,   0.07 + (chaos * 0.04),
            \\chaos, chaos,
            \\pan,   if((bellIdx % 2) == 0, 0.75, -0.75),
          ]);
          (primes[(bellIdx + 4) % 8] * 3.5).wait;
          bellIdx = bellIdx + 1;
        }};
      }};

      // Layer 4: cowbell — at half-pulse (double time), skips a beat for swing
      fork {{
        while {{ cowActive }} {{
          if((cowIdx % 7) != 3, {{  // skip beat 4 of every 7 — math rock cowbell
            Synth(\\cowbell_mt, [
              \\freq,  530 + (sessionIdx % 7 * 25),  // retuned per session
              \\amp,   0.22 + (chaos * 0.12),
              \\chaos, chaos,
              \\pan,   if((cowIdx % 2) == 0, 0.15, -0.15),
            ]);
          }});
          (pulse * 0.5).wait;
          cowIdx = cowIdx + 1;
        }};
      }};

      // Layer 5: counter-melody — slow wandering line, reads messages out of order
      fork {{
        while {{ cmActive }} {{
          var cmMsg  = messages[(cmIdx * 3 + 7) % density];
          var cmLen  = cmMsg[1];
          var cmDur  = pickDur.(cmLen) * 1.8;
          var cmFreq = pickFreq.(cmLen + 50, (cmIdx % 2) == 0, rootMult);
          if(cmLen > 0, {{
            if((cmIdx % 2) == 0, {{
              Synth(\\you_mt, [
                \\freq,     cmFreq,
                \\amp,      0.09,
                \\dur,      cmDur,
                \\chaos,    chaos,
                \\modDepth, modDepth * 0.5,
                \\pan,      0.2,
              ]);
            }}, {{
              Synth(\\claudia_mt, [
                \\freq,     cmFreq,
                \\amp,      0.08,
                \\dur,      cmDur * 1.3,
                \\chaos,    chaos,
                \\modDepth, modDepth * 0.4,
                \\speed,    speed * 0.6,
                \\pan,      -0.2,
              ]);
            }});
          }});
          (cmDur * 0.65).wait;
          cmIdx = cmIdx + 1;
        }};
      }};

      messages.do({{|msg|
        var role      = msg[0];
        var textLen   = msg[1];
        var toolCount = msg[2];
        var isUser    = role == 0;
        var freq      = pickFreq.(textLen, isUser, rootMult);
        var dur       = pickDur.(textLen);
        var harmFreq  = if(isUser, {{ freq * 2 / 3 }}, {{ freq * 4 / 3 }});

        // Explicit tool hits stack on top of the groove layer
        if(toolCount > 0, {{
          fork {{
            toolCount.do({{|i|
              (dur / (toolCount + 1)).wait;
              Synth(\\tool_mt, [
                \\amp,   0.28,
                \\freq,  scale[(i + textLen) % 7] * rootMult * (2 ** ((i % 3) + 1)),
                \\chaos, chaos,
              ]);
            }});
          }};
        }});

        // Main voice
        if(isUser, {{
          Synth(\\you_mt, [
            \\freq,     freq,
            \\amp,      0.22,
            \\dur,      dur,
            \\chaos,    chaos,
            \\modDepth, modDepth,
            \\pan,      0.3 + (chaos * 0.55),
          ]);
        }}, {{
          Synth(\\claudia_mt, [
            \\freq,     freq,
            \\amp,      0.18,
            \\dur,      dur,
            \\chaos,    chaos,
            \\modDepth, modDepth,
            \\speed,    speed,
            \\pan,      -0.3 - (chaos * 0.55),
          ]);
        }});

        // Harmony voice — ~half of messages, JI interval on opposite side
        if((textLen % 2) == 0, {{
          if(isUser, {{
            Synth(\\claudia_mt, [
              \\freq,     harmFreq,
              \\amp,      0.08,
              \\dur,      dur * 1.4,
              \\chaos,    chaos,
              \\modDepth, modDepth * 0.4,
              \\speed,    speed,
              \\pan,      -0.55,
            ]);
          }}, {{
            Synth(\\you_mt, [
              \\freq,     harmFreq,
              \\amp,      0.07,
              \\dur,      dur * 0.9,
              \\chaos,    chaos,
              \\modDepth, modDepth * 0.4,
              \\pan,      0.55,
            ]);
          }});
        }});

        // 75% overlap — notes breathe into each other
        (dur * 0.75).wait;
        (primes[(textLen + 1) % 8] * 0.25).wait;
      }});

      // Kill all five forks
      percActive = false;
      bassActive = false;
      bellActive = false;
      cmActive   = false;
      cowActive  = false;
      2.3.wait;
    }});

    "\\n👽 The transmission is complete.".postln;
  }}).play;

}});
)
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert Claude sessions to a SuperCollider score")
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT,
                        help="Output .scd file path")
    parser.add_argument("--microtonal", action="store_true",
                        help="Use 11-limit JI scale, golden-ratio FM, prime rhythms, and a drone")
    args = parser.parse_args()

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    print("Loading sessions…")
    sessions = load_all_sessions()
    if not sessions:
        print("No sessions found.")
        return

    total_msgs = sum(len(s["messages"]) for s in sessions)
    print(f"✓ {len(sessions)} sessions · {total_msgs} messages")

    if args.microtonal:
        print("👽 Microtonal mode activated")
        sc_code = generate_sc_microtonal(sessions)
    else:
        sc_code = generate_sc(sessions)

    output.write_text(sc_code, encoding="utf-8")
    print(f"✓ Written to {output}")
    print()
    print("  Next steps:")
    print("  1. brew install --cask supercollider")
    print(f"  2. open {output}")
    print("  3. Cmd+A → Cmd+Return")


if __name__ == "__main__":
    main()
