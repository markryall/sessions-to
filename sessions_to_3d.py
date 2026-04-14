#!/usr/bin/env python3
"""Convert Claude Code sessions into a self-contained 3D galaxy visualisation.

Each session becomes a glowing sphere:
  Position  → golden-angle spiral (x,z) · chaos as vertical height (y)
  Size      → log₂(message count)
  Colour    → chaos: blue (early/calm) → violet → red (late/chaotic)
  Glow halo → proportional to message count
  Trail     → dim line connecting sessions chronologically

Open the generated HTML in any modern browser — no server needed.
Drag to orbit · scroll to zoom · hover to inspect · click to pause rotation.
"""

import json
import sys
from pathlib import Path

CLAUDE_DIR     = Path.home() / ".claude" / "projects"
DEFAULT_OUTPUT = Path(__file__).parent / "tmp" / "sessions_3d.html"


# ── Parsing ───────────────────────────────────────────────────────────────────

def build_global_index(base_dir):
    index_map = {}
    for project_dir in base_dir.iterdir():
        idx_path = project_dir / "sessions-index.json"
        if idx_path.exists():
            try:
                with open(idx_path) as f:
                    for entry in json.load(f).get("entries", []):
                        sid = entry.get("sessionId")
                        if sid:
                            index_map[sid] = entry
            except Exception:
                pass
    return index_map


def parse_session(jsonl_path):
    msg_count  = 0
    tool_count = 0
    first_text = ""
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
                if msg.get("role") not in ("user", "assistant"):
                    continue
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    msg_count += 1
                    if not first_text:
                        first_text = content.strip()
                elif isinstance(content, list):
                    has_text = False
                    for b in content:
                        if isinstance(b, dict):
                            if b.get("type") == "text" and b.get("text", "").strip():
                                has_text = True
                                if not first_text:
                                    first_text = b["text"].strip()
                            elif b.get("type") == "tool_use":
                                tool_count += 1
                    if has_text:
                        msg_count += 1
    except Exception:
        pass
    return msg_count, tool_count, first_text


def load_sessions():
    index_map = build_global_index(CLAUDE_DIR)
    sessions  = []

    for project_dir in sorted(CLAUDE_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            sid = jsonl.stem
            msg_count, tool_count, first_text = parse_session(jsonl)
            if msg_count == 0:
                continue
            meta    = index_map.get(sid, {})
            title   = (meta.get("summary") or meta.get("firstPrompt") or first_text or "Untitled")
            if len(title) > 80:
                title = title[:80] + "…"
            created = meta.get("created", "")
            sessions.append({
                "title":      title,
                "msgCount":   msg_count,
                "toolCount":  tool_count,
                "created":    created,
            })

    sessions.sort(key=lambda s: s["created"])
    n = len(sessions)
    for i, s in enumerate(sessions):
        s["chaos"] = round(i / max(n - 1, 1), 4)
    return sessions


# ── HTML generation ───────────────────────────────────────────────────────────

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sessions — 3D Galaxy</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #000; overflow: hidden; font-family: monospace; color: #8af; }
  canvas { display: block; }

  #tooltip {
    position: fixed; top: 24px; left: 24px;
    max-width: 380px; pointer-events: none;
    line-height: 1.6;
  }
  #tooltip .t-title { font-size: 13px; color: #ccf; margin-bottom: 4px; }
  #tooltip .t-meta  { font-size: 11px; color: #669; }

  #legend {
    position: fixed; bottom: 24px; right: 24px;
    font-size: 11px; color: #446; text-align: right; line-height: 2;
  }
  #legend canvas { display: inline-block; vertical-align: middle; margin-left: 6px; }

  #hint {
    position: fixed; bottom: 24px; left: 50%;
    transform: translateX(-50%);
    font-size: 11px; color: #334; pointer-events: none;
  }

  #stats {
    position: fixed; top: 24px; right: 24px;
    font-size: 11px; color: #446; text-align: right; line-height: 1.8;
  }
</style>
</head>
<body>

<div id="tooltip"></div>
<div id="stats"></div>
<div id="hint">drag to orbit &nbsp;·&nbsp; scroll to zoom &nbsp;·&nbsp; click to pause rotation</div>
<div id="legend"></div>

<script type="importmap">
{
  "imports": {
    "three":          "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
    "three/addons/":  "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
  }
}
</script>

<script id="session-data" type="application/json">
SESSION_DATA_PLACEHOLDER
</script>

<script type="module">
import * as THREE       from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const sessions = JSON.parse(document.getElementById('session-data').textContent);
const N        = sessions.length;

// ── Scene ──────────────────────────────────────────────────────────────────
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000510);
scene.fog        = new THREE.FogExp2(0x000510, 0.006);

const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 3000);
camera.position.set(0, 50, 150);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(innerWidth, innerHeight);
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
document.body.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping    = true;
controls.dampingFactor    = 0.05;
controls.autoRotate       = true;
controls.autoRotateSpeed  = 0.25;
controls.minDistance      = 20;
controls.maxDistance      = 500;

// ── Starfield ──────────────────────────────────────────────────────────────
{
  const verts = new Float32Array(6000 * 3);
  for (let i = 0; i < verts.length; i++) verts[i] = (Math.random() - 0.5) * 3000;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(verts, 3));
  scene.add(new THREE.Points(geo, new THREE.PointsMaterial({ color: 0x223355, size: 0.25 })));
}

// ── Colour helper ──────────────────────────────────────────────────────────
function sessionColor(chaos) {
  // blue (0) → violet (0.5) → hot pink/red (1)
  const hue = 0.66 - chaos * 0.56;
  const sat = 0.55 + chaos * 0.45;
  const lit = 0.48 + chaos * 0.22;
  return new THREE.Color().setHSL(hue, sat, lit);
}

// ── Session spheres ────────────────────────────────────────────────────────
const meshes   = [];
const positions = [];  // for the trail line

const GOLDEN_ANGLE = Math.PI * 2 * 0.6180339887;

sessions.forEach((s, i) => {
  const angle  = i * GOLDEN_ANGLE;
  const radius = 10 + i * 0.55;
  const x      = Math.cos(angle) * radius;
  const z      = Math.sin(angle) * radius;
  const y      = (s.chaos - 0.5) * 80;   // chaos → vertical height

  const size  = Math.log2(s.msgCount + 2) * 0.55;
  const color = sessionColor(s.chaos);

  // Core sphere
  const geo  = new THREE.SphereGeometry(size, 14, 14);
  const mat  = new THREE.MeshBasicMaterial({ color });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.position.set(x, y, z);
  mesh.userData = s;
  scene.add(mesh);
  meshes.push(mesh);
  positions.push(new THREE.Vector3(x, y, z));

  // Glow halo — larger, transparent
  const haloMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.12 });
  const halo    = new THREE.Mesh(new THREE.SphereGeometry(size * 2.8, 8, 8), haloMat);
  halo.position.set(x, y, z);
  scene.add(halo);

  // Point light per session
  const light = new THREE.PointLight(color, 1.2, size * 18);
  light.position.set(x, y, z);
  scene.add(light);
});

// ── Trail line ─────────────────────────────────────────────────────────────
{
  const geo = new THREE.BufferGeometry().setFromPoints(positions);
  const mat = new THREE.LineBasicMaterial({ color: 0x112244, opacity: 0.35, transparent: true });
  scene.add(new THREE.Line(geo, mat));
}

// ── Stats panel ────────────────────────────────────────────────────────────
{
  const totalMsgs  = sessions.reduce((a, s) => a + s.msgCount,  0);
  const totalTools = sessions.reduce((a, s) => a + s.toolCount, 0);
  document.getElementById('stats').innerHTML =
    `${N} sessions<br>${totalMsgs.toLocaleString()} messages<br>${totalTools.toLocaleString()} tool calls`;
}

// ── Legend ─────────────────────────────────────────────────────────────────
{
  const c = document.createElement('canvas');
  c.width = 120; c.height = 12;
  const ctx = c.getContext('2d');
  const grad = ctx.createLinearGradient(0, 0, 120, 0);
  grad.addColorStop(0,    '#3366ff');
  grad.addColorStop(0.5,  '#aa44dd');
  grad.addColorStop(1.0,  '#ff3366');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 120, 12);
  document.getElementById('legend').innerHTML =
    'early &nbsp;' + c.outerHTML + '&nbsp; chaotic<br>size = message count';
}

// ── Raycasting ─────────────────────────────────────────────────────────────
const raycaster = new THREE.Raycaster();
const mouse     = new THREE.Vector2(-9, -9);
const tooltip   = document.getElementById('tooltip');
let   autoRotate = true;

window.addEventListener('mousemove', e => {
  mouse.x =  (e.clientX / innerWidth)  * 2 - 1;
  mouse.y = -(e.clientY / innerHeight) * 2 + 1;
});

window.addEventListener('click', () => {
  autoRotate = !autoRotate;
  controls.autoRotate = autoRotate;
});

// ── Animation loop ─────────────────────────────────────────────────────────
const clock = new THREE.Clock();

(function animate() {
  requestAnimationFrame(animate);
  controls.update();

  const t = clock.getElapsedTime();

  // Gentle breathing pulse per sphere
  meshes.forEach((m, i) => {
    const s = 1 + Math.sin(t * 0.7 + i * 0.41) * 0.04;
    m.scale.setScalar(s);
  });

  // Hover detection
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(meshes);
  if (hits.length > 0) {
    const s = hits[0].object.userData;
    tooltip.innerHTML =
      `<div class="t-title">${s.title}</div>` +
      `<div class="t-meta">${s.msgCount} messages &nbsp;·&nbsp; ${s.toolCount} tool calls &nbsp;·&nbsp; chaos ${s.chaos.toFixed(3)}</div>`;
    renderer.domElement.style.cursor = 'pointer';
  } else {
    tooltip.innerHTML = '';
    renderer.domElement.style.cursor = 'default';
  }

  renderer.render(scene, camera);
})();

window.addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
</script>
</body>
</html>
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)

    print("Loading sessions…")
    sessions = load_sessions()
    if not sessions:
        print("No sessions found.")
        return

    total_msgs  = sum(s["msgCount"]  for s in sessions)
    total_tools = sum(s["toolCount"] for s in sessions)
    print(f"✓ {len(sessions)} sessions · {total_msgs} messages · {total_tools} tool calls")

    data_json = json.dumps(sessions, ensure_ascii=False, indent=2)
    html      = HTML_TEMPLATE.replace("SESSION_DATA_PLACEHOLDER", data_json)
    output.write_text(html, encoding="utf-8")

    print(f"✓ Written to {output}")
    print()
    print(f"  open {output}")


if __name__ == "__main__":
    main()
