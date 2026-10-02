"""CLI for sequential T0049 compatibility runs."""
import argparse
import asyncio
from statistics import fmean
from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.player_compatibility_experiment import PlayerCompatibilityResult, VIEW_NAMES, evaluate_player_compatibility

TARGETS = ("molerat", "peppy", "mrekk", "Vaxei", "WhiteCat")

def _mods(value: tuple[str, ...]) -> str:
    return "".join(value) or "NM"

def print_result(result: PlayerCompatibilityResult) -> None:
    pool = result.hydrated_pool
    print(f"RUN target={result.target_username} split={result.split_index} primary={_mods(result.target_primary_mods)}")
    print(f"POOL positive={sum(x.target_primary_mod_share>0 for x in pool)} ge25={sum(x.target_primary_mod_share>=.25 for x in pool)} ge50={sum(x.target_primary_mod_share>=.5 for x in pool)} pp_overlap={sum(x.pp_iqr_overlaps is True for x in pool)} both={sum(x.target_primary_mod_share>=.5 and x.pp_iqr_overlaps is True for x in pool)}")
    baseline = result.views[0]
    for view in result.views:
        r = view.recovery; ranks = r.recovered_rank_summary
        overlap = len({x.user_id for x in view.ordered_players[:10]} & {x.user_id for x in baseline.ordered_players[:10]})
        print(f"VIEW {view.name} candidates={view.candidate_map_count} recovered={r.recovered_anywhere}/{r.held_out_count} r10={r.recall_at_10:.3f} r30={r.recall_at_30:.3f} r50={r.recall_at_50:.3f} r100={r.recall_at_100:.3f} median={ranks.median if ranks else 'NA'} mean={ranks.mean if ranks else 'NA'} top10_overlap={overlap} mod_mean={view.top10.mean_mod_share:.3f} mod_median={view.top10.median_mod_share:.3f} mod50={view.top10.mod_share_at_least_half} pp_overlap={view.top10.pp_iqr_overlap} pp_distance_mean={view.top10.mean_median_pp_distance} overlap_mean={view.top10.mean_independent_overlap:.2f} overlap_median={view.top10.median_independent_overlap:.2f} overlap_min={view.top10.minimum_independent_overlap}")
        if result.target_username.lower() == "molerat":
            for rank, item in enumerate(view.ordered_players[:10], 1):
                pp = item.pp
                iqr = f"{pp.first_quartile:.2f}-{pp.third_quartile:.2f}" if pp else "NA"
                print(f"PLAYER {view.name} {rank} {item.username} base={item.baseline_rank} overlap={item.independent_overlap} mods={_mods(item.dominant_mods)} share={item.target_primary_mod_share:.3f} median_pp={pp.median if pp else 'NA'} iqr={iqr} pp_overlap={item.pp_iqr_overlaps}")
    print(f"REQUESTS leaderboard={result.leaderboard_requests} top_play={result.top_play_requests} views_extra=0")

async def _run(username: str|None, split_index: int|None, all_fixed: bool) -> int:
    client = OsuApiClient(OsuCredentials.from_environment()); results=[]
    pairs = [(t,s) for t in TARGETS for s in range(3)] if all_fixed else [(username or "", split_index or 0)]
    for target, split in pairs:
        result = await evaluate_player_compatibility(target, split_index=split, osu_client=client)
        results.append(result); print_result(result)
    if all_fixed:
        print("AGGREGATE")
        for name in VIEW_NAMES:
            views=[next(v for v in x.views if v.name==name) for x in results]; total=sum(v.recovery.held_out_count for v in views); recovered=sum(v.recovery.recovered_anywhere for v in views)
            print(f"AGG {name} recovered={recovered}/{total} r10={fmean(v.recovery.recall_at_10 for v in views):.3f} r30={fmean(v.recovery.recall_at_30 for v in views):.3f} r50={fmean(v.recovery.recall_at_50 for v in views):.3f} r100={fmean(v.recovery.recall_at_100 for v in views):.3f} candidates_mean={fmean(v.candidate_map_count for v in views):.2f} mod_mean={fmean(v.top10.mean_mod_share for v in views):.3f} pp_overlap_mean={fmean(v.top10.pp_iqr_overlap for v in views):.2f} overlap_mean={fmean(v.top10.mean_independent_overlap for v in views):.2f}")
    return 0

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("username",nargs="?"); parser.add_argument("--split-index",type=int,choices=range(3)); parser.add_argument("--all-fixed",action="store_true"); args=parser.parse_args()
    if not args.all_fixed and (args.username is None or args.split_index is None): parser.error("username and --split-index are required without --all-fixed")
    return asyncio.run(_run(args.username,args.split_index,args.all_fixed))

if __name__ == "__main__": raise SystemExit(main())
