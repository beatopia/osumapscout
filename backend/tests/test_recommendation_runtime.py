"""Tests for recommendation-level caching and concurrency control."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.app.recommendation.runtime import RecommendationRuntime


class RecommendationRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_identical_requests_are_generated_once(self) -> None:
        runtime = RecommendationRuntime(SimpleNamespace(close=AsyncMock()), ttl_seconds=5)  # type: ignore[arg-type]
        result = object()
        generator = AsyncMock(return_value=result)
        with patch("backend.app.recommendation.runtime.generate_recommendations", generator):
            first, second = await asyncio.gather(
                runtime.recommendations("Player", 20),
                runtime.recommendations("player", 20),
            )
        self.assertIs(first.result, result)
        self.assertIs(second.result, result)
        self.assertEqual({first.cache_status, second.cache_status}, {"miss", "coalesced"})
        generator.assert_awaited_once()

    async def test_different_requests_respect_generation_limit(self) -> None:
        runtime = RecommendationRuntime(
            SimpleNamespace(close=AsyncMock()),  # type: ignore[arg-type]
            ttl_seconds=5,
            max_concurrent_generations=2,
        )
        active = 0
        maximum = 0

        async def generate(username: str, **_kwargs: object) -> object:
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return object()

        with patch(
            "backend.app.recommendation.runtime.generate_recommendations",
            side_effect=generate,
        ):
            await asyncio.gather(
                *(runtime.recommendations(name, 20) for name in ("one", "two", "three"))
            )
        self.assertEqual(maximum, 2)


if __name__ == "__main__":
    unittest.main()
