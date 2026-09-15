"""Decision policies for the three walkers.

Every policy answers the same question: standing on node X with candidate
neighbors [n1..nk], which one do you move to? The FLY policy answers via the
oracle (MaleCNS spike decode); COIN and GREEDY are its control counterparts.
"""

import random


class OracleClient:
    """Thin HTTP client for the oracle sidecar."""

    def __init__(self, base_url, timeout=600):
        import requests

        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.http = requests.Session()

    def consult(self, png_bytes, reinforcement=None):
        import base64 as b64

        body = {"png_b64": b64.b64encode(png_bytes).decode()}
        if reinforcement:
            body["reinforcement"] = reinforcement
        resp = self.http.post(f"{self.base}/consult", json=body, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def reinforce(self, sign):
        resp = self.http.post(f"{self.base}/{sign}", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def checkpoint(self):
        resp = self.http.post(f"{self.base}/checkpoint", timeout=300)
        resp.raise_for_status()
        return resp.json()

    def vitals(self):
        resp = self.http.get(f"{self.base}/vitals", timeout=30)
        resp.raise_for_status()
        return resp.json()


class CoinPolicy:
    """Control: zero-information navigation."""

    def __init__(self, seed=42):
        self.rng = random.Random(seed)

    def choose(self, node, candidates, run_dir):
        return self.rng.choice(candidates), None


class GreedyPolicy:
    """Control: always step to the candidate that most reduces straight-line
    distance to the goal. Crow-flies instinct, not pathfinding - dead ends
    still trap it."""

    def __init__(self, goal, nodes):
        self.goal = goal
        self.nodes = nodes

    def choose(self, node, candidates, run_dir):
        from corridor import haversine_m

        def dist(nid):
            rec = self.nodes[nid]
            return haversine_m(rec["lat"], rec["lng"], self.goal["lat"], self.goal["lng"])

        return min(candidates, key=dist), None


class FlyPolicy:
    """Protagonist: consult the brain once per candidate (round-robin),
    move to the candidate with the highest approach_hz (mean DNp20 firing
    while viewing it). Reinforcement for the previous move rides along on the
    first consult of this tick, following Stonkfly's "delivered at the next
    observation" semantics."""

    def __init__(self, oracle, goal, nodes, timing_stats=None):
        self.oracle = oracle
        self.goal = goal
        self.nodes = nodes
        self.pending_sign = None  # "reward" | "aversive" | None
        self.timing = timing_stats

    def choose(self, node, candidates, run_dir):
        import os
        import time

        from corridor import haversine_m
        from frames import option_frame

        letters = ["A", "B", "C", "D", "E"]
        results = []
        for i, (letter, nid) in enumerate(zip(letters, candidates)):
            rec = self.nodes[nid]
            frame = option_frame(run_dir, rec, letter)
            reinforcement = self.pending_sign if i == 0 else None
            t0 = time.monotonic()
            obs = self.oracle.consult(frame, reinforcement)
            consult_s = time.monotonic() - t0
            if self.timing:
                self.timing.record_consult(consult_s)
            results.append(
                {
                    "node": nid,
                    "letter": letter,
                    "approach_hz": obs["approach_hz"],
                    "side": obs["side"],
                    "left_hz": obs["left_hz"],
                    "right_hz": obs["right_hz"],
                    "difference_hz": obs["difference_hz"],
                    "gate_spikes": obs["gate_spikes"],
                    "total_spikes": obs.get("total_spikes"),
                    "compute_seconds": obs.get("compute_seconds"),
                    "brain_kind": obs.get("brain_kind"),
                    "oracle_consult": obs.get("oracle_consult"),
                    "reinforcement": reinforcement or "none",
                    "consult_ms": round(consult_s * 1000, 1),
                }
            )
        best = max(results, key=lambda s: s["approach_hz"])
        self.pending_sign = None  # consumed
        return best["node"], {"candidates": results}
