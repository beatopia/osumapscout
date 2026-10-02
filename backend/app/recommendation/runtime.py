"""Process-local recommendation runtime and conservative response cache."""

import asyncio

from dataclasses import dataclass

from backend.app.cache import AsyncTTLCache, CacheSnapshot
from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.service import RecommendationResult, generate_recommendations

RECOMMENDATION_TTL_SECONDS = 120.0
RECOMMENDATION_CACHE_SIZE = 128
MAX_CONCURRENT_GENERATIONS = 2


@dataclass(frozen=True)
class CachedRecommendationResult:
    result: RecommendationResult
    cache_status: str


class RecommendationRuntime:
    """Reuse OAuth state and coalesce identical recommendation requests."""

    def __init__(
        self,
        client: OsuApiClient,
        *,
        ttl_seconds: float = RECOMMENDATION_TTL_SECONDS,
        max_entries: int = RECOMMENDATION_CACHE_SIZE,
        max_concurrent_generations: int = MAX_CONCURRENT_GENERATIONS,
    ) -> None:
        self._client = client
        self._cache: AsyncTTLCache[tuple[str, int], RecommendationResult] = (
            AsyncTTLCache(ttl_seconds, max_entries)
        )
        self._generation_semaphore = asyncio.Semaphore(max_concurrent_generations)

    async def recommendations(
        self, username: str, limit: int
    ) -> CachedRecommendationResult:
        normalized = username.strip()
        key = (normalized.casefold(), limit)
        async def generate() -> RecommendationResult:
            async with self._generation_semaphore:
                return await generate_recommendations(
                    normalized, limit=limit, osu_client=self._client
                )

        result, status = await self._cache.get_or_create(
            key,
            generate,
        )
        return CachedRecommendationResult(result, status)

    def cache_snapshot(self) -> CacheSnapshot:
        return self._cache.snapshot()

    async def clear(self) -> None:
        await self._cache.clear()

    async def close(self) -> None:
        await self._client.close()


_runtime: RecommendationRuntime | None = None


def get_recommendation_runtime() -> RecommendationRuntime:
    global _runtime
    if _runtime is None:
        _runtime = RecommendationRuntime(
            OsuApiClient(OsuCredentials.from_environment(), persistent=True)
        )
    return _runtime


async def close_recommendation_runtime() -> None:
    """Close and discard the process runtime during application shutdown."""
    global _runtime
    if _runtime is not None:
        await _runtime.close()
        _runtime = None
