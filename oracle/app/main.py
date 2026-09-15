"""flywalker oracle HTTP API.

Wraps a single fly brain (real MaleCNS v1.0 via Stonkfly, or mock) behind:

    POST /consult   {png_b64, reinforcement?}  -> observation + approach score
    POST /reward    queue dopamine pulse (15 PAM11), delivered next consult
    POST /punish    queue aversive pulse (2 PPL101), delivered next consult
    GET  /vitals    brain state, consult count, memory stats
    GET  /health    liveness (does not force brain load)
    GET  /report    circuit report (cell identities, counts)
    POST /checkpoint force brain state save

Reinforcement semantics follow Stonkfly: pulses are delivered during an
observation window, so queued signals are consumed by the next consult.
"""

import base64
import os
import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brain import BrainService  # noqa: E402

app = FastAPI(title="flywalker-oracle", version="0.1.0")
service = BrainService()


class ConsultRequest(BaseModel):
    png_b64: str
    reinforcement: str | None = None


@app.post("/consult")
def consult(req: ConsultRequest):
    try:
        frame_bytes = base64.b64decode(req.png_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="png_b64 is not valid base64")
    if req.reinforcement not in (None, "none", "reward", "aversive"):
        raise HTTPException(status_code=400, detail="reinforcement must be none|reward|aversive")
    try:
        return service.consult(frame_bytes, req.reinforcement)
    except Exception as exc:  # kernel build errors, bad frames, OOM signals
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.post("/reward")
def reward():
    return service.queue_reinforcement("reward")


@app.post("/punish")
def punish():
    return service.queue_reinforcement("aversive")


@app.get("/vitals")
def vitals():
    return service.vitals()


@app.get("/health")
def health():
    return {"status": "ok", "brain_kind": service.kind}


@app.get("/report")
def report():
    try:
        return service.report()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/checkpoint")
def checkpoint():
    try:
        return service.force_checkpoint()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
