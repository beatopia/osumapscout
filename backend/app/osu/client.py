import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

OSU_TOKEN_URL = "https://osu.ppy.sh/oauth/token"
OSU_API_BASE_URL = "https://osu.ppy.sh/api/v2"


class OsuAuthenticationError(RuntimeError):
    """Raised when osu! does not provide a usable access token."""


class OsuNetworkError(RuntimeError):
    """Raised when an osu! API request cannot be completed."""


class OsuApiError(RuntimeError):
    """Raised when osu! returns an unusable API response."""


class OsuUserNotFoundError(OsuApiError):
    """Raised when osu! cannot find the requested user."""


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


@dataclass(frozen=True)
class OsuUserProfile:
    user_id: int
    username: str
    country_code: str
    avatar_url: str
    global_rank: int | None
    performance_points: float | None


@dataclass(frozen=True)
class OsuTopPlay:
    score_id: int | None
    beatmap_id: int
    beatmapset_id: int | None
    artist: str | None
    title: str | None
    difficulty_name: str | None
    performance_points: float | None
    accuracy: float | None
    grade: str | None
    mods: tuple[str, ...]
    max_combo: int | None
    played_at: str | None
    star_rating: float | None
    approach_rate: float | None
    bpm: float | None


class OsuApiClient:
    """Perform the osu! HTTP communication used by the application."""

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

    async def get_user_by_username(self, username: str) -> OsuUserProfile:
        """Fetch a minimal osu!standard profile using a normal username."""
        normalized_username = username.strip()
        if not normalized_username:
            raise ValueError("Username must not be empty.")

        access_token = await self.request_access_token()
        encoded_username = quote(normalized_username, safe="")
        user_url = f"{OSU_API_BASE_URL}/users/@{encoded_username}/osu"

        try:
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                response = await http_client.get(
                    user_url,
                    headers={
                        "Authorization": f"Bearer {access_token.access_token}",
                    },
                )
        except httpx.RequestError as error:
            raise OsuNetworkError(
                "Could not reach osu! to request the user profile."
            ) from error

        if response.status_code == 404:
            raise OsuUserNotFoundError(
                f"osu! user '{normalized_username}' was not found."
            )
        if response.status_code in (401, 403):
            raise OsuAuthenticationError(
                f"osu! rejected the user-profile request with HTTP {response.status_code}."
            )
        if response.is_error:
            raise OsuApiError(
                f"osu! user-profile request failed with HTTP {response.status_code}."
            )

        return self._parse_user_profile(response)

    @staticmethod
    def _parse_user_profile(response: httpx.Response) -> OsuUserProfile:
        try:
            response_data: Any = response.json()
            user_id = response_data["id"]
            username = response_data["username"]
            country_code = response_data["country_code"]
            avatar_url = response_data["avatar_url"]
            statistics = response_data.get("statistics") or {}
            global_rank = statistics.get("global_rank")
            performance_points = statistics.get("pp")
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise OsuApiError(
                "osu! returned an invalid user-profile response."
            ) from error

        required_fields_are_valid = (
            isinstance(user_id, int)
            and not isinstance(user_id, bool)
            and isinstance(username, str)
            and bool(username)
            and isinstance(country_code, str)
            and bool(country_code)
            and isinstance(avatar_url, str)
            and bool(avatar_url)
        )
        global_rank_is_valid = global_rank is None or (
            isinstance(global_rank, int) and not isinstance(global_rank, bool)
        )
        performance_points_are_valid = performance_points is None or (
            isinstance(performance_points, (int, float))
            and not isinstance(performance_points, bool)
        )

        if not (
            required_fields_are_valid
            and global_rank_is_valid
            and performance_points_are_valid
        ):
            raise OsuApiError(
                "osu! returned an invalid user-profile response."
            )

        return OsuUserProfile(
            user_id=user_id,
            username=username,
            country_code=country_code,
            avatar_url=avatar_url,
            global_rank=global_rank,
            performance_points=(
                float(performance_points)
                if performance_points is not None
                else None
            ),
        )

    async def get_top_plays_by_username(
        self,
        username: str,
        limit: int = 100,
    ) -> list[OsuTopPlay]:
        """Fetch up to 100 best osu!standard scores for a username."""
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("Top-play limit must be an integer from 1 through 100.")

        user = await self.get_user_by_username(username)
        access_token = await self.request_access_token()
        scores_url = f"{OSU_API_BASE_URL}/users/{user.user_id}/scores/best"

        try:
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                response = await http_client.get(
                    scores_url,
                    params={"mode": "osu", "limit": limit},
                    headers={
                        "Authorization": f"Bearer {access_token.access_token}",
                    },
                )
        except httpx.RequestError as error:
            raise OsuNetworkError(
                "Could not reach osu! to request top plays."
            ) from error

        if response.status_code in (401, 403):
            raise OsuAuthenticationError(
                f"osu! rejected the top-play request with HTTP {response.status_code}."
            )
        if response.is_error:
            raise OsuApiError(
                f"osu! top-play request failed with HTTP {response.status_code}."
            )

        try:
            response_data: Any = response.json()
        except ValueError as error:
            raise OsuApiError("osu! returned an invalid top-play response.") from error

        if not isinstance(response_data, list):
            raise OsuApiError("osu! returned an invalid top-play response.")

        return [
            self._parse_top_play(raw_play, position)
            for position, raw_play in enumerate(response_data, start=1)
        ]

    @staticmethod
    def _parse_top_play(raw_play: Any, position: int) -> OsuTopPlay:
        if not isinstance(raw_play, dict):
            raise OsuApiError(
                f"osu! returned an invalid top play at position {position}."
            )

        beatmap = raw_play.get("beatmap") or {}
        beatmapset = raw_play.get("beatmapset") or {}
        if not isinstance(beatmap, dict) or not isinstance(beatmapset, dict):
            raise OsuApiError(
                f"osu! returned an invalid top play at position {position}."
            )

        score_id = raw_play.get("id")
        beatmap_id = raw_play.get("beatmap_id", beatmap.get("id"))
        beatmapset_id = beatmap.get("beatmapset_id", beatmapset.get("id"))
        artist = beatmapset.get("artist")
        title = beatmapset.get("title")
        difficulty_name = beatmap.get("version")
        performance_points = raw_play.get("pp")
        accuracy = raw_play.get("accuracy")
        grade = raw_play.get("rank")
        max_combo = raw_play.get("max_combo")
        played_at = raw_play.get("created_at", raw_play.get("ended_at"))
        star_rating = beatmap.get("difficulty_rating")
        approach_rate = beatmap.get("ar")
        bpm = beatmap.get("bpm")

        integer_fields = (score_id, beatmapset_id, max_combo)
        number_fields = (
            performance_points,
            accuracy,
            star_rating,
            approach_rate,
            bpm,
        )
        string_fields = (artist, title, difficulty_name, grade, played_at)

        fields_are_valid = (
            isinstance(beatmap_id, int)
            and not isinstance(beatmap_id, bool)
            and all(
                value is None
                or (isinstance(value, int) and not isinstance(value, bool))
                for value in integer_fields
            )
            and all(
                value is None
                or (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                )
                for value in number_fields
            )
            and all(value is None or isinstance(value, str) for value in string_fields)
        )
        if not fields_are_valid:
            raise OsuApiError(
                f"osu! returned an invalid top play at position {position}."
            )

        raw_mods = raw_play.get("mods") or []
        if not isinstance(raw_mods, list):
            raise OsuApiError(
                f"osu! returned invalid mods for top play at position {position}."
            )

        mods: list[str] = []
        for raw_mod in raw_mods:
            if isinstance(raw_mod, str) and raw_mod:
                mods.append(raw_mod)
            elif (
                isinstance(raw_mod, dict)
                and isinstance(raw_mod.get("acronym"), str)
                and raw_mod["acronym"]
            ):
                mods.append(raw_mod["acronym"])
            else:
                raise OsuApiError(
                    f"osu! returned invalid mods for top play at position {position}."
                )

        return OsuTopPlay(
            score_id=score_id,
            beatmap_id=beatmap_id,
            beatmapset_id=beatmapset_id,
            artist=artist,
            title=title,
            difficulty_name=difficulty_name,
            performance_points=(
                float(performance_points)
                if performance_points is not None
                else None
            ),
            accuracy=float(accuracy) if accuracy is not None else None,
            grade=grade,
            mods=tuple(mods),
            max_combo=max_combo,
            played_at=played_at,
            star_rating=float(star_rating) if star_rating is not None else None,
            approach_rate=(
                float(approach_rate) if approach_rate is not None else None
            ),
            bpm=float(bpm) if bpm is not None else None,
        )
