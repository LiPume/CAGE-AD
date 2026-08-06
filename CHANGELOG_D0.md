# D0 changelog

## D0-0 — source-only G0 checkpoint

- Preserved the three D0 design documents byte-for-byte with SHA-256 checks.
- Collected the actual G0 scripts, launch/config, platform-neutral contracts, conformance fixtures, report, runbook, bridge audit, and version lock.
- Recorded pinned Apollo, CARLA, and bridge provenance; generated textual patches and verified both against clean upstream commits.
- Excluded runtime binaries, raw data, private oracle, logs/dumps, credentials, and all historical Zhijia-Guardian source/data/results.
- Removed the historical package import from the copied A2 golden diagnostic and made the source checkpoint self-contained.
- Passed the secret/large/private-material audit and four CPU-only checkpoint tests.

## D0-1 — diagnosis contracts and state engine

- Added five strict Pydantic contracts and matching checked-in JSON Schemas.
- Added catalog legality, undeclared-parameter rejection, atomic multidimensional budgets, evidence and belief ledgers.
- Added hash-chained append-only events, crash replay, durable intervention idempotency keys, and state snapshots.
- Made the central gate the only owner of executors; policy interface remains proposal-only.
- Added deterministic payload checksum/provenance verification and forbidden-key/path isolation.
- Added an evaluator-only process entry requiring proof that diagnosis has exited.
- Added independent Python 3.10 environment lock and synthetic unit/property/security tests.
