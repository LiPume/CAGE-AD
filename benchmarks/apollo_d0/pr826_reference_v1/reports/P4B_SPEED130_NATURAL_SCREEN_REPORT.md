# P4B speed-1.30 native screen report

Status: `SCENE_FAULT_PAIR_NOT_ADMITTED`

## Matched outcome

- Fixed `QZ0_A`: overtake, +14.272 m maximum pass margin.
- Active `QZ1_A`: overtake, +13.185 m maximum pass margin.
- Both arms were runtime/transport valid, collision-free and free of illegal lane invasion.
- Manifest comparison passed; the only behavioral difference was
  `private_prediction_runtime.domain_active`.

## Mechanism result

L0 passed: active Prediction executed 1,532 expanded STRAIGHT eligibility events. Forty-three
expanded candidates overlapped the ADC trajectory and ten entered the unchanged `(0,10 m)`
distance guard.

L1 failed: all ten nearby candidates had `polygon_in_own_lane=0`, remained enabled, and produced
zero erroneous disables. Their signed distances were 9.455–9.969 m. The modern own-lane polygon
guard therefore compensated the expanded maneuver-domain predicate.

The generic output detector counted 38 active versus 36 fixed lateral-signature frames, and
Planning consumed 35 active signature sequences with nine response-delta frames. These differences
are not attributed to the PR826 port because the required L1 candidate-set delta did not occur.
L4 also failed because the active vehicle completed the overtake and reached the success region.

## Conclusion

Classification: `CANDIDATE_SEMANTIC_DELTA_ABSENT`. The speed-1.30 pair is closed without changing
the fault predicate or oracle. The evidence indicates a timing mismatch: the target enters the
nearby-distance guard only after its polygon has left its own lane. Any next scene candidate must be
designed normal-only and target that guard ordering, then pass fixed screening and 3/3 before a new
active result. This report does not establish a natural PR826 failed-overtake case.

Machine audit: `P4B_SPEED130_NATURAL_SCREEN_AUDIT.json` (SHA256
`49799e867e2bb8f6d799b276e47c870f9c13c7478c20bca929c1014632aeeb3c`).
