"""Developer CLI for the fixed T0053 allocation experiment."""

import argparse
import asyncio
import sys

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.allocation_mixture_experiment import (
    AllocationMixtureResult,
    evaluate_allocation_mixtures,
)

TARGETS = ("molerat", "peppy", "mrekk", "Vaxei", "WhiteCat")


def _mods(value: tuple[str, ...]) -> str:
    return "".join(value) or "NM"


def print_result(result: AllocationMixtureResult) -> None:
    print(f"RUN target={result.target_username} split={result.split_index} primary={_mods(result.target_primary_mods)}")
    for view in result.views:
        a, h, r = view.accounting, view.hydrated, view.recovery.preference_aware_summary
        combined10 = sum(x.target_primary_mod_share >= .5 and x.pp_iqr_overlaps is True for x in view.features[:10])
        print(f"VIEW {view.name} requested={a.requested_baseline}/{a.requested_target_mod} composition={a.baseline_only}/{a.target_mod_only}/{a.present_in_both_pools} duplicate={a.duplicates_skipped} backfill={a.baseline_backfill} hydrated={a.final_unique} pool_overlap={h.mean_overlap:.2f}/{h.median_overlap:.2f} pool_mod={h.mod_positive}/{h.mod_ge25}/{h.mod_ge50} pool_pp={h.pp_overlap} pool_both={h.both} top10_overlap={view.top10.mean_independent_overlap:.2f}/{view.top10.median_independent_overlap:.2f}/{view.top10.minimum_independent_overlap} top10_mod={view.top10.mean_mod_share:.3f}/{view.top10.median_mod_share:.3f}/{view.top10.mod_share_at_least_half} top10_pp={view.top10.pp_iqr_overlap} top10_both={combined10} top10_sources={view.top10_sources.baseline_phase}/{view.top10_sources.target_mod_phase}/{view.top10_sources.baseline_backfill}/{view.top10_sources.present_in_both_pools} top15_sources={view.top15_sources.baseline_phase}/{view.top15_sources.target_mod_phase}/{view.top15_sources.baseline_backfill}/{view.top15_sources.present_in_both_pools} placement={view.target_mod_placement.ranks_1_10}/{view.target_mod_placement.ranks_11_15}/{view.target_mod_placement.below_15} candidates={view.recovery.candidate_map_count} recovered={r.recovered_anywhere}/{r.held_out_count} r10={r.recall_at_10:.3f} r30={r.recall_at_30:.3f} r50={r.recall_at_50:.3f} r100={r.recall_at_100:.3f} median={r.recovered_rank_summary.median if r.recovered_rank_summary else 'NA'} mean={r.recovered_rank_summary.mean if r.recovered_rank_summary else 'NA'}")
        if result.target_username.lower() == "molerat" and result.split_index == 0:
            by_id = {item.candidate.user_id: item for item in view.allocated}
            for rank, item in enumerate(view.features[:10], 1):
                allocated = by_id[item.user_id]
                pp = item.pp
                print(f"PLAYER {view.name} {rank} {item.username} source={allocated.allocation_source} in_mod={allocated.present_in_target_mod_source} overlap={item.independent_overlap} mods={_mods(item.dominant_mods)} share={item.target_primary_mod_share:.3f} median_pp={pp.median if pp else 'NA'} pp_overlap={item.pp_iqr_overlaps}")
    print(f"REQUESTS baseline_leaderboard={result.baseline_leaderboard_requests} target_mod_leaderboard={result.target_mod_leaderboard_requests} logical_hydration={result.logical_hydration_requests} actual_hydration={result.actual_hydration_requests} avoided={result.logical_hydration_requests-result.actual_hydration_requests}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username", nargs="?")
    parser.add_argument("--split-index", type=int, default=0)
    parser.add_argument("--all-fixed", action="store_true")
    args = parser.parse_args()
    if not args.all_fixed and not args.username:
        parser.error("username is required unless --all-fixed is used")
    client = OsuApiClient(OsuCredentials.from_environment())
    for target in TARGETS if args.all_fixed else (args.username,):
        for split_index in range(3) if args.all_fixed else (args.split_index,):
            print_result(await evaluate_allocation_mixtures(target, split_index=split_index, osu_client=client))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as error:
        print(f"Experiment failed: {error}", file=sys.stderr)
        raise
