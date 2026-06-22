"""
crash_engine.py
Core crash simulator with provably fair multiplier generation.

Uses HMAC-SHA256 with server seed, client seed, and nonce to produce
deterministic crash multipliers matching the real Aviator distribution.
"""

import hmac
import hashlib
import struct
import math
import time
import random
from typing import Optional


# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_HOUSE_EDGE = 0.01  # 1 % house edge
MAX_MULTIPLIER = 1_000_000.0

# These seeds are hard-coded for the simulator. In production they would
# be generated once and the server seed would be hashed / revealed on a
# regular schedule for verifiability.
DEFAULT_SERVER_SEED = "7a8f3b2c9d1e4f5a6b7c8d9e0f1a2b3c"
DEFAULT_CLIENT_SEED = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


# ── Provably-fair multiplier ──────────────────────────────────────────────

def generate_multiplier(
    server_seed: str = DEFAULT_SERVER_SEED,
    client_seed: str = DEFAULT_CLIENT_SEED,
    nonce: int = 0,
    house_edge: float = DEFAULT_HOUSE_EDGE,
    max_mult: float = MAX_MULTIPLIER,
) -> float:
    """
    Return a deterministic crash multiplier using the same provably-fair
    algorithm real Aviator / crash games employ.

    Steps
    -----
    1.  HMAC-SHA256(server_seed, client_seed:nonce)
    2.  First 4 bytes → 32-bit unsigned integer
    3.  Map to float *u* in [0, 1)
    4.  If *u* falls in the top ``house_edge`` fraction → instant crash (1.00×).
    5.  Otherwise → ``multiplier = (1 - house_edge) / u``

    The resulting distribution satisfies:

        P(multiplier > x) = (1 - house_edge) / x      for x ≥ 1

    which means:
        • ~50 % of rounds crash before 2×
        • ~90 % before 10×
        • ~98 % before 50×
        • ~99 % before 100×
    """
    message = f"{client_seed}:{nonce}".encode("utf-8")
    digest = hmac.new(
        server_seed.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()

    int_val = struct.unpack(">I", digest[:4])[0]  # 0 … 2³²-1
    u = int_val / (2 ** 32)  # uniform in [0, 1)

    # ── House edge – instant crash at 1.00× ────────────────────────────
    if u >= 1.0 - house_edge:
        return 1.00

    raw = (1.0 - house_edge) / u
    return round(min(raw, max_mult), 2)


# ── Duration simulation ───────────────────────────────────────────────────

def estimate_duration(multiplier: float, speed: float = 0.18) -> float:
    """
    Estimate the round duration (seconds) based on the crash multiplier.

    The multiplier is modelled as growing exponentially:
        multiplier(t) = exp(speed × t)

    Solving for *t*:
        t = log(multiplier) / speed

    A small random jitter (±0.3 s) is added for realism.
    Instant-crash rounds (≤ 1.01×) are very short.
    """
    if multiplier <= 1.01:
        return round(random.uniform(0.1, 0.5), 2)

    base = math.log(max(multiplier, 1.001)) / speed
    jitter = random.uniform(-0.3, 0.3)
    return round(max(base + jitter, 0.3), 2)


# ── Round factory ─────────────────────────────────────────────────────────

def create_round(
    round_id: int,
    nonce: int,
    server_seed: Optional[str] = None,
    client_seed: Optional[str] = None,
    house_edge: float = DEFAULT_HOUSE_EDGE,
    timestamp: Optional[float] = None,
) -> dict:
    """
    Build a complete round dict:

        {
            "round_id":   int,
            "timestamp":  float (unix epoch),
            "multiplier": float,
            "duration":   float (seconds)
        }
    """
    ss = server_seed or DEFAULT_SERVER_SEED
    cs = client_seed or DEFAULT_CLIENT_SEED

    mult = generate_multiplier(ss, cs, nonce, house_edge)
    dur = estimate_duration(mult)
    ts = timestamp if timestamp is not None else time.time()

    return {
        "round_id": round_id,
        "timestamp": round(ts, 3),
        "multiplier": mult,
        "duration": dur,
    }

