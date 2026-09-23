"""Budgeted acquisition and overlap ranking for similar-player candidates."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Literal

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
from backend.app.similarity.one_hit_baseline import (
    select_stratified_one_hit_candidates,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.target_map_overlap import (
    SeedExcludedTargetEmptyError,
    calculate_raw_and_seed_excluded_overlap,
)

AcquisitionGroup = Literal["recurring", "one_hit"]
AcquisitionFunction = Callable[..., Awaitable[TargetMapCandidatePool]]


class RankedCandidatesEmptyError(RuntimeError):
    """Raised when acquisition returns no candidates to hydrate."""


@dataclass(frozen=True)
class SelectedCandidate:
    candidate: TargetMapCandidate
    acquisition_group: AcquisitionGroup


@dataclass(frozen=True)
class BudgetedCandidateSelection:
    recurring: tuple[TargetMapCandidate, ...]
    one_hit: tuple[TargetMapCandidate, ...]

    @property
    def ordered(self) -> tuple[SelectedCandidate, ...]:
        return tuple(
            SelectedCandidate(candidate, "recurring")
            for candidate in self.recurring
        ) + tuple(
            SelectedCandidate(candidate, "one_hit")
            for candidate in self.one_hit
        )


@dataclass(frozen=True)
class RankedSimilarPlayer:
    user_id: int
    username: str | None
    seed_beatmap_ids: tuple[int, ...]
    acquisition_group: AcquisitionGroup
    candidate_play_count: int
    raw_shared_beatmap_count: int
    raw_jaccard_similarity: float
    raw_target_coverage: float
    seed_excluded_shared_beatmap_count: int
    seed_excluded_jaccard_similarity: float
    seed_excluded_target_coverage: float

    @property
    def seed_hit_count(self) -> int:
        return len(self.seed_beatmap_ids)


@dataclass(frozen=True)
class AcquisitionGroupCounts:
    recurring: int
    one_hit: int


@dataclass(frozen=True)
class RankedCandidateSummary:
    hydrated_count: int
    zero_shared_count: int
    one_or_more_shared_count: int
    two_or_more_shared_count: int
    five_or_more_shared_count: int
    ten_or_more_shared_count: int
    maximum_shared_count: int
    median_shared_count: float
    top_five_groups: AcquisitionGroupCounts
    top_ten_groups: AcquisitionGroupCounts


@dataclass(frozen=True)
class RankedCandidateExperimentResult:
    target_user_id: int
    target_username: str
    target_play_count: int
    selected_seeds: tuple[TargetMapSeed, ...]
    discovered_candidate_count: int
    recurring_candidate_count: int
    one_hit_candidate_count: int
    hydration_budget: int
    recurring_selected_count: int
    one_hit_selected_count: int
    one_hit_sample_by_seed: tuple[tuple[TargetMapSeed, int], ...]
    leaderboard_requests_made: int
    top_play_requests_made: int
    candidates: tuple[RankedSimilarPlayer, ...]
    summary: RankedCandidateSummary

    @property
    def total_hydrated(self) -> int:
        return len(self.candidates)


def select_candidates_with_budget(
    candidates: Sequence[TargetMapCandidate],
    selected_seeds: Sequence[TargetMapSeed],
    hydration_budget: int,
) -> BudgetedCandidateSelection:
    """Spend the budget on recurring users before a stratified one-hit fill."""
    _validate_bound(hydration_budget, 1, 50, "Hydration budget")
    recurring_list: list[TargetMapCandidate] = []
    seen_user_ids: set[int] = set()
    for candidate in candidates:
        if candidate.seed_hit_count < 2 or candidate.user_id in seen_user_ids:
            continue
        recurring_list.append(candidate)
        seen_user_ids.add(candidate.user_id)
        if len(recurring_list) == hydration_budget:
            break
    recurring = tuple(recurring_list)
    remaining = hydration_budget - len(recurring)
    if remaining == 0:
        return BudgetedCandidateSelection(recurring=recurring, one_hit=())
    one_hit = select_stratified_one_hit_candidates(
        candidates,
        selected_seeds,
        remaining,
    )
    return BudgetedCandidateSelection(recurring=recurring, one_hit=one_hit)


def rank_similar_players(
    candidates: Sequence[RankedSimilarPlayer],
) -> tuple[RankedSimilarPlayer, ...]:
    """Rank only by existing independent overlap metrics and numeric ID."""
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                -candidate.seed_excluded_shared_beatmap_count,
                -candidate.seed_excluded_jaccard_similarity,
                -candidate.seed_excluded_target_coverage,
                candidate.user_id,
            ),
        )
    )


def summarize_ranked_candidates(
    candidates: Sequence[RankedSimilarPlayer],
) -> RankedCandidateSummary:
    values = [candidate.seed_excluded_shared_beatmap_count for candidate in candidates]
    return RankedCandidateSummary(
        hydrated_count=len(candidates),
        zero_shared_count=sum(value == 0 for value in values),
        one_or_more_shared_count=sum(value >= 1 for value in values),
        two_or_more_shared_count=sum(value >= 2 for value in values),
        five_or_more_shared_count=sum(value >= 5 for value in values),
        ten_or_more_shared_count=sum(value >= 10 for value in values),
        maximum_shared_count=max(values, default=0),
        median_shared_count=float(median(values)) if values else 0.0,
        top_five_groups=_count_groups(candidates[:5]),
        top_ten_groups=_count_groups(candidates[:10]),
    )


async def evaluate_ranked_candidates(
    username: str,
    *,
    seed_count: int = 5,
    hydration_budget: int = 25,
    top_plays: int = 100,
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    acquisition_function: AcquisitionFunction = (
        discover_full_target_map_candidate_pool
    ),
    osu_client: OsuApiClient | None = None,
) -> RankedCandidateExperimentResult:
    requested_username = username.strip()
    if not requested_username:
        raise ValueError("Username must not be empty.")
    _validate_bound(seed_count, 1, 10, "Seed count")
    _validate_bound(hydration_budget, 1, 50, "Hydration budget")
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
    pool = await acquisition_function(requested_username, **acquisition_arguments)
    seed_ids = tuple(seed.beatmap_id for seed in pool.selected_seeds)
    if not frozenset(target_ids) - frozenset(seed_ids):
        raise SeedExcludedTargetEmptyError(
            "Removing selected seed maps leaves no target top plays to compare."
        )
    selection = select_candidates_with_budget(
        pool.candidates,
        pool.selected_seeds,
        hydration_budget,
    )
    if not selection.ordered:
        raise RankedCandidatesEmptyError(
            "Target-map acquisition returned no candidates to hydrate."
        )

    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    evaluated: list[RankedSimilarPlayer] = []
    for selected in selection.ordered:
        candidate = selected.candidate
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
        evaluated.append(
            RankedSimilarPlayer(
                user_id=candidate.user_id,
                username=candidate.username,
                seed_beatmap_ids=candidate.seed_beatmap_ids,
                acquisition_group=selected.acquisition_group,
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
                seed_excluded_target_coverage=metrics.seed_excluded.target_coverage,
            )
        )

    ranked = rank_similar_players(evaluated)
    return RankedCandidateExperimentResult(
        target_user_id=target.user_id,
        target_username=target.username,
        target_play_count=len(frozenset(target_ids)),
        selected_seeds=pool.selected_seeds,
        discovered_candidate_count=pool.unique_candidate_count,
        recurring_candidate_count=sum(
            candidate.seed_hit_count >= 2 for candidate in pool.candidates
        ),
        one_hit_candidate_count=sum(
            candidate.seed_hit_count == 1 for candidate in pool.candidates
        ),
        hydration_budget=hydration_budget,
        recurring_selected_count=len(selection.recurring),
        one_hit_selected_count=len(selection.one_hit),
        one_hit_sample_by_seed=_count_one_hit_by_seed(
            selection.one_hit,
            pool.selected_seeds,
        ),
        leaderboard_requests_made=pool.leaderboard_requests_made,
        top_play_requests_made=len(evaluated),
        candidates=ranked,
        summary=summarize_ranked_candidates(ranked),
    )


def _count_one_hit_by_seed(
    candidates: Sequence[TargetMapCandidate],
    seeds: Sequence[TargetMapSeed],
) -> tuple[tuple[TargetMapSeed, int], ...]:
    counts = {seed.beatmap_id: 0 for seed in seeds}
    for candidate in candidates:
        counts[candidate.seed_beatmap_ids[0]] += 1
    return tuple((seed, counts[seed.beatmap_id]) for seed in seeds)


def _count_groups(
    candidates: Sequence[RankedSimilarPlayer],
) -> AcquisitionGroupCounts:
    return AcquisitionGroupCounts(
        recurring=sum(
            candidate.acquisition_group == "recurring" for candidate in candidates
        ),
        one_hit=sum(
            candidate.acquisition_group == "one_hit" for candidate in candidates
        ),
    )


def _validate_bound(value: int, minimum: int, maximum: int, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f"{label} must be an integer from {minimum} through {maximum}."
        )
