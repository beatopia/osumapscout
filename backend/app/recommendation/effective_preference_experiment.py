"""Offline T0055 base-versus-effective AR/BPM ranking experiment."""

from collections import Counter
from dataclasses import dataclass, replace
from typing import Literal

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.effective_attributes import effective_attributes
from backend.app.recommendation.holdout_recovery import (
    HeldOutMapRecovery,
    OrderingRecoverySummary,
    TargetPlayEvidence,
    evaluate_holdout_recovery,
    summarize_recovery,
)
from backend.app.recommendation.preference_evidence import (
    CandidatePreferenceEvidence,
    NumericPreferenceSummary,
    TargetPreferenceProfile,
    calculate_numeric_summary,
    compare_numeric_evidence,
)
from backend.app.recommendation.preference_ranking import (
    PreferenceRankedCandidate,
    rank_candidate_map_preferences,
)
from backend.app.recommendation.service import build_hybrid_ranking

Movement = Literal["improved", "worsened", "unchanged"]


@dataclass(frozen=True)
class EffectiveTargetProfile:
    base: TargetPreferenceProfile
    effective_ar: NumericPreferenceSummary | None
    effective_bpm: NumericPreferenceSummary | None
    clock_rates: tuple[tuple[float, int], ...]


@dataclass(frozen=True)
class CandidateClassificationSummary:
    candidate_count: int
    ar_within: int
    bpm_within: int
    both_within: int


@dataclass(frozen=True)
class PlacementTransition:
    beatmap_id: int
    original_position: int
    base_rank: int
    effective_rank: int
    movement: Movement


@dataclass(frozen=True)
class CutoffTransitions:
    cutoff: int
    crossed_in: int
    crossed_out: int


@dataclass(frozen=True)
class ClassificationChanges:
    ar_only: int
    bpm_only: int
    both: int
    unchanged: int


@dataclass(frozen=True)
class EffectivePreferenceResult:
    target_username: str
    split_index: int
    profile: EffectiveTargetProfile
    base_ordering: tuple[PreferenceRankedCandidate, ...]
    effective_ordering: tuple[PreferenceRankedCandidate, ...]
    base_summary: OrderingRecoverySummary
    effective_summary: OrderingRecoverySummary
    base_classification: CandidateClassificationSummary
    effective_classification: CandidateClassificationSummary
    placement_transitions: tuple[PlacementTransition, ...]
    cutoff_transitions: tuple[CutoffTransitions, ...]
    top_overlap: tuple[tuple[int, float], ...]
    classification_changes: ClassificationChanges
    held_out: tuple[TargetPlayEvidence, ...]
    leaderboard_requests: int
    hydration_requests: int
    other_osu_requests: int


def build_effective_target_profile(
    base: TargetPreferenceProfile,
    training: tuple[TargetPlayEvidence, ...],
) -> EffectiveTargetProfile:
    calculated = tuple(
        effective_attributes(play.approach_rate, play.bpm, play.mods)
        for play in training
    )
    rates = Counter(item.clock_rate for item in calculated)
    return EffectiveTargetProfile(
        base,
        calculate_numeric_summary(item.effective_ar for item in calculated),
        calculate_numeric_summary(item.effective_bpm for item in calculated),
        tuple((rate, rates.get(rate, 0)) for rate in (1.0, 1.5, 0.75)),
    )


def build_effective_candidates(
    candidates: tuple[PreferenceRankedCandidate, ...],
    profile: EffectiveTargetProfile,
) -> tuple[CandidatePreferenceEvidence, ...]:
    mods = profile.base.top_exact_mod_combination or ()
    result: list[CandidatePreferenceEvidence] = []
    for ranked in candidates:
        base = ranked.preference_evidence
        values = effective_attributes(
            base.collaborative.candidate_map.approach_rate,
            base.collaborative.candidate_map.bpm,
            mods,
        )
        ar = compare_numeric_evidence(values.effective_ar, profile.effective_ar)
        bpm = compare_numeric_evidence(values.effective_bpm, profile.effective_bpm)
        result.append(replace(
            base,
            approach_rate=ar,
            bpm=bpm,
            attributes_within_iqr_count=sum(
                item.within_target_iqr is True for item in (base.star_rating, ar, bpm)
            ),
            comparable_attribute_count=sum(
                item.within_target_iqr is not None for item in (base.star_rating, ar, bpm)
            ),
        ))
    return tuple(result)


def classification_summary(
    candidates: tuple[CandidatePreferenceEvidence, ...],
) -> CandidateClassificationSummary:
    return CandidateClassificationSummary(
        len(candidates),
        sum(item.approach_rate.within_target_iqr is True for item in candidates),
        sum(item.bpm.within_target_iqr is True for item in candidates),
        sum(
            item.approach_rate.within_target_iqr is True
            and item.bpm.within_target_iqr is True
            for item in candidates
        ),
    )


def compare_orderings(
    held_out: tuple[TargetPlayEvidence, ...],
    base: tuple[PreferenceRankedCandidate, ...],
    effective: tuple[PreferenceRankedCandidate, ...],
) -> tuple[tuple[PlacementTransition, ...], tuple[CutoffTransitions, ...]]:
    base_ranks = _ranks(base)
    effective_ranks = _ranks(effective)
    transitions: list[PlacementTransition] = []
    for play in held_out:
        left = base_ranks.get(play.beatmap_id)
        right = effective_ranks.get(play.beatmap_id)
        if left is None or right is None:
            continue
        movement: Movement = "improved" if right < left else "worsened" if right > left else "unchanged"
        transitions.append(PlacementTransition(play.beatmap_id, play.position, left, right, movement))
    cutoffs = tuple(CutoffTransitions(
        cutoff,
        sum(base_ranks.get(play.beatmap_id, 10**9) > cutoff >= effective_ranks.get(play.beatmap_id, 10**9) for play in held_out),
        sum(base_ranks.get(play.beatmap_id, 10**9) <= cutoff < effective_ranks.get(play.beatmap_id, 10**9) for play in held_out),
    ) for cutoff in (10, 30, 50, 100))
    return tuple(transitions), cutoffs


def top_n_overlap(
    base: tuple[PreferenceRankedCandidate, ...],
    effective: tuple[PreferenceRankedCandidate, ...],
    limit: int,
) -> float:
    left = set(_ids(base[:limit]))
    right = set(_ids(effective[:limit]))
    return len(left & right) / max(1, min(limit, len(left), len(right)))


def classification_changes(
    base: tuple[PreferenceRankedCandidate, ...],
    effective: tuple[PreferenceRankedCandidate, ...],
) -> ClassificationChanges:
    right = {item.preference_evidence.collaborative.candidate_map.beatmap_id: item.preference_evidence for item in effective}
    ar_only = bpm_only = both = unchanged = 0
    for item in base:
        left = item.preference_evidence
        other = right[left.collaborative.candidate_map.beatmap_id]
        ar = left.approach_rate.within_target_iqr != other.approach_rate.within_target_iqr
        bpm = left.bpm.within_target_iqr != other.bpm.within_target_iqr
        if ar and bpm: both += 1
        elif ar: ar_only += 1
        elif bpm: bpm_only += 1
        else: unchanged += 1
    return ClassificationChanges(ar_only, bpm_only, both, unchanged)


async def evaluate_effective_preferences(
    username: str,
    *,
    split_index: int,
    osu_client: OsuApiClient | None = None,
) -> EffectivePreferenceResult:
    recovery = await evaluate_holdout_recovery(
        username, top_plays=100, holdout_count=10, split_count=8,
        split_index=split_index, seed_count=5, hydration_budget=25,
        candidate_top_plays=100, similar_player_limit=15,
        osu_client=osu_client or OsuApiClient(OsuCredentials.from_environment()),
    )
    ranking = recovery.ranking_result
    base_profile = recovery.target_preference_profile
    if ranking is None or base_profile is None:
        raise ValueError("Holdout result lacks ranking or preference evidence.")
    base = build_hybrid_ranking(ranking, base_profile)
    profile = build_effective_target_profile(base_profile, recovery.training_plays)
    effective_evidence = build_effective_candidates(base, profile)
    effective = rank_candidate_map_preferences(effective_evidence)
    held_ids = tuple(play.play.beatmap_id for play in recovery.held_out_maps)
    base_summary = summarize_recovery(held_ids, _ids(base))
    effective_summary = summarize_recovery(held_ids, _ids(effective))
    held_out = tuple(item.play for item in recovery.held_out_maps)
    transitions, cutoffs = compare_orderings(held_out, base, effective)
    return EffectivePreferenceResult(
        recovery.target_username, split_index, profile, base, effective,
        base_summary, effective_summary,
        classification_summary(tuple(item.preference_evidence for item in base)),
        classification_summary(effective_evidence), transitions, cutoffs,
        tuple((limit, top_n_overlap(base, effective, limit)) for limit in (10, 20, 50, 100)),
        classification_changes(base, effective), held_out,
        recovery.leaderboard_requests_made, recovery.top_play_requests_made, 0,
    )


def _ids(items: tuple[PreferenceRankedCandidate, ...]) -> tuple[int, ...]:
    return tuple(item.preference_evidence.collaborative.candidate_map.beatmap_id for item in items)


def _ranks(items: tuple[PreferenceRankedCandidate, ...]) -> dict[int, int]:
    return {beatmap_id: rank for rank, beatmap_id in enumerate(_ids(items), 1)}
