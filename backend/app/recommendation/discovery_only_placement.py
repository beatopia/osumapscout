"""Describe placement of candidates introduced only by discovery players 11-15."""

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from statistics import fmean, median
from typing import Literal

from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.discovery_ranking_separation import (
    DiscoveryRankingSeparationResult,
    evaluate_discovery_ranking_separation,
)
from backend.app.recommendation.preference_ranking import PreferenceRankedCandidate

SeparationFunction = Callable[..., Awaitable[DiscoveryRankingSeparationResult]]
RankingKey = Literal[
    "support_count", "attributes_within_iqr_count",
    "total_independent_shared_count", "best_supporting_player_rank", "beatmap_id",
]
RANK_BUCKETS = ("1-30", "31-50", "51-100", "101-200", "201-300", "301+")


@dataclass(frozen=True)
class DiscoveryOnlyCandidate:
    beatmap_id: int
    rank: int
    support_count: int
    total_independent_shared_count: int
    mean_independent_shared_count: float
    best_supporting_player_rank: int
    supporting_player_ranks: tuple[int, ...]
    attributes_within_iqr_count: int
    star_within_iqr: bool | None
    ar_within_iqr: bool | None
    bpm_within_iqr: bool | None
    star_delta: float | None
    ar_delta: float | None
    bpm_delta: float | None


@dataclass(frozen=True)
class TierSummary:
    value: int
    count: int
    median_rank: float
    mean_rank: float


@dataclass(frozen=True)
class DescriptiveSummary:
    count: int
    mean_support: float | None
    median_support: float | None
    mean_independent: float | None
    median_independent: float | None
    mean_iqr_count: float | None
    median_iqr_count: float | None
    mean_star_delta: float | None
    median_star_delta: float | None
    mean_ar_delta: float | None
    median_ar_delta: float | None
    mean_bpm_delta: float | None
    median_bpm_delta: float | None
    mean_rank: float | None
    median_rank: float | None


@dataclass(frozen=True)
class PositiveDiagnostic:
    split_index: int
    target_position: int
    candidate: DiscoveryOnlyCandidate
    rank_percentile: float
    support_percentile: float
    independent_percentile: float
    iqr_count_percentile: float
    above: tuple[DiscoveryOnlyCandidate, ...]
    below: tuple[DiscoveryOnlyCandidate, ...]
    immediate_above_first_difference: RankingKey | None
    highest_same_support: DiscoveryOnlyCandidate | None
    same_support_first_difference: RankingKey | None


@dataclass(frozen=True)
class DiscoveryOnlyPlacementResult:
    split_index: int
    candidates: tuple[DiscoveryOnlyCandidate, ...]
    minimum_rank: int | None
    median_rank: float | None
    mean_rank: float | None
    maximum_rank: int | None
    rank_buckets: tuple[tuple[str, int], ...]
    support_distribution: tuple[TierSummary, ...]
    iqr_distribution: tuple[TierSummary, ...]
    best_supporter_distribution: tuple[TierSummary, ...]
    positives: tuple[PositiveDiagnostic, ...]
    positive_summary: DescriptiveSummary
    other_summary: DescriptiveSummary
    first_difference_counts: tuple[tuple[str, int], ...]
    leaderboard_requests: int
    top_play_requests: int

    @property
    def total_data_requests(self) -> int:
        return self.leaderboard_requests + self.top_play_requests


async def evaluate_discovery_only_placement(
    username: str, *, top_plays: int = 100, holdout_count: int = 10,
    split_count: int = 5, split_index: int = 0, seed_count: int = 5,
    candidate_top_plays: int = 100,
    separation_function: SeparationFunction = evaluate_discovery_ranking_separation,
    osu_client: OsuApiClient | None = None,
) -> DiscoveryOnlyPlacementResult:
    arguments: dict[str, object] = dict(
        top_plays=top_plays, holdout_count=holdout_count, split_count=split_count,
        split_index=split_index, seed_count=seed_count,
        candidate_top_plays=candidate_top_plays,
    )
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    return analyze_discovery_only_placement(
        await separation_function(username, **arguments)
    )


def analyze_discovery_only_placement(
    separation: DiscoveryRankingSeparationResult,
) -> DiscoveryOnlyPlacementResult:
    native_ids = {_id(item) for item in separation.top10.preference}
    candidates = tuple(
        _candidate(item) for item in separation.hybrid.preference if _id(item) not in native_ids
    )
    positive_ids = {
        item.beatmap_id: item for item in separation.held_out_impacts
        if item.classification == "newly_recovered_by_expansion"
    }
    positives = tuple(
        _positive(separation.split_index, item, positive_ids[item.beatmap_id].position, candidates)
        for item in candidates if item.beatmap_id in positive_ids
    )
    positive_set = set(positive_ids)
    ranks = [item.rank for item in candidates]
    differences = Counter(
        item.immediate_above_first_difference for item in positives
        if item.immediate_above_first_difference is not None
    )
    return DiscoveryOnlyPlacementResult(
        split_index=separation.split_index,
        candidates=candidates,
        minimum_rank=min(ranks, default=None),
        median_rank=float(median(ranks)) if ranks else None,
        mean_rank=fmean(ranks) if ranks else None,
        maximum_rank=max(ranks, default=None),
        rank_buckets=tuple((label, sum(_rank_bucket(item.rank) == label for item in candidates)) for label in RANK_BUCKETS),
        support_distribution=_tiers(candidates, "support_count"),
        iqr_distribution=_tiers(candidates, "attributes_within_iqr_count", range(4)),
        best_supporter_distribution=_tiers(candidates, "best_supporting_player_rank", range(11, 16)),
        positives=positives,
        positive_summary=_describe(tuple(item for item in candidates if item.beatmap_id in positive_set)),
        other_summary=_describe(tuple(item for item in candidates if item.beatmap_id not in positive_set)),
        first_difference_counts=tuple(sorted(differences.items())),
        leaderboard_requests=separation.leaderboard_requests,
        top_play_requests=separation.top_play_requests,
    )


def first_distinguishing_key(
    above: DiscoveryOnlyCandidate, below: DiscoveryOnlyCandidate
) -> RankingKey | None:
    fields: tuple[tuple[RankingKey, object, object], ...] = (
        ("support_count", above.support_count, below.support_count),
        ("attributes_within_iqr_count", above.attributes_within_iqr_count, below.attributes_within_iqr_count),
        ("total_independent_shared_count", above.total_independent_shared_count, below.total_independent_shared_count),
        ("best_supporting_player_rank", above.best_supporting_player_rank, below.best_supporting_player_rank),
        ("beatmap_id", above.beatmap_id, below.beatmap_id),
    )
    return next((name for name, left, right in fields if left != right), None)


def neighbors(
    candidates: Sequence[DiscoveryOnlyCandidate], rank: int, limit: int = 5
) -> tuple[tuple[DiscoveryOnlyCandidate, ...], tuple[DiscoveryOnlyCandidate, ...]]:
    index = next(index for index, item in enumerate(candidates) if item.rank == rank)
    return tuple(candidates[max(0, index - limit):index]), tuple(candidates[index + 1:index + 1 + limit])


def _positive(split: int, item: DiscoveryOnlyCandidate, position: int,
              population: Sequence[DiscoveryOnlyCandidate]) -> PositiveDiagnostic:
    above, below = neighbors(population, item.rank)
    immediate = above[-1] if above else None
    same_support = next(
        (candidate for candidate in population if candidate.rank < item.rank and candidate.support_count == item.support_count), None
    )
    return PositiveDiagnostic(
        split, position, item,
        _percentile(item.rank, [x.rank for x in population], lower_is_better=True),
        _percentile(item.support_count, [x.support_count for x in population]),
        _percentile(item.total_independent_shared_count, [x.total_independent_shared_count for x in population]),
        _percentile(item.attributes_within_iqr_count, [x.attributes_within_iqr_count for x in population]),
        above, below,
        first_distinguishing_key(immediate, item) if immediate else None,
        same_support,
        first_distinguishing_key(same_support, item) if same_support else None,
    )


def _candidate(item: PreferenceRankedCandidate) -> DiscoveryOnlyCandidate:
    evidence = item.preference_evidence
    collaborative = evidence.collaborative
    return DiscoveryOnlyCandidate(
        _id(item), item.preference_rank, collaborative.support_count,
        collaborative.total_independent_shared_count,
        collaborative.mean_independent_shared_count,
        collaborative.best_supporting_player_rank,
        tuple(sorted(support.similar_player_rank for support in collaborative.candidate_map.supports)),
        evidence.attributes_within_iqr_count,
        evidence.star_rating.within_target_iqr,
        evidence.approach_rate.within_target_iqr,
        evidence.bpm.within_target_iqr,
        evidence.star_rating.delta_from_target_median,
        evidence.approach_rate.delta_from_target_median,
        evidence.bpm.delta_from_target_median,
    )


def _id(item: PreferenceRankedCandidate) -> int:
    return item.preference_evidence.collaborative.candidate_map.beatmap_id


def _rank_bucket(rank: int) -> str:
    if rank <= 30: return "1-30"
    if rank <= 50: return "31-50"
    if rank <= 100: return "51-100"
    if rank <= 200: return "101-200"
    if rank <= 300: return "201-300"
    return "301+"


def _tiers(candidates: Sequence[DiscoveryOnlyCandidate], field: str,
           values: Sequence[int] | None = None) -> tuple[TierSummary, ...]:
    present = sorted(set(getattr(item, field) for item in candidates)) if values is None else values
    summaries = []
    for value in present:
        ranks = [item.rank for item in candidates if getattr(item, field) == value]
        if ranks:
            summaries.append(TierSummary(value, len(ranks), float(median(ranks)), fmean(ranks)))
    return tuple(summaries)


def _pair(values: Sequence[float | int | None]) -> tuple[float | None, float | None]:
    actual = [float(value) for value in values if value is not None]
    return (fmean(actual), float(median(actual))) if actual else (None, None)


def _describe(candidates: Sequence[DiscoveryOnlyCandidate]) -> DescriptiveSummary:
    support = _pair([x.support_count for x in candidates])
    independent = _pair([x.total_independent_shared_count for x in candidates])
    iqr = _pair([x.attributes_within_iqr_count for x in candidates])
    star = _pair([x.star_delta for x in candidates])
    ar = _pair([x.ar_delta for x in candidates])
    bpm = _pair([x.bpm_delta for x in candidates])
    rank = _pair([x.rank for x in candidates])
    return DescriptiveSummary(len(candidates), *support, *independent, *iqr, *star, *ar, *bpm, *rank)


def _percentile(value: int, population: Sequence[int], *, lower_is_better: bool = False) -> float:
    """Inclusive empirical percentile; 100 means at the favorable end."""
    favorable = sum(item >= value for item in population) if lower_is_better else sum(item <= value for item in population)
    return 100 * favorable / len(population) if population else 0.0
