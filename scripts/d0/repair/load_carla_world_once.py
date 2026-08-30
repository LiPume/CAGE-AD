#!/usr/bin/env python3
"""Load Town01 exactly once before bridge startup; never creates actors."""

from __future__ import annotations

import json
import time

import carla


def main() -> None:
    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(30)
    before = client.get_world().get_map().name
    started = time.monotonic()
    world = client.load_world("Town01")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        map_name = world.get_map().name
        if map_name.endswith("/Town01"):
            snapshot = world.wait_for_tick(10)
            print(
                json.dumps(
                    {
                        "before_map": before,
                        "after_map": map_name,
                        "elapsed_seconds": time.monotonic() - started,
                        "frame": snapshot.frame,
                        "load_world_calls": 1,
                        "result": "PASS",
                    },
                    sort_keys=True,
                )
            )
            return
        time.sleep(1)
    raise RuntimeError(f"one-shot load_world returned unexpected map {map_name}")


if __name__ == "__main__":
    main()
