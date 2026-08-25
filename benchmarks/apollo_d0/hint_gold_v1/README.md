# HINT-style one-gold-case protocol

This protocol constructs failure cases before any active-diagnosis experiment.
It never enumerates a scene/fault Cartesian product and never uses a probe or an
Agent result to decide whether a failure case exists.

For the first case, run exactly three reference companions and three faulty
companions.  Retain the pair only when all reference runs are valid and safe,
all faulty runs are valid failures, the semantic mutation is confirmed in every
faulty run, activation precedes failure by at most five seconds, and the visible
tree passes oracle-leakage audit.

The initial candidate is a planning threshold mutation in a lead-vehicle braking
scene.  If it does not pass unchanged, reject this scene/fault pair and choose a
new functional scene; do not strengthen the dose after seeing results.
