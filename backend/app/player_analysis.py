"""HTTP endpoint for statistics derived from persisted player data."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from backend.app.analysis.statistics import (
    PlayerNotFoundError,
    PlayerStatistics,
    get_player_statistics,
)

router = APIRouter(prefix="/api/users", tags=["player analysis"])


class ExactModCombinationResponse(BaseModel):
    mods: list[str]
    count: int


class IndividualModResponse(BaseModel):
    mod: str
    count: int


class PlayerAnalysisResponse(BaseModel):
    user_id: int
    username: str
    top_play_count: int
    average_pp: float | None
    average_accuracy: float | None
    average_star_rating: float | None
    average_approach_rate: float | None
    average_bpm: float | None
    exact_mod_combinations: list[ExactModCombinationResponse]
    individual_mods: list[IndividualModResponse]


def _to_response(statistics: PlayerStatistics) -> PlayerAnalysisResponse:
    """Map the internal statistics result to the public HTTP contract."""
    return PlayerAnalysisResponse(
        user_id=statistics.user_id,
        username=statistics.username,
        top_play_count=statistics.top_play_count,
        average_pp=statistics.average_pp,
        average_accuracy=statistics.average_accuracy,
        average_star_rating=statistics.average_star_rating,
        average_approach_rate=statistics.average_approach_rate,
        average_bpm=statistics.average_bpm,
        exact_mod_combinations=[
            ExactModCombinationResponse(mods=list(item.mods), count=item.count)
            for item in statistics.exact_mod_combinations
        ],
        individual_mods=[
            IndividualModResponse(mod=item.acronym, count=item.count)
            for item in statistics.individual_mods
        ],
    )


@router.get("/{username}/analysis", response_model=PlayerAnalysisResponse)
def get_player_analysis(username: str) -> PlayerAnalysisResponse:
    """Return on-demand statistics for an already persisted user."""
    try:
        statistics = get_player_statistics(username)
    except PlayerNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persisted user was not found.",
        ) from error
    except (ValueError, SQLAlchemyError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Player analysis is currently unavailable.",
        ) from error

    return _to_response(statistics)
