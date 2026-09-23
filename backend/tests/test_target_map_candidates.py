"""Tests for target-map leaderboard candidate acquisition."""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend.app.candidates.target_maps import (
    TargetMapCandidateTargetNotFoundError,
    TargetMapEvidenceEmptyError,
    TargetMapSeed,
    discover_target_map_candidates,
    select_evenly_spaced_seeds,
)
from backend.app.osu.client import (
    OsuAccessToken,
    OsuApiClient,
    OsuApiError,
    OsuAuthenticationError,
    OsuCredentials,
    OsuLeaderboardUser,
    OsuNetworkError,
)


class FakeTargetMapSession:
    """Read-only target and ordered-play query double."""

    def __init__(self, target: Any, rows: list[Any]) -> None:
        self.target = target
        self.rows = rows
        self.execute_calls = 0

    def __enter__(self) -> "FakeTargetMapSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: Any) -> Any:
        self.execute_calls += 1
        if self.execute_calls == 1:
            return SimpleNamespace(one_or_none=lambda: self.target)
        if self.execute_calls == 2:
            return SimpleNamespace(all=lambda: self.rows)
        raise AssertionError("Target-map acquisition performed an unexpected query.")


class SeedSelectionTests(unittest.TestCase):
    def test_zero_plays_returns_no_seeds(self) -> None:
        self.assertEqual(select_evenly_spaced_seeds([], 5), ())

    def test_one_play_selects_that_play(self) -> None:
        play = TargetMapSeed(1, 101)
        self.assertEqual(select_evenly_spaced_seeds([play], 5), (play,))

    def test_fewer_plays_than_requested_selects_every_play_once(self) -> None:
        plays = self._plays(3)
        self.assertEqual(select_evenly_spaced_seeds(plays, 5), tuple(plays))

    def test_exact_requested_count_selects_every_play(self) -> None:
        plays = self._plays(5)
        self.assertEqual(select_evenly_spaced_seeds(plays, 5), tuple(plays))

    def test_one_hundred_plays_selects_deterministic_spread(self) -> None:
        plays = self._plays(100)

        first = select_evenly_spaced_seeds(plays, 5)
        second = select_evenly_spaced_seeds(plays, 5)

        self.assertEqual([seed.position for seed in first], [1, 25, 50, 75, 100])
        self.assertEqual(first, second)
        self.assertEqual(len({seed.position for seed in first}), 5)
        self.assertEqual(first[0], plays[0])
        self.assertEqual(first[-1], plays[-1])

    def test_seed_count_bounds_are_enforced(self) -> None:
        for value in (0, 11, True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "1 through 10"):
                    select_evenly_spaced_seeds(self._plays(5), value)

    @staticmethod
    def _plays(count: int) -> list[TargetMapSeed]:
        return [TargetMapSeed(position=index, beatmap_id=1000 + index) for index in range(1, count + 1)]


class BeatmapLeaderboardClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_expected_endpoint_mode_and_normalizes_users(self) -> None:
        client = OsuApiClient(OsuCredentials("id", "secret"))
        response = httpx.Response(
            200,
            json={
                "scores": [
                    {"id": 999, "user": {"id": 10, "username": "Player"}},
                    {"id": 998, "user": {"id": 20, "username": None}},
                ]
            },
        )
        http_client = AsyncMock()
        http_client.get.return_value = response
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=http_client)
        context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.object(
                client,
                "request_access_token",
                new=AsyncMock(return_value=OsuAccessToken("token", "Bearer", 100)),
            ),
            patch("backend.app.osu.client.httpx.AsyncClient", return_value=context),
        ):
            users = await client.get_beatmap_leaderboard_users(123)

        self.assertEqual(users, (OsuLeaderboardUser(10, "Player"), OsuLeaderboardUser(20, None)))
        http_client.get.assert_awaited_once_with(
            "https://osu.ppy.sh/api/v2/beatmaps/123/scores",
            params={"mode": "osu"},
            headers={"Authorization": "Bearer token"},
        )

    async def test_zero_scores_is_valid(self) -> None:
        response = httpx.Response(200, json={"scores": []})
        self.assertEqual(OsuApiClient._parse_beatmap_leaderboard(response), ())

    async def test_malformed_score_is_rejected(self) -> None:
        response = httpx.Response(200, json={"scores": [{"user": {"id": "bad"}}]})
        with self.assertRaisesRegex(OsuApiError, "position 1"):
            OsuApiClient._parse_beatmap_leaderboard(response)

    async def test_auth_api_and_network_errors_use_existing_categories(self) -> None:
        for status, error_type in ((401, OsuAuthenticationError), (500, OsuApiError)):
            with self.subTest(status=status):
                client, context = self._client_for_response(httpx.Response(status))
                with patch("backend.app.osu.client.httpx.AsyncClient", return_value=context):
                    with self.assertRaises(error_type):
                        await client.get_beatmap_leaderboard_users(123)

        client, context = self._client_for_response(
            httpx.RequestError("offline", request=httpx.Request("GET", "https://example.test"))
        )
        with patch("backend.app.osu.client.httpx.AsyncClient", return_value=context):
            with self.assertRaises(OsuNetworkError):
                await client.get_beatmap_leaderboard_users(123)

    @staticmethod
    def _client_for_response(response_or_error: object) -> tuple[OsuApiClient, MagicMock]:
        client = OsuApiClient(OsuCredentials("id", "secret"))
        client.request_access_token = AsyncMock(
            return_value=OsuAccessToken("token", "Bearer", 100)
        )
        http_client = AsyncMock()
        if isinstance(response_or_error, Exception):
            http_client.get.side_effect = response_or_error
        else:
            http_client.get.return_value = response_or_error
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=http_client)
        context.__aexit__ = AsyncMock(return_value=None)
        return client, context


class TargetMapCandidateExperimentTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_persisted_target_and_skips_api(self) -> None:
        session = FakeTargetMapSession(None, [])
        client = SimpleNamespace(get_beatmap_leaderboard_users=AsyncMock())

        with self.assertRaisesRegex(TargetMapCandidateTargetNotFoundError, "was not found"):
            await discover_target_map_candidates(
                "missing", session_factory=lambda: session, osu_client=client
            )

        client.get_beatmap_leaderboard_users.assert_not_awaited()
        self.assertEqual(session.execute_calls, 1)

    async def test_empty_target_evidence_skips_api(self) -> None:
        session = self._session([])
        client = SimpleNamespace(get_beatmap_leaderboard_users=AsyncMock())

        with self.assertRaisesRegex(TargetMapEvidenceEmptyError, "no top plays"):
            await discover_target_map_candidates(
                "target", session_factory=lambda: session, osu_client=client
            )

        client.get_beatmap_leaderboard_users.assert_not_awaited()

    async def test_processes_all_seeds_then_accumulates_and_truncates(self) -> None:
        session = self._session([(1, 101), (2, 102), (3, 103)])
        client = SimpleNamespace(
            get_beatmap_leaderboard_users=AsyncMock(
                side_effect=[
                    (OsuLeaderboardUser(42, "Target"), OsuLeaderboardUser(10, "Ten"), OsuLeaderboardUser(20, "Twenty")),
                    (),
                    (OsuLeaderboardUser(20, "Twenty"), OsuLeaderboardUser(30, "Thirty"), OsuLeaderboardUser(10, "Ten")),
                ]
            ),
            get_user_by_username=AsyncMock(),
            get_top_plays_by_user_id=AsyncMock(),
        )

        result = await discover_target_map_candidates(
            "target",
            seed_count=3,
            candidate_limit=2,
            session_factory=lambda: session,
            osu_client=client,
        )

        self.assertEqual(client.get_beatmap_leaderboard_users.await_count, 3)
        self.assertEqual(
            [call.args[0] for call in client.get_beatmap_leaderboard_users.await_args_list],
            [101, 102, 103],
        )
        self.assertEqual(result.leaderboard_requests_made, 3)
        self.assertEqual(result.unique_candidate_count, 3)
        self.assertEqual(result.seed_hit_distribution, ((2, 2), (1, 1)))
        self.assertEqual([candidate.user_id for candidate in result.candidates], [10, 20])
        self.assertEqual(result.candidates[0].seed_beatmap_ids, (101, 103))
        self.assertEqual(result.candidates[0].seed_hit_count, 2)
        self.assertNotIn(42, [candidate.user_id for candidate in result.candidates])
        client.get_user_by_username.assert_not_awaited()
        client.get_top_plays_by_user_id.assert_not_awaited()

    async def test_two_hundred_returned_users_still_make_one_call_per_seed(self) -> None:
        session = self._session([(index, 100 + index) for index in range(1, 6)])
        users = tuple(OsuLeaderboardUser(index, f"User{index}") for index in range(1, 201))
        client = SimpleNamespace(
            get_beatmap_leaderboard_users=AsyncMock(return_value=users)
        )

        result = await discover_target_map_candidates(
            "target",
            seed_count=5,
            candidate_limit=100,
            session_factory=lambda: session,
            osu_client=client,
        )

        self.assertEqual(client.get_beatmap_leaderboard_users.await_count, 5)
        self.assertEqual(result.leaderboard_requests_made, 5)
        self.assertEqual(result.unique_candidate_count, 199)
        self.assertEqual(len(result.candidates), 100)
        self.assertTrue(all(candidate.seed_hit_count == 5 for candidate in result.candidates))

    async def test_upstream_failure_returns_no_partial_result(self) -> None:
        session = self._session([(1, 101), (2, 102)])
        client = SimpleNamespace(
            get_beatmap_leaderboard_users=AsyncMock(
                side_effect=[(OsuLeaderboardUser(10, "Ten"),), OsuApiError("failed")]
            )
        )

        with self.assertRaisesRegex(OsuApiError, "failed"):
            await discover_target_map_candidates(
                "target",
                seed_count=2,
                session_factory=lambda: session,
                osu_client=client,
            )

    async def test_limits_validate_before_database_access(self) -> None:
        session = self._session([(1, 101)])
        for arguments in (
            {"seed_count": 0},
            {"seed_count": 11},
            {"candidate_limit": 0},
            {"candidate_limit": 101},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ValueError, "must be an integer"):
                    await discover_target_map_candidates(
                        "target", session_factory=lambda: session, **arguments
                    )
        self.assertEqual(session.execute_calls, 0)

    @staticmethod
    def _session(rows: list[tuple[int, int]]) -> FakeTargetMapSession:
        return FakeTargetMapSession(
            SimpleNamespace(user_id=42, username="Target"),
            [SimpleNamespace(position=position, beatmap_id=beatmap_id) for position, beatmap_id in rows],
        )


if __name__ == "__main__":
    unittest.main()
