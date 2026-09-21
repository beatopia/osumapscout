"""Tests for descriptive statistics derived from persisted top plays."""

import unittest
from types import SimpleNamespace
from typing import Any

from backend.app.analysis.statistics import (
    PlayerNotFoundError,
    TopPlayStatisticsInput,
    calculate_player_statistics,
    get_player_statistics,
)
from backend.app.database.models import User


class FakeStatisticsSession:
    """Small read-only session double for persisted-user lookup tests."""

    def __init__(self, user: User | None, rows: list[Any] | None = None) -> None:
        self.user = user
        self.rows = rows or []
        self.scalar_calls = 0
        self.execute_calls = 0

    def __enter__(self) -> "FakeStatisticsSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def scalar(self, statement: Any) -> User | None:
        self.scalar_calls += 1
        return self.user

    def execute(self, statement: Any) -> SimpleNamespace:
        self.execute_calls += 1
        return SimpleNamespace(all=lambda: self.rows)


class PlayerStatisticsTests(unittest.TestCase):
    def test_normal_statistics_ignore_nulls_and_count_mods(self) -> None:
        result = calculate_player_statistics(
            42,
            "Player",
            [
                self._play(400.0, 0.98, 6.0, 9.5, 180.0, ("HD", "HR")),
                self._play(200.0, None, 4.0, 8.5, None, ("HD",)),
                self._play(None, 0.96, None, None, 220.0, ()),
                self._play(300.0, 1.0, 5.0, 9.0, 200.0, ("HR", "HD")),
            ],
        )

        self.assertEqual(result.top_play_count, 4)
        self.assertEqual(result.average_pp, 300.0)
        self.assertAlmostEqual(result.average_accuracy or 0, 0.98)
        self.assertEqual(result.average_star_rating, 5.0)
        self.assertEqual(result.average_approach_rate, 9.0)
        self.assertEqual(result.average_bpm, 200.0)
        self.assertEqual(
            [(item.mods, item.count) for item in result.exact_mod_combinations],
            [((), 1), (("HD",), 1), (("HD", "HR"), 1), (("HR", "HD"), 1)],
        )
        self.assertEqual(
            [(item.acronym, item.count) for item in result.individual_mods],
            [("HD", 3), ("HR", 2)],
        )

    def test_all_null_metrics_return_none_and_nm_is_not_an_acronym(self) -> None:
        result = calculate_player_statistics(
            42,
            "Player",
            [self._play(None, None, None, None, None, ())],
        )

        self.assertIsNone(result.average_pp)
        self.assertIsNone(result.average_accuracy)
        self.assertIsNone(result.average_star_rating)
        self.assertIsNone(result.average_approach_rate)
        self.assertIsNone(result.average_bpm)
        self.assertEqual(result.exact_mod_combinations[0].mods, ())
        self.assertEqual(result.individual_mods, ())

    def test_zero_top_plays_returns_empty_statistics(self) -> None:
        result = calculate_player_statistics(42, "Player", [])

        self.assertEqual(result.top_play_count, 0)
        self.assertIsNone(result.average_pp)
        self.assertIsNone(result.average_accuracy)
        self.assertEqual(result.exact_mod_combinations, ())
        self.assertEqual(result.individual_mods, ())

    def test_mod_counts_sort_by_count_then_alphabetically(self) -> None:
        result = calculate_player_statistics(
            42,
            "Player",
            [
                self._play(None, None, None, None, None, ("HR",)),
                self._play(None, None, None, None, None, ("HD",)),
                self._play(None, None, None, None, None, ("DT",)),
                self._play(None, None, None, None, None, ("DT",)),
            ],
        )

        self.assertEqual(
            [item.mods for item in result.exact_mod_combinations],
            [("DT",), ("HD",), ("HR",)],
        )
        self.assertEqual(
            [item.acronym for item in result.individual_mods],
            ["DT", "HD", "HR"],
        )

    def test_database_lookup_returns_persisted_rows_without_osu_credentials(self) -> None:
        user = User(user_id=42, username="CanonicalPlayer")
        session = FakeStatisticsSession(
            user,
            [
                SimpleNamespace(
                    performance_points=250.0,
                    accuracy=0.97,
                    star_rating=5.5,
                    approach_rate=9.2,
                    bpm=190.0,
                    mods=["HD"],
                )
            ],
        )

        result = get_player_statistics(
            "canonicalplayer",
            session_factory=lambda: session,
        )

        self.assertEqual(result.user_id, 42)
        self.assertEqual(result.username, "CanonicalPlayer")
        self.assertEqual(result.top_play_count, 1)
        self.assertEqual(session.scalar_calls, 1)
        self.assertEqual(session.execute_calls, 1)

    def test_persisted_user_not_found_is_clear_and_skips_play_query(self) -> None:
        session = FakeStatisticsSession(None)

        with self.assertRaisesRegex(PlayerNotFoundError, "was not found"):
            get_player_statistics(
                "missing-player",
                session_factory=lambda: session,
            )

        self.assertEqual(session.scalar_calls, 1)
        self.assertEqual(session.execute_calls, 0)

    @staticmethod
    def _play(
        performance_points: float | None,
        accuracy: float | None,
        star_rating: float | None,
        approach_rate: float | None,
        bpm: float | None,
        mods: tuple[str, ...],
    ) -> TopPlayStatisticsInput:
        return TopPlayStatisticsInput(
            performance_points=performance_points,
            accuracy=accuracy,
            star_rating=star_rating,
            approach_rate=approach_rate,
            bpm=bpm,
            mods=mods,
        )


if __name__ == "__main__":
    unittest.main()
