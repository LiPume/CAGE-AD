# D0-1 contracts/state/verifier checkpoint

Status: implementation complete; clean-shell gate audit passed.

Implemented:

- Strict Pydantic models and checked-in JSON Schemas for `EpisodeSpec`, `DiagnosticState`, `ActionProposal`, `VerifiedEvidence`, and `DiagnosisResult`.
- Multidimensional atomic budget reservations/commit/rollback and a verified evidence ledger.
- Normalized deterministic Bayesian belief state and prediction sets.
- Hash-chained append-only JSONL events, state snapshots, crash replay, and intervention idempotency receipts.
- A single central execution gate; policies receive only state/catalog and cannot own executors.
- JSON checksum/provenance verification, forbidden-key/path rejection, and evaluator-private UID boundary tests.
- A separate evaluator entry point that requires a diagnosis-exited marker.

Scientific boundary: these are synthetic CPU fixtures only. They establish protocol invariants, not Apollo D0 fault stability or diagnosis accuracy.

Verification command:

```bash
env -i HOME=/root USER=root LOGNAME=root LANG=C.UTF-8 \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  /path/to/cage-ad-py310/bin/python -m pytest -q
```

Result before gate commit: 37 passed; source audit passed. The commit-bound replay is recorded in the external D0 state root after commit.
