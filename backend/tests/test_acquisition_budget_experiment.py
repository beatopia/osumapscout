"""Tests for the fixed acquisition-budget sensitivity experiment."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.app.osu.client import OsuAccessToken, OsuApiClient, OsuCredentials
from backend.app.recommendation.acquisition_budget_experiment import (
    BUDGET_CONFIGURATIONS,
    AcquisitionBudgetExperimentResult,
    aggregate_budget_experiments,
    classify_budget_transitions,
    evaluate_acquisition_budgets,
    summarize_acquisition_requests,
)
from backend.app.recommendation.holdout_recovery import (
    AcquisitionDiagnosticSummary,
    OrderingRecoverySummary,
    RecoveredRankSummary,
)


class BudgetConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_configs_run_sequentially_with_explicit_request_budgets(self) -> None:
        results = tuple(self._result(index) for index in range(3))
        experiment_function = AsyncMock(side_effect=results)
        client = OsuApiClient(OsuCredentials("client-id", "client-secret"))

        result = await evaluate_acquisition_budgets(
            "target",
            split_index=2,
            osu_client=client,
            experiment_function=experiment_function,
        )

        self.assertEqual(
            [(item.hydration_budget, item.similar_player_limit) for item in BUDGET_CONFIGURATIONS],
            [(25, 10), (25, 15), (40, 15)],
        )
        self.assertEqual(experiment_function.await_count, 3)
        for call, configuration in zip(
            experiment_function.await_args_list, BUDGET_CONFIGURATIONS, strict=True
        ):
            self.assertEqual(call.args, ("target",))
            self.assertEqual(call.kwargs["hydration_budget"], configuration.hydration_budget)
            self.assertEqual(call.kwargs["similar_player_limit"], configuration.similar_player_limit)
            self.assertEqual(call.kwargs["seed_count"], 5)
            self.assertEqual(call.kwargs["candidate_top_plays"], 100)
            self.assertIs(call.kwargs["osu_client"], client)
        self.assertEqual(result.results, results)
        self.assertEqual(
            [
                (item.leaderboard_requests_made, item.top_play_requests_made)
                for item in result.results
            ],
            [(5, 25), (5, 25), (5, 40)],
        )
        requests = summarize_acquisition_requests(result.results)
        self.assertEqual(requests.leaderboard_requests, 15)
        self.assertEqual(requests.top_play_requests, 90)
        self.assertEqual(requests.total_data_requests, 105)

    async def test_one_split_reuses_one_unexpired_access_token(self) -> None:
        results = iter(self._result(index) for index in range(3))
        client = OsuApiClient(OsuCredentials("client-id", "client-secret"))
        token_request = AsyncMock(
            return_value=OsuAccessToken("token", "Bearer", 3600)
        )
        supplied_clients: list[OsuApiClient] = []

        async def run_configuration(
            username: str, **kwargs: object
        ) -> SimpleNamespace:
            self.assertEqual(username, "target")
            supplied_client = kwargs["osu_client"]
            self.assertIsInstance(supplied_client, OsuApiClient)
            assert isinstance(supplied_client, OsuApiClient)
            supplied_clients.append(supplied_client)
            await supplied_client._get_access_token()
            return next(results)

        with patch.object(client, "request_access_token", token_request):
            await evaluate_acquisition_budgets(
                "target",
                osu_client=client,
                experiment_function=run_configuration,
            )

        self.assertEqual(supplied_clients, [client, client, client])
        token_request.assert_awaited_once_with()

    async def test_token_inside_expiry_margin_is_refreshed(self) -> None:
        client = OsuApiClient(OsuCredentials("client-id", "client-secret"))
        token_request = AsyncMock(
            side_effect=(
                OsuAccessToken("first", "Bearer", 30),
                OsuAccessToken("second", "Bearer", 30),
            )
        )

        with patch.object(client, "request_access_token", token_request):
            first = await client._get_access_token()
            second = await client._get_access_token()

        self.assertEqual(first.access_token, "first")
        self.assertEqual(second.access_token, "second")
        self.assertEqual(token_request.await_count, 2)

    @staticmethod
    def _result(index: int) -> SimpleNamespace:
        return _result(
            (_diagnostic(1, "recovered", 10 + index),),
            recovered=1,
            top_requests=(25, 25, 40)[index],
        )


class TransitionTests(unittest.TestCase):
    def test_attributes_selected_hydration_baseline_and_absent_cases(self) -> None:
        baseline = _result(
            (
                _diagnostic(1, "present_only_in_nonselected_candidates", None),
                _diagnostic(2, "not_present_in_hydrated_candidates", None),
                _diagnostic(3, "recovered", 5),
                _diagnostic(4, "not_present_in_hydrated_candidates", None),
            ),
            recovered=1,
        )
        selected = _result(
            (
                _diagnostic(1, "recovered", 20),
                _diagnostic(2, "not_present_in_hydrated_candidates", None),
                _diagnostic(3, "recovered", 6),
                _diagnostic(4, "not_present_in_hydrated_candidates", None),
            ),
            recovered=2,
        )
        hydrated = _result(
            (
                _diagnostic(1, "recovered", 21),
                _diagnostic(2, "recovered", 30),
                _diagnostic(3, "recovered", 7),
                _diagnostic(4, "not_present_in_hydrated_candidates", None),
            ),
            recovered=3,
        )

        transitions = classify_budget_transitions((baseline, selected, hydrated))

        self.assertEqual(
            [item.cause for item in transitions],
            [
                "selected_limit_gain",
                "hydration_budget_gain",
                "baseline_recovered",
                "still_absent",
            ],
        )

    def test_aggregate_reports_coverage_ranking_requests_and_gains(self) -> None:
        baseline = _result((_diagnostic(1, "present_only_in_nonselected_candidates", None),), 0)
        selected = _result((_diagnostic(1, "recovered", 8),), 1)
        hydrated = _result((_diagnostic(1, "recovered", 9),), 1, top_requests=40)
        experiment = AcquisitionBudgetExperimentResult(
            split_index=0,
            configurations=BUDGET_CONFIGURATIONS,
            results=(baseline, selected, hydrated),
            transitions=classify_budget_transitions((baseline, selected, hydrated)),
        )

        aggregate = aggregate_budget_experiments((experiment,))

        self.assertEqual(aggregate.selected_limit_gains, 1)
        self.assertEqual(aggregate.hydration_budget_gains, 0)
        self.assertEqual(aggregate.configurations[0].top_play_requests, 25)
        self.assertEqual(aggregate.configurations[2].top_play_requests, 40)
        self.assertEqual(aggregate.configurations[1].recovered, 1)
        self.assertEqual(aggregate.configurations[1].mean_recall_at_10, 1.0)


def _diagnostic(beatmap_id: int, stage: str, rank: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        play=SimpleNamespace(position=beatmap_id, beatmap_id=beatmap_id),
        failure_stage=stage,
        preference_aware_rank=rank,
    )


def _result(
    diagnostics: tuple[SimpleNamespace, ...],
    recovered: int,
    *,
    top_requests: int = 25,
) -> SimpleNamespace:
    total = len(diagnostics)
    absent = sum(
        item.failure_stage == "not_present_in_hydrated_candidates"
        for item in diagnostics
    )
    nonselected = sum(
        item.failure_stage == "present_only_in_nonselected_candidates"
        for item in diagnostics
    )
    extraction = sum(
        item.failure_stage == "extraction_or_exclusion_failure"
        for item in diagnostics
    )
    rank_summary = RecoveredRankSummary(1, 2.0, 3.0, 4) if recovered else None
    preference = OrderingRecoverySummary(
        held_out_count=total,
        recovered_anywhere=recovered,
        recovery_rate=recovered / total if total else 0.0,
        recovered_at_10=recovered,
        recovered_at_30=recovered,
        recovered_at_50=recovered,
        recovered_at_100=recovered,
        recall_at_10=recovered / total if total else 0.0,
        recall_at_30=recovered / total if total else 0.0,
        recall_at_50=recovered / total if total else 0.0,
        recall_at_100=recovered / total if total else 0.0,
        recovered_rank_summary=rank_summary,
    )
    return SimpleNamespace(
        acquisition_diagnostics=diagnostics,
        acquisition_summary=AcquisitionDiagnosticSummary(
            total, recovered, absent, nonselected, extraction, 0, 0
        ),
        preference_aware_summary=preference,
        leaderboard_requests_made=5,
        top_play_requests_made=top_requests,
        additional_recovery_requests=0,
    )


if __name__ == "__main__":
    unittest.main()
