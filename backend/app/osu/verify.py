import asyncio
import sys

from backend.app.osu.client import (
    OsuApiClient,
    OsuAuthenticationError,
    OsuCredentials,
    OsuNetworkError,
)


async def verify_authentication() -> None:
    """Acquire a token and report success without displaying the token."""
    credentials = OsuCredentials.from_environment()
    client = OsuApiClient(credentials)
    await client.request_access_token()


def main() -> None:
    try:
        asyncio.run(verify_authentication())
    except (ValueError, OsuAuthenticationError, OsuNetworkError) as error:
        print(f"osu! API authentication failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print("osu! API authentication succeeded.")


if __name__ == "__main__":
    main()
