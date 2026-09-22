"""Tests for bounded candidate-user discovery."""

import os
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from backend.app.candidates.discovery import (
    CandidateTargetNotFoundError,
    discover_candidate_users,
)
from backend.app.osu.client import (
    OsuApiError,
    OsuRankingPage,
    OsuRankingUser,
)


class FakeCandidateSession:
    """Read-only session double returning a target and one local result set."""

    def __init__(self, target: Any, local_rows: list[Any]) -> None:
        self.target = target
        self.local_rows = local_rows
        self.execute_calls = 0

    def __enter__(self) -> "FakeCandidateSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: Any) -> Any:
        self.execute_calls += 1
        if self.execute_calls == 1:
            return SimpleNamespace(one_or_none=lambda: self.target)
        if self.execute_calls == 2:
            return SimpleNamespace(all=lambda: self.local_rows)
        raise AssertionError("Candidate discovery performed an unexpected query.")


class CandidateDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_persisted_target_is_clear_and_skips_local_query(self) -> None:
        session = FakeCandidateSession(None, [])

        with self.assertRaisesRegex(CandidateTargetNotFoundError, "was not found"):
            await discover_candidate_users(
                "missing",
                session_factory=lambda: session,
            )

        self.assertEqual(session.execute_calls, 1)

    async def test_local_candidates_are_ordered_and_need_no_osu_credentials(self) -> None:
        session = self._session(
            local=[(10, "Ten"), (20, "Twenty"), (30, "Thirty")]
        )

        with patch.dict(os.environ, {}, clear=True):
            result = await discover_candidate_users(
                "target",
                limit=2,
                session_factory=lambda: session,
            )

        self.assertEqual([item.user_id for item in result.candidates], [10, 20])
        self.assertEqual([item.sources for item in result.candidates], [("local",)] * 2)
        self.assertNotIn(result.target_user_id, [item.user_id for item in result.candidates])
        self.assertEqual(result.ranking_requests_made, 0)
        self.assertEqual(session.execute_calls, 2)

    async def test_ranking_fills_capacity_in_upstream_order_and_stops_early(self) -> None:
        session = self._session(local=[(10, "Local")])
        client = SimpleNamespace(
            get_osu_performance_ranking=AsyncMock(
                return_value=self._page(
                    [(100, "First"), (200, "Second"), (300, "Unused")],
                    cursor=(("page", "2"),),
                )
            )
        )

        result = await discover_candidate_users(
            "target", limit=3, session_factory=lambda: session, osu_client=client
        )

        self.assertEqual([item.user_id for item in result.candidates], [10, 100, 200])
        self.assertEqual(result.ranking_requests_made, 1)
        client.get_osu_performance_ranking.assert_awaited_once_with(None)

    async def test_deduplicates_by_id_merges_provenance_and_excludes_target(self) -> None:
        session = self._session(local=[(10, "Local Name")])
        client = SimpleNamespace(
            get_osu_performance_ranking=AsyncMock(
                return_value=self._page(
                    [(42, "Target"), (10, "Changed Name"), (20, "New")]
                )
            )
        )

        result = await discover_candidate_users(
            "target", limit=3, session_factory=lambda: session, osu_client=client
        )

        self.assertEqual([item.user_id for item in result.candidates], [10, 20])
        self.assertEqual(result.candidates[0].username, "Local Name")
        self.assertEqual(result.candidates[0].sources, ("local", "ranking"))
        self.assertEqual(result.candidates[1].sources, ("ranking",))

    async def test_follows_returned_cursor_and_stops_when_cursor_ends(self) -> None:
        session = self._session(local=[])
        client = SimpleNamespace(
            get_osu_performance_ranking=AsyncMock(
                side_effect=[
                    self._page([(10, "Ten")], cursor=(("page", "2"),)),
                    self._page([(20, "Twenty")]),
                ]
            )
        )

        result = await discover_candidate_users(
            "target", limit=10, session_factory=lambda: session, osu_client=client
        )

        self.assertEqual([item.user_id for item in result.candidates], [10, 20])
        self.assertEqual(result.ranking_requests_made, 2)
        self.assertEqual(
            client.get_osu_performance_ranking.await_args_list[1].args,
            ((('page', '2'),),),
        )

    async def test_ranking_request_hard_cap_is_three_even_for_duplicates(self) -> None:
        session = self._session(local=[])
        pages = [
            self._page([(10, "Ten")], cursor=(("page", str(page + 1)),))
            for page in range(1, 4)
        ]
        client = SimpleNamespace(
            get_osu_performance_ranking=AsyncMock(side_effect=pages)
        )

        result = await discover_candidate_users(
            "target", limit=100, session_factory=lambda: session, osu_client=client
        )

        self.assertEqual([item.user_id for item in result.candidates], [10])
        self.assertEqual(result.ranking_requests_made, 3)
        self.assertEqual(client.get_osu_performance_ranking.await_count, 3)

    async def test_ranking_failure_is_not_silently_returned_as_partial_success(self) -> None:
        session = self._session(local=[(10, "Local")])
        client = SimpleNamespace(
            get_osu_performance_ranking=AsyncMock(
                side_effect=OsuApiError("safe upstream failure")
            )
        )

        with self.assertRaisesRegex(OsuApiError, "safe upstream failure"):
            await discover_candidate_users(
                "target", limit=2, session_factory=lambda: session, osu_client=client
            )

    async def test_ranking_fallback_without_credentials_fails_clearly(self) -> None:
        session = self._session(local=[])

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OSU_CLIENT_ID"):
                await discover_candidate_users(
                    "target", limit=1, session_factory=lambda: session
                )

    async def test_limit_validation_happens_before_database_access(self) -> None:
        session = self._session(local=[])
        for invalid_limit in (0, 101, True):
            with self.subTest(limit=invalid_limit):
                with self.assertRaisesRegex(ValueError, "1 through 100"):
                    await discover_candidate_users(
                        "target",
                        invalid_limit,
                        session_factory=lambda: session,
                    )
        self.assertEqual(session.execute_calls, 0)

    @staticmethod
    def _session(local: list[tuple[int, str]]) -> FakeCandidateSession:
        return FakeCandidateSession(
            SimpleNamespace(user_id=42, username="Target"),
            [SimpleNamespace(user_id=user_id, username=username) for user_id, username in local],
        )

    @staticmethod
    def _page(
        users: list[tuple[int, str]],
        cursor: tuple[tuple[str, str], ...] | None = None,
    ) -> OsuRankingPage:
        return OsuRankingPage(
            users=tuple(OsuRankingUser(user_id, username) for user_id, username in users),
            cursor=cursor,
        )


if __name__ == "__main__":
    unittest.main()
