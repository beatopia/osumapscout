"""Tests for bounded TTL caching and identical-request coalescing."""

import asyncio
import unittest
from unittest.mock import AsyncMock

from backend.app.cache import AsyncTTLCache


class AsyncTTLCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_hit_before_expiry_and_miss_after_expiry(self) -> None:
        now = [10.0]
        cache: AsyncTTLCache[str, object] = AsyncTTLCache(
            5.0, 2, clock=lambda: now[0]
        )
        factory = AsyncMock(side_effect=[object(), object()])

        first, first_status = await cache.get_or_create("key", factory)
        second, second_status = await cache.get_or_create("key", factory)
        now[0] = 16.0
        third, third_status = await cache.get_or_create("key", factory)

        self.assertIs(first, second)
        self.assertIsNot(first, third)
        self.assertEqual((first_status, second_status, third_status), ("miss", "hit", "miss"))
        self.assertEqual(factory.await_count, 2)

    async def test_concurrent_requests_share_one_factory_call(self) -> None:
        cache: AsyncTTLCache[str, int] = AsyncTTLCache(5.0, 2)
        started = asyncio.Event()
        release = asyncio.Event()

        async def factory() -> int:
            started.set()
            await release.wait()
            return 42

        first = asyncio.create_task(cache.get_or_create("key", factory))
        await started.wait()
        second = asyncio.create_task(cache.get_or_create("key", factory))
        await asyncio.sleep(0)
        release.set()

        self.assertEqual(await first, (42, "miss"))
        self.assertEqual(await second, (42, "coalesced"))

    async def test_failure_is_not_cached(self) -> None:
        cache: AsyncTTLCache[str, int] = AsyncTTLCache(5.0, 2)
        failing = AsyncMock(side_effect=RuntimeError("temporary"))
        with self.assertRaises(RuntimeError):
            await cache.get_or_create("key", failing)
        successful = AsyncMock(return_value=7)
        self.assertEqual(await cache.get_or_create("key", successful), (7, "miss"))

    async def test_oldest_entry_is_evicted_at_bound(self) -> None:
        cache: AsyncTTLCache[str, int] = AsyncTTLCache(5.0, 2)
        for key, value in (("a", 1), ("b", 2), ("c", 3)):
            await cache.get_or_create(key, AsyncMock(return_value=value))
        factory = AsyncMock(return_value=4)
        self.assertEqual(await cache.get_or_create("a", factory), (4, "miss"))
