"""隔离诊断工具；这些模块不属于正式数据生成路径。"""

from .ttc_null import (
    ClosestApproach,
    DiagnosticOBB,
    DiagnosticTraceRow,
    RootCause,
    classify_root_cause,
    classify_tick_disagreement,
    closest_approach,
    fine_step_ttc,
    has_stable_true,
    relative_state_in_ego_frame,
    sampled_prediction_geometry,
    sat_separation_m,
    summarize_trace,
    world_obb_from_carla_state,
)

__all__ = [
    "ClosestApproach",
    "DiagnosticOBB",
    "DiagnosticTraceRow",
    "RootCause",
    "classify_root_cause",
    "classify_tick_disagreement",
    "closest_approach",
    "fine_step_ttc",
    "has_stable_true",
    "relative_state_in_ego_frame",
    "sampled_prediction_geometry",
    "sat_separation_m",
    "summarize_trace",
    "world_obb_from_carla_state",
]
