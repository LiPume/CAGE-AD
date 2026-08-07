#!/usr/bin/env python3
"""Fail-closed preflight for the installed Apollo 10 lane-follow plugin bundle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET


TASK_RE = re.compile(r"task\s*\{.*?type:\s*\"([^\"]+)\".*?\}", re.DOTALL)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def inspect(neo_root: Path) -> dict:
    share = neo_root / "share"
    pipeline = share / "modules/planning/scenarios/lane_follow/conf/pipeline.pb.txt"
    if not pipeline.is_file():
        raise FileNotFoundError(pipeline)
    pipeline_text = "\n".join(
        line.split("#", 1)[0] for line in pipeline.read_text().splitlines()
    )
    task_types = TASK_RE.findall(pipeline_text)
    task_types.append("FastStopTrajectoryFallback")
    plugins: dict[str, dict[str, str]] = {}
    for plugin_xml in sorted((share / "modules/planning/tasks").glob("*/plugins.xml")):
        root = ET.fromstring(plugin_xml.read_text())
        library = root.attrib["path"]
        for item in root.findall("class"):
            class_name = item.attrib["type"].rsplit("::", 1)[-1]
            plugins[class_name] = {
                "plugin_xml": str(plugin_xml),
                "library": str(neo_root / "lib" / library),
                "default_config": str(plugin_xml.parent / "conf/default_conf.pb.txt"),
            }
    checks = []
    for task_type in task_types:
        plugin = plugins.get(task_type)
        record = {"task_type": task_type, "plugin_found": plugin is not None}
        if plugin is not None:
            record.update(plugin)
            record["library_found"] = Path(plugin["library"]).is_file()
            record["default_config_found"] = Path(plugin["default_config"]).is_file()
            record["default_config_required"] = task_type != "FastStopTrajectoryFallback"
        checks.append(record)
    passed = all(
        item.get("plugin_found")
        and item.get("library_found")
        and (not item.get("default_config_required") or item.get("default_config_found"))
        for item in checks
    )
    stage_dir = pipeline.parent / "lane_follow_stage"
    return {
        "schema_version": 1,
        "result": "PASS" if passed else "FAIL",
        "neo_root": str(neo_root),
        "pipeline": str(pipeline),
        "task_count": len(checks),
        "tasks": checks,
        "stage_custom_config_dir": str(stage_dir),
        "stage_custom_config_dir_exists": stage_dir.is_dir(),
        "interpretation": (
            "Apollo 10 plugin defaults are complete; absent stage-local files are optional user overrides"
            if passed and not stage_dir.is_dir()
            else "see task checks"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = inspect(args.neo_root.resolve())
    _atomic_json(args.output, document)
    print(json.dumps({"result": document["result"], "task_count": document["task_count"]}, sort_keys=True))
    raise SystemExit(0 if document["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
