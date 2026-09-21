"""HTTP tests for the persisted player-analysis endpoint."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app.analysis.statistics import (
    ModAcronymCount,
    ModCombinationCount,
    PlayerNotFoundError,
    PlayerStatistics,
)
from backend.app.main import app


class PlayerAnalysisEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_success_serializes_explicit_response_without_osu_call(self) -> None:
        statistics = PlayerStatistics(
            user_id=42,
            username="CanonicalPlayer",
            top_play_count=3,
            average_pp=321.5,
            average_accuracy=0.9842,
            average_star_rating=6.4,
            average_approach_rate=None,
            average_bpm=190.0,
            exact_mod_combinations=(
                ModCombinationCount(("HD", "HR"), 2),
                ModCombinationCount((), 1),
            ),
            individual_mods=(
                ModAcronymCount("HD", 2),
                ModAcronymCount("HR", 2),
            ),
        )

        with (
            patch(
                "backend.app.player_analysis.get_player_statistics",
                return_value=statistics,
            ) as analysis,
            patch("backend.app.osu.client.OsuApiClient") as osu_client,
        ):
            response = self.client.get("/api/users/requested-name/analysis")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "user_id": 42,
                "username": "CanonicalPlayer",
                "top_play_count": 3,
                "average_pp": 321.5,
                "average_accuracy": 0.9842,
                "average_star_rating": 6.4,
                "average_approach_rate": None,
                "average_bpm": 190.0,
                "exact_mod_combinations": [
                    {"mods": ["HD", "HR"], "count": 2},
                    {"mods": [], "count": 1},
                ],
                "individual_mods": [
                    {"mod": "HD", "count": 2},
                    {"mod": "HR", "count": 2},
                ],
            },
        )
        analysis.assert_called_once_with("requested-name")
        osu_client.assert_not_called()

    def test_zero_play_user_returns_200_with_null_averages(self) -> None:
        statistics = PlayerStatistics(
            user_id=7,
            username="NewPlayer",
            top_play_count=0,
            average_pp=None,
            average_accuracy=None,
            average_star_rating=None,
            average_approach_rate=None,
            average_bpm=None,
            exact_mod_combinations=(),
            individual_mods=(),
        )

        with patch(
            "backend.app.player_analysis.get_player_statistics",
            return_value=statistics,
        ):
            response = self.client.get("/api/users/NewPlayer/analysis")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["top_play_count"], 0)
        self.assertIsNone(response.json()["average_pp"])
        self.assertIsNone(response.json()["average_accuracy"])
        self.assertEqual(response.json()["exact_mod_combinations"], [])
        self.assertEqual(response.json()["individual_mods"], [])

    def test_missing_persisted_user_returns_404(self) -> None:
        with patch(
            "backend.app.player_analysis.get_player_statistics",
            side_effect=PlayerNotFoundError("internal lookup detail"),
        ):
            response = self.client.get("/api/users/missing/analysis")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Persisted user was not found."})

    def test_configuration_error_returns_safe_500(self) -> None:
        with patch(
            "backend.app.player_analysis.get_player_statistics",
            side_effect=ValueError(
                "DATABASE_URL contains postgresql+psycopg://secret:password@host/db"
            ),
        ):
            response = self.client.get("/api/users/player/analysis")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {"detail": "Player analysis is currently unavailable."},
        )
        self.assertNotIn("password", response.text)

    def test_database_error_returns_safe_500(self) -> None:
        with patch(
            "backend.app.player_analysis.get_player_statistics",
            side_effect=OperationalError("statement", {}, Exception("private")),
        ):
            response = self.client.get("/api/users/player/analysis")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {"detail": "Player analysis is currently unavailable."},
        )
        self.assertNotIn("private", response.text)

    def test_existing_routes_remain_available(self) -> None:
        health_response = self.client.get("/health")
        paths = app.openapi()["paths"]

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.json(), {"status": "ok"})
        self.assertIn("/api/users/{username}/analysis", paths)
        self.assertIn("/api/users/{username}/top-plays", paths)


if __name__ == "__main__":
    unittest.main()
