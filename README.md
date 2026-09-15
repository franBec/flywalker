# flywalker

A retained simulation of the adult male fruit fly central nervous system, given a body: a walker on real street-level imagery from Lisbon, with one mission, find pastel de nata.

The brain is MaleCNS v1.0, the connectome Google Research and HHMI Janelia released in September 2026: 166,700 neurons, 25.6M directed connections, 124M synaptic contacts. The neural simulation comes from [Stonkfly](https://github.com/nftechie/stonkfly) (MIT), reused unmodified.

Three walkers traverse the same corridor of Mapillary images and log every step:

- **FLY** shows each junction's candidate street images to the simulated connectome, one candidate per consult, through the mapped R1-R6 and R8 photoreceptors. Spike activity in descending neurons is decoded into an approach score and the fly moves to the highest-scoring candidate. Progress toward the goal pulses dopamine into 15 PAM11 cells; regression pulses the 2 aversive PPL101 cells. The KC to MBON candidate memory rule may or may not accumulate anything useful. That is part of the experiment.
- **COIN** has no brain. It picks a uniformly random neighbor each step. This is the noise floor.
- **GREEDY** has no brain. It always steps to the candidate that most reduces straight-line distance to the goal. This is the sense-of-direction ceiling.

FLY's result alone means nothing. Against COIN it says whether the fly beats noise. Against GREEDY it says how far the fly is from intent. Both baselines run in the same walk on the same terrain.

## Honesty, read before sharing any result

Connectome weights are anatomy, not a living fly. The decoder is an engineered mapping, inherited from Stonkfly's DNp20 left/right differential with a DNpe017 spike gate, not a discovery of walk neurons. Dopamine and aversive pulses are engineered reinforcement signals, not modeled pain or pleasure. The visual adapter, light-background 320x180 RGB frames, is an explicit display proxy, not validated retinal physiology. The likely outcome is that FLY statistically resembles COIN, which is a valid and honest result. Stonkfly's own validation docs demonstrated no learned trading skill, and the original Doom-fly authors report mostly no-op play.

## Route v1 (coverage-verified)

Rossio square to Manteigaria in Chiado. The corridor contains a 10,253-node connected component, with 990m crow-flies between start and goal. The values live in `.env` as `ROUTE_BBOX`, `ROUTE_START`, `ROUTE_GOAL`.

Mapillary's `/images` endpoint rejects bboxes larger than about 200m (it 500s past ~1500 results and offers no pagination), so `corridor.py` fetches the corridor as a grid of 200m tiles, filters each page to images within 200m of the start-goal line, and merges results by id. The list endpoint never returns `sequence_id`, so adjacency is purely spatial: each image links to its nearest neighbors within 30m. Dense cities produce disconnected capture islands, so the route keeps only the connected component that contains the goal, then snaps the requested start to the nearest node inside it.

## Layout

```
infra/       Terraform: spot e2-highmem-4 (16GB), STOP on preemption, no inbound ports
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

1. Push this repo to GitHub. The VM clones it on boot (`infra/variables.tf` holds the URL and ref).
2. From the repo root: `cp .env.sample .env` and fill in `MAPILLARY_TOKEN`.
3. `cd infra && terraform init && terraform plan && terraform apply`. The module creates a spot `e2-highmem-4` in `europe-west4` with a 25GB boot disk. `instance_termination_action = STOP` keeps the disk across preemptions and `automatic_restart` brings the VM back. The startup script installs Docker, clones the repo, writes `.env` from instance metadata, and runs compose.
4. First boot: compose runs the `prepare` service, which downloads the MaleCNS dataset and builds the graph into the shared `/data` volume. The oracle compiles Stonkfly's LIF kernel on first brain load and serves on port 8000 inside the Docker network. The walker then runs the walk, resuming from `walk.jsonl` if the VM was preempted.
5. Pull artifacts with the `pull_artifacts_command` terraform output (`gcloud compute scp --recurse flywalker:/data/runs ./local-runs`). The VM exposes no ports, so artifacts leave the VM this way.
6. `python walker/replay.py --run-id <run-id> --data-dir local-runs` regenerates the replay page from the pulled artifacts. Sync it wherever you like.

Estimated cost: about $1-3 for a weekend of spot time, a few cents of disk. `terraform destroy` removes everything.

## Artifacts

`replay.py` writes `replay/index.html`, a self-contained page with animated polylines for all three walkers, the flycam frame per step, distance-to-goal curves, the dopamine ledger, a final score table, and the honesty section. `export_video` is a stub that awaits an ffmpeg compositing step; the replay page is the v1 artifact.

## Credits

- [Stonkfly](https://github.com/nftechie/stonkfly) (MIT): the MaleCNS v1.0 event-driven LIF kernel, visual adapter, decoder, and reinforcement scaffolding. This repo vendors it at commit `78ef3e05ab0fa086032098558d893667068944a0` and imports only the `stonkfly.neural` package.
- [MaleCNS v1.0](https://male-cns.janelia.org/): Google Research + HHMI Janelia, open connectome, source files downloaded under the upstream license.
- [Mapillary](https://www.mapillary.com/): street-level imagery, free token.
- The connectome-driven robotics lineage (worm-sim, the GoPiGo connectome robot) and the 2026 wave of MaleCNS projects (the Doom fly, Stonkfly, flybrain.online) for the idea that a connectome deserves a body.

Nothing here is neuroscience research or investment advice. It is a weekend toy with unusually honest baselines.
