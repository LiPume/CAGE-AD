#!/usr/bin/env python3
"""Publish typed empty-road PnC input for a no-NPC execution smoke."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import threading

from cyber.proto.clock_pb2 import Clock
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.perception_msgs.perception_obstacle_pb2 import PerceptionObstacles
from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import PredictionObstacles


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stats", type=Path, required=True)
    args = parser.parse_args()
    if not args.run_id.startswith("NO_NPC_"):
        raise ValueError("execution smoke run id must start with NO_NPC_")

    stopping = threading.Event()
    cyber.init("cage_d0_empty_road_" + args.run_id)
    node = cyber.Node("cage_d0_empty_road_" + args.run_id)
    prediction_writer = node.create_writer("/apollo/prediction_raw", PredictionObstacles, 10)
    perception_writer = node.create_writer(
        "/apollo/perception/obstacles", PerceptionObstacles, 10
    )
    counts = {"clock": 0, "prediction": 0, "perception": 0}

    def on_clock(message: Clock) -> None:
        timestamp = message.clock / 1_000_000_000.0
        prediction = PredictionObstacles()
        prediction.header.timestamp_sec = timestamp
        prediction.header.module_name = "cage_d0_empty_road_execution_smoke"
        prediction.header.sequence_num = counts["prediction"]
        prediction_writer.write(prediction)
        perception = PerceptionObstacles()
        perception.header.timestamp_sec = timestamp
        perception.header.module_name = "cage_d0_empty_road_execution_smoke"
        perception.header.sequence_num = counts["perception"]
        perception_writer.write(perception)
        counts["clock"] += 1
        counts["prediction"] += 1
        counts["perception"] += 1

    reader = node.create_reader("/clock", Clock, on_clock)

    def stop(_signum, _frame) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print("empty_road_runtime=READY no_npc=true dataset=false", flush=True)
    while not stopping.wait(0.2):
        pass
    _atomic_json(
        args.stats,
        {
            "schema_version": 1,
            "label": "RUNTIME_REPAIR_SMOKE_NOT_DATASET",
            "run_id": args.run_id,
            "counts": counts,
            "oracle_access": False,
            "interaction_actor": False,
            "prediction_output_topic": "/apollo/prediction_raw",
        },
    )
    del reader
    os._exit(0)


if __name__ == "__main__":
    main()
