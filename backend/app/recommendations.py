"""Public HTTP endpoint for on-demand map recommendations."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.osu.client import (
    OsuApiError,
    OsuAuthenticationError,
    OsuNetworkError,
    OsuUserNotFoundError,
)
from backend.app.recommendation.service import RecommendationResult, generate_recommendations
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.ranked_candidates import RankedCandidatesEmptyError
from backend.app.similarity.target_map_overlap import SeedExcludedTargetEmptyError

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


class RecommendationResponse(BaseModel):
    rank: int
    beatmap_id: int
    artist: str | None
    title: str | None
    difficulty_name: str | None
    star_rating: float | None
    approach_rate: float | None
    bpm: float | None
    support_count: int
    best_supporting_player_rank: int
    attributes_within_iqr_count: int
    why_recommended: str


class RecommendationContextResponse(BaseModel):
    discovered_candidate_users: int
    hydrated_candidate_users: int
    ranking_similar_players: int
    discovery_similar_players: int
    candidate_map_count: int
    returned_recommendation_count: int


class RecommendationRequestsResponse(BaseModel):
    profile_requests: int
    target_top_play_requests: int
    leaderboard_requests: int
    candidate_top_play_requests: int


class RecommendationsResponse(BaseModel):
    target_username: str
    target_user_id: int
    recommendations: list[RecommendationResponse]
    context: RecommendationContextResponse
    requests: RecommendationRequestsResponse


def _to_response(result: RecommendationResult) -> RecommendationsResponse:
    return RecommendationsResponse.model_validate(result, from_attributes=True)


@router.get("/{username}", response_model=RecommendationsResponse)
async def get_recommendations(
    username: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RecommendationsResponse:
    """Refresh a target and return the frozen MVP recommendation ranking."""
    try:
        result = await generate_recommendations(username, limit=limit)
    except OsuUserNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "osu! user was not found.") from error
    except (TargetTopPlaysEmptyError, SeedExcludedTargetEmptyError, RankedCandidatesEmptyError) as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "There is insufficient top-play evidence to generate recommendations.",
        ) from error
    except OsuAuthenticationError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "osu! API authentication failed.") from error
    except OsuNetworkError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The osu! API is currently unreachable.") from error
    except (OsuApiError, CandidateHydrationError) as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The osu! API request failed.") from error
    except SimilarityTargetNotFoundError as error:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "The refreshed target could not be loaded.") from error
    except (ValueError, SQLAlchemyError) as error:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Recommendations are currently unavailable.") from error
    return _to_response(result)
