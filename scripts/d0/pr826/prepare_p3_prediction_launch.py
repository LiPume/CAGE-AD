#!/usr/bin/env python3
"""Prepare a private Apollo Prediction launch with an opaque semantic switch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(value)
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--component", type=Path, required=True)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--domain-active", action="store_true")
    parser.add_argument("--trace-active", action="store_true")
    parser.add_argument(
        "--apollo-root",
        type=Path,
        default=Path(
            "/root/autodl_apollo10_g0_bundle/runtime/apollo/application-pnc/"
            ".aem/envroot/opt/apollo/neo"
        ),
    )
    args = parser.parse_args()
    if not args.component.is_file():
        raise FileNotFoundError(args.component)
    if not args.library_dir.is_dir():
        raise NotADirectoryError(args.library_dir)

    share = args.apollo_root / "share"
    stock_flagfile = share / "modules/prediction/conf/prediction.conf"
    stock_conf = share / "modules/prediction/conf/prediction_conf.pb.txt"
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    private_flagfile = output / "q1.conf"
    contents = stock_flagfile.read_text()
    contents += "\n--s3_domain_v1={}\n--s3_trace_v1={}\n".format(
        "true" if args.domain_active else "false",
        "true" if args.trace_active else "false",
    )
    atomic_text(private_flagfile, contents)

    dag = output / "q1.dag"
    atomic_text(
        dag,
        """module_config {
    module_library: \"%s\"
    components {
        class_name: \"PredictionComponent\"
        config {
            name: \"prediction\"
            config_file_path: \"%s\"
            flag_file_path: \"%s\"
            readers: [{ channel: \"/apollo/perception/obstacles\" qos_profile: { depth: 1 } }]
        }
    }
}
"""
        % (args.component.resolve(), stock_conf.resolve(), private_flagfile.resolve()),
    )
    launch = output / "q1.launch"
    atomic_text(
        launch,
        """<cyber>
  <module>
    <name>prediction</name>
    <dag_conf>%s</dag_conf>
    <process_name>prediction</process_name>
  </module>
</cyber>
"""
        % dag.resolve(),
    )

    metadata = {
        "schema_version": 1,
        "component": str(args.component.resolve()),
        "component_sha256": sha256(args.component),
        "behavior_library": str((args.library_dir / "libapollo_prediction.so").resolve()),
        "behavior_library_sha256": sha256(
            args.library_dir / "libapollo_prediction.so"
        ),
        "domain_active": args.domain_active,
        "trace_active": args.trace_active,
        "stock_flagfile_sha256": sha256(stock_flagfile),
        "stock_prediction_conf_sha256": sha256(stock_conf),
        "launch": str(launch),
        "dag": str(dag),
        "private_flagfile": str(private_flagfile),
        "library_dir": str(args.library_dir.resolve()),
    }
    atomic_text(output / "launch_metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print(json.dumps(metadata, sort_keys=True))


if __name__ == "__main__":
    main()
