"""Offline replay renderer: turn a completed run into a shareable cinematic page.

    python replay.py --run-id nata2 --data-dir local-runs

Reads runs/<run_id>/{route.json,walk.jsonl,summary.json,frames} and writes
runs/<run_id>/replay/ containing a self-contained index.html (only external
dependency: Leaflet 1.9.4 + OpenStreetMap tiles):

- dark cinematic theme, run card with MaleCNS badges and consult stats
- hand-drawn animated fly mark in the header; on the map the FLY walker
  is a fly that turns to its heading
- "what you're looking at" explainer: the cast, the map keys, and why
  the cockpit measures decoded approach in Hz
- junction theater map: subgraph buffered around the walker trails, GREEDY
  ghost path, per-walker GPS-density halos, pulsing nata marker
- what-the-fly-saw cockpit: flycam frame, candidate score bars (A-E),
  DNp20 left/right differential meter, DNpe017 gate, spikes, consult
  latency, reinforcement badge, signed delta pill
- timeline player: play/pause, 0.5/1/2/4x, scrubber with key-moment
  markers, live per-walker distance chips
- synced SVG charts: distance-to-goal with arrival stars + scrub cursor,
  cumulative distance-walked inset
- reinforcement ledger with reward/aversive counts and a data-derived
  honesty chip
- two-column what-is-real / what-is-engineered honesty table

Tiles block the file:// protocol - serve the replay directory instead:

    cd runs/<run_id>/replay && python3 -m http.server 8080

No data collection logic lives here: the page only renders existing
artifacts from the walk.
"""

import argparse
import json
import math
import os
import shutil

COLORS = {"fly": "#e8710a", "coin": "#9aa0a6", "greedy": "#1a73e8"}

RUN_LABELS = {
    "nata": ("Rossio", "Manteigaria", "run v1"),
    "nata2": ("Santa Justa", "Carmo", "run v2"),
}

THEATER_RADIUS_M = 120.0


def haversine_m(a_lat, a_lng, b_lat, b_lng):
    R = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def load(run_dir):
    with open(os.path.join(run_dir, "route.json")) as f:
        route = json.load(f)
    lines = []
    with open(os.path.join(run_dir, "walk.jsonl")) as f:
        for line in f:
            if line.strip():
                lines.append(json.loads(line))
    with open(os.path.join(run_dir, "summary.json")) as f:
        summary = json.load(f)
    return route, lines, summary


def process_lines(lines):
    """Split walk.jsonl into the compact per-walker structures the page
    needs. Every float/datum below already exists in the walk record."""
    series = {"fly": [], "coin": [], "greedy": []}
    trails = {"fly": [], "coin": [], "greedy": []}
    trail_nodes = {"fly": [], "coin": [], "greedy": []}
    fly_cockpit = []
    arrivals = []
    rl = []
    for rec in lines:
        if rec.get("event") == "arrival":
            arrivals.append([rec["tick"], rec["walker"], rec.get("dist_m")])
            continue
        if rec.get("event") != "move":
            continue
        name = rec["walker"]
        series[name].append(
            [rec["tick"], rec["dist_m"], rec["moved_m"], rec["delta_m"]]
        )
        trails[name].append([rec["lat"], rec["lng"]])
        trail_nodes[name].append(rec["node"])
        if name == "fly":
            cands = []
            for c in rec.get("candidates") or []:
                cands.append(
                    [
                        c["letter"],
                        c["node"],
                        c["approach_hz"],
                        c["side"],
                        c["left_hz"],
                        c["right_hz"],
                        c["difference_hz"],
                        c["gate_spikes"],
                        c["total_spikes"],
                        round(c.get("consult_ms") or 0, 0),
                    ]
                )
            entry = {"t": rec["tick"], "n": rec["node"], "c": cands}
            if rec.get("consult_ms_total"):
                entry["ms"] = round(rec["consult_ms_total"], 0)
            sign = rec.get("queued_reinforcement")
            if sign:
                entry["rl"] = sign
                rl.append([rec["tick"], sign])
            fly_cockpit.append(entry)
    return series, trails, trail_nodes, fly_cockpit, arrivals, rl


def theater_subgraph(route, trail_nodes):
    """Nodes/edges within THEATER_RADIUS_M of any walker-visited node, plus
    the GREEDY->goal shortest path (ghost). Compact output: nodes as
    [[lat, lng], ...], edges as index pairs, ghost as indices."""
    nodes = route["nodes"]
    edges = route["edges"]
    start_node = route["start_node"]
    goal_node = route["goal_node"]
    visited = {"fly": [], "coin": [], "greedy": []}
    for name in visited:
        visited[name] = list(dict.fromkeys(trail_nodes[name] + [start_node]))
    visited_uniq = set().union(*visited.values())
    last_greedy = trail_nodes["greedy"][-1] if trail_nodes["greedy"] else start_node

    ghost = []
    if last_greedy != goal_node:
        prev = {last_greedy: None}
        queue = [last_greedy]
        qi = 0
        while qi < len(queue):
            u = queue[qi]
            qi += 1
            if u == goal_node:
                break
            for v in edges.get(u, []):
                if v not in prev:
                    prev[v] = u
                    queue.append(v)
        if goal_node in prev:
            u = goal_node
            while u != last_greedy:
                ghost.append(u)
                u = prev[u]
            ghost.append(last_greedy)
            ghost.reverse()
    ghost_nodes = set(ghost)

    theater = set(visited_uniq) | ghost_nodes
    for nid, node in nodes.items():
        if nid in theater:
            continue
        la, lo = node["lat"], node["lng"]
        for vid in visited_uniq:
            vn = nodes[vid]
            if haversine_m(la, lo, vn["lat"], vn["lng"]) <= THEATER_RADIUS_M:
                theater.add(nid)
                break

    ordered = [n for n in nodes if n in theater]
    index = {n: i for i, n in enumerate(ordered)}
    edge_pairs = []
    for u in ordered:
        for v in edges.get(u, []):
            if v not in index:
                continue
            a, b = index[u], index[v]
            if a < b:
                edge_pairs.append((a, b))
    return {
        "nodes": [[nodes[n]["lat"], nodes[n]["lng"]] for n in ordered],
        "edges": edge_pairs,
        "ghost": [index[n] for n in ghost],
        "visited": {
            name: [[index[n], visited[name].count(n)] for n in dict.fromkeys(visited[name])]
            for name in visited
        },
        "edge_count": sum(len(v) for v in edges.values()),
        "node_count": len(nodes),
    }


def _signed(v):
    """README convention: net = last_dist - first_dist; negative = closer."""
    if v < -0.05:
        return "\u2212%.1f m" % abs(v)
    if v > 0.05:
        return "+%.1f m" % v
    return "0.0 m"


def closeness_stats(series):
    """Honesty numbers derivable from the logs alone."""
    all_ticks = sorted({r[0] for r in series["fly"]} & {r[0] for r in series["coin"]})
    hits = sum(1 for t in all_ticks if
               next(d for (tt, d, m, dl) in series["fly"] if tt == t)
               < next(d for (tt, d, m, dl) in series["coin"] if tt == t))
    first, last = {}, {}
    for name in series:
        rows = series[name]
        first[name] = rows[0][1]
        last[name] = rows[-1][1]
    return {
        "hits": hits,
        "both": len(all_ticks),
        "pct": round(100 * hits / max(len(all_ticks), 1)),
        "fly_net": round(last["fly"] - first["fly"], 1),
        "coin_net": round(last["coin"] - first["coin"], 1),
        "gap": round(last["coin"] - last["fly"], 1),
    }


def honesty_html(summary, close, arrivals, run_id):
    w = summary["walkers"]
    if arrivals:
        arrived = ("; ".join("%s arrived at tick %d (%.1f m from the goal)"
                             % (a[1].upper(), a[0], a[2]) for a in arrivals)
                   + "; the other walkers did not arrive.")
        greedy_arrive = next((a[0] for a in arrivals if a[1] == "greedy"), None)
    else:
        arrived = ("No walker arrived: after %d ticks all three ended ~1,000 m "
                   "from the goal (started at ~990 m), and the corridor's "
                   "spatial graph offers no connected path that reduces "
                   "crow-flies distance to the goal." % summary["ticks"])
        greedy_arrive = None
    if greedy_arrive is not None:
        outcome_eng = (
            "FLY stood closer to the nata than COIN on %d of %d ticks (%d%%), "
            "final distance %s vs COIN %s (ended %.1f m closer), net %s vs "
            "COIN net %s \u2014 a direction-consistent but statistically weak "
            "edge, inseparable from random variation at tick resolution. The "
            "honest read: a real connectome making real decisions on "
            "goal-tinted frames still cannot turn visual salience into "
            "navigation, even on a corridor GREEDY walks in %d steps."
            % (close["hits"], close["both"], close["pct"],
               "%.1f m" % w["fly"]["final_dist_m"], "%.1f m" % w["coin"]["final_dist_m"],
               close["gap"], _signed(close["fly_net"]), _signed(close["coin_net"]),
               greedy_arrive))
    else:
        outcome_eng = (
            "Both brains drifted relative to the goal: FLY net %s, COIN net "
            "%s; FLY stood closer to the goal than COIN on %d of %d ticks "
            "(%d%%). FLY statistically resembles COIN \u2014 the "
            "connectome-driven walker did not beat the random baseline. "
            "GREEDY walked furthest (%d m) and still did not arrive."
            % (_signed(close["fly_net"]), _signed(close["coin_net"]),
               close["hits"], close["both"], close["pct"],
               round(w["greedy"]["distance_m"])))
    lead = (
        "Connectome weights are fixed anatomy, not a living fly. The decoder "
        "is an engineered mapping (DNp20 left/right differential with a "
        "DNpe017 gate), not a discovery of \u201cwalk neurons\u201d. "
        "Dopamine and aversive pulses are engineered reinforcement signals, "
        "not modeled pain or pleasure. The visual adapter is an explicit "
        "display proxy; since v2 it honestly admits the goal-tinted column, "
        "measured inert against the live brain (per-junction corr "
        "\u22120.07, n=32) after the brightness veil proved direction-blind. "
        "Most likely the FLY line statistically resembles COIN \u2014 that "
        "is the honest result. Nothing here claims learned navigation unless "
        "the distance curve beats the random baseline reproducibly, and "
        "nothing here is neuroscience research."
    )
    rows = [
        (
            "The brain behind FLY",
            "MaleCNS v1.0 connectome weights: fixed anatomy, 166,700 neurons "
            "and 25.6M directed connections (Google Research + HHMI Janelia). "
            "Not a living fly.",
            "Engineered mapping inherited from Stonkfly: a DNp20 left/right "
            "differential with a DNpe017 spike gate. Not a discovery of "
            "\u201cwalk neurons\u201d.",
        ),
        (
            "Reward signals",
            "FLY\u2019s moves are the connectome\u2019s spike-decoded output "
            "on real imagery \u2014 this run: %d brain consults, avg %d ms, "
            "p95 %d ms." % (summary["timing"]["total_consults"],
                            summary["timing"]["avg_consult_ms"],
                            summary["timing"]["p95_consult_ms"]),
            "Dopamine (PAM11) and aversive (PPL101) pulses are engineered "
            "reinforcement signals, not modeled pain or pleasure.",
        ),
        (
            "Vision",
            "320\u00d7180 light-background frames of real Lisbon street "
            "imagery (Mapillary), photoreceptor-mapped.",
            "The visual adapter is an explicit display proxy, not retinal "
            "physiology. Since v2 the frames carry a goal meter \u2014 a "
            "chart-ink column encoding each candidate\u2019s distance "
            "reduction \u2014 engineered input, measured inert against the "
            "live brain (per-junction corr \u22120.07, n=32).",
        ),
        ("Outcome", arrived, outcome_eng),
        (
            "Claims",
            "Every logged step happened on real imagery through the real "
            "connectome, or through the honest baselines.",
            "No learned navigation is claimed on either run. Nothing here is "
            "neuroscience research or investment advice.",
        ),
    ]
    row_html = []
    for key, real, eng in rows:
        row_html.append(
            '<div class="row"><div class="k">%s</div>'
            '<div class="col">%s</div><div class="col">%s</div></div>'
            % (key, real, eng)
        )
    return lead, "".join(row_html), arrived


def prov_html(route, summary, run_id, crow_m, label, wall_est, theater):
    w = summary["walkers"]
    walker_rows = []
    for name in ["fly", "coin", "greedy"]:
        wt = w[name]
        walker_rows.append(
            "<tr><td style='color:%s;font-weight:600'>%s</td>"
            "<td>%d</td><td>%.1f m</td><td>%.1f m</td><td>%s</td></tr>"
            % (COLORS[name], name.upper(), wt["steps"], wt["distance_m"],
               wt["final_dist_m"], "yes" if wt["arrived"] else "no")
        )
    fetched = route["fetched_at"]
    if isinstance(fetched, (int, float)):
        import datetime
        fetched = datetime.datetime.fromtimestamp(
            fetched, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return "\n".join(
        [
            "<table><tr><td class='k'>run</td><td>%s (%s) \u00b7 %d ticks \u00b7 "
            "approx wall time %s \u00b7 recorded %s</td></tr>" % (
                run_id, label, summary["ticks"], wall_est, _fmt_ts(summary)),
            "<tr><td class='k'>route</td><td>%s \u00b7 crow-flies %.0f m \u00b7 "
            "graph %d nodes / %d links \u00b7 %d Mapillary frames \u00b7 "
            "fetched %s \u00b7 bbox %s</td></tr>" % (
                label, crow_m, route["node_count"], route["edge_count"],
                route["image_count"], fetched, route["bbox"]),
            "<tr><td class='k'>start</td><td class='nums'>%.6f, %.6f (node %s)</td></tr>" % (
                route["start"]["lat"], route["start"]["lng"], route["start_node"]),
            "<tr><td class='k'>goal</td><td class='nums'>%.6f, %.6f (node %s, %s)</td></tr>" % (
                route["goal"]["lat"], route["goal"]["lng"], route["goal_node"],
                route["source"]),
            "<tr><td class='k'>walkers</td><td><table>"
            "<tr><td></td><td class='k'>steps</td><td class='k'>walked</td>"
            "<td class='k'>final dist</td><td class='k'>arrived</td></tr>"
            + "".join(walker_rows) + "</table></td></tr>",
            "<tr><td class='k'>embedded</td><td>theater subgraph: %d nodes / "
            "%d edges within %.0f m of the trails, plus the GREEDY ghost "
            "path (%d nodes)</td></tr>" % (
                len(theater["nodes"]), len(theater["edges"]), THEATER_RADIUS_M,
                len(theater["ghost"])),
            "<tr><td class='k'>timing</td><td>%d consults \u00b7 avg %d ms \u00b7 "
            "p95 %d ms \u00b7 avg tick %.1f s \u00b7 total consult time %.0f s</td></tr>" % (
                summary["timing"]["total_consults"],
                summary["timing"]["avg_consult_ms"],
                summary["timing"]["p95_consult_ms"],
                summary["timing"]["avg_tick_s"],
                summary["timing"]["total_consult_s"]),
            "</table>",
        ]
    )


def _fmt_ts(summary):
    import datetime
    ts = summary.get("ended_at")
    if ts:
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC")
    return "unknown"


def _wall_est(summary):
    est_s = summary["ticks"] * summary["timing"]["avg_tick_s"]
    return "%dh%02dm" % (int(est_s // 3600), int(est_s % 3600 // 60))


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>flywalker — a fruit fly brain looks for pastel de nata</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'%3E%3Cpath d='M20 16 C10 6 3 12 6 22 C8 28 14 30 20 26 Z' fill='%239fc4e8' opacity='.8'/%3E%3Cpath d='M28 16 C38 6 45 12 42 22 C40 28 34 30 28 26 Z' fill='%239fc4e8' opacity='.8'/%3E%3Cellipse cx='24' cy='21' rx='5.6' ry='7' fill='%23e8710a'/%3E%3Cellipse cx='24' cy='32' rx='6.2' ry='9' fill='%23e8710a'/%3E%3Ccircle cx='24' cy='10.5' r='5' fill='%23b15408'/%3E%3Ccircle cx='21.4' cy='9.6' r='2.6' fill='%231a0d04'/%3E%3Ccircle cx='26.6' cy='9.6' r='2.6' fill='%231a0d04'/%3E%3C/svg%3E"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
:root {
  --bg:#0b0e12; --panel:#12161c; --panel2:#161b23; --line:#232a33;
  --text:#d7dbe1; --muted:#8b94a0; --dim:#5b6470;
  --fly:#e8710a; --coin:#9aa0a6; --greedy:#1a73e8;
  --nata:#f5c65d;
  --ok:#2ecc71; --bad:#e74c3c; --accent:#e8710a;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:15px; line-height:1.5; }
a { color:#7ab3f5; text-decoration:none; }
a:hover { text-decoration:underline; }
.wrap { max-width:1180px; margin:0 auto; padding:0 18px 40px; }
h1 { font-size:22px; margin:0 0 4px; letter-spacing:.2px; }
.sub { font-size:13px; color:var(--muted); }
h2 { font-size:14px; font-weight:700; color:var(--text);
  letter-spacing:.1px; margin:0 0 12px;
  border-left:3px solid var(--fly); padding-left:9px; }
button:focus-visible, input[type=range]:focus-visible, a:focus-visible {
  outline:2px solid #7ab3f5; outline-offset:2px; }
@media (prefers-reduced-motion: reduce) {
  .nata-icon .ring { animation:none; opacity:.5; }
  .diff .l, .diff .r, .diff .n { transition:none; }
  .hero-fly { animation:none; }
  .fly-wing-l, .fly-wing-r { animation:none; }
  .fly-marker-inner { transition:none; }
}
@media (max-width:600px) {
  input[type=range]::-webkit-slider-thumb { width:22px; height:22px; margin-top:-9px; }
  input[type=range]::-moz-range-thumb { width:18px; height:18px; }
}
.panel { background:linear-gradient(180deg,var(--panel),#0f1318);
  border:1px solid var(--line); border-radius:12px; padding:16px 18px;
  margin:14px 0; }
.badges { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0 2px; }
.badge { display:inline-block; padding:2px 9px; border-radius:999px;
  font-size:12px; border:1px solid var(--line); color:var(--muted);
  background:#10141a; white-space:nowrap; }
.badge.solid { color:#10141a; background:var(--fly); border-color:var(--fly);
  font-weight:700; }
.kv { display:flex; flex-wrap:wrap; gap:6px 26px; font-size:13px;
  color:var(--muted); margin-top:10px; }
.kv b { color:var(--text); font-weight:600; font-variant-numeric:tabular-nums; }
.hero { display:flex; justify-content:space-between; gap:24px;
  align-items:flex-start; }
.hero-text { min-width:0; flex:1 1 auto; }
.hero-fly { flex:0 0 auto; width:112px;
  filter:drop-shadow(0 0 20px rgba(232,113,10,.3));
  animation:bob 2.6s ease-in-out infinite; }
.hero-fly svg { width:100%; height:auto; display:block; overflow:visible; }
@media (max-width:720px) { .hero-fly { display:none; } }
.fly-wing-l, .fly-wing-r { transform-box:view-box; }
.fly-wing-l { transform-origin:52px 46px;
  animation:flapL .18s ease-in-out infinite alternate; }
.fly-wing-r { transform-origin:68px 46px;
  animation:flapR .18s ease-in-out infinite alternate; }
@keyframes flapL { from { transform:rotate(0deg); }
  to { transform:rotate(-16deg); } }
@keyframes flapR { from { transform:rotate(0deg); }
  to { transform:rotate(16deg); } }
@keyframes bob { 0%,100% { transform:translateY(0); }
  50% { transform:translateY(-7px); } }
.legend { display:flex; flex-wrap:wrap; gap:14px; font-size:12.5px;
  color:var(--muted); align-items:center; }
.legend .sw { display:inline-block; width:10px; height:10px; border-radius:3px;
  margin-right:6px; vertical-align:-1px; }
.cast { display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
  gap:12px; }
@media (max-width:700px) { .cast { grid-template-columns:1fr; } }
.cast-card { background:#0d1117; border:1px solid #1a2029;
  border-top:3px solid var(--fly); border-radius:8px; padding:10px 12px;
  font-size:12.5px; color:var(--muted); line-height:1.55; }
.cast-card b { color:var(--text); font-size:13px; display:block;
  margin-bottom:2px; }
.glossary { display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
  gap:2px 24px; font-size:12.5px; color:var(--muted); }
@media (max-width:700px) { .glossary { grid-template-columns:1fr; } }
.glossary dt { color:var(--text); font-weight:600; font-size:12px;
  margin-top:8px; }
.glossary dd { margin:0 0 4px; }
.cast-cap { margin-bottom:8px; }
.legend-panel { display:flex; justify-content:space-between; flex-wrap:wrap;
  gap:8px; }
#map { height:520px; border-radius:10px; border:1px solid var(--line);
  background:#0d1117; }
.player { display:flex; flex-wrap:wrap; align-items:center; gap:12px; }
.btn { background:#171d25; color:var(--text); border:1px solid var(--line);
  border-radius:8px; padding:6px 12px; cursor:pointer; font-size:13px; }
.btn:hover { background:#1e2530; }
.btn.on { background:var(--fly); border-color:var(--fly); color:#10141a;
  font-weight:700; }
.scrub-wrap { position:relative; margin-top:4px; }
.scrub-marks { position:relative; height:10px; margin:0 8px 2px; }
.scrub-marks i { position:absolute; top:0; width:4px; height:4px;
  border-radius:50%; transform:translate(-50%,0); }
.scrub-marks i.m-arr { background:#fff; height:6px; width:6px; }
input[type=range] { width:100%; margin:0; -webkit-appearance:none;
  appearance:none; background:transparent; cursor:pointer; display:block; }
input[type=range]::-webkit-slider-runnable-track { height:4px;
  background:#252d37; border-radius:2px; }
input[type=range]::-webkit-slider-thumb { -webkit-appearance:none;
  width:16px; height:16px; border-radius:50%; background:var(--fly);
  border:3px solid #10141a; margin-top:-6px; box-shadow:0 0 0 1px var(--fly),
  0 0 12px rgba(232,113,10,.5); }
input[type=range]::-moz-range-track { height:4px; background:#252d37;
  border-radius:2px; }
input[type=range]::-moz-range-thumb { width:10px; height:10px; border-radius:50%;
  background:var(--fly); border:3px solid #10141a; }
.ticklabel { font-variant-numeric:tabular-nums; font-size:13px; color:var(--muted);
  min-width:130px; text-align:right; }
.chips { display:flex; gap:8px; flex-wrap:wrap; }
.chip { border:1px solid var(--line); border-radius:8px; padding:4px 10px;
  font-size:12px; color:var(--muted); background:#10141a; line-height:1.4; }
.chip b { display:block; font-size:14px; font-weight:700;
  font-variant-numeric:tabular-nums; }
.cockpit { display:grid; grid-template-columns:minmax(0,400px) minmax(0,1fr);
  gap:18px; align-items:start; }
@media (max-width:900px) { .cockpit { grid-template-columns:1fr; } }
.cam { position:relative; background:#000; border-radius:10px; overflow:hidden;
  border:1px solid var(--line); }
.cam img { width:100%; height:auto; display:block; image-rendering:pixelated; }
.cam .cam-msg { position:absolute; inset:0; display:none;
  align-items:center; justify-content:center; color:var(--dim); font-size:12px;
  text-align:center; padding:12px; }
.cam-cap { display:flex; justify-content:space-between; align-items:center;
  padding:6px 10px; background:#0d1117; border-top:1px solid var(--line);
  font-size:12px; color:var(--muted); }
.pill { display:inline-flex; align-items:center; gap:6px; border-radius:999px;
  padding:2px 10px; font-size:12px; font-weight:700; white-space:nowrap; }
.pill.ok { background:rgba(46,204,113,.14); color:var(--ok);
  border:1px solid rgba(46,204,113,.4); }
.pill.bad { background:rgba(231,76,60,.14); color:var(--bad);
  border:1px solid rgba(231,76,60,.4); }
.pill.neu { background:rgba(139,148,160,.12); color:var(--muted);
  border:1px solid var(--line); }
.pill.dop { background:rgba(46,204,113,.18); color:var(--ok);
  border:1px solid var(--ok); box-shadow:0 0 12px rgba(46,204,113,.35); }
.pill.avs { background:rgba(231,76,60,.18); color:var(--bad);
  border:1px solid var(--bad); box-shadow:0 0 12px rgba(231,76,60,.35); }
.cockpit-head { display:flex; justify-content:space-between; align-items:center;
  flex-wrap:wrap; gap:8px; margin-bottom:10px; }
.bars { display:flex; flex-direction:column; gap:6px; }
.bar-row { display:grid; grid-template-columns:18px 18px minmax(0,1fr) 56px 46px;
  align-items:center; gap:8px; }
.bar-arr { font-size:11px; text-align:center; color:var(--fly); }
.bar-idx { text-align:center; font-size:13px; font-weight:800; color:var(--dim);
  font-family:ui-monospace,Menlo,monospace; }
.bar-idx.go { color:var(--fly); text-shadow:0 0 8px rgba(232,113,10,.7); }
.bar-track { height:14px; background:#0d1117; border-radius:4px; overflow:hidden;
  border:1px solid #1a2029; }
.bar-fill { height:100%; background:#2a3340; }
.bar-fill.top { background:linear-gradient(90deg,#b1540840,#e8710a);
  box-shadow:0 0 8px rgba(232,113,10,.55); }
.bar-hz { font-size:12px; color:var(--muted); text-align:right;
  font-variant-numeric:tabular-nums; white-space:nowrap; }
.side { font-size:10px; font-weight:800; letter-spacing:.5px; text-align:center;
  padding:1px 4px; border-radius:4px; line-height:1.7; }
.side.BUY { color:var(--ok); background:rgba(46,204,113,.12); }
.side.SELL { color:var(--bad); background:rgba(231,76,60,.12); }
.side.HOLD { color:var(--muted); background:rgba(139,148,160,.12); }
.empty-note { color:var(--dim); font-size:13px; padding:8px 2px; }
.meters { display:grid; grid-template-columns:1fr 1fr; gap:8px 18px;
  margin-top:14px; align-items:end; }
@media (max-width:600px) { .meters { grid-template-columns:1fr; } }
.meter-label { font-size:11px; color:var(--dim); text-transform:uppercase;
  letter-spacing:.8px; margin-bottom:4px; }
.diff { position:relative; height:18px; background:#0d1117; border-radius:4px;
  border:1px solid #1a2029; overflow:hidden; }
.diff .l { position:absolute; left:0; top:0; bottom:0;
  background:rgba(107,118,131,.55); transition:width .15s; }
.diff .r { position:absolute; right:0; top:0; bottom:0;
  background:rgba(232,113,10,.55); transition:width .15s; }
.diff .n { position:absolute; top:-2px; bottom:-2px; width:2px; background:#fff;
  box-shadow:0 0 6px rgba(255,255,255,.8); transition:left .15s; }
.hud { display:flex; flex-wrap:wrap; gap:6px; }
.hud .chip { flex:1; min-width:92px; text-align:center; }
.nums { font-variant-numeric:tabular-nums; }
.charts { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr);
  gap:18px; }
@media (max-width:900px) { .charts { grid-template-columns:1fr; } }
.chart-wrap { background:#0d1117; border:1px solid #1a2029; border-radius:8px;
  padding:10px 10px 4px; position:relative; }
svg.chart { width:100%; height:auto; display:block; }
.chart .grid { stroke:#1e2530; stroke-width:1; }
.chart .axis { fill:var(--dim); font-size:10px; }
.chart .star { fill:var(--greedy); }
.rl-strip { position:relative; height:44px; background:#0d1117;
  border:1px solid #1a2029; border-radius:8px; overflow:hidden; }
.rl-strip .mid { position:absolute; left:0; right:0; top:50%; height:1px;
  background:#1e2530; }
.rl-strip i { position:absolute; top:50%; transform:translate(-50%,-50%);
  font-style:normal; font-size:12.5px; cursor:default; }
.rl-strip i.r { color:var(--ok); }
.rl-strip i.a { color:var(--bad); }
.rl-meta { display:flex; flex-wrap:wrap; gap:10px; margin-top:10px;
  align-items:center; }
.honest-grid { margin-top:16px; }
.honest-grid .headers { display:grid; grid-template-columns:1fr 1fr; gap:14px;
  margin-bottom:4px; }
.honest-grid .headers h3 { margin:0; }
.honest-grid h3.real { color:var(--ok); }
.honest-grid h3.eng { color:var(--fly); }
.honest-grid .row { border-top:1px solid var(--line); padding:12px 0 6px;
  display:grid; grid-template-columns:1fr 1fr; gap:6px 22px; }
.honest-grid .row .k { color:var(--muted); font-weight:600; grid-column:1/-1;
  font-size:11.5px; text-transform:uppercase; letter-spacing:.8px; }
.honest-grid .row .cell { font-size:13.5px; color:var(--text); padding-bottom:6px; }
@media (max-width:700px) {
  .honest-grid .headers, .honest-grid .row { grid-template-columns:1fr; }
}
.lead { color:var(--muted); font-size:13.5px; max-width:900px; }
.prov { font-size:12px; color:var(--dim); }
.prov table { width:100%; border-collapse:collapse; font-size:12.5px; }
.prov td { padding:3px 10px 3px 0; vertical-align:top; color:var(--muted); }
.prov td.k { color:var(--dim); white-space:nowrap; }
.prov .credit { margin-top:10px; color:var(--muted); font-size:12px; }
.nata-icon { position:relative; }
.nata-icon .dot { position:absolute; left:50%; top:50%; width:14px; height:14px;
  margin:-7px 0 0 -7px; border-radius:50%; background:var(--nata);
  box-shadow:0 0 10px rgba(245,198,93,.9); border:2px solid #ffffff55; }
.nata-icon .ring { position:absolute; left:50%; top:50%; width:14px; height:14px;
  margin:-7px 0 0 -7px; border-radius:50%; border:2px solid var(--nata);
  animation:pulse 2s ease-out infinite; }
@keyframes pulse { 0% { transform:scale(1); opacity:.9; }
  100% { transform:scale(4.2); opacity:0; } }
.start-icon { position:relative; }
.start-icon .dot { position:absolute; left:50%; top:50%; width:11px; height:11px;
  margin:-5px 0 0 -5px; border-radius:50%; background:#fff; border:2px solid #0b0e12;
  box-shadow:0 0 6px rgba(255,255,255,.6); }
.fly-marker-inner { width:26px; height:26px; transform-origin:center;
  transition:transform .35s ease-out; }
.fly-marker svg { display:block; filter:drop-shadow(0 0 2.5px rgba(0,0,0,.85)); }
</style>
</head>
<body>
<div class="wrap">
  <header style="padding-top:22px">
    <div class="hero">
      <div class="hero-text">
        <h1>flywalker &nbsp;<span class="sub" style="display:inline">a MaleCNS fruit fly brain goes looking for pastel de nata</span></h1>
        <div class="sub" style="margin-top:2px">
          FLY = MaleCNS v1.0 spike-decoded decisions · COIN = random · GREEDY = crow-flies instinct. Three walkers, one Lisbon corridor, honest baselines.
        </div>
        <div class="badges">
          <span class="badge solid">MaleCNS v1.0</span>
          <span class="badge">166,700 neurons</span>
          <span class="badge">25.6M connections</span>
          <span class="badge">124M synaptic contacts</span>
          <span class="badge" id="b-run"></span>
        </div>
        <div class="kv" id="run-card"></div>
      </div>
      <div class="hero-fly" aria-hidden="true">
        <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="flyBody" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="#f5c65d"/>
              <stop offset="0.45" stop-color="#e8710a"/>
              <stop offset="1" stop-color="#8a3c05"/>
            </linearGradient>
            <linearGradient id="flyWing" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#cfe6ff" stop-opacity="0.55"/>
              <stop offset="1" stop-color="#7ab3f5" stop-opacity="0.14"/>
            </linearGradient>
          </defs>
          <g class="fly-wing-l">
            <path d="M52 42 C30 18 8 26 10 52 C11 68 26 76 40 70 C46 66 50 54 52 42 Z"
              fill="url(#flyWing)" stroke="#9fc4e8" stroke-width="1.2"/>
            <path d="M50 46 C34 34 20 34 16 50 M48 56 C36 54 28 60 24 68"
              fill="none" stroke="#9fc4e8" stroke-width="0.9" opacity="0.8"/>
          </g>
          <g class="fly-wing-r">
            <path d="M68 42 C90 18 112 26 110 52 C109 68 94 76 80 70 C74 66 70 54 68 42 Z"
              fill="url(#flyWing)" stroke="#9fc4e8" stroke-width="1.2"/>
            <path d="M70 46 C86 34 100 34 104 50 M72 56 C84 54 92 60 96 68"
              fill="none" stroke="#9fc4e8" stroke-width="0.9" opacity="0.8"/>
          </g>
          <g stroke="#c25e08" stroke-width="2.4" stroke-linecap="round" fill="none">
            <path d="M52 48 L30 38 L20 44"/>
            <path d="M51 56 L26 54 L15 62"/>
            <path d="M52 64 L30 74 L20 86"/>
            <path d="M68 48 L90 38 L100 44"/>
            <path d="M69 56 L94 54 L105 62"/>
            <path d="M68 64 L90 74 L100 86"/>
          </g>
          <ellipse cx="60" cy="79" rx="12.5" ry="19" fill="url(#flyBody)"/>
          <path d="M50 72 Q60 77 70 72 M49 80 Q60 85 71 80 M51 88 Q60 92 69 88"
            stroke="#7a3404" stroke-width="1" fill="none" opacity="0.55"/>
          <ellipse cx="60" cy="52" rx="11.5" ry="15" fill="url(#flyBody)"/>
          <ellipse cx="57" cy="46" rx="3.4" ry="8" fill="#ffffff" opacity="0.18"/>
          <circle cx="60" cy="30" r="9.5" fill="#a34a06"/>
          <ellipse cx="52.5" cy="27.5" rx="5.4" ry="6.4" fill="#2b1608"
            stroke="#f5c65d" stroke-width="0.9" transform="rotate(-14 52.5 27.5)"/>
          <ellipse cx="67.5" cy="27.5" rx="5.4" ry="6.4" fill="#2b1608"
            stroke="#f5c65d" stroke-width="0.9" transform="rotate(14 67.5 27.5)"/>
          <path d="M56 22 Q50 14 44 12 M64 22 Q70 14 76 12"
            stroke="#e8710a" stroke-width="1.6" fill="none" stroke-linecap="round"/>
        </svg>
      </div>
    </div>
  </header>

  <section class="panel" style="padding:0;overflow:hidden">
    <div id="map"></div>
  </section>

  <section class="panel">
    <h2>What you're looking at</h2>
    <div class="cast-cap sub">the cast</div>
    <div class="cast">
      <div class="cast-card" style="border-top-color:var(--fly)"><b>FLY — the real brain</b>
        MaleCNS v1.0, the adult male fruit-fly connectome: 166,700 neurons, 25.6M connections.
        At every junction it views each exit's street photo through a simulated retina and turns the
        connectome's spike traffic into a direction score. This is the experiment: does the connectome walk?</div>
      <div class="cast-card" style="border-top-color:var(--coin)"><b>COIN — no brain</b>
        Picks a uniformly random exit at every step. The noise floor: a walker that does not beat COIN
        is not navigating.</div>
      <div class="cast-card" style="border-top-color:var(--greedy)"><b>GREEDY — no brain</b>
        Always steps toward the exit that most reduces the straight-line distance to the goal.
        The sense-of-direction ceiling: how far FLY is from intent.</div>
    </div>
    <div class="cast-cap sub" style="margin-top:16px">the legend, decoded</div>
    <dl class="glossary">
      <dt>junction theater</dt><dd>only the street graph near where the walkers actually went. Dots are
        street-photo capture points; thin lines link neighbouring captures.</dd>
      <dt>GPS-density halos</dt><dd>where each walker lingered; stronger colour means more revisits.</dd>
      <dt>GREEDY ghost path</dt><dd>the dashed blue line: shortest graph route from GREEDY's last
        position to the goal.</dd>
      <dt>pulsing gold dot</dt><dd>the goal: a pastel de nata.</dd>
      <dt>approach scores A–E, in Hz</dt><dd>the five exits from the current junction. Bar height is the
        connectome's score for that exit's photo, in Hz = spikes per second in the descending neurons the
        decoder listens to. Higher bar, stronger approach vote; ▼ marks the exit FLY actually took.</dd>
      <dt>BUY / SELL / HOLD</dt><dd>the DNp20 decoder's verdict: right-selective neurons firing harder (BUY —
        move right-leaning), left harder (SELL — left-leaning), neither (HOLD).</dd>
      <dt>Σ spikes · gate · latency</dt><dd>total connectome spikes across the five consults, DNpe017 gate
        spike count, and how long the brain simulation took for that candidate.</dd>
      <dt>delta pill &amp; reinforcement</dt><dd>±m closer / away: this step's change in straight-line
        distance to the nata. The dopamine badge means progress queued a reward pulse for the next
        consult; aversive means regression.</dd>
    </dl>
  </section>

  <section class="panel">
    <div class="legend-panel">
      <h2 style="margin:0">Timeline</h2>
      <div class="legend" id="legend"></div>
    </div>
    <div class="player" style="margin-top:12px">
      <button class="btn" id="play">▶ play</button>
      <button class="btn" id="rew">⏮ start</button>
      <span id="speeds" style="display:flex;gap:6px">
        <button class="btn" data-s="0.5">0.5×</button>
        <button class="btn on" data-s="1">1×</button>
        <button class="btn" data-s="2">2×</button>
        <button class="btn" data-s="4">4×</button>
      </span>
      <span class="ticklabel nums" id="ticklabel"></span>
    </div>
    <div class="scrub-wrap">
      <div class="scrub-marks" id="scrub-marks"></div>
      <input id="scrub" type="range" min="0" value="0"/>
    </div>
    <div class="chips" id="chips" style="margin-top:10px"></div>
  </section>

  <section class="panel">
    <h2>What the fly saw</h2>
    <div class="cockpit">
      <div>
        <div class="cam">
          <div class="cam-msg" id="cam-msg">no frame before the first step</div>
          <img id="flycam" alt="flycam frame" style="visibility:hidden;width:100%"/>
        </div>
        <div class="cam-cap">
          <span class="nums" id="cam-label"></span>
          <span>320×180 · R1–R6/R8 photoreceptor mapping</span>
        </div>
      </div>
      <div>
        <div class="cockpit-head">
          <span style="font-size:12.5px;color:var(--muted)">
            decoded approach scores at junction <span class="nums" id="jx-node" style="color:var(--text)"></span>
          </span>
          <span style="display:flex;gap:8px;flex-wrap:wrap">
            <span class="pill neu nums" id="delta-pill" style="display:none"></span>
            <span class="pill neu" id="rl-badge" style="display:none"></span>
          </span>
        </div>
        <div class="bars" id="bars"></div>
        <div class="meters">
          <div style="min-width:0">
            <div class="meter-label">DNp20 left/right differential (Hz)</div>
            <div class="diff" id="diffmeter">
              <div class="l" id="diff-l"></div>
              <div class="r" id="diff-r"></div>
              <div class="n" id="diff-n"></div>
            </div>
            <div class="sub nums" id="diff-note" style="font-size:11px;color:var(--dim);margin-top:3px"></div>
          </div>
          <div style="min-width:0">
            <div class="meter-label">Spike bookkeeping</div>
            <div class="hud">
              <span class="chip"><b class="nums" id="hud-spikes">—</b>spikes · all consults</span>
              <span class="chip"><b class="nums" id="hud-gate">—</b>DNpe017 gate</span>
              <span class="chip"><b class="nums" id="hud-ms">—</b>consult latency</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <section class="panel">
    <div class="chips" id="verdict-chips" style="margin-bottom:12px"></div>
    <div class="charts">
      <div>
        <h2>Distance to goal (m)</h2>
        <div class="chart-wrap"><svg class="chart" id="chart-dist" viewBox="0 0 900 240"></svg></div>
      </div>
      <div>
        <h2>Distance walked (m)</h2>
        <div class="chart-wrap"><svg class="chart" id="chart-walked" viewBox="0 0 900 240"></svg></div>
      </div>
    </div>
    <div class="sub" style="color:var(--dim);font-size:12px;margin-top:8px">
      The orange cursor tracks the timeline. ★ marks walker arrivals.
    </div>
  </section>

  <section class="panel" id="rl-panel" style="display:none">
    <h2>Reinforcement ledger</h2>
    <div class="legend" style="margin-bottom:8px">
      <span><span class="sw" style="background:var(--ok);border-radius:50%"></span>dopamine pulse (PAM11, progress) — queued for the next consult</span>
      <span><span class="sw" style="background:var(--bad);border-radius:50%"></span>aversive pulse (PPL101, regression)</span>
    </div>
    <div class="rl-strip" id="rl-strip"><div class="mid"></div></div>
    <div class="rl-meta" id="rl-meta"></div>
  </section>

  <section class="panel">
    <h2>Honesty: what is real, what is engineered</h2>
    <p class="lead">__HONESTY_LEAD__</p>
    <div class="honest-grid">
      <div class="headers">
        <h3 class="real">what is real</h3>
        <h3 class="eng">what is engineered</h3>
      </div>
      __HONESTY_ROWS__
    </div>
  </section>

  <section class="panel">
    <h2>Provenance</h2>
    <div class="prov">
      __PROV__
      <div class="credit">
        Brain: MaleCNS v1.0 (<a href="https://male-cns.janelia.org/">Google Research + HHMI Janelia</a>) ·
        neural kernel &amp; decoder: <a href="https://github.com/nftechie/stonkfly">Stonkfly</a> (MIT) ·
        imagery: <a href="https://www.mapillary.com/">Mapillary</a> ·
        map: <a href="https://leafletjs.com/">Leaflet</a> + OpenStreetMap tiles ·
        repo: <a href="https://github.com/franBec/flywalker">github.com/franBec/flywalker</a>
      </div>
    </div>
  </section>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const P = __PAYLOAD__;
const COLORS = { fly:"#e8710a", coin:"#9aa0a6", greedy:"#1a73e8" };
const maxTick = P.max_tick;

/* ---------- header / run card ---------- */
document.getElementById("b-run").textContent = P.run.id + " · " + P.run.label;
const card = document.getElementById("run-card");
[
  ["route", P.run.label],
  ["route graph", P.theater.node_count + " nodes · " + P.theater.edge_count + " links"],
  ["imagery", P.run.image_count + " frames · " + P.run.source],
  ["crow-flies", P.run.crow_m.toFixed(0) + " m"],
  ["ticks", maxTick],
  ["wall clock ≈", P.run.wall_est],
  ["brain consults", P.run.consults + " · avg " + P.run.avg_consult_ms + " ms · p95 " + P.run.p95_consult_ms + " ms"],
  ["recorded", P.run.recorded],
].forEach(function (kv) {
  const d = document.createElement("span");
  d.innerHTML = kv[0] + ": <b>" + kv[1] + "</b>";
  card.appendChild(d);
});

/* ---------- legend ---------- */
const legend = document.getElementById("legend");
[
  ["fly", "FLY (MaleCNS spike decode)"],
  ["coin", "COIN (random)"],
  ["greedy", "GREEDY (crow-flies)"],
].forEach(function (kv) {
  const s = document.createElement("span");
  s.innerHTML = '<span class="sw" style="background:' + COLORS[kv[0]] + '"></span>' + kv[1];
  legend.appendChild(s);
});
const ls = document.createElement("span");
ls.innerHTML = '<span class="sw" style="background:#2a3340;border-radius:50%"></span>junction theater · '
  + '<span class="sw" style="background:none;border:1px dashed #1a73e8;border-radius:0"></span>GREEDY ghost path · '
  + '<span class="sw" style="background:#f5c65d;border-radius:50%"></span>pastel de nata';
legend.appendChild(ls);

/* ---------- theater map ---------- */
const map = L.map("map", { zoomControl: true });
map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · imagery © Mapillary',
  maxZoom: 19
}).addTo(map);

const T = P.theater;
const FLY_MARKER_SVG = '<svg viewBox="0 0 48 48" width="26" height="26">'
  + '<g stroke="#e8710a" stroke-width="2.4" stroke-linecap="round" fill="none">'
  + '<path d="M22 21 L11 14 M21 25 L9 25 M22 29 L11 35"/>'
  + '<path d="M26 21 L37 14 M27 25 L39 25 M26 29 L37 35"/></g>'
  + '<path d="M20 16 C10 6 3 12 6 22 C8 28 14 30 20 26 Z" fill="#9fc4e8" opacity=".8" stroke="#cfe6ff" stroke-width=".8"/>'
  + '<path d="M28 16 C38 6 45 12 42 22 C40 28 34 30 28 26 Z" fill="#9fc4e8" opacity=".8" stroke="#cfe6ff" stroke-width=".8"/>'
  + '<ellipse cx="24" cy="21" rx="5.6" ry="7" fill="#e8710a"/>'
  + '<ellipse cx="24" cy="32" rx="6.2" ry="9" fill="#e8710a"/>'
  + '<circle cx="24" cy="10.5" r="5" fill="#b15408"/>'
  + '<circle cx="21.4" cy="9.6" r="2.6" fill="#1a0d04"/>'
  + '<circle cx="26.6" cy="9.6" r="2.6" fill="#1a0d04"/>'
  + '</svg>';
function bearingDeg(a, b) {
  const toRad = Math.PI / 180;
  const y = Math.sin((b[1] - a[1]) * toRad) * Math.cos(b[0] * toRad);
  const x = Math.cos(a[0] * toRad) * Math.sin(b[0] * toRad)
    - Math.sin(a[0] * toRad) * Math.cos(b[0] * toRad) * Math.cos((b[1] - a[1]) * toRad);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}
const nodeLL = T.nodes.map(function (p) { return L.latLng(p[0], p[1]); });
if (T.edges.length) {
  const segs = [];
  for (const e of T.edges) segs.push([nodeLL[e[0]], nodeLL[e[1]]]);
  L.polyline(segs, { color:"#2a3340", weight:1, opacity:.6, interactive:false }).addTo(map);
}
if (T.nodes.length < 8000) {
  const dots = nodeLL.map(function (p) { return [p, p]; });
  L.polyline(dots, { color:"#39434f", weight:2, opacity:.3, lineCap:"round", interactive:false }).addTo(map);
}
/* per-walker GPS-density halos: revisit count buckets */
const haloBuckets = [[1, 1, 4, .16], [2, 5, 7, .3], [6, 1e9, 10, .5]];
for (const name of ["fly", "coin", "greedy"]) {
  const visits = T.visited[name] || [];
  const count = new Map(visits);
  for (const b of haloBuckets) {
    const segs = [];
    for (const v of visits) {
      const c = count.get(v[0]);
      if (c >= b[0] && c <= b[1]) segs.push([nodeLL[v[0]], nodeLL[v[0]]]);
    }
    if (segs.length) L.polyline(segs, { color:COLORS[name], weight:b[2], opacity:b[3], lineCap:"round", interactive:false }).addTo(map);
  }
}
if (T.ghost.length > 1) {
  L.polyline(T.ghost.map(function (i) { return nodeLL[i]; }),
    { color:"#1a73e8", weight:2.5, dashArray:"2 8", opacity:.9, interactive:false }).addTo(map);
}
const fullTrail = {}, liveTrail = {}, mark = {};
for (const name of ["fly", "coin", "greedy"]) {
  fullTrail[name] = L.polyline(P.trails[name], { color:COLORS[name], opacity:.3, weight:3, interactive:false }).addTo(map);
  liveTrail[name] = L.polyline([P.trails[name][0]], { color:COLORS[name], weight:5, opacity:.95, interactive:false }).addTo(map);
  if (name === "fly") {
    mark[name] = L.marker(P.trails[name][0], { icon:L.divIcon({
      className:"fly-marker",
      html:'<div class="fly-marker-inner">' + FLY_MARKER_SVG + '</div>',
      iconSize:[26, 26], iconAnchor:[13, 13],
    }), interactive:true }).addTo(map);
  } else {
    mark[name] = L.circleMarker(P.trails[name][0], { color:COLORS[name], radius:6, weight:2.5, fill:true, fillColor:COLORS[name], fillOpacity:1 }).addTo(map);
  }
  liveTrail[name].bindTooltip(WALKER_LABEL(name), { sticky:true, direction:"top" });
  mark[name].bindTooltip(WALKER_LABEL(name), { sticky:true, direction:"top" });
}
function WALKER_LABEL(name) {
  const w = P.walkers[name];
  return name.toUpperCase() + (w.arrived ? " — arrived" : "") + " · " + w.steps + " steps · " + w.distance_m.toFixed(0) + " m";
}
L.marker(P.goal, { icon:L.divIcon({ className:"nata-icon", html:'<div class="ring"></div><div class="dot"></div>', iconSize:[20,20], iconAnchor:[10,10] }), interactive:true }).addTo(map)
  .bindTooltip("pastel de nata");
L.marker(P.start, { icon:L.divIcon({ className:"start-icon", html:'<div class="dot"></div>', iconSize:[18,18], iconAnchor:[9,9] }), interactive:false }).addTo(map)
  .bindTooltip("start");

const theaterBounds = L.latLngBounds(nodeLL.length ? nodeLL : [P.start, P.goal])
  .extend(P.goal).extend(P.start);
map.fitBounds(theaterBounds, { padding:[30, 30] });

/* ---------- data helpers ---------- */
const distAt = { fly:new Array(maxTick+1).fill(null), coin:new Array(maxTick+1).fill(null), greedy:new Array(maxTick+1).fill(null) };
const deltaAt = { fly:new Array(maxTick+1).fill(null) };
const cutAt = { fly:new Array(maxTick+1).fill(0), coin:new Array(maxTick+1).fill(0), greedy:new Array(maxTick+1).fill(0) };
(function () {
  const ptr = { fly:0, coin:0, greedy:0 };
  for (let t = 0; t <= maxTick; t++) {
    for (const name of ["fly", "coin", "greedy"]) {
      const rows = P.series[name];
      while (ptr[name] < rows.length - 1 && rows[ptr[name] + 1][0] <= t) ptr[name]++;
      if (rows[ptr[name]] && rows[ptr[name]][0] <= t) {
        cutAt[name][t] = ptr[name] + 1;
        distAt[name][t] = rows[ptr[name]][1];
        if (deltaAt[name]) deltaAt[name][t] = rows[ptr[name]][3];
      }
    }
  }
})();
const flyAt = {};
for (const e of P.fly) flyAt[e.t] = e;

function pad5(n) { return String(n).padStart(5, "0"); }
function fmtSpikes(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return Math.round(n / 1e3) + "k";
  return String(n);
}
function fmtDelta(d) {
  const v = Math.abs(d).toFixed(1);
  if (d > 0.05) return { txt:"+" + v + " m closer", cls:"ok" };
  if (d < -0.05) return { txt:"\u2212" + v + " m away", cls:"bad" };
  return { txt:"0.0 m", cls:"neu" };
}

/* ---------- charts ---------- */
function chart(svgId, series, yMax) {
  const svg = document.getElementById(svgId);
  const ns = "http://www.w3.org/2000/svg";
  const W = 900, H = 240, pl = 46, pr = 14, pt = 12, pb = 28;
  const iw = W - pl - pr, ih = H - pt - pb;
  const x = function (t) { return pl + (maxTick ? (t / maxTick) * iw : 0); };
  const y = function (v) { return pt + ih - Math.max(0, Math.min(v / yMax, 1)) * ih; };
  for (const gy of [0.25, 0.5, 0.75, 1]) {
    const g = document.createElementNS(ns, "line");
    g.setAttribute("x1", pl); g.setAttribute("x2", W - pr);
    g.setAttribute("y1", y(yMax * gy)); g.setAttribute("y2", y(yMax * gy));
    g.setAttribute("class", "grid");
    svg.appendChild(g);
    const tx = document.createElementNS(ns, "text");
    tx.setAttribute("x", pl - 6); tx.setAttribute("y", y(yMax * gy) + 3);
    tx.setAttribute("text-anchor", "end"); tx.setAttribute("class", "axis");
    tx.textContent = Math.round(yMax * gy);
    svg.appendChild(tx);
  }
  for (const gx of [0, 0.25, 0.5, 0.75, 1]) {
    const tx = document.createElementNS(ns, "text");
    tx.setAttribute("x", x(maxTick * gx)); tx.setAttribute("y", H - 8);
    tx.setAttribute("text-anchor", "middle"); tx.setAttribute("class", "axis");
    tx.textContent = Math.round(maxTick * gx) + "t";
    svg.appendChild(tx);
  }
  for (const name of ["fly", "coin", "greedy"]) {
    const rows = series[name];
    if (!rows.length) continue;
    const d = rows.map(function (r, i) {
      return (i ? "L" : "M") + x(r[0]).toFixed(1) + "," + y(r[1]).toFixed(1);
    }).join(" ");
    const area = document.createElementNS(ns, "path");
    area.setAttribute("d", d + " L" + x(maxTick).toFixed(1) + "," + (pt + ih) + " L" + x(0).toFixed(1) + "," + (pt + ih) + " Z");
    area.setAttribute("fill", COLORS[name]); area.setAttribute("opacity", "0.07");
    svg.appendChild(area);
    const line = document.createElementNS(ns, "path");
    line.setAttribute("d", d);
    line.setAttribute("fill", "none"); line.setAttribute("stroke", COLORS[name]);
    line.setAttribute("stroke-width", "2"); line.setAttribute("stroke-linejoin", "round");
    svg.appendChild(line);
  }
  for (const a of P.arrivals) {
    if (svgId !== "chart-dist") break;
    const star = document.createElementNS(ns, "text");
    star.setAttribute("x", x(a[0])); star.setAttribute("y", y(a[2]) - 9);
    star.setAttribute("text-anchor", "middle"); star.setAttribute("class", "star");
    star.setAttribute("font-size", "17");
    star.textContent = "\u2605";
    svg.appendChild(star);
  }
  const cur = document.createElementNS(ns, "line");
  cur.setAttribute("y1", pt); cur.setAttribute("y2", pt + ih);
  cur.setAttribute("stroke", "#e8710a"); cur.setAttribute("stroke-width", "1.5");
  cur.setAttribute("opacity", ".8");
  svg.appendChild(cur);
  return { x: x, cur: cur };
}

const distSeries = {
  fly: P.series.fly.map(function (r) { return [r[0], r[1]]; }),
  coin: P.series.coin.map(function (r) { return [r[0], r[1]]; }),
  greedy: P.series.greedy.map(function (r) { return [r[0], r[1]]; }),
};
const cDist = chart("chart-dist", distSeries, Math.max(P.ycap, 1));
const cWalk = chart("chart-walked", P.walk_cum, Math.max(P.walk_cap, 1));

/* ---------- data-derived honesty chips ---------- */
(() => {
  const box = document.getElementById("verdict-chips");
  const v = document.createElement("span");
  v.className = "chip";
  v.style.borderColor = "rgba(232,113,10,.5)";
  v.innerHTML = "<b>" + P.verdict.txt + "</b>" + P.verdict.detail;
  box.appendChild(v);
  for (const a of P.arrivals) {
    const c = document.createElement("span");
    c.className = "chip";
    c.style.borderColor = COLORS[a[1]];
    c.innerHTML = "<b>" + a[1].toUpperCase() + " arrived</b>tick " + a[0] + " · " + a[2].toFixed(1) + " m from the goal";
    box.appendChild(c);
  }
  if (P.gap_chip) {
    const c = document.createElement("span");
    c.className = "chip";
    c.innerHTML = "<b>" + P.gap_chip.txt + "</b>" + P.gap_chip.detail;
    box.appendChild(c);
  }
})();

/* ---------- timeline controls ---------- */
const scrub = document.getElementById("scrub");
scrub.max = maxTick;
const state = { tick:0, playing:false, speed:1, timer:null };
const ticklabel = document.getElementById("ticklabel");

function setPlay(playing) {
  state.playing = playing;
  document.getElementById("play").textContent = playing ? "\u23f8 pause" : "\u25b6 play";
  document.getElementById("play").classList.toggle("on", !!playing);
  if (playing) {
    clearTimeout(state.timer);
    state.timer = setTimeout(step, 900 / state.speed);
  } else {
    clearTimeout(state.timer);
  }
}
function step() {
  if (!state.playing) return;
  let next = state.tick + 1;
  if (next > maxTick) { setPlay(false); return; }
  render(next);
  state.timer = setTimeout(step, 900 / state.speed);
}
document.getElementById("play").addEventListener("click", function () { setPlay(!state.playing); });
document.getElementById("rew").addEventListener("click", function () { setPlay(false); render(0); });
document.getElementById("speeds").addEventListener("click", function (ev) {
  const b = ev.target.closest("button"); if (!b) return;
  state.speed = parseFloat(b.dataset.s);
  for (const s of document.getElementById("speeds").children) s.classList.toggle("on", s === b);
});
scrub.addEventListener("input", function () { setPlay(false); render(+scrub.value); });
document.addEventListener("keydown", function (ev) {
  if (ev.target.tagName === "INPUT") return;
  if (ev.code === "Space") { ev.preventDefault(); setPlay(!state.playing); }
  if (ev.code === "ArrowRight") { setPlay(false); render(Math.min(maxTick, state.tick + 1)); }
  if (ev.code === "ArrowLeft") { setPlay(false); render(Math.max(0, state.tick - 1)); }
});

/* ---------- scrubber key-moment markers ---------- */
(function () {
  const box = document.getElementById("scrub-marks");
  function add(cls, color, tick) {
    const i = document.createElement("i");
    i.className = cls;
    if (color) i.style.background = color;
    i.style.left = (maxTick ? (tick / maxTick) * 100 : 0) + "%";
    box.appendChild(i);
  }
  for (const a of P.arrivals) add("m-arr", null, a[0]);
  for (const c of P.closest) add("m-close", COLORS[c[1]], c[0]);   /* [tick, walker] */
  for (const r of P.rl) {
    const cls = r[1] === "reward" ? "m-rl-r" : "m-rl-a";
    add(cls, null, r[0]);
  }
})();

/* ---------- chips ---------- */
const chipsWrap = document.getElementById("chips");
const chipEl = {};
(function () {
  for (const name of ["fly", "coin", "greedy"]) {
    const c = document.createElement("span");
    c.className = "chip";
    c.style.borderTopColor = COLORS[name];
    c.innerHTML = '<b class="nums" id="chip-' + name + '">—</b>' + (name === "fly" ? "FLY · dist to goal" : name === "coin" ? "COIN · dist to goal" : "GREEDY · dist to goal");
    chipsWrap.appendChild(c);
    chipEl[name] = document.getElementById("chip-" + name);
  }
})();

/* ---------- cockpit ---------- */
const camMsg = document.getElementById("cam-msg");
const flycam = document.getElementById("flycam");
const camLabel = document.getElementById("cam-label");

function setPill(el, show, cls, html) {
  el.style.display = show ? "" : "none";
  if (show) { el.className = "pill " + cls; el.innerHTML = html; }
}

function renderCockpit(tick) {
  const nodeEl = document.getElementById("jx-node");
  const barsEl = document.getElementById("bars");
  const f = flyAt[tick];
  if (!f) {
    nodeEl.textContent = "—";
    barsEl.innerHTML = '<div class="empty-note">no consult at this tick — FLY asks the brain on every step.</div>';
    document.getElementById("diff-l").style.width = "0%";
    document.getElementById("diff-r").style.width = "0%";
    document.getElementById("diff-n").style.left = "50%";
    document.getElementById("diff-note").textContent = "";
    document.getElementById("hud-spikes").textContent = "—";
    document.getElementById("hud-gate").textContent = "—";
    document.getElementById("hud-ms").textContent = "—";
    setPill(document.getElementById("delta-pill"), false, "neu", "");
    setPill(document.getElementById("rl-badge"), false, "neu", "");
    return;
  }
  nodeEl.textContent = f.n;
  const cands = f.c;
  let chosen = -1, argmax = 0, maxHz = 0;
  for (let i = 0; i < cands.length; i++) {
    if (cands[i][2] > maxHz) { maxHz = cands[i][2]; }
    if (cands[i][1] === f.n) chosen = i;
  }
  for (let i = 0; i < cands.length; i++) if (cands[i][2] > cands[argmax][2]) argmax = i;
  if (chosen < 0) chosen = argmax;
  const scale = Math.max(maxHz, 1);
  barsEl.innerHTML = "";
  for (let i = 0; i < cands.length; i++) {
    const c = cands[i];
    const row = document.createElement("div");
    row.className = "bar-row";
    row.title = "candidate " + c[0] + ": approach " + c[2].toFixed(0) +
      " Hz \u2014 spikes per second in the decoder's descending neurons while viewing this candidate";
    const arr = document.createElement("span");
    arr.className = "bar-arr";
    arr.textContent = i === chosen ? "\u25bc" : "";
    const idx = document.createElement("span");
    idx.className = "bar-idx" + (i === chosen ? " go" : "");
    idx.textContent = c[0];
    const track = document.createElement("span");
    track.className = "bar-track";
    const fill = document.createElement("span");
    fill.className = "bar-fill" + (i === argmax ? " top" : "");
    fill.style.width = Math.round(100 * c[2] / scale) + "%";
    track.appendChild(fill);
    const hz = document.createElement("span");
    hz.className = "bar-hz";
    hz.textContent = c[2].toFixed(0) + " Hz";
    const side = document.createElement("span");
    side.className = "side " + c[3];
    side.textContent = c[3];
    row.appendChild(arr); row.appendChild(idx); row.appendChild(track);
    row.appendChild(hz); row.appendChild(side);
    barsEl.appendChild(row);
  }
  const c = cands[chosen];
  const lw = Math.min(50, (c[4] / 120) * 50), rw = Math.min(50, (c[5] / 120) * 50);
  document.getElementById("diff-l").style.width = lw + "%";
  document.getElementById("diff-r").style.width = rw + "%";
  const needle = Math.max(2, Math.min(98, 50 + (c[6] / 120) * 50));
  document.getElementById("diff-n").style.left = needle + "%";
  document.getElementById("diff-note").textContent =
    "left " + c[4].toFixed(0) + " Hz · right " + c[5].toFixed(0) + " Hz · \u0394" + (c[6] >= 0 ? "+" : "\u2212") +
    Math.abs(c[6]).toFixed(0) + " Hz \u2192 " + c[3] + (c[3] === "BUY" ? " (move right-leaning)" : c[3] === "SELL" ? " (move left-leaning)" : " (hold)");
  let tot = 0;
  for (const cnd of cands) tot += cnd[8];
  document.getElementById("hud-spikes").textContent = "\u03a3 " + fmtSpikes(tot);
  document.getElementById("hud-gate").textContent = c[7] + (c[7] === 1 ? " spike" : " spikes");
  document.getElementById("hud-ms").textContent = (c[9] / 1000).toFixed(1) + " s";
  const d = fmtDelta(deltaAt.fly[tick]);
  setPill(document.getElementById("delta-pill"), true, d.cls, d.txt);
  const rl = f.rl;
  if (rl === "reward") setPill(document.getElementById("rl-badge"), true, "dop", "\u25b2 dopamine pulse");
  else if (rl === "aversive") setPill(document.getElementById("rl-badge"), true, "avs", "\u25bc aversive pulse");
  else setPill(document.getElementById("rl-badge"), false, "neu", "");
}

/* ---------- render ---------- */
function render(tick) {
  state.tick = tick;
  scrub.value = tick;
  ticklabel.textContent = "tick " + tick + " / " + maxTick;
  for (const name of ["fly", "coin", "greedy"]) {
    const cut = cutAt[name][tick];
    liveTrail[name].setLatLngs(P.trails[name].slice(0, cut + 1));
    mark[name].setLatLng(P.trails[name][Math.min(cut, P.trails[name].length - 1)]);
    const d = distAt[name][tick];
    chipEl[name].textContent = d === null ? "—" : d.toFixed(1) + " m";
  }
  /* the fly turns to its heading */
  const flyCut = cutAt.fly[tick];
  if (flyCut >= 1) {
    const el = mark.fly.getElement();
    const inner = el ? el.querySelector(".fly-marker-inner") : null;
    if (inner) inner.style.transform =
      "rotate(" + bearingDeg(P.trails.fly[flyCut - 1], P.trails.fly[flyCut]).toFixed(0) + "deg)";
  }
  /* flycam */
  if (tick >= 1 && tick <= P.frames) {
    flycam.src = "frames/" + pad5(tick) + ".png";
    flycam.style.visibility = "";
    camMsg.style.display = "none";
  } else {
    flycam.style.visibility = "hidden";
    camMsg.style.display = "flex";
    camMsg.textContent = tick === 0 ? "no frame before the first step" : "no frame for this tick";
  }
  camLabel.textContent = "tick " + tick + " · frame " + (tick >= 1 ? pad5(tick) : "—");
  renderCockpit(tick);
  const xD = cDist.x(tick), xW = cWalk.x(tick);
  cDist.cur.setAttribute("x1", xD); cDist.cur.setAttribute("x2", xD);
  cWalk.cur.setAttribute("x1", xW); cWalk.cur.setAttribute("x2", xW);
}

/* ---------- reinforcement ledger ---------- */
if (P.rl.length) {
  document.getElementById("rl-panel").style.display = "";
  const strip = document.getElementById("rl-strip");
  for (const r of P.rl) {
    const i = document.createElement("i");
    i.className = r[1] === "reward" ? "r" : "a";
    i.textContent = r[1] === "reward" ? "\u25b2" : "\u25bc";
    i.style.left = (maxTick ? (r[0] / maxTick) * 100 : 0) + "%";
    i.title = "tick " + r[0] + " \u00b7 " + r[1];
    strip.appendChild(i);
  }
  const meta = document.getElementById("rl-meta");
  const nR = P.rl.filter(function (r) { return r[1] === "reward"; }).length;
  const nA = P.rl.length - nR;
  const w = document.createElement("span");
  w.className = "chip";
  w.innerHTML = "<b>" + nR + "</b> dopamine pulses (PAM11)";
  meta.appendChild(w);
  const a = document.createElement("span");
  a.className = "chip";
  a.innerHTML = "<b>" + nA + "</b> aversive pulses (PPL101)";
  meta.appendChild(a);
}

render(0);
</script>
</body>
</html>"""


def render(run_dir):
    route, lines, summary = load(run_dir)
    replay_dir = os.path.join(run_dir, "replay")
    os.makedirs(replay_dir, exist_ok=True)

    frames_src = os.path.join(run_dir, "frames")
    if os.path.isdir(frames_src):
        shutil.copytree(frames_src, os.path.join(replay_dir, "frames"), dirs_exist_ok=True)

    series, trails, trail_nodes, fly_cockpit, arrivals, rl = process_lines(lines)
    theater = theater_subgraph(route, trail_nodes)
    close = closeness_stats(series)
    run_id = summary["run_id"]

    label = RUN_LABELS.get(run_id, (route["start"]["lat"], route["goal"]["lat"], "run"))
    if isinstance(label[0], float):
        label = ("start", "goal", "run")
    crow_m = haversine_m(route["start"]["lat"], route["start"]["lng"],
                         route["goal"]["lat"], route["goal"]["lng"])

    walk_cum = {}
    for name in series:
        cum = 0.0
        walk_cum[name] = []
        for t, d, m, dl in series[name]:
            cum += m
            walk_cum[name].append([t, round(cum, 1)])

    ycap = max((r[1] for s in series.values() for r in s), default=1) * 1.06
    walk_cap = max((r[1] for s in walk_cum.values() for r in s), default=1) * 1.06

    closest = []
    for name in series:
        best = min(series[name], key=lambda r: r[1])
        closest.append([best[0], name])

    verdict_detail = (
        "net %s vs COIN net %s"
        % (_signed(close["fly_net"]), _signed(close["coin_net"]))
    )
    verdict_txt = "FLY closer than COIN on %d/%d ticks (%d%%)" % (close["hits"], close["both"], close["pct"])
    gap_txt = ""
    if close["gap"] > 0.05:
        gap_txt = "FLY ended %.1f m closer to the goal" % close["gap"]
    elif close["gap"] < -0.05:
        gap_txt = "COIN ended %.1f m closer to the goal" % abs(close["gap"])

    payload = {
        "run": {
            "id": run_id,
            "label": "%s \u2192 %s (%s)" % (label[0], label[1], label[2]),
            "ticks": summary["ticks"],
            "image_count": route.get("image_count"),
            "source": route.get("source"),
            "crow_m": round(crow_m, 1),
            "wall_est": _wall_est(summary),
            "consults": summary["timing"]["total_consults"],
            "avg_consult_ms": summary["timing"]["avg_consult_ms"],
            "p95_consult_ms": summary["timing"]["p95_consult_ms"],
            "recorded": _fmt_ts(summary),
        },
        "walkers": summary["walkers"],
        "start": [route["start"]["lat"], route["start"]["lng"]],
        "goal": [route["goal"]["lat"], route["goal"]["lng"]],
        "series": series,
        "walk_cum": walk_cum,
        "trails": {name: [[
            route["nodes"][route["start_node"]]["lat"],
            route["nodes"][route["start_node"]]["lng"],
        ]] + pts for name, pts in trails.items()},
        "fly": fly_cockpit,
        "arrivals": arrivals,
        "rl": rl,
        "closest": closest,
        "theater": theater,
        "verdict": {"txt": verdict_txt, "detail": verdict_detail},
        "gap_chip": {"txt": gap_txt, "detail": "final distance-to-goal: FLY %.1f m · COIN %.1f m" % (summary["walkers"]["fly"]["final_dist_m"], summary["walkers"]["coin"]["final_dist_m"])} if gap_txt else None,
        "ycap": round(ycap, 1),
        "walk_cap": round(walk_cap, 1),
        "max_tick": max((p[0] for s in series.values() for p in s), default=0),
        "frames": len([f for f in os.listdir(frames_src) if f.endswith(".png")])
        if os.path.isdir(frames_src) else 0,
    }

    lead, rows_html, _ = honesty_html(summary, close, arrivals, run_id)
    route_payload = dict(route)
    del route_payload["nodes"]
    del route_payload["edges"]
    route_payload["node_count"] = len(route["nodes"])
    route_payload["edge_count"] = sum(len(v) for v in route["edges"].values())
    prov = prov_html(route_payload, summary, run_id, crow_m, "%s \u2192 %s" % (label[0], label[1]), _wall_est(summary), theater)

    html = (PAGE_TEMPLATE
            .replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":")))
            .replace("__HONESTY_LEAD__", lead)
            .replace("__HONESTY_ROWS__", rows_html)
            .replace("__PROV__", prov))

    out = os.path.join(replay_dir, "index.html")
    with open(out, "w") as f:
        f.write(html)

    shutil.copy(os.path.join(run_dir, "route.json"), os.path.join(replay_dir, "route.json"))
    with open(os.path.join(replay_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    size_mb = os.path.getsize(out) / 1024 / 1024
    print(f"replay written: {out} ({size_mb:.2f} MB, "
          f"theater {theater['node_count']}/{theater['edge_count']} "
          f"nodes/edges total, embedded {len(theater['nodes'])} nodes)")
    print(f"  payload: max_tick={payload['max_tick']}, frames={payload['frames']}, "
          f"rl pulses={len(rl)}, arrivals={len(arrivals)}")


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