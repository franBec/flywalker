# sample/nata2 — the real Santa Justa to Carmo (run v2) run, ready to watch

This is an actual run artifact, packaged so a fresh clone of the repo
shows the replay without running the simulation pipeline.

- `replay/index.html` — the full replay page: walk logs, decoded
  approach scores, charts, reinforcement ledger and the honesty section
  are all embedded. Serve it as-is.
- `replay/frames/*.webp` — the 400 flycam frames, re-encoded from the
  original PNGs to WebP q80 (roughly 8x smaller). The page prefers
  `.webp` and falls back to `.png`, so a full-fidelity build also works.
  Every decoded score and statistic is computed from the exact run logs.
- `route.json`, `summary.json` — byte-exact provenance copies.

Watch it:

    cd sample/nata2/replay && python3 -m http.server 8080
    # open http://localhost:8080

The v1 run (nata) is not shipped: its 1,200 PNG frames weigh ~100 MB.
Rebuild this sample with:  python tools/ship_sample.py
