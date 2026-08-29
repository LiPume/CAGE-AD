#!/usr/bin/env python3
"""Build an auditable Apollo map variant with missing lane road-width samples.

The public CARLA-Apollo bridge maps contain lane-width samples but no
left_road_sample/right_road_sample values. Apollo's LaneChangePath uses the
latter to extend a target-lane path boundary around an ADC that is still in an
adjacent lane. This tool fills only explicitly allowlisted lanes by walking
their same-direction neighbor chains. Geometry and routing topology are not
modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

from google.protobuf import text_format

from modules.common_msgs.map_msgs import map_pb2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def interpolate(samples, s: float) -> float:
    values = [(float(item.s), float(item.width)) for item in samples]
    if not values:
        raise ValueError("lane has no width samples")
    if s <= values[0][0]:
        return values[0][1]
    if s >= values[-1][0]:
        return values[-1][1]
    low = 0
    high = len(values) - 1
    while low + 1 < high:
        middle = (low + high) // 2
        if values[middle][0] <= s:
            low = middle
        else:
            high = middle
    s0, width0 = values[low]
    s1, width1 = values[high]
    ratio = (s - s0) / (s1 - s0)
    return width0 + ratio * (width1 - width0)


def lane_half_widths(lane, normalized_position: float) -> tuple[float, float]:
    lane_s = max(0.0, min(float(lane.length), normalized_position * float(lane.length)))
    return interpolate(lane.left_sample, lane_s), interpolate(lane.right_sample, lane_s)


def neighbor_chain(lanes: dict, lane, side: str) -> list:
    chain = []
    seen = {lane.id.id}
    current = lane
    field = f"{side}_neighbor_forward_lane_id"
    while True:
        identifiers = [item.id for item in getattr(current, field)]
        if not identifiers:
            return chain
        if len(identifiers) != 1:
            raise ValueError(
                f"ambiguous {side} neighbor chain for {current.id.id}: {identifiers}"
            )
        identifier = identifiers[0]
        if identifier in seen:
            raise ValueError(f"cycle in {side} neighbor chain at {identifier}")
        if identifier not in lanes:
            raise ValueError(f"missing neighbor lane {identifier}")
        current = lanes[identifier]
        seen.add(identifier)
        chain.append(current)


def road_width(lane, chain: list, normalized_position: float, side: str) -> float:
    own_left, own_right = lane_half_widths(lane, normalized_position)
    result = own_left if side == "left" else own_right
    for neighbor in chain:
        left, right = lane_half_widths(neighbor, normalized_position)
        result += left + right
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lane-id", action="append", required=True)
    parser.add_argument("--created-at", required=True)
    args = parser.parse_args()

    source = args.source_dir.resolve()
    output = args.output_dir.resolve()
    if source == output:
        raise SystemExit("output must be a derived map directory")
    if output.exists() and any(output.iterdir()):
        raise SystemExit("append-only map build refuses a non-empty output directory")

    map_message = map_pb2.Map()
    map_message.ParseFromString((source / "base_map.bin").read_bytes())
    lanes = {lane.id.id: lane for lane in map_message.lane}
    requested = list(dict.fromkeys(args.lane_id))
    missing = [identifier for identifier in requested if identifier not in lanes]
    if missing:
        raise SystemExit(f"unknown lane IDs: {missing}")

    audit = []
    for identifier in requested:
        lane = lanes[identifier]
        if lane.left_road_sample or lane.right_road_sample:
            raise SystemExit(f"source lane already has road-width samples: {identifier}")
        left_chain = neighbor_chain(lanes, lane, "left")
        right_chain = neighbor_chain(lanes, lane, "right")
        sample_positions = sorted(
            {float(sample.s) for sample in lane.left_sample}
            | {float(sample.s) for sample in lane.right_sample}
        )
        for s in sample_positions:
            normalized = 0.0 if lane.length == 0 else s / float(lane.length)
            left_sample = lane.left_road_sample.add()
            left_sample.s = s
            left_sample.width = road_width(lane, left_chain, normalized, "left")
            right_sample = lane.right_road_sample.add()
            right_sample.s = s
            right_sample.width = road_width(lane, right_chain, normalized, "right")
        audit.append({
            "lane_id": identifier,
            "sample_count": len(sample_positions),
            "left_neighbor_chain": [item.id.id for item in left_chain],
            "right_neighbor_chain": [item.id.id for item in right_chain],
            "left_road_width_min_m": min(item.width for item in lane.left_road_sample),
            "left_road_width_max_m": max(item.width for item in lane.left_road_sample),
            "right_road_width_min_m": min(item.width for item in lane.right_road_sample),
            "right_road_width_max_m": max(item.width for item in lane.right_road_sample),
        })

    output.mkdir(parents=True, exist_ok=True)
    for name in ("routing_map.bin", "routing_map.txt", "sim_map.bin", "sim_map.txt"):
        shutil.copy2(source / name, output / name)
    atomic_bytes(output / "base_map.bin", map_message.SerializeToString(deterministic=True))
    atomic_bytes(
        output / "base_map.txt",
        text_format.MessageToString(map_message).encode("utf-8"),
    )
    build_manifest = {
        "schema_version": 1,
        "created_at": args.created_at,
        "method": "SAME_DIRECTION_NEIGHBOR_CHAIN_WIDTH_SUM_V1",
        "scope": "ROAD_WIDTH_METADATA_ONLY",
        "source_dir": str(source),
        "source_base_map_sha256": sha256(source / "base_map.bin"),
        "output_base_map_sha256": sha256(output / "base_map.bin"),
        "geometry_modified": False,
        "routing_topology_modified": False,
        "prediction_modified": False,
        "planning_modified": False,
        "patched_lanes": audit,
        "copied_dependency_files": {
            name: sha256(output / name)
            for name in ("routing_map.bin", "routing_map.txt", "sim_map.bin", "sim_map.txt")
        },
    }
    atomic_bytes(
        output / "configured_map_manifest.json",
        (json.dumps(build_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    print(json.dumps(build_manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
