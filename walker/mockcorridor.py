"""Synthetic corridor for plumbing tests: no Mapillary token, no network.

Builds a small grid "city", writes route.json in the standard shape, and
pre-generates mock thumbnails into run_dir/thumbs so frames.py treats them
exactly like real Mapillary imagery. Thumbnails encode goal direction as
brightness so the mock brain's brightness preference produces goal-ish drift.
"""

import json
import math
import os
import time

from corridor import haversine_m


def build(run_dir, nx=9, ny=7, spacing_m=35.0):
    os.makedirs(os.path.join(run_dir, "thumbs"), exist_ok=True)

    # A small patch near Lisbon so coordinates look plausible on a map
    base_lat, base_lng = 38.7100, -9.1400
    lat_step = spacing_m / 111_320.0
    lng_step = spacing_m / (111_320.0 * math.cos(math.radians(base_lat)))

    goal_latlng = {"lat": base_lat, "lng": base_lng + (nx - 1) * lng_step}
    nodes, edges = {}, {}
    for y in range(ny):
        seq = f"mock-row-{y}"
        for x in range(nx):
            nid = f"mock-{x:02d}-{y:02d}"
            nodes[nid] = {
                "id": nid,
                "lat": base_lat + y * lat_step,
                "lng": base_lng + x * lng_step,
                "seq": seq,
                "captured_at": "2026-01-01T00:00:00Z",
                "pano": False,
                "compass": 90.0,
                "thumb": f"mock://{nid}",
            }
            edges[nid] = set()
            if x > 0:
                edges[nid].add(f"mock-{x - 1:02d}-{y:02d}")
            if x < nx - 1:
                edges[nid].add(f"mock-{x + 1:02d}-{y:02d}")
            if y > 0:
                edges[nid].add(f"mock-{x:02d}-{y - 1:02d}")
            if y < ny - 1:
                edges[nid].add(f"mock-{x:02d}-{y + 1:02d}")
    edges = {nid: sorted(e) for nid, e in edges.items()}

    start = f"mock-00-{ny - 1:02d}"
    goal_node = "mock-08-00"
    goal = {"lat": nodes[goal_node]["lat"], "lng": nodes[goal_node]["lng"]}
    route = {
        "bbox": [base_lat - 0.01, base_lng - 0.01, base_lat + (ny - 1) * lat_step + 0.01, base_lng + (nx - 1) * lng_step + 0.01],
        "goal": goal,
        "goal_node": goal_node,
        "start_node": start,
        "nodes": nodes,
        "edges": edges,
        "source": "mock",
        "fetched_at": time.time(),
        "image_count": len(nodes),
    }
    with open(os.path.join(run_dir, "route.json"), "w") as f:
        json.dump(route, f, indent=2)

    for nid, rec in nodes.items():
        path = os.path.join(run_dir, "thumbs", f"{nid}.jpg")
        if not os.path.exists(path):
            d_goal = haversine_m(rec["lat"], rec["lng"], goal["lat"], goal["lng"])
            _write_mock_thumb(path, rec["id"], d_goal, max_dist=haversine_m(nodes[start]["lat"], nodes[start]["lng"], goal["lat"], goal["lng"]))
    return route


def _write_mock_thumb(path, node_id, dist_to_goal, max_dist):
    import io
    import random

    from PIL import Image, ImageDraw

    random.seed(node_id)
    proximity = 1.0 - min(1.0, dist_to_goal / max(1.0, max_dist))
    brightness = int(140 + 100 * proximity)
    im = Image.new("RGB", (160, 120), (int(brightness * 0.9), int(brightness * 0.95), brightness))
    d = ImageDraw.Draw(im)
    for _ in range(6):  # fake street furniture
        x, y = random.randint(4, 150), random.randint(4, 100)
        w, h = random.randint(8, 30), random.randint(8, 26)
        shade = random.randint(60, 130)
        d.rectangle((x, y, x + w, y + h), fill=(shade, shade, shade + 10))
    d.text((6, 100), f"MOCK {node_id}", fill=(20, 30, 60))
    im.save(path, format="JPEG", quality=85)


if __name__ == "__main__":
    import sys

    build(sys.argv[1] if len(sys.argv) > 1 else "data/runs/mock")
