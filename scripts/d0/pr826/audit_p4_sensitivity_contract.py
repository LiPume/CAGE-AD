#!/usr/bin/env python3
"""CLI writer for the version-independent persistent sensitivity audit core."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

from p4_sensitivity_audit_core import audit_pair


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--s0", type=Path, required=True)
    parser.add_argument("--s1", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_bytes())
    result = audit_pair(contract, args.contract, args.s0, args.s1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
