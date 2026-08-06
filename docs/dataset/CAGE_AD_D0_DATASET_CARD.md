# CAGE-AD D0 dataset card

Status: **engineering pilot; not yet a release-ready benchmark**  
Document version: 0.1  
Runtime target: Apollo 10 host mode + CARLA 0.9.15  
Benchmark scope: perfect-perception, planning-and-control (PnC), active diagnosis

This document describes what every D0-A0 scene, fault, companion run, and
published field means. It is also the release checklist for a future public
dataset. A batch is not promoted to a public benchmark merely because its files
exist: the reproducibility, leakage, fault-repeatability, counterfactual, license,
and checksum gates below must all pass first.

## 1. Intended use

CAGE-AD D0 studies **action-aware, cost-aware sequential diagnosis** in a
modular autonomous-driving stack. A diagnostic policy begins with limited
failure evidence, chooses legal observations or bounded interventions, pays the
measured cost of each action, updates its belief over responsibility domains,
and either returns a diagnosis or abstains.

The benchmark is intended for:

- comparing fixed and adaptive diagnostic policies under equal budgets;
- measuring selective risk against cumulative evidence cost;
- testing whether safe, non-ground-truth interventions improve localization;
- auditing abstention, wrong-singleton diagnoses, and domain-level calibration.

It is not a perception, sensor-fusion, end-to-end driving, repair, or open-road
safety benchmark. Simulator state is used by a privileged adapter to construct
perfect-perception stack input. Simulator truth is forbidden from the diagnosis
view.

## 2. Unit of analysis and dataset size

One **diagnosis episode** is one opaque scenario/fault/seed combination. Its
companion simulations provide initial evidence and counterfactual evidence; they
are not extra independent diagnosis samples.

| Stage | Scenario templates | Domains | Mechanisms per domain | Seeds | Diagnosis episodes |
|---|---:|---:|---:|---:|---:|
| D0-A0 smoke | 2 | 3 | 2 | 1 | 12 |
| D0-A1 pilot target | 2 | 3 | 2 | 3 | 36 |

Each D0-A0 episode has seven linked runtime invocations: one nominal run, three
fault-confirmation repeats, one correct-domain probe, and two wrong-domain
probes. Therefore 12 episodes require 84 runtime invocations, but the scientific
sample size remains 12.

The D0-A1 registry and split must be frozen before formal test outcomes are
viewed. Seeds and parameter variants sharing a semantic fault template and
scenario parent must not cross a split.

## 3. Common driving envelope

Both current scene templates run in CARLA Town01 on the same eastbound route:

- route start in Apollo coordinates: `(202.550003, -59.330017)`;
- destination in Apollo coordinates: `(288.237488, -59.330009)`;
- diagnostic observation window: 32 simulated seconds after the route epoch;
- ego stack: Apollo 10 routing, planning, and control in host mode;
- interaction actor: `vehicle.audi.tt`, spawned deterministically relative to
  the ego vehicle;
- stack input: a confidence-1.0 vehicle obstacle and a five-second semantic
  forecast, published by the privileged perfect-perception adapter;
- trajectory sampling: 0.2 seconds, 26 points including time zero.

The route publication defines the scene epoch. Before that epoch the interaction
actor remains stationary so Apollo startup latency does not alter the nominal,
fault, and probe initial conditions.

The current smoke failure envelope marks a run as failed if any of the following
occurs: at least one collision, minimum time-to-collision below 2.5 seconds,
route failure, or less than 5 metres of forward progress by the end of the
32-second window. These are engineering-stage D0-A0 thresholds and are not to be
retuned after inspecting a formal batch.

## 4. Scene catalogue

### 4.1 `lead_vehicle_deceleration`

**What it represents.** A same-lane longitudinal interaction in which a lead
vehicle initially moves ahead of the ego and then brakes to a stop. The scene
tests whether forecasting exposes the deceleration, whether planning respects
the changing safety envelope, and whether control executes the requested
response without excessive delay or gain error.

**Initial condition.** The actor is spawned 30 metres in front of the ego, with
zero lateral offset and the ego's heading. It begins moving when the route epoch
is observed.

**Actor programme.** The lead vehicle travels at 5 m/s until scene time 6 s,
then decelerates at 3 m/s^2 to zero. Its privileged five-second forecast follows
the same programme.

**Scientific meaning.** This is primarily a longitudinal stopping and following
case. It creates a shared observable consequence—unsafe closing or inadequate
progress—that can be caused at three different module boundaries. Diagnosis
must distinguish those causes using legal evidence rather than the simulator
programme or injected label.

**Not represented.** The scene does not model uncertain perception, multiple
lead actors, occlusion, traffic-light policy, or a naturally driven human
vehicle.

### 4.2 `cut_in_or_crossing_actor`

**What it represents.** A lateral-to-longitudinal interaction in which a nearby
vehicle begins offset from the ego lane and progressively cuts toward or across
the ego path. It tests manoeuvre/heading forecasts, a planner's treatment of a
changing lateral conflict, and the tracking layer's ability to realize a safe
response.

**Initial condition.** The actor is spawned 25 metres forward and 3.5 metres to
the ego's left, aligned with the ego heading. It begins moving when the route
epoch is observed.

**Actor programme.** Longitudinal speed is 3 m/s. Before scene time 3 s the
lateral speed is zero. From 3 s onward the commanded lateral speed ramps at
0.6 m/s^2 and is capped at 1.5 m/s toward the ego path. The semantic forecast
uses the same kinematic programme.

**Scientific meaning.** This scene makes forecast orientation and manoeuvre
shape especially relevant while retaining the same three possible
responsibility domains. A wrong-domain intervention must remain present so a
policy cannot succeed by applying every conservative action.

**Not represented.** The scene does not model negotiation, turn signals,
pedestrians, cyclist dynamics, intersection priority, or perception occlusion.

## 5. Responsibility domains and fault mechanisms

The public taxonomy describes mechanisms, but the per-episode mechanism and its
opaque identifier mapping remain evaluator-private during blind evaluation.

### 5.1 Interaction forecasting

`forecast_stale_or_delayed` represents an otherwise well-formed prediction
stream whose content is approximately two seconds old. The runtime keeps a
stateful prediction queue and releases the delayed semantic forecast. This tests
temporal freshness, not packet absence.

`forecast_heading_or_maneuver_bias` rotates forecast trajectory heading by
75 degrees and reconstructs the path from the current obstacle origin. It
represents a large but syntactically valid manoeuvre/heading error.

### 5.2 Motion planning

`planning_constraint_omitted` forces every emitted planning point to at least
10 m/s and at least 1.5 m/s^2 acceleration. It represents omission or severe
under-weighting of the interaction safety constraint.

`planning_unsafe_cost_or_speed_bias` transforms point speed to
`min(18, 3 * speed + 3)` m/s and adds 1.5 m/s^2 acceleration. It represents an
unsafe objective/cost bias while retaining the planner's trajectory structure.

### 5.3 Tracking and execution

`control_command_transport_delay` queues control messages for 3.5 simulated
seconds before release. It represents transport, scheduling, or actuator-command
latency at the execution boundary.

`control_gain_saturation_tracking_bias` maps throttle to
`min(100, 2.5 * throttle + 20)` percent, suppresses braking, and scales steering
to 0.6 of the request within a ±35 percent bound. It represents combined gain,
saturation, and tracking bias.

These mechanisms are deliberate boundary perturbations, not claims that this is
the only realistic implementation of each real-world fault class.

## 6. Companion run semantics

For each diagnosis episode:

- `nominal` uses the same scene and seed with no injected fault. It verifies that
  the base scenario is runnable and supplies a paired reference.
- `fault_repeat_0..2` repeat the same injected mechanism three times. At least
  two of three must satisfy the frozen mechanism and outcome criteria.
- `probe_interaction_forecasting` replaces the forecast temporarily with a
  constant-velocity extrapolation.
- `probe_motion_planning` applies a monotonic 2.5-second safety-envelope
  deceleration along the existing path.
- `probe_tracking_execution` applies a bounded command of 0% throttle, 60%
  brake, and 0% steering.

All probes begin at scene time 6 s and remain active for 10 s. They are
deterministic and do not inspect the ground-truth fault label. The probe matching
the injected responsibility domain is the **correct-domain counterfactual**;
the other two are required wrong-domain controls. A correct probe is not assumed
to repair a run—it must demonstrate that effect under the preregistered
evaluator.

## 7. Diagnostic action catalogue

| Action ID | Meaning | Class |
|---|---|---|
| `O0_failure_summary` | Obtain the allowed aggregate failure summary. | Observation |
| `O1_forecast_window` | Inspect a bounded semantic forecast window. | Observation |
| `O1_motion_plan_window` | Inspect a bounded motion-plan window. | Observation |
| `O1_tracking_window` | Inspect requested-versus-executed tracking evidence. | Observation |
| `O2_timing_metadata` | Obtain allowed timestamps, freshness, and latency metadata. | Observation |
| `O3_semantic_replay` | Replay the bounded semantic evidence without native-topic access. | Observation |
| `I2_F_constant_velocity` | Execute the non-GT constant-velocity forecast probe. | Intervention |
| `I2_P_safety_envelope` | Execute the non-GT conservative planning-envelope probe. | Intervention |
| `I2_C_bounded_brake` | Execute the bounded braking control probe. | Intervention |

Only the central gate may execute an action. Policies and language models may
submit typed proposals but cannot read private files or invoke runtime tools
directly. Each executed action must append its measured cost, verified evidence,
posterior update, and stop decision to the episode event log.

## 8. Data organization and field dictionary

Large data and private evaluation material are intentionally outside Git:

```text
CAGE_DATA_ROOT/<batch_id>/<episode_id>/
  visible/episode.json
  retained/<opaque_run_id>.json

CAGE_PRIVATE_ORACLE_ROOT/<batch_id>/
  episode_<episode_id>.json
  <opaque_run_id>/scenario.json
  <opaque_run_id>/injector.json
  <opaque_run_id>/metrics.json
  <opaque_run_id>/interposer_stats.json
  <opaque_run_id>/scenario_stats.json

CAGE_STATE_ROOT/
  <batch_id>_plan.json
  <batch_id>_execution.json
  evidence/<batch_id>_evaluation.json
```

`visible/episode.json` is the diagnosis-visible initial manifest:

| Field | Meaning |
|---|---|
| `episode_id` | Opaque stable identifier; it does not encode the label. |
| `scenario_template` | Opaque scene-template identifier. |
| `failure_type` | Public high-level failure class. |
| `failure_window` | Start and end of the evidence window in seconds. |
| `observable_regime` | Maximum allowed evidence regime for the episode. |
| `allowed_action_ids` | Exact actions the central gate may accept. |
| `budget_profile` | Frozen cost/token/action budget profile. |
| `seed` | Public deterministic episode seed. |
| `stack` | Evaluated ADS stack and major version. |
| `initial_evidence_refs` | References to diagnosis-visible initial evidence. |

`retained/<opaque_run_id>.json` stores allowlisted semantic traces. Forecast
samples contain elapsed time, end-horizon displacement, and predicted end
speed. Plan samples contain elapsed time, point count, and min/max speed.
Control samples contain elapsed time, throttle, brake, steering, and queued
target count. `native_topics_disclosed=false` and
`oracle_fields_present=false` are mandatory assertions, not labels.

The `retained/` traces are generator/evaluator inputs and are not part of the
policy's initial diagnosis view. The evaluator materializes separately
allowlisted action payloads under `visible/evidence/`; the central gate exposes
only the payload for an action that was legally executed and charged. A public
archive inventory may list retained file checksums, but that listing does not
change the benchmark access protocol.

The private oracle stores the semantic scene, responsibility domain, mechanism,
companion linkage, run metrics, source commit, and configuration digest. It is
root-readable only during evaluation and must never be mounted into a diagnosis
process. A future public release should publish labels in a separate archive
only after the benchmark's blind test period or under a clearly documented
access policy.

## 9. Provenance and reproducibility

Every published batch must bind all results to:

- the exact CAGE-AD source commit;
- Apollo, CARLA, bridge, map, and host-runtime versions;
- SHA-256 of the scenario, fault, action, threshold, budget, and split
  registries;
- SHA-256 of every visible manifest and released data object;
- the batch preparation, execution, and evaluation commands;
- an append-only invalid/retry/failure ledger;
- powered-on hours and incremental storage consumption.

After a batch reaches runtime `PASS`, `scripts/d0/build_public_manifest.py`
creates a deterministic, content-addressed public index using only
`CAGE_DATA_ROOT`, the resumable state checkpoint, and this repository. Its
interface deliberately accepts no private-oracle root. It refuses incomplete
batches, missing companions, symlinks, and evaluator-only keys in public JSON.

The reproducible unit is the full linked episode, not an isolated trace. A
release manifest must preserve the nominal/fault/probe relationships without
allowing those relationships to leak the answer to a policy.

## 10. Quality gates before public release

A candidate release must pass all of the following without changing labels,
splits, budgets, thresholds, or evaluation rules after test inspection:

1. all required runtime invocations complete with required metrics, semantic
   capture, scenario stats, and interposer stats;
2. each fault is active and repeatable under the frozen criteria;
3. nominal runs satisfy the frozen nominal envelope;
4. correct-domain and wrong-domain probes are both retained and evaluated;
5. reruns reproduce semantic checksums or declared numerical tolerances;
6. forbidden-key, forbidden-path, oracle-token, secret, and native-topic scans
   report zero diagnosis-view leakage;
7. a clean-shell replay reproduces the published aggregate results;
8. every file is listed with byte size, media type, and SHA-256;
9. dependency and redistribution rights are reviewed by a human maintainer;
10. known invalid and failed attempts remain documented rather than silently
    removed.

## 11. Ethics, privacy, and safety

The current data are synthetic and are not expected to contain people,
biometrics, personal identifiers, or public-road recordings. This does not make
the benchmark a safety certification. The interventions are bounded research
probes executed only in simulation. Results must not be used to justify
deployment of an automated repair or intervention mechanism on a real vehicle.

## 12. Licensing and redistribution

No dataset license has been selected yet, and this repository currently contains
no license grant. Therefore neither this pilot nor the future dataset should be
described as open source until the maintainer adds an explicit code license and
dataset/data license.

Apollo, CARLA, map, bridge, vehicle model, and other third-party artifacts retain
their own licenses. The source-only repository and planned semantic release must
not redistribute third-party binaries, maps, raw records, or assets unless the
relevant license has been reviewed and permits it. The release process should
ship checksums and acquisition instructions when redistribution is not allowed.

## 13. Known limitations of the D0-A0 pilot

- only two deterministic traffic templates and one seed are present;
- perfect perception removes sensing and tracking uncertainty;
- the route is a single Town01 straight-road envelope;
- boundary perturbations are intentionally strong engineering probes;
- 12 episodes support pilot intervals, not broad significance claims;
- repeated simulations share semantic parents and are not independent samples;
- current engineering batches may fail the preregistered scientific gate;
- a passing smoke gate would validate the generator, not establish real-world
  external validity.

## 14. Citation and contact placeholders

A public release must add a versioned DOI or archival URL, authors, maintainer
contact, publication date, license identifiers, and a citation file. Until then,
cite the exact Git commit and batch manifest SHA rather than an unversioned
dataset name.

## 15. Release-history policy

Each published revision should document added or removed semantic groups,
changed generator code, invalidated checksums, and compatibility with earlier
splits. Failed engineering batches remain in the private/state provenance ledger
and are summarized in release notes. They are never relabelled or discarded to
improve benchmark results.
