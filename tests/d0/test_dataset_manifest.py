from __future__ import annotations

import json
from pathlib import Path

import pytest

from cage_ad.dataset_manifest import build_public_manifest, sha256_file


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))


def fixture(tmp_path: Path):
    data = tmp_path / "data"
    state = tmp_path / "state"
    repo = tmp_path / "repo"
    batch = "pilot"
    episode_id = "opaque_episode"
    card = repo / "docs/dataset/CAGE_AD_D0_DATASET_CARD.md"
    card.parent.mkdir(parents=True)
    card.write_text("pilot card")
    write_json(data / batch / episode_id / "visible/episode.json", {"episode_id": episode_id})
    for index in range(7):
        write_json(
            data / batch / episode_id / "retained" / f"opaque_{index}.json",
            {"schema_version": 1, "samples": []},
        )
    write_json(
        state / f"{batch}_plan.json",
        {
            "episode_count": 1,
            "episodes": [{"episode_id": episode_id}],
            "source_commit": "abc",
            "config_sha256": "def",
        },
    )
    write_json(
        state / f"{batch}_execution.json",
        {
            "status": "PASS",
            "failed_count": 0,
            "completed_count": 7,
            "runs": {f"run_{index}": {"outcome": "PASS"} for index in range(7)},
        },
    )
    return data, state, repo, batch, episode_id


def test_public_manifest_is_deterministic_and_complete(tmp_path):
    data, state, repo, batch, episode_id = fixture(tmp_path)
    first = build_public_manifest(
        data_root=data, state_root=state, repo_root=repo, batch_id=batch
    )
    second = build_public_manifest(
        data_root=data, state_root=state, repo_root=repo, batch_id=batch
    )
    assert first == second
    assert first["diagnosis_episode_count"] == 1
    assert first["companion_run_count"] == 7
    assert len(first["episodes"][0]["files"]) == 8
    assert first["dataset_card_sha256"] == sha256_file(
        repo / "docs/dataset/CAGE_AD_D0_DATASET_CARD.md"
    )
    assert first["episodes"][0]["episode_id"] == episode_id


def test_public_manifest_refuses_incomplete_batch(tmp_path):
    data, state, repo, batch, _ = fixture(tmp_path)
    execution = state / f"{batch}_execution.json"
    value = json.loads(execution.read_text())
    value["status"] = "RUNNING"
    write_json(execution, value)
    with pytest.raises(ValueError, match="incomplete"):
        build_public_manifest(
            data_root=data, state_root=state, repo_root=repo, batch_id=batch
        )


def test_public_manifest_rejects_oracle_fields_in_public_data(tmp_path):
    data, state, repo, batch, episode_id = fixture(tmp_path)
    write_json(
        data / batch / episode_id / "retained/opaque_0.json",
        {"fault_mechanism": "must_not_leak"},
    )
    with pytest.raises(ValueError, match="forbidden evaluator key"):
        build_public_manifest(
            data_root=data, state_root=state, repo_root=repo, batch_id=batch
        )
