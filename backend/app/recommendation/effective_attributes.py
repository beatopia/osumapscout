"""Request-free osu!standard effective AR and BPM calculations."""

from dataclasses import dataclass
from math import isclose
from collections.abc import Sequence


@dataclass(frozen=True)
class EffectiveAttributes:
    effective_ar: float | None
    effective_bpm: float | None
    clock_rate: float


def clock_rate_for_mods(mods: Sequence[str]) -> float:
    """Return the default ranked clock rate while preserving caller mod identity."""
    values = set(mods)
    fast = bool(values & {"DT", "NC"})
    slow = bool(values & {"HT", "DC"})
    if fast and slow:
        raise ValueError("Fast and slow clock-rate mods cannot be combined.")
    return 1.5 if fast else 0.75 if slow else 1.0


def effective_attributes(
    base_ar: float | None,
    base_bpm: float | None,
    mods: Sequence[str],
) -> EffectiveAttributes:
    """Apply difficulty mods, then convert AR through preempt timing and clock rate."""
    values = set(mods)
    if "EZ" in values and "HR" in values:
        raise ValueError("Easy and Hard Rock cannot be combined.")
    rate = clock_rate_for_mods(mods)
    ar = base_ar
    if ar is not None:
        if "EZ" in values:
            ar *= 0.5
        elif "HR" in values:
            ar = min(ar * 1.4, 10.0)
        preempt = _ar_to_preempt(ar) / rate
        ar = _preempt_to_ar(preempt)
    return EffectiveAttributes(
        effective_ar=ar,
        effective_bpm=None if base_bpm is None else base_bpm * rate,
        clock_rate=rate,
    )


def _ar_to_preempt(ar: float) -> float:
    return 1200.0 + 120.0 * (5.0 - ar) if ar < 5.0 else 1200.0 - 150.0 * (ar - 5.0)


def _preempt_to_ar(preempt: float) -> float:
    if preempt > 1200.0 and not isclose(preempt, 1200.0):
        return 5.0 - (preempt - 1200.0) / 120.0
    return 5.0 + (1200.0 - preempt) / 150.0
