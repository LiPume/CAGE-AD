# D0 changelog

## D0-0 — source-only G0 checkpoint

- Preserved the three D0 design documents byte-for-byte with SHA-256 checks.
- Collected the actual G0 scripts, launch/config, platform-neutral contracts, conformance fixtures, report, runbook, bridge audit, and version lock.
- Recorded pinned Apollo, CARLA, and bridge provenance; generated textual patches and verified both against clean upstream commits.
- Excluded runtime binaries, raw data, private oracle, logs/dumps, credentials, and all historical Zhijia-Guardian source/data/results.
- Removed the historical package import from the copied A2 golden diagnostic and made the source checkpoint self-contained.
- Passed the secret/large/private-material audit and four CPU-only checkpoint tests.
