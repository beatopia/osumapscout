"""Tests for narrow osu! performance-ranking normalization."""

import unittest

import httpx

from backend.app.osu.client import OsuApiClient, OsuApiError


class OsuRankingParsingTests(unittest.TestCase):
    def test_normalizes_only_user_identity_and_cursor(self) -> None:
        response = httpx.Response(
            200,
            json={
                "ranking": [
                    {
                        "global_rank": 1,
                        "pp": 25000,
                        "user": {"id": 10, "username": "Player", "country_code": "US"},
                    }
                ],
                "cursor": {"page": 2},
                "total": 1000000,
            },
        )

        page = OsuApiClient._parse_ranking_page(response)

        self.assertEqual(page.users[0].user_id, 10)
        self.assertEqual(page.users[0].username, "Player")
        self.assertEqual(page.cursor, (("page", "2"),))

    def test_rejects_invalid_user_identity(self) -> None:
        response = httpx.Response(
            200,
            json={"ranking": [{"user": {"id": "10", "username": "Player"}}]},
        )

        with self.assertRaisesRegex(OsuApiError, "entry at position 1"):
            OsuApiClient._parse_ranking_page(response)

    def test_rejects_invalid_cursor(self) -> None:
        response = httpx.Response(200, json={"ranking": [], "cursor": ["page", 2]})

        with self.assertRaisesRegex(OsuApiError, "cursor"):
            OsuApiClient._parse_ranking_page(response)


if __name__ == "__main__":
    unittest.main()
