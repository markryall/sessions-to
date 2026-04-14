#!/usr/bin/env python3
"""Convert Claude Code sessions into a self-contained sparkly stats dashboard."""

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from datetime import date as Date
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "stats.html"


# ── Data collection ───────────────────────────────────────────────────────────

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


def parse_session_stats(jsonl_path):
    """Returns (user_count, asst_count, tool_count, timestamps_list)."""
    user_count = asst_count = tool_count = 0
    timestamps = []
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
                if ts:
                    timestamps.append(ts)
                content = msg.get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_count += 1
                if role == "user":
                    user_count += 1
                else:
                    asst_count += 1
    except Exception:
        pass
    return user_count, asst_count, tool_count, timestamps


def project_display_name(name):
    d = name.replace("-", "/").lstrip("/")
    return d.replace("Users/markryall/", "~/")


# ── Stats computation ─────────────────────────────────────────────────────────

def compute_stats():
    index_map = build_global_index(CLAUDE_DIR)

    sessions_by_date  = defaultdict(int)
    sessions_by_month = defaultdict(int)
    sessions_by_hour  = defaultdict(int)
    sessions_by_dow   = defaultdict(int)
    project_counts    = defaultdict(int)
    session_msg_counts = []

    total_sessions = total_user = total_asst = total_tools = 0
    all_dates = set()

    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        pname = project_dir.name
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            sid = jsonl.stem
            u, a, t, tss = parse_session_stats(jsonl)
            if u + a == 0:
                continue

            meta = index_map.get(sid, {})
            created = meta.get("created", "") or (tss[0] if tss else "")
            if not created:
                continue

            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except Exception:
                continue

            ds = dt.strftime("%Y-%m-%d")
            ms = dt.strftime("%Y-%m")

            sessions_by_date[ds]    += 1
            sessions_by_month[ms]   += 1
            sessions_by_hour[dt.hour] += 1
            sessions_by_dow[dt.weekday()] += 1
            project_counts[pname]   += 1
            session_msg_counts.append(u + a)
            all_dates.add(ds)
            total_sessions += 1
            total_user  += u
            total_asst  += a
            total_tools += t

    if not total_sessions:
        return {"total_sessions": 0}

    # Streak calculation
    sorted_dates = sorted(all_dates)
    longest = cur = 1
    for i in range(1, len(sorted_dates)):
        d1 = Date.fromisoformat(sorted_dates[i - 1])
        d2 = Date.fromisoformat(sorted_dates[i])
        if (d2 - d1).days == 1:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 1

    today = Date.today()
    cur_streak = 0
    d = today
    while d.isoformat() in all_dates:
        cur_streak += 1
        d -= timedelta(days=1)
    if cur_streak == 0:
        d = today - timedelta(days=1)
        while d.isoformat() in all_dates:
            cur_streak += 1
            d -= timedelta(days=1)

    most_active = max(sessions_by_date.items(), key=lambda x: x[1])

    top_projects = sorted(project_counts.items(), key=lambda x: -x[1])[:12]
    top_projects = [{"name": n, "display": project_display_name(n), "count": c}
                    for n, c in top_projects]

    buckets = {"1": 0, "2–5": 0, "6–10": 0, "11–20": 0, "21+": 0}
    for n in session_msg_counts:
        if   n == 1:  buckets["1"]     += 1
        elif n <= 5:  buckets["2–5"]   += 1
        elif n <= 10: buckets["6–10"]  += 1
        elif n <= 20: buckets["11–20"] += 1
        else:         buckets["21+"]   += 1

    # Fill month range with zeros
    if sorted_dates:
        first_month = sorted_dates[0][:7]
        last_month  = sorted_dates[-1][:7]
        y, m = map(int, first_month.split("-"))
        ey, em = map(int, last_month.split("-"))
        month_range = {}
        while (y, m) <= (ey, em):
            k = f"{y}-{m:02d}"
            month_range[k] = sessions_by_month.get(k, 0)
            m += 1
            if m > 12:
                m = 1
                y += 1
    else:
        month_range = {}

    return {
        "total_sessions":      total_sessions,
        "total_user_messages": total_user,
        "total_asst_messages": total_asst,
        "total_tool_uses":     total_tools,
        "total_days":          len(all_dates),
        "total_projects":      len(project_counts),
        "avg_msgs_per_session": round((total_user + total_asst) / total_sessions, 1),
        "longest_streak":      longest,
        "current_streak":      cur_streak,
        "most_active_day":     {"date": most_active[0], "count": most_active[1]},
        "sessions_by_date":    dict(sessions_by_date),
        "sessions_by_month":   month_range,
        "sessions_by_hour":    {str(h): sessions_by_hour.get(h, 0) for h in range(24)},
        "sessions_by_dow":     {str(d): sessions_by_dow.get(d, 0) for d in range(7)},
        "top_projects":        top_projects,
        "length_buckets":      buckets,
        "first_session":       sorted_dates[0]  if sorted_dates else "",
        "last_session":        sorted_dates[-1] if sorted_dates else "",
    }


# ── HTML template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Stats 💜</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:          #0a0010;
  --bg2:         #0f0018;
  --bg3:         #140020;
  --pink:        #ff69b4;
  --pink-dim:    #ff69b488;
  --pink-faint:  #ff69b422;
  --purple:      #8a2be2;
  --purple-dim:  #8a2be266;
  --lavender:    #da8fff;
  --text:        #f0d6f5;
  --text-dim:    #bb99cc;
  --text-faint:  #88449966;
  --border:      #ff69b433;
  --muted:       #9966aa;
}

html { scroll-behavior: smooth; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  min-height: 100vh;
}

/* ── Header ── */
.header {
  background: linear-gradient(135deg, #1a002e 0%, #2d0044 50%, #1a002e 100%);
  border-bottom: 2px solid transparent;
  border-image: linear-gradient(90deg, transparent, var(--pink), var(--lavender), var(--pink), transparent) 1;
  padding: 1.5rem 2rem;
  text-align: center;
  position: relative;
  overflow: hidden;
}

.header::before {
  content: '✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦ ✧ ✦';
  position: absolute;
  top: 6px; left: 0; right: 0;
  font-size: 0.5rem;
  color: #ff69b420;
  letter-spacing: 1.4rem;
  pointer-events: none;
}

.header h1 {
  font-size: 2.2rem;
  font-weight: 800;
  background: linear-gradient(135deg, var(--pink), var(--lavender), #ff1493, var(--pink));
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: shimmer 4s linear infinite;
  letter-spacing: -0.02em;
}

.header .subtitle {
  font-size: 0.85rem;
  color: var(--text-dim);
  margin-top: 0.35rem;
}

/* ── Layout ── */
.dashboard {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem 1.5rem 4rem;
}

.section {
  margin-bottom: 2.5rem;
}

.section-title {
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--muted);
  margin-bottom: 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.section-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--border), transparent);
}

/* ── Stat cards ── */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.75rem;
}

.stat-card {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1rem 1.25rem;
  position: relative;
  overflow: hidden;
  transition: transform 0.15s, box-shadow 0.15s;
}

.stat-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, var(--pink-faint), transparent 60%);
  pointer-events: none;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 20px var(--pink-faint);
}

.stat-icon {
  font-size: 1.4rem;
  margin-bottom: 0.4rem;
  display: block;
}

.stat-value {
  font-size: 1.8rem;
  font-weight: 800;
  background: linear-gradient(135deg, var(--pink), var(--lavender));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1;
  margin-bottom: 0.25rem;
}

.stat-label {
  font-size: 0.72rem;
  color: var(--text-dim);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.stat-card.highlight {
  border-color: var(--pink-dim);
  box-shadow: 0 0 20px var(--pink-faint);
}

.stat-card.highlight .stat-value {
  background: linear-gradient(135deg, #ff69b4, #ff1493);
  -webkit-background-clip: text;
  background-clip: text;
}

/* ── Heatmap ── */
.heatmap-scroll {
  overflow-x: auto;
  padding-bottom: 0.5rem;
}

.heatmap-scroll::-webkit-scrollbar { height: 4px; }
.heatmap-scroll::-webkit-scrollbar-track { background: transparent; }
.heatmap-scroll::-webkit-scrollbar-thumb { background: var(--purple-dim); border-radius: 2px; }

#heatmap {
  display: grid;
  grid-template-rows: repeat(7, 12px);
  grid-auto-flow: column;
  grid-auto-columns: 12px;
  gap: 2px;
  width: max-content;
}

.hm-cell {
  width: 12px;
  height: 12px;
  border-radius: 2px;
  cursor: default;
  transition: transform 0.1s;
}

.hm-cell:hover { transform: scale(1.3); }

.heatmap-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 0.6rem;
  font-size: 0.68rem;
  color: var(--text-faint);
}

.heatmap-legend {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 0.65rem;
  color: var(--muted);
}

.heatmap-legend span { display: block; width: 12px; height: 12px; border-radius: 2px; }

/* ── Chart cards ── */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
  margin-bottom: 2.5rem;
}

.chart-card {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.25rem;
  overflow: hidden;
}

.chart-title {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--muted);
  margin-bottom: 0.9rem;
}

.chart-area { width: 100%; }
.chart-area svg { display: block; overflow: visible; }

/* ── Projects ── */
.proj-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.55rem;
}

.proj-label {
  font-size: 0.72rem;
  color: var(--text-dim);
  width: 200px;
  flex-shrink: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.proj-track {
  flex: 1;
  height: 14px;
  background: var(--bg3);
  border-radius: 7px;
  overflow: hidden;
  position: relative;
}

.proj-fill {
  height: 100%;
  border-radius: 7px;
  background: linear-gradient(90deg, var(--purple), var(--pink));
  transition: width 0.4s ease;
  position: relative;
}

.proj-fill::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.12));
}

.proj-count {
  font-size: 0.7rem;
  color: var(--pink);
  font-weight: 600;
  width: 30px;
  text-align: right;
  flex-shrink: 0;
}

/* ── Breakdown ── */
.breakdown-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
}

.breakdown-card {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.25rem;
  text-align: center;
}

.bd-num {
  font-size: 2rem;
  font-weight: 800;
  line-height: 1;
  margin-bottom: 0.3rem;
}

.bd-label {
  font-size: 0.72rem;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.bd-sub {
  font-size: 0.65rem;
  color: var(--muted);
  margin-top: 0.2rem;
}

/* ── Animations ── */
@keyframes shimmer {
  0%   { background-position: 0% center; }
  100% { background-position: 200% center; }
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

.stat-card { animation: fadeUp 0.35s ease both; }

/* Stagger cards */
.stat-card:nth-child(1)  { animation-delay: 0.05s; }
.stat-card:nth-child(2)  { animation-delay: 0.10s; }
.stat-card:nth-child(3)  { animation-delay: 0.15s; }
.stat-card:nth-child(4)  { animation-delay: 0.20s; }
.stat-card:nth-child(5)  { animation-delay: 0.25s; }
.stat-card:nth-child(6)  { animation-delay: 0.30s; }
.stat-card:nth-child(7)  { animation-delay: 0.35s; }
.stat-card:nth-child(8)  { animation-delay: 0.40s; }

/* Scrollbar */
* { scrollbar-width: thin; scrollbar-color: var(--purple-dim) transparent; }
</style>
</head>
<body>

<header class="header">
  <h1>✨ Claude Wrapped 💜</h1>
  <div class="subtitle" id="headerSub"></div>
</header>

<div class="dashboard">

  <!-- Stat cards -->
  <div class="section">
    <div class="section-title">Overview</div>
    <div class="stat-grid" id="statGrid"></div>
  </div>

  <!-- Activity heatmap -->
  <div class="section">
    <div class="section-title">Activity ✦ last 52 weeks</div>
    <div class="heatmap-scroll">
      <div id="heatmap"></div>
    </div>
    <div class="heatmap-footer">
      <span id="heatmapRange"></span>
      <div class="heatmap-legend">
        <span>Less</span>
        <span style="background:#1a0030"></span>
        <span style="background:#4a0070"></span>
        <span style="background:#8a00cc"></span>
        <span style="background:#cc44ff"></span>
        <span style="background:#ff69b4"></span>
        <span>More</span>
      </div>
    </div>
  </div>

  <!-- 4 charts -->
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-title">Sessions by Month</div>
      <div class="chart-area" id="chartMonth"></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Hour of Day</div>
      <div class="chart-area" id="chartHour"></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Day of Week</div>
      <div class="chart-area" id="chartDow"></div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Session Length (messages)</div>
      <div class="chart-area" id="chartLength"></div>
    </div>
  </div>

  <!-- Top projects -->
  <div class="section">
    <div class="section-title">Top Projects</div>
    <div id="projects"></div>
  </div>

  <!-- Message breakdown -->
  <div class="section">
    <div class="section-title">Message Breakdown</div>
    <div class="breakdown-grid" id="breakdown"></div>
  </div>

</div>

<script>
const S = __STATS_JSON__;

// ── Helpers ──────────────────────────────────────────────────────────────────
function fmt(n) {
  return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n);
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function fmtDate(ds) {
  if (!ds) return '';
  const [y, m, d] = ds.split('-');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${months[+m-1]} ${+d}, ${y}`;
}

// ── Stat cards ───────────────────────────────────────────────────────────────
function renderStatCards() {
  const grid = document.getElementById('statGrid');
  const cards = [
    { icon: '💬', value: fmt(S.total_sessions),       label: 'Sessions',          highlight: false },
    { icon: '📨', value: fmt(S.total_user_messages + S.total_asst_messages),
                                                        label: 'Messages',          highlight: false },
    { icon: '📅', value: S.total_days,                 label: 'Days Active',       highlight: false },
    { icon: '📁', value: S.total_projects,             label: 'Projects',          highlight: false },
    { icon: '⚡', value: S.avg_msgs_per_session,       label: 'Avg msgs/session',  highlight: false },
    { icon: '🔧', value: fmt(S.total_tool_uses),       label: 'Tool Uses',         highlight: false },
    { icon: '🔥', value: `${S.current_streak}d`,       label: 'Current Streak',    highlight: S.current_streak > 1 },
    { icon: '✦',  value: `${S.longest_streak}d`,       label: 'Longest Streak',    highlight: false },
  ];
  grid.innerHTML = cards.map(c => `
    <div class="stat-card ${c.highlight ? 'highlight' : ''}">
      <span class="stat-icon">${c.icon}</span>
      <div class="stat-value">${c.value}</div>
      <div class="stat-label">${c.label}</div>
    </div>
  `).join('');
}

// ── Activity heatmap ─────────────────────────────────────────────────────────
function heatColor(n) {
  if (n === 0) return '#1a0030';
  if (n === 1) return '#4a0070';
  if (n <= 3)  return '#8a00cc';
  if (n <= 6)  return '#cc44ff';
  return '#ff69b4';
}

function renderHeatmap() {
  const grid   = document.getElementById('heatmap');
  const range  = document.getElementById('heatmapRange');
  const today  = new Date();
  today.setHours(0, 0, 0, 0);

  // Start 52 weeks ago, snapped to Monday
  const start = new Date(today);
  start.setDate(start.getDate() - 52 * 7);
  const dow = start.getDay(); // 0=Sun
  start.setDate(start.getDate() - (dow === 0 ? 6 : dow - 1));

  const d = new Date(start);
  const byDate = S.sessions_by_date;

  while (d <= today) {
    const key   = d.toISOString().slice(0, 10);
    const count = byDate[key] || 0;
    const cell  = document.createElement('div');
    cell.className = 'hm-cell';
    cell.style.background = heatColor(count);
    cell.title = `${key}: ${count} session${count !== 1 ? 's' : ''}`;
    grid.appendChild(cell);
    d.setDate(d.getDate() + 1);
  }

  const startStr = start.toLocaleDateString('en-GB', { day:'numeric', month:'short', year:'numeric' });
  const todayStr = today.toLocaleDateString('en-GB', { day:'numeric', month:'short', year:'numeric' });
  range.textContent = `${startStr} — ${todayStr}`;
}

// ── SVG bar chart ────────────────────────────────────────────────────────────
function renderBarChart(containerId, labels, values, opts = {}) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const W   = container.clientWidth || 280;
  const H   = opts.height || 100;
  const pad = opts.pad ?? 28;
  const n   = labels.length;
  const maxV = Math.max(...values, 1);
  const barW = Math.max(2, Math.floor((W - pad) / n) - 2);
  const totalW = n * (barW + 2);
  const xOff = Math.floor((W - totalW) / 2);

  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', W);
  svg.setAttribute('height', H + pad);
  svg.setAttribute('viewBox', `0 0 ${W} ${H + pad}`);

  // Gradient def
  const defs = document.createElementNS(ns, 'defs');
  const grad = document.createElementNS(ns, 'linearGradient');
  grad.setAttribute('id', `bg_${containerId}`);
  grad.setAttribute('x1', '0'); grad.setAttribute('y1', '0');
  grad.setAttribute('x2', '0'); grad.setAttribute('y2', '1');
  const s1 = document.createElementNS(ns, 'stop');
  s1.setAttribute('offset', '0%');
  s1.setAttribute('stop-color', opts.colorTop || '#ff69b4');
  const s2 = document.createElementNS(ns, 'stop');
  s2.setAttribute('offset', '100%');
  s2.setAttribute('stop-color', opts.colorBot || '#8a2be2');
  grad.appendChild(s1); grad.appendChild(s2);
  defs.appendChild(grad);
  svg.appendChild(defs);

  // Baseline
  const base = document.createElementNS(ns, 'line');
  base.setAttribute('x1', 0); base.setAttribute('y1', H);
  base.setAttribute('x2', W); base.setAttribute('y2', H);
  base.setAttribute('stroke', '#ff69b422'); base.setAttribute('stroke-width', '1');
  svg.appendChild(base);

  labels.forEach((lbl, i) => {
    const v    = values[i] || 0;
    const bH   = Math.max(v > 0 ? 2 : 0, Math.round((v / maxV) * H));
    const x    = xOff + i * (barW + 2);
    const y    = H - bH;

    const rect = document.createElementNS(ns, 'rect');
    rect.setAttribute('x', x);
    rect.setAttribute('y', y);
    rect.setAttribute('width', barW);
    rect.setAttribute('height', bH);
    rect.setAttribute('rx', Math.min(3, barW / 2));
    rect.setAttribute('fill', `url(#bg_${containerId})`);
    rect.setAttribute('opacity', v === 0 ? '0.15' : '0.85');

    const title = document.createElementNS(ns, 'title');
    title.textContent = `${lbl}: ${v}`;
    rect.appendChild(title);
    svg.appendChild(rect);

    if (opts.showLabels !== false && n <= 32) {
      const txt = document.createElementNS(ns, 'text');
      txt.setAttribute('x', x + barW / 2);
      txt.setAttribute('y', H + 18);
      txt.setAttribute('text-anchor', 'middle');
      txt.setAttribute('font-size', n > 20 ? '7' : '8.5');
      txt.setAttribute('fill', '#9966aa');
      txt.setAttribute('font-family', 'Inter, sans-serif');
      txt.textContent = lbl;
      svg.appendChild(txt);
    }
  });

  container.appendChild(svg);
}

// ── Charts ───────────────────────────────────────────────────────────────────
function renderCharts() {
  // By month
  const months = Object.keys(S.sessions_by_month);
  const mLabels = months.map(m => {
    const [, mo] = m.split('-');
    return ['J','F','M','A','M','J','J','A','S','O','N','D'][+mo - 1];
  });
  renderBarChart('chartMonth', mLabels, months.map(k => S.sessions_by_month[k]));

  // By hour (0-23)
  const hours  = Array.from({length: 24}, (_, i) => i);
  const hLabels = hours.map(h => h % 6 === 0 ? `${h}h` : '');
  renderBarChart('chartHour', hLabels, hours.map(h => S.sessions_by_hour[h] || 0),
    { colorTop: '#da8fff', colorBot: '#ff69b4' });

  // By day of week
  const DOW = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  renderBarChart('chartDow', DOW, DOW.map((_, i) => S.sessions_by_dow[i] || 0),
    { colorTop: '#ff1493', colorBot: '#8a2be2' });

  // Session lengths
  const bKeys = Object.keys(S.length_buckets);
  renderBarChart('chartLength', bKeys, bKeys.map(k => S.length_buckets[k]),
    { colorTop: '#ff69b4', colorBot: '#4a0070' });
}

// ── Top projects ─────────────────────────────────────────────────────────────
function renderProjects() {
  const wrap = document.getElementById('projects');
  const max  = S.top_projects[0]?.count || 1;
  wrap.innerHTML = S.top_projects.map(p => `
    <div class="proj-row">
      <div class="proj-label" title="${esc(p.display)}">${esc(p.display)}</div>
      <div class="proj-track">
        <div class="proj-fill" style="width:${Math.round(p.count / max * 100)}%"></div>
      </div>
      <div class="proj-count">${p.count}</div>
    </div>
  `).join('');
}

// ── Breakdown ────────────────────────────────────────────────────────────────
function renderBreakdown() {
  const wrap = document.getElementById('breakdown');
  const total = S.total_user_messages + S.total_asst_messages;
  const uPct  = total ? Math.round(S.total_user_messages / total * 100) : 0;
  const aPct  = 100 - uPct;

  wrap.innerHTML = `
    <div class="breakdown-card">
      <div class="bd-num" style="background:linear-gradient(135deg,#ff69b4,#ff1493);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">${fmt(S.total_user_messages)}</div>
      <div class="bd-label">🧑 Your Messages</div>
      <div class="bd-sub">${uPct}% of conversation</div>
    </div>
    <div class="breakdown-card">
      <div class="bd-num" style="background:linear-gradient(135deg,var(--lavender),var(--purple));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">${fmt(S.total_asst_messages)}</div>
      <div class="bd-label">💜 Claudia's Messages</div>
      <div class="bd-sub">${aPct}% of conversation</div>
    </div>
    <div class="breakdown-card">
      <div class="bd-num" style="background:linear-gradient(135deg,#9966aa,#da8fff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">${fmt(S.total_tool_uses)}</div>
      <div class="bd-label">🔧 Tool Invocations</div>
      <div class="bd-sub">${total ? (S.total_tool_uses / S.total_sessions).toFixed(1) : 0} per session</div>
    </div>
  `;
}

// ── Header subtitle ───────────────────────────────────────────────────────────
function renderHeader() {
  const sub = document.getElementById('headerSub');
  const first = fmtDate(S.first_session);
  const last  = fmtDate(S.last_session);
  if (first && last && first !== last) {
    sub.textContent = `${first} — ${last}`;
  } else if (first) {
    sub.textContent = first;
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
renderHeader();
renderStatCards();
renderHeatmap();
renderCharts();
renderProjects();
renderBreakdown();
</script>
</body>
</html>
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)

    print("Computing stats…")
    stats = compute_stats()
    if not stats.get("total_sessions"):
        print("No sessions found.")
        return

    print(f"✓ {stats['total_sessions']} sessions · "
          f"{stats['total_days']} days · "
          f"{stats['total_projects']} projects")

    stats_json = json.dumps(stats, ensure_ascii=False)
    stats_json = stats_json.replace("</", "<\\/")
    html = HTML_TEMPLATE.replace("__STATS_JSON__", stats_json)
    output.write_text(html, encoding="utf-8")
    print(f"✓ Written to {output}")


if __name__ == "__main__":
    main()
