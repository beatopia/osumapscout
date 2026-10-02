"""Developer CLI for the T0054 fixed out-of-sample validation matrix."""

import argparse
import asyncio
import sys

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.hybrid_acquisition_validation import (
    HybridValidationResult,
    evaluate_hybrid_validation,
)

TARGETS = ("molerat", "peppy", "mrekk", "Vaxei", "WhiteCat")
SPLITS = (3, 4, 5, 6, 7)


def _mods(value: tuple[str, ...]) -> str:
    return "".join(value) or "NM"


def print_result(result: HybridValidationResult) -> None:
    signals = result.source_signals
    pp = signals.target_pp
    print(
        f"RUN target={result.target_username} split={result.split_index} "
        f"primary={_mods(result.target_primary_mods)} primary_share={signals.target_primary_mod_share:.3f} "
        f"pp={pp.first_quartile if pp else 'NA'}/{pp.median if pp else 'NA'}/{pp.third_quartile if pp else 'NA'} "
        f"sources={signals.baseline_candidates}/{signals.target_mod_candidates}/"
        f"{signals.source_intersection}/{signals.source_intersection_rate:.4f} "
        f"mod_recurring={signals.target_mod_recurring}"
    )
    print("SEEDS " + " ".join(
        f"{item.beatmap_id}:{item.score_rows}/{item.unique_users}"
        for item in signals.target_mod_seeds
    ))
    for view in (result.baseline, result.hybrid):
        summary = view.recovery.preference_aware_summary
        rank = summary.recovered_rank_summary
        top10_both = sum(
            item.target_primary_mod_share >= .5 and item.pp_iqr_overlaps is True
            for item in view.features[:10]
        )
        print(
            f"VIEW {view.name} recovered={summary.recovered_anywhere}/{summary.held_out_count} "
            f"r10={summary.recall_at_10:.3f} r30={summary.recall_at_30:.3f} "
            f"r50={summary.recall_at_50:.3f} r100={summary.recall_at_100:.3f} "
            f"median={rank.median if rank else 'NA'} mean={rank.mean if rank else 'NA'} "
            f"pool_compat={view.hydrated.mod_ge50}/{view.hydrated.pp_overlap}/{view.hydrated.both} "
            f"top10_compat={view.top10.mod_share_at_least_half}/{view.top10.pp_iqr_overlap}/{top10_both} "
            f"top10_overlap={view.top10.mean_independent_overlap:.2f}/"
            f"{view.top10.median_independent_overlap:.2f}/{view.top10.minimum_independent_overlap}"
        )
    print(
        f"COMPARE recovered={result.comparison.recovered_anywhere} "
        f"r10={result.comparison.recall_at_10} r30={result.comparison.recall_at_30} "
        f"r50={result.comparison.recall_at_50} r100={result.comparison.recall_at_100}"
    )
    by_id = {item.candidate.user_id: item for item in result.hybrid.allocated}
    ranks = {item.user_id: rank for rank, item in enumerate(result.hybrid.features, 1)}
    for user_id, item in by_id.items():
        if item.allocation_source != "target_mod":
            continue
        feature = result.hybrid.features[ranks[user_id] - 1]
        print(
            f"PLAYER id={user_id} name={feature.username} rank={ranks[user_id]} "
            f"overlap={feature.independent_overlap} mods={_mods(feature.dominant_mods)} "
            f"share={feature.target_primary_mod_share:.3f} "
            f"median_pp={feature.pp.median if feature.pp else 'NA'} "
            f"pp_overlap={feature.pp_iqr_overlaps}"
        )
    for transition in result.transitions:
        print(
            f"TRANSITION kind={transition.kind} beatmap={transition.beatmap_id} "
            f"position={transition.original_position} cause={transition.cause}"
        )
    print(
        f"REQUESTS baseline={result.baseline_leaderboard_requests} "
        f"target_mod={result.target_mod_leaderboard_requests} "
        f"logical_hydration={result.logical_hydration_requests} "
        f"actual_hydration={result.actual_hydration_requests} "
        f"avoided={result.logical_hydration_requests-result.actual_hydration_requests}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username", nargs="?")
    parser.add_argument("--split-index", type=int)
    parser.add_argument("--all-fixed", action="store_true")
    args = parser.parse_args()
    if not args.all_fixed and (not args.username or args.split_index is None):
        parser.error("username and --split-index are required unless --all-fixed is used")
    client = OsuApiClient(OsuCredentials.from_environment())
    targets = TARGETS if args.all_fixed else (args.username,)
    splits = SPLITS if args.all_fixed else (args.split_index,)
    for target in targets:
        for split_index in splits:
            print_result(await evaluate_hybrid_validation(
                target, split_index=split_index, osu_client=client
            ))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as error:
        print(f"Experiment failed: {error}", file=sys.stderr)
        raise
