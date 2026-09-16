# sample — the flywalker run, ready to watch

This is the real MaleCNS walk, packaged so a fresh clone shows the replay without running the simulation pipeline.

- `replay/index.html` — the full replay page: walk logs, decoded approach scores, charts, reinforcement ledger and the honesty section are embedded. Serve it as-is.
- `replay/frames/*.webp` — the 400 flycam frames, re-encoded from the original PNGs to WebP q80 (roughly 8x smaller). The page prefers `.webp` and falls back to `.png`, so a full-fidelity build also works. Every score and statistic is computed from the exact run logs.
- `route.json`, `summary.json` — byte-exact provenance copies.

Watch it:

    cd sample/run/replay && python3 -m http.server 8080
    # open http://localhost:8080

Rebuild this sample with:  python tools/ship_sample.py
