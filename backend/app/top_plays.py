from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from backend.app.osu.client import (
    OsuApiClient,
    OsuApiError,
    OsuAuthenticationError,
    OsuCredentials,
    OsuNetworkError,
    OsuTopPlay,
    OsuUserNotFoundError,
)

router = APIRouter(prefix="/api/users", tags=["top plays"])


class TopPlayResponse(BaseModel):
    score_id: int | None
    beatmap_id: int
    beatmapset_id: int | None
    artist: str | None
    title: str | None
    difficulty_name: str | None
    performance_points: float | None
    accuracy: float | None
    grade: str | None
    mods: list[str]
    max_combo: int | None
    played_at: str | None
    star_rating: float | None
    approach_rate: float | None
    bpm: float | None


class TopPlaysResponse(BaseModel):
    username: str
    count: int
    top_plays: list[TopPlayResponse]


def _to_response(play: OsuTopPlay) -> TopPlayResponse:
    return TopPlayResponse(
        score_id=play.score_id,
        beatmap_id=play.beatmap_id,
        beatmapset_id=play.beatmapset_id,
        artist=play.artist,
        title=play.title,
        difficulty_name=play.difficulty_name,
        performance_points=play.performance_points,
        accuracy=play.accuracy,
        grade=play.grade,
        mods=list(play.mods),
        max_combo=play.max_combo,
        played_at=play.played_at,
        star_rating=play.star_rating,
        approach_rate=play.approach_rate,
        bpm=play.bpm,
    )


@router.get("/{username}/top-plays", response_model=TopPlaysResponse)
async def get_top_plays(
    username: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> TopPlaysResponse:
    """Return normalized osu!standard top plays for a username."""
    try:
        credentials = OsuCredentials.from_environment()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="osu! API credentials are not configured.",
        ) from error

    client = OsuApiClient(credentials)
    try:
        plays = await client.get_top_plays_by_username(username, limit)
    except OsuUserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="osu! user was not found.",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The username or limit is invalid.",
        ) from error
    except OsuAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="osu! API authentication failed.",
        ) from error
    except OsuNetworkError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The osu! API is currently unreachable.",
        ) from error
    except OsuApiError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The osu! API returned an invalid response.",
        ) from error

    response_plays = [_to_response(play) for play in plays]
    return TopPlaysResponse(
        username=username.strip(),
        count=len(response_plays),
        top_plays=response_plays,
    )
