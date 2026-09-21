"""Unit tests for current-state persistence mapping."""

import unittest
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.database.models import Beatmap, User, UserTopPlay
from backend.app.database.persist_user import fetch_and_persist_user
from backend.app.database.persistence import (
    PersistenceResult,
    parse_played_at,
    persist_user_top_plays,
)
from backend.app.osu.client import (
    OsuApiClient,
    OsuCredentials,
    OsuTopPlay,
    OsuUserProfile,
)


class OsuClientPersistenceSupportTests(unittest.IsolatedAsyncioTestCase):
    async def test_username_method_validates_limit_before_profile_lookup(self) -> None:
        client = OsuApiClient(OsuCredentials("client-id", "client-secret"))

        with patch.object(
            client,
            "get_user_by_username",
            new_callable=AsyncMock,
        ) as profile_lookup:
            with self.assertRaisesRegex(ValueError, "limit"):
                await client.get_top_plays_by_username("player", limit=0)

        profile_lookup.assert_not_awaited()

    async def test_workflow_fetches_profile_once_then_full_plays_by_id(self) -> None:
        profile = OsuUserProfile(
            user_id=42,
            username="player",
            country_code="US",
            avatar_url="https://example.test/avatar.png",
            global_rank=None,
            performance_points=None,
        )
        client = MagicMock()
        client.get_user_by_username = AsyncMock(return_value=profile)
        client.get_top_plays_by_user_id = AsyncMock(return_value=[])
        expected = PersistenceResult(42, "player", 0, 0)

        with (
            patch(
                "backend.app.database.persist_user.OsuCredentials.from_environment",
                return_value=OsuCredentials("client-id", "client-secret"),
            ),
            patch(
                "backend.app.database.persist_user.OsuApiClient",
                return_value=client,
            ),
            patch(
                "backend.app.database.persist_user.persist_user_top_plays",
                return_value=expected,
            ) as persist,
        ):
            result = await fetch_and_persist_user("player")

        client.get_user_by_username.assert_awaited_once_with("player")
        client.get_top_plays_by_user_id.assert_awaited_once_with(42, limit=100)
        persist.assert_called_once_with(profile, [])
        self.assertEqual(result, expected)


class FakeSession:
    """Minimal session double used to inspect ORM objects before a live database test."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.executed: list[Any] = []

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def begin(self) -> nullcontext[None]:
        return nullcontext()

    def get(self, model: type[Any], identity: int) -> None:
        return None

    def scalars(self, statement: Any) -> tuple[()]:
        return ()

    def add(self, model: Any) -> None:
        self.added.append(model)

    def execute(self, statement: Any) -> None:
        self.executed.append(statement)


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = OsuUserProfile(
            user_id=42,
            username="player",
            country_code="US",
            avatar_url="https://example.test/avatar.png",
            global_rank=123,
            performance_points=4567.8,
        )
        self.observed_at = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

    def test_maps_fields_and_assigns_positions_in_response_order(self) -> None:
        session = FakeSession()
        plays = [
            self._play(
                beatmap_id=20,
                played_at="2026-09-19T01:02:03Z",
                mods=("HD", "HR"),
            ),
            self._play(beatmap_id=10, played_at=None, mods=()),
        ]

        result = persist_user_top_plays(
            self.profile,
            plays,
            fetched_at=self.observed_at,
            session_factory=lambda: session,
        )

        user = next(item for item in session.added if isinstance(item, User))
        beatmaps = [item for item in session.added if isinstance(item, Beatmap)]
        saved_plays = [
            item for item in session.added if isinstance(item, UserTopPlay)
        ]

        self.assertEqual(user.user_id, 42)
        self.assertEqual(len(beatmaps), 2)
        self.assertEqual([play.beatmap_id for play in saved_plays], [20, 10])
        self.assertEqual([play.position for play in saved_plays], [1, 2])
        self.assertEqual(saved_plays[0].mods, ["HD", "HR"])
        self.assertEqual(saved_plays[1].mods, [])
        self.assertEqual(
            saved_plays[0].played_at,
            datetime(2026, 9, 19, 1, 2, 3, tzinfo=timezone.utc),
        )
        self.assertIsNone(saved_plays[1].played_at)
        self.assertTrue(
            all(item.fetched_at == self.observed_at for item in session.added)
        )
        self.assertEqual(len(session.executed), 1)
        self.assertEqual(result.top_play_count, 2)
        self.assertEqual(result.beatmap_count, 2)

    def test_empty_complete_result_still_replaces_existing_rows(self) -> None:
        session = FakeSession()

        result = persist_user_top_plays(
            self.profile,
            [],
            fetched_at=self.observed_at,
            session_factory=lambda: session,
        )

        self.assertEqual(len(session.executed), 1)
        self.assertFalse(
            any(isinstance(item, UserTopPlay) for item in session.added)
        )
        self.assertEqual(result.top_play_count, 0)

    def test_rejects_timestamp_without_timezone(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone offset"):
            parse_played_at("2026-09-19T01:02:03")

    @staticmethod
    def _play(
        *,
        beatmap_id: int,
        played_at: str | None,
        mods: tuple[str, ...],
    ) -> OsuTopPlay:
        return OsuTopPlay(
            score_id=beatmap_id + 100,
            beatmap_id=beatmap_id,
            beatmapset_id=1,
            artist="Artist",
            title="Title",
            difficulty_name="Difficulty",
            performance_points=100.0,
            accuracy=0.98,
            grade="S",
            mods=mods,
            max_combo=500,
            played_at=played_at,
            star_rating=5.2,
            approach_rate=9.0,
            bpm=180.0,
        )


if __name__ == "__main__":
    unittest.main()
