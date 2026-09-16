# walker/vendor — asset cache for the offline replay page

Files inlined into every `replay/index.html` by `walker/replay.py` so the
page renders with no script or stylesheet dependencies. Extracted byte-exact
from the standalone artifact `flywalker replay (offline).html` at the repo
root (which bundled project copies of them); do not bump versions without
re-testing the replay.

- `leaflet/leaflet.js` — Leaflet 1.9.4, BSD-2-Clause, (c) 2010-2023
  Vladimir Agafonkin, (c) 2010-2011 CloudMade. https://leafletjs.com
- `leaflet/leaflet.css` + `leaflet/images/` — same release, same license.
- `three.min.js` — three.js r149, MIT. https://threejs.org