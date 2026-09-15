"""Mapillary v4 corridor: fetch street-level image nodes in a bbox and build
a walkable graph (sequence adjacency + nearby cross-sequence links).

TODO(run-time): verify live API field shapes (thumb_1024_url, Link pagination)
on first real fetch; shapes here follow the documented v4 graph API.
"""

import json
import math
import os
import time

GRAPH_URL = "https://graph.mapillary.com/images"
FIELDS = "id,geometry,sequence_id,captured_at,is_pano,compass_angle,thumb_1024_url"


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fetch_images(
    bbox,
    token,
    session=None,
    max_pages=50,
    line_filter=None,
    stop_after=8000,
):
    """bbox = (south, west, north, east). Returns list of image records.

    line_filter = (start, goal, half_width_m) keeps only images within
    half_width_m of the start-goal straight line (dense cities return tens of
    thousands of results; the corridor line keeps the graph tractable).
    Retries 5xx responses with backoff (the endpoint occasionally 500s).
    """
    import requests

    s = session or requests
    south, west, north, east = bbox
    params = {
        "bbox": f"{west},{south},{east},{north}",
        "fields": FIELDS,
        "access_token": token,
    }

    def acceptable(img):
        if line_filter is None:
            return True
        start, goal, half_width_m = line_filter
        rec = _record(img)
        if rec["lat"] is None:
            return False
        d = haversine_m(rec["lat"], rec["lng"], goal["lat"], goal["lng"])
        ax, ay = start["lng"], start["lat"]
        bx, by = goal["lng"], goal["lat"]
        dx, dy = bx - ax, by - ay
        span2 = dx * dx + dy * dy
        px, py = rec["lng"], rec["lat"]
        if span2 == 0:
            return haversine_m(py, px, ay, ax) <= half_width_m * 3
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / span2))
        cx, cy = ax + t * dx, ay + t * dy
        return haversine_m(py, px, cy, cx) <= half_width_m

    images, page = [], 0
    url, params_current = GRAPH_URL, params
    while True:
        resp = None
        for attempt in range(4):
            try:
                resp = s.get(url, params=params_current, timeout=60)
                if resp.status_code < 500:
                    break
            except requests.RequestException:
                if attempt == 3:
                    raise
            time.sleep(3 * (attempt + 1))
        if resp is None or resp.status_code >= 500:
            raise RuntimeError(f"Mapillary kept 5xx-ing (page {page})")
        resp.raise_for_status()
        payload = resp.json()
        batch = payload.get("data", [])
        images.extend(img for img in batch if acceptable(img))
        next_url = resp.links.get("next", {}).get("url")
        page += 1
        if not next_url or page >= max_pages or len(images) >= stop_after:
            break
        url, params_current = next_url, None
    return images


def _tile_bboxes(bbox, tile_m=200.0):
    """Split bbox into ~tile_m squares. Empirically, the /images endpoint
    500s when a bbox yields more than ~1500 results (no pagination offered
    for this query shape), so tiles stay small and results get merged."""
    import math

    south, west, north, east = bbox
    mid_lat = (south + north) / 2
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = 111_320.0 * math.cos(math.radians(mid_lat))
    d_lat = tile_m / m_per_deg_lat
    d_lng = tile_m / m_per_deg_lng
    cols = max(1, math.ceil((east - west) / d_lng))
    rows = max(1, math.ceil((north - south) / d_lat))
    tiles = []
    for i in range(cols):
        for j in range(rows):
            w = west + i * d_lng
            e = min(w + d_lng, east)
            s = south + j * d_lat
            n = min(s + d_lat, north)
            tiles.append((s, w, n, e))
    return tiles


def fetch_images_tiled(bbox, token, session=None, tile_m=200.0, line_filter=None, stop_after=30000, politeness_s=0.4):
    """Fetch a dense city corridor by tiling the bbox and merging (dedup by id).

    stop_after exists as a runaway guard; set it high enough to cover the
    whole corridor (6400 kept ≈ one third of this Lisbon corridor)."""
    import requests

    s = session or requests
    tiles = _tile_bboxes(bbox, tile_m)
    seen = {}
    for i, tile in enumerate(tiles):
        try:
            batch = fetch_images(
                tile, token, session=s, max_pages=2, line_filter=line_filter, stop_after=stop_after - len(seen)
            )
        except RuntimeError as exc:
            raise RuntimeError(f"tile {i} ({tile}): {exc}") from exc
        for img in batch:
            seen[str(img["id"])] = img
        if i % 10 == 0:
            print(f"  tile {i + 1}/{len(tiles)}: kept {len(seen)} images", flush=True)
        time.sleep(politeness_s)
        if len(seen) >= stop_after:
            break
    return list(seen.values())


def _record(img):
    geom = img.get("geometry", {})
    coords = geom.get("coordinates", [None, None])
    return {
        "id": str(img["id"]),
        "lng": coords[0],
        "lat": coords[1],
        "seq": str(img.get("sequence_id") or ""),
        "captured_at": img.get("captured_at") or "",
        "pano": bool(img.get("is_pano", False)),
        "compass": img.get("compass_angle"),
        "thumb": img.get("thumb_1024_url"),
    }


def build_graph(images, cross_radius_m=15.0, cross_k=4):
    """Nodes + spatial adjacency edges.

    Note: the v4 /images list endpoint does not reliably return
    `sequence_id` (observed empty in the wild), so adjacency is purely
    spatial: each image links to its K nearest neighbors within
    cross_radius_m. Same-position captures (pano bursts) link to each other
    at distance 0 - stepping through them is the fly "looking around".
    Returns (nodes, edges)."""
    nodes = {}
    for img in images:
        rec = _record(img)
        if rec["lat"] is None or not rec["thumb"]:
            continue
        nodes[rec["id"]] = rec

    # grid bucket for neighbor queries (cell = cross_radius_m)
    m_per_deg_lat = 111_320.0
    cell = cross_radius_m / m_per_deg_lat
    mid_lat = (min(r["lat"] for r in nodes.values()) + max(r["lat"] for r in nodes.values())) / 2
    m_per_deg_lng = 111_320.0 * math.cos(math.radians(mid_lat))
    lng_cell = cross_radius_m / m_per_deg_lng

    def cell_of(rec):
        return (int(rec["lng"] // lng_cell), int(rec["lat"] // cell))

    buckets = {}
    for nid, rec in nodes.items():
        buckets.setdefault(cell_of(rec), []).append(nid)

    edges = {nid: set() for nid in nodes}
    for nid, rec in nodes.items():
        cx, cy = cell_of(rec)
        near = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((cx + dx, cy + dy), []):
                    if other == nid:
                        continue
                    d = haversine_m(rec["lat"], rec["lng"], nodes[other]["lat"], nodes[other]["lng"])
                    if d <= cross_radius_m:
                        near.append((d, other))
        near.sort()
        for _, other in near[:cross_k]:
            edges[nid].add(other)
            edges[other].add(nid)

    edges = {nid: sorted(e) for nid, e in edges.items()}
    connected = {nid for nid, e in edges.items() if e}
    nodes = {nid: rec for nid, rec in nodes.items() if nid in connected}
    edges = {nid: e for nid, e in edges.items() if nid in connected}
    return nodes, edges


def nearest_node(nodes, lat, lng):
    return min(nodes, key=lambda nid: haversine_m(lat, lng, nodes[nid]["lat"], nodes[nid]["lng"]))


def clip_to_corridor(nodes, edges, start_node, goal, half_width_m=300.0):
    """Drop nodes farther than half_width_m from the start-goal straight line,
    then keep only nodes reachable from start_node (no detached islands)."""
    srec = nodes[start_node]
    ax, ay = srec["lng"], srec["lat"]
    bx, by = goal["lng"], goal["lat"]
    dx, dy = bx - ax, by - ay
    span2 = dx * dx + dy * dy

    def line_dist(rec):
        if span2 == 0:
            return haversine_m(rec["lat"], rec["lng"], ay, ax)
        t = max(0.0, min(1.0, ((rec["lng"] - ax) * dx + (rec["lat"] - ay) * dy) / span2))
        cx, cy = ax + t * dx, ay + t * dy
        return haversine_m(rec["lat"], rec["lng"], cy, cx)

    keep = {nid for nid, rec in nodes.items() if line_dist(rec) <= half_width_m}
    keep.add(start_node)
    reachable, stack = {start_node}, [start_node]
    while stack:
        cur = stack.pop()
        for nxt in edges[cur]:
            if nxt in keep and nxt not in reachable:
                reachable.add(nxt)
                stack.append(nxt)
    nodes = {nid: rec for nid, rec in nodes.items() if nid in reachable}
    edges = {nid: [o for o in e if o in reachable] for nid, e in edges.items() if nid in reachable}
    return nodes, edges


def largest_component_with(nodes, edges, anchor):
    """Return (nodes, edges) of the connected component containing `anchor`."""
    comp, stack = {anchor}, [anchor]
    while stack:
        cur = stack.pop()
        for nxt in edges[cur]:
            if nxt not in comp:
                comp.add(nxt)
                stack.append(nxt)
    return (
        {nid: rec for nid, rec in nodes.items() if nid in comp},
        {nid: e for nid, e in edges.items() if nid in comp},
    )


def build_route(bbox, start, goal, token, cache_dir, session=None):
    """Fetch (tiled, corridor-filtered), graph, clip, keep the component
    containing the goal, then snap start to the nearest node inside it.

    The pruning order matters: dense cities have disconnected capture
    islands; the fly walks one connected world, the one the goal lives in."""
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, "route.json")
    if os.path.exists(cache):
        return json.load(open(cache))

    images = fetch_images_tiled(
        bbox, token, session=session, line_filter=(start, goal, 200.0)
    )
    if len(images) < 50:
        raise RuntimeError(
            f"Corridor too thin: {len(images)} Mapillary images in bbox {bbox}. "
            "Pick a start/goal pair with dense street-level coverage."
        )
    nodes, edges = build_graph(images, cross_radius_m=30.0, cross_k=8)
    if not nodes:
        raise RuntimeError("No connected nodes after graph build - coverage too sparse.")
    nodes, edges = clip_to_corridor(nodes, edges, nearest_node(nodes, start["lat"], start["lng"]), goal)
    goal_node = nearest_node(nodes, goal["lat"], goal["lng"])
    nodes, edges = largest_component_with(nodes, edges, goal_node)

    start_node = nearest_node(nodes, start["lat"], start["lng"])
    snap_m = haversine_m(start["lat"], start["lng"], nodes[start_node]["lat"], nodes[start_node]["lng"])
    if snap_m > 400.0:
        print(
            f"WARNING: requested start snaps {snap_m:.0f}m away inside the goal's "
            "connected imagery - consider moving the start point."
        )
    route = {
        "bbox": list(bbox),
        "start": start,
        "goal": goal,
        "goal_node": goal_node,
        "start_node": start_node,
        "start_snap_m": round(snap_m, 1),
        "nodes": nodes,
        "edges": edges,
        "source": "mapillary",
        "fetched_at": time.time(),
        "image_count": len(images),
    }
    tmp = cache + ".partial"
    with open(tmp, "w") as f:
        json.dump(route, f)
    os.replace(tmp, cache)
    return route
