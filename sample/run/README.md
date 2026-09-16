# sample — the flywalker run, ready to watch

This is the real MaleCNS walk, packaged so a fresh clone shows the replay without running the simulation pipeline.

- `replay/index.html` — the full replay page: walk logs, decoded approach scores, charts, reinforcement ledger and the honesty section are embedded. Leaflet 1.9.4 and three.js are inlined; the 400 flycam frames are embedded in the page — open index.html directly, no server needed
- `route.json`, `summary.json` — byte-exact provenance copies.

Watch it:

        # double-click sample/run/replay/index.html (the OpenStreetMap tiles still need a connection)

Rebuild this sample with:  python tools/ship_sample.py
