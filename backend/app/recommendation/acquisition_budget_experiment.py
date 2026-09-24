"""Developer-only sensitivity experiment for existing acquisition budgets."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Literal

from backend.app.osu.client import OsuApiClient, OsuCredentials
from backend.app.recommendation.holdout_recovery import (
    HoldoutRecoveryExperimentResult,
    OrderingRecoverySummary,
    evaluate_holdout_recovery,
)

ExperimentFunction = Callable[..., Awaitable[HoldoutRecoveryExperimentResult]]
TransitionCause = Literal[
    "baseline_recovered",
    "selected_limit_gain",
    "hydration_budget_gain",
    "still_absent",
    "unattributed_change",
]


@dataclass(frozen=True)
class AcquisitionBudgetConfiguration:
    label: str
    hydration_budget: int
    similar_player_limit: int


BUDGET_CONFIGURATIONS = (
    AcquisitionBudgetConfiguration("25/10", 25, 10),
    AcquisitionBudgetConfiguration("25/15", 25, 15),
    AcquisitionBudgetConfiguration("40/15", 40, 15),
)


@dataclass(frozen=True)
class HeldOutBudgetTransition:
    position: int
    beatmap_id: int
    baseline_stage: str
    selected_limit_stage: str
    hydration_budget_stage: str
    baseline_preference_rank: int | None
    selected_limit_preference_rank: int | None
    hydration_budget_preference_rank: int | None
    cause: TransitionCause


@dataclass(frozen=True)
class AcquisitionBudgetExperimentResult:
    split_index: int
    configurations: tuple[AcquisitionBudgetConfiguration, ...]
    results: tuple[HoldoutRecoveryExperimentResult, ...]
    transitions: tuple[HeldOutBudgetTransition, ...]


@dataclass(frozen=True)
class BudgetConfigurationAggregate:
    configuration: AcquisitionBudgetConfiguration
    split_count: int
    held_out_total: int
    recovered: int
    micro_recovery_rate: float
    absent_from_hydrated: int
    nonselected_only: int
    extraction_failures: int
    mean_recall_at_10: float
    mean_recall_at_30: float
    mean_recall_at_50: float
    mean_recall_at_100: float
    mean_split_median_recovered_rank: float | None
    mean_split_mean_recovered_rank: float | None
    leaderboard_requests: int
    top_play_requests: int
    additional_diagnostic_requests: int


@dataclass(frozen=True)
class AcquisitionBudgetAggregate:
    split_count: int
    configurations: tuple[BudgetConfigurationAggregate, ...]
    selected_limit_gains: int
    hydration_budget_gains: int


@dataclass(frozen=True)
class AcquisitionRequestSummary:
    leaderboard_requests: int
    top_play_requests: int

    @property
    def total_data_requests(self) -> int:
        return self.leaderboard_requests + self.top_play_requests


async def evaluate_acquisition_budgets(
    username: str,
    *,
    top_plays: int = 100,
    holdout_count: int = 10,
    split_count: int = 5,
    split_index: int = 0,
    seed_count: int = 5,
    candidate_top_plays: int = 100,
    osu_client: OsuApiClient | None = None,
    experiment_function: ExperimentFunction = evaluate_holdout_recovery,
) -> AcquisitionBudgetExperimentResult:
    """Run the three fixed configurations as explicit independent experiments."""
    client = osu_client or OsuApiClient(OsuCredentials.from_environment())
    results: list[HoldoutRecoveryExperimentResult] = []
    for configuration in BUDGET_CONFIGURATIONS:
        results.append(
            await experiment_function(
                username,
                top_plays=top_plays,
                holdout_count=holdout_count,
                split_count=split_count,
                split_index=split_index,
                seed_count=seed_count,
                hydration_budget=configuration.hydration_budget,
                candidate_top_plays=candidate_top_plays,
                similar_player_limit=configuration.similar_player_limit,
                osu_client=client,
            )
        )
    result_tuple = tuple(results)
    return AcquisitionBudgetExperimentResult(
        split_index=split_index,
        configurations=BUDGET_CONFIGURATIONS,
        results=result_tuple,
        transitions=classify_budget_transitions(result_tuple),
    )


def classify_budget_transitions(
    results: Sequence[HoldoutRecoveryExperimentResult],
) -> tuple[HeldOutBudgetTransition, ...]:
    if len(results) != len(BUDGET_CONFIGURATIONS):
        raise ValueError("Exactly three configured experiment results are required.")
    diagnostic_maps = tuple(
        {item.play.beatmap_id: item for item in result.acquisition_diagnostics}
        for result in results
    )
    baseline_ids = tuple(diagnostic_maps[0])
    if any(set(items) != set(baseline_ids) for items in diagnostic_maps[1:]):
        raise ValueError("Configuration results must describe the same held-out maps.")
    transitions: list[HeldOutBudgetTransition] = []
    for beatmap_id in baseline_ids:
        baseline, selected, hydrated = (
            items[beatmap_id] for items in diagnostic_maps
        )
        transitions.append(
            HeldOutBudgetTransition(
                position=baseline.play.position,
                beatmap_id=beatmap_id,
                baseline_stage=baseline.failure_stage,
                selected_limit_stage=selected.failure_stage,
                hydration_budget_stage=hydrated.failure_stage,
                baseline_preference_rank=baseline.preference_aware_rank,
                selected_limit_preference_rank=selected.preference_aware_rank,
                hydration_budget_preference_rank=hydrated.preference_aware_rank,
                cause=_transition_cause(
                    baseline.failure_stage,
                    selected.failure_stage,
                    hydrated.failure_stage,
                ),
            )
        )
    return tuple(transitions)


def aggregate_budget_experiments(
    experiments: Sequence[AcquisitionBudgetExperimentResult],
) -> AcquisitionBudgetAggregate:
    if not experiments:
        raise ValueError("At least one budget experiment is required.")
    aggregates = tuple(
        _aggregate_configuration(
            configuration,
            tuple(experiment.results[index] for experiment in experiments),
        )
        for index, configuration in enumerate(BUDGET_CONFIGURATIONS)
    )
    return AcquisitionBudgetAggregate(
        split_count=len(experiments),
        configurations=aggregates,
        selected_limit_gains=sum(
            transition.cause == "selected_limit_gain"
            for experiment in experiments
            for transition in experiment.transitions
        ),
        hydration_budget_gains=sum(
            transition.cause == "hydration_budget_gain"
            for experiment in experiments
            for transition in experiment.transitions
        ),
    )


def summarize_acquisition_requests(
    results: Sequence[HoldoutRecoveryExperimentResult],
) -> AcquisitionRequestSummary:
    """Total data requests across independently executed configurations."""
    return AcquisitionRequestSummary(
        leaderboard_requests=sum(item.leaderboard_requests_made for item in results),
        top_play_requests=sum(item.top_play_requests_made for item in results),
    )


def _transition_cause(
    baseline: str,
    selected: str,
    hydrated: str,
) -> TransitionCause:
    if baseline == "recovered":
        return "baseline_recovered"
    if baseline == "present_only_in_nonselected_candidates" and selected == "recovered":
        return "selected_limit_gain"
    if (
        baseline == "not_present_in_hydrated_candidates"
        and selected == "not_present_in_hydrated_candidates"
        and hydrated == "recovered"
    ):
        return "hydration_budget_gain"
    if hydrated != "recovered":
        return "still_absent"
    return "unattributed_change"


def _aggregate_configuration(
    configuration: AcquisitionBudgetConfiguration,
    results: Sequence[HoldoutRecoveryExperimentResult],
) -> BudgetConfigurationAggregate:
    held_out_total = sum(item.acquisition_summary.held_out_total for item in results)
    recovered = sum(item.acquisition_summary.recovered for item in results)
    summaries = tuple(item.preference_aware_summary for item in results)
    medians = _rank_values(summaries, "median")
    means = _rank_values(summaries, "mean")
    return BudgetConfigurationAggregate(
        configuration=configuration,
        split_count=len(results),
        held_out_total=held_out_total,
        recovered=recovered,
        micro_recovery_rate=recovered / held_out_total if held_out_total else 0.0,
        absent_from_hydrated=sum(
            item.acquisition_summary.not_present_in_hydrated_candidates
            for item in results
        ),
        nonselected_only=sum(
            item.acquisition_summary.present_only_in_nonselected_candidates
            for item in results
        ),
        extraction_failures=sum(
            item.acquisition_summary.extraction_or_exclusion_failures
            for item in results
        ),
        mean_recall_at_10=fmean(item.recall_at_10 for item in summaries),
        mean_recall_at_30=fmean(item.recall_at_30 for item in summaries),
        mean_recall_at_50=fmean(item.recall_at_50 for item in summaries),
        mean_recall_at_100=fmean(item.recall_at_100 for item in summaries),
        mean_split_median_recovered_rank=fmean(medians) if medians else None,
        mean_split_mean_recovered_rank=fmean(means) if means else None,
        leaderboard_requests=sum(item.leaderboard_requests_made for item in results),
        top_play_requests=sum(item.top_play_requests_made for item in results),
        additional_diagnostic_requests=sum(
            item.additional_recovery_requests for item in results
        ),
    )


def _rank_values(
    summaries: Sequence[OrderingRecoverySummary],
    field: Literal["median", "mean"],
) -> tuple[float, ...]:
    return tuple(
        float(getattr(item.recovered_rank_summary, field))
        for item in summaries
        if item.recovered_rank_summary is not None
    )
