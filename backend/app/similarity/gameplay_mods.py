"""Gameplay-mod family semantics shared by similarity selection."""

from collections import Counter
from collections.abc import Sequence


def normalize_gameplay_mods(mods: Sequence[str]) -> tuple[str, ...]:
    """Ignore HD while preserving every gameplay-affecting mod identity."""
    return tuple(mod for mod in mods if mod != "HD")


def mod_family_variants(normalized: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Return exact no-HD and HD leaderboard variants for one family."""
    return (normalized, ("HD",) + normalized)


def dominant_mod_family(
    combinations: Sequence[Sequence[str]],
) -> tuple[tuple[str, ...], float]:
    """Return the deterministic dominant normalized family and its share."""
    counts = Counter(normalize_gameplay_mods(mods) for mods in combinations)
    if not counts:
        return (), 0.0
    family = min(counts, key=lambda value: (-counts[value], value))
    return family, counts[family] / sum(counts.values())


def compatibility_minimum_share(target_share: float) -> float:
    """Require a majority unless the target itself is less specialized."""
    if not 0.0 <= target_share <= 1.0:
        raise ValueError("Target mod-family share must be between zero and one.")
    return min(0.5, target_share)


def is_mod_family_compatible(
    combinations: Sequence[Sequence[str]],
    target_family: tuple[str, ...],
    minimum_share: float,
) -> bool:
    """Require the target family to be dominant and sufficiently represented."""
    family, share = dominant_mod_family(combinations)
    return family == target_family and share >= minimum_share
