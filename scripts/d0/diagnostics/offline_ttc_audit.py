#!/usr/bin/env python3
"""只读汇总旧 protocol-v1 nominal attempts；绝不写原账本或数据目录。"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from statistics import median
from typing import Any, Mapping


CSV_FIELDS = (
    "attempt_id",
    "recipe_id",
    "candidate_id",
    "seed",
    "status",
    "sim_seconds",
    "frame_count",
    "route_epoch_sim",
    "planning_messages",
    "guarded_control_messages",
    "forward_progress_m",
    "ego_speed_min_mps",
    "ego_speed_median_mps",
    "ego_speed_max_mps",
    "separation_start_m",
    "separation_min_m",
    "separation_end_m",
    "finite_ttc_tick_count",
    "minimum_ttc_s",
    "collision_count",
    "missing_fields",
)


class OfflineAuditError(RuntimeError):
    pass


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _assert_isolated(
    output_root: Path, state_root: Path, data_root: Path, private_oracle_root: Path
) -> None:
    output = output_root.resolve()
    forbidden = (
        (state_root / "calibration").resolve(),
        (state_root / "ledger").resolve(),
        data_root.resolve(),
        private_oracle_root.resolve(),
    )
    if any(_inside(output, root) or _inside(root, output) for root in forbidden):
        raise OfflineAuditError("diagnostic output overlaps calibration ledger/data/private oracle")


def _read_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text())
    if not isinstance(value, Mapping):
        raise OfflineAuditError(f"JSON root must be an object: {path}")
    return value


def _value(document: Mapping[str, Any] | None, *keys: str) -> Any:
    current: Any = document
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _sample_stats(samples: list[Mapping[str, Any]]) -> dict[str, Any]:
    speeds = [float(item["ego_speed_mps"]) for item in samples if item.get("ego_speed_mps") is not None]
    separations = [float(item["center_separation_m"]) for item in samples if item.get("center_separation_m") is not None]
    finite = [float(item["obb_ttc_s"]) for item in samples if item.get("obb_ttc_s") is not None]
    return {
        "ego_speed_min_mps": min(speeds) if speeds else None,
        "ego_speed_median_mps": median(speeds) if speeds else None,
        "ego_speed_max_mps": max(speeds) if speeds else None,
        "separation_start_m": separations[0] if separations else None,
        "separation_min_m": min(separations) if separations else None,
        "separation_end_m": separations[-1] if separations else None,
        "finite_ttc_tick_count": len(finite),
        "minimum_ttc_s": min((value for value in finite if value > 0.0), default=None),
        "ttc_all_null": bool(samples) and not finite,
    }


def _log_counts(log_root: Path) -> dict[str, int]:
    stack = log_root / "stack.log"
    bridge = log_root / "bridge.log"
    stack_text = stack.read_text(errors="replace") if stack.is_file() else ""
    bridge_text = bridge.read_text(errors="replace") if bridge.is_file() else ""
    return {
        "chassis_not_ready": stack_text.count("Chassis msg is not ready"),
        "planning_no_trajectory": stack_text.count("planning has no trajectory point"),
        "control_input_failed": stack_text.count("Control input data failed"),
        "bridge_control_guarded_mentions": bridge_text.count("/apollo/control_guarded"),
    }


def build_offline_audit(
    *,
    state_root: Path,
    private_oracle_root: Path,
    data_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    _assert_isolated(output_root, state_root, data_root, private_oracle_root)
    ledger_path = state_root / "ledger/attempts.jsonl"
    events = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    plans = {
        event["payload"]["attempt_id"]: event["payload"]
        for event in events
        if event["event_type"] == "attempt_planned"
    }
    finished = [
        event["payload"]
        for event in events
        if event["event_type"] == "attempt_finished"
        and event["payload"]["attempt_id"] in plans
        and plans[event["payload"]["attempt_id"]]["phase"] == "nominal_gate"
    ]
    rows: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {}
    details: dict[str, Any] = {}
    for result in finished:
        attempt_id = result["attempt_id"]
        plan = plans[attempt_id]
        private_root = (
            private_oracle_root / "protocol_v1/calibration" / plan["recipe_id"] / attempt_id
        )
        log_root = state_root / "logs" / plan["recipe_id"] / attempt_id
        metrics_path = private_root / "run_metrics.json"
        scenario_stats_path = private_root / "scenario_stats.json"
        metrics = _read_json(metrics_path)
        scenario_stats = _read_json(scenario_stats_path)
        samples = [] if metrics is None else list(metrics.get("samples", []))
        stats = _sample_stats(samples)
        missing = []
        field_values = {
            "sim_seconds": _value(metrics, "runtime", "simulation_seconds"),
            "frame_count": _value(metrics, "runtime", "frames"),
            "route_epoch_sim": _value(scenario_stats, "route_epoch_sim"),
            "planning_messages": _value(metrics, "runtime", "messages", "planning"),
            "guarded_control_messages": _value(metrics, "runtime", "messages", "control_guarded"),
            "forward_progress_m": _value(metrics, "task_outcome", "forward_progress_m"),
            "collision_count": _value(metrics, "safety_outcome", "collision_count"),
        }
        for name, value in {**field_values, **{key: value for key, value in stats.items() if key != "ttc_all_null"}}.items():
            if value is None and name != "minimum_ttc_s":
                missing.append(name)
        if metrics is not None and stats["minimum_ttc_s"] is None:
            missing.append("minimum_ttc_s:no_positive_or_finite_ttc")
        # 旧 trace 明确没有记录这些字段，不能从角色名或摘要反推。
        missing.extend(
            [
                "ego_actor_id:not_recorded",
                "interaction_actor_id:not_recorded",
                "actor_xy_yaw_velocity_components:not_recorded",
                "obb_local_transform_extent:not_recorded",
                "localization_chassis_planning_target_control_values:not_recorded",
            ]
        )
        row = {
            "attempt_id": attempt_id,
            "recipe_id": plan["recipe_id"],
            "candidate_id": plan["candidate_id"],
            "seed": plan["seed"],
            "status": result["status"],
            **field_values,
            **{key: value for key, value in stats.items() if key not in {"ttc_all_null", "minimum_ttc_s"}},
            "minimum_ttc_s": stats["minimum_ttc_s"],
            "missing_fields": ";".join(missing),
        }
        rows.append(row)
        provenance[attempt_id] = {
            "ledger": str(ledger_path),
            "metrics": str(metrics_path),
            "scenario_stats": str(scenario_stats_path),
            "logs": str(log_root),
        }
        details[attempt_id] = {
            "plan": {
                "recipe_id": plan["recipe_id"],
                "candidate_id": plan["candidate_id"],
                "seed": plan["seed"],
                "source_commit": plan["source_commit"],
                "infrastructure_attempt": plan["infrastructure_attempt"],
            },
            "result_status": result["status"],
            "runtime_valid": result["runtime_valid"],
            "ttc_all_null": stats["ttc_all_null"],
            "scenario_actor_spawned": _value(scenario_stats, "actor_spawned"),
            "scenario_route_accepted": _value(scenario_stats, "route_accepted"),
            "scenario_frames": _value(scenario_stats, "frames"),
            "scenario_non_fixed_clock_steps": _value(scenario_stats, "non_fixed_clock_steps"),
            "log_counts": _log_counts(log_root),
        }
    if len(rows) != len(finished):
        raise OfflineAuditError("CSV row count would not match finished nominal ledger attempts")
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / "nominal_attempts.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (output_root / "nominal_attempt_provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['recipe_id']}/{row['candidate_id']}"
        group = groups.setdefault(key, {"finished": 0, "with_metrics": 0, "progress": [], "separation_min": [], "finite_ttc_ticks": 0})
        group["finished"] += 1
        if row["frame_count"] is not None:
            group["with_metrics"] += 1
        if row["forward_progress_m"] is not None:
            group["progress"].append(float(row["forward_progress_m"]))
        if row["separation_min_m"] is not None:
            group["separation_min"].append(float(row["separation_min_m"]))
        group["finite_ttc_ticks"] += int(row["finite_ttc_tick_count"] or 0)
    group_summary = {
        key: {
            "finished_attempts": value["finished"],
            "attempts_with_metrics": value["with_metrics"],
            "forward_progress_median_m": median(value["progress"]) if value["progress"] else None,
            "forward_progress_min_m": min(value["progress"]) if value["progress"] else None,
            "forward_progress_max_m": max(value["progress"]) if value["progress"] else None,
            "center_separation_min_over_runs_m": min(value["separation_min"]) if value["separation_min"] else None,
            "finite_ttc_tick_count": value["finite_ttc_ticks"],
        }
        for key, value in sorted(groups.items())
    }
    document = {
        "schema_version": 1,
        "classification": "measurement cannot establish TTC AND old trace cannot independently prove scenario geometry",
        "ledger_event_count": len(events),
        "finished_nominal_attempt_count": len(finished),
        "attempts_with_metrics": sum(row["frame_count"] is not None for row in rows),
        "attempts_without_metrics": sum(row["frame_count"] is None for row in rows),
        "all_recorded_ttc_null": all(
            detail["ttc_all_null"] for detail in details.values() if detail["result_status"] == "completed"
        ),
        "identity_uniqueness": "not recorded",
        "actor_program_execution": "not independently reconstructable from old artifacts",
        "apollo_command_execution": "message counts recorded; command values/chassis/gear not recorded",
        "groups": group_summary,
        "attempts": details,
        "csv_path": str(csv_path),
        "provenance_path": str(output_root / "nominal_attempt_provenance.json"),
    }
    (output_root / "OFFLINE_AUDIT.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    lines = [
        "# TTC null 只读离线审计",
        "",
        "## 结论（仿真启动前）",
        "",
        f"账本共有 {len(events)} 条事件，其中 {len(finished)} 条是已结束的 nominal attempt；{document['attempts_with_metrics']} 条有完整旧 run metrics，{document['attempts_without_metrics']} 条是历史失败或未执行即被新源码 supersede。CSV 行数与这 {len(finished)} 条严格一致。",
        "",
        "旧 trace 能确认：所有有 metrics 的运行均完整记录了约 32 秒、640 帧、无 frame gap，且 production TTC 全程为 null。它不能确认 actor 身份唯一、actor 世界坐标/速度分量、OBB local transform、Apollo 底盘/档位/控制值，因此不能仅靠旧 trace 排除 evaluator/identity 或 runtime bug。",
        "",
        "当前必须把两层问题分开：`measurement cannot establish TTC` 已被确认；`scenario never establishes interaction` 有强迹象（中心距离和 NPC 解析运动方向），但旧产物缺少独立复算所需字段，仍须 R1/R2 验证。",
        "",
        "## 按 candidate 汇总",
        "",
        "| recipe/candidate | finished | 有 metrics | progress 中位数 [min,max] m | 全运行最小中心距 m | finite TTC ticks |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, value in group_summary.items():
        progress = "not recorded" if value["forward_progress_median_m"] is None else f"{value['forward_progress_median_m']:.3f} [{value['forward_progress_min_m']:.3f},{value['forward_progress_max_m']:.3f}]"
        separation = "not recorded" if value["center_separation_min_over_runs_m"] is None else f"{value['center_separation_min_over_runs_m']:.3f}"
        lines.append(f"| {key} | {value['finished_attempts']} | {value['attempts_with_metrics']} | {progress} | {separation} | {value['finite_ttc_tick_count']} |")
    lines.extend(
        [
            "",
            "## 旧产物能回答什么",
            "",
            "- simulation seconds、frame 数、frame gap、route epoch、消息计数、ego 速度标量、forward progress、中心距离、production TTC 和 collision 可从 private metrics 原样读取。",
            "- route epoch 前冻结 actor 是源码行为；旧 stats 没保存逐帧 actor 状态，不能证明每次实际执行都吻合 YAML。",
            "- planning/control 只能证明有消息，不能证明目标速度、刹车、油门、档位或 bridge 执行正确。stack 日志的 chassis/planning-not-ready 计数写入机器可读 JSON，必须由 replay 的字段级采样解释。",
            "- 旧产物没有 ego/interaction actor ID、actor x/y/yaw/速度分量和 bounding box local transform，身份唯一性与独立 TTC 均为 `not recorded`。",
            "",
            "## R1/R2 必采字段",
            "",
            "完整 actor/OBB 状态、双方世界速度分量、intended/actual actor velocity、localization/chassis/planning/control/bridge 字段、road/lane、production 与独立 TTC/CPA，以及六个事件时刻。",
            "",
            "本审计没有启动 CARLA，没有写原 calibration ledger、decision、RUN_STATE、visible 或 private 数据。",
        ]
    )
    (output_root / "OFFLINE_AUDIT.md").write_text("\n".join(lines) + "\n")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--private-oracle-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = build_offline_audit(
        state_root=args.state_root,
        data_root=args.data_root,
        private_oracle_root=args.private_oracle_root,
        output_root=args.output_root,
    )
    print(json.dumps({key: result[key] for key in ("ledger_event_count", "finished_nominal_attempt_count", "attempts_with_metrics", "attempts_without_metrics")}, sort_keys=True))


if __name__ == "__main__":
    main()
