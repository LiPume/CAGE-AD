#!/usr/bin/env python3
"""Private benchmark injector and semantic control-output probe adapter.

The process reads a private numeric configuration, delays Apollo control targets,
and publishes them to the CARLA bridge input.  A diagnostic action may replace
that output temporarily with a fixed, non-GT control target.  No simulator state
or oracle label is consumed by this process.
"""

import argparse
from collections import deque
import json
import os
from pathlib import Path
import signal
import threading

from cyber.proto.clock_pb2 import Clock
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-config", type=Path, required=True)
    parser.add_argument("--private-stats", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.private_config.read_text())
    delay_seconds = float(config["delay_seconds"])
    if delay_seconds <= 0.0:
        raise ValueError("delay_seconds must be positive")

    stopping = threading.Event()
    lock = threading.Lock()
    queue = deque()
    latest_clock = [None]
    probe = [None]
    probe_until = [None]
    counters = {
        "received_targets": 0,
        "released_delayed_targets": 0,
        "probe_requests": 0,
        "probe_publications": 0,
        "cleared_delayed_targets": 0,
    }

    cyber.init("a2_control_interposer")
    node = cyber.Node("a2_control_interposer")
    writer = node.create_writer("/apollo/control_guarded", ControlCommand, 10)

    def on_target(message: ControlCommand) -> None:
        with lock:
            if latest_clock[0] is None:
                return
            queued = ControlCommand()
            queued.CopyFrom(message)
            queue.append((latest_clock[0] + delay_seconds, queued))
            counters["received_targets"] += 1

    def on_probe(message: ControlCommand) -> None:
        duration = 2.0
        replacement = ControlCommand()
        replacement.CopyFrom(message)
        with lock:
            if latest_clock[0] is None:
                return
            counters["probe_requests"] += 1
            counters["cleared_delayed_targets"] += len(queue)
            queue.clear()
            probe[0] = replacement
            probe_until[0] = latest_clock[0] + duration
            writer.write(replacement)
            counters["probe_publications"] += 1

    def on_clock(message: Clock) -> None:
        sim_time = message.clock / 1_000_000_000.0
        with lock:
            latest_clock[0] = sim_time
            if probe[0] is not None and sim_time <= probe_until[0]:
                replacement = ControlCommand()
                replacement.CopyFrom(probe[0])
                replacement.header.timestamp_sec = sim_time
                writer.write(replacement)
                counters["probe_publications"] += 1
                return
            if probe[0] is not None:
                probe[0] = None
                probe_until[0] = None
            while queue and queue[0][0] <= sim_time:
                _, target = queue.popleft()
                writer.write(target)
                counters["released_delayed_targets"] += 1

    readers = [
        node.create_reader("/apollo/control", ControlCommand, on_target),
        node.create_reader("/apollo/guardian/control_probe", ControlCommand, on_probe),
        node.create_reader("/clock", Clock, on_clock),
    ]

    def stop(_signum, _frame) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print("a2_interposer=READY private_config_loaded=true oracle_label_loaded=false", flush=True)
    while not stopping.wait(0.2):
        pass
    with lock:
        stats = dict(counters)
        stats["delay_seconds"] = delay_seconds
        stats["queued_at_shutdown"] = len(queue)
    atomic_json(args.private_stats, stats)
    del readers
    cyber.shutdown()


if __name__ == "__main__":
    main()
