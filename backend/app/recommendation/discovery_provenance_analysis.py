"""Describe supporter structure and acquisition provenance without reranking."""

from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from statistics import fmean, median
from typing import Literal

from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.continuous_tiebreak_experiment import _groups, _id
from backend.app.recommendation.discovery_ranking_separation import (
    DiscoveryRankingSeparationResult,
    evaluate_discovery_ranking_separation,
)
from backend.app.recommendation.preference_ranking import PreferenceRankedCandidate

SupportStructure = Literal["single_support", "multi_support"]
Provenance = Literal[
    "recurring_only", "one_hit_only", "mixed_provenance", "unknown"
]
SeparationFunction = Callable[..., Awaitable[DiscoveryRankingSeparationResult]]
SPLITS = (8, 9, 10, 11, 12)
TOTAL_SPLIT_COUNT = 13


@dataclass(frozen=True)
class NumericSummary:
    mean: float | None
    median: float | None


@dataclass(frozen=True)
class CategorySummary:
    count: int
    rate: float


@dataclass(frozen=True)
class RankStratum:
    name: str
    count: int
    mean_rank: float | None
    median_rank: float | None


@dataclass(frozen=True)
class PeerComparison:
    group_size: int
    greater_support: int
    equal_support: int
    better_similarity_rank: int
    worse_similarity_rank: int
    recurring_only: int
    one_hit_only: int
    mixed: int
    better_top_play_position: int
    worse_top_play_position: int


@dataclass(frozen=True)
class CandidateProvenance:
    beatmap_id: int
    baseline_rank: int
    target_position: int | None
    is_positive: bool
    support_count: int
    support_structure: SupportStructure
    supporter_user_ids: tuple[int, ...]
    supporter_ranks: tuple[int, ...]
    best_supporter_rank: int
    worst_supporter_rank: int
    mean_supporter_rank: float
    supporter_positions: tuple[int, ...]
    best_supporter_position: int | None
    mean_supporter_position: float | None
    acquisition_groups: tuple[str | None, ...]
    seed_hit_counts: tuple[int | None, ...]
    acquisition_classification: Provenance
    best_position_supporter_rank: int | None
    best_position_supporter_is_best_similarity_supporter: bool | None
    top_play_position_range: int | None
    similarity_rank_range: int
    hydrated_supporter_count: int
    selected_discovery_supporter_count: int
    peer_comparison: PeerComparison | None


@dataclass(frozen=True)
class PopulationSummary:
    count: int
    single_support: CategorySummary
    multi_support: CategorySummary
    recurring_only: CategorySummary
    one_hit_only: CategorySummary
    mixed: CategorySummary
    unknown: CategorySummary
    best_supporter_rank: NumericSummary
    mean_supporter_rank: NumericSummary
    support_count: NumericSummary
    best_supporter_position: NumericSummary
    mean_supporter_position: NumericSummary
    alignment_rate: float | None


@dataclass(frozen=True)
class ProvenanceRunResult:
    target: str
    split_index: int
    candidates: tuple[CandidateProvenance, ...]
    positives: tuple[CandidateProvenance, ...]
    positive_summary: PopulationSummary
    other_summary: PopulationSummary
    support_rank_strata: tuple[RankStratum, ...]
    provenance_rank_strata: tuple[RankStratum, ...]
    supporter_rank_strata: tuple[RankStratum, ...]
    ranks_unchanged: bool
    leaderboard_requests: int
    top_play_requests: int

    @property
    def total_data_requests(self) -> int:
        return self.leaderboard_requests + self.top_play_requests


@dataclass(frozen=True)
class ProvenanceAggregate:
    run_count: int
    candidate_observations: int
    positive_observations: int
    positive_summary: PopulationSummary
    other_summary: PopulationSummary
    targets: tuple[tuple[str, PopulationSummary], ...]


async def evaluate_discovery_provenance(
    username: str,
    *,
    split_index: int,
    separation_function: SeparationFunction = evaluate_discovery_ranking_separation,
    osu_client: OsuApiClient | None = None,
) -> ProvenanceRunResult:
    arguments: dict[str, object] = {
        "split_count": TOTAL_SPLIT_COUNT,
        "split_index": split_index,
    }
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    separation = await separation_function(username, **arguments)
    return analyze_discovery_provenance(username, separation)


def analyze_discovery_provenance(
    target: str, separation: DiscoveryRankingSeparationResult
) -> ProvenanceRunResult:
    baseline = separation.hybrid.preference
    native_ids = {_id(item) for item in separation.top10.preference}
    discovery = tuple(item for item in baseline if _id(item) not in native_ids)
    groups = _groups(discovery)
    positive_positions = {
        item.beatmap_id: item.position
        for item in separation.held_out_impacts
        if item.classification == "newly_recovered_by_expansion"
    }
    hydrated = separation.ranking_result.candidates
    initial = tuple(
        describe_candidate(
            item,
            target_position=positive_positions.get(_id(item)),
            hydrated_supporter_count=sum(
                any(play.beatmap_id == _id(item) for play in player.hydrated_top_plays)
                for player in hydrated
            ),
        )
        for item in discovery
    )
    by_id = {item.beatmap_id: item for item in initial}
    peer_ids = {
        _id(item): tuple(_id(peer) for peer in values)
        for values in groups.values()
        for item in values
    }
    candidates = tuple(
        _with_peers(
            item,
            [by_id[beatmap_id] for beatmap_id in peer_ids[item.beatmap_id]],
        ) if item.is_positive else item
        for item in initial
    )
    positives = tuple(item for item in candidates if item.is_positive)
    others = tuple(item for item in candidates if not item.is_positive)
    return ProvenanceRunResult(
        target=target,
        split_index=separation.split_index,
        candidates=candidates,
        positives=positives,
        positive_summary=summarize_population(positives),
        other_summary=summarize_population(others),
        support_rank_strata=stratify_ranks(
            candidates, lambda item: item.support_structure,
            ("single_support", "multi_support"),
        ),
        provenance_rank_strata=stratify_ranks(
            candidates, lambda item: item.acquisition_classification,
            ("recurring_only", "one_hit_only", "mixed_provenance", "unknown"),
        ),
        supporter_rank_strata=stratify_ranks(
            candidates, lambda item: str(item.best_supporter_rank),
            ("11", "12", "13", "14", "15"),
        ),
        ranks_unchanged=tuple(
            item.baseline_rank for item in candidates
        ) == tuple(
            candidate.preference_rank for candidate in discovery
        ),
        leaderboard_requests=separation.leaderboard_requests,
        top_play_requests=separation.top_play_requests,
    )


def describe_candidate(
    candidate: PreferenceRankedCandidate,
    *,
    target_position: int | None = None,
    hydrated_supporter_count: int | None = None,
) -> CandidateProvenance:
    supports = candidate.preference_evidence.collaborative.candidate_map.supports
    ranks = tuple(support.similar_player_rank for support in supports)
    positions = tuple(
        support.supporter_top_play_position
        for support in supports
        if support.supporter_top_play_position is not None
    )
    best_position = min(positions, default=None)
    best_position_ranks = tuple(
        support.similar_player_rank
        for support in supports
        if support.supporter_top_play_position == best_position
    ) if best_position is not None else ()
    best_rank = min(ranks)
    acquisition = classify_provenance(
        tuple(support.acquisition_group for support in supports)
    )
    return CandidateProvenance(
        beatmap_id=_id(candidate),
        baseline_rank=candidate.preference_rank,
        target_position=target_position,
        is_positive=target_position is not None,
        support_count=len(supports),
        support_structure=classify_support(len(supports)),
        supporter_user_ids=tuple(support.user_id for support in supports),
        supporter_ranks=ranks,
        best_supporter_rank=best_rank,
        worst_supporter_rank=max(ranks),
        mean_supporter_rank=fmean(ranks),
        supporter_positions=positions,
        best_supporter_position=best_position,
        mean_supporter_position=fmean(positions) if positions else None,
        acquisition_groups=tuple(support.acquisition_group for support in supports),
        seed_hit_counts=tuple(support.seed_hit_count for support in supports),
        acquisition_classification=acquisition,
        best_position_supporter_rank=min(best_position_ranks, default=None),
        best_position_supporter_is_best_similarity_supporter=(
            best_rank in best_position_ranks if best_position_ranks else None
        ),
        top_play_position_range=(
            max(positions) - min(positions) if len(positions) > 1 else 0
            if positions else None
        ),
        similarity_rank_range=max(ranks) - min(ranks),
        hydrated_supporter_count=(
            hydrated_supporter_count
            if hydrated_supporter_count is not None
            else len(supports)
        ),
        selected_discovery_supporter_count=len(supports),
        peer_comparison=None,
    )


def classify_support(count: int) -> SupportStructure:
    if count < 1:
        raise ValueError("A discovery candidate must have at least one supporter.")
    return "single_support" if count == 1 else "multi_support"


def classify_provenance(groups: Sequence[str | None]) -> Provenance:
    actual = set(groups)
    if not actual or None in actual or actual - {"recurring", "one_hit"}:
        return "unknown"
    if actual == {"recurring"}:
        return "recurring_only"
    if actual == {"one_hit"}:
        return "one_hit_only"
    return "mixed_provenance"


def summarize_population(
    candidates: Sequence[CandidateProvenance],
) -> PopulationSummary:
    total = len(candidates)
    category = Counter(item.support_structure for item in candidates)
    provenance = Counter(item.acquisition_classification for item in candidates)
    alignments = [
        item.best_position_supporter_is_best_similarity_supporter
        for item in candidates
        if item.best_position_supporter_is_best_similarity_supporter is not None
    ]
    return PopulationSummary(
        count=total,
        single_support=_category(category["single_support"], total),
        multi_support=_category(category["multi_support"], total),
        recurring_only=_category(provenance["recurring_only"], total),
        one_hit_only=_category(provenance["one_hit_only"], total),
        mixed=_category(provenance["mixed_provenance"], total),
        unknown=_category(provenance["unknown"], total),
        best_supporter_rank=_numeric(
            item.best_supporter_rank for item in candidates
        ),
        mean_supporter_rank=_numeric(
            item.mean_supporter_rank for item in candidates
        ),
        support_count=_numeric(item.support_count for item in candidates),
        best_supporter_position=_numeric(
            item.best_supporter_position for item in candidates
        ),
        mean_supporter_position=_numeric(
            item.mean_supporter_position for item in candidates
        ),
        alignment_rate=(
            sum(alignments) / len(alignments) if alignments else None
        ),
    )


def stratify_ranks(
    candidates: Sequence[CandidateProvenance],
    classifier: Callable[[CandidateProvenance], str],
    names: Sequence[str],
) -> tuple[RankStratum, ...]:
    result = []
    for name in names:
        ranks = [
            item.baseline_rank for item in candidates if classifier(item) == name
        ]
        result.append(
            RankStratum(
                name, len(ranks), fmean(ranks) if ranks else None,
                float(median(ranks)) if ranks else None,
            )
        )
    return tuple(result)


def aggregate_results(
    results: Sequence[ProvenanceRunResult],
) -> ProvenanceAggregate:
    candidates = tuple(item for result in results for item in result.candidates)
    positives = tuple(item for item in candidates if item.is_positive)
    others = tuple(item for item in candidates if not item.is_positive)
    targets = tuple(dict.fromkeys(result.target for result in results))
    return ProvenanceAggregate(
        run_count=len(results),
        candidate_observations=len(candidates),
        positive_observations=len(positives),
        positive_summary=summarize_population(positives),
        other_summary=summarize_population(others),
        targets=tuple(
            (
                target,
                summarize_population(
                    tuple(
                        item
                        for result in results
                        if result.target == target
                        for item in result.positives
                    )
                ),
            )
            for target in targets
        ),
    )


def _with_peers(
    positive: CandidateProvenance,
    group: Sequence[CandidateProvenance],
) -> CandidateProvenance:
    peers = [
        item for item in group if item.beatmap_id != positive.beatmap_id
    ]
    comparison = PeerComparison(
        group_size=len(peers) + 1,
        greater_support=sum(item.support_count > positive.support_count for item in peers),
        equal_support=sum(item.support_count == positive.support_count for item in peers),
        better_similarity_rank=sum(
            item.best_supporter_rank < positive.best_supporter_rank for item in peers
        ),
        worse_similarity_rank=sum(
            item.best_supporter_rank > positive.best_supporter_rank for item in peers
        ),
        recurring_only=sum(
            item.acquisition_classification == "recurring_only" for item in peers
        ),
        one_hit_only=sum(
            item.acquisition_classification == "one_hit_only" for item in peers
        ),
        mixed=sum(
            item.acquisition_classification == "mixed_provenance" for item in peers
        ),
        better_top_play_position=sum(
            _position(item.best_supporter_position)
            < _position(positive.best_supporter_position)
            for item in peers
        ),
        worse_top_play_position=sum(
            _position(item.best_supporter_position)
            > _position(positive.best_supporter_position)
            for item in peers
        ),
    )
    return CandidateProvenance(
        **{
            **positive.__dict__,
            "peer_comparison": comparison,
        }
    )
def _category(count: int, total: int) -> CategorySummary:
    return CategorySummary(count, count / total if total else 0.0)


def _numeric(values: Iterable[float | int | None]) -> NumericSummary:
    actual = [float(value) for value in values if value is not None]
    return NumericSummary(
        fmean(actual) if actual else None,
        float(median(actual)) if actual else None,
    )


def _position(value: int | None) -> float:
    return float(value) if value is not None else float("inf")
