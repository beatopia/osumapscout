import argparse
import asyncio
import sys

from backend.app.osu.client import (
    OsuApiClient,
    OsuApiError,
    OsuAuthenticationError,
    OsuCredentials,
    OsuNetworkError,
)


async def print_top_plays(username: str, limit: int) -> None:
    """Fetch top plays and print a concise, readable summary."""
    credentials = OsuCredentials.from_environment()
    client = OsuApiClient(credentials)
    plays = await client.get_top_plays_by_username(username, limit)

    print(f"Fetched {len(plays)} top plays for {username}.")
    for position, play in enumerate(plays, start=1):
        artist = play.artist or "Unknown artist"
        title = play.title or f"Beatmap {play.beatmap_id}"
        difficulty = f" [{play.difficulty_name}]" if play.difficulty_name else ""
        pp = (
            f"{play.performance_points:.2f}pp"
            if play.performance_points is not None
            else "PP unavailable"
        )
        mods = "".join(play.mods) or "NM"
        print(
            f"{position}. {artist} - {title}{difficulty} | "
            f"beatmap {play.beatmap_id} | {pp} | {mods}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify osu!standard top-play fetching."
    )
    parser.add_argument("username", help="osu! username to look up")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="number of top plays to fetch, from 1 to 100 (default: 10)",
    )
    arguments = parser.parse_args()

    try:
        asyncio.run(print_top_plays(arguments.username, arguments.limit))
    except (ValueError, OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
        print(f"osu! top-play lookup failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
