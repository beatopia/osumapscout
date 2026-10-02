"""Developer CLI for the bounded T0050 acquisition experiment."""

import argparse
import asyncio
import sys

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.candidate_acquisition_experiment import (
    AcquisitionViewResult,
    CandidateAcquisitionResult,
    evaluate_candidate_acquisition,
)

TARGETS = ("molerat", "peppy", "mrekk", "Vaxei", "WhiteCat")


def _mods(value: tuple[str, ...]) -> str:
    return "".join(value) or "NM"


def print_result(result: CandidateAcquisitionResult) -> None:
    print(f"RUN target={result.target_username} split={result.split_index} primary={_mods(result.target_primary_mods)}")
    print(f"PERFORMANCE target_rank={result.target_global_rank} target_profile_pp={result.target_profile_pp} pages={result.ranking_pages} rank_range={result.ranking_candidate_rank_range} profile_pp_range={result.ranking_candidate_pp_range}")
    for seed in result.mod_seeds:
        print(f"MOD_SEED beatmap={seed.beatmap_id} mods={_mods(seed.mods)} rows={seed.score_rows} unique={seed.unique_users}")
    for view in result.views:
        _print_view(view, result.target_username.lower() == "molerat")
    print(f"REQUESTS logical_leaderboard={result.logical_leaderboard_requests} logical_ranking={result.logical_ranking_requests} logical_top_play={result.logical_top_play_requests} actual_top_play={result.actual_top_play_requests}")


def _print_view(view: AcquisitionViewResult, show_players: bool) -> None:
    a, h, r = view.acquisition, view.hydrated, view.recovery.preference_aware_summary
    print(f"VIEW {view.name} raw={a.raw_users} unique={a.unique_users} recurring={a.recurring_users} hydrated={a.selected_users} sources={a.source_both}/{a.source_mod_only}/{a.source_performance_only} overlap={h.mean_overlap:.2f}/{h.median_overlap:.2f} overlap_counts={h.overlap_zero}/{h.overlap_ge1}/{h.overlap_ge2}/{h.overlap_ge5} mod={h.mod_positive}/{h.mod_ge25}/{h.mod_ge50} pp_overlap={h.pp_overlap} both={h.both} top10_mod={view.top10.mean_mod_share:.3f}/{view.top10.median_mod_share:.3f}/{view.top10.mod_share_at_least_half} top10_pp={view.top10.pp_iqr_overlap} top10_both={sum(x.target_primary_mod_share>=.5 and x.pp_iqr_overlaps is True for x in view.features[:10])} top10_pp_distance={view.top10.mean_median_pp_distance} top10_overlap={view.top10.mean_independent_overlap:.2f}/{view.top10.median_independent_overlap:.2f}/{view.top10.minimum_independent_overlap} candidates={view.recovery.candidate_map_count} recovered={r.recovered_anywhere}/{r.held_out_count} r10={r.recall_at_10:.3f} r30={r.recall_at_30:.3f} r50={r.recall_at_50:.3f} r100={r.recall_at_100:.3f} median={r.recovered_rank_summary.median if r.recovered_rank_summary else 'NA'} mean={r.recovered_rank_summary.mean if r.recovered_rank_summary else 'NA'}")
    if show_players:
        sources = dict(view.sources)
        for rank, item in enumerate(view.features[:10], 1):
            pp = item.pp
            iqr = f"{pp.first_quartile:.2f}-{pp.third_quartile:.2f}" if pp else "NA"
            print(f"PLAYER {view.name} {rank} {item.username} source={sources[item.user_id]} overlap={item.independent_overlap} mods={_mods(item.dominant_mods)} hdhr={item.target_primary_mod_share:.3f} median_pp={pp.median if pp else 'NA'} iqr={iqr} pp_overlap={item.pp_iqr_overlaps}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username", nargs="?")
    parser.add_argument("--split-index", type=int, default=0)
    parser.add_argument("--all-fixed", action="store_true")
    args = parser.parse_args()
    client = OsuApiClient(OsuCredentials.from_environment())
    targets = TARGETS if args.all_fixed else (args.username,)
    if not args.all_fixed and not args.username:
        parser.error("username is required unless --all-fixed is used")
    for target in targets:
        indexes = range(3) if args.all_fixed else (args.split_index,)
        for split_index in indexes:
            print_result(await evaluate_candidate_acquisition(target, split_index=split_index, osu_client=client))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as error:
        print(f"Experiment failed: {error}", file=sys.stderr)
        raise
