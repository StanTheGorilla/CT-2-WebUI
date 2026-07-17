"""Tier detection for adaptive pipeline depth.

Determines model tier (small/medium/large) from the GGUF filename's
parameter-count marker (e.g. '4B', '70B') or an explicit override.
The tier controls how many pipeline stages run: small models get
inline planning only; large models get full review passes.
"""

import re

TIERS = ("small", "medium", "large")

_PARAM_RE = re.compile(r"(\d+\.?\d*)[Bb]")


def detect_tier(model_filename: str, explicit_tier: str | None = None) -> str:
    """Return the model tier for *model_filename*.

    Resolution order:
      1. *explicit_tier* if provided and valid.
      2. Parsed parameter count from the filename.
      3. ``"small"`` as a safe default.
    """
    # --- explicit override wins ---
    if explicit_tier is not None:
        normed = explicit_tier.strip().lower()
        if normed in TIERS:
            return normed

    # --- parse parameter count from filename ---
    matches = _PARAM_RE.findall(model_filename)
    if matches:
        # Take the last match — the first numeric-B token in names like
        # "Qwen3.5-4B" is the param count, but "NVIDIA-Nemotron-3-Nano-4B"
        # also has a stray "3" that doesn't end with B.  findall already
        # filters to digits+B, so the last one is the most specific.
        params = float(matches[-1])
        if params < 2:
            return "small"   # sub-2B: very limited, inline planning only
        if params <= 14:
            return "medium"  # 2B-14B: Gemma 2B/4B, Qwen3 4B, 8B, 13B
        return "large"       # 14B+: full pipeline with self-review

    # --- fail safe ---
    return "small"
