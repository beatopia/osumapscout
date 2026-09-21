"""On-demand analysis derived from persisted application data."""

from backend.app.analysis.statistics import (
    ModAcronymCount,
    ModCombinationCount,
    PlayerNotFoundError,
    PlayerStatistics,
    get_player_statistics,
)

__all__ = [
    "ModAcronymCount",
    "ModCombinationCount",
    "PlayerNotFoundError",
    "PlayerStatistics",
    "get_player_statistics",
]
