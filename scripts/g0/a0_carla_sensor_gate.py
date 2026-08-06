#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CARLA A0 synchronous RGB/LiDAR gate")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town01")
    parser.add_argument("--fixed-delta", type=float, default=0.05)
    parser.add_argument("--wall-seconds", type=float, default=1800.0)
    parser.add_argument("--warmup-ticks", type=int, default=20)
    parser.add_argument("--sensor-timeout", type=float, default=10.0)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def gpu_sample() -> dict[str, float | None]:
    command = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        fields = subprocess.check_output(command, text=True, timeout=5).strip().split(",")
        return {
            "gpu_util_pct": float(fields[0]),
            "vram_used_mib": float(fields[1]),
            "vram_total_mib": float(fields[2]),
        }
    except Exception:
        return {"gpu_util_pct": None, "vram_used_mib": None, "vram_total_mib": None}


def read_memory_gib() -> dict[str, float]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0])
    host_used = (values["MemTotal"] - values["MemAvailable"]) * 1024
    host_total = values["MemTotal"] * 1024
    cgroup = Path("/sys/fs/cgroup")
    try:
        current = int((cgroup / "memory.current").read_text(encoding="utf-8").strip())
        raw_limit = (cgroup / "memory.max").read_text(encoding="utf-8").strip()
        limit = host_total if raw_limit == "max" else int(raw_limit)
        return {
            "ram_used_gib": current / 1024**3,
            "ram_total_gib": limit / 1024**3,
            "host_ram_used_gib": host_used / 1024**3,
            "host_ram_total_gib": host_total / 1024**3,
        }
    except (OSError, ValueError):
        return {
            "ram_used_gib": host_used / 1024**3,
            "ram_total_gib": host_total / 1024**3,
        }


def disk_used_gib(path: Path) -> float:
    stats = os.statvfs(path)
    return (stats.f_blocks - stats.f_bfree) * stats.f_frsize / 1024**3


class CpuSampler:
    def __init__(self) -> None:
        self.last_usage_usec: int | None = None
        self.last_time: float | None = None
        self.cgroup = Path("/sys/fs/cgroup")

    def sample(self) -> dict[str, float | None]:
        try:
            stats = dict(
                line.split(maxsplit=1)
                for line in (self.cgroup / "cpu.stat").read_text(encoding="utf-8").splitlines()
            )
            usage_usec = int(stats["usage_usec"])
            quota_fields = (self.cgroup / "cpu.max").read_text(encoding="utf-8").split()
            quota_cores = (
                float(len(__import__("os").sched_getaffinity(0)))
                if quota_fields[0] == "max"
                else int(quota_fields[0]) / int(quota_fields[1])
            )
            now = time.monotonic()
            used_cores = None
            util_pct = None
            if self.last_usage_usec is not None and self.last_time is not None and now > self.last_time:
                used_cores = (usage_usec - self.last_usage_usec) / 1_000_000 / (now - self.last_time)
                util_pct = used_cores / quota_cores * 100.0
            self.last_usage_usec = usage_usec
            self.last_time = now
            return {
                "cpu_used_cores": used_cores,
                "cpu_quota_cores": quota_cores,
                "cpu_util_pct_of_quota": util_pct,
            }
        except (OSError, ValueError, KeyError, ZeroDivisionError):
            return {
                "cpu_used_cores": None,
                "cpu_quota_cores": None,
                "cpu_util_pct_of_quota": None,
            }


def matching_measurement(
    sensor_queue: queue.Queue[Any], expected_frame: int, timeout: float, sensor_name: str
) -> tuple[Any, int]:
    deadline = time.monotonic() + timeout
    discarded = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"sensor timeout waiting for frame {expected_frame}")
        try:
            measurement = sensor_queue.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError(
                f"{sensor_name} timeout waiting for frame {expected_frame}"
            ) from exc
        if measurement.frame < expected_frame:
            discarded += 1
            continue
        if measurement.frame != expected_frame:
            raise RuntimeError(
                f"sensor frame jumped from expected {expected_frame} to {measurement.frame}"
            )
        return measurement, discarded


def main() -> None:
    args = parse_args()
    import carla

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    client = carla.Client(args.host, args.port)
    client.set_timeout(30.0)
    world = client.get_world()
    if not world.get_map().name.endswith(f"/{args.town}"):
        world = client.load_world(args.town)
    original_settings = world.get_settings()
    actors: list[Any] = []
    rgb_queue: queue.Queue[Any] = queue.Queue()
    lidar_queue: queue.Queue[Any] = queue.Queue()
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "FAIL",
        "host": args.host,
        "port": args.port,
        "fixed_delta_seconds": args.fixed_delta,
        "requested_wall_seconds": args.wall_seconds,
        "no_rendering_mode": False,
    }
    started = time.monotonic()
    disk_used_start_gib = disk_used_gib(output.parent)
    try:
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = args.fixed_delta
        settings.no_rendering_mode = False
        world.apply_settings(settings)
        applied = world.get_settings()
        if not applied.synchronous_mode or applied.no_rendering_mode:
            raise RuntimeError("CARLA rejected synchronous rendered settings")
        if abs(float(applied.fixed_delta_seconds) - args.fixed_delta) > 1e-9:
            raise RuntimeError("CARLA fixed delta does not match requested value")

        library = world.get_blueprint_library()
        vehicle_bp = library.find("vehicle.tesla.model3")
        spawn_points = world.get_map().get_spawn_points()
        vehicle = next(
            (actor for transform in spawn_points if (actor := world.try_spawn_actor(vehicle_bp, transform))),
            None,
        )
        if vehicle is None:
            raise RuntimeError("unable to spawn A0 ego vehicle")
        actors.append(vehicle)

        camera_bp = library.find("sensor.camera.rgb")
        camera_bp.set_attribute("image_size_x", "640")
        camera_bp.set_attribute("image_size_y", "360")
        camera = world.spawn_actor(
            camera_bp,
            carla.Transform(carla.Location(x=1.5, z=2.4)),
            attach_to=vehicle,
        )
        camera.listen(rgb_queue.put)
        actors.append(camera)

        lidar_bp = library.find("sensor.lidar.ray_cast")
        lidar_bp.set_attribute("channels", "32")
        lidar_bp.set_attribute("points_per_second", "56000")
        lidar_bp.set_attribute("rotation_frequency", str(1.0 / args.fixed_delta))
        lidar = world.spawn_actor(
            lidar_bp,
            carla.Transform(carla.Location(z=2.5)),
            attach_to=vehicle,
        )
        lidar.listen(lidar_queue.put)
        actors.append(lidar)

        for _ in range(args.warmup_ticks):
            frame = world.tick()
            matching_measurement(rgb_queue, frame, args.sensor_timeout, "rgb")
            matching_measurement(lidar_queue, frame, args.sensor_timeout, "lidar")

        tick_latency_ms: list[float] = []
        rgb_bytes: list[int] = []
        lidar_bytes: list[int] = []
        timestamp_error: list[float] = []
        discarded_rgb = 0
        discarded_lidar = 0
        resource_samples: list[dict[str, Any]] = []
        cpu_sampler = CpuSampler()
        cpu_sampler.sample()
        last_rgb_timestamp = -math.inf
        last_lidar_timestamp = -math.inf
        measured_started = time.monotonic()
        next_resource_sample = measured_started
        while time.monotonic() - measured_started < args.wall_seconds:
            tick_started = time.monotonic()
            frame = world.tick()
            snapshot = world.get_snapshot()
            rgb, rgb_discarded = matching_measurement(
                rgb_queue, frame, args.sensor_timeout, "rgb"
            )
            lidar_data, lidar_discarded = matching_measurement(
                lidar_queue, frame, args.sensor_timeout, "lidar"
            )
            tick_latency_ms.append((time.monotonic() - tick_started) * 1000.0)
            discarded_rgb += rgb_discarded
            discarded_lidar += lidar_discarded
            if len(rgb.raw_data) == 0 or len(lidar_data.raw_data) == 0:
                raise RuntimeError(f"empty sensor payload at frame {frame}")
            if rgb.timestamp <= last_rgb_timestamp or lidar_data.timestamp <= last_lidar_timestamp:
                raise RuntimeError(f"non-monotonic sensor timestamp at frame {frame}")
            last_rgb_timestamp = rgb.timestamp
            last_lidar_timestamp = lidar_data.timestamp
            rgb_bytes.append(len(rgb.raw_data))
            lidar_bytes.append(len(lidar_data.raw_data))
            timestamp_error.extend(
                [
                    abs(rgb.timestamp - snapshot.timestamp.elapsed_seconds),
                    abs(lidar_data.timestamp - snapshot.timestamp.elapsed_seconds),
                ]
            )
            now = time.monotonic()
            if now >= next_resource_sample:
                resource_samples.append(
                    {
                        "elapsed_seconds": now - measured_started,
                        **gpu_sample(),
                        **read_memory_gib(),
                        **cpu_sampler.sample(),
                    }
                )
                next_resource_sample = now + 10.0

        result.update(
            {
                "status": "PASS",
                "map": world.get_map().name,
                "frames": len(tick_latency_ms),
                "measured_wall_seconds": time.monotonic() - measured_started,
                "tick_latency_ms": {
                    "mean": statistics.fmean(tick_latency_ms),
                    "p95": percentile(tick_latency_ms, 0.95),
                    "p99": percentile(tick_latency_ms, 0.99),
                    "max": max(tick_latency_ms),
                },
                "rgb_payload_bytes": {"min": min(rgb_bytes), "max": max(rgb_bytes)},
                "lidar_payload_bytes": {"min": min(lidar_bytes), "max": max(lidar_bytes)},
                "max_sensor_world_timestamp_error_seconds": max(timestamp_error),
                "discarded_sensor_callbacks": {
                    "rgb": discarded_rgb,
                    "lidar": discarded_lidar,
                },
                "resource_samples": resource_samples,
                "peak_vram_used_mib": max(
                    (sample["vram_used_mib"] or 0.0 for sample in resource_samples), default=0.0
                ),
                "peak_gpu_util_pct": max(
                    (sample["gpu_util_pct"] or 0.0 for sample in resource_samples), default=0.0
                ),
                "peak_ram_used_gib": max(
                    (sample["ram_used_gib"] for sample in resource_samples), default=0.0
                ),
                "peak_cpu_util_pct_of_quota": max(
                    (
                        sample["cpu_util_pct_of_quota"] or 0.0
                        for sample in resource_samples
                    ),
                    default=0.0,
                ),
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        result["total_wall_seconds"] = time.monotonic() - started
        result["disk_used_start_gib"] = disk_used_start_gib
        result["disk_used_end_gib"] = disk_used_gib(output.parent)
        result["disk_growth_gib"] = result["disk_used_end_gib"] - disk_used_start_gib
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for actor in reversed(actors):
            try:
                if hasattr(actor, "stop"):
                    actor.stop()
                actor.destroy()
            except Exception:
                pass
        world.apply_settings(original_settings)


if __name__ == "__main__":
    main()
