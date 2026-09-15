"""Brain backends behind the oracle HTTP API.

RealFlyBrain wraps Stonkfly's FlyController (FlyWire MaleCNS v1.0 graph,
event-driven LIF kernel, RGB display adapter, engineered reinforcement).
MockFlyBrain has the same interface with deterministic pseudo-scores so the
walker and replay pipeline can run end-to-end on a laptop with no dataset.
"""

import base64
import hashlib
import math
import os
import sys
import threading
import time


def _require(cond, msg):
    if not cond:
        raise RuntimeError(msg)


class RealFlyBrain:
    """Stonkfly MaleCNS v1.0 controller. Requires STONKFLY_HOME + prepared data."""

    def __init__(self, stonkfly_home, data_dir):
        _require(os.path.isdir(stonkfly_home), f"STONKFLY_HOME missing: {stonkfly_home}")
        if stonkfly_home not in sys.path:
            sys.path.insert(0, stonkfly_home)
        os.environ.setdefault("STONKFLY_DATA", data_dir)
        from stonkfly.config import Settings
        from stonkfly.neural.controller import FlyController

        # Settings defaults carry the neural parameters that matter here:
        # neural_ms=500, neural_bin_ms=10, pulse_ms=200, pulse_current=20,
        # decoder_threshold_hz=2, learning=True. Trading fields are inert
        # for flywalker (no broker is ever constructed).
        self.controller = FlyController(Settings())
        self.kind = "real-malecns-v1.0"

    def consult(self, frame, reinforcement):
        return self.controller.observe(frame, reinforcement)

    def checkpoint(self, path):
        self.controller.save(path)

    def restore(self, path):
        self.controller.restore(path)

    def checkpoint_exists(self, path):
        return os.path.exists(path)

    def report(self):
        return self.controller.brain.circuit["report"]

    def memory(self):
        return self.controller.brain.memory()


class MockFlyBrain:
    """Deterministic stand-in: score = f(pixel stats, hash noise).

    Decisions are reproducible given the same frame bytes and consult order,
    so a mock run survives checkpoint-resume with identical behavior.
    Deliberately NOT a model of the fly - it exists to smoke-test plumbing.
    """

    def __init__(self, stonkfly_home=None, data_dir=None):
        self.sim_ms = 0.0
        self.total_spikes = 0
        self.consults = 0
        self.kind = "mock"
        self._memory_w = {}

    def _frame_stats(self, frame):
        import numpy as np

        f = np.asarray(frame, dtype=np.float32)
        h, w = f.shape[:2]
        center = f[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4].mean()
        left = f[:, : w // 3].mean()
        right = f[:, 2 * w // 3 :].mean()
        return float(center), float(left), float(right)

    def consult(self, frame, reinforcement):
        import numpy as np

        center, left, right = self._frame_stats(frame)
        seed = int(hashlib.sha256(np.asarray(frame).tobytes()).hexdigest()[:12], 16)
        rng = hash((seed, self.consults)) % (2**32)
        rng = (rng / (2**32)) * 2 - 1
        # Skew toward "run toward brighter things, slightly"
        right_hz = max(0.0, 1.5 + (right - 128) / 40 + rng)
        left_hz = max(0.0, 1.5 + (left - 128) / 40 + rng * 0.5)
        difference = right_hz - left_hz
        gate = 1 if abs(difference) > 0.4 else 0
        side = (
            "HOLD"
            if not gate or abs(difference) < 2.0
            else "BUY"
            if difference > 0
            else "SELL"
        )
        self.consults += 1
        self.sim_ms += 500.0
        self.total_spikes += int(1000 + (right + left) * 3)
        return {
            "side": side,
            "left_hz": round(left_hz, 3),
            "right_hz": round(right_hz, 3),
            "difference_hz": round(difference, 3),
            "gate_spikes": gate,
            "brain_ms": self.sim_ms,
            "compute_seconds": 0.001,
            "stimulus": reinforcement,
            "reward_spikes": 15 if reinforcement == "reward" else 0,
            "aversive_spikes": 2 if reinforcement == "aversive" else 0,
            "total_spikes": self.total_spikes,
            "approach_hz": round(left_hz + right_hz, 3),
            "mock_stats": {"center": round(center, 1), "left": round(left, 1), "right": round(right, 1)},
            "memory": {"model": "mock", "changed_edges": len(self._memory_w)},
        }

    def checkpoint(self, path):
        base64.b64encode  # no-op; kept for API parity
        self._checkpoint_path = path

    def restore(self, path):
        self._checkpoint_path = path

    def checkpoint_exists(self, path):
        return False

    def report(self):
        return {
            "release": "mock",
            "neurons": 166700,
            "note": "MockFlyBrain: deterministic plumbing test double, not a fly.",
            "validated": False,
        }

    def memory(self):
        return {"model": "mock", "plastic_edges": 7835, "changed_edges": 0}


class BrainService:
    """Single-brain state behind the API: lazy load, restore, checkpoint cadence,
    one queued reinforcement pulse consumed at the next consult."""

    def __init__(self):
        self.kind = os.environ.get("FLY_BRAIN", "real")
        self.stonkfly_home = os.environ.get("STONKFLY_HOME", "/opt/stonkfly")
        self.data_dir = os.environ.get("DATA_DIR", "/data")
        self.checkpoint_path = os.environ.get(
            "CHECKPOINT_PATH", os.path.join(self.data_dir, "brain", "flywalker.npz")
        )
        self.checkpoint_every = int(os.environ.get("CHECKPOINT_EVERY", "25"))
        self.lock = threading.Lock()
        self.brain = None
        self.pending_reinforcement = None
        self.consult_count = 0
        self.last_wall_seconds = None

    def _load(self):
        if self.brain is not None:
            return
        cls = MockFlyBrain if self.kind == "mock" else RealFlyBrain
        self.brain = cls(self.stonkfly_home, self.data_dir)
        if self.brain.checkpoint_exists(self.checkpoint_path):
            self.brain.restore(self.checkpoint_path)

    def maybe_checkpoint(self):
        if self.brain is None:
            return False
        if self.consult_count and self.consult_count % self.checkpoint_every == 0:
            os.makedirs(os.path.dirname(self.checkpoint_path), exist_ok=True)
            self.brain.checkpoint(self.checkpoint_path)
            return True
        return False

    def consult(self, frame_bytes, explicit_reinforcement=None):
        import io

        from PIL import Image

        with self.lock:
            self._load()
            reinforcement = explicit_reinforcement
            if reinforcement is None:
                reinforcement = self.pending_reinforcement or "none"
            self.pending_reinforcement = None
            frame = np_frame(Image.open(io.BytesIO(frame_bytes)))
            obs = self.brain.consult(frame, reinforcement)
            self.consult_count += 1
            self.last_wall_seconds = obs.get("compute_seconds")
            checkpointed = self.maybe_checkpoint()
        return {
            **obs,
            "approach_hz": round(obs["left_hz"] + obs["right_hz"], 3),
            "oracle_consult": self.consult_count,
            "checkpointed": checkpointed,
            "brain_kind": self.kind,
        }

    def queue_reinforcement(self, sign):
        with self.lock:
            if sign not in ("reward", "aversive"):
                raise ValueError("sign must be reward|aversive")
            self.pending_reinforcement = sign
            return {"queued": sign, "consumed_at_next_consult": True}

    def vitals(self):
        with self.lock:
            if self.brain is None:
                return {
                    "brain_kind": self.kind,
                    "loaded": False,
                    "consult_count": 0,
                    "pending_reinforcement": self.pending_reinforcement,
                }
            m = self.brain.memory()
            return {
                "brain_kind": self.kind,
                "loaded": True,
                "consult_count": self.consult_count,
                "last_consult_wall_seconds": self.last_wall_seconds,
                "pending_reinforcement": self.pending_reinforcement,
                "checkpoint_every": self.checkpoint_every,
                "checkpoint_path": self.checkpoint_path,
                "memory": m,
            }

    def force_checkpoint(self):
        with self.lock:
            self._load()
            os.makedirs(os.path.dirname(self.checkpoint_path), exist_ok=True)
            self.brain.checkpoint(self.checkpoint_path)
            return {"checkpointed": True, "path": self.checkpoint_path}

    def report(self):
        self._load()
        return self.brain.report()


def np_frame(image):
    import numpy as np

    return np.asarray(image.convert("RGB"), dtype=np.uint8)
