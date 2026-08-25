# HINT-style one-gold-case protocol

This protocol constructs failure cases before any active-diagnosis experiment.
It never enumerates a scene/fault Cartesian product and never uses a probe or an
Agent result to decide whether a failure case exists.

For the first case, run exactly three reference companions and three faulty
companions.  Retain the pair only when all reference runs are valid and safe,
all faulty runs are valid failures, the semantic mutation is confirmed in every
faulty run, activation precedes failure by at most five seconds, and the visible
tree passes oracle-leakage audit.

Use one matched reference/faulty pair as an early screen before spending the
remaining four repeats.  If either mechanism activation or behavioral
degradation is absent, preserve and reject that candidate unchanged, then freeze
a new functional scene/fault pair.  Only a positive screen proceeds to the full
three-plus-three admission run.

Candidate 01 is a Planning threshold mutation in a lead-vehicle braking scene.
Candidate 02 is a separately frozen cut-in case using the protocol-v1 semantic
Planning time-compression transform.  They are distinct candidates; candidate
02 is not a post-result dose change to candidate 01.

Candidate 03 pairs the frame-stable LBC1 lead-braking scene with protocol-v1's
braking-constraint omission transform.  It is selected because the mutation
acts specifically on a nominal negative-acceleration suffix; its screening and
admission rules remain identical.

Candidate 04 keeps frame-stable LBC1 but uses candidate 02's already declared
time-compression mechanism.  This tests a distinct scene/fault pairing after
candidate 03 established that LBC1 had no meaningful braking suffix to omit.
