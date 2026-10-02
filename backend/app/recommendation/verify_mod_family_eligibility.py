"""Developer CLI for gameplay-mod-family similar-player eligibility."""

import argparse
import asyncio
import sys
from statistics import fmean

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.mod_family_eligibility_experiment import (
    ModFamilyEligibilityResult,
    evaluate_mod_family_eligibility,
)

TARGETS = ("molerat", "peppy", "mrekk", "Vaxei", "WhiteCat")


def _mods(value: tuple[str, ...]) -> str:
    return "".join(value) or "NM"


def _profile(value: object) -> str:
    return "NA" if value is None else f"{value.first_quartile:.2f}/{value.median:.2f}/{value.third_quartile:.2f}"


def print_result(result: ModFamilyEligibilityResult) -> None:
    print(
        f"RUN target={result.target_username} split={result.split_index} "
        f"style={_mods(result.target_exact_mods)}/{_mods(result.target_normalized_mods)} "
        f"target_share={result.target_normalized_share:.3f} "
        f"supply={result.eligible_count}/{result.hydrated_count}"
    )
    for name, summary, maps in (
        ("baseline", result.baseline_recovery, result.baseline_candidate_maps),
        ("eligible", result.eligible_recovery, result.eligible_candidate_maps),
    ):
        ranks = summary.recovered_rank_summary
        print(
            f"VIEW {name} maps={maps} recovered={summary.recovered_anywhere}/10 "
            f"r10={summary.recall_at_10:.3f} r30={summary.recall_at_30:.3f} "
            f"r50={summary.recall_at_50:.3f} r100={summary.recall_at_100:.3f} "
            f"median={ranks.median if ranks else 'NA'} mean={ranks.mean if ranks else 'NA'}"
        )
    if result.target_username.lower() == "molerat":
        for name, players in (("baseline", result.baseline_players), ("eligible", result.eligible_players)):
            for rank, player in enumerate(players, 1):
                print(
                    f"PLAYER view={name} rank={rank} original={player.baseline_rank} "
                    f"name={player.username or player.user_id} overlap={player.independent_overlap} "
                    f"exact={_mods(player.dominant_exact_mods)} normalized={_mods(player.dominant_normalized_mods)} "
                    f"share={player.target_normalized_share:.3f} ar={_profile(player.effective_ar)} "
                    f"bpm={_profile(player.effective_bpm)} pp={_profile(player.pp)}"
                )
    print(f"REQUESTS leaderboard={result.leaderboard_requests} hydration={result.hydration_requests} other=0")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username", nargs="?")
    parser.add_argument("--split-index", type=int)
    parser.add_argument("--all-fixed", action="store_true")
    args = parser.parse_args()
    if not args.all_fixed and (not args.username or args.split_index is None):
        parser.error("username and --split-index are required unless --all-fixed is used")
    client = OsuApiClient(OsuCredentials.from_environment())
    results: list[ModFamilyEligibilityResult] = []
    for target in TARGETS if args.all_fixed else (args.username,):
        for split_index in range(8) if args.all_fixed else (args.split_index,):
            result = await evaluate_mod_family_eligibility(target, split_index=split_index, osu_client=client)
            results.append(result)
            print_result(result)
    for label, group in (("ALL", results),) + tuple(
        (target, [item for item in results if item.target_username.lower() == target.lower()])
        for target in TARGETS
        if any(item.target_username.lower() == target.lower() for item in results)
    ):
        for variant in ("baseline_recovery", "eligible_recovery"):
            summaries = [getattr(item, variant) for item in group]
            print(
                f"AGGREGATE target={label} view={variant.removesuffix('_recovery')} "
                f"recovered={sum(item.recovered_anywhere for item in summaries)}/{sum(item.held_out_count for item in summaries)} "
                f"recall={fmean(item.recall_at_10 for item in summaries):.3f}/"
                f"{fmean(item.recall_at_30 for item in summaries):.3f}/"
                f"{fmean(item.recall_at_50 for item in summaries):.3f}/"
                f"{fmean(item.recall_at_100 for item in summaries):.3f}"
            )
        print(
            f"SUPPLY target={label} mean={fmean(item.eligible_count for item in group):.2f} "
            f"min={min(item.eligible_count for item in group)} max={max(item.eligible_count for item in group)}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as error:
        print(f"Experiment failed: {error}", file=sys.stderr)
        raise
