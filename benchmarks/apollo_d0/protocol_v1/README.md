# Apollo D0 literature-grounded generation protocol v1

This directory is the normative source for the next CAGE-AD data-generation iteration. The files under
`../draft/` describe the failed `d0_a0_repaired_v3` pilot and remain as provenance; they must not be silently
overwritten or treated as the specification for new data.

Read in this order:

1. `literature_provenance.yaml`: which construction rule comes from which paper or artifact;
2. `scenario_recipes.yaml`: deterministic scenario candidates and their search order;
3. `fault_recipes.yaml`: injection boundary, target, trigger, duration, dose grid and activation signature;
4. `probe_recipes.yaml`: the three deterministic, non-fault-aware responsibility-domain probes;
5. `episode_recipes.yaml`: the exact 12 calibration items to build;
6. `quality_gates.yaml`: admission, ambiguity and rejection rules;
7. `docs/dataset/CAGE_AD_D0_GENERATION_PROTOCOL.md`: executable human runbook.

The 12 entries are **calibration recipes**, not 12 already-valid benchmark samples. A recipe becomes a formal
episode parent only after its nominal, activation, causal-degradation and selectivity gates pass. Parameters are
searched only in the listed order and only on calibration seeds. The selected candidate and dose are then frozen
before any formal seed is run.

Server implementations must fail closed when a required field or semantic boundary is unavailable. They may not
replace an unavailable operation with a “similar” fault, invent a new threshold, change the candidate order, or
drop a failed attempt without recording it in the append-only ledger.
