"""The flywalker run loop.

One narrative run, three walkers on the same corridor:

    python walk.py [--run-id NAME] [--mock-corridor]

Progress lives in runs/<run_id>/walk.jsonl (one JSON line per move), which is
also the resume log: after a spot preemption (VM stops, boots, compose re-runs
this script), the walk continues from the last logged step. The fly's brain
state is checkpointed separately by the oracle (see oracle/app/brain.py).
"""

import argparse
import json
import os
import time

import corridor
from policies import CoinPolicy, FlyPolicy, GreedyPolicy, OracleClient


def env_float(name, default):
    return float(os.environ.get(name, default))


def env_int(name, default):
    return int(os.environ.get(name, default))


def parse_bbox(text):
    s, w, n, e = [float(x) for x in text.split(",")]
    return (s, w, n, e)


def parse_point(text):
    lat, lng = [float(x) for x in text.split(",")]
    return {"lat": lat, "lng": lng}


class RunLogger:
    """JSONL append-only log with fsync per line (preemption safety)."""

    def __init__(self, path):
        self.path = path
        self.handle = open(path, "a", buffering=1)

    def log(self, record):
        record["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def read_all(self):
        records = []
        if not os.path.exists(self.path):
            return records
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records


def load_route(args, run_dir):
    if args.mock_corridor:
        import mockcorridor

        return mockcorridor.build(run_dir)
    token = os.environ.get("MAPILLARY_TOKEN")
    if not token:
        raise SystemExit(
            "MAPILLARY_TOKEN missing in env (copy .env.sample to .env). "
            "For a tokenless plumbing test use --mock-corridor."
        )
    bbox = parse_bbox(os.environ["ROUTE_BBOX"])
    start = parse_point(os.environ["ROUTE_START"])
    goal = parse_point(os.environ["ROUTE_GOAL"])
    return corridor.build_route(bbox, start, goal, token, run_dir)


def build_walker_states(route, logger):
    """Reconstruct walker positions from the log (resume) or start fresh."""
    names = ["fly", "coin", "greedy"]
    start_node = route["start_node"]
    states = {
        name: {
            "node": start_node,
            "arrived": False,
            "steps": 0,
            "distance_m": 0.0,
            "last_dist_m": None,
        }
        for name in names
    }
    last_tick = 0
    for rec in logger.read_all():
        name = rec.get("walker")
        if rec.get("event") == "move" and name in states:
            states[name]["node"] = rec["node"]
            states[name]["steps"] += 1
            states[name]["distance_m"] += rec["moved_m"]
            states[name]["last_dist_m"] = rec["dist_m"]
            last_tick = max(last_tick, rec["tick"])
        if rec.get("event") == "arrival" and name in states:
            states[name]["arrived"] = True
    # FLY's pending reinforcement sign is derived from its last move's delta
    return states, last_tick


def wait_for_oracle(oracle, deadline_seconds=1800):
    import requests

    deadline = time.time() + deadline_seconds
    delay = 5
    while time.time() < deadline:
        try:
            oracle.vitals()
            return
        except requests.RequestException:
            print(f"oracle not ready, retrying in {delay}s...", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise SystemExit("oracle did not become ready")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=os.environ.get("RUN_ID", "nata"))
    parser.add_argument(
        "--mock-corridor",
        action="store_true",
        help="synthetic corridor + mock brain-friendly thumbs; no Mapillary needed",
    )
    args = parser.parse_args()

    data_dir = os.environ.get("DATA_DIR", "data")
    run_dir = os.path.join(data_dir, "runs", args.run_id)
    os.makedirs(run_dir, exist_ok=True)

    summary_path = os.path.join(run_dir, "summary.json")
    if os.path.exists(summary_json_path(run_dir)):
        print(f"run '{args.run_id}' already complete; nothing to do")
        return

    route = load_route(args, run_dir)
    print(
        f"route: {len(route['nodes'])} nodes, goal_node={route['goal_node']}, "
        f"start={route['start_node']}"
    )

    logger = RunLogger(os.path.join(run_dir, "walk.jsonl"))
    states, last_tick = build_walker_states(route, logger)

    oracle_url = os.environ.get("ORACLE_URL", "http://localhost:8000")
    oracle = OracleClient(oracle_url)
    wait_for_oracle(oracle)

    goal = route["goal"]
    nodes = route["nodes"]
    edges = route["edges"]
    arrival_radius = env_float("ARRIVAL_RADIUS_M", 25.0)
    deadband = env_float("PROGRESS_DEADBAND_M", 2.0)
    max_steps = env_int("MAX_STEPS", 1200)

    fly = FlyPolicy(oracle, goal, nodes)
    coin = CoinPolicy(seed=42)
    greedy = GreedyPolicy(goal, nodes)

    for name, state in states.items():
        dist = node_dist(nodes, state["node"], goal)
        state["last_dist_m"] = dist
        if dist <= arrival_radius:
            state["arrived"] = True

    print(f"resuming at tick {last_tick + 1}, max_steps={max_steps}")
    tick = last_tick
    while tick < max_steps and not all(s["arrived"] for s in states.values()):
        tick += 1
        for name in ["fly", "coin", "greedy"]:
            state = states[name]
            if state["arrived"]:
                continue
            policy = {"fly": fly, "coin": coin, "greedy": greedy}[name]
            candidates = [n for n in edges[state["node"]] if n != state["node"]]
            try:
                chosen, extra = retry_call(
                    lambda: policy.choose(state["node"], candidates, run_dir)
                )
            except Exception as exc:
                print(f"{name} failed at tick {tick}: {exc}", flush=True)
                raise
            rec = nodes[state["node"]]
            dst = nodes[chosen]
            moved = corridor.haversine_m(rec["lat"], rec["lng"], dst["lat"], dst["lng"])
            dist = corridor.haversine_m(dst["lat"], dst["lng"], goal["lat"], goal["lng"])
            prev = state["last_dist_m"] if state["last_dist_m"] is not None else dist + moved
            delta = prev - dist  # positive = closer to the nata
            line = {
                "tick": tick,
                "walker": name,
                "event": "move",
                "node": chosen,
                "from_node": state["node"],
                "lat": dst["lat"],
                "lng": dst["lng"],
                "dist_m": round(dist, 1),
                "moved_m": round(moved, 1),
                "delta_m": round(delta, 1),
                "candidates": extra.get("candidates") if extra else None,
            }
            state["node"] = chosen
            state["steps"] += 1
            state["distance_m"] += moved
            state["last_dist_m"] = dist
            if extra and name == "fly":
                # reinforcement for THIS move is delivered on the next tick's
                # first consult; keep the sign in policy state and log it
                sign = (
                    "reward"
                    if delta > deadband
                    else "aversive"
                    if delta < -deadband
                    else None
                )
                fly.pending_sign = sign
                line["queued_reinforcement"] = sign
                letter = next(
                    c["letter"] for c in extra["candidates"] if c["node"] == chosen
                )
                save_fly_frame(run_dir, tick, nodes, chosen, letter)
            logger.log(line)
            if dist <= arrival_radius:
                state["arrived"] = True
                logger.log(
                    {
                        "tick": tick,
                        "walker": name,
                        "event": "arrival",
                        "node": chosen,
                        "dist_m": round(dist, 1),
                    }
                )
                print(f"✓ {name} arrived (tick {tick}, {state['steps']} steps)")

    oracle.checkpoint()
    summary = {
        "run_id": args.run_id,
        "ticks": tick,
        "mock_corridor": bool(args.mock_corridor),
        "route_nodes": len(nodes),
        "walkers": {
            name: {
                "steps": s["steps"],
                "distance_m": round(s["distance_m"], 1),
                "arrived": s["arrived"],
                "final_dist_m": round(s["last_dist_m"], 1),
                "node": s["node"],
            }
            for name, s in states.items()
        },
        "ended_at": time.time(),
    }
    with open(summary_json_path(run_dir), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


def summary_json_path(run_dir):
    return os.path.join(run_dir, "summary.json")


def node_dist(nodes, nid, goal):
    rec = nodes[nid]
    return corridor.haversine_m(rec["lat"], rec["lng"], goal["lat"], goal["lng"])


def retry_call(fn, attempts=20, base_delay=5):
    """Call with backoff - survives oracle brain reload after preemption."""
    import requests

    delay = base_delay
    for attempt in range(attempts):
        try:
            return fn()
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 120)


def save_fly_frame(run_dir, tick, nodes, chosen, letter):
    """Re-render (deterministic) the chosen candidate's frame for the flycam."""
    from frames import option_frame

    frames_dir = os.path.join(run_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    path = os.path.join(frames_dir, f"{tick:05d}.png")
    tmp = path + ".partial"
    with open(tmp, "wb") as f:
        f.write(option_frame(run_dir, nodes[chosen], letter))
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
