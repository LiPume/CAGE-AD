#!/usr/bin/env python3
"""Bounded CARLA RPC readiness check used before starting the synchronous bridge."""

from __future__ import annotations

import argparse
import time

import carla


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            client = carla.Client("127.0.0.1", 2000)
            client.set_timeout(3)
            world = client.get_world()
            print(f"carla_rpc=READY map={world.get_map().name}")
            return
        except RuntimeError as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"CARLA RPC did not become ready: {last_error}")


if __name__ == "__main__":
    main()
