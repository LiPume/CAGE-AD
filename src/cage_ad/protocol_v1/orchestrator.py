"""Single-recipe, append-safe execution of the normative calibration search."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
from typing import Any, Mapping, Sequence

import yaml

from .attempts import PreparedAttempt, prepare_attempt
from .audit import audit_visible_tree
from .calibration import (
    RunEvidence,
    calibration_gate_config,
    evaluate_dose_gate,
    evaluate_nominal_gate,
    evaluate_probe_gate,
)
from .ledger import AttemptPlan, AttemptResult, CalibrationLedger
from .loader import ProtocolValidationError, load_protocol
from .search import SearchEvent, SearchPhase


PROBE_CONDITIONS = {
    "interaction_forecasting": "probe_forecasting",
    "motion_planning": "probe_planning",
    "tracking_execution": "probe_control",
}
REGRESSION_CONDITIONS = {
    "interaction_forecasting": "regression_probe_forecasting",
    "motion_planning": "regression_probe_planning",
    "tracking_execution": "regression_probe_control",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: Mapping[str, Any], mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _atomic_text(path: Path, value: str, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(value)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


class RecipeOrchestrator:
    def __init__(
        self,
        *,
        repo_root: Path,
        bundle_root: Path,
        runtime_root: Path,
        state_root: Path,
        data_root: Path,
        private_oracle_root: Path,
        recipe_id: str,
        execute: bool,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.bundle_root = bundle_root.resolve()
        self.runtime_root = runtime_root.resolve()
        self.state_root = state_root.resolve()
        self.data_root = data_root.resolve()
        self.private_oracle_root = private_oracle_root.resolve()
        self.bundle = load_protocol(self.repo_root)
        self.recipe_id = recipe_id
        self.recipe = self.bundle.recipe(recipe_id)
        self.execute = execute
        self.ledger_path = self.state_root / "ledger/attempts.jsonl"
        self.source_commit = self._source_commit()
        self._supersede_stale_pending_plans()
        self._enforce_recipe_order()

    def _supersede_stale_pending_plans(self) -> None:
        ledger = self._ledger()
        for record in ledger.records:
            if record.event_type != "attempt_planned":
                continue
            plan = AttemptPlan(**record.payload)
            if (
                plan.recipe_id != self.recipe_id
                or plan.source_commit == self.source_commit
                or ledger.find_operation(f"attempt-result/{plan.attempt_id}") is not None
            ):
                continue
            ledger.complete_attempt(
                AttemptResult(
                    attempt_id=plan.attempt_id,
                    status="interrupted",
                    runtime_valid=False,
                    five_layer_metrics={
                        "infrastructure_valid": False,
                        "mechanism_activated": None,
                        "safety_outcome": None,
                        "task_outcome": None,
                        "attribution_outcome": None,
                    },
                    wall_seconds=0.0,
                    powered_on_seconds=0.0,
                    incremental_storage_bytes=0,
                    output_sha256={},
                    failure_reason="source_checkpoint_superseded_before_execution",
                ),
                recorded_at=_utc_now(),
            )

    def _source_commit(self) -> str:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        if status:
            raise ProtocolValidationError("calibration requires a clean source-only checkpoint")
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        if branch != "codex/apollo-d0-protocol-v1":
            raise ProtocolValidationError("calibration must run on codex/apollo-d0-protocol-v1")
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def _enforce_recipe_order(self) -> None:
        order = self.bundle.recipe_order
        index = order.index(self.recipe_id)
        missing = [
            recipe_id
            for recipe_id in order[:index]
            if not (self.state_root / f"calibration/decisions/{recipe_id}.json").is_file()
        ]
        if missing:
            raise ProtocolValidationError(
                "earlier recipes do not have terminal decisions: " + ", ".join(missing)
            )

    def _ledger(self) -> CalibrationLedger:
        return CalibrationLedger(self.ledger_path)

    def _matching_plans(
        self,
        *,
        candidate_id: str,
        seed: int,
        condition: str,
        dose: Mapping[str, float] | None,
    ) -> list[AttemptPlan]:
        plans = []
        for record in self._ledger().records:
            if record.event_type != "attempt_planned":
                continue
            plan = AttemptPlan(**record.payload)
            if (
                plan.recipe_id == self.recipe_id
                and plan.source_commit == self.source_commit
                and plan.candidate_id == candidate_id
                and plan.seed == seed
                and plan.condition == condition
                and plan.dose == dose
            ):
                plans.append(plan)
        return sorted(plans, key=lambda item: item.infrastructure_attempt)

    def _result(self, attempt_id: str) -> AttemptResult | None:
        record = self._ledger().find_operation(f"attempt-result/{attempt_id}")
        return None if record is None else AttemptResult(**record.payload)

    def _prepare_or_resume(
        self,
        *,
        phase: str,
        candidate_id: str,
        seed: int,
        condition: str,
        dose: Mapping[str, float] | None,
    ) -> tuple[AttemptPlan, AttemptResult | None]:
        plans = self._matching_plans(
            candidate_id=candidate_id, seed=seed, condition=condition, dose=dose
        )
        if plans:
            latest = plans[-1]
            result = self._result(latest.attempt_id)
            if result is None:
                return latest, None
            if not result.runtime_valid and latest.infrastructure_attempt == 0:
                prepared = prepare_attempt(
                    repo_root=self.repo_root,
                    state_root=self.state_root,
                    data_root=self.data_root,
                    private_oracle_root=self.private_oracle_root,
                    recipe_id=self.recipe_id,
                    phase=phase,
                    candidate_id=candidate_id,
                    seed=seed,
                    condition=condition,
                    dose=dose,
                    source_commit=self.source_commit,
                    infrastructure_attempt=1,
                )
                retry = self._ledger().find_attempt_plan(prepared.attempt_id)
                assert retry is not None
                return retry, self._result(retry.attempt_id)
            return latest, result
        prepared = prepare_attempt(
            repo_root=self.repo_root,
            state_root=self.state_root,
            data_root=self.data_root,
            private_oracle_root=self.private_oracle_root,
            recipe_id=self.recipe_id,
            phase=phase,
            candidate_id=candidate_id,
            seed=seed,
            condition=condition,
            dose=dose,
            source_commit=self.source_commit,
        )
        plan = self._ledger().find_attempt_plan(prepared.attempt_id)
        assert plan is not None
        return plan, None

    def _execute_plan(self, plan: AttemptPlan) -> AttemptResult | None:
        if not self.execute:
            return None
        self._check_budget()
        env = os.environ.copy()
        env.update(
            CAGE_BUNDLE_ROOT=str(self.bundle_root),
            CAGE_RUNTIME_ROOT=str(self.runtime_root),
            CAGE_STATE_ROOT=str(self.state_root),
            CAGE_DATA_ROOT=str(self.data_root),
            CAGE_PRIVATE_ORACLE_ROOT=str(self.private_oracle_root),
        )
        process = subprocess.Popen(
            list(plan.command), cwd=self.repo_root, env=env, start_new_session=True
        )
        try:
            return_code = process.wait(timeout=420)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=30)
            raise ProtocolValidationError(f"attempt timed out and was cleaned: {plan.attempt_id}")
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, list(plan.command))
        return self._result(plan.attempt_id)

    def _check_budget(self) -> None:
        run_state = yaml.safe_load((self.state_root / "RUN_STATE.yaml").read_text())
        completed = [
            AttemptResult(**record.payload)
            for record in self._ledger().records
            if record.event_type == "attempt_finished"
        ]
        powered_hours = sum(item.powered_on_seconds for item in completed) / 3600.0
        storage_gib = sum(item.incremental_storage_bytes for item in completed) / 1024**3
        powered_limit = float(run_state["budget"]["remaining_powered_on_hours"])
        storage_limit = float(run_state["budget"]["remaining_incremental_storage_gib_estimate"])
        if powered_hours + 0.10 > powered_limit or storage_gib + 0.25 > storage_limit:
            required = self.state_root / "USER_ACTION_REQUIRED.md"
            _atomic_text(
                required,
                "# 需要用户增加 D0 v1 预算\n\n"
                f"当前 v1 已使用 {powered_hours:.3f} powered-on 小时、{storage_gib:.3f} GiB。"
                "下一次运行将接近现有总预算上限；Apollo/CARLA 已保持关闭。\n",
                0o640,
            )
            raise ProtocolValidationError("calibration budget is too close to the declared limit")

    def _ensure_runs(
        self,
        *,
        phase: str,
        candidate_id: str,
        seeds: Sequence[int],
        condition: str,
        dose: Mapping[str, float] | None,
    ) -> tuple[list[AttemptPlan], bool]:
        selected: list[AttemptPlan] = []
        complete = True
        for seed in seeds:
            plan, result = self._prepare_or_resume(
                phase=phase,
                candidate_id=candidate_id,
                seed=seed,
                condition=condition,
                dose=dose,
            )
            if result is None:
                result = self._execute_plan(plan)
            if (
                result is not None
                and not result.runtime_valid
                and plan.infrastructure_attempt == 0
            ):
                retry_plan, retry_result = self._prepare_or_resume(
                    phase=phase,
                    candidate_id=candidate_id,
                    seed=seed,
                    condition=condition,
                    dose=dose,
                )
                plan = retry_plan
                if retry_result is None:
                    retry_result = self._execute_plan(retry_plan)
                result = retry_result
            selected.append(plan)
            complete &= result is not None
        return selected, complete

    def _run_evidence(self, plan: AttemptPlan) -> RunEvidence:
        result = self._result(plan.attempt_id)
        if result is None:
            raise ProtocolValidationError(f"attempt is not finished: {plan.attempt_id}")
        private_root = (
            self.private_oracle_root
            / "protocol_v1/calibration"
            / self.recipe_id
            / plan.attempt_id
        )
        metrics_path = private_root / "run_metrics.json"
        if not metrics_path.is_file():
            return RunEvidence(
                plan.seed,
                False,
                False,
                {"collision_count": 0, "minimum_ttc_s": None},
                {"route_completion": 0.0, "forward_progress_m": 0.0, "timeout": True},
                None,
                (),
            )
        metrics = json.loads(metrics_path.read_text())
        return RunEvidence(
            seed=plan.seed,
            runtime_valid=result.runtime_valid,
            route_accepted=bool(metrics["infrastructure_outcome"]["route_accepted"]),
            safety=metrics["safety_outcome"],
            task=metrics["task_outcome"],
            mechanism=result.five_layer_metrics["mechanism_activated"],
            samples=metrics["samples"],
        )

    def _write_gate(self, name: str, value: Mapping[str, Any]) -> None:
        path = self.state_root / "calibration/gates" / self.recipe_id / f"{name}.json"
        document = {
            "schema_version": 1,
            "protocol_bundle_sha256": self.bundle.bundle_sha256,
            "source_commit": self.source_commit,
            **value,
        }
        if path.exists():
            if json.loads(path.read_text()) != document:
                raise ProtocolValidationError(f"existing gate evidence differs: {path}")
            return
        _atomic_json(path, document, 0o600)

    def _nominal_plans(self, candidate_id: str) -> list[AttemptPlan]:
        plans = []
        for seed in self.bundle.scenarios["scenario_admission"]["calibration_trials_per_candidate"]["seeds"]:
            matches = self._matching_plans(
                candidate_id=candidate_id, seed=int(seed), condition="nominal", dose=None
            )
            if not matches:
                raise ProtocolValidationError("nominal evidence unexpectedly missing")
            plans.append(matches[-1])
        return plans

    def _finish_decision(self, snapshot) -> dict[str, Any]:
        decision_path = self.state_root / f"calibration/decisions/{self.recipe_id}.json"
        if decision_path.exists():
            existing = json.loads(decision_path.read_text())
            if existing.get("terminal_classification") != snapshot.terminal_classification:
                raise ProtocolValidationError("existing terminal decision conflicts with search ledger")
            return existing
        decision = {
            "schema_version": 1,
            "protocol_version": self.bundle.episodes["protocol_version"],
            "recipe_id": self.recipe_id,
            "terminal_classification": snapshot.terminal_classification,
            "selected_candidate_id": snapshot.selected_candidate_id,
            "selected_dose": snapshot.selected_dose,
            "trigger_window": (
                None
                if snapshot.selected_candidate_id is None
                else list(
                    scenario_trigger_window(
                        self.bundle, self.recipe["scenario_id"], snapshot.selected_candidate_id
                    )
                )
            ),
            "source_commit": self.source_commit,
            "protocol_bundle_sha256": self.bundle.bundle_sha256,
            "ledger_tail_sha256": (
                self._ledger().records[-1].event_sha256 if self._ledger().records else None
            ),
            "formal_seeds_executed": False,
            "completed_at": _utc_now(),
        }
        _atomic_json(decision_path, decision, 0o600)
        chinese = (
            f"# {self.recipe_id} 校准判定\n\n"
            f"- 终态：`{snapshot.terminal_classification}`\n"
            f"- 选中候选：`{snapshot.selected_candidate_id}`\n"
            f"- 选中剂量：`{json.dumps(snapshot.selected_dose, ensure_ascii=False, sort_keys=True)}`\n"
            f"- 协议哈希：`{self.bundle.bundle_sha256}`\n"
            f"- 源码提交：`{self.source_commit}`\n"
            "- 正式 seeds：未运行；本文件只记录 calibration。\n"
        )
        _atomic_text(
            self.state_root / f"calibration/decisions/{self.recipe_id}.md", chinese, 0o600
        )
        return decision

    def run(self) -> dict[str, Any]:
        gate_config = calibration_gate_config(self.bundle)
        calibration_seeds = tuple(map(int, self.bundle.episodes["calibration_seeds"]))
        regression_seeds = tuple(
            map(int, self.bundle.probes["common"]["fault_free_regression_seeds"])
        )
        while True:
            machine = self._ledger().replay_search(self.bundle, self.recipe_id)
            state = machine.snapshot
            if state.phase == SearchPhase.TERMINAL:
                return self._finish_decision(state)
            candidate_id = machine.current_candidate["candidate_id"]
            if state.phase == SearchPhase.NOMINAL:
                plans, complete = self._ensure_runs(
                    phase=state.phase.value,
                    candidate_id=candidate_id,
                    seeds=calibration_seeds,
                    condition="nominal",
                    dose=None,
                )
                if not complete:
                    return {"status": "PLANNED", "recipe_id": self.recipe_id, "attempts": [p.attempt_id for p in plans]}
                result = evaluate_nominal_gate(
                    [self._run_evidence(plan) for plan in plans], gate_config
                )
                self._write_gate(f"nominal_{candidate_id}", asdict(result))
                self._ledger().advance_search_once(
                    self.bundle,
                    self.recipe_id,
                    SearchEvent.NOMINAL_PASSED if result.passed else SearchEvent.NOMINAL_FAILED,
                    transition_id=f"nominal-{candidate_id}",
                    recorded_at=_utc_now(),
                )
                continue
            if state.phase == SearchPhase.DOSE:
                dose = dict(machine.current_dose)
                plans, complete = self._ensure_runs(
                    phase=state.phase.value,
                    candidate_id=candidate_id,
                    seeds=calibration_seeds[:3],
                    condition="fault_no_probe",
                    dose=dose,
                )
                if not complete:
                    return {"status": "PLANNED", "recipe_id": self.recipe_id, "attempts": [p.attempt_id for p in plans]}
                nominal = {
                    plan.seed: self._run_evidence(plan)
                    for plan in self._nominal_plans(candidate_id)
                    if plan.seed in calibration_seeds[:3]
                }
                result = evaluate_dose_gate(
                    nominal, [self._run_evidence(plan) for plan in plans], gate_config
                )
                self._write_gate(
                    f"dose_{candidate_id}_{state.dose_index}",
                    {"dose": dose, **asdict(result)},
                )
                self._ledger().advance_search_once(
                    self.bundle,
                    self.recipe_id,
                    SearchEvent.DOSE_PASSED if result.passed else SearchEvent.DOSE_FAILED,
                    transition_id=f"dose-{candidate_id}-{state.dose_index}",
                    recorded_at=_utc_now(),
                )
                continue
            selected_dose = dict(state.selected_dose)
            probe_plan_map: dict[str, list[AttemptPlan]] = {}
            for domain, condition in PROBE_CONDITIONS.items():
                plans, complete = self._ensure_runs(
                    phase=state.phase.value,
                    candidate_id=candidate_id,
                    seeds=calibration_seeds[:3],
                    condition=condition,
                    dose=selected_dose,
                )
                probe_plan_map[domain] = plans
                if not complete:
                    return {"status": "PLANNED", "recipe_id": self.recipe_id, "attempts": [p.attempt_id for p in plans]}
            regression_nominal_plans, complete = self._ensure_runs(
                phase=state.phase.value,
                candidate_id=candidate_id,
                seeds=regression_seeds,
                condition="regression_nominal",
                dose=None,
            )
            if not complete:
                return {"status": "PLANNED", "recipe_id": self.recipe_id, "attempts": [p.attempt_id for p in regression_nominal_plans]}
            regression_plan_map = {}
            for domain, condition in REGRESSION_CONDITIONS.items():
                plans, complete = self._ensure_runs(
                    phase=state.phase.value,
                    candidate_id=candidate_id,
                    seeds=regression_seeds,
                    condition=condition,
                    dose=None,
                )
                regression_plan_map[domain] = plans
                if not complete:
                    return {"status": "PLANNED", "recipe_id": self.recipe_id, "attempts": [p.attempt_id for p in plans]}
            no_probe = {
                plan.seed: self._run_evidence(plan)
                for plan in self._matching_selected_dose_plans(candidate_id, selected_dose)
            }
            probes = {
                domain: {plan.seed: self._run_evidence(plan) for plan in plans}
                for domain, plans in probe_plan_map.items()
            }
            regression_nominal = {
                plan.seed: self._run_evidence(plan) for plan in regression_nominal_plans
            }
            regression_probes = {
                domain: {plan.seed: self._run_evidence(plan) for plan in plans}
                for domain, plans in regression_plan_map.items()
            }
            for plan in [*sum(probe_plan_map.values(), []), *regression_nominal_plans, *sum(regression_plan_map.values(), [])]:
                audit_visible_tree(self.data_root / "protocol_v1" / plan.attempt_id / "visible")
            correct_domain = self.bundle.faults["faults"][self.recipe["fault_id"]][
                "responsibility_domain"
            ]
            result = evaluate_probe_gate(
                correct_domain=correct_domain,
                trigger_start_s=scenario_trigger_window(
                    self.bundle, self.recipe["scenario_id"], candidate_id
                )[0],
                no_probe_by_seed=no_probe,
                probes_by_domain=probes,
                regression_nominal_by_seed=regression_nominal,
                regression_probes_by_domain=regression_probes,
                base_gates_pass=True,
                no_oracle_leakage=True,
                config=gate_config,
            )
            self._write_gate("probes", asdict(result))
            if result.classification == "rejected":
                event, classification = SearchEvent.PROBES_INVALID, None
            else:
                labels = {
                    "multi_domain_overlap": "ambiguous_multi_domain",
                    "insufficient_correct_effect": "ambiguous_insufficient_correct_effect",
                    "nonselective_probe_effect": "ambiguous_nonselective",
                }
                event = SearchEvent.PROBES_VALID
                classification = (
                    "identifiable"
                    if result.classification == "identifiable"
                    else labels[result.reason]
                )
            self._ledger().advance_search_once(
                self.bundle,
                self.recipe_id,
                event,
                transition_id="probes",
                recorded_at=_utc_now(),
                classification=classification,
            )

    def _matching_selected_dose_plans(
        self, candidate_id: str, dose: Mapping[str, float]
    ) -> list[AttemptPlan]:
        plans = []
        for seed in map(int, self.bundle.episodes["calibration_seeds"][:3]):
            matches = self._matching_plans(
                candidate_id=candidate_id,
                seed=seed,
                condition="fault_no_probe",
                dose=dose,
            )
            if not matches:
                raise ProtocolValidationError("selected dose no-probe evidence missing")
            plans.append(matches[-1])
        return plans


def scenario_trigger_window(bundle, scenario_id: str, candidate_id: str) -> tuple[float, float]:
    from .scenario import scenario_candidate_by_id

    return scenario_candidate_by_id(bundle, scenario_id, candidate_id).trigger_window
