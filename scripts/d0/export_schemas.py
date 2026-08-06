#!/usr/bin/env python3
"""Export the five public Pydantic contracts as deterministic JSON Schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cage_ad.active_diagnosis.contracts import (
    ActionProposal,
    DiagnosisResult,
    DiagnosticState,
    EpisodeSpec,
    VerifiedEvidence,
)


MODELS = (EpisodeSpec, DiagnosticState, ActionProposal, VerifiedEvidence, DiagnosisResult)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        path = args.output_dir / f"{model.__name__}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
