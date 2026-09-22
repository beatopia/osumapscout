"""Bounded, ephemeral top-play hydration for discovered candidates."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from backend.app.candidates.discovery import (
    CandidateDiscoveryResult,
    CandidateUser,
    discover_candidate_users,
)
from backend.app.osu.client import (
    OsuApiClient,
    OsuApiError,
    OsuAuthenticationError,
    OsuCredentials,
    OsuNetworkError,
    OsuTopPlay,
)

DEFAULT_CANDIDATE_POOL_LIMIT = 20
DEFAULT_HYDRATE_LIMIT = 5
DEFAULT_TOP_PLAYS_PER_CANDIDATE = 100
MAX_HYDRATE_LIMIT = 10

DiscoveryFunction = Callable[..., Awaitable[CandidateDiscoveryResult]]


class CandidateHydrationError(RuntimeError):
    """Raised when a candidate's top plays cannot be hydrated completely."""


@dataclass(frozen=True)
class HydratedCandidate:
    """A discovered candidate with ephemeral current top-play evidence."""

    user_id: int
    username: str | None
    sources: tuple[str, ...]
    top_plays: tuple[OsuTopPlay, ...]


@dataclass(frozen=True)
class CandidateHydrationResult:
    """Complete output and request accounting for one hydration run."""

    target_user_id: int
    target_username: str
    requested_candidate_pool: int
    discovered_candidate_count: int
    hydrated_candidates: tuple[HydratedCandidate, ...]
    ranking_requests_made: int
    top_play_requests_made: int


async def hydrate_candidate_top_plays(
    username: str,
    *,
    candidate_pool_limit: int = DEFAULT_CANDIDATE_POOL_LIMIT,
    hydrate_limit: int = DEFAULT_HYDRATE_LIMIT,
    top_plays_per_candidate: int = DEFAULT_TOP_PLAYS_PER_CANDIDATE,
    discovery_function: DiscoveryFunction = discover_candidate_users,
    osu_client: OsuApiClient | None = None,
) -> CandidateHydrationResult:
    """Discover candidates once and hydrate a bounded prefix sequentially."""
    _validate_limit(
        candidate_pool_limit,
        minimum=1,
        maximum=100,
        label="Candidate-pool limit",
    )
    _validate_limit(
        hydrate_limit,
        minimum=1,
        maximum=MAX_HYDRATE_LIMIT,
        label="Hydrate limit",
    )
    _validate_limit(
        top_plays_per_candidate,
        minimum=1,
        maximum=100,
        label="Top-play limit",
    )

    discovery_arguments: dict[str, object] = {"limit": candidate_pool_limit}
    if osu_client is not None:
        discovery_arguments["osu_client"] = osu_client
    discovery = await discovery_function(username, **discovery_arguments)

    selected_candidates = discovery.candidates[:hydrate_limit]
    if not selected_candidates:
        return _build_result(
            discovery,
            candidate_pool_limit,
            hydrated_candidates=(),
        )

    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    hydrated: list[HydratedCandidate] = []
    for candidate in selected_candidates:
        try:
            top_plays = await client.get_top_plays_by_user_id(
                candidate.user_id,
                limit=top_plays_per_candidate,
            )
        except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
            raise CandidateHydrationError(
                f"Could not hydrate top plays for candidate user {candidate.user_id}."
            ) from error

        hydrated.append(_hydrate(candidate, top_plays))

    return _build_result(
        discovery,
        candidate_pool_limit,
        hydrated_candidates=tuple(hydrated),
    )


def _hydrate(
    candidate: CandidateUser,
    top_plays: list[OsuTopPlay],
) -> HydratedCandidate:
    return HydratedCandidate(
        user_id=candidate.user_id,
        username=candidate.username,
        sources=candidate.sources,
        top_plays=tuple(top_plays),
    )


def _build_result(
    discovery: CandidateDiscoveryResult,
    requested_candidate_pool: int,
    *,
    hydrated_candidates: tuple[HydratedCandidate, ...],
) -> CandidateHydrationResult:
    return CandidateHydrationResult(
        target_user_id=discovery.target_user_id,
        target_username=discovery.target_username,
        requested_candidate_pool=requested_candidate_pool,
        discovered_candidate_count=len(discovery.candidates),
        hydrated_candidates=hydrated_candidates,
        ranking_requests_made=discovery.ranking_requests_made,
        top_play_requests_made=len(hydrated_candidates),
    )


def _validate_limit(
    value: int,
    *,
    minimum: int,
    maximum: int,
    label: str,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f"{label} must be an integer from {minimum} through {maximum}."
        )
