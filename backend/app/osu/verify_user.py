import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from backend.app.osu.client import (
    OsuApiClient,
    OsuApiError,
    OsuAuthenticationError,
    OsuCredentials,
    OsuNetworkError,
)


async def fetch_user(username: str) -> None:
    """Fetch and print only the normalized profile fields."""
    credentials = OsuCredentials.from_environment()
    client = OsuApiClient(credentials)
    profile = await client.get_user_by_username(username)
    print(json.dumps(asdict(profile), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify osu!standard user-profile fetching."
    )
    parser.add_argument("username", help="osu! username to look up")
    arguments = parser.parse_args()

    try:
        asyncio.run(fetch_user(arguments.username))
    except (ValueError, OsuAuthenticationError, OsuNetworkError, OsuApiError) as error:
        print(f"osu! user lookup failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
