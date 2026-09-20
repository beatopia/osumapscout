import os
from dataclasses import dataclass
from typing import Any

import httpx

OSU_TOKEN_URL = "https://osu.ppy.sh/oauth/token"


class OsuAuthenticationError(RuntimeError):
    """Raised when osu! does not provide a usable access token."""


class OsuNetworkError(RuntimeError):
    """Raised when the osu! authentication request cannot be completed."""


@dataclass(frozen=True)
class OsuCredentials:
    client_id: str
    client_secret: str

    @classmethod
    def from_environment(cls) -> "OsuCredentials":
        """Load required osu! application credentials from the environment."""
        client_id = os.getenv("OSU_CLIENT_ID", "").strip()
        client_secret = os.getenv("OSU_CLIENT_SECRET", "").strip()

        missing_variables = [
            name
            for name, value in (
                ("OSU_CLIENT_ID", client_id),
                ("OSU_CLIENT_SECRET", client_secret),
            )
            if not value
        ]
        if missing_variables:
            missing = ", ".join(missing_variables)
            raise ValueError(f"Missing required environment variables: {missing}")

        return cls(client_id=client_id, client_secret=client_secret)


@dataclass(frozen=True)
class OsuAccessToken:
    access_token: str
    token_type: str
    expires_in: int


class OsuApiClient:
    """Perform the osu! API HTTP communication needed for authentication."""

    def __init__(self, credentials: OsuCredentials) -> None:
        self._credentials = credentials

    async def request_access_token(self) -> OsuAccessToken:
        """Request an application access token using client credentials."""
        request_data = {
            "client_id": self._credentials.client_id,
            "client_secret": self._credentials.client_secret,
            "grant_type": "client_credentials",
            "scope": "public",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                response = await http_client.post(OSU_TOKEN_URL, data=request_data)
        except httpx.RequestError as error:
            raise OsuNetworkError(
                "Could not reach osu! to request an access token."
            ) from error

        if response.is_error:
            raise OsuAuthenticationError(
                f"osu! rejected the access-token request with HTTP {response.status_code}."
            )

        return self._parse_access_token(response)

    @staticmethod
    def _parse_access_token(response: httpx.Response) -> OsuAccessToken:
        try:
            response_data: Any = response.json()
            access_token = response_data["access_token"]
            token_type = response_data["token_type"]
            expires_in = response_data["expires_in"]
        except (KeyError, TypeError, ValueError) as error:
            raise OsuAuthenticationError(
                "osu! returned an invalid access-token response."
            ) from error

        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(token_type, str)
            or not token_type
            or not isinstance(expires_in, int)
        ):
            raise OsuAuthenticationError(
                "osu! returned an invalid access-token response."
            )

        return OsuAccessToken(
            access_token=access_token,
            token_type=token_type,
            expires_in=expires_in,
        )
