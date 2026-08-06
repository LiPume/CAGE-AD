#!/usr/bin/env python3
"""Publish a typed empty-road perception heartbeat from the A1 scenario contract.

This adapter consumes only simulation clock.  It has no access to CARLA actors,
fault labels, injector state, or evaluator/oracle files.
"""

import os
import signal
import threading

from cyber.proto.clock_pb2 import Clock
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.perception_msgs.perception_obstacle_pb2 import (
    PerceptionObstacles,
)


def main():
    stopping = threading.Event()
    cyber.init("a1_empty_semantic_heartbeat")
    node = cyber.Node("a1_empty_semantic_heartbeat")
    writer = node.create_writer(
        "/apollo/perception/obstacles", PerceptionObstacles, 10
    )
    sequence = 0

    def publish(clock):
        nonlocal sequence
        message = PerceptionObstacles()
        message.header.timestamp_sec = clock.clock / 1_000_000_000.0
        message.header.module_name = "g0_empty_semantic_adapter"
        message.header.sequence_num = sequence
        sequence += 1
        writer.write(message)

    reader = node.create_reader("/clock", Clock, publish)

    def stop(_signum, _frame):
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print("semantic_heartbeat=READY source=scenario_empty_road oracle_access=false", flush=True)
    while not stopping.wait(0.2):
        pass
    del reader
    print(f"semantic_heartbeat=STOPPED messages={sequence}", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
