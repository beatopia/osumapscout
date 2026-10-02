"""Regression tests for production gameplay-compatible peer selection."""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from backend.app.osu.client import OsuLeaderboardUser, OsuTopPlay
from backend.app.similarity.gameplay_compatible import (
    evaluate_gameplay_compatible_candidates,
)
from backend.app.similarity.gameplay_mods import (
    compatibility_minimum_share,
    dominant_mod_family,
    is_mod_family_compatible,
    normalize_gameplay_mods,
)
from backend.app.similarity.ranked_candidates import (
    RankedCandidateExperimentResult,
    RankedSimilarPlayer,
    summarize_ranked_candidates,
)


class FakeGameplaySession:
    def __init__(self) -> None:
        self.calls = 0

    def __enter__(self) -> "FakeGameplaySession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: Any) -> Any:
        del statement
        self.calls += 1
        if self.calls == 1:
            target = SimpleNamespace(user_id=42, username="Target")
            return SimpleNamespace(one=lambda: target)
        rows = [
            SimpleNamespace(position=index, beatmap_id=100 + index, mods=("HD", "HR"))
            for index in range(1, 6)
        ]
        return SimpleNamespace(all=lambda: rows)


class GameplayModSemanticsTests(unittest.TestCase):
    def test_hd_only_normalization_and_dominant_family(self) -> None:
        self.assertEqual(normalize_gameplay_mods(("HD", "HR")), ("HR",))
        self.assertEqual(normalize_gameplay_mods(("HD", "HR", "NC")), ("HR", "NC"))
        family, share = dominant_mod_family(
            (("HD", "HR"), ("HR",), ("HD", "HR", "NC"))
        )
        self.assertEqual((family, share), (("HR",), 2 / 3))

    def test_compatibility_is_dominant_and_target_calibrated(self) -> None:
        self.assertEqual(compatibility_minimum_share(0.3), 0.3)
        self.assertEqual(compatibility_minimum_share(0.9), 0.5)
        self.assertTrue(
            is_mod_family_compatible(
                (("HD", "HR"), ("HR",), ("HD", "HR", "NC")),
                ("HR",),
                0.5,
            )
        )
        self.assertFalse(
            is_mod_family_compatible(
                (("HD", "HR", "NC"), ("HD", "HR", "NC"), ("HR",)),
                ("HR",),
                0.3,
            )
        )


class GameplayCompatibleSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_queries_both_hd_variants_and_filters_before_returning(self) -> None:
        client = SimpleNamespace(
            get_beatmap_leaderboard_users=AsyncMock(
                return_value=(OsuLeaderboardUser(7, "Peer"),)
            )
        )
        compatible = self._player(7, (("HD", "HR"),) * 6 + (("HR", "NC"),) * 4)
        incompatible = self._player(8, (("HD", "HR", "NC"),) * 8 + (("HR",),) * 2)

        async def fake_evaluate(username: str, **kwargs: object) -> RankedCandidateExperimentResult:
            acquisition = kwargs["acquisition_function"]
            pool = await acquisition(
                username,
                seed_count=kwargs["seed_count"],
                osu_client=kwargs["osu_client"],
            )
            candidates = (compatible, incompatible)
            return RankedCandidateExperimentResult(
                42, "Target", 5, (101, 102, 103, 104, 105), pool.selected_seeds,
                pool.unique_candidate_count, 1, 0, 25, 1, 0, (),
                pool.leaderboard_requests_made, 2, candidates,
                summarize_ranked_candidates(candidates),
            )

        with (
            patch(
                "backend.app.similarity.gameplay_compatible.get_session_factory",
                return_value=lambda: FakeGameplaySession(),
            ),
            patch(
                "backend.app.similarity.gameplay_compatible.evaluate_ranked_candidates",
                side_effect=fake_evaluate,
            ),
        ):
            result = await evaluate_gameplay_compatible_candidates(
                "Target", osu_client=client
            )

        self.assertEqual([item.user_id for item in result.candidates], [7])
        self.assertEqual(result.summary.hydrated_count, 1)
        self.assertEqual(result.leaderboard_requests_made, 10)
        self.assertEqual(
            {call.kwargs["mods"] for call in client.get_beatmap_leaderboard_users.await_args_list},
            {("HR",), ("HD", "HR")},
        )

    @staticmethod
    def _player(
        user_id: int, mods: tuple[tuple[str, ...], ...]
    ) -> RankedSimilarPlayer:
        plays = tuple(
            OsuTopPlay(None, index, None, None, None, None, 200, None, None, value, None, None, 5, 9, 180)
            for index, value in enumerate(mods, 1)
        )
        return RankedSimilarPlayer(
            user_id, f"Peer{user_id}", (101, 102), "recurring", len(plays),
            5, 0.2, 0.3, 3, 0.1, 0.2, plays,
        )


if __name__ == "__main__":
    unittest.main()
