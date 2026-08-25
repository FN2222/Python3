from __future__ import annotations

import random

from .config import ReaderConfig
from .textutil import reading_units


def jittered(rng: random.Random, base_ms: float, jitter: float) -> int:
    if base_ms <= 0:
        return 0
    span = max(0.0, jitter)
    factor = rng.uniform(1.0 - span, 1.0 + span)
    return max(1, int(round(base_ms * factor)))


def reading_time_ms(text: str, config: ReaderConfig, rng: random.Random, viewport_index: int) -> int:
    cjk, words = reading_units(text)
    minutes = 0.0
    if config.cjk_chars_per_minute > 0:
        minutes += cjk / config.cjk_chars_per_minute
    if config.words_per_minute > 0:
        minutes += words / config.words_per_minute
    # Empty / mostly-punctuation screens still get a glance.
    base_ms = max(420.0, minutes * 60_000.0)
    fatigue = 1.0 + max(0, viewport_index) * config.fatigue_per_viewport
    return jittered(rng, base_ms * fatigue, config.timing_jitter)


def uniform_ms(rng: random.Random, lo: int, hi: int) -> int:
    if hi < lo:
        lo, hi = hi, lo
    return rng.randint(lo, hi)
