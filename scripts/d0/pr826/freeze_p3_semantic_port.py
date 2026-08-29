#!/usr/bin/env python3
"""Freeze reproducible P3 source patches and their machine-readable hashes."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def unified(old: str, new: str, old_label: str, new_label: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=old_label,
            tofile=new_label,
            lineterm="\n",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--behavior-library", type=Path, required=True)
    parser.add_argument("--component-library", type=Path, required=True)
    parser.add_argument("--pinned-commit", required=True)
    args = parser.parse_args()

    relative_cc = Path("modules/prediction/predictor/sequence/sequence_predictor.cc")
    relative_header = Path(
        "modules/prediction/predictor/sequence/nearby_filter_policy.h"
    )
    relative_build = Path("modules/prediction/BUILD")
    stock_cc = (args.stock_root / relative_cc).read_text()
    candidate_cc = (args.candidate_root / relative_cc).read_text()
    candidate_header = (args.candidate_root / relative_header).read_text()
    stock_build = (args.stock_root / relative_build).read_text()
    candidate_build = (args.candidate_root / relative_build).read_text()

    marker = '        "predictor/sequence/sequence_predictor.h",\n'
    if stock_build.count(marker) != 1:
        raise ValueError("expected exactly one SequencePredictor header marker")
    semantic_build = stock_build.replace(
        marker, marker + '        "predictor/sequence/nearby_filter_policy.h",\n'
    )

    semantic_patch = "".join(
        (
            unified(
                stock_cc,
                candidate_cc,
                f"a/{relative_cc}",
                f"b/{relative_cc}",
            ),
            unified("", candidate_header, "/dev/null", f"b/{relative_header}"),
            unified(
                stock_build,
                semantic_build,
                f"a/{relative_build}",
                f"b/{relative_build}",
            ),
        )
    ).encode()
    build_patch = unified(
        semantic_build,
        candidate_build,
        f"a/{relative_build}",
        f"b/{relative_build}",
    ).encode()
    if not semantic_patch or not build_patch:
        raise ValueError("both frozen patches must be nonempty")

    output = args.output_dir
    semantic_path = output / "apollo10_semantic_port.patch"
    build_path = output / "apollo10_host_build_compat.patch"
    atomic_bytes(semantic_path, semantic_patch)
    atomic_bytes(build_path, build_patch)

    manifest = {
        "schema_version": 1,
        "status": "FROZEN_CANDIDATE",
        "pinned_apollo_commit": args.pinned_commit,
        "stock_source_root": str(args.stock_root.resolve()),
        "candidate_source_root": str(args.candidate_root.resolve()),
        "stock_sequence_predictor_sha256": digest_file(args.stock_root / relative_cc),
        "candidate_sequence_predictor_sha256": digest_file(
            args.candidate_root / relative_cc
        ),
        "policy_header_sha256": digest_file(args.candidate_root / relative_header),
        "semantic_patch_sha256": digest_bytes(semantic_patch),
        "build_compat_patch_sha256": digest_bytes(build_patch),
        "behavior_library_sha256": digest_file(args.behavior_library),
        "component_library_sha256": digest_file(args.component_library),
        "behavior_switch_default": False,
        "behavior_change_outside_prediction": False,
        "build_compat_behavioral_delta_between_arms": False,
    }
    atomic_bytes(
        output / "frozen_candidate_manifest.json",
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
    )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
