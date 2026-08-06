"""Deterministic public index builder for an opaque CAGE-AD dataset batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


FORBIDDEN_PUBLIC_KEYS = {
    "scenario_kind",
    "fault_mechanism",
    "responsibility_domain",
    "correct_probe_role",
    "wrong_probe_roles",
    "fault_repeat_roles",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _assert_public_json(value: Any, path: Path) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_PUBLIC_KEYS.intersection(value)
        if forbidden:
            raise ValueError(f"forbidden evaluator key(s) in {path}: {sorted(forbidden)}")
        for child in value.values():
            _assert_public_json(child, path)
    elif isinstance(value, list):
        for child in value:
            _assert_public_json(child, path)


def _safe_file(root: Path, path: Path) -> Path:
    if path.is_symlink():
        raise ValueError(f"public batch cannot contain a symlink: {path}")
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"file escapes public batch root: {path}")
    if not resolved.is_file():
        raise ValueError(f"missing public data file: {path}")
    return resolved


def _file_record(batch_root: Path, path: Path) -> dict[str, Any]:
    resolved = _safe_file(batch_root, path)
    if resolved.suffix == ".json":
        _assert_public_json(json.loads(resolved.read_text()), resolved)
    return {
        "path": resolved.relative_to(batch_root.resolve()).as_posix(),
        "bytes": resolved.stat().st_size,
        "media_type": "application/json" if resolved.suffix == ".json" else "application/octet-stream",
        "sha256": sha256_file(resolved),
    }


def build_public_manifest(
    *, data_root: Path, state_root: Path, repo_root: Path, batch_id: str
) -> dict[str, Any]:
    """Build an opaque public index without accepting or opening an oracle root."""
    if not batch_id or Path(batch_id).name != batch_id:
        raise ValueError("batch_id must be one path component")
    batch_root = data_root / batch_id
    plan_path = state_root / f"{batch_id}_plan.json"
    execution_path = state_root / f"{batch_id}_execution.json"
    plan = _load_json(plan_path)
    execution = _load_json(execution_path)
    if execution.get("status") != "PASS" or execution.get("failed_count") != 0:
        raise ValueError("refusing to index an incomplete or runtime-failed batch")
    episodes = plan.get("episodes")
    if not isinstance(episodes, list) or plan.get("episode_count") != len(episodes):
        raise ValueError("invalid episode plan")
    expected_runs = len(episodes) * 7
    runs = execution.get("runs")
    if (
        not isinstance(runs, dict)
        or execution.get("completed_count") != expected_runs
        or len(runs) != expected_runs
    ):
        raise ValueError("batch does not contain seven completed companion runs per episode")

    public_episodes = []
    for episode in sorted(episodes, key=lambda item: item["episode_id"]):
        episode_id = episode["episode_id"]
        if Path(episode_id).name != episode_id:
            raise ValueError("episode_id must be opaque and path-safe")
        episode_root = batch_root / episode_id
        visible = episode_root / "visible" / "episode.json"
        retained_root = episode_root / "retained"
        _safe_file(batch_root, visible)
        if not retained_root.is_dir():
            raise ValueError(f"missing retained companion data: {episode_id}")
        retained = sorted(retained_root.glob("*.json"))
        if len(retained) != 7:
            raise ValueError(f"expected seven retained companions for {episode_id}")
        unexpected_directories = {
            path.name for path in episode_root.iterdir() if path.is_dir()
        } - {"visible", "retained"}
        if unexpected_directories:
            raise ValueError(
                f"unexpected episode directories for {episode_id}: "
                f"{sorted(unexpected_directories)}"
            )
        all_files = sorted(path for path in episode_root.rglob("*") if not path.is_dir())
        files = [_file_record(batch_root, path) for path in all_files]
        public_episodes.append({"episode_id": episode_id, "files": files})

    card_path = repo_root / "docs/dataset/CAGE_AD_D0_DATASET_CARD.md"
    manifest = {
        "schema_version": 1,
        "release_status": "engineering_candidate",
        "batch_id": batch_id,
        "diagnosis_episode_count": len(public_episodes),
        "companion_run_count": expected_runs,
        "source_commit": plan.get("source_commit"),
        "config_sha256": plan.get("config_sha256"),
        "plan_sha256": sha256_file(plan_path),
        "execution_sha256": sha256_file(execution_path),
        "dataset_card_sha256": sha256_file(card_path),
        "episodes": public_episodes,
    }
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["content_sha256"] = hashlib.sha256(encoded).hexdigest()
    return manifest
