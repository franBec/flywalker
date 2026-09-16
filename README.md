# flywalker

A retained simulation of the adult male fruit fly central nervous system, given a body: a walker on real street-level imagery from Lisbon, with one mission, find pastel de nata.

The brain is MaleCNS v1.0, the connectome Google Research and HHMI Janelia released in September 2026: 166,700 neurons, 25.6M directed connections, 124M synaptic contacts. The neural simulation comes from [Stonkfly](https://github.com/nftechie/stonkfly) (MIT), reused unmodified.

Three walkers traverse the same corridor of Mapillary images and log every step:

- **FLY** shows each junction's candidate street images to the simulated connectome, one candidate per consult, through the mapped R1-R6 and R8 photoreceptors. Spike activity in descending neurons is decoded into an approach score and the fly moves to the highest-scoring candidate. Progress toward the goal pulses dopamine into 15 PAM11 cells; regression pulses the 2 aversive PPL101 cells. The KC to MBON candidate memory rule may or may not accumulate anything useful. That is part of the experiment. (Since v2 the frames carry a goal meter — a display-adapter column whose height says how close each candidate gets to the nata — so the connectome's salience has something navigation-shaped to react to.)
- **COIN** has no brain. It picks a uniformly random neighbor each step. This is the noise floor.
- **GREEDY** has no brain. It always steps to the candidate that most reduces straight-line distance to the goal. This is the sense-of-direction ceiling.

FLY's result alone means nothing. Against COIN it says whether the fly beats noise. Against GREEDY it says how far the fly is from intent. Both baselines run in the same walk on the same terrain.

## Honesty, read before sharing any result

Connectome weights are anatomy, not a living fly. The decoder is an engineered mapping, inherited from Stonkfly's DNp20 left/right differential with a DNpe017 spike gate, not a discovery of walk neurons. Dopamine and aversive pulses are engineered reinforcement signals, not modeled pain or pleasure. The visual adapter, light-background 320x180 RGB frames, is an explicit display proxy — and since v2 it includes a goal meter: a chart-ink column whose height encodes how much each candidate reduces straight-line distance to the goal, because the v1 walk proved the connectome's own visual salience carries no navigation signal. An earlier v2 attempt at a brightness veil was measured direction-blind against the real brain and reverted. That is engineered input, not retinal physiology; the FLY decisions are still made by the actual MaleCNS connectome on frames that are honest about being goal-tinted. The likely outcome is that FLY statistically resembles COIN, which is a valid and honest result. Stonkfly's own validation docs demonstrated no learned trading skill, and the original Doom-fly authors report mostly no-op play.

## Route v2 (coverage-verified 2026-09-15)

Rossio square to the Rua de Santa Justa / Largo do Carmo neighbourhood. 369m crow-flies between start and goal — short enough that a direction-aware walker can actually arrive. The values live in `.env` as `ROUTE_BBOX`, `ROUTE_START`, `ROUTE_GOAL`.

**Start position (2026-09-16):** the walker now starts on the goal-descent path at `38.716061,-9.140325` (125m crow-flies from the goal). The original Rossio start was a measured local minimum: within the spatial graph every edge from it increases distance to the goal, so neither GREEDY nor the goal-bias veil can move through it. Run `walker` analysis (BFS + greedy simulation on the cached route) located the first reachable node with a descending path. This made the corridor navigable (GREEDY arrived in 23 steps) and isolated the remaining blocker as the connectome's visual salience itself.

The v2 frame pipeline also carries the goal signal as the display-adapter's chart-native goal meter (see Honesty): `walker/frames.py` renders a dark column whose height encodes how much each candidate reduces distance to the goal versus the fly's current node. Both the meter and the earlier brightness veil were measured inert against the live MaleCNS brain during v2's probe phase (veil: per-junction correlation ~+0.01, hz drift −1.8 Hz across the full boost range; meter: per-junction correlation −0.07 over 32 probe junctions while GREEDY descended the same corridor in 23 steps). Knobs: `GOAL_SALIENCE_K`/`GOAL_SALIENCE_ABS` (brightness veil, default off), `GOAL_SALIENCE_L` (delta length scale in metres, default 3), `GOAL_METER_W`/`GOAL_METER_H` (column size in px, 26×80).

Mapillary's `/images` endpoint rejects bboxes larger than about 100m as of 2026-09 (it 500s past ~1500 results and offers no pagination), so `corridor.py` fetches the corridor as a grid of 100m tiles, filters each page to images within 200m of the start-goal line, and merges results by id. The list endpoint never returns `sequence_id`, so adjacency is purely spatial: each image links to its nearest neighbors within 30m. Dense cities produce disconnected capture islands, so the route keeps only the connected component that contains the goal, then snaps the requested start to the nearest node inside it.

## Route v1 (historic)

Rossio square to Manteigaria in Chiado, 990m crow-flies, 10,253-node connected component. Replaced in v2 because the walkers could not traverse it in 1200 steps.

## Results (run v1)

| Walker | Steps | Distance walked | Final distance to goal | Arrived? |
|--------|-------|-----------------|------------------------|----------|
| FLY | 1200 | 444.4m | 1000.9m | No |
| COIN | 1200 | 406.9m | 1004.1m | No |
| GREEDY | 1200 | 869.0m | 1000.4m | No |

None arrived. All three walkers ended ~1000m from the goal after 1200 steps (started at ~990m). FLY statistically resembles COIN — the connectome-driven walker did not beat the random baseline. GREEDY walked more distance but still didn't arrive, suggesting the corridor's spatial graph doesn't have a connected path that reduces crow-flies distance to the goal.

Timing: 76 brain consults, avg 4,542ms per consult, p95 5,934ms, total brain time 362.7s (~6 minutes). The walk itself took ~8 hours wall time (including preemption recovery from spot VM).

## Results (run v2)

Goal meter input channel, 125m Santa Justa corridor, MAX_STEPS=400.

| Walker | Steps | Distance walked | Final distance to goal | Arrived? |
|--------|-------|-----------------|------------------------|----------|
| FLY | 400 | 691.1m | 106.1m | No |
| COIN | 400 | 776.7m | 117.7m | No |
| GREEDY | 23 | 151.3m | 15.9m | Yes |

GREEDY navigated the corridor cleanly and reached the nata. Neither FLY nor COIN did: the corridor's start pocket hands the fly a tight knot of near-equidistant captures, and both walkers burned their 400 ticks doing 690-780m of lateral walking inside it (FLY net −19.4m, COIN net −8.9m). FLY ended 11.6m closer than COIN and was closer on net distance, but only on 117/400 ticks (29%) — a direction-consistent but statistically weak edge, inseparable from random variation at tick resolution. The goal meter itself was probed inert against the live brain before the run (per-junction corr −0.07, n=32 junctions). The honest v2 read: a real connectome making real decisions on goal-tinted frames still cannot turn visual salience into navigation, even on a corridor where GREEDY walks the answer in 23 steps.

Timing: 64 trackable consults in the tail window, avg 4,640ms per consult, p95 6,075ms, avg tick 23.3s. The full 400-tick run took ~2.6h wall time.

Runs/artifacts: `local-runs/runs/nata2/` (route.json, walk.jsonl, summary.json, 400 flycam frames, thumbs). Replay: `local-runs/runs/nata2/replay/index.html`.

## Layout

```
infra/       Terraform: on-demand e2-highmem-4 (16GB), no inbound ports
oracle/      FastAPI sidecar wrapping Stonkfly's neural package
walker/      Mapillary corridor builder, walker loop, replay renderer
compose.yml  prepare (dataset) -> oracle -> walker, shared /data volume
```

## The oracle API

```
POST /consult    {"png_b64": ...} -> spike stats + approach score for one frame
POST /reward     queue a dopamine pulse, delivered during the next consult
POST /punish     queue an aversive pulse, delivered during the next consult
GET  /vitals     brain state, consult count, memory stats
GET  /health     liveness, does not force brain load
GET  /report     circuit report with cell identities
POST /checkpoint save brain state
```

`FLY_BRAIN=real` serves the MaleCNS graph. `FLY_BRAIN=mock` serves deterministic pseudo-scores derived from pixel statistics, so the walker and replay pipeline run end to end on a laptop with no dataset and no GPU.

## Run the local smoke test

The mock path needs no Mapillary token and no dataset.

1. Copy `.env.sample` to `.env`. Set `FLY_BRAIN=mock`.
2. Create a venv with `oracle/mock-requirements.txt` and `walker/requirements.txt`.
3. Start the oracle: `uvicorn app.main:app --app-dir oracle --port 8000`.
4. From `walker/`, run `python walk.py --run-id smoke --mock-corridor`. This builds a synthetic 63-node grid city and walks FLY, COIN, and GREEDY through it.
5. Render the replay with `python replay.py --run-id smoke`. Open `runs/smoke/replay/index.html`.

In the verified smoke run FLY arrived in 59 steps, COIN wandered to 298m and gave up, and GREEDY walked 12 steps to the nata.

## Run on GCP

### Prerequisites

- GCP project with billing enabled and Compute Engine API activated
- `gcloud` authenticated (`gcloud auth login` and `gcloud auth application-default login`)
- Terraform (or use the pre-built binary: `curl -fsSL https://releases.hashicorp.com/terraform/1.14.0/terraform_1.14.0_linux_amd64.zip | funzip > /tmp/terraform && chmod +x /tmp/terraform`)

### Setup

1. Push this repo to GitHub. The VM clones it on boot (`infra/variables.tf` holds the URL and ref).
2. Create `infra/terraform.tfvars` (gitignored):
   ```hcl
   project_id      = "flywalker"
   mapillary_token = "MLY|YOUR_TOKEN_HERE"
   ```
3. `cd infra && terraform init && terraform plan && terraform apply`. The module creates an on-demand `e2-highmem-4` in `europe-west4` with a 25GB boot disk.
4. First boot: the startup script installs Docker, creates 4GB swap, clones the repo, writes `.env` from instance metadata, and runs `docker compose up -d --build`.
5. The `prepare` service downloads the MaleCNS dataset (~1GB) and builds the graph into the shared `/data` volume. The oracle compiles Stonkfly's LIF kernel on first brain load (tens of seconds). The walker then starts the walk.

### Monitoring

```bash
# SSH into the VM
gcloud compute ssh flywalker --zone=europe-west4-a

# Check services
sudo docker compose -f /opt/flywalker/compose.yml ps

# Watch the walk (stdout is buffered; timing lines every 10 ticks)
sudo docker compose -f /opt/flywalker/compose.yml logs -f walker

# Check walk progress via JSONL (works even when stdout is buffered)
sudo docker compose -f /opt/flywalker/compose.yml exec walker sh -c 'wc -l /data/runs/nata/walk.jsonl && tail -1 /data/runs/nata/walk.jsonl'

# Check consult latency
sudo docker compose -f /opt/flywalker/compose.yml exec walker sh -c 'tail -1 /data/runs/nata/walk.jsonl' | python3 -m json.tool | grep consult_ms
```

### Timing

The walker prints timing lines every 10 ticks:
```
tick 40/1200 | consult avg=5601ms p95=13508ms | tick=28.4s | 3 walkers active | ETA 548min
```

Real MaleCNS consult latency: ~5-9 seconds per consult (~40-50 seconds per tick with 5-8 candidates). v2 caps the run at MAX_STEPS=400 (the COIN baseline never arrives and would otherwise extend the walk to the step cap) — a full v2 run takes ~2.5-4 hours; v1's 1200-step run took ~8-10 hours.

### Pull artifacts

Data lives on a Docker named volume, not directly on the VM filesystem.

```bash
# Create a tarball on the VM
gcloud compute ssh flywalker --zone=europe-west4-a --command="sudo tar czf /tmp/nata.tar.gz -C /var/lib/docker/volumes/flywalker_data/_data/runs nata"

# Download
mkdir -p local-runs
gcloud compute scp flywalker:/tmp/nata.tar.gz ./local-runs/nata.tar.gz --zone=europe-west4-a

# Extract
cd local-runs && tar xzf nata.tar.gz
```

### Render and view replay

```bash
python walker/replay.py --run-id nata --data-dir local-runs

# Serve locally (OSM tiles block file:// requests)
cd local-runs/runs/nata/replay && python3 -m http.server 8080
# Open http://localhost:8080
```

### Cleanup

```bash
cd infra && terraform destroy
```

Estimated cost: ~$2-3 for an on-demand run (~10 hours), a few cents of disk.

### Spot VM alternative

Spot VMs are ~2-3x cheaper but get preempted frequently (~every 30-60 minutes). The walk resumes from `walk.jsonl` after preemption, but you must manually restart the VM (`gcloud compute instances start flywalker --zone=europe-west4-a`). If using spot, you also need to fix `.env` after each restart (the startup script's heredoc sometimes fails to write route variables). On-demand is recommended for a single uninterrupted run.

## Artifacts

`replay.py` renders `replay/index.html`, a self-contained, dark-cinematic replay page (only external dependency: Leaflet 1.9.4 + OpenStreetMap tiles). It embeds a junction-theater subgraph around the walker trails — with the GREEDY ghost path, per-walker GPS-density halos, and a pulsing goal marker — a what-the-fly-saw cockpit (flycam frame, candidate score bars A–E, DNp20 left/right differential meter, DNpe017 gate, consult latency, reinforcement badge, signed delta pill), a timeline player with key-moment markers (arrivals, closest approaches, dopamine pulses), synced distance-to-goal and cumulative-walked charts, a reinforcement ledger, data-derived honesty chips (e.g. "FLY closer than COIN on 117/400 ticks (29%)"), the two-column what-is-real/what-is-engineered honesty table, and a provenance footer. The page embeds the walk logs and the theater subgraph only; the heavy `route.json` stays alongside for provenance.

**Viewing the replay:** OSM tiles block `file://` requests. Serve the replay directory locally:
```bash
cd local-runs/runs/nata/replay && python3 -m http.server 8080
# Open http://localhost:8080
```

`export_video` is a stub that awaits an ffmpeg compositing step; the replay page is the v1 artifact.

## Credits

- [Stonkfly](https://github.com/nftechie/stonkfly) (MIT): the MaleCNS v1.0 event-driven LIF kernel, visual adapter, decoder, and reinforcement scaffolding. This repo vendors it at commit `78ef3e05ab0fa086032098558d893667068944a0` and imports only the `stonkfly.neural` package.
- [MaleCNS v1.0](https://male-cns.janelia.org/): Google Research + HHMI Janelia, open connectome, source files downloaded under the upstream license.
- [Mapillary](https://www.mapillary.com/): street-level imagery, free token.
- The connectome-driven robotics lineage (worm-sim, the GoPiGo connectome robot) and the 2026 wave of MaleCNS projects (the Doom fly, Stonkfly, flybrain.online) for the idea that a connectome deserves a body.

Nothing here is neuroscience research or investment advice. It is a weekend toy with unusually honest baselines.
