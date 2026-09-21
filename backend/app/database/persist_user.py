"""Developer command for fetching and persisting one osu! user's current state."""

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from backend.app.database.persistence import (
    PersistenceResult,
    persist_user_top_plays,
)
from backend.app.osu.client import (
    OsuApiClient,
    OsuApiError,
    OsuAuthenticationError,
    OsuCredentials,
    OsuNetworkError,
)


async def fetch_and_persist_user(username: str) -> PersistenceResult:
    """Fetch one complete user state and persist it transactionally."""
    client = OsuApiClient(OsuCredentials.from_environment())
    profile = await client.get_user_by_username(username)
    top_plays = await client.get_top_plays_by_user_id(profile.user_id, limit=100)
    return persist_user_top_plays(profile, top_plays)


def main() -> int:
    """Run the explicit persistence workflow with concise safe errors."""
    parser = argparse.ArgumentParser(
        description="Fetch and persist an osu! user's complete current top-play state."
    )
    parser.add_argument("username", help="osu! username to fetch and persist")
    arguments = parser.parse_args()

    try:
        result = asyncio.run(fetch_and_persist_user(arguments.username))
    except ValueError as error:
        print(f"Configuration or data error: {error}", file=sys.stderr)
        return 1
    except OsuAuthenticationError:
        print("osu! API authentication failed.", file=sys.stderr)
        return 1
    except OsuNetworkError:
        print("The osu! API is currently unreachable.", file=sys.stderr)
        return 1
    except OsuApiError as error:
        print(f"osu! API request failed: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "Database persistence failed. Check the PostgreSQL connection and schema.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Persisted {result.username} (user ID {result.user_id}): "
        f"{result.top_play_count} top plays, {result.beatmap_count} beatmaps."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
