"""Compare support-only and evidence-aware candidate-map ordering."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.candidate_maps import (
    CandidateMap,
    CandidateMapExperimentResult,
    CandidateMapSupport,
    evaluate_candidate_maps,
)

ExtractionFunction = Callable[..., Awaitable[CandidateMapExperimentResult]]


@dataclass(frozen=True)
class CandidateMapEvidence:
    candidate_map: CandidateMap
    support_count: int
    total_independent_shared_count: int
    mean_independent_shared_count: float
    best_supporting_player_rank: int
    mean_supporting_player_rank: float
    support_only_rank: int
    evidence_rank: int

    @property
    def rank_delta(self) -> int:
        """Positive values mean movement upward from the old ordering."""
        return self.support_only_rank - self.evidence_rank


@dataclass(frozen=True)
class CandidateMapRankingExperimentResult:
    extraction: CandidateMapExperimentResult
    support_only_ordering: tuple[CandidateMap, ...]
    evidence_aware_ordering: tuple[CandidateMapEvidence, ...]
    largest_upward_moves: tuple[CandidateMapEvidence, ...]
    largest_downward_moves: tuple[CandidateMapEvidence, ...]


def rank_candidate_map_evidence(
    candidate_maps: Sequence[CandidateMap],
) -> tuple[CandidateMapEvidence, ...]:
    """Apply an interpretable lexicographic ordering to one existing pool."""
    support_only = tuple(candidate_maps)
    old_ranks = {
        candidate_map.beatmap_id: rank
        for rank, candidate_map in enumerate(support_only, start=1)
    }
    aggregates = [
        _aggregate_candidate_map(candidate_map, old_ranks[candidate_map.beatmap_id])
        for candidate_map in support_only
    ]
    aggregates.sort(
        key=lambda item: (
            -item.support_count,
            -item.total_independent_shared_count,
            -item.mean_independent_shared_count,
            item.best_supporting_player_rank,
            item.candidate_map.beatmap_id,
        )
    )
    return tuple(
        CandidateMapEvidence(
            candidate_map=item.candidate_map,
            support_count=item.support_count,
            total_independent_shared_count=item.total_independent_shared_count,
            mean_independent_shared_count=item.mean_independent_shared_count,
            best_supporting_player_rank=item.best_supporting_player_rank,
            mean_supporting_player_rank=item.mean_supporting_player_rank,
            support_only_rank=item.support_only_rank,
            evidence_rank=new_rank,
        )
        for new_rank, item in enumerate(aggregates, start=1)
    )


async def evaluate_candidate_map_ranking(
    username: str,
    *,
    seed_count: int = 5,
    hydration_budget: int = 25,
    top_plays: int = 100,
    similar_player_limit: int = 10,
    extraction_function: ExtractionFunction = evaluate_candidate_maps,
    osu_client: OsuApiClient | None = None,
) -> CandidateMapRankingExperimentResult:
    """Build the T0026 pool once and compare two orderings without API work."""
    arguments: dict[str, object] = {
        "seed_count": seed_count,
        "hydration_budget": hydration_budget,
        "top_plays": top_plays,
        "similar_player_limit": similar_player_limit,
    }
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    extraction = await extraction_function(username, **arguments)
    evidence_ordering = rank_candidate_map_evidence(extraction.candidate_maps)
    upward = tuple(
        sorted(
            (item for item in evidence_ordering if item.rank_delta > 0),
            key=lambda item: (-item.rank_delta, item.candidate_map.beatmap_id),
        )[:10]
    )
    downward = tuple(
        sorted(
            (item for item in evidence_ordering if item.rank_delta < 0),
            key=lambda item: (item.rank_delta, item.candidate_map.beatmap_id),
        )[:10]
    )
    return CandidateMapRankingExperimentResult(
        extraction=extraction,
        support_only_ordering=extraction.candidate_maps,
        evidence_aware_ordering=evidence_ordering,
        largest_upward_moves=upward,
        largest_downward_moves=downward,
    )


def _aggregate_candidate_map(
    candidate_map: CandidateMap,
    support_only_rank: int,
) -> CandidateMapEvidence:
    supports = _distinct_supports(candidate_map.supports)
    support_count = len(supports)
    total_independent = sum(
        support.independent_shared_count for support in supports
    )
    ranks = [support.similar_player_rank for support in supports]
    return CandidateMapEvidence(
        candidate_map=candidate_map,
        support_count=support_count,
        total_independent_shared_count=total_independent,
        mean_independent_shared_count=(
            total_independent / support_count if support_count else 0.0
        ),
        best_supporting_player_rank=min(ranks, default=0),
        mean_supporting_player_rank=(sum(ranks) / support_count if ranks else 0.0),
        support_only_rank=support_only_rank,
        evidence_rank=0,
    )


def _distinct_supports(
    supports: Sequence[CandidateMapSupport],
) -> tuple[CandidateMapSupport, ...]:
    distinct: list[CandidateMapSupport] = []
    seen_user_ids: set[int] = set()
    for support in supports:
        if support.user_id in seen_user_ids:
            continue
        seen_user_ids.add(support.user_id)
        distinct.append(support)
    return tuple(distinct)
