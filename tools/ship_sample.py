#!/usr/bin/env python3
"""Package a finished run into sample/ so a fresh clone can watch it.

    python tools/ship_sample.py [--run-id nata2] [--data-dir local-runs]

Copies the rendered replay page plus route/summary provenance byte-exact,
and re-encodes the flycam PNGs to WebP (q80, ~8x smaller) into
sample/<run_id>/replay/frames/. The replay page prefers .webp and falls
back to .png, so the sample works as-is with no pipeline.

The sample is for watching, not re-running: the raw logs stay in
local-runs/ (gitignored). The walk data itself is embedded in the page.
"""

import argparse
import os
import shutil

from PIL import Image

WEBP_QUALITY = 80
WEBP_METHOD = 6

SAMPLE_README = """\
# sample/{run_id} — the real {label} run, ready to watch

This is an actual run artifact, packaged so a fresh clone of the repo
shows the replay without running the simulation pipeline.

- `replay/index.html` — the full replay page: walk logs, decoded
  approach scores, charts, reinforcement ledger and the honesty section
  are all embedded. Serve it as-is.
- `replay/frames/*.webp` — the {frames} flycam frames, re-encoded from the
  original PNGs to WebP q80 (roughly 8x smaller). The page prefers
  `.webp` and falls back to `.png`, so a full-fidelity build also works.
  Every decoded score and statistic is computed from the exact run logs.
- `route.json`, `summary.json` — byte-exact provenance copies.

Watch it:

    cd sample/{run_id}/replay && python3 -m http.server 8080
    # open http://localhost:8080

The v1 run (nata) is not shipped: its 1,200 PNG frames weigh ~100 MB.
Rebuild this sample with:  python tools/ship_sample.py
"""


def ship(run_dir, out_dir, run_id, label):
    replay_src = os.path.join(run_dir, "replay")
    index_src = os.path.join(replay_src, "index.html")
    if not os.path.isfile(index_src):
        raise SystemExit(
            f"no rendered replay at {replay_src} - run "
            f"python walker/replay.py --run-id {run_id} --data-dir <dir> first"
        )
    frames_src = os.path.join(run_dir, "frames")
    if not os.path.isdir(frames_src):
        raise SystemExit(f"no frames dir at {frames_src}")

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    frames_out = os.path.join(out_dir, "replay", "frames")
    os.makedirs(frames_out)

    shutil.copy(index_src, os.path.join(out_dir, "replay", "index.html"))
    for name in ("route.json", "summary.json"):
        shutil.copy(os.path.join(run_dir, name), os.path.join(out_dir, name))

    pngs = sorted(f for f in os.listdir(frames_src) if f.endswith(".png"))
    if not pngs:
        raise SystemExit(f"no .png frames found in {frames_src}")
    for f in pngs:
        basename = f[:-4] + ".webp"
        im = Image.open(os.path.join(frames_src, f)).convert("RGB")
        im.save(os.path.join(frames_out, basename), format="WEBP",
                quality=WEBP_QUALITY, method=WEBP_METHOD)

    with open(os.path.join(out_dir, "README.md"), "w") as fh:
        fh.write(SAMPLE_README.format(
            run_id=run_id, label=label, frames=len(pngs)))

    total = 0
    for root, _dirs, files in os.walk(out_dir):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    print(f"sample written: {out_dir}")
    print(f"  {len(pngs)} frames re-encoded to webp q{WEBP_QUALITY} "
          f"({total / 1e6:.1f} MB total)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="nata2")
    parser.add_argument("--data-dir", default="local-runs")
    args = parser.parse_args()
    run_dir = os.path.join(args.data_dir, "runs", args.run_id)
    out_dir = os.path.join("sample", args.run_id)
    labels = {"nata": "Rossio to Manteigaria (run v1)",
              "nata2": "Santa Justa to Carmo (run v2)"}
    ship(run_dir, out_dir, args.run_id, labels.get(args.run_id, args.run_id))