"""Small bounded asynchronous TTL cache with per-key request coalescing."""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True)
class CacheSnapshot:
    hits: int
    misses: int
    coalesced: int
    entries: int


class AsyncTTLCache(Generic[K, V]):
    """Cache successful immutable values and share concurrent identical work."""

    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("Cache TTL and maximum size must be positive.")
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._values: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self._inflight: dict[K, asyncio.Task[V]] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._coalesced = 0

    async def get_or_create(
        self, key: K, factory: Callable[[], Awaitable[V]]
    ) -> tuple[V, str]:
        """Return a value plus ``hit``, ``miss``, or ``coalesced`` status."""
        async with self._lock:
            now = self._clock()
            cached = self._values.get(key)
            if cached is not None and cached[0] > now:
                self._values.move_to_end(key)
                self._hits += 1
                return cached[1], "hit"
            if cached is not None:
                del self._values[key]
            task = self._inflight.get(key)
            if task is not None:
                self._coalesced += 1
                status = "coalesced"
            else:
                task = asyncio.create_task(factory())
                self._inflight[key] = task
                self._misses += 1
                status = "miss"
        try:
            value = await asyncio.shield(task)
        except BaseException:
            async with self._lock:
                if self._inflight.get(key) is task and task.done():
                    del self._inflight[key]
            raise
        async with self._lock:
            if self._inflight.get(key) is task:
                del self._inflight[key]
                self._values[key] = (self._clock() + self._ttl, value)
                self._values.move_to_end(key)
                while len(self._values) > self._max_entries:
                    self._values.popitem(last=False)
        return value, status

    async def clear(self) -> None:
        async with self._lock:
            self._values.clear()

    def snapshot(self) -> CacheSnapshot:
        return CacheSnapshot(
            self._hits, self._misses, self._coalesced, len(self._values)
        )
