"""Compare recurring target-map candidates with a stratified one-hit baseline."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from statistics import fmean, median

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.candidates.target_maps import (
    TargetMapCandidate,
    TargetMapCandidatePool,
    TargetMapSeed,
    discover_full_target_map_candidate_pool,
)
from backend.app.database.connection import get_session_factory
from backend.app.database.models import User, UserTopPlay
from backend.app.osu.client import (
    OsuApiClient,
    OsuApiError,
    OsuAuthenticationError,
    OsuCredentials,
    OsuNetworkError,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.target_map_overlap import (
    SeedExcludedTargetEmptyError,
    TargetMapCandidateOverlap,
    calculate_raw_and_seed_excluded_overlap,
)

AcquisitionFunction = Callable[..., Awaitable[TargetMapCandidatePool]]


class BaselineCandidatesEmptyError(RuntimeError):
    """Raised when acquisition provides neither recurring nor one-hit users."""


@dataclass(frozen=True)
class OverlapGroupSummary:
    """Descriptive counts for one experimental candidate group."""

    evaluated_count: int
    zero_shared_count: int
    one_or_more_shared_count: int
    two_or_more_shared_count: int
    five_or_more_shared_count: int
    total_shared_count: int
    mean_shared_count: float
    median_shared_count: float
    maximum_shared_count: int


@dataclass(frozen=True)
class OneHitBaselineResult:
    """Separate recurring and stratified one-hit overlap results."""

    target_user_id: int
    target_username: str
    target_play_count: int
    selected_seeds: tuple[TargetMapSeed, ...]
    discovered_candidate_count: int
    recurring_candidate_count: int
    one_hit_candidate_count: int
    one_hit_available_by_seed: tuple[tuple[TargetMapSeed, int], ...]
    one_hit_sample_by_seed: tuple[tuple[TargetMapSeed, int], ...]
    recurring_candidates: tuple[TargetMapCandidateOverlap, ...]
    one_hit_candidates: tuple[TargetMapCandidateOverlap, ...]
    recurring_summary: OverlapGroupSummary
    one_hit_summary: OverlapGroupSummary
    leaderboard_requests_made: int
    top_play_requests_made: int


def select_stratified_one_hit_candidates(
    candidates: Sequence[TargetMapCandidate],
    selected_seeds: Sequence[TargetMapSeed],
    limit: int,
) -> tuple[TargetMapCandidate, ...]:
    """Round-robin one-hit users across seed buckets in seed order."""
    _validate_bound(limit, 1, 20, "One-hit limit")
    buckets: dict[int, list[TargetMapCandidate]] = {
        seed.beatmap_id: [] for seed in selected_seeds
    }
    seen_user_ids: set[int] = set()
    for candidate in candidates:
        if candidate.seed_hit_count != 1 or candidate.user_id in seen_user_ids:
            continue
        seed_id = candidate.seed_beatmap_ids[0]
        bucket = buckets.get(seed_id)
        if bucket is None:
            continue
        bucket.append(candidate)
        seen_user_ids.add(candidate.user_id)

    selected: list[TargetMapCandidate] = []
    bucket_index = 0
    while len(selected) < limit:
        added = False
        for seed in selected_seeds:
            bucket = buckets[seed.beatmap_id]
            if bucket_index < len(bucket):
                selected.append(bucket[bucket_index])
                added = True
                if len(selected) >= limit:
                    break
        if not added:
            break
        bucket_index += 1
    return tuple(selected)


def summarize_independent_overlap(
    candidates: Sequence[TargetMapCandidateOverlap],
) -> OverlapGroupSummary:
    """Summarize seed-excluded shared counts without creating a new score."""
    values = [candidate.seed_excluded_shared_beatmap_count for candidate in candidates]
    if not values:
        return OverlapGroupSummary(0, 0, 0, 0, 0, 0, 0.0, 0.0, 0)
    return OverlapGroupSummary(
        evaluated_count=len(values),
        zero_shared_count=sum(value == 0 for value in values),
        one_or_more_shared_count=sum(value >= 1 for value in values),
        two_or_more_shared_count=sum(value >= 2 for value in values),
        five_or_more_shared_count=sum(value >= 5 for value in values),
        total_shared_count=sum(values),
        mean_shared_count=fmean(values),
        median_shared_count=float(median(values)),
        maximum_shared_count=max(values),
    )


async def evaluate_one_hit_baseline(
    username: str,
    *,
    seed_count: int = 5,
    recurring_limit: int = 20,
    one_hit_limit: int = 15,
    top_plays: int = 100,
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    acquisition_function: AcquisitionFunction = discover_full_target_map_candidate_pool,
    osu_client: OsuApiClient | None = None,
) -> OneHitBaselineResult:
    """Evaluate recurring and stratified one-hit candidates separately."""
    requested_username = username.strip()
    if not requested_username:
        raise ValueError("Username must not be empty.")
    _validate_bound(seed_count, 1, 10, "Seed count")
    _validate_bound(recurring_limit, 1, 20, "Recurring limit")
    _validate_bound(one_hit_limit, 1, 20, "One-hit limit")
    _validate_bound(top_plays, 1, 100, "Top-play limit")

    create_session = session_factory or get_session_factory()
    with create_session() as session:
        target = session.execute(
            select(User.user_id, User.username).where(
                func.lower(User.username) == requested_username.lower()
            )
        ).one_or_none()
        if target is None:
            raise SimilarityTargetNotFoundError(
                f"Persisted user '{requested_username}' was not found."
            )
        rows = session.execute(
            select(UserTopPlay.beatmap_id)
            .where(UserTopPlay.user_id == target.user_id)
            .order_by(UserTopPlay.position)
            .limit(top_plays)
        ).all()

    target_ids = tuple(row.beatmap_id for row in rows[:top_plays])
    if not target_ids:
        raise TargetTopPlaysEmptyError(
            "The persisted target has no top plays to compare."
        )

    acquisition_arguments: dict[str, object] = {"seed_count": seed_count}
    if osu_client is not None:
        acquisition_arguments["osu_client"] = osu_client
    acquisition = await acquisition_function(
        requested_username,
        **acquisition_arguments,
    )
    seed_ids = tuple(seed.beatmap_id for seed in acquisition.selected_seeds)
    if not frozenset(target_ids) - frozenset(seed_ids):
        raise SeedExcludedTargetEmptyError(
            "Removing selected seed maps leaves no target top plays to compare."
        )

    recurring_pool = tuple(
        candidate
        for candidate in acquisition.candidates
        if candidate.seed_hit_count >= 2
    )
    one_hit_pool = tuple(
        candidate
        for candidate in acquisition.candidates
        if candidate.seed_hit_count == 1
    )
    recurring = recurring_pool[:recurring_limit]
    one_hit = select_stratified_one_hit_candidates(
        one_hit_pool,
        acquisition.selected_seeds,
        one_hit_limit,
    )
    if not recurring and not one_hit:
        raise BaselineCandidatesEmptyError(
            "Target-map acquisition returned no recurring or one-hit candidates."
        )

    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    recurring_results = await _hydrate_group(
        recurring, target_ids, seed_ids, top_plays, client
    )
    one_hit_results = await _hydrate_group(
        one_hit, target_ids, seed_ids, top_plays, client
    )

    return OneHitBaselineResult(
        target_user_id=target.user_id,
        target_username=target.username,
        target_play_count=len(frozenset(target_ids)),
        selected_seeds=acquisition.selected_seeds,
        discovered_candidate_count=acquisition.unique_candidate_count,
        recurring_candidate_count=len(recurring_pool),
        one_hit_candidate_count=len(one_hit_pool),
        one_hit_available_by_seed=_count_one_hit_candidates_by_seed(
            one_hit_pool,
            acquisition.selected_seeds,
        ),
        one_hit_sample_by_seed=_count_one_hit_candidates_by_seed(
            one_hit,
            acquisition.selected_seeds,
        ),
        recurring_candidates=recurring_results,
        one_hit_candidates=one_hit_results,
        recurring_summary=summarize_independent_overlap(recurring_results),
        one_hit_summary=summarize_independent_overlap(one_hit_results),
        leaderboard_requests_made=acquisition.leaderboard_requests_made,
        top_play_requests_made=len(recurring_results) + len(one_hit_results),
    )


async def _hydrate_group(
    candidates: Sequence[TargetMapCandidate],
    target_ids: tuple[int, ...],
    seed_ids: tuple[int, ...],
    top_plays: int,
    client: OsuApiClient,
) -> tuple[TargetMapCandidateOverlap, ...]:
    results: list[TargetMapCandidateOverlap] = []
    for candidate in candidates:
        try:
            plays = await client.get_top_plays_by_user_id(
                candidate.user_id,
                limit=top_plays,
            )
        except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
            raise CandidateHydrationError(
                f"Could not hydrate top plays for candidate user {candidate.user_id}."
            ) from error
        metrics = calculate_raw_and_seed_excluded_overlap(
            target_ids,
            (play.beatmap_id for play in plays[:top_plays]),
            seed_ids,
        )
        results.append(
            TargetMapCandidateOverlap(
                user_id=candidate.user_id,
                username=candidate.username,
                seed_beatmap_ids=candidate.seed_beatmap_ids,
                candidate_play_count=metrics.raw.candidate_play_count,
                raw_shared_beatmap_count=metrics.raw.shared_beatmap_count,
                raw_jaccard_similarity=metrics.raw.jaccard_similarity,
                raw_target_coverage=metrics.raw.target_coverage,
                seed_excluded_shared_beatmap_count=(
                    metrics.seed_excluded.shared_beatmap_count
                ),
                seed_excluded_jaccard_similarity=(
                    metrics.seed_excluded.jaccard_similarity
                ),
                seed_excluded_target_coverage=(
                    metrics.seed_excluded.target_coverage
                ),
            )
        )
    return tuple(results)


def _count_one_hit_candidates_by_seed(
    candidates: Sequence[TargetMapCandidate],
    selected_seeds: Sequence[TargetMapSeed],
) -> tuple[tuple[TargetMapSeed, int], ...]:
    counts = {seed.beatmap_id: 0 for seed in selected_seeds}
    for candidate in candidates:
        if candidate.seed_hit_count == 1:
            seed_id = candidate.seed_beatmap_ids[0]
            if seed_id in counts:
                counts[seed_id] += 1
    return tuple((seed, counts[seed.beatmap_id]) for seed in selected_seeds)


def _validate_bound(value: int, minimum: int, maximum: int, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f"{label} must be an integer from {minimum} through {maximum}."
        )
