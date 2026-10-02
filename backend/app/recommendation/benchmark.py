"""Repeatable cold/warm production recommendation benchmark."""

import argparse
import asyncio
import time

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.runtime import RecommendationRuntime
from backend.app.recommendation.service import RecommendationResult

DEFAULT_TARGETS = ("molerat", "mrekk", "Vaxei", "WhiteCat", "peppy")


def _request_total(result: RecommendationResult) -> int:
    requests = result.requests
    return sum((
        requests.profile_requests,
        requests.target_top_play_requests,
        requests.leaderboard_requests,
        requests.candidate_top_play_requests,
        requests.beatmap_attribute_requests,
    ))


def _identity(result: RecommendationResult) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (item.beatmap_id, item.suggested_mods, item.support_count)
        for item in result.recommendations
    )


async def _measure(runtime: RecommendationRuntime, username: str, limit: int) -> None:
    started = time.perf_counter()
    cold = await runtime.recommendations(username, limit)
    cold_seconds = time.perf_counter() - started
    started = time.perf_counter()
    warm = await runtime.recommendations(username, limit)
    warm_seconds = time.perf_counter() - started
    identical = _identity(cold.result) == _identity(warm.result)
    print(
        f"BENCHMARK target={cold.result.target_username} "
        f"cold_seconds={cold_seconds:.3f} warm_seconds={warm_seconds:.6f} "
        f"cold_api_requests={_request_total(cold.result)} warm_api_requests=0 "
        f"cold_status={cold.cache_status} warm_status={warm.cache_status} "
        f"recommendations={len(cold.result.recommendations)} identical={identical}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("targets", nargs="*", default=DEFAULT_TARGETS)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    runtime = RecommendationRuntime(
        OsuApiClient(OsuCredentials.from_environment(), persistent=True)
    )
    for target in args.targets:
        await _measure(runtime, target, args.limit)
    await runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
