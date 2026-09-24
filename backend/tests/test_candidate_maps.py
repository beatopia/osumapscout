"""Tests for extracting candidate maps from hydrated similar players."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.app.osu.client import OsuTopPlay
from backend.app.recommendation.candidate_maps import (
    evaluate_candidate_maps,
    extract_candidate_maps,
    validate_show_maps,
)
from backend.app.similarity.ranked_candidates import (
    AcquisitionGroupCounts,
    RankedCandidateExperimentResult,
    RankedCandidateSummary,
    RankedSimilarPlayer,
)


class CandidateMapExtractionTests(unittest.TestCase):
    def test_excludes_target_deduplicates_and_preserves_support(self) -> None:
        player_a = self._player(
            10,
            "A",
            8,
            (
                self._play(2),
                self._play(4, artist="Artist", mods=("HD",), pp=100.0),
                self._play(4, artist="Ignored duplicate", mods=("HR",), pp=90.0),
                self._play(5, title="Five"),
            ),
        )
        player_b = self._player(
            20,
            "B",
            6,
            (
                self._play(3),
                self._play(4, title="Four", difficulty="Hard", pp=80.0),
                self._play(6),
            ),
        )

        result = extract_candidate_maps(
            self._ranking((player_a, player_b), target_ids=(1, 2, 3)),
            2,
        )

        self.assertEqual([item.beatmap_id for item in result.candidate_maps], [4, 5, 6])
        shared = result.candidate_maps[0]
        self.assertEqual(shared.support_count, 2)
        self.assertEqual(shared.supporting_player_ids, (10, 20))
        self.assertEqual(shared.supporting_usernames, ("A", "B"))
        self.assertEqual(shared.best_supporting_player_rank, 1)
        self.assertEqual(shared.artist, "Artist")
        self.assertEqual(shared.title, "Four")
        self.assertEqual(shared.difficulty_name, "Hard")
        self.assertEqual(shared.supports[0].similar_player_rank, 1)
        self.assertEqual(shared.supports[0].independent_shared_count, 8)
        self.assertEqual(shared.supports[0].mods, ("HD",))
        self.assertEqual(shared.supports[0].performance_points, 100.0)
        self.assertNotIn(2, [item.beatmap_id for item in result.candidate_maps])
        self.assertNotIn(3, [item.beatmap_id for item in result.candidate_maps])
        self.assertEqual(
            [item.candidate_map_count for item in result.contributions],
            [2, 2],
        )

    def test_orders_by_support_best_rank_then_beatmap_id(self) -> None:
        players = (
            self._player(1, "One", 10, (self._play(30), self._play(40))),
            self._player(2, "Two", 9, (self._play(20), self._play(30))),
            self._player(3, "Three", 8, (self._play(20), self._play(30))),
            self._player(4, "Four", 7, (self._play(20), self._play(30))),
            self._player(5, "Five", 6, (self._play(20), self._play(40))),
        )

        result = extract_candidate_maps(self._ranking(players), 5)

        self.assertEqual([item.beatmap_id for item in result.candidate_maps], [30, 20, 40])
        self.assertEqual([item.support_count for item in result.candidate_maps], [4, 4, 2])

        tied_players = (
            self._player(1, "One", 1, (self._play(11), self._play(10))),
            self._player(2, "Two", 1, (self._play(11), self._play(10))),
        )
        tied = extract_candidate_maps(self._ranking(tied_players), 2)
        self.assertEqual([item.beatmap_id for item in tied.candidate_maps], [10, 11])

    def test_limit_empty_pool_optional_metadata_and_summary(self) -> None:
        players = (
            self._player(1, "One", 5, (self._play(1), self._play(7))),
            self._player(2, "Two", 4, (self._play(7), self._play(8))),
            self._player(3, "Three", 3, (self._play(7), self._play(8))),
            self._player(4, "Four", 2, (self._play(7),)),
            self._player(5, "Five", 1, (self._play(7),)),
        )

        limited = extract_candidate_maps(self._ranking(players, target_ids=(1,)), 1)
        self.assertEqual([item.beatmap_id for item in limited.candidate_maps], [7])
        self.assertIsNone(limited.candidate_maps[0].artist)

        all_players = extract_candidate_maps(self._ranking(players, target_ids=(1,)), 25)
        summary = all_players.summary
        self.assertEqual(all_players.similar_players_selected, 5)
        self.assertEqual(summary.candidate_map_count, 2)
        self.assertEqual(summary.one_or_more_support_count, 2)
        self.assertEqual(summary.two_or_more_support_count, 2)
        self.assertEqual(summary.three_or_more_support_count, 1)
        self.assertEqual(summary.five_or_more_support_count, 1)
        self.assertEqual(summary.maximum_support_count, 5)

        empty = extract_candidate_maps(
            self._ranking((self._player(1, "One", 1, (self._play(1),)),), target_ids=(1,)),
            1,
        )
        self.assertEqual(empty.candidate_maps, ())
        self.assertEqual(empty.summary.maximum_support_count, 0)

    def test_invalid_limits_are_rejected(self) -> None:
        ranking = self._ranking(())
        for value in (0, 26):
            with self.assertRaises(ValueError):
                extract_candidate_maps(ranking, value)
        for value in (0, 101):
            with self.assertRaises(ValueError):
                validate_show_maps(value)

    @staticmethod
    def _ranking(
        players: tuple[RankedSimilarPlayer, ...],
        *,
        target_ids: tuple[int, ...] = (),
    ) -> RankedCandidateExperimentResult:
        summary = RankedCandidateSummary(
            hydrated_count=len(players),
            zero_shared_count=0,
            one_or_more_shared_count=len(players),
            two_or_more_shared_count=0,
            five_or_more_shared_count=0,
            ten_or_more_shared_count=0,
            maximum_shared_count=0,
            median_shared_count=0.0,
            top_five_groups=AcquisitionGroupCounts(0, 0),
            top_ten_groups=AcquisitionGroupCounts(0, 0),
        )
        return RankedCandidateExperimentResult(
            target_user_id=42,
            target_username="Target",
            target_play_count=len(set(target_ids)),
            target_beatmap_ids=target_ids,
            selected_seeds=(),
            discovered_candidate_count=len(players),
            recurring_candidate_count=0,
            one_hit_candidate_count=len(players),
            hydration_budget=25,
            recurring_selected_count=0,
            one_hit_selected_count=len(players),
            one_hit_sample_by_seed=(),
            leaderboard_requests_made=5,
            top_play_requests_made=25,
            candidates=players,
            summary=summary,
        )

    @staticmethod
    def _player(
        user_id: int,
        username: str,
        shared: int,
        plays: tuple[OsuTopPlay, ...],
    ) -> RankedSimilarPlayer:
        return RankedSimilarPlayer(
            user_id=user_id,
            username=username,
            seed_beatmap_ids=(1,),
            acquisition_group="one_hit",
            candidate_play_count=len(plays),
            raw_shared_beatmap_count=shared,
            raw_jaccard_similarity=0.0,
            raw_target_coverage=0.0,
            seed_excluded_shared_beatmap_count=shared,
            seed_excluded_jaccard_similarity=0.0,
            seed_excluded_target_coverage=0.0,
            hydrated_top_plays=plays,
        )

    @staticmethod
    def _play(
        beatmap_id: int,
        *,
        artist: str | None = None,
        title: str | None = None,
        difficulty: str | None = None,
        mods: tuple[str, ...] = (),
        pp: float | None = None,
    ) -> OsuTopPlay:
        return OsuTopPlay(
            score_id=None,
            beatmap_id=beatmap_id,
            beatmapset_id=None,
            artist=artist,
            title=title,
            difficulty_name=difficulty,
            performance_points=pp,
            accuracy=None,
            grade=None,
            mods=mods,
            max_combo=None,
            played_at=None,
            star_rating=None,
            approach_rate=None,
            bpm=None,
        )


class CandidateMapWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_t0025_once_and_performs_no_extraction_requests(self) -> None:
        ranking = CandidateMapExtractionTests._ranking(
            (
                CandidateMapExtractionTests._player(
                    10,
                    "Ten",
                    5,
                    (CandidateMapExtractionTests._play(4),),
                ),
            ),
            target_ids=(1, 2, 3),
        )
        ranking_function = AsyncMock(return_value=ranking)
        client = SimpleNamespace(
            get_top_plays_by_user_id=AsyncMock(),
            get_beatmap_leaderboard_users=AsyncMock(),
            get_user_by_username=AsyncMock(),
        )

        result = await evaluate_candidate_maps(
            "target",
            seed_count=5,
            hydration_budget=25,
            top_plays=100,
            similar_player_limit=10,
            ranking_function=ranking_function,
            osu_client=client,
        )

        ranking_function.assert_awaited_once_with(
            "target",
            seed_count=5,
            hydration_budget=25,
            top_plays=100,
            osu_client=client,
        )
        self.assertEqual(result.leaderboard_requests_made, 5)
        self.assertEqual(result.top_play_requests_made, 25)
        self.assertEqual(result.additional_extraction_requests, 0)
        client.get_top_plays_by_user_id.assert_not_awaited()
        client.get_beatmap_leaderboard_users.assert_not_awaited()
        client.get_user_by_username.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
