"""Offline replay renderer: turn a completed run into a shareable cinematic page.

    python replay.py --run-id <run_id> --data-dir local-runs [--standalone]

Reads runs/<run_id>/{route.json,walk.jsonl,summary.json,frames} and writes
runs/<run_id>/replay/index.html: a self-contained page on the standalone
artifact's design — a three.js 3D stage puts a low-poly fly where it stood
on its capture point, the left rail holds the Leaflet junction theater, live
standings, decoded approach bars and the DNp20 differential meter, the
transport bar drives a timeline with key-moment markers, and the reading
sections below carry the honesty table and provenance. Leaflet 1.9.4 and
three.js are vendored in walker/vendor/ and inlined, so the page has no
script or stylesheet dependencies; OpenStreetMap tiles still need a network.

With --standalone the flycam frames are base64-embedded into the single
index.html as well (PNG frames are re-encoded to WebP when a converter is
available), so the page plays with no sibling files. Without it the page
loads frames from the frames/ dir (webp preferred, png fallback).

The rest of the cast, cockpit and honesty design:

- dark cinematic theme, run card with MaleCNS badges and consult stats
- hand-drawn animated fly mark in the header; the 3D stage and the map
  both carry the FLY walker, turning to its heading as the timeline plays
- flycam loads .webp frames first with a .png fallback, so the committed
  sample build (sample/) stays small
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

(The --standalone page opens directly from a file:// double-click; only its
OpenStreetMap tiles need a connection.)

No data collection logic lives here: the page only renders existing
artifacts from the walk.
"""

import argparse
import base64
import io
import json
import math
import os
import shutil
import subprocess
import tempfile

COLORS = {"fly": "#e8710a", "coin": "#9aa0a6", "greedy": "#1a73e8"}

RUN_LABELS = {
    "nata": ("Rossio", "Manteigaria"),
    "nata2": ("Santa Justa", "Carmo"),
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


def honesty_html(summary, close, arrivals):
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


def prov_html(route, summary, crow_m, label, wall_est, theater):
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
            "<table><tbody>",
            "<tr><td class='k'>run</td><td>%s \u00b7 %d ticks \u00b7 "
            "approx wall time %s \u00b7 recorded %s</td></tr>" % (
                label, summary["ticks"], wall_est, _fmt_ts(summary)),
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
            "</tbody></table>",
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


_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "replay_template.html")
_VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _template():
    return _read_text(_TEMPLATE_PATH)


def _vendor(path):
    with open(os.path.join(_VENDOR_DIR, path), "rb") as f:
        return f.read()


def _b64(blob):
    return base64.b64encode(blob).decode("ascii")


def _webp_from(data):
    """Re-encode one PNG frame to WebP q80. Pillow is the walker runtime's
    converter; ffmpeg's libwebp is the laptop fallback."""
    try:
        from PIL import Image
        bio = io.BytesIO()
        Image.open(io.BytesIO(data)).convert("RGB").save(
            bio, "WEBP", quality=80, method=6)
        return bio.getvalue()
    except Exception:
        with tempfile.NamedTemporaryFile(suffix=".png") as png, \
                tempfile.NamedTemporaryFile(suffix=".webp") as webp:
            png.write(data)
            png.flush()
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", png.name,
                 "-c:v", "libwebp", "-q:v", "80", webp.name],
                check=True)
            return open(webp.name, "rb").read()


def frame_listing(frames_src):
    """[(tick, mime, bytes)] for every flycam frame, in tick order. Existing
    .webp files are used as-is; .png frames are re-encoded to webp when a
    converter is available and embedded as png otherwise."""
    out = []
    names = [f for f in os.listdir(frames_src)
             if f.endswith((".png", ".webp"))]
    for tick in sorted({int(f[:5]) for f in names}):
        webp = os.path.join(frames_src, "%05d.webp" % tick)
        png = os.path.join(frames_src, "%05d.png" % tick)
        if os.path.isfile(webp):
            with open(webp, "rb") as f:
                out.append((tick, "image/webp", f.read()))
        elif os.path.isfile(png):
            with open(png, "rb") as f:
                data = f.read()
            try:
                out.append((tick, "image/webp", _webp_from(data)))
            except Exception as err:
                print("  frame %05d webp conversion failed, embedding png: %s"
                      % (tick, err))
                out.append((tick, "image/png", data))
    return out


def _resources_js(frames):
    """window.__resources map: f00001 -> data: URI, with </ escaped so the
    JSON survives inside the page's <script> block."""
    res = {
        "f%05d" % t: "data:%s;base64,%s" % (mime, _b64(blob))
        for t, mime, blob in frames
    }
    return json.dumps(res, separators=(",", ":")).replace("</", "<\\/")


def render(run_dir, standalone=False):
    route, lines, summary = load(run_dir)
    replay_dir = os.path.join(run_dir, "replay")
    os.makedirs(replay_dir, exist_ok=True)

    frames_src = os.path.join(run_dir, "frames")
    frames = frame_listing(frames_src) if os.path.isdir(frames_src) else []
    if standalone:
        print(f"  embedding {len(frames)} flycam frames into index.html")
    elif frames:
        shutil.copytree(frames_src, os.path.join(replay_dir, "frames"), dirs_exist_ok=True)

    series, trails, trail_nodes, fly_cockpit, arrivals, rl = process_lines(lines)
    theater = theater_subgraph(route, trail_nodes)
    close = closeness_stats(series)
    run_id = summary["run_id"]

    label = RUN_LABELS.get(run_id, (route["start"]["lat"], route["goal"]["lat"]))
    if isinstance(label[0], float):
        label = ("start", "goal")
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
            "label": "%s \u2192 %s" % (label[0], label[1]),
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
        "frames": len(frames),
    }

    lead, rows_html, _ = honesty_html(summary, close, arrivals)
    route_payload = dict(route)
    del route_payload["nodes"]
    del route_payload["edges"]
    route_payload["node_count"] = len(route["nodes"])
    route_payload["edge_count"] = sum(len(v) for v in route["edges"].values())
    prov = prov_html(route_payload, summary, crow_m, "%s \u2192 %s" % (label[0], label[1]), _wall_est(summary), theater)

    html = (_template()
            .replace("__LEAFLET_CSS__", _vendor("leaflet/leaflet.css").decode("utf-8"))
            .replace("__LEAFLET_JS__", _vendor("leaflet/leaflet.js").decode("utf-8"))
            .replace("__THREE_JS__", _vendor("three.min.js").decode("utf-8"))
            .replace("__RESOURCES__", _resources_js(frames) if standalone else "{}")
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
    parser.add_argument("--standalone", action="store_true",
                        help="embed flycam frames into the single index.html "
                             "(no frames/ dir needed)")
    args = parser.parse_args()
    render(os.path.join(args.data_dir, "runs", args.run_id),
           standalone=args.standalone)