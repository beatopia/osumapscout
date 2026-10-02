"""Developer CLI for the HD-normalized mod-family acquisition pilot."""

import argparse
import asyncio
import sys
from statistics import fmean

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.mod_family_eligibility_experiment import (
    PlayerModCompatibility,
)
from backend.app.recommendation.normalized_mod_acquisition_experiment import (
    NormalizedModAcquisitionResult,
    evaluate_normalized_mod_acquisition,
)

TARGETS = ("molerat", "peppy", "mrekk", "Vaxei", "WhiteCat")


def _mods(value: tuple[str, ...]) -> str:
    return "".join(value) or "NM"


def _player(item: PlayerModCompatibility) -> str:
    effective_ar = item.effective_ar.median if item.effective_ar else "NA"
    effective_bpm = item.effective_bpm.median if item.effective_bpm else "NA"
    pp = item.pp.median if item.pp else "NA"
    return (
        f"rank={item.baseline_rank} name={item.username or item.user_id} "
        f"overlap={item.independent_overlap} exact={_mods(item.dominant_exact_mods)} "
        f"normalized={_mods(item.dominant_normalized_mods)} "
        f"share={item.target_normalized_share:.3f} ar={effective_ar} "
        f"bpm={effective_bpm} pp={pp} eligible={item.eligible}"
    )


def print_result(result: NormalizedModAcquisitionResult, *, players: bool) -> None:
    print(
        f"RUN target={result.target_username} split={result.split_index} "
        f"family={_mods(result.target_normalized_mods)} "
        f"target_share={result.target_normalized_share:.3f} "
        f"calibrated_min={result.calibrated_minimum_share:.3f} "
        f"queries={','.join(_mods(value) for value in result.queried_mods)} "
        f"acquired={result.acquired_users} hydrated={result.hydrated_users} "
        f"eligible={result.eligible_users} calibrated={result.calibrated_eligible_users} "
        f"effective_range={result.effective_range_eligible_users}"
    )
    if players:
        for item in result.players:
            print(f"PLAYER {_player(item)}")
    for label, summary in (
        ("source", result.source_recovery),
        ("eligible", result.eligible_recovery),
        ("calibrated", result.calibrated_recovery),
        ("effective_range", result.effective_range_recovery),
        ("effective_map", result.effective_map_recovery),
        ("effective_map_eligible", result.effective_map_eligible_recovery),
        ("behavior_first", result.behavior_first_recovery),
    ):
        print(
            f"VIEW {label} recovered={summary.recovered_anywhere}/10 "
            f"recall={summary.recall_at_10:.3f}/{summary.recall_at_30:.3f}/"
            f"{summary.recall_at_50:.3f}/{summary.recall_at_100:.3f}"
        )
    print(
        f"REQUESTS leaderboard={result.leaderboard_requests} "
        f"hydration={result.hydration_requests}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username", nargs="?")
    parser.add_argument("--split-index", type=int)
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--out-of-sample", action="store_true")
    args = parser.parse_args()
    if args.matrix and args.out_of_sample:
        parser.error("Choose only one matrix range")
    if not (args.matrix or args.out_of_sample) and (
        not args.username or args.split_index is None
    ):
        parser.error("username and --split-index are required unless a matrix is used")
    client = OsuApiClient(OsuCredentials.from_environment())
    results: list[NormalizedModAcquisitionResult] = []
    targets = TARGETS if args.matrix or args.out_of_sample else (args.username,)
    splits = range(3, 8) if args.out_of_sample else range(3) if args.matrix else (args.split_index,)
    for target in targets:
        for split_index in splits:
            result = await evaluate_normalized_mod_acquisition(
                target, split_index=split_index, osu_client=client
            )
            results.append(result)
            print_result(result, players=result.target_username.lower() == "molerat")
    for label, group in (("ALL", results),) + tuple(
        (target, [item for item in results if item.target_username.lower() == target.lower()])
        for target in TARGETS
        if any(item.target_username.lower() == target.lower() for item in results)
    ):
        for view in (
            "source_recovery",
            "eligible_recovery",
            "calibrated_recovery",
            "effective_range_recovery",
            "effective_map_recovery",
            "effective_map_eligible_recovery",
            "behavior_first_recovery",
        ):
            summaries = [getattr(item, view) for item in group]
            print(
                f"AGGREGATE target={label} view={view.removesuffix('_recovery')} "
                f"recovered={sum(item.recovered_anywhere for item in summaries)}/"
                f"{sum(item.held_out_count for item in summaries)} "
                f"recall={fmean(item.recall_at_10 for item in summaries):.3f}/"
                f"{fmean(item.recall_at_30 for item in summaries):.3f}/"
                f"{fmean(item.recall_at_50 for item in summaries):.3f}/"
                f"{fmean(item.recall_at_100 for item in summaries):.3f}"
            )
        print(
            f"SUPPLY target={label} mean={fmean(item.eligible_users for item in group):.2f} "
            f"min={min(item.eligible_users for item in group)} "
            f"max={max(item.eligible_users for item in group)}"
        )
        print(
            f"CALIBRATED_SUPPLY target={label} "
            f"mean={fmean(item.calibrated_eligible_users for item in group):.2f} "
            f"min={min(item.calibrated_eligible_users for item in group)} "
            f"max={max(item.calibrated_eligible_users for item in group)}"
        )
        print(
            f"RANGE_SUPPLY target={label} "
            f"mean={fmean(item.effective_range_eligible_users for item in group):.2f} "
            f"min={min(item.effective_range_eligible_users for item in group)} "
            f"max={max(item.effective_range_eligible_users for item in group)}"
        )
        print(
            f"MAP_ELIGIBLE_SUPPLY target={label} "
            f"mean={fmean(item.effective_map_eligible_count for item in group):.2f} "
            f"min={min(item.effective_map_eligible_count for item in group)} "
            f"max={max(item.effective_map_eligible_count for item in group)}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as error:
        print(f"Experiment failed: {error}", file=sys.stderr)
        raise
