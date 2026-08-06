"""Environment-only runtime path resolution with private-root separation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    runtime_root: Path
    state_root: Path
    data_root: Path
    private_oracle_root: Path

    @classmethod
    def from_environment(cls) -> "RuntimePaths":
        names = (
            "CAGE_RUNTIME_ROOT",
            "CAGE_STATE_ROOT",
            "CAGE_DATA_ROOT",
            "CAGE_PRIVATE_ORACLE_ROOT",
        )
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"missing required runtime roots: {', '.join(missing)}")
        paths = cls(*(Path(os.environ[name]).expanduser().resolve() for name in names))
        paths.assert_separated()
        return paths

    def assert_separated(self) -> None:
        public = (self.runtime_root, self.state_root, self.data_root)
        private = self.private_oracle_root
        for root in public:
            if root == private or root in private.parents or private in root.parents:
                raise ValueError("private oracle root must not overlap public roots")

    def ensure_directories(self) -> None:
        for root in (self.runtime_root, self.state_root, self.data_root):
            root.mkdir(parents=True, exist_ok=True, mode=0o750)
        self.private_oracle_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.private_oracle_root.chmod(0o700)
