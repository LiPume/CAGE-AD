#!/usr/bin/env python3
"""Render the passed V17 trajectory in CARLA without rerunning Apollo."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import subprocess

import carla


WIDTH, HEIGHT, FPS, FRAME_COUNT = 1280, 720, 20, 300
FONT = (
    "/root/autodl_apollo10_g0_bundle/runtime/carla/0.9.15/Engine/Content/"
    "Slate/Fonts/DroidSansFallback.ttf"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def matching_image(images: queue.Queue[carla.Image], frame: int) -> carla.Image:
    while True:
        image = images.get(timeout=10.0)
        if image.frame < frame:
            continue
        if image.frame > frame:
            raise RuntimeError(f"camera skipped CARLA frame {frame}; next was {image.frame}")
        return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--expected-trace-sha256", required=True)
    parser.add_argument("--v17-evaluation", type=Path, required=True)
    parser.add_argument("--expected-evaluation-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    if sha256(args.trace) != args.expected_trace_sha256:
        raise RuntimeError("V17 source trace SHA256 mismatch")
    if sha256(args.v17_evaluation) != args.expected_evaluation_sha256:
        raise RuntimeError("V17 evaluation SHA256 mismatch")
    evaluation = json.loads(args.v17_evaluation.read_text())
    if not evaluation.get("passed"):
        raise RuntimeError("source V17 evaluation did not pass")
    rows = [json.loads(line) for line in args.trace.read_text().splitlines() if line.strip()]
    start = next(index for index, row in enumerate(rows) if row["carla"]["speed_mps"] >= 0.5)
    selected = rows[start : start + FRAME_COUNT]
    if len(selected) != FRAME_COUNT:
        raise RuntimeError("V17 trace does not contain 300 post-start frames")

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    if not world.get_map().name.endswith("/Town01"):
        raise RuntimeError("offline V17 render requires preloaded Town01")
    if world.get_actors().filter("vehicle.*"):
        raise RuntimeError("offline V17 render requires zero existing vehicles")
    old_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)
    first = selected[0]["carla"]
    location = carla.Location(x=first["x"], y=first["y"], z=0.5)
    waypoint = world.get_map().get_waypoint(location, project_to_road=True)
    z = waypoint.transform.location.z + 0.5 if waypoint is not None else 0.5
    blueprint = world.get_blueprint_library().find("vehicle.lincoln.mkz_2017")
    blueprint.set_attribute("role_name", "offline_v17_passed_trace_replay")
    actor = world.try_spawn_actor(
        blueprint,
        carla.Transform(carla.Location(x=first["x"], y=first["y"], z=z), carla.Rotation(yaw=0.0)),
    )
    if actor is None:
        world.apply_settings(old_settings)
        raise RuntimeError("could not spawn Lincoln for offline V17 render")
    actor.set_simulate_physics(False)
    camera_bp = world.get_blueprint_library().find("sensor.camera.rgb")
    camera_bp.set_attribute("image_size_x", str(WIDTH))
    camera_bp.set_attribute("image_size_y", str(HEIGHT))
    camera_bp.set_attribute("fov", "90")
    camera_bp.set_attribute("sensor_tick", "0.0")
    camera = world.spawn_actor(
        camera_bp,
        carla.Transform(carla.Location(x=-7.5, z=3.4), carla.Rotation(pitch=-12.0)),
        attach_to=actor,
    )
    images: queue.Queue[carla.Image] = queue.Queue()
    camera.listen(images.put)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + f".tmp.{os.getpid()}")
    overlay = (
        f"drawbox=x=0:y=0:w=iw:h=86:color=black@0.62:t=fill,"
        f"drawtext=fontfile={FONT}:text='CAGE-AD  |  Apollo 10 + CARLA 0.9.15':"
        "fontcolor=white:fontsize=28:x=28:y=14,"
        f"drawtext=fontfile={FONT}:text='V17 成功轨迹 · CARLA 离线回放':"
        "fontcolor=white:fontsize=23:x=28:y=51,"
        "drawbox=x=0:y=ih-48:w=iw:h=48:color=black@0.70:t=fill,"
        f"drawtext=fontfile={FONT}:text='演示录像 · 非实时控制 · 非安全认证':"
        "fontcolor=yellow:fontsize=22:x=(w-text_w)/2:y=h-38"
    )
    command = [
        "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-an", "-vf", overlay,
        "-c:v", "libx264", "-preset", "ultrafast", "-threads", "2", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4", str(temporary),
    ]
    environment = os.environ.copy()
    environment.pop("LD_LIBRARY_PATH", None)
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    if encoder.stdin is None:
        raise RuntimeError("ffmpeg stdin is unavailable")
    sensor_frames: list[int] = []
    try:
        for row in selected:
            state = row["carla"]
            actor.set_transform(
                carla.Transform(carla.Location(x=state["x"], y=state["y"], z=z), carla.Rotation(yaw=0.0))
            )
            frame = world.tick()
            image = matching_image(images, frame)
            sensor_frames.append(int(image.frame))
            encoder.stdin.write(bytes(image.raw_data))
    finally:
        camera.stop()
        camera.destroy()
        actor.destroy()
        world.apply_settings(old_settings)
        try:
            encoder.stdin.close()
        except BrokenPipeError:
            pass
    stderr = encoder.stderr.read().decode(errors="replace") if encoder.stderr else ""
    return_code = encoder.wait()
    if return_code != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg failed ({return_code}): {stderr[-1000:]}")
    os.replace(temporary, args.output)
    sensor_gaps = sum(right - left != 1 for left, right in zip(sensor_frames, sensor_frames[1:]))
    progress = math.hypot(
        selected[-1]["carla"]["x"] - selected[0]["carla"]["x"],
        selected[-1]["carla"]["y"] - selected[0]["carla"]["y"],
    )
    metadata = {
        "schema_version": 1,
        "label": "OFFLINE_CARLA_VISUAL_REPLAY_OF_PASSED_V17_TRACE_NOT_DATASET",
        "source_execution_commit": evaluation["execution_source_commit"],
        "renderer_source_commit": args.source_commit,
        "source_trace_sha256": args.expected_trace_sha256,
        "source_v17_evaluation_sha256": args.expected_evaluation_sha256,
        "source_v17_verdict": evaluation["verdict"],
        "source_trace_start_index": start,
        "source_trace_frames_rendered": len(selected),
        "source_progress_m": progress,
        "source_speed_mps": {
            "start": selected[0]["carla"]["speed_mps"],
            "maximum": max(row["carla"]["speed_mps"] for row in selected),
        },
        "render": {
            "map": world.get_map().name,
            "vehicle": "vehicle.lincoln.mkz_2017",
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "duration_s": FRAME_COUNT / FPS,
            "frames": FRAME_COUNT,
            "sensor_frame_gaps": sensor_gaps,
            "method": "set_transform_from_passed_trace_with_physics_disabled",
        },
        "video": str(args.output),
        "video_bytes": args.output.stat().st_size,
        "video_sha256": sha256(args.output),
        "scientific_use": "forbidden_visualization_only",
    }
    atomic_json(args.metadata, metadata)
    print(json.dumps(metadata, sort_keys=True, ensure_ascii=False))
    raise SystemExit(0 if sensor_gaps == 0 else 2)


if __name__ == "__main__":
    main()
