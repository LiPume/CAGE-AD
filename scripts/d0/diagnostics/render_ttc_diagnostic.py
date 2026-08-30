#!/usr/bin/env python3
"""Render diagnostic-only TTC plots and a 1280x720 replay video."""

from __future__ import annotations

import argparse
from bisect import bisect_left
import json
import math
from pathlib import Path
import subprocess
from typing import Any


def _load_trace(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        raise ValueError("diagnostic trace is empty")
    return rows


def _series(rows: list[dict[str, Any]], path: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    for row in rows:
        value: Any = row
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        values.append(math.nan if value is None else float(value))
    return values


def _render_plots(rows: list[dict[str, Any]], output: Path, run_id: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    times = _series(rows, ("route_epoch_elapsed_s",))
    ego_x = _series(rows, ("ego", "location", "x"))
    ego_y = _series(rows, ("ego", "location", "y"))
    actor_x = _series(rows, ("interaction_actor", "location", "x"))
    actor_y = _series(rows, ("interaction_actor", "location", "y"))

    figure, axis = plt.subplots(figsize=(10, 6), dpi=150)
    axis.plot(ego_x, ego_y, label="ego", color="#1565c0", linewidth=2)
    axis.plot(actor_x, actor_y, label="interaction actor", color="#d32f2f", linewidth=2)
    axis.scatter([ego_x[0], actor_x[0]], [ego_y[0], actor_y[0]], marker="o", s=30)
    axis.scatter([ego_x[-1], actor_x[-1]], [ego_y[-1], actor_y[-1]], marker="x", s=50)
    axis.set_title(f"{run_id} XY trajectory — DIAGNOSTIC ONLY, NOT DATASET")
    axis.set_xlabel("CARLA world x (m)")
    axis.set_ylabel("CARLA world y (m)")
    axis.axis("equal")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output / "xy_trajectory.png")
    plt.close(figure)

    figure, axes = plt.subplots(4, 1, figsize=(12, 10), dpi=150, sharex=True)
    axes[0].plot(times, _series(rows, ("relative", "center_distance_m")), label="center")
    axes[0].plot(times, _series(rows, ("geometry", "current_obb_separation_m")), label="OBB")
    axes[0].set_ylabel("distance (m)")
    axes[0].legend()
    axes[1].plot(times, [math.hypot(row["ego"]["velocity"]["x"], row["ego"]["velocity"]["y"]) for row in rows], label="ego")
    axes[1].plot(times, [math.hypot(row["interaction_actor"]["velocity"]["x"], row["interaction_actor"]["velocity"]["y"]) for row in rows], label="actor")
    axes[1].plot(times, _series(rows, ("apollo", "planning", "target_speed_1s_mps")), label="planning target +1s", alpha=0.8)
    axes[1].set_ylabel("speed (m/s)")
    axes[1].legend()
    axes[2].plot(times, _series(rows, ("relative", "closing_mps")), color="#6a1b9a")
    axes[2].axhline(0.0, color="black", linewidth=0.6)
    axes[2].set_ylabel("closing (m/s)")
    axes[3].plot(times, _series(rows, ("geometry", "production_ttc_s")), label="production")
    axes[3].plot(times, _series(rows, ("geometry", "independent_ttc_s")), label="independent", linestyle="--")
    axes[3].set_ylabel("TTC (s)")
    axes[3].set_xlabel("route epoch elapsed (s)")
    axes[3].set_ylim(0.0, 10.0)
    axes[3].legend()
    for axis in axes:
        axis.grid(True, alpha=0.25)
    figure.suptitle(f"{run_id} semantic trace — DIAGNOSTIC ONLY, NOT DATASET")
    figure.tight_layout()
    figure.savefig(output / "semantic_timeseries.png")
    plt.close(figure)


def _interpolated_row(rows: list[dict[str, Any]], times: list[float], target: float) -> dict[str, Any]:
    index = min(len(rows) - 1, bisect_left(times, target))
    if index == 0 or index == len(rows) or times[index] == target:
        return rows[index]
    left, right = rows[index - 1], rows[index]
    ratio = (target - times[index - 1]) / (times[index] - times[index - 1])
    result = json.loads(json.dumps(left))
    for actor_key in ("ego", "interaction_actor"):
        for field in ("x", "y", "z"):
            result[actor_key]["location"][field] = (
                left[actor_key]["location"][field] * (1.0 - ratio)
                + right[actor_key]["location"][field] * ratio
            )
        for field in ("x", "y", "z"):
            result[actor_key]["velocity"][field] = (
                left[actor_key]["velocity"][field] * (1.0 - ratio)
                + right[actor_key]["velocity"][field] * ratio
            )
        result[actor_key]["yaw_deg"] = (
            left[actor_key]["yaw_deg"] * (1.0 - ratio) + right[actor_key]["yaw_deg"] * ratio
        )
    result["route_epoch_elapsed_s"] = target
    return result


def _render_video(
    rows: list[dict[str, Any]], output: Path, run_id: str, ffmpeg: str, fps: int
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1280, 720
    margin = 80
    all_x = [row[key]["location"]["x"] for row in rows for key in ("ego", "interaction_actor")]
    all_y = [row[key]["location"]["y"] for row in rows for key in ("ego", "interaction_actor")]
    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)
    x_pad = max(8.0, (x_max - x_min) * 0.08)
    y_pad = max(8.0, (y_max - y_min) * 0.08)
    x_min, x_max = x_min - x_pad, x_max + x_pad
    y_min, y_max = y_min - y_pad, y_max + y_pad
    scale = min((width - 2 * margin) / max(1.0, x_max - x_min), (height - 2 * margin) / max(1.0, y_max - y_min))

    def screen(x: float, y: float) -> tuple[int, int]:
        return int(margin + (x - x_min) * scale), int(height - margin - (y - y_min) * scale)

    def actor_polygon(state: dict[str, Any]) -> list[tuple[int, int]]:
        extent = state["bounding_box"]["extent"]
        half_length, half_width = float(extent["x"]), float(extent["y"])
        angle = math.radians(float(state["yaw_deg"]) + float(state["bounding_box"]["yaw_deg"]))
        forward = math.cos(angle), math.sin(angle)
        side = -math.sin(angle), math.cos(angle)
        center_x, center_y = float(state["location"]["x"]), float(state["location"]["y"])
        return [
            screen(
                center_x + sx * half_length * forward[0] + sy * half_width * side[0],
                center_y + sx * half_length * forward[1] + sy * half_width * side[1],
            )
            for sx, sy in ((1, 1), (1, -1), (-1, -1), (-1, 1))
        ]

    times = [float(row["route_epoch_elapsed_s"]) for row in rows]
    duration = times[-1] - times[0]
    frame_count = max(1, int(round(duration * fps)) + 1)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output / "diagnostic_replay.mp4"),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    if process.stdin is None:
        raise RuntimeError("ffmpeg stdin is unavailable")
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font = ImageFont.truetype(font_path, 20)
    small = ImageFont.truetype(font_path, 16)
    ego_history: list[tuple[int, int]] = []
    actor_history: list[tuple[int, int]] = []
    try:
        for frame_index in range(frame_count):
            target = times[0] + min(duration, frame_index / fps)
            row = _interpolated_row(rows, times, target)
            ego_history.append(screen(row["ego"]["location"]["x"], row["ego"]["location"]["y"]))
            actor_history.append(screen(row["interaction_actor"]["location"]["x"], row["interaction_actor"]["location"]["y"]))
            image = Image.new("RGB", (width, height), "#f4f4f4")
            draw = ImageDraw.Draw(image)
            for offset in (-3.5, 0.0, 3.5):
                y = screen(x_min, (y_min + y_max) / 2.0 + offset)[1]
                draw.line((margin, y, width - margin, y), fill="#bdbdbd", width=2)
            if len(ego_history) > 1:
                draw.line(ego_history, fill="#64b5f6", width=3)
                draw.line(actor_history, fill="#ef9a9a", width=3)
            draw.polygon(actor_polygon(row["ego"]), fill="#1565c0", outline="black")
            draw.polygon(actor_polygon(row["interaction_actor"]), fill="#d32f2f", outline="black")
            ego_speed = math.hypot(row["ego"]["velocity"]["x"], row["ego"]["velocity"]["y"])
            actor_speed = math.hypot(row["interaction_actor"]["velocity"]["x"], row["interaction_actor"]["velocity"]["y"])
            geometry = row["geometry"]
            ttc = geometry.get("production_ttc_s")
            independent = geometry.get("independent_ttc_s")
            info = [
                f"{run_id}",
                f"route epoch +{target:6.2f} s    ego {ego_speed:5.2f} m/s    actor {actor_speed:5.2f} m/s",
                f"center {row['relative']['center_distance_m']:6.2f} m    OBB {geometry['current_obb_separation_m']:6.2f} m    closing {row['relative']['closing_mps']:6.2f} m/s",
                f"production TTC {('null' if ttc is None else f'{ttc:.2f} s')}    independent TTC {('null' if independent is None else f'{independent:.2f} s')}    CPA {geometry['closest_approach_time_s']:.2f} s",
            ]
            draw.rectangle((18, 18, 930, 140), fill="#ffffff", outline="#424242", width=2)
            for line_index, line in enumerate(info):
                draw.text((32, 28 + line_index * 27), line, fill="black", font=small if line_index else font)
            draw.rectangle((0, height - 46, width, height), fill="#212121")
            draw.text((width // 2 - 205, height - 36), "DIAGNOSTIC ONLY — NOT DATASET", fill="#ffeb3b", font=font)
            process.stdin.write(image.tobytes())
    finally:
        process.stdin.close()
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {return_code}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--fps", type=int, default=20)
    args = parser.parse_args()
    if args.fps <= 0:
        raise ValueError("fps must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = _load_trace(args.trace)
    _render_plots(rows, args.output_dir, args.run_id)
    _render_video(rows, args.output_dir, args.run_id, args.ffmpeg, args.fps)
    print(json.dumps({"run_id": args.run_id, "frames": len(rows), "output_dir": str(args.output_dir)}, sort_keys=True))


if __name__ == "__main__":
    main()
