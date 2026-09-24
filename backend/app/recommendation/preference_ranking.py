"""Preference-aware ordering layered on existing collaborative evidence."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from backend.app.osu.client import OsuApiClient
from backend.app.recommendation.preference_evidence import (
    CandidatePreferenceEvidence,
    PreferenceEvidenceExperimentResult,
    TargetPreferenceProfile,
    evaluate_preference_evidence,
)

PreferenceEvidenceFunction = Callable[..., Awaitable[PreferenceEvidenceExperimentResult]]


@dataclass(frozen=True)
class PreferenceRankedCandidate:
    preference_evidence: CandidatePreferenceEvidence
    preference_rank: int

    @property
    def evidence_rank(self) -> int:
        return self.preference_evidence.collaborative.evidence_rank

    @property
    def rank_delta(self) -> int:
        """Positive values mean movement upward from evidence-aware ordering."""
        return self.evidence_rank - self.preference_rank


@dataclass(frozen=True)
class PreferenceRankingExperimentResult:
    evidence: PreferenceEvidenceExperimentResult
    preference_aware_ordering: tuple[PreferenceRankedCandidate, ...]
    show_maps: int
    additional_preference_ranking_requests: int

    @property
    def target_profile(self) -> TargetPreferenceProfile:
        return self.evidence.target_profile


def rank_candidate_map_preferences(
    candidates: Sequence[CandidatePreferenceEvidence],
) -> tuple[PreferenceRankedCandidate, ...]:
    """Rank lexicographically without weights, filtering, mods, or distances."""
    ordered = sorted(
        candidates,
        key=lambda item: (
            -item.collaborative.support_count,
            -item.attributes_within_iqr_count,
            -item.collaborative.total_independent_shared_count,
            item.collaborative.best_supporting_player_rank,
            item.collaborative.candidate_map.beatmap_id,
        ),
    )
    return tuple(
        PreferenceRankedCandidate(candidate, rank)
        for rank, candidate in enumerate(ordered, start=1)
    )


async def evaluate_preference_ranking(
    username: str,
    *,
    seed_count: int = 5,
    hydration_budget: int = 25,
    top_plays: int = 100,
    similar_player_limit: int = 10,
    show_maps: int = 30,
    preference_evidence_function: PreferenceEvidenceFunction = evaluate_preference_evidence,
    osu_client: OsuApiClient | None = None,
) -> PreferenceRankingExperimentResult:
    """Build one existing pool and add a request-free third ordering."""
    arguments: dict[str, object] = {
        "seed_count": seed_count,
        "hydration_budget": hydration_budget,
        "top_plays": top_plays,
        "similar_player_limit": similar_player_limit,
        "show_maps": show_maps,
    }
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    evidence = await preference_evidence_function(username, **arguments)
    return PreferenceRankingExperimentResult(
        evidence=evidence,
        preference_aware_ordering=rank_candidate_map_preferences(
            evidence.candidates
        ),
        show_maps=show_maps,
        additional_preference_ranking_requests=0,
    )
