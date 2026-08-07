"""Private attempt preparation and completion for protocol-v1 calibration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from typing import Any, Mapping

from .audit import audit_visible_tree, assert_storage_isolation
from .evaluator import MechanismObservation, evaluate_mechanism_activation
from .ledger import AttemptPlan, AttemptResult, CalibrationLedger
from .loader import PROTOCOL_VERSION, ProtocolBundle, ProtocolValidationError, load_protocol
from .scenario import scenario_candidate_by_id


CONDITIONS = {
    "nominal",
    "fault_no_probe",
    "probe_forecasting",
    "probe_planning",
    "probe_control",
    "regression_nominal",
    "regression_probe_forecasting",
    "regression_probe_planning",
    "regression_probe_control",
}
PROBE_DOMAIN_BY_CONDITION = {
    "probe_forecasting": "interaction_forecasting",
    "probe_planning": "motion_planning",
    "probe_control": "tracking_execution",
    "regression_probe_forecasting": "interaction_forecasting",
    "regression_probe_planning": "motion_planning",
    "regression_probe_control": "tracking_execution",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _atomic_json(path: Path, value: Mapping[str, Any], mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_bytes(_canonical(value) + b"\n")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _write_once(path: Path, value: Mapping[str, Any], mode: int) -> None:
    expected = _canonical(value) + b"\n"
    if path.exists():
        if path.is_symlink() or path.read_bytes() != expected:
            raise ProtocolValidationError(f"existing attempt artifact differs: {path}")
        return
    _atomic_json(path, value, mode)


def _namespace_key(private_oracle_root: Path) -> bytes:
    root = private_oracle_root / "protocol_v1"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    path = root / "opaque_id_namespace.key"
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, secrets.token_bytes(32))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ProtocolValidationError("opaque ID namespace key permissions are unsafe")
    value = path.read_bytes()
    if len(value) != 32:
        raise ProtocolValidationError("opaque ID namespace key is malformed")
    return value


def _sha_document(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class PreparedAttempt:
    attempt_id: str
    private_root: Path
    visible_root: Path
    log_root: Path
    plan_record_sha256: str


def _validate_attempt_semantics(
    bundle: ProtocolBundle,
    recipe_id: str,
    candidate_id: str,
    seed: int,
    condition: str,
    dose: Mapping[str, float] | None,
) -> tuple[Mapping[str, Any], Any]:
    if condition not in CONDITIONS:
        raise ProtocolValidationError(f"unknown attempt condition: {condition}")
    recipe = bundle.recipe(recipe_id)
    candidate = scenario_candidate_by_id(bundle, recipe["scenario_id"], candidate_id)
    calibration_seeds = set(map(int, bundle.episodes["calibration_seeds"]))
    regression_seeds = set(map(int, bundle.probes["common"]["fault_free_regression_seeds"]))
    if condition.startswith("regression_"):
        if seed not in regression_seeds:
            raise ProtocolValidationError("attempt seed is not in the regression registry")
    elif seed not in calibration_seeds:
        raise ProtocolValidationError("attempt seed is not in the calibration registry")
    is_fault_condition = condition == "fault_no_probe" or condition.startswith("probe_")
    if is_fault_condition:
        fault = bundle.faults["faults"][recipe["fault_id"]]
        if dose not in fault["dose_grid"]:
            raise ProtocolValidationError("attempt dose is not declared for recipe fault")
    elif dose is not None:
        raise ProtocolValidationError("nominal/regression attempt must not contain a fault dose")
    return recipe, candidate


def prepare_attempt(
    *,
    repo_root: Path,
    state_root: Path,
    data_root: Path,
    private_oracle_root: Path,
    recipe_id: str,
    phase: str,
    candidate_id: str,
    seed: int,
    condition: str,
    dose: Mapping[str, float] | None,
    source_commit: str,
    infrastructure_attempt: int = 0,
    recorded_at: str | None = None,
) -> PreparedAttempt:
    assert_storage_isolation(repo_root, data_root, private_oracle_root)
    bundle = load_protocol(repo_root)
    recipe, candidate = _validate_attempt_semantics(
        bundle, recipe_id, candidate_id, seed, condition, dose
    )
    if not re_fullmatch_hex_commit(source_commit):
        raise ProtocolValidationError("attempt source commit must be a full Git SHA-1")
    if infrastructure_attempt not in {0, 1}:
        raise ProtocolValidationError("protocol permits at most one infrastructure retry")
    private_identity = {
        "protocol_bundle_sha256": bundle.bundle_sha256,
        "recipe_id": recipe_id,
        "phase": phase,
        "candidate_id": candidate_id,
        "seed": seed,
        "condition": condition,
        "dose": dose,
        "repeat_index": 0,
        "infrastructure_attempt": infrastructure_attempt,
        "source_commit": source_commit,
    }
    attempt_id = "d0v1_" + hmac.new(
        _namespace_key(private_oracle_root), _canonical(private_identity), hashlib.sha256
    ).hexdigest()[:24]
    private_root = private_oracle_root / "protocol_v1" / "calibration" / recipe_id / attempt_id
    visible_root = data_root / "protocol_v1" / attempt_id / "visible"
    log_root = state_root / "logs" / recipe_id / attempt_id
    for path, mode in ((private_root, 0o700), (visible_root, 0o750), (log_root, 0o750)):
        path.mkdir(parents=True, exist_ok=True, mode=mode)
        path.chmod(mode)
    scenario_config = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_bundle_sha256": bundle.bundle_sha256,
        "scenario_id": recipe["scenario_id"],
        "candidate_id": candidate_id,
        "seed": seed,
    }
    fault_condition = condition == "fault_no_probe" or condition.startswith("probe_")
    interposer_config = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_bundle_sha256": bundle.bundle_sha256,
        "scenario_id": recipe["scenario_id"],
        "candidate_id": candidate_id,
        "seed": seed,
        "fault_id": recipe["fault_id"] if fault_condition else None,
        "dose": dict(dose) if fault_condition else None,
        "probe_domain": PROBE_DOMAIN_BY_CONDITION.get(condition),
        "trigger_window": list(candidate.trigger_window),
    }
    run_config = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_bundle_sha256": bundle.bundle_sha256,
        "interposer_stats_path": str(private_root / "interposer_stats.json"),
        "scenario_stats_path": str(private_root / "scenario_stats.json"),
    }
    config_sha = hashlib.sha256(
        _canonical(scenario_config) + b"\n" + _canonical(interposer_config) + b"\n" + _canonical(run_config)
    ).hexdigest()
    command = [
        str(repo_root / "scripts/d0/protocol_v1/run_calibration_once.sh"),
        attempt_id,
        str(private_root),
        str(visible_root),
        str(log_root),
    ]
    plan = AttemptPlan(
        attempt_id=attempt_id,
        recipe_id=recipe_id,
        phase=phase,
        candidate_id=candidate_id,
        seed=seed,
        condition=condition,
        source_commit=source_commit,
        protocol_bundle_sha256=bundle.bundle_sha256,
        config_sha256=config_sha,
        command=command,
        dose=dict(dose) if dose is not None else None,
        infrastructure_attempt=infrastructure_attempt,
    )
    _write_once(private_root / "scenario.json", scenario_config, 0o600)
    _write_once(private_root / "interposer.json", interposer_config, 0o600)
    _write_once(private_root / "run.json", run_config, 0o600)
    _write_once(private_root / "attempt_private.json", private_identity, 0o600)
    _write_once(
        visible_root / "episode.json",
        {
            "schema_version": 2,
            "protocol_version": PROTOCOL_VERSION,
            "episode_id": attempt_id,
            "observable_regime": "perfect_perception_pnc",
        },
        0o640,
    )
    audit_visible_tree(visible_root)
    ledger = CalibrationLedger(state_root / "ledger/attempts.jsonl")
    record = ledger.plan_attempt(plan, recorded_at=recorded_at or utc_now())
    return PreparedAttempt(attempt_id, private_root, visible_root, log_root, record.event_sha256)


def re_fullmatch_hex_commit(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value.lower())


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def complete_attempt(
    *,
    repo_root: Path,
    state_root: Path,
    data_root: Path,
    private_oracle_root: Path,
    attempt_id: str,
    recorded_at: str | None = None,
) -> AttemptResult:
    assert_storage_isolation(repo_root, data_root, private_oracle_root)
    ledger = CalibrationLedger(state_root / "ledger/attempts.jsonl")
    existing = ledger.find_operation(f"attempt-result/{attempt_id}")
    if existing is not None:
        return AttemptResult(**existing.payload)
    plan = ledger.find_attempt_plan(attempt_id)
    if plan is None:
        raise ProtocolValidationError(f"attempt was not planned: {attempt_id}")
    private_root = private_oracle_root / "protocol_v1" / "calibration" / plan.recipe_id / attempt_id
    visible_root = data_root / "protocol_v1" / attempt_id / "visible"
    private_identity = json.loads((private_root / "attempt_private.json").read_text())
    metrics_path = private_root / "run_metrics.json"
    resource_path = private_root / "resource_usage.json"
    if not resource_path.is_file():
        raise ProtocolValidationError("attempt output is incomplete: resource_usage.json")
    resources = json.loads(resource_path.read_text())
    bundle = load_protocol(repo_root)
    failure_path = private_root / "runtime_failure.json"
    if not metrics_path.is_file():
        if not failure_path.is_file():
            raise ProtocolValidationError("attempt has neither metrics nor a recorded runtime failure")
        failure = json.loads(failure_path.read_text())
        audit_visible_tree(visible_root)
        storage_bytes = sum(
            path.stat().st_size
            for root in (private_root, visible_root)
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
        result = AttemptResult(
            attempt_id=attempt_id,
            status="failed",
            runtime_valid=False,
            five_layer_metrics={
                "infrastructure_valid": False,
                "mechanism_activated": None,
                "safety_outcome": None,
                "task_outcome": None,
                "attribution_outcome": None,
            },
            wall_seconds=float(resources["wall_seconds"]),
            powered_on_seconds=float(resources["powered_on_seconds"]),
            incremental_storage_bytes=storage_bytes,
            output_sha256={
                **{f"private/{key}": value for key, value in _file_hashes(private_root).items()},
                **{f"visible/{key}": value for key, value in _file_hashes(visible_root).items()},
            },
            failure_reason=str(failure.get("reason", "runtime_failed_without_metrics")),
        )
        ledger.complete_attempt(result, recorded_at=recorded_at or utc_now())
        _write_once(private_root / "attempt_result.json", asdict(result), 0o600)
        return result
    metrics = json.loads(metrics_path.read_text())
    interposer_path = private_root / "interposer_stats.json"
    if not interposer_path.is_file():
        raise ProtocolValidationError("attempt metrics exist but interposer stats are missing")
    interposer = json.loads(interposer_path.read_text())
    mechanism = None
    if private_identity["condition"] == "fault_no_probe" or private_identity["condition"].startswith("probe_"):
        recipe = bundle.recipe(plan.recipe_id)
        observations = [
            MechanismObservation(
                simulator_time_s=float(item["simulator_time_s"]),
                metric_value=float(item["metric_value"]),
                transform_residual=(
                    None if item.get("transform_residual") is None else float(item["transform_residual"])
                ),
            )
            for item in interposer["activation_observations"]
        ]
        mechanism = asdict(
            evaluate_mechanism_activation(
                bundle,
                recipe["fault_id"],
                private_identity["dose"],
                observations,
                tuple(json.loads((private_root / "interposer.json").read_text())["trigger_window"]),
            )
        )
    five_layers = {
        "infrastructure_valid": bool(metrics["infrastructure_valid"]),
        "mechanism_activated": mechanism,
        "safety_outcome": metrics["safety_outcome"],
        "task_outcome": metrics["task_outcome"],
        "attribution_outcome": None,
    }
    audit_visible_tree(visible_root)
    storage_bytes = sum(
        path.stat().st_size
        for root in (private_root, visible_root)
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    status = "completed" if metrics["infrastructure_valid"] else "invalid"
    failure_reason = None if status == "completed" else "infrastructure_invalid"
    output_hashes = {
        **{f"private/{key}": value for key, value in _file_hashes(private_root).items()},
        **{f"visible/{key}": value for key, value in _file_hashes(visible_root).items()},
    }
    result = AttemptResult(
        attempt_id=attempt_id,
        status=status,
        runtime_valid=bool(metrics["infrastructure_valid"]),
        five_layer_metrics=five_layers,
        wall_seconds=float(resources["wall_seconds"]),
        powered_on_seconds=float(resources["powered_on_seconds"]),
        incremental_storage_bytes=storage_bytes,
        output_sha256=output_hashes,
        failure_reason=failure_reason,
    )
    ledger.complete_attempt(result, recorded_at=recorded_at or utc_now())
    _write_once(private_root / "attempt_result.json", asdict(result), 0o600)
    return result
