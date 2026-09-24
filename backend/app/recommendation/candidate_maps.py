"""Extract candidate maps from already-hydrated similar-player evidence."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from backend.app.osu.client import OsuApiClient, OsuTopPlay
from backend.app.similarity.ranked_candidates import (
    RankedCandidateExperimentResult,
    RankedSimilarPlayer,
    evaluate_ranked_candidates,
)

RankingFunction = Callable[..., Awaitable[RankedCandidateExperimentResult]]


@dataclass(frozen=True)
class CandidateMapSupport:
    user_id: int
    username: str | None
    similar_player_rank: int
    independent_shared_count: int
    mods: tuple[str, ...]
    performance_points: float | None


@dataclass(frozen=True)
class CandidateMap:
    beatmap_id: int
    artist: str | None
    title: str | None
    difficulty_name: str | None
    supports: tuple[CandidateMapSupport, ...]

    @property
    def support_count(self) -> int:
        return len(self.supports)

    @property
    def best_supporting_player_rank(self) -> int:
        return self.supports[0].similar_player_rank

    @property
    def supporting_player_ids(self) -> tuple[int, ...]:
        return tuple(support.user_id for support in self.supports)

    @property
    def supporting_usernames(self) -> tuple[str | None, ...]:
        return tuple(support.username for support in self.supports)


@dataclass(frozen=True)
class SimilarPlayerContribution:
    user_id: int
    username: str | None
    similar_player_rank: int
    candidate_map_count: int


@dataclass(frozen=True)
class CandidateMapSummary:
    candidate_map_count: int
    one_or_more_support_count: int
    two_or_more_support_count: int
    three_or_more_support_count: int
    five_or_more_support_count: int
    maximum_support_count: int


@dataclass(frozen=True)
class CandidateMapExperimentResult:
    target_user_id: int
    target_username: str
    target_top_play_count: int
    hydration_budget: int
    similar_players_hydrated: int
    similar_players_selected: int
    leaderboard_requests_made: int
    top_play_requests_made: int
    additional_extraction_requests: int
    contributions: tuple[SimilarPlayerContribution, ...]
    candidate_maps: tuple[CandidateMap, ...]
    summary: CandidateMapSummary


@dataclass
class _CandidateMapAccumulator:
    beatmap_id: int
    artist: str | None
    title: str | None
    difficulty_name: str | None
    supports: list[CandidateMapSupport]


def extract_candidate_maps(
    ranking: RankedCandidateExperimentResult,
    similar_player_limit: int,
) -> CandidateMapExperimentResult:
    """Build a candidate-map pool without performing external work."""
    _validate_bound(similar_player_limit, 1, 25, "Similar-player limit")
    selected_players = ranking.candidates[:similar_player_limit]
    target_ids = frozenset(ranking.target_beatmap_ids)
    accumulated: dict[int, _CandidateMapAccumulator] = {}
    contributions: list[SimilarPlayerContribution] = []

    for similar_player_rank, player in enumerate(selected_players, start=1):
        contributed_ids: set[int] = set()
        for play in player.hydrated_top_plays:
            if play.beatmap_id in target_ids:
                continue
            existing = accumulated.get(play.beatmap_id)
            if play.beatmap_id in contributed_ids:
                if existing is not None:
                    _fill_missing_metadata(existing, play)
                continue
            contributed_ids.add(play.beatmap_id)
            support = _support_from_play(player, similar_player_rank, play)
            if existing is None:
                accumulated[play.beatmap_id] = _CandidateMapAccumulator(
                    beatmap_id=play.beatmap_id,
                    artist=play.artist,
                    title=play.title,
                    difficulty_name=play.difficulty_name,
                    supports=[support],
                )
            else:
                _fill_missing_metadata(existing, play)
                existing.supports.append(support)
        contributions.append(
            SimilarPlayerContribution(
                user_id=player.user_id,
                username=player.username,
                similar_player_rank=similar_player_rank,
                candidate_map_count=len(contributed_ids),
            )
        )

    candidate_maps = tuple(
        CandidateMap(
            beatmap_id=item.beatmap_id,
            artist=item.artist,
            title=item.title,
            difficulty_name=item.difficulty_name,
            supports=tuple(item.supports),
        )
        for item in accumulated.values()
    )
    ordered_maps = tuple(
        sorted(
            candidate_maps,
            key=lambda item: (
                -item.support_count,
                item.best_supporting_player_rank,
                item.beatmap_id,
            ),
        )
    )
    support_counts = [item.support_count for item in ordered_maps]
    summary = CandidateMapSummary(
        candidate_map_count=len(ordered_maps),
        one_or_more_support_count=sum(value >= 1 for value in support_counts),
        two_or_more_support_count=sum(value >= 2 for value in support_counts),
        three_or_more_support_count=sum(value >= 3 for value in support_counts),
        five_or_more_support_count=sum(value >= 5 for value in support_counts),
        maximum_support_count=max(support_counts, default=0),
    )
    return CandidateMapExperimentResult(
        target_user_id=ranking.target_user_id,
        target_username=ranking.target_username,
        target_top_play_count=ranking.target_play_count,
        hydration_budget=ranking.hydration_budget,
        similar_players_hydrated=ranking.total_hydrated,
        similar_players_selected=len(selected_players),
        leaderboard_requests_made=ranking.leaderboard_requests_made,
        top_play_requests_made=ranking.top_play_requests_made,
        additional_extraction_requests=0,
        contributions=tuple(contributions),
        candidate_maps=ordered_maps,
        summary=summary,
    )


async def evaluate_candidate_maps(
    username: str,
    *,
    seed_count: int = 5,
    hydration_budget: int = 25,
    top_plays: int = 100,
    similar_player_limit: int = 10,
    ranking_function: RankingFunction = evaluate_ranked_candidates,
    osu_client: OsuApiClient | None = None,
) -> CandidateMapExperimentResult:
    """Run T0025 once, then extract maps from its retained evidence."""
    _validate_bound(similar_player_limit, 1, 25, "Similar-player limit")
    arguments: dict[str, object] = {
        "seed_count": seed_count,
        "hydration_budget": hydration_budget,
        "top_plays": top_plays,
    }
    if osu_client is not None:
        arguments["osu_client"] = osu_client
    ranking = await ranking_function(username, **arguments)
    return extract_candidate_maps(ranking, similar_player_limit)


def validate_show_maps(show_maps: int) -> None:
    _validate_bound(show_maps, 1, 100, "Show-maps limit")


def _support_from_play(
    player: RankedSimilarPlayer,
    similar_player_rank: int,
    play: OsuTopPlay,
) -> CandidateMapSupport:
    return CandidateMapSupport(
        user_id=player.user_id,
        username=player.username,
        similar_player_rank=similar_player_rank,
        independent_shared_count=player.seed_excluded_shared_beatmap_count,
        mods=play.mods,
        performance_points=play.performance_points,
    )


def _fill_missing_metadata(
    candidate_map: _CandidateMapAccumulator,
    play: OsuTopPlay,
) -> None:
    if candidate_map.artist is None and play.artist is not None:
        candidate_map.artist = play.artist
    if candidate_map.title is None and play.title is not None:
        candidate_map.title = play.title
    if (
        candidate_map.difficulty_name is None
        and play.difficulty_name is not None
    ):
        candidate_map.difficulty_name = play.difficulty_name


def _validate_bound(value: int, minimum: int, maximum: int, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f"{label} must be an integer from {minimum} through {maximum}."
        )
