"""Offline replay renderer: turn a completed run into shareable artifacts.

    python replay.py --run-id nata [--data-dir /data]

Reads runs/<run_id>/{route.json,walk.jsonl,summary.json,thumbs,frames} and
writes runs/<run_id>/replay/ containing a self-contained index.html:
animated Leaflet polylines for FLY/COIN/GREEDY, per-step flycam, distance
curves, dopamine ledger, summary table, honesty section.

No web server is required afterward - open the file or rsync it anywhere.
"""

import argparse
import json
import os
import shutil

COLORS = {"fly": "#e8710a", "coin": "#9aa0a6", "greedy": "#1a73e8"}

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>flywalker - a fruit fly brain looks for pastel de nata</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0; background: #fafafa; color: #202124; }
  header { padding: 18px 24px 8px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #5f6368; font-size: 13px; }
  #map { height: 420px; margin: 12px 24px; border-radius: 8px; }
  .panel { margin: 10px 24px; padding: 14px 18px; background: #fff; border: 1px solid #e8eaed; border-radius: 8px; }
  #flycam { width: 320px; image-rendering: pixelated; border: 1px solid #dadce0; border-radius: 6px; }
  .row { display: flex; gap: 28px; flex-wrap: wrap; align-items: flex-start; }
  .legend span { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin: 0 6px 0 14px; }
  button { padding: 6px 14px; border-radius: 6px; border: 1px solid #dadce0; background: #fff; cursor: pointer; }
  button:hover { background: #f1f3f4; }
  table { border-collapse: collapse; font-size: 14px; }
  td, th { padding: 6px 14px; border-bottom: 1px solid #e8eaed; text-align: left; }
  .honest { font-size: 12.5px; color: #5f6368; max-width: 720px; line-height: 1.5; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 6px; }
  .reward { background: #e6f4ea; color: #137333; } .aversive { background: #fce8e6; color: #c5221f; }
  #ticklabel { font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
<header>
  <h1>🪰 flywalker: a fruit fly brain (166,700 neurons) tries to find pastel de nata</h1>
  <div class="sub">FLY = MaleCNS v1.0 spike decode &nbsp;·&nbsp; COIN = random &nbsp;·&nbsp; GREEDY = crow-flies instinct. Three walkers, one corridor, honest baselines.</div>
</header>
<div id="map"></div>
<div class="panel">
  <div class="legend">
    <b>Walkers:</b>
    <span style="background:#e8710a"></span> FLY
    <span style="background:#9aa0a6"></span> COIN (random)
    <span style="background:#1a73e8"></span> GREEDY (greedy)
  </div>
  <div style="margin-top:10px">
    <button id="play">▶ play</button>
    <input id="scrub" type="range" min="0" value="0" style="width:52%; vertical-align:middle"/>
    <span id="ticklabel">tick 0 / __MAX_TICK__</span>
  </div>
</div>
<div class="panel row">
  <div>
    <div class="sub">What the fly saw at this step (flycam, 320×180 through its photoreceptor mapping):</div>
    <img id="flycam" src="frames/00000.png" onerror="this.style.visibility='hidden'"/>
  </div>
  <div>
    <div class="sub">Dopamine ledger (progress → PAM11 pulse, regression → PPL101 pulse):</div>
    <div id="ledger" style="max-height:120px; overflow:auto; font-size:12px"></div>
  </div>
</div>
<div class="panel">
  <div class="sub">Distance to goal (m) over the walk:</div>
  __CURVES__
</div>
<div class="panel">
  <h3>Final score</h3>
  <table id="score"></table>
</div>
<div class="panel">
  <h3>Honesty</h3>
  <div class="honest">
    Connectome weights are fixed anatomy, not a living fly. The decoder is an
    engineered mapping (DNp20 left/right differential + DNpe017 gate), not a
    discovery of "walk neurons". Dopamine/aversive pulses are engineered
    reinforcement signals, not modeled pain or pleasure. The visual adapter is
    an explicit display proxy. Most likely the FLY line statistically
    resembles COIN - that is the honest result. Nothing here claims learned
    navigation unless the distance curve beats the random baseline
    reproducibly, and nothing here is neuroscience research.
  </div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const P = __PAYLOAD__;
const COLORS = { fly: "#e8710a", coin: "#9aa0a6", greedy: "#1a73e8" };
const map = L.map("map");
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "© OpenStreetMap contributors · imagery © Mapillary",
  maxZoom: 19
}).addTo(map);
map.fitBounds(L.latLngBounds([P.polylines.fly[0], P.goal]));
L.circleMarker(P.goal, { color: "#137333", radius: 8, fill: true }).addTo(map)
  .bindTooltip("nata");
for (const name of ["fly", "coin", "greedy"]) {
  L.polyline(P.polylines[name], { color: COLORS[name], opacity: 0.35, weight: 3 }).addTo(map);
}
const live = {};
for (const name of ["fly", "coin", "greedy"]) {
  live[name] = L.polyline([P.polylines[name][0]], { color: COLORS[name], weight: 5 }).addTo(map);
}
const markers = {};
for (const name of ["fly", "coin", "greedy"]) {
  markers[name] = L.circleMarker(P.polylines[name][0], { color: COLORS[name], radius: 6, fill: true, fillOpacity: 1 }).addTo(map);
}
const scrub = document.getElementById("scrub");
scrub.max = P.max_tick;
document.getElementById("ticklabel").textContent = "tick 0 / " + P.max_tick;
let playing = false, raf = null;
function render(tick) {
  scrub.value = tick;
  document.getElementById("ticklabel").textContent = "tick " + tick + " / " + P.max_tick;
  for (const name of ["fly", "coin", "greedy"]) {
    const pts = P.series[name];
    let cut = pts.length;
    for (let i = 0; i < pts.length; i++) { if (pts[i].tick > tick) { cut = i; break; } }
    const full = P.polylines[name];
    live[name].setLatLngs(full.slice(0, cut + 1));
    markers[name].setLatLng(full[Math.min(cut, full.length - 1)]);
  }
  const img = document.getElementById("flycam");
  const n = String(tick).padStart(5, "0");
  img.style.visibility = "";
  img.onerror = () => img.style.visibility = "hidden";
  img.src = "frames/" + n + ".png";
}
scrub.addEventListener("input", () => { playing = false; document.getElementById("play").textContent = "▶ play"; render(+scrub.value); });
document.getElementById("play").addEventListener("click", () => {
  playing = !playing;
  document.getElementById("play").textContent = playing ? "⏸ pause" : "▶ play";
  if (playing) step();
});
function step() {
  if (!playing) return;
  const next = (+scrub.value + 1) % (P.max_tick + 1);
  render(next);
  raf = setTimeout(step, 700);
}
const ledgerEl = document.getElementById("ledger");
for (const ev of P.ledger) {
  const span = document.createElement("span");
  span.className = "badge " + ev.sign;
  span.textContent = "t" + ev.tick + " " + ev.sign;
  ledgerEl.appendChild(span);
  ledgerEl.appendChild(document.createTextNode(" "));
}
const table = document.getElementById("score");
table.innerHTML = "<tr><th>walker</th><th>steps</th><th>distance</th><th>arrived</th><th>final distance to goal</th></tr>" +
  ["fly", "coin", "greedy"].map(name => {
    const w = P.summary.walkers[name];
    return "<tr><td style='color:" + COLORS[name] + ";font-weight:600'>" + name + "</td><td>" + w.steps +
      "</td><td>" + (w.distance_m / 1000).toFixed(2) + " km</td><td>" + (w.arrived ? "✓" : "✗") +
      "</td><td>" + (w.final_dist_m / 1000).toFixed(2) + " km</td></tr>";
  }).join("");
render(0);
</script>
</body>
</html>"""



def load(run_dir):
    route = json.load(open(os.path.join(run_dir, "route.json")))
    lines = []
    with open(os.path.join(run_dir, "walk.jsonl")) as f:
        for line in f:
            if line.strip():
                lines.append(json.loads(line))
    with open(os.path.join(run_dir, "summary.json")) as f:
        summary = json.load(f)
    return route, lines, summary


def series_by_walker(lines):
    out = {"fly": [], "coin": [], "greedy": []}
    for rec in lines:
        if rec.get("event") != "move":
            continue
        out[rec["walker"]].append(
            {
                "tick": rec["tick"],
                "lat": rec["lat"],
                "lng": rec["lng"],
                "dist_m": rec["dist_m"],
                "delta_m": rec["delta_m"],
            }
        )
    return out


def dopamine_ledger(lines):
    return [
        {"tick": r["tick"], "sign": r["queued_reinforcement"]}
        for r in lines
        if r.get("event") == "move" and r.get("queued_reinforcement")
    ]


def svg_curve(points, width=560, height=90, color="#e8710a"):
    if len(points) < 2:
        return ""
    lo = min(points)
    hi = max(points)
    span = max(hi - lo, 1e-6)
    step = (width - 20) / (len(points) - 1)
    coords = [
        (10 + i * step, height - 10 - (v - lo) / span * (height - 20))
        for i, v in enumerate(points)
    ]
    path = " ".join(
        ("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}" for i, (x, y) in enumerate(coords)
    )
    return (
        f'<svg width="{width}" height="{height}" style="background:#f8f9fa">'
        f'<path d="{path}" stroke="{color}" stroke-width="2" fill="none"/></svg>'
    )


def render(run_dir):
    route, lines, summary = load(run_dir)
    replay_dir = os.path.join(run_dir, "replay")
    os.makedirs(replay_dir, exist_ok=True)

    # copy frames (flycam) + thumbs referenced by the replay page
    frames_src = os.path.join(run_dir, "frames")
    if os.path.isdir(frames_src):
        shutil.copytree(frames_src, os.path.join(replay_dir, "frames"), dirs_exist_ok=True)

    series = series_by_walker(lines)
    ledger = dopamine_ledger(lines)
    fly_frames = sorted(
        f for f in os.listdir(os.path.join(run_dir, "frames")) if f.endswith(".png")
    ) if os.path.isdir(os.path.join(run_dir, "frames")) else []

    start = route["start_node"]
    start_rec = route["nodes"][start]
    polylines = {
        name: [[start_rec["lat"], start_rec["lng"]]]
        + [[p["lat"], p["lng"]] for p in pts]
        for name, pts in series.items()
    }
    dist_curves = {
        name: [p["dist_m"] for p in series[name]]
        + ([summary["walkers"][name]["final_dist_m"]] if series[name] else [])
        for name in series
    }

    payload = {
        "center": [
            (route["nodes"][route["start_node"]]["lat"] + route["goal"]["lat"]) / 2,
            (route["nodes"][route["start_node"]]["lng"] + route["goal"]["lng"]) / 2,
        ],
        "goal": [route["goal"]["lat"], route["goal"]["lng"]],
        "max_tick": max((p["tick"] for pts in series.values() for p in pts), default=0),
        "polylines": polylines,
        "series": series,
        "summary": summary,
        "ledger": ledger,
    }

    html = PAGE_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":")))
    html = html.replace("__CURVES__", "".join(
        f"<h3 style='color:{COLORS[name]}'>{name}</h3>{svg_curve(dist_curves[name], color=COLORS[name])}<br/>"
        for name in ["fly", "coin", "greedy"] if dist_curves[name]
    ))
    out = os.path.join(replay_dir, "index.html")
    with open(out, "w") as f:
        f.write(html)

    # thumbs are needed by nothing in the static page (frames embed imagery);
    # but we keep route.json alongside for provenance
    shutil.copy(os.path.join(run_dir, "route.json"), os.path.join(replay_dir, "route.json"))
    with open(os.path.join(replay_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"replay written: {out}")


def export_video(run_dir, out_name="flywalk.mp4"):
    raise SystemExit(
        "export_video is a follow-up hook (needs ffmpeg + a frame compositing step); "
        "see docs in replay.py. The static replay page is the v1 artifact."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=os.environ.get("RUN_ID", "nata"))
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "data"))
    args = parser.parse_args()
    render(os.path.join(args.data_dir, "runs", args.run_id))
