"""Developer CLI for the T0055 effective AR/BPM experiment."""

import argparse
import asyncio
import sys
from statistics import fmean

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.effective_attributes import effective_attributes
from backend.app.recommendation.effective_preference_experiment import (
    EffectivePreferenceResult,
    evaluate_effective_preferences,
)

TARGETS = ("molerat", "peppy", "mrekk", "Vaxei", "WhiteCat")


def _summary(value: object) -> str:
    return "NA" if value is None else f"{value.first_quartile:.3f}/{value.median:.3f}/{value.third_quartile:.3f}"


def print_result(result: EffectivePreferenceResult) -> None:
    profile = result.profile
    print(
        f"RUN target={result.target_username} split={result.split_index} "
        f"primary={''.join(profile.base.top_exact_mod_combination or ()) or 'NM'} "
        f"base_ar={_summary(profile.base.approach_rate)} effective_ar={_summary(profile.effective_ar)} "
        f"base_bpm={_summary(profile.base.bpm)} effective_bpm={_summary(profile.effective_bpm)} "
        f"rates={'/'.join(f'{rate}:{count}' for rate, count in profile.clock_rates)}"
    )
    for name, ordering, recovery, diagnostics in (
        ("base_attributes", result.base_ordering, result.base_summary, result.base_classification),
        ("effective_ar_bpm", result.effective_ordering, result.effective_summary, result.effective_classification),
    ):
        ranks = recovery.recovered_rank_summary
        print(
            f"VIEW {name} candidates={len(ordering)} recovered={recovery.recovered_anywhere}/10 "
            f"r10={recovery.recall_at_10:.3f} r30={recovery.recall_at_30:.3f} "
            f"r50={recovery.recall_at_50:.3f} r100={recovery.recall_at_100:.3f} "
            f"median={ranks.median if ranks else 'NA'} mean={ranks.mean if ranks else 'NA'} "
            f"class={diagnostics.ar_within}/{diagnostics.bpm_within}/{diagnostics.both_within}"
        )
    print("PLACEMENT " + " ".join(
        f"{item.beatmap_id}:{item.original_position}:{item.base_rank}>{item.effective_rank}:{item.movement}"
        for item in result.placement_transitions
    ))
    print("CUTOFFS " + " ".join(
        f"{item.cutoff}:{item.crossed_in}/{item.crossed_out}"
        for item in result.cutoff_transitions
    ))
    print("STABILITY " + " ".join(f"{limit}:{value:.3f}" for limit, value in result.top_overlap))
    changes = result.classification_changes
    print(f"CHANGES ar={changes.ar_only} bpm={changes.bpm_only} both={changes.both} unchanged={changes.unchanged}")
    if result.target_username.lower() == "molerat" and result.split_index == 0:
        for name, ordering in (("base", result.base_ordering), ("effective", result.effective_ordering)):
            for rank, item in enumerate(ordering[:20], 1):
                evidence = item.preference_evidence
                candidate = evidence.collaborative.candidate_map
                adjusted = effective_attributes(candidate.approach_rate, candidate.bpm, profile.base.top_exact_mod_combination or ())
                print(
                    f"MAP {name} rank={rank} id={candidate.beatmap_id} ar={candidate.approach_rate}/"
                    f"{adjusted.effective_ar} bpm={candidate.bpm}/{adjusted.effective_bpm} "
                    f"fit={evidence.approach_rate.within_target_iqr}/{evidence.bpm.within_target_iqr} "
                    f"support={evidence.collaborative.support_count}"
                )
    for play in result.held_out[:2]:
        adjusted = effective_attributes(play.approach_rate, play.bpm, play.mods)
        print(
            f"PLAY user={result.target_username} id={play.beatmap_id} mods={''.join(play.mods) or 'NM'} "
            f"ar={play.approach_rate}/{adjusted.effective_ar} bpm={play.bpm}/{adjusted.effective_bpm}"
        )
    print(
        f"REQUESTS leaderboard={result.leaderboard_requests} hydration={result.hydration_requests} "
        f"other={result.other_osu_requests} effective_calculations=local"
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
    results: list[EffectivePreferenceResult] = []
    for target in TARGETS if args.all_fixed else (args.username,):
        for split_index in range(8) if args.all_fixed else (args.split_index,):
            result = await evaluate_effective_preferences(target, split_index=split_index, osu_client=client)
            results.append(result)
            print_result(result)
    for label, group in (("ALL", results),) + tuple(
        (target, [item for item in results if item.target_username.lower() == target.lower()])
        for target in TARGETS
        if any(item.target_username.lower() == target.lower() for item in results)
    ):
        values = []
        for variant in ("base_summary", "effective_summary"):
            summaries = [getattr(item, variant) for item in group]
            values.append(
                f"{variant.removesuffix('_summary')}="
                f"{sum(item.recovered_anywhere for item in summaries)}/{sum(item.held_out_count for item in summaries)}:"
                f"{fmean(item.recall_at_10 for item in summaries):.3f}/"
                f"{fmean(item.recall_at_30 for item in summaries):.3f}/"
                f"{fmean(item.recall_at_50 for item in summaries):.3f}/"
                f"{fmean(item.recall_at_100 for item in summaries):.3f}"
            )
        print(f"AGGREGATE {label} {' '.join(values)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as error:
        print(f"Experiment failed: {error}", file=sys.stderr)
        raise
