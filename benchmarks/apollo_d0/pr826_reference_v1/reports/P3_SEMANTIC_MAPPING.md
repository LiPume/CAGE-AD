# P3 semantic mapping — historical PR #826 to pinned Apollo 10

Status: `P3_SEMANTIC_FIXTURE_PASS`
Recorded: 2026-08-29T11:25:00Z
Pinned application-pnc commit: `d994e55fb3c3cf88222f8b4813fa5425cc7c1f56`
Pinned `sequence_predictor.cc` SHA256: `8c8ad816ac7aff8caefcd873f8f7c07378e1a678817854fb4d9bd1af14ec4bb5`

## Research boundary

This document maps a historical responsibility semantic to the pinned Apollo 10 execution chain.
It does not claim source equivalence with 2017, does not alter Planning, Control, CARLA, bridge or
map behavior, and does not authorize a CARLA faulty run.  The candidate port can be frozen only
after the function-level target and negative controls pass.

## Historical semantic

Apollo PR [#826](https://github.com/ApolloAuto/apollo/pull/826), merged 2017-10-25, contains one
repair commit,
[`92b7434c4656555d8350fc051e5d1d5c32897db6`](https://github.com/ApolloAuto/apollo/commit/92b7434c4656555d8350fc051e5d1d5c32897db6).
The parent implementation disabled a lane sequence whenever
`GetLaneChangeDistanceWithADC(sequence) < FLAGS_lane_change_dist`; it had skipped only `INVALID`
types.  The repair added a `LEFT || RIGHT` maneuver-type requirement.  The fault family is thus:

> A proximity filter intended for genuine lane-change candidates is applied too broadly to a
> valid non-lane-change candidate, causing that candidate to be removed.

This mapping preserves that responsibility semantic rather than copying the 2017 expression.

## Pinned Apollo 10 execution chain

The source of record is the installed, pinned tree under
`.aem/envroot/opt/apollo/neo/src/modules/prediction`.

1. `PredictionComponent` receives perception and the latest Localization, Storytelling and prior
   Planning data, then delegates a perception cycle to `MessageProcess`.
2. `ObstaclesContainer::BuildLaneGraph` calls `Obstacle::BuildLaneGraph`.  A moving on-lane target
   receives current- and nearby-lane sequences; a still target is deliberately skipped.
3. The installed `prediction_conf.pb.txt` maps a normal, on-lane `VEHICLE` to
   `CRUISE_MLP_EVALUATOR` and `MOVE_SEQUENCE_PREDICTOR`.  P2 native logs identify target 1001 as a
   normal obstacle evaluated by `CRUISE_MLP_EVALUATOR`.
4. The evaluator assigns lane-sequence probabilities.
5. `MoveSequencePredictor::Predict` initializes every candidate enabled, calls
   `SequencePredictor::FilterLaneSequences`, and draws trajectories only for candidates that
   remain enabled.
6. `PredictorManager::PredictObstacle` copies the selected predicted trajectories into the
   published `PredictionObstacle`; Planning consumes `/apollo/prediction`.

The fault responsibility point is therefore the candidate-eligibility gate in
`SequencePredictor::FilterLaneSequences`, before final trajectory generation.

## Apollo 10 stock predicate

For each non-parking candidate, Apollo 10 first classifies `LaneChangeType`.  Only `LEFT`, `RIGHT`
and `ONTO_LANE` enter the proximity branch.  `STRAIGHT` and `INVALID` continue without proximity
filtering.  A proximity-eligible candidate is disabled only when all remaining guards hold:

- the sequence overlaps the ADC trajectory;
- signed obstacle-to-ADC lane distance is positive and below `FLAGS_lane_change_dist` (10 m);
- every target polygon point remains within the obstacle's own lane.

Later logic preserves the most-probable candidate, applies probability thresholds, and removes a
conflicting lower-probability lane-change direction.

## Candidate semantic port

The smallest proposed change is to the *eligibility* predicate only:

```text
fixed eligibility  = LEFT | RIGHT | ONTO_LANE
faulty eligibility = LEFT | RIGHT | ONTO_LANE | STRAIGHT
```

No other predicate or downstream selector changes.  Consequently, a valid high-probability
`STRAIGHT` candidate can be incorrectly removed only when the existing Apollo 10 overlap,
positive-nearby-distance and own-lane-polygon guards all hold.  This is in the PR #826 semantic
family because the delta is precisely the missing maneuver-type restriction on a nearby-candidate
filter.  It is not a replay of the 2017 source.

## 2017 versus Apollo 10

| Concern | 2017 repaired implementation | Pinned Apollo 10 |
|---|---|---|
| Maneuver protection | inline `LEFT || RIGHT` condition | early eligibility gate admits `LEFT`, `RIGHT`, `ONTO_LANE` |
| Signed distance | only `< lane_change_dist` visible in repaired hunk | requires `distance > 0` and `< lane_change_dist` |
| ADC relation | lane-change distance helper | explicit sequence overlap before signed projection |
| Obstacle geometry | absent from repair hunk | all polygon points must remain in the obstacle's own lane |
| Parking | no corresponding repair-hunk guard | parking candidates disabled first |
| Later selection | older selector | max-probability, threshold and conflicting-side filtering |
| Output hardening | older pipeline | modern trajectory generation and trimming remain intact |

The proposed port deliberately retains every modern guard above and changes only the type domain
eligible for the same near-ADC filter.

## Fixture contract before patch freeze

The fixture must use the same pure eligibility predicate as the production patch seam and record
candidate ID, sequence, probability, lane-change type, overlap, signed ADC distance,
polygon-in-own-lane result, enabled-before/after, final selected candidate and final trajectories.

- Target condition: a high-probability `STRAIGHT` candidate at +5 m, overlapping the ADC path and
  fully in its own lane remains enabled in fixed mode and is disabled in candidate faulty mode.
- Identity: instrumented fixed mode is byte-for-byte equal to the stock semantic result.
- Wrong condition: distance at/above 10 m, distance at/below zero, no overlap, polygon outside own
  lane, parking and invalid candidates produce no fixed/faulty delta.
- Reversibility: switching candidate mode off restores the exact fixed result.

The frozen fixture subsequently passed all four controls and produced machine-readable
fixed/faulty/diff artifacts.  The resulting semantic patch SHA256 is
`f00cd04565564e85b22b6f4bdabb58c907b6c14044e9ea1d624575d09ac718b6`; see
`P3_SEMANTIC_FIXTURE_REPORT.md` for the complete gate audit.

## Modern guards that may compensate at runtime

- The target may lack a `STRAIGHT` candidate or may not overlap the ADC trajectory.
- Its signed distance may not enter `(0, 10)` m while the predicate is evaluated.
- The polygon may extend outside its own lane, retaining the candidate.
- Evaluator probabilities or another surviving candidate may yield an equivalent final trajectory.
- Candidate sets are rebuilt in subsequent Prediction cycles.
- Trajectory validation/trimming may erase or mask the candidate delta.
- Planning may be insensitive to the changed target trajectory.
- The admitted P2 route-driven lane change may dominate obstacle interaction.

These are P4 hypotheses, not reasons to broaden the P3 fault dose.  If the frozen fixture-valid port
is compensated, the result must be classified according to the observed causal stage rather than
strengthened after seeing vehicle behavior.

## Sources

- Local pinned source: `modules/prediction/predictor/sequence/sequence_predictor.cc`, especially
  lines 58–178 and 181–231.
- Local pinned source: `modules/prediction/predictor/move_sequence/move_sequence_predictor.cc`,
  especially lines 38–113.
- Local pinned source: `modules/prediction/container/obstacles/obstacle.cc`, lines 804–906.
- Local pinned source: `modules/prediction/predictor/predictor_manager.cc`, lines 130–298.
- Local pinned config: `modules/prediction/conf/prediction_conf.pb.txt`, lines 77–83.
- [Apollo PR #826](https://github.com/ApolloAuto/apollo/pull/826).
- [Historical repair commit](https://github.com/ApolloAuto/apollo/commit/92b7434c4656555d8350fc051e5d1d5c32897db6).
- [Apollo 10 Prediction configuration source](https://apollo.baidu.com/docs/apollo/10.x/conf_2prediction__conf_8pb_8txt_source.html).
- [Apollo Prediction predictor documentation](https://github.com/ApolloAuto/apollo/blob/master/docs/07_Prediction/prediction_predictor.md).
- [Apollo Planning class architecture](https://github.com/ApolloAuto/apollo/blob/master/docs/07_Prediction/Class_Architecture_Planning.md).

