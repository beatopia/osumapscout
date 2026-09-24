"""Offline held-out top-play recovery experiment with strict anti-leakage."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import fmean, median
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.analysis.statistics import TopPlayStatisticsInput
from backend.app.candidates.hydration import CandidateHydrationError
from backend.app.candidates.target_maps import (
    TargetMapCandidate,
    TargetMapSeed,
    acquire_target_map_candidate_pool,
    select_evenly_spaced_seeds,
)
from backend.app.database.connection import get_session_factory
from backend.app.database.models import Beatmap, User, UserTopPlay
from backend.app.osu.client import (
    OsuApiClient,
    OsuApiError,
    OsuAuthenticationError,
    OsuCredentials,
    OsuNetworkError,
    OsuTopPlay,
)
from backend.app.recommendation.candidate_map_ranking import (
    CandidateMapEvidence,
    rank_candidate_map_evidence,
)
from backend.app.recommendation.candidate_maps import CandidateMap, extract_candidate_maps
from backend.app.recommendation.preference_evidence import (
    TargetPreferenceProfile,
    annotate_candidate_evidence,
    build_target_preference_profile,
)
from backend.app.recommendation.preference_ranking import (
    PreferenceRankedCandidate,
    rank_candidate_map_preferences,
)
from backend.app.similarity.overlap import (
    SimilarityTargetNotFoundError,
    TargetTopPlaysEmptyError,
)
from backend.app.similarity.ranked_candidates import (
    AcquisitionGroup,
    RankedCandidateExperimentResult,
    RankedCandidatesEmptyError,
    RankedSimilarPlayer,
    rank_similar_players,
    select_candidates_with_budget,
    summarize_ranked_candidates,
)
from backend.app.similarity.target_map_overlap import (
    RawAndSeedExcludedMetrics,
    SeedExcludedTargetEmptyError,
    calculate_raw_and_seed_excluded_overlap,
)


@dataclass(frozen=True)
class TargetPlayEvidence:
    position: int
    beatmap_id: int
    artist: str | None
    title: str | None
    difficulty_name: str | None
    star_rating: float | None
    approach_rate: float | None
    bpm: float | None
    mods: tuple[str, ...]


@dataclass(frozen=True)
class HoldoutSplit:
    training: tuple[TargetPlayEvidence, ...]
    held_out: tuple[TargetPlayEvidence, ...]


@dataclass(frozen=True)
class HeldOutMapRecovery:
    play: TargetPlayEvidence
    support_only_rank: int | None
    evidence_aware_rank: int | None
    preference_aware_rank: int | None
    support_count: int | None
    best_supporting_player_rank: int | None
    total_independent_shared_count: int | None
    mean_independent_shared_count: float | None


AcquisitionFailureStage = Literal[
    "not_present_in_hydrated_candidates",
    "present_only_in_nonselected_candidates",
    "extraction_or_exclusion_failure",
    "recovered",
]


@dataclass(frozen=True)
class HeldOutAcquisitionDiagnostic:
    play: TargetPlayEvidence
    hydrated_supporter_user_ids: tuple[int, ...]
    selected_supporter_user_ids: tuple[int, ...]
    selected_supporter_ranks: tuple[int, ...]
    best_containing_candidate_similarity_rank: int | None
    seen_among_recurring_candidates: bool
    seen_only_among_one_hit_candidates: bool
    candidate_pool_rank: int | None
    preference_aware_rank: int | None
    failure_stage: AcquisitionFailureStage

    @property
    def hydrated_supporter_count(self) -> int:
        return len(self.hydrated_supporter_user_ids)

    @property
    def selected_supporter_count(self) -> int:
        return len(self.selected_supporter_user_ids)


@dataclass(frozen=True)
class AcquisitionDiagnosticSummary:
    held_out_total: int
    recovered: int
    not_present_in_hydrated_candidates: int
    present_only_in_nonselected_candidates: int
    extraction_or_exclusion_failures: int
    seen_among_recurring_candidates: int
    seen_only_among_one_hit_candidates: int


@dataclass(frozen=True)
class AcquisitionDiagnosticAggregate:
    split_count: int
    held_out_total: int
    recovered: int
    not_present_in_hydrated_candidates: int
    present_only_in_nonselected_candidates: int
    extraction_or_exclusion_failures: int
    seen_among_recurring_candidates: int
    seen_only_among_one_hit_candidates: int


@dataclass(frozen=True)
class RecoveredRankSummary:
    minimum: int
    median: float
    mean: float
    maximum: int


@dataclass(frozen=True)
class OrderingRecoverySummary:
    held_out_count: int
    recovered_anywhere: int
    recovery_rate: float
    recovered_at_10: int
    recovered_at_30: int
    recovered_at_50: int
    recovered_at_100: int
    recall_at_10: float
    recall_at_30: float
    recall_at_50: float
    recall_at_100: float
    recovered_rank_summary: RecoveredRankSummary | None


@dataclass(frozen=True)
class SplitPositionDiagnostics:
    split_positions: tuple[tuple[int, ...], ...]
    unique_positions_covered: int
    target_count: int


@dataclass(frozen=True)
class OrderingRecoveryAggregate:
    total_held_out: int
    total_recovered_anywhere: int
    micro_recovery_rate: float
    mean_recall_at_10: float
    mean_recall_at_30: float
    mean_recall_at_50: float
    mean_recall_at_100: float
    mean_split_median_recovered_rank: float | None


@dataclass(frozen=True)
class MultiSplitRecoveryAggregate:
    split_count: int
    support_only: OrderingRecoveryAggregate
    evidence_aware: OrderingRecoveryAggregate
    preference_aware: OrderingRecoveryAggregate


@dataclass(frozen=True)
class HoldoutRecoveryExperimentResult:
    target_user_id: int
    target_username: str
    original_target_play_count: int
    training_play_count: int
    held_out_play_count: int
    selected_seeds: tuple[TargetMapSeed, ...]
    candidates_hydrated: int
    similar_players_used: int
    leaderboard_requests_made: int
    top_play_requests_made: int
    additional_recovery_requests: int
    held_out_maps: tuple[HeldOutMapRecovery, ...]
    support_only_summary: OrderingRecoverySummary
    evidence_aware_summary: OrderingRecoverySummary
    preference_aware_summary: OrderingRecoverySummary
    split_count: int
    split_index: int
    split_diagnostics: SplitPositionDiagnostics
    acquisition_diagnostics: tuple[HeldOutAcquisitionDiagnostic, ...]
    acquisition_summary: AcquisitionDiagnosticSummary
    ranking_result: RankedCandidateExperimentResult | None = None
    target_preference_profile: TargetPreferenceProfile | None = None


@dataclass(frozen=True)
class _TargetIdentity:
    user_id: int
    username: str


def split_target_evidence(
    plays: Sequence[TargetPlayEvidence],
    holdout_count: int,
    split_count: int = 5,
    split_index: int = 0,
) -> HoldoutSplit:
    """Split by evenly spaced indexes shifted circularly by ``split_index``."""
    diagnostics = calculate_split_position_sets(
        len(plays), holdout_count, split_count
    )
    _validate_split_index(split_index, split_count)
    held_indexes = {
        position - 1 for position in diagnostics.split_positions[split_index]
    }
    return HoldoutSplit(
        training=tuple(play for index, play in enumerate(plays) if index not in held_indexes),
        held_out=tuple(play for index, play in enumerate(plays) if index in held_indexes),
    )


def calculate_split_position_sets(
    target_count: int,
    holdout_count: int,
    split_count: int = 5,
) -> SplitPositionDiagnostics:
    """Return pure 1-based position diagnostics for every configured split.

    Split zero uses T0029's evenly spaced indexes. Later splits add their split
    index to every base index and wrap at ``target_count``. Sorting restores
    target order after wrapping and each set remains spread around the range.
    """
    if isinstance(target_count, bool) or not isinstance(target_count, int):
        raise ValueError("Target count must be a positive integer.")
    if target_count < 1:
        raise ValueError("Target count must be a positive integer.")
    _validate_bound(holdout_count, 1, 20, "Holdout count")
    _validate_bound(split_count, 2, 10, "Split count")
    if holdout_count >= target_count:
        raise ValueError("Holdout count must be smaller than target evidence count.")

    if holdout_count == 1:
        base_indexes = (target_count // 2,)
    else:
        last_index = target_count - 1
        base_indexes = tuple(
            index * last_index // (holdout_count - 1)
            for index in range(holdout_count)
        )
    split_positions = tuple(
        tuple(
            sorted(
                ((base_index + current_split) % target_count) + 1
                for base_index in base_indexes
            )
        )
        for current_split in range(split_count)
    )
    if any(len(set(positions)) != holdout_count for positions in split_positions):
        raise ValueError("Holdout selection could not produce unique positions.")
    return SplitPositionDiagnostics(
        split_positions=split_positions,
        unique_positions_covered=len(
            {position for positions in split_positions for position in positions}
        ),
        target_count=target_count,
    )


def summarize_recovery(
    held_out_ids: Sequence[int],
    ordered_candidate_ids: Sequence[int],
) -> OrderingRecoverySummary:
    ranks = {
        beatmap_id: rank
        for rank, beatmap_id in enumerate(ordered_candidate_ids, start=1)
    }
    recovered_ranks = [ranks[value] for value in dict.fromkeys(held_out_ids) if value in ranks]
    held_count = len(tuple(dict.fromkeys(held_out_ids)))

    def recovered_at(limit: int) -> int:
        return sum(rank <= limit for rank in recovered_ranks)

    return OrderingRecoverySummary(
        held_out_count=held_count,
        recovered_anywhere=len(recovered_ranks),
        recovery_rate=len(recovered_ranks) / held_count if held_count else 0.0,
        recovered_at_10=recovered_at(10),
        recovered_at_30=recovered_at(30),
        recovered_at_50=recovered_at(50),
        recovered_at_100=recovered_at(100),
        recall_at_10=recovered_at(10) / held_count if held_count else 0.0,
        recall_at_30=recovered_at(30) / held_count if held_count else 0.0,
        recall_at_50=recovered_at(50) / held_count if held_count else 0.0,
        recall_at_100=recovered_at(100) / held_count if held_count else 0.0,
        recovered_rank_summary=_summarize_ranks(recovered_ranks),
    )


def aggregate_split_summaries(
    summaries: Sequence[
        tuple[
            OrderingRecoverySummary,
            OrderingRecoverySummary,
            OrderingRecoverySummary,
        ]
    ],
) -> MultiSplitRecoveryAggregate:
    """Aggregate explicitly supplied support/evidence/preference summaries."""
    if not summaries:
        raise ValueError("At least one split summary is required.")
    return MultiSplitRecoveryAggregate(
        split_count=len(summaries),
        support_only=_aggregate_orderings(tuple(item[0] for item in summaries)),
        evidence_aware=_aggregate_orderings(tuple(item[1] for item in summaries)),
        preference_aware=_aggregate_orderings(tuple(item[2] for item in summaries)),
    )


def diagnose_held_out_acquisition(
    held_out: Sequence[TargetPlayEvidence],
    hydrated_candidates: Sequence[RankedSimilarPlayer],
    selected_candidates: Sequence[RankedSimilarPlayer],
    candidate_maps: Sequence[CandidateMap],
    preference_ordering: Sequence[PreferenceRankedCandidate],
) -> tuple[HeldOutAcquisitionDiagnostic, ...]:
    """Classify held-out maps using only already-hydrated in-memory evidence."""
    hydrated_rank = {
        candidate.user_id: rank
        for rank, candidate in enumerate(hydrated_candidates, start=1)
    }
    selected_rank = {
        candidate.user_id: rank
        for rank, candidate in enumerate(selected_candidates, start=1)
    }
    pool_ranks = {
        candidate.beatmap_id: rank
        for rank, candidate in enumerate(candidate_maps, start=1)
    }
    preference_ranks = {
        item.preference_evidence.collaborative.candidate_map.beatmap_id:
            item.preference_rank
        for item in preference_ordering
    }
    diagnostics: list[HeldOutAcquisitionDiagnostic] = []
    for play in held_out:
        hydrated_by_id = {
            candidate.user_id: candidate
            for candidate in hydrated_candidates
            if any(
                candidate_play.beatmap_id == play.beatmap_id
                for candidate_play in candidate.hydrated_top_plays
            )
        }
        selected_by_id = {
            candidate.user_id: candidate
            for candidate in selected_candidates
            if candidate.user_id in hydrated_by_id
        }
        hydrated_supporters = tuple(hydrated_by_id.values())
        selected_supporters = tuple(selected_by_id.values())
        pool_rank = pool_ranks.get(play.beatmap_id)
        if not hydrated_supporters:
            stage: AcquisitionFailureStage = "not_present_in_hydrated_candidates"
        elif not selected_supporters:
            stage = "present_only_in_nonselected_candidates"
        elif pool_rank is None:
            stage = "extraction_or_exclusion_failure"
        else:
            stage = "recovered"
        groups = {candidate.acquisition_group for candidate in hydrated_supporters}
        diagnostics.append(
            HeldOutAcquisitionDiagnostic(
                play=play,
                hydrated_supporter_user_ids=tuple(
                    sorted({candidate.user_id for candidate in hydrated_supporters})
                ),
                selected_supporter_user_ids=tuple(
                    sorted({candidate.user_id for candidate in selected_supporters})
                ),
                selected_supporter_ranks=tuple(
                    sorted(
                        selected_rank[candidate.user_id]
                        for candidate in selected_supporters
                    )
                ),
                best_containing_candidate_similarity_rank=(
                    min(hydrated_rank[candidate.user_id] for candidate in hydrated_supporters)
                    if hydrated_supporters
                    else None
                ),
                seen_among_recurring_candidates="recurring" in groups,
                seen_only_among_one_hit_candidates=groups == {"one_hit"},
                candidate_pool_rank=pool_rank,
                preference_aware_rank=preference_ranks.get(play.beatmap_id),
                failure_stage=stage,
            )
        )
    return tuple(diagnostics)


def summarize_acquisition_diagnostics(
    diagnostics: Sequence[HeldOutAcquisitionDiagnostic],
) -> AcquisitionDiagnosticSummary:
    return AcquisitionDiagnosticSummary(
        held_out_total=len(diagnostics),
        recovered=sum(item.failure_stage == "recovered" for item in diagnostics),
        not_present_in_hydrated_candidates=sum(
            item.failure_stage == "not_present_in_hydrated_candidates"
            for item in diagnostics
        ),
        present_only_in_nonselected_candidates=sum(
            item.failure_stage == "present_only_in_nonselected_candidates"
            for item in diagnostics
        ),
        extraction_or_exclusion_failures=sum(
            item.failure_stage == "extraction_or_exclusion_failure"
            for item in diagnostics
        ),
        seen_among_recurring_candidates=sum(
            item.seen_among_recurring_candidates for item in diagnostics
        ),
        seen_only_among_one_hit_candidates=sum(
            item.seen_only_among_one_hit_candidates for item in diagnostics
        ),
    )


def aggregate_acquisition_diagnostics(
    summaries: Sequence[AcquisitionDiagnosticSummary],
) -> AcquisitionDiagnosticAggregate:
    """Aggregate explicitly supplied diagnostic summaries without running splits."""
    if not summaries:
        raise ValueError("At least one acquisition diagnostic summary is required.")
    return AcquisitionDiagnosticAggregate(
        split_count=len(summaries),
        held_out_total=sum(item.held_out_total for item in summaries),
        recovered=sum(item.recovered for item in summaries),
        not_present_in_hydrated_candidates=sum(
            item.not_present_in_hydrated_candidates for item in summaries
        ),
        present_only_in_nonselected_candidates=sum(
            item.present_only_in_nonselected_candidates for item in summaries
        ),
        extraction_or_exclusion_failures=sum(
            item.extraction_or_exclusion_failures for item in summaries
        ),
        seen_among_recurring_candidates=sum(
            item.seen_among_recurring_candidates for item in summaries
        ),
        seen_only_among_one_hit_candidates=sum(
            item.seen_only_among_one_hit_candidates for item in summaries
        ),
    )


async def evaluate_holdout_recovery(
    username: str,
    *,
    top_plays: int = 100,
    holdout_count: int = 10,
    split_count: int = 5,
    split_index: int = 0,
    seed_count: int = 5,
    hydration_budget: int = 25,
    candidate_top_plays: int = 100,
    similar_player_limit: int = 10,
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
    osu_client: OsuApiClient | None = None,
) -> HoldoutRecoveryExperimentResult:
    requested_username = username.strip()
    if not requested_username:
        raise ValueError("Username must not be empty.")
    _validate_bound(top_plays, 2, 100, "Target top-play limit")
    _validate_bound(holdout_count, 1, 20, "Holdout count")
    _validate_bound(split_count, 2, 10, "Split count")
    _validate_split_index(split_index, split_count)
    _validate_bound(seed_count, 1, 10, "Seed count")
    _validate_bound(hydration_budget, 1, 50, "Hydration budget")
    _validate_bound(candidate_top_plays, 1, 100, "Candidate top-play limit")
    _validate_bound(similar_player_limit, 1, 25, "Similar-player limit")
    target, plays = _load_target_evidence(
        requested_username,
        top_plays,
        session_factory or get_session_factory(),
    )
    split_diagnostics = calculate_split_position_sets(
        len(plays), holdout_count, split_count
    )
    split = split_target_evidence(
        plays, holdout_count, split_count, split_index
    )
    training_seeds = select_evenly_spaced_seeds(
        tuple(TargetMapSeed(play.position, play.beatmap_id) for play in split.training),
        seed_count,
    )
    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    pool = await acquire_target_map_candidate_pool(
        target.user_id,
        target.username,
        training_seeds,
        client,
    )
    selection = select_candidates_with_budget(
        pool.candidates, pool.selected_seeds, hydration_budget
    )
    if not selection.ordered:
        raise RankedCandidatesEmptyError(
            "Target-map acquisition returned no candidates to hydrate."
        )
    training_ids = tuple(play.beatmap_id for play in split.training)
    seed_ids = tuple(seed.beatmap_id for seed in training_seeds)
    if not frozenset(training_ids) - frozenset(seed_ids):
        raise SeedExcludedTargetEmptyError(
            "Removing selected seed maps leaves no training maps to compare."
        )
    evaluated: list[RankedSimilarPlayer] = []
    for selected in selection.ordered:
        candidate = selected.candidate
        try:
            candidate_plays = tuple(
                (await client.get_top_plays_by_user_id(
                    candidate.user_id, limit=candidate_top_plays
                ))[:candidate_top_plays]
            )
        except (OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
            raise CandidateHydrationError(
                f"Could not hydrate top plays for candidate user {candidate.user_id}."
            ) from error
        metrics = calculate_raw_and_seed_excluded_overlap(
            training_ids,
            (play.beatmap_id for play in candidate_plays),
            seed_ids,
        )
        evaluated.append(
            _ranked_player(
                candidate,
                selected.acquisition_group,
                candidate_plays,
                metrics,
            )
        )
    ranked = rank_similar_players(evaluated)
    ranking_result = RankedCandidateExperimentResult(
        target_user_id=target.user_id,
        target_username=target.username,
        target_play_count=len(frozenset(training_ids)),
        target_beatmap_ids=training_ids,
        selected_seeds=training_seeds,
        discovered_candidate_count=pool.unique_candidate_count,
        recurring_candidate_count=sum(item.seed_hit_count >= 2 for item in pool.candidates),
        one_hit_candidate_count=sum(item.seed_hit_count == 1 for item in pool.candidates),
        hydration_budget=hydration_budget,
        recurring_selected_count=len(selection.recurring),
        one_hit_selected_count=len(selection.one_hit),
        one_hit_sample_by_seed=(),
        leaderboard_requests_made=pool.leaderboard_requests_made,
        top_play_requests_made=len(evaluated),
        candidates=ranked,
        summary=summarize_ranked_candidates(ranked),
    )
    extraction = extract_candidate_maps(ranking_result, similar_player_limit)
    evidence = rank_candidate_map_evidence(extraction.candidate_maps)
    training_profile = build_target_preference_profile(
        target.user_id,
        target.username,
        tuple(
            TopPlayStatisticsInput(
                performance_points=None,
                accuracy=None,
                star_rating=play.star_rating,
                approach_rate=play.approach_rate,
                bpm=play.bpm,
                mods=play.mods,
            )
            for play in split.training
        ),
    )
    preference = rank_candidate_map_preferences(
        annotate_candidate_evidence(evidence, training_profile)
    )
    support_ids = tuple(item.beatmap_id for item in extraction.candidate_maps)
    evidence_ids = tuple(item.candidate_map.beatmap_id for item in evidence)
    preference_ids = tuple(
        item.preference_evidence.collaborative.candidate_map.beatmap_id
        for item in preference
    )
    recoveries = _build_recoveries(
        split.held_out, extraction.candidate_maps, evidence, preference
    )
    selected_players = ranked[:similar_player_limit]
    acquisition_diagnostics = diagnose_held_out_acquisition(
        split.held_out,
        ranked,
        selected_players,
        extraction.candidate_maps,
        preference,
    )
    return HoldoutRecoveryExperimentResult(
        target_user_id=target.user_id,
        target_username=target.username,
        original_target_play_count=len(plays),
        training_play_count=len(split.training),
        held_out_play_count=len(split.held_out),
        selected_seeds=training_seeds,
        candidates_hydrated=len(evaluated),
        similar_players_used=extraction.similar_players_selected,
        leaderboard_requests_made=pool.leaderboard_requests_made,
        top_play_requests_made=len(evaluated),
        additional_recovery_requests=0,
        held_out_maps=recoveries,
        support_only_summary=summarize_recovery(
            tuple(play.beatmap_id for play in split.held_out), support_ids
        ),
        evidence_aware_summary=summarize_recovery(
            tuple(play.beatmap_id for play in split.held_out), evidence_ids
        ),
        preference_aware_summary=summarize_recovery(
            tuple(play.beatmap_id for play in split.held_out), preference_ids
        ),
        split_count=split_count,
        split_index=split_index,
        split_diagnostics=split_diagnostics,
        acquisition_diagnostics=acquisition_diagnostics,
        acquisition_summary=summarize_acquisition_diagnostics(
            acquisition_diagnostics
        ),
        ranking_result=ranking_result,
        target_preference_profile=training_profile,
    )


def _load_target_evidence(
    username: str,
    limit: int,
    session_factory: Callable[[], Session] | sessionmaker[Session],
) -> tuple[_TargetIdentity, tuple[TargetPlayEvidence, ...]]:
    with session_factory() as session:
        target = session.execute(
            select(User.user_id, User.username).where(
                func.lower(User.username) == username.lower()
            )
        ).one_or_none()
        if target is None:
            raise SimilarityTargetNotFoundError(f"Persisted user '{username}' was not found.")
        rows = session.execute(
            select(
                UserTopPlay.position,
                UserTopPlay.beatmap_id,
                Beatmap.artist,
                Beatmap.title,
                Beatmap.difficulty_name,
                Beatmap.star_rating,
                Beatmap.approach_rate,
                Beatmap.bpm,
                UserTopPlay.mods,
            )
            .join(Beatmap, Beatmap.beatmap_id == UserTopPlay.beatmap_id)
            .where(UserTopPlay.user_id == target.user_id)
            .order_by(UserTopPlay.position).limit(limit)
        ).all()
    if not rows:
        raise TargetTopPlaysEmptyError("The persisted target has no top plays to split.")
    return _TargetIdentity(target.user_id, target.username), tuple(
        TargetPlayEvidence(
            row.position,
            row.beatmap_id,
            row.artist,
            row.title,
            row.difficulty_name,
            row.star_rating,
            row.approach_rate,
            row.bpm,
            tuple(row.mods),
        )
        for row in rows
    )


def _ranked_player(
    candidate: TargetMapCandidate,
    group: AcquisitionGroup,
    plays: tuple[OsuTopPlay, ...],
    metrics: RawAndSeedExcludedMetrics,
) -> RankedSimilarPlayer:
    return RankedSimilarPlayer(
        user_id=candidate.user_id,
        username=candidate.username,
        seed_beatmap_ids=candidate.seed_beatmap_ids,
        acquisition_group=group,
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
        hydrated_top_plays=plays,
    )


def _build_recoveries(
    held_out: Sequence[TargetPlayEvidence],
    support_maps: Sequence[CandidateMap],
    evidence: Sequence[CandidateMapEvidence],
    preference: Sequence[PreferenceRankedCandidate],
) -> tuple[HeldOutMapRecovery, ...]:
    support_ranks = {item.beatmap_id: rank for rank, item in enumerate(support_maps, 1)}
    evidence_by_id = {item.candidate_map.beatmap_id: item for item in evidence}
    preference_ranks = {
        item.preference_evidence.collaborative.candidate_map.beatmap_id:
            item.preference_rank
        for item in preference
    }
    return tuple(
        HeldOutMapRecovery(
            play=play,
            support_only_rank=support_ranks.get(play.beatmap_id),
            evidence_aware_rank=(
                evidence_by_id[play.beatmap_id].evidence_rank
                if play.beatmap_id in evidence_by_id
                else None
            ),
            preference_aware_rank=preference_ranks.get(play.beatmap_id),
            support_count=(
                evidence_by_id[play.beatmap_id].support_count
                if play.beatmap_id in evidence_by_id
                else None
            ),
            best_supporting_player_rank=(
                evidence_by_id[play.beatmap_id].best_supporting_player_rank
                if play.beatmap_id in evidence_by_id
                else None
            ),
            total_independent_shared_count=(
                evidence_by_id[play.beatmap_id].total_independent_shared_count
                if play.beatmap_id in evidence_by_id
                else None
            ),
            mean_independent_shared_count=(
                evidence_by_id[play.beatmap_id].mean_independent_shared_count
                if play.beatmap_id in evidence_by_id
                else None
            ),
        )
        for play in held_out
    )


def _summarize_ranks(ranks: Sequence[int]) -> RecoveredRankSummary | None:
    if not ranks:
        return None
    return RecoveredRankSummary(min(ranks), float(median(ranks)), fmean(ranks), max(ranks))


def _aggregate_orderings(
    summaries: Sequence[OrderingRecoverySummary],
) -> OrderingRecoveryAggregate:
    total_held_out = sum(item.held_out_count for item in summaries)
    total_recovered = sum(item.recovered_anywhere for item in summaries)
    medians = tuple(
        item.recovered_rank_summary.median
        for item in summaries
        if item.recovered_rank_summary is not None
    )
    return OrderingRecoveryAggregate(
        total_held_out=total_held_out,
        total_recovered_anywhere=total_recovered,
        micro_recovery_rate=(
            total_recovered / total_held_out if total_held_out else 0.0
        ),
        mean_recall_at_10=fmean(item.recall_at_10 for item in summaries),
        mean_recall_at_30=fmean(item.recall_at_30 for item in summaries),
        mean_recall_at_50=fmean(item.recall_at_50 for item in summaries),
        mean_recall_at_100=fmean(item.recall_at_100 for item in summaries),
        mean_split_median_recovered_rank=fmean(medians) if medians else None,
    )


def _validate_split_index(split_index: int, split_count: int) -> None:
    if (
        isinstance(split_index, bool)
        or not isinstance(split_index, int)
        or not 0 <= split_index < split_count
    ):
        raise ValueError(
            f"Split index must be an integer from 0 through {split_count - 1}."
        )


def _validate_bound(value: int, minimum: int, maximum: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} through {maximum}.")
