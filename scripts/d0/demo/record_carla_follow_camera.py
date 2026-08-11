#!/usr/bin/env python3
"""Record an observation-only CARLA chase camera to a labeled H.264 MP4."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import time

import carla


WIDTH = 1280
HEIGHT = 720
FPS = 20
FONT = (
    "/root/autodl_apollo10_g0_bundle/runtime/carla/0.9.15/Engine/Content/"
    "Slate/Fonts/DroidSansFallback.ttf"
)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actor_speed(actor: carla.Actor) -> float:
    velocity = actor.get_velocity()
    return math.sqrt(velocity.x * velocity.x + velocity.y * velocity.y + velocity.z * velocity.z)


def wait_for_ego(timeout_s: float) -> tuple[carla.World, carla.Vehicle]:
    deadline = time.monotonic() + timeout_s
    last_error = "CARLA not available"
    while time.monotonic() < deadline:
        try:
            client = carla.Client("127.0.0.1", 2000)
            client.set_timeout(2.0)
            world = client.get_world()
            egos = [
                actor for actor in world.get_actors().filter("vehicle.*")
                if actor.attributes.get("role_name") == "ego_vehicle"
            ]
            if len(egos) == 1:
                return world, egos[0]
            last_error = f"expected one ego vehicle, observed {len(egos)}"
        except RuntimeError as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for ego vehicle: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=15.0)
    parser.add_argument("--connect-timeout-s", type=float, default=90.0)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if args.duration_s != 15.0:
        raise SystemExit("showcase duration is frozen at 15 seconds")
    if not Path(FONT).is_file():
        raise RuntimeError(f"Chinese overlay font is missing: {FONT}")

    world, ego = wait_for_ego(args.connect_timeout_s)
    if not world.get_map().name.endswith("/Town01"):
        raise RuntimeError("showcase requires Town01")
    blueprint = world.get_blueprint_library().find("sensor.camera.rgb")
    blueprint.set_attribute("image_size_x", str(WIDTH))
    blueprint.set_attribute("image_size_y", str(HEIGHT))
    blueprint.set_attribute("fov", "90")
    blueprint.set_attribute("sensor_tick", str(1.0 / FPS))
    transform = carla.Transform(
        carla.Location(x=-7.5, z=3.4),
        carla.Rotation(pitch=-12.0),
    )
    camera = world.spawn_actor(blueprint, transform, attach_to=ego)
    frame_queue: queue.Queue[tuple[int, bytes]] = queue.Queue(maxsize=8)

    def receive(image: carla.Image) -> None:
        frame_queue.put((int(image.frame), bytes(image.raw_data)))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + f".tmp.{os.getpid()}")
    overlay = (
        f"drawbox=x=0:y=0:w=iw:h=86:color=black@0.62:t=fill,"
        f"drawtext=fontfile={FONT}:text='CAGE-AD  |  Apollo 10 + CARLA 0.9.15':"
        "fontcolor=white:fontsize=28:x=28:y=14,"
        f"drawtext=fontfile={FONT}:text='Apollo 自动驾驶稳定直行演示':"
        "fontcolor=white:fontsize=23:x=28:y=51,"
        "drawbox=x=0:y=ih-48:w=iw:h=48:color=black@0.70:t=fill,"
        f"drawtext=fontfile={FONT}:text='演示录像 · 非数据集 · 非安全认证':"
        "fontcolor=yellow:fontsize=22:x=(w-text_w)/2:y=h-38"
    )
    command = [
        "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS), "-i", "-", "-an", "-vf", overlay,
        "-c:v", "libx264", "-preset", "ultrafast", "-threads", "2", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4", str(temporary),
    ]
    encoder_environment = os.environ.copy()
    # Apollo ships FFmpeg libraries for its modules. The host /usr/bin/ffmpeg
    # must use the matching host libraries instead of Apollo's LD_LIBRARY_PATH.
    encoder_environment.pop("LD_LIBRARY_PATH", None)
    encoder = subprocess.Popen(
        command, stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=encoder_environment
    )
    if encoder.stdin is None:
        raise RuntimeError("ffmpeg stdin is unavailable")
    camera.listen(receive)
    target_frames = int(args.duration_s * FPS)
    encoded_frames = 0
    observed_frames: list[int] = []
    start_speed = None
    maximum_speed = 0.0
    recording_started = False
    failure: BaseException | None = None
    try:
        deadline = time.monotonic() + args.connect_timeout_s
        while encoded_frames < target_frames:
            if time.monotonic() > deadline and not recording_started:
                raise RuntimeError("ego did not reach the frozen 0.5 m/s recording threshold")
            try:
                frame, pixels = frame_queue.get(timeout=10.0)
            except queue.Empty as exc:
                raise RuntimeError("camera stream stopped before the showcase completed") from exc
            speed = actor_speed(ego)
            if not recording_started:
                if speed < 0.5:
                    continue
                recording_started = True
                start_speed = speed
            encoder.stdin.write(pixels)
            encoded_frames += 1
            observed_frames.append(frame)
            maximum_speed = max(maximum_speed, speed)
    except BaseException as exc:
        failure = exc
    finally:
        camera.stop()
        camera.destroy()
        try:
            encoder.stdin.close()
        except BrokenPipeError:
            pass
    stderr = encoder.stderr.read().decode(errors="replace") if encoder.stderr else ""
    return_code = encoder.wait()
    if failure is not None:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"camera encode failed; ffmpeg_return_code={return_code}; "
            f"ffmpeg_stderr={stderr[-1000:]!r}"
        ) from failure
    if return_code != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg failed ({return_code}): {stderr[-1000:]}")
    os.replace(temporary, args.output)
    gaps = sum(right - left != 1 for left, right in zip(observed_frames, observed_frames[1:]))
    metadata = {
        "schema_version": 1,
        "label": "SHOWCASE_REPLAY_NOT_DATASET_NOT_SAFETY_CERTIFICATION",
        "run_id": args.run_id,
        "source_commit": args.source_commit,
        "map": world.get_map().name,
        "vehicle": ego.type_id,
        "camera": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "fov_deg": 90,
            "relative_location_m": {"x": -7.5, "y": 0.0, "z": 3.4},
            "relative_pitch_deg": -12.0,
        },
        "duration_s": args.duration_s,
        "encoded_frames": encoded_frames,
        "non_unit_sensor_frame_gaps": gaps,
        "start_speed_mps": start_speed,
        "maximum_speed_mps": maximum_speed,
        "video": str(args.output),
        "video_bytes": args.output.stat().st_size,
        "video_sha256": sha256(args.output),
        "control_authority": "none_observation_only_camera",
        "scientific_use": "forbidden",
    }
    atomic_json(args.metadata, metadata)
    print(json.dumps(metadata, sort_keys=True, ensure_ascii=False))
    raise SystemExit(0 if gaps == 0 and encoded_frames == target_frames else 2)


if __name__ == "__main__":
    main()
