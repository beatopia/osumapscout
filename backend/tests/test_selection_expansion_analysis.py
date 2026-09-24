"""Tests for selected-player expansion diagnostics."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.app.osu.client import OsuApiClient, OsuCredentials, OsuTopPlay
from backend.app.recommendation.candidate_map_ranking import CandidateMapEvidence
from backend.app.recommendation.candidate_maps import CandidateMap, CandidateMapSupport
from backend.app.recommendation.holdout_recovery import TargetPlayEvidence
from backend.app.recommendation.preference_evidence import (
    CandidatePreferenceEvidence,
    NumericCandidateEvidence,
    NumericPreferenceSummary,
    TargetPreferenceProfile,
)
from backend.app.recommendation.preference_ranking import PreferenceRankedCandidate
from backend.app.recommendation.selection_expansion_analysis import (
    _held_out_impacts,
    _top_n_stability,
    aggregate_selection_expansions,
    analyze_selection_expansion,
    evaluate_selection_expansion,
)
from backend.app.similarity.ranked_candidates import (
    AcquisitionGroupCounts,
    RankedCandidateExperimentResult,
    RankedCandidateSummary,
    RankedSimilarPlayer,
)


class SelectionExpansionWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_hydrated_pass_serves_both_selected_limits(self) -> None:
        recovery = _recovery()
        recovery_function = AsyncMock(return_value=recovery)
        client = OsuApiClient(OsuCredentials("id", "secret"))

        result = await evaluate_selection_expansion(
            "target", recovery_function=recovery_function, osu_client=client
        )

        recovery_function.assert_awaited_once()
        arguments = recovery_function.await_args.kwargs
        self.assertEqual(arguments["hydration_budget"], 25)
        self.assertEqual(arguments["similar_player_limit"], 15)
        self.assertIs(arguments["osu_client"], client)
        self.assertEqual(result.leaderboard_requests, 5)
        self.assertEqual(result.top_play_requests, 25)
        self.assertEqual(result.total_data_requests, 30)


class SelectionExpansionAnalysisTests(unittest.TestCase):
    def test_pool_superset_and_new_map_provenance(self) -> None:
        result = analyze_selection_expansion(_recovery())

        self.assertEqual(result.top10_only_count, 0)
        self.assertEqual(result.top15_new_count, 2)
        self.assertEqual(
            {item.beatmap_id for item in result.new_candidates}, {104, 105}
        )
        self.assertEqual(dict(result.new_map_origin_counts), {11: 1, 12: 1})

    def test_support_inflation_and_tier_transition(self) -> None:
        result = analyze_selection_expansion(_recovery())
        change = next(item for item in result.existing_map_changes if item.beatmap_id == 101)

        self.assertEqual(change.support_count_top10, 2)
        self.assertEqual(change.support_count_top15, 3)
        self.assertEqual(change.support_delta, 1)
        self.assertEqual(dict(result.support_tier_transitions), {(2, 3): 1})

    def test_intrinsic_preference_evidence_is_stable(self) -> None:
        result = analyze_selection_expansion(_recovery())
        self.assertTrue(
            all(item.intrinsic_preference_unchanged for item in result.existing_map_changes)
        )

    def test_top_n_overlap_is_deterministic(self) -> None:
        old = tuple(_preference(beatmap_id, rank) for rank, beatmap_id in enumerate((1, 2, 3), 1))
        new = tuple(_preference(beatmap_id, rank) for rank, beatmap_id in enumerate((1, 4, 2), 1))

        summary = _top_n_stability(old, new)[0]

        self.assertEqual(summary.overlap_count, 2)
        self.assertEqual(summary.denominator, 3)
        self.assertEqual(summary.entering_count, 1)
        self.assertEqual(summary.leaving_count, 1)

    def test_rank_displacement_reports_absolute_movement(self) -> None:
        result = analyze_selection_expansion(_recovery())
        change = next(item for item in result.existing_map_changes if item.beatmap_id == 101)
        self.assertEqual(abs(change.rank_delta), abs(change.new_preference_rank - change.old_preference_rank))

    def test_held_out_new_recovery_identifies_introducing_player(self) -> None:
        result = analyze_selection_expansion(_recovery())
        impact = next(item for item in result.held_out_impacts if item.play.beatmap_id == 104)

        self.assertEqual(impact.classification, "newly_recovered_by_expansion")
        self.assertEqual(impact.introducing_player_rank, 11)

    def test_held_out_regression_is_worsened_by_fifty(self) -> None:
        play = _target_play(999)
        old = {999: _preference(999, 20)}
        new = {999: _preference(999, 70)}

        impact = _held_out_impacts((play,), old, new)[0]

        self.assertEqual(impact.classification, "already_recovered")
        self.assertEqual(impact.rank_delta, 50)

    def test_cross_split_aggregation_is_pure(self) -> None:
        result = analyze_selection_expansion(_recovery())
        aggregate = aggregate_selection_expansions((result, result))

        self.assertEqual(aggregate.split_count, 2)
        self.assertEqual(aggregate.total_new_candidate_maps, 4)
        self.assertEqual(aggregate.selected_limit_gains, 2)


def _recovery() -> SimpleNamespace:
    players = []
    for rank in range(1, 16):
        plays: tuple[OsuTopPlay, ...] = ()
        if rank == 1:
            plays = (_play(101), _play(102))
        elif rank == 2:
            plays = (_play(101), _play(103))
        elif rank == 11:
            plays = (_play(104),)
        elif rank == 12:
            plays = (_play(105), _play(101))
        players.append(_player(rank, plays))
    ranking = RankedCandidateExperimentResult(
        target_user_id=1,
        target_username="target",
        target_play_count=2,
        target_beatmap_ids=(900, 901),
        selected_seeds=(),
        discovered_candidate_count=15,
        recurring_candidate_count=15,
        one_hit_candidate_count=0,
        hydration_budget=25,
        recurring_selected_count=15,
        one_hit_selected_count=0,
        one_hit_sample_by_seed=(),
        leaderboard_requests_made=5,
        top_play_requests_made=25,
        candidates=tuple(players),
        summary=RankedCandidateSummary(
            15, 0, 15, 0, 0, 0, 1, 1.0,
            AcquisitionGroupCounts(5, 0), AcquisitionGroupCounts(10, 0),
        ),
    )
    profile = TargetPreferenceProfile(
        user_id=1,
        username="target",
        top_play_count=2,
        star_rating=NumericPreferenceSummary(2, 4.0, 4.5, 5.0, 5.5, 6.0, 5.0),
        approach_rate=NumericPreferenceSummary(2, 8.0, 8.25, 8.5, 8.75, 9.0, 8.5),
        bpm=NumericPreferenceSummary(2, 160.0, 170.0, 180.0, 190.0, 200.0, 180.0),
        exact_mod_combinations=(),
        individual_mods=(),
        top_exact_mod_combination=None,
    )
    return SimpleNamespace(
        ranking_result=ranking,
        target_preference_profile=profile,
        held_out_maps=(
            SimpleNamespace(play=_target_play(101)),
            SimpleNamespace(play=_target_play(104)),
            SimpleNamespace(play=_target_play(999)),
        ),
        split_index=0,
        leaderboard_requests_made=5,
        top_play_requests_made=25,
    )


def _player(rank: int, plays: tuple[OsuTopPlay, ...]) -> RankedSimilarPlayer:
    return RankedSimilarPlayer(
        user_id=rank,
        username=f"player-{rank}",
        seed_beatmap_ids=(900,),
        acquisition_group="recurring",
        candidate_play_count=len(plays),
        raw_shared_beatmap_count=1,
        raw_jaccard_similarity=0.1,
        raw_target_coverage=0.1,
        seed_excluded_shared_beatmap_count=1,
        seed_excluded_jaccard_similarity=0.1,
        seed_excluded_target_coverage=0.1,
        hydrated_top_plays=plays,
    )


def _play(beatmap_id: int) -> OsuTopPlay:
    return OsuTopPlay(
        score_id=None,
        beatmap_id=beatmap_id,
        beatmapset_id=None,
        artist=None,
        title=None,
        difficulty_name=None,
        performance_points=None,
        accuracy=None,
        grade=None,
        mods=(),
        max_combo=None,
        played_at=None,
        star_rating=5.0,
        approach_rate=8.5,
        bpm=180.0,
    )


def _target_play(beatmap_id: int) -> TargetPlayEvidence:
    return TargetPlayEvidence(beatmap_id, beatmap_id, None, None, None, 5.0, 8.5, 180.0, ())


def _preference(beatmap_id: int, rank: int) -> PreferenceRankedCandidate:
    support = CandidateMapSupport(1, "player", 1, 1, 0.1, 0.1, (), None)
    candidate = CandidateMap(beatmap_id, None, None, None, 5.0, 8.5, 180.0, (support,))
    collaborative = CandidateMapEvidence(candidate, 1, 1, 1.0, 1, 1.0, rank, rank)
    numeric = NumericCandidateEvidence(5.0, 0.0, True)
    evidence = CandidatePreferenceEvidence(
        collaborative, numeric, numeric, numeric, 3, 3, (), (), None
    )
    return PreferenceRankedCandidate(evidence, rank)


if __name__ == "__main__":
    unittest.main()
