#!/usr/bin/env python3
"""Package a finished run into sample/ so a fresh clone can watch it.

    python tools/ship_sample.py [--run-id nata2] [--data-dir local-runs]

Copies the rendered replay page plus route/summary provenance byte-exact.
If that replay was rendered with `replay.py --standalone`, the flycam
frames are already base64-embedded inside index.html and the sample ships
the single page (plus provenance) as-is — a double-click ready artifact.

Otherwise the flycam PNGs are re-encoded to WebP (q80, ~8x smaller) into
sample/run/replay/frames/; the replay page prefers .webp and falls back
to .png, so the sample works as-is with no pipeline.

The sample is for watching, not re-running: the raw logs stay in
local-runs/ (gitignored). The walk data itself is embedded in the page.
"""

import argparse
import json
import os
import shutil

WEBP_QUALITY = 80
WEBP_METHOD = 6

SAMPLE_README = """\
# sample — the flywalker run, ready to watch

This is the real MaleCNS walk, packaged so a fresh clone shows the replay without running the simulation pipeline.

- `replay/index.html` — the full replay page: walk logs, decoded approach scores, charts, reinforcement ledger and the honesty section are embedded. Leaflet 1.9.4 and three.js are inlined; {frames_note}
- `route.json`, `summary.json` — byte-exact provenance copies.

Watch it:

    {watch_note}

Rebuild this sample with:  python tools/ship_sample.py
"""


def embedded_frame_count(index_path):
    """Number of frames base64-embedded by replay.py --standalone (0 when
    the page reads them from the frames/ dir instead)."""
    with open(index_path, encoding="utf-8") as f:
        page = f.read()
    start = page.find("window.__resources = ")
    if start < 0:
        return 0
    start += len("window.__resources = ")
    if not page.startswith("{", start):
        return 0
    res = json.JSONDecoder().raw_decode(page[start:start + 8_000_000])[0]
    return sum(1 for k, v in res.items()
               if k.startswith("f") and isinstance(v, str) and v.startswith("data:"))


def ship(run_dir, out_dir):
    replay_src = os.path.join(run_dir, "replay")
    index_src = os.path.join(replay_src, "index.html")
    if not os.path.isfile(index_src):
        raise SystemExit(
            f"no rendered replay at {replay_src} - run "
            "python walker/replay.py --run-id <run_id> --data-dir <dir> first"
        )

    embedded = embedded_frame_count(index_src)
    frames_src = os.path.join(run_dir, "frames")
    if not embedded and not os.path.isdir(frames_src):
        raise SystemExit(f"no frames dir at {frames_src}")

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    replay_out = os.path.join(out_dir, "replay")
    os.makedirs(replay_out)
    if not embedded:
        os.makedirs(os.path.join(replay_out, "frames"))

    shutil.copy(index_src, os.path.join(replay_out, "index.html"))
    for name in ("route.json", "summary.json"):
        shutil.copy(os.path.join(run_dir, name), os.path.join(out_dir, name))

    if embedded:
        frames_note = ("the %d flycam frames are embedded in the page — "
                       "open index.html directly, no server needed"
                       % embedded)
        watch_note = ("    # double-click sample/run/replay/index.html "
                      "(the OpenStreetMap tiles still need a connection)")
    else:
        try:
            from PIL import Image
        except ImportError:
            raise SystemExit(
                "Pillow is required to re-encode the flycam frames; "
                "install walker/requirements.txt (or render the replay "
                "with --standalone and rerun this)")
        pngs = sorted(f for f in os.listdir(frames_src) if f.endswith(".png"))
        if not pngs:
            raise SystemExit(f"no .png frames found in {frames_src}")
        for f in pngs:
            basename = f[:-4] + ".webp"
            im = Image.open(os.path.join(frames_src, f)).convert("RGB")
            im.save(os.path.join(replay_out, "frames", basename),
                    format="WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
        frames_note = ("the %d flycam frames are re-encoded to WebP q80 "
                       "(roughly 8x smaller)" % len(pngs))
        watch_note = ("    cd sample/run/replay && python3 -m http.server 8080\n"
                      "    # open http://localhost:8080")

    with open(os.path.join(out_dir, "README.md"), "w") as fh:
        fh.write(SAMPLE_README.format(frames_note=frames_note,
                                      watch_note=watch_note))

    total = sum(os.path.getsize(os.path.join(root, f))
                for root, _dirs, files in os.walk(out_dir) for f in files)
    print(f"sample written: {out_dir} ({total / 1e6:.1f} MB total)"
          + (" — standalone, frames embedded" if embedded else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="nata2")
    parser.add_argument("--data-dir", default="local-runs")
    parser.add_argument("--out", default="sample/run")
    args = parser.parse_args()
    run_dir = os.path.join(args.data_dir, "runs", args.run_id)
    ship(run_dir, args.out)