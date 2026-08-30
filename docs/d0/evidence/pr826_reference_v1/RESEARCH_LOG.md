# Failed-overtake normal-reference research log

Append-only laboratory log. Prior failed runs remain authoritative evidence and are never
overwritten. All timestamps are UTC unless a source log explicitly records another timezone.

## Issue P2D-001 — RF01 nominally identical runs diverge before stable admission

Timestamp: 2026-08-29T05:50:00Z

现象：

`P2_REFERENCE_05_RF01_01` completed the frozen overtake oracle once, while
`P2_REFERENCE_06_RF01_01_REPEAT_1` did not. Both runs used RF01_01, seed 82601, a stationary
target, a 45-second observation window, and the same frozen registry and runtime hashes.

证据：

- Success: pass margin +6.118 m, lateral excursion 2.683 m, 887/912 valid Planning messages.
- Failure: pass margin -11.225 m, lateral excursion 1.319 m, 582/902 valid Planning messages.
- Both: route accepted, no collision, identity relay exact, target Prediction present.
- Both: `target_prediction_with_trajectory = 0`, so neither is yet a valid
  Prediction-trajectory-to-Planning reference.
- Source files: each run's `summary.json`, `stack.log`, frozen manifest, and generated configs.

当前假设：

- H1: LaneBorrow state/counter/path-selection first diverged.
- H2: Prediction/Localization/Chassis timing or message combination first diverged.
- H3: CARLA reload/startup/physics state was not fully deterministic.
- H4: the stationary target was classified as still/static and bypassed trajectory generation.
- H5: Prediction still and Planning static thresholds make a stationary scene unsuitable for the
  intended Prediction-to-Planning mechanism.

联网检索：

Pending. Official Apollo 10 source/documentation and CARLA determinism documentation will be
recorded in follow-up entries before changing scene parameters.

计划实验：

First perform a read-only timeline comparison of the retained runs. Then add the minimum native
Planning/input instrumentation needed to expose the first divergent cycle. Debug runs are not
admission evidence. No scene or oracle change is authorized in P2-D.

修改：

No runtime/config modification yet. Created this append-only log and `FIX_LEDGER.jsonl`.

实验结果：

INCONCLUSIVE — historical summaries show divergence but do not expose native LaneBorrow state.

结论：

The prior `CASE_NOT_ADMITTED` decision remains valid for that repeat set, but the underlying
cause is unresolved. The project is resumed under the user's new P2-D protocol.

下一步：

Extract the earliest differences from samples and Planning logs, and inventory Apollo 10's real
status/debug fields before adding instrumentation.

## Issue P2D-001 follow-up — first observable divergence is speed fallback, not LaneBorrow entry

Timestamp: 2026-08-29T05:56:20Z

现象：

The retained native Planning logs show that both runs entered LaneBorrow. The failure run then
lost longitudinal progress much earlier than the successful run.

证据：

- Success native log:
  `runtime/apollo/application-pnc/data/log/planning.log.INFO.20260829-112013.29042`,
  152,026,933 bytes, SHA-256
  `f107d4eab5d7995cd809a6315b36fe5ecf7d0c3826f922b47467d28fa10cf62a`.
- Both logs contain exactly one `Switch from SELF-LANE path to LANE-BORROW path.` transition.
  Success logged it at 11:20:58.556694; failure at 11:24:56.138219.
- Relative to that transition, the failure's first PiecewiseJerk speed optimizer failure occurs at
  approximately +12.646 s and is immediately followed by speed fallback. The successful run's
  first corresponding failure occurs only around +23.14 s.
- The failing optimizer reports an initial state with negative longitudinal speed and strong
  deceleration (representative values: `init_s 0,-0.223348,-2.24728`) and OSQP reports
  `primal infeasible`; the relaxed retry also fails.
- At approximately 12.5--15 s after the run observation starts, the successful actor remains near
  0.84 m/s, while the failed actor falls to approximately 0.056 m/s by 15 s.
- Sampled ego-position deltas first exceed 0.01 m at 1.65 s, 0.05 m at 3.4 s, 0.10 m at
  12.25 s, 0.25 m at 12.85 s, 0.50 m at 13.15 s, and 1.0 m at 13.8 s.
- Success counts: 23 PiecewiseJerk speed failures/fallbacks, 615 LaneFollow path-bound failures,
  12 LaneFollow path-optimization failures. Failure counts: 15, 464, and 9 respectively. These
  totals show that both executions are marginal; totals alone do not identify the cause.

当前假设：

- H1a rejected: gross behavior did not diverge because only one run entered LaneBorrow.
- H1b: after entering LaneBorrow, different initial longitudinal states or constraint inputs make
  the failing run's speed QP infeasible first.
- H2 remains: the different longitudinal state may originate in a different synchronized
  Prediction/Localization/Chassis combination or planning-cycle schedule.
- H3 remains: CARLA/Apollo startup timing may perturb the closed-loop state before the optimizer
  divergence.

联网检索：

- Query: `Apollo Piecewise jerk speed optimizer primal infeasible fallback`.
- Source: ApolloAuto/apollo issue #12896,
  https://github.com/ApolloAuto/apollo/issues/12896 (accessed 2026-08-29 UTC).
- 关键结论: an older Apollo report exhibits the same broad chain, optimizer infeasibility followed
  by fallback/planning failure. It is corroborative symptom evidence only, not Apollo 10 authority.
- Source: pinned Apollo 10 source,
  `modules/planning/tasks/piecewise_jerk_speed/piecewise_jerk_speed_optimizer.cc`.
- 关键结论: current code checks/adjusts the initial state, retries a failed OSQP solve with relaxed
  velocity bounds, and returns an error for upstream fallback if the retry still fails.
- 可信度: high for local source semantics; low-to-medium for the older issue's applicability.

计划实验：

Capture the exact Planning debug input headers, scenario/stage, selected path/speed-plan names,
task latency/status, and CARLA state for every raw Planning message. Align on simulation time, not
wall-clock line order, and identify the first input/state difference preceding the first fallback.

修改：

No behavior modification. This follow-up records a read-only comparison.

实验结果：

INCONCLUSIVE — the first observable decision/optimizer divergence is localized, but the first
causal input divergence is not observable in the old summaries.

结论：

The old failure is not explained by failure to enter LaneBorrow. The earliest meaningful visible
branch is the failed run's early speed-optimizer infeasibility/fallback around +12.65 s. Native
input-timeline instrumentation is required to trace one step earlier.

下一步：

Audit deterministic setup, then instrument Planning debug inputs and rerun RF01 in debug-only mode.

## Issue P2D-002 — existing bridge startup does not implement CARLA's deterministic reload recipe

Timestamp: 2026-08-29T05:56:20Z

现象：

RF01 uses synchronous mode and a fixed 0.05 s step, but the bridge applies those settings only
after loading the town. It does not explicitly freeze physics substepping, and its synchronous
tick thread begins before asynchronous ego-object setup completes.

证据：

- Generated bridge config freezes `synchronous_mode: True`, `fixed_delta_seconds: 0.05`, and
  `realtime_factor: 1.0`.
- `runtime/bridge/apollo-carla/carla_bridge/main.py` calls
  `load_world(requested_town, reset_settings=True)` before `initialize_bridge()` applies sync/fixed
  settings.
- `initialize_bridge()` temporarily disables synchronous mode if the world is already synchronous,
  then applies settings again.
- No experiment config currently records `substepping`, `max_substep_delta_time`, or
  `max_substeps`.
- The RF01 scene does not use Traffic Manager. The target is spawned directly and its policy is
  fixed; therefore TM sync/seed is not an active source but must be recorded as `used: false`.

当前假设：

- H3a: load-before-sync permits a non-frozen initial physics/startup state.
- H3b: implicit/default substepping is stable on this image but not auditable.
- H3c: spawning the ego after the tick loop begins creates a variable spawn frame even if actor
  order is nominally identical.
- H3d: Apollo at 20 Hz wall-clock pacing (`realtime_factor=1.0`) may receive different scheduling
  combinations even when CARLA frames are deterministic.

联网检索：

- Query: `CARLA 0.9.15 deterministic synchronous simulation reload_world substepping`.
- Source: CARLA 0.9.15 official synchrony/time-step documentation,
  https://carla.readthedocs.io/en/0.9.15/adv_synchrony_timestep/ (accessed 2026-08-29 UTC).
- 关键结论: CARLA recommends synchronous mode plus a fixed delta; only one client should tick;
  physics determinism requires synchronous mode before loading/reloading, reloading for each
  repetition, and batch-synchronous commands. It also requires
  `fixed_delta_seconds <= max_substep_delta_time * max_substeps`, with physics substeps ideally no
  larger than 0.01 s.
- Query: `CARLA 0.9.15 Traffic Manager deterministic seed synchronous reload`.
- Source: CARLA 0.9.15 official Traffic Manager documentation,
  https://carla.readthedocs.io/en/0.9.15/adv_traffic_manager/ (accessed 2026-08-29 UTC).
- 关键结论: a used TM must be synchronous and its deterministic seed must be reset after reload.
  RF01 does not use TM, so the relevant audit value is explicitly `used: false`.
- Source: CARLA GitHub discussion #6082,
  https://github.com/carla-simulator/carla/discussions/6082 (accessed 2026-08-29 UTC).
- 关键结论: users report residual apparent nondeterminism; the discussion reinforces using the
  official determinism tests and checking substepping. Community evidence, not a guarantee.
- Source: CARLA GitHub issue #2789,
  https://github.com/carla-simulator/carla/issues/2789 (accessed 2026-08-29 UTC).
- 关键结论: older versions had reload/TM synchronous-mode interactions. Not directly applicable
  because RF01 uses no TM, retained as a negative-scope check.
- 可信度: high for the official 0.9.15 guidance; medium/low for community reports.

计划实验：

Implement one minimal deterministic-startup change set: explicitly apply sync/fixed/substep
settings, reload the world while preserving them, verify the post-reload values, and record spawn
frame/order. Keep scene geometry, oracle, and Apollo configuration unchanged. First run a bridge
smoke probe; then perform P2-D debug-only repeats.

修改：

Not yet applied. This entry freezes the rationale before observing new run results.

实验结果：

FAIL (configuration audit) — the retained RF01 setup does not meet the full documented
deterministic recipe, so comparing more old-protocol repeats would not isolate Planning behavior.

结论：

H3 is credible and must be corrected before P2-D repetitions. This is an infrastructure fix, not a
success-oracle or scene change.

下一步：

Add auditable deterministic settings/reload support and per-cycle provenance instrumentation.

## Issue P2D-003 — stationary RF01 cannot satisfy the Prediction trajectory mechanism gate

Timestamp: 2026-08-29T05:56:20Z

现象：

The target is present in Prediction in both retained RF01 runs but has no predicted trajectory in
any target frame.

证据：

- Both retained summaries report `target_prediction_with_trajectory = 0`.
- Pinned Apollo 10 Prediction defines `still_obstacle_speed_threshold` as 0.99 m/s in
  `modules/prediction/common/prediction_gflags.cc` and branches on `Obstacle::IsStill()` in
  `modules/prediction/predictor/predictor_manager.cc`.
- Pinned Apollo 10 Planning defines `static_obstacle_speed_threshold` as 0.5 m/s in
  `modules/planning/planning_base/gflags/planning_gflags.cc`; path-bound logic ignores obstacles
  faster than this static threshold.
- The old target policy is 0 m/s, so it lies unambiguously in both still/static regimes.

当前假设：

- H4 is strongly supported for the exact old scenario: a zero-speed target is intentionally treated
  as still/static and is therefore unsuitable for a required trajectory-bearing Prediction case.
- H5 is supported as a future search constraint: a simple speed choice cannot simultaneously be
  above the stock Prediction still threshold (0.99) and below the stock Planning static threshold
  (0.5). A slow-moving scenario may need a stock slow-vehicle behavior path or a frozen, explicitly
  configured Planning threshold.

联网检索：

- Query: `Apollo lane borrow static obstacle Apollo 10 source`.
- Source: Apollo current official source,
  https://github.com/ApolloAuto/apollo/blob/master/modules/planning/tasks/lane_borrow_path/lane_borrow_path.cc
  (accessed 2026-08-29 UTC).
- 关键结论: LaneBorrow checks single reference line, ADC speed, intersection clearance,
  long-term blocking-obstacle count, destination, side-passability, and neighbor-lane/boundary
  availability before switching.
- Source: Apollo 10 official PathAssessmentDecider documentation,
  https://github.com/ApolloAuto/apollo/blob/master/docs/09_Decider/path_assessment_decider_cn.md
  (accessed 2026-08-29 UTC).
- 关键结论: the Apollo 10 document describes candidate path validation/selection and the front
  static-obstacle cycle counter used in path behavior.
- Source: Apollo current official Prediction flags,
  https://github.com/ApolloAuto/apollo/blob/master/modules/prediction/common/prediction_gflags.cc
  (accessed 2026-08-29 UTC).
- 关键结论: online current source is supporting context; the pinned local Apollo 10 source and
  generated configuration remain authoritative for this experiment.
- 可信度: high for pinned local source and official repository; exact online `master` applicability
  is constrained by branch/version differences.

计划实验：

Finish P2-D to explain the old run divergence. Do not admit RF01 regardless of any later
repeatability improvement. If P2-D confirms the static-lane-borrow mechanism, open P2-V2 with a
small slow-NPC sweep beginning around 1.1--1.2 m/s and freeze a trajectory-coverage admission gate
before formal repeats.

修改：

No Prediction or Planning behavior modified.

实验结果：

FAIL (mechanism admission) — old RF01 is diagnostic-only and cannot be the final reference under
the required Prediction trajectory gate.

结论：

RF01 remains valuable for repeatability debugging but is permanently ineligible for formal
Prediction-to-Planning admission in its zero-speed form.

下一步：

Do not change target speed until P2-D instrumentation establishes the first causal divergence.

## Issue P2D-004 — debug run 01 completed simulation but provenance RPC crashed CARLA at finish

Timestamp: 2026-08-29T06:08:00Z

现象：

`P2D_RF01_DEBUG_01` produced a complete 45-second Planning/Prediction timeline, but no summary was
written. At finish, the new provenance collector called `get_physics_control()` on the target after
its physics had been disabled; the CARLA server received SIGSEGV, then the bridge tick and actor
cleanup RPCs timed out.

证据：

- Run manifest SHA-256:
  `bfdf4e994904ee939dbea2c1dcf8fa6eab5375df80329deae58be96f1edce4df`.
- `bridge_determinism.json` confirms reload performed, Town01 retained, and post-reload values:
  synchronous true, fixed delta 0.05, substepping true, max substep delta 0.01, max substeps 10.
- `planning_input_timeline.jsonl` contains 1,813 complete events: 914 Prediction and 899 raw
  Planning events. Its last simulation clock is 84.30 s, exactly 45 s after the target/runtime
  began around 39.30 s.
- Runtime traceback identifies `finish -> actor_record(self.npc) -> actor.get_physics_control()`.
- CARLA server log immediately records `Signal 11 caught` and `Segmentation fault (core dumped)`;
  bridge subsequently reports a 30-second `world.tick()` timeout.
- Because the exception occurred before the atomic summary write, this run is infrastructure-invalid
  and cannot be used for behavioral comparison or admission.

当前假设：

- H6a (supported): querying vehicle physics over RPC after disabling simulation on that target is
  unsafe in this CARLA build and triggered the observed server crash.
- H6b (less likely): CARLA 0.9.15 can also crash nondeterministically under repeated launches, but
  the exact caller traceback and server termination order provide a much more specific trigger in
  this run.

联网检索：

- Query: `CARLA get_physics_control segmentation fault set_simulate_physics false`.
- Source: CARLA Python API,
  https://carla.readthedocs.io/en/latest/python_api/ (accessed 2026-08-29 UTC).
- 关键结论: `get_physics_control()` is explicitly a simulator RPC, unlike several cached vehicle
  getters. The documentation does not promise safety after physics is disabled.
- Query: `CARLA 0.9.15 repeated server segmentation fault`.
- Source: CARLA GitHub issue #9067,
  https://github.com/carla-simulator/carla/issues/9067 (accessed 2026-08-29 UTC).
- 关键结论: 0.9.15 has a reported repeated-launch SIGSEGV failure with a similar terminal server
  signature. This is background risk, not evidence that it caused this specific crash.
- Source: CARLA 0.9.15 release notes,
  https://github.com/carla-simulator/carla/releases/tag/0.9.15 (accessed 2026-08-29 UTC).
- 关键结论: 0.9.15 fixed some Python 3.10 GIL-related segfaults, but no exact disabled-physics RPC
  issue is documented there.
- 可信度: high for the local traceback/server sequence; medium for the minimal fix; low for the
  relevance of generic repeated-launch reports.

计划实验：

Capture the target physics-control representation immediately after spawn and before disabling
physics. Cache all initial actor provenance before the scenario, perform no provenance RPC at
finish, and make exception summaries atomic even when cleanup fails. Rerun the same RF01 debug
manifest content under a new append-only run ID.

修改：

- Removed finish-time physics RPCs; initial actor provenance is cached before the run.
- Target physics control is queried only before `set_simulate_physics(False)`.
- Added atomic `RUNTIME_EXCEPTION` summary fallback and tolerant cleanup.
- Preserved `P2D_RF01_DEBUG_01` unchanged as failed evidence.

实验结果：

FAIL — debug run 01 infrastructure invalid. Corrective run not yet observed.

结论：

The deterministic reload itself passed its first runtime verification. The failed result is caused
by the new instrumentation's finish-time RPC, not by a Planning or reference behavior conclusion.

下一步：

Run `P2D_RF01_DEBUG_02` with the same scene and deterministic settings, changing only the
provenance capture timing/error handling.

## Issue P2D-005 — RF01 first divergence localized from startup phase to early speed fallback

Timestamp: 2026-08-29T06:37:39Z

现象：

Five post-instrumentation RF01 debug runs used the same normalized manifest and generated launch
artifacts, but only `P2D_RF01_DEBUG_06` crossed the frozen screening oracle. Runs 02, 03, and 05
remained behind the target; run 04 passed the target longitudinally by only 2.536 m and therefore
failed the frozen 6 m pass-margin oracle. This confirms that deterministic CARLA settings alone do
not make the Apollo/CARLA closed loop behaviorally repeatable.

证据：

- `P2D_RF01_DEBUG_02`: infrastructure valid, pass margin -9.874 m, lateral excursion 1.556 m,
  Planning valid 564/901, no collision.
- `P2D_RF01_DEBUG_03`: infrastructure valid, pass margin -11.249 m, lateral excursion 1.288 m,
  Planning valid 608/903, no collision.
- `P2D_RF01_DEBUG_04`: infrastructure valid, pass margin +2.536 m, lateral excursion 2.655 m,
  Planning valid 877/912, no collision, but below the pre-existing +6 m pass-margin gate.
- `P2D_RF01_DEBUG_05`: infrastructure valid, pass margin -10.701 m, lateral excursion 1.414 m,
  Planning valid 694/894, no collision.
- `P2D_RF01_DEBUG_06`: infrastructure valid, pass margin +7.155 m, lateral excursion 2.621 m,
  Planning valid 888/912, no collision; debug-only screening pass.
- Every valid run had 917/917 target Prediction frames and 0 target frames with a trajectory.
- Runs 02--04 have identical normalized manifests and generated launch-artifact sets in
  `P2D_RF01_DEBUG_COMPARISON_01/summary.json` (SHA-256
  `ae7be6ed6ff7cb28ab5e63ad8b03435a3aabe42a9f80ab150b6dda476cab9274`). Runs 05--06 used the
  same scene/config and only added control/route phase telemetry.
- All verified CARLA settings were synchronous=true, fixed delta=0.05 s, substepping=true,
  max substep delta=0.01 s, max substeps=10. Actor IDs and spawn order were stable.
- Both outcome arms entered LaneBorrow. The first physical divergence is earlier: Apollo control
  became positive and CARLA autobox entered Drive 2--4 frames apart relative to the observation
  boundary. In run 05, positive throttle was first applied at simulation time 40.80 s and Drive
  feedback followed after motion startup; in run 06, positive throttle was already applied at
  38.45 s, one frame before observation began at 38.50 s, and Drive feedback appeared at 40.25 s.
- The outcome-relevant Planning divergence followed. Failing runs first triggered PiecewiseJerk
  speed failure/fallback 13.25--13.50 s after the left-reverse path appeared. Immediately before
  fallback, the chassis approached zero speed and Planning extrapolated an invalid-looking initial
  state around v=-0.22 m/s and a=-2.2 m/s^2. Run 06 did not reach the same fallback until +24.30 s,
  with v=+0.788 m/s and a=-0.058 m/s^2, after it had already developed a useful borrow path.
- Run 06 artifact hashes: summary
  `4255110bfc463bbeddf00587d70001f5ec555dd31fbdb54bd659f56c54b48eb4`, timeline
  `88f137ff46f6e7fe2adb5051392424ad5bec6fe5b246a424e412baa20b47ca90`, bridge-control telemetry
  `b58ba1c2f37b336bdd0d3c407330528869c8ee90e25f2546ae6e44f43c692370`.
- Lane-invasion telemetry recorded Broken Yellow markings with `lane_change=NONE`, and CARLA lane
  IDs changed from -1 to +1. RF01 therefore also lacks a defensible legal adjacent-lane claim.

当前假设：

- H1 is refined and supported: both arms enter LaneBorrow; the key Planning branch is not the
  scenario-entry gate but the early low-speed/fallback state within the borrow maneuver.
- H2 is partly supported: Apollo modules run on wall-time timers while CARLA data arrive at fixed
  simulation ticks. Small startup phase changes alter which localization/chassis state is used by
  a Planning cycle, then propagate into the speed optimizer.
- H3 is narrowed: world reload, seed-independent actor creation, fixed timestep, substepping,
  settings verification, actor IDs, and spawn order are controlled. Remaining variation is the
  asynchronous Apollo/CyberRT-to-CARLA control phase, not an unverified CARLA world setting.
- H4/H5 are confirmed for RF01: the zero-speed target is treated as still/static, never produces a
  target trajectory, and the observed behavior is static lane borrowing rather than the required
  Prediction-trajectory-to-Planning mechanism.

联网检索：

- Source: CARLA 0.9.15 synchronous-mode documentation,
  https://carla.readthedocs.io/en/0.9.15/adv_synchrony_timestep/ (accessed 2026-08-29 UTC).
  关键结论: synchronous mode requires a fixed timestep and a single tick-driving client; physics
  substep constraints must be compatible with the fixed delta. The implemented settings satisfy
  those conditions.
- Source: Apollo 10 pinned local CyberRT source and official developer documentation,
  https://apollo.baidu.com/docs/apollo/latest/cyber.html (accessed 2026-08-29 UTC).
  关键结论: Planning and Control use independent periodic components. The local bundle config has
  Planning at 10 Hz and Control at 100 Hz, while the bridge drives CARLA at 20 Hz.
- Source: Apollo issue #12896, https://github.com/ApolloAuto/apollo/issues/12896
  (accessed 2026-08-29 UTC).
  关键结论: historical Apollo users have reported lane-borrow/side-pass behavior that is sensitive
  to planning state and obstacle handling; this is supporting context, not proof of this run's
  exact cause.
- 可信度: high for local timelines, native logs, and pinned source; medium for attributing the last
  few-frame variation to scheduler phase because the underlying thread scheduling is observed only
  through messages and applied controls.

计划实验：

Close P2-D without modifying ego control or weakening the oracle. RF01 is permanently excluded
from final admission because it has zero trajectory coverage and questionable lane legality. Move
to P2-V2 on a same-direction multi-lane Town04 segment with a deterministic slow-moving NPC. Treat
closed-loop robustness across formal repeats, rather than bitwise scheduler determinism, as the
behavioral admission requirement.

修改：

Added per-cycle Planning input hashes/ages, scenario/path/speed decision fields, route events,
applied-control telemetry, actual ego speed, CARLA settings/actor provenance, structured lane
markings, and reproducible comparison/indexing tools. No Planning, Prediction, or ego-control
behavior was modified.

实验结果：

PASS (P2-D scientific objective) — the first observable physical and outcome-relevant Planning
divergences are localized. FAIL (RF01 admission) — RF01 remains nonrepeatable and mechanism-invalid.

结论：

The old success/failure split cannot be summarized as “one entered LaneBorrow and one did not.”
Both enter it. The earliest measured difference is control/autobox phase; the decisive Planning
branch is an early near-zero-speed PiecewiseJerk fallback in failing arms. Because RF01 supplies no
target trajectories, further tuning it would not answer the research question.

下一步：

Freeze the target trajectory coverage gate at 0.90 before any formal repeats, then run a minimal
P2-V2 stock-Planning screen with a 1.1 m/s deterministic NPC on a same-direction Town04 road.

## Issue P2D-006 — Cyber mock-clock probes rejected as a determinism fix

Timestamp: 2026-08-29T06:37:39Z

现象：

Two debug-only probes tested whether making Apollo read CARLA's `/clock` would remove the startup
phase difference. Neither configuration is admissible.

证据：

- `P2D_CLOCK_PROBE_MOCK_01` set both Cyber run mode to `MODE_SIMULATION` and clock mode to
  `MODE_MOCK`. It produced 0 Planning, Prediction, and Control messages and no accepted route.
- Pinned CyberRT source inspection showed that `MODE_SIMULATION` is not the desired runtime mode:
  channel topology joining and timer startup are guarded by `MODE_REALITY`.
- `P2D_CLOCK_PROBE_MOCK_02` retained `MODE_REALITY` and changed only clock mode to `MODE_MOCK`.
  Infrastructure became valid, but it still failed to overtake: pass margin -11.241 m, lateral
  excursion 1.202 m, Planning valid 586/894, target trajectories 0/907.
- Native logs in probe 02 contained repeated `latency begin_time >= end_time` diagnostics and a
  trajectory-stitching time difference of about 7.02 s. The 100 Hz wall-timer Control component can
  execute multiple times while the 20 Hz mock clock is unchanged, so replacing the clock alone
  does not create a coherent simulation scheduler.

当前假设：

- H7a rejected: `MODE_SIMULATION` cannot be used as a drop-in Apollo host simulation mode.
- H7b rejected: `MODE_REALITY + MODE_MOCK` without synchronizing component timers introduces new
  time-domain inconsistencies and is not a safe fix.

联网检索：

- Source: pinned Apollo 10 CyberRT `NodeChannelImpl`, `Timer::Start`, clock, and global-config
  source in the local workspace; applicable version is exact.
- Source: Apollo CyberRT documentation,
  https://apollo.baidu.com/docs/apollo/latest/cyber.html (accessed 2026-08-29 UTC).
- 可信度: high; both source guards and runtime counterexamples agree.

计划实验：

Retain default `MODE_REALITY + MODE_CYBER`. Do not change CARLA realtime factor because that would
make CARLA simulation timestamps drift from Apollo wall time. Do not add an external ego-control
barrier. Prefer a reference scene with enough behavioral margin to tolerate the measured scheduler
phase while satisfying 3/3 formal repeats.

修改：

The renderer now supports an explicit custom Cyber config for probes, but the default launch path
and global Apollo configuration remain unchanged. The first erroneous combined-mode rendering was
corrected so any future mock-clock diagnostic keeps run mode in reality.

实验结果：

FAIL — neither clock probe is an admissible determinism fix; no mock-clock change is selected for
P2-V2.

结论：

A coherent lockstep Apollo scheduler would require a broader architecture change than swapping the
clock source. That expansion is unnecessary and risky for the normal-reference objective.

下一步：

Proceed with stock Cyber timing and require empirical 3/3 robustness after candidate freeze.

## Issue P2V2-001 — freeze first Prediction-aware Town04 slow-NPC screening

Timestamp: 2026-08-29T06:42:00Z

现象：

RF01 cannot satisfy the mechanism gate. A new normal-only candidate is required, but its target
policy and trajectory oracle must be recorded before observing its behavior.

证据：

- Exact pinned Apollo 10 thresholds recorded in P2D-003 are 0.99 m/s for Prediction still-obstacle
  classification and 0.5 m/s for Planning static-obstacle handling.
- The pre-existing `RF04_01` topology selects Town04 road 46 lane -2, with same-direction adjacent
  lanes -1 and -3 and a 130.18 m route.
- The formal target trajectory coverage gate was frozen at 0.90 at 2026-08-29T06:37:39Z, before
  any P2-V2 formal-repeat outcome.

当前假设：

- H8a: a 1.10 m/s target will remain above the 0.99 m/s still threshold after initialization and
  therefore traverse a trajectory-producing Prediction path.
- H8b: stock Planning may follow rather than pass because 1.10 m/s is above its 0.5 m/s static
  threshold. This first screen deliberately tests stock behavior before any configured-reference
  threshold is considered.
- H8c: the Town04 same-direction lanes provide a more defensible legal overtake geometry than RF01.

联网检索：

- Query: `CARLA 0.9.15 enable_constant_velocity Python API`.
- Source: CARLA 0.9.15 Python API,
  https://carla.readthedocs.io/en/0.9.15/python_api/ (accessed 2026-08-29 UTC).
- 关键结论: `Actor.enable_constant_velocity()` sets a vehicle's approximately constant velocity
  in the actor's local frame; it warns against TrafficManager conflict. The candidate uses no TM.
- Query: `CARLA behavior set_target_velocity enable_constant_velocity`.
- Source: CARLA issue #7202,
  https://github.com/carla-simulator/carla/issues/7202 (accessed 2026-08-29 UTC).
- 关键结论: the issue shows both APIs in synchronous simulations and cautions that their behavior
  is not interchangeable. The official constant-velocity API is chosen because the NPC policy is
  intended to be frozen, not physically accelerated by a controller.
- Source: Apollo official Prediction flag documentation,
  https://github.com/ApolloAuto/apollo/blob/master/collection/prediction/README_cn.md
  (accessed 2026-08-29 UTC).
- 关键结论: current official documentation also lists the 0.99 m/s still-obstacle threshold,
  consistent with the exact pinned Apollo 10 source audit.
- 可信度: high for API availability and pinned thresholds; behavior outcome remains unknown until
  the screen.

计划实验：

Run exactly one screening candidate, `RF04_01_SLOW_110`. Keep stock Prediction, stock/default
Planning task configuration, Apollo-only ego control, fixed CARLA 20 Hz settings, no TM, and the
existing frozen overtake oracle. Reject immediately if target trajectory coverage is below 0.90.

修改：

- Added an explicit candidate-level NPC policy schema.
- Added deterministic CARLA local constant velocity for the target NPC only; ego control remains
  untouched.
- Added trajectory coverage to the summary and made the frozen 0.90 gate an explicit screening
  rejection condition.
- Added same-direction allowed lane IDs for future legality evaluation.

实验结果：

INCONCLUSIVE — static/schema validation passed; no P2-V2 runtime result has been observed.

结论：

The experimental change is one-dimensional (target velocity/mechanism), auditable, and does not
modify Prediction or Planning behavior.

下一步：

Prepare an append-only manifest and execute one screening run. Analyze trajectory coverage before
considering any Planning configuration change.

## Issue P2V2-002 — stock slow-NPC mechanism passes but stock Planning follows

Timestamp: 2026-08-29T06:49:00Z

现象：

`P2V2_REFERENCE_SCREEN_01_RF04_SLOW_110` produced real target trajectories but did not initiate
any lateral passing behavior.

证据：

- Immutable manifest SHA-256:
  `45eef89400bf4108bb7392db6bd90876dd5c6f207191ed227216da97e8ebc940`.
- Summary SHA-256:
  `ddbb926a42fda0f5494f257b4529baf2f34e15af9230c5c2e9f64baa666b6d5d`.
- Infrastructure valid; route accepted; no collision; Planning valid 900/911; no speed/path
  optimizer failure or fallback in the indexed native Planning log.
- Target appeared in 917 Prediction messages and had trajectories in 854, coverage 0.9312977,
  exceeding the frozen 0.90 mechanism gate.
- Ego remained on CARLA lane -2, maximum lateral excursion 0.053 m, maximum pass margin -26.332 m.
- No LaneBorrow entry, lane invasion, or positive lateral candidate was observed.

当前假设：

- H8a supported: 1.10 m/s reliably crosses the Prediction still threshold and produces
  trajectories.
- H8b supported: stock LaneBorrow is static-obstacle-only; at 1.10 m/s Planning follows the target.
- H8c remains untested behaviorally because no lane crossing occurred.

联网检索：

- Query: `Apollo slow vehicle lane borrow static obstacle`.
- Source: Apollo issue #8808,
  https://github.com/ApolloAuto/apollo/issues/8808 (accessed 2026-08-29 UTC).
- 关键结论: the reported behavior matches this screen: lane-borrow/side-pass is valid only for a
  static obstacle, while a slow car on a single reference line is followed.
- Source: Apollo issue #14627,
  https://github.com/ApolloAuto/apollo/issues/14627 (accessed 2026-08-29 UTC).
- 关键结论: Apollo maintainers/users discuss ground-truth perception and the need to let Prediction
  produce trajectories before lane borrowing, supporting the need to retain the mechanism gate.
- Source: Apollo official lane-borrow source and pinned Apollo 10 thresholds recorded in P2D-003.
- 可信度: high; runtime behavior, official/source semantics, and the independent issue align.

计划实验：

Test one configured-reference candidate. Keep the target at 1.10 m/s and Prediction stock. Change
only Planning's `static_obstacle_speed_threshold` from 0.50 to 1.20 m/s. This is a classification
configuration, not a path or control patch. Freeze that the identical override must be present in
all future fixed/faulty matched arms.

修改：

- Added `RF04_01_SLOW_110_CFG_STATIC_120` with the explicit label
  `APOLLO_10_CONFIGURED_REFERENCE`.
- Added a renderer allowlist that accepts only the named Planning threshold and writes it to the
  run-local Planning flagfile; global Apollo configuration is not modified.
- Added the effective Planning override to runtime provenance.

实验结果：

FAIL (stock behavior admission) / PASS (Prediction mechanism discovery). Configured candidate not
yet executed.

结论：

The first P2-V2 screen is an expected, informative rejection and is retained in the screening
ledger. Random map search is not justified before testing the exact static-classification gap.

下一步：

Validate the run-local flag rendering, then execute one configured-reference screen. If LaneBorrow
still does not activate, inspect its first failed gate before changing any other variable.

## Issue P2V2-003 — Planning threshold cannot turn trajectory-bearing obstacle into LaneBorrow static obstacle

Timestamp: 2026-08-29T07:02:00Z

现象：

`P2V2_REFERENCE_SCREEN_02_RF04_CFG_STATIC_120` loaded the 1.20 m/s Planning threshold but behaved
the same as the stock-Planning slow-target screen: it followed and did not borrow a lane.

证据：

- Manifest SHA-256:
  `5abac6fa039168df9ea0dfc0e910e9de70d69c0f8119c3c221990c1d7f4e68d7`.
- Summary SHA-256:
  `216723d2e61c63386b8e49ee1dd9aea397866a61e1caebe976886de84b8a5043`.
- The generated run-local Planning flagfile contains
  `--static_obstacle_speed_threshold=1.200000`; runtime provenance records the same override.
- Infrastructure valid, Planning 901/911 valid, target trajectory coverage 854/916=0.9323144,
  no collision or optimizer failure.
- Ego stayed in lane -2; lateral excursion 0.071 m; pass margin -26.332 m; no LaneBorrow entry.
- Native Planning logs show `Blocking obstacle ID[1001]` for one transient cycle and empty IDs
  thereafter; the trajectory instance is represented as `1001_0` in ST-boundary processing.

当前假设：

- H9a rejected: the Planning speed threshold alone cannot preserve a Prediction trajectory and
  also make that trajectory instance a LaneBorrow static obstacle.
- H9b supported: Planning creates obstacles from Prediction trajectories and initializes
  `Obstacle::is_static_` from `PredictionObstacle.is_static`; a velocity gflag does not override
  that field. LaneBorrow's blocking check explicitly rejects `!obstacle->IsStatic()`.
- H9c: a stock route/lane-change path may pass a trajectory-bearing slow vehicle without relying
  on the static-only LaneBorrow task.

联网检索：

- Source: Apollo 10 `planning_base/common/obstacle.cc`,
  https://raw.githubusercontent.com/ApolloAuto/apollo/r10.0.0/modules/planning/planning_base/common/obstacle.cc
  (accessed 2026-08-29 UTC).
- 关键结论: `CreateObstacles` creates one Planning obstacle per Prediction trajectory and passes
  `prediction_obstacle.is_static()` into the constructor; `is_static_` is set from that argument.
- Source: Apollo 10 `obstacle_blocking_analyzer.cc`,
  https://raw.githubusercontent.com/ApolloAuto/apollo/r10.0.0/modules/planning/planning_base/common/obstacle_blocking_analyzer.cc
  (accessed 2026-08-29 UTC).
- 关键结论: the side-pass gate rejects an obstacle if `!obstacle->IsStatic()` or if its speed is
  above a separate minimum. Both conditions must pass.
- Source: Apollo 10 Planning gflags,
  https://raw.githubusercontent.com/ApolloAuto/apollo/r10.0.0/modules/planning/planning_base/gflags/planning_gflags.cc
  (accessed 2026-08-29 UTC).
- 关键结论: the 0.5 m/s threshold exists, but source tracing shows it is not a replacement for
  Prediction's static label in the LaneBorrow gate.
- 可信度: high; exact-version source and runtime counterexample agree.

计划实验：

Do not raise the threshold further and do not modify Prediction to lie about `is_static`. Preserve
the failed configured candidate for audit. Test a stock-PnC route-driven lane change on the same
Town04 geometry and same 1.10 m/s trajectory-bearing target.

修改：

- Retained the allowlisted threshold renderer only to reproduce the failed candidate; it is not
  selected for subsequent candidates.
- Audited CARLA Town04 topology using the 0.9.15 API. Road 46 lane -2 and left lane -1 are both
  same-direction, 3.5 m Driving lanes. Their shared boundary is Broken White with `Both` lane-change
  permission. The downstream road 47 retains the same topology.
- Added `RF04_02_SLOW_110_ROUTE_LC_LEFT`. Its route stays on lane -2 for the first 20 m, requests
  lane -1 by 40 m, and ends in a frozen lane -1 success region. No Planning override is present.
- Added route-waypoint and success-region instrumentation/gates.

实验结果：

FAIL — configured static-threshold candidate rejected. New stock-PnC route candidate not yet run.

结论：

The threshold workaround is scientifically invalid for the intended mechanism and is abandoned.
The next experiment changes only route lane intent, using Apollo's native Routing/Planning/Control.

下一步：

Execute one route-driven screening. Require 0.90 trajectory coverage, entry into allowed lane -1,
positive pass margin/lateral margin, no collision, and arrival in the frozen road-47/lane-1 region.

## Issue P2V2-004 — route intent reached Planning, missing road-width metadata makes lane-change QP infeasible

Timestamp: 2026-08-29T07:30:00Z

现象：

`P2V2_REFERENCE_SCREEN_03_RF04_ROUTE_LC_LEFT` accepted the four-waypoint route but never entered
lane -1. The route request itself was not the first failure: once a second reference line became
available, LaneChangePath attempted the transition and failed on every cycle.

证据：

- Manifest SHA-256:
  `d295b0d120d4f84399e2b4d5352a9f9c756a36a0c5b6474055cb0d440d85cb1f`.
- Summary SHA-256:
  `e40f78f3ad9b9495ee8deef87778bc880384619224fc83df92dfbe937181f8b2`.
- Infrastructure valid; Planning 901/911 valid; target trajectory coverage 854/916=0.9323144;
  no collision or lane invasion. Ego remained in lane -2 and pass margin stayed -26.332 m.
- Native Routing logs resolve the requested route into road 46 lane -2, then road 46 lane -1,
  road 1072 lane -1 and road 47 lane -1. At Planning frame 530, ego is at x=9.284 while the
  target reference line is centered at x=5.753.
- Exact first target-reference-line failure: initial lateral state `l=-3.53044`, but the emitted
  lane-change bound is only `[-0.695,+0.695]`; OSQP reports `primal infeasible`, followed by
  `lane change path optimize failed`. The failure repeats for the remainder of the run.
- The bridge Town04 `base_map.bin` contains zero `left_road_sample/right_road_sample` entries for
  every lane. Apollo's exact-version `LaneInfo::GetRoadWidth` reads only these arrays and returns
  zero when they are absent. The LaneChangePath boundary extension is therefore clamped back to
  the target lane instead of including the adjacent lane occupied by ego.

当前假设：

- H10a rejected: Routing did not ignore the requested lane transition.
- H10b supported: missing Apollo road-width metadata, rather than route distance or target
  Prediction, is sufficient to explain the infeasible lane-change initial state.
- H10c: adding only the missing road-width samples for the frozen route's target-lane segments
  will make the native lane-change QP feasible without changing Planning behavior.

联网检索：

- Query: `Apollo CHANGE_LANE_FINISHED path_id lane_change_path`.
- Source: Apollo 10 exact source,
  https://raw.githubusercontent.com/ApolloAuto/apollo/r10.0.0/modules/planning/tasks/lane_change_path/lane_change_path.cc
  (accessed 2026-08-29 UTC).
- 关键结论: initialization to `CHANGE_LANE_FINISHED/path_id=""` is intentional. Once a target
  reference line exists and the three-second success freeze has elapsed, status changes to
  `IN_CHANGE_LANE`; the observed status initialization is not itself the defect.
- Query: `Apollo left_road_sample right_road_sample`.
- Source: Apollo official map proto and HD-map implementation,
  https://github.com/ApolloAuto/apollo/blob/master/modules/common_msgs/map_msgs/map_lane.proto and
  https://github.com/ApolloAuto/apollo/blob/master/modules/map/hdmap/hdmap_common.cc
  (accessed 2026-08-29 UTC).
- 关键结论: lane road-width samples are explicit Apollo HD-map fields; `LaneInfo::Init` loads them
  and `GetRoadWidth` interpolates only these arrays.
- Source: Apollo issue #15777,
  https://github.com/ApolloAuto/apollo/issues/15777 (accessed 2026-08-29 UTC).
- 关键结论: an independent Apollo 9 report reproduces the same route-waypoint pattern and initial
  `CHANGE_LANE_FINISHED/path_id=""` failure, confirming this is a known lane-change/map-sensitive
  failure mode rather than evidence that Routing did not accept the command.
- Source: GuardStrikeLab bridge repository,
  https://github.com/guardstrikelab/carla_apollo_bridge (accessed 2026-08-29 UTC).
- 关键结论: the public bridge was tested against CARLA 0.9.14/Apollo 8 and ships the map artifact;
  it does not establish Apollo 10 LaneChangePath completeness.
- 可信度: high for the local root cause; the exact constraint values, empty protobuf fields, and
  pinned source dataflow agree.

计划实验：

Create one derived, explicitly configured Town04 map. Fill road-width samples only for
`road_46_lane_0_-1`, `road_1072_lane_0_-1`, and `road_47_lane_0_-1` by summing their frozen
same-direction neighbor-chain lane widths. Preserve the original map and copy routing/sim maps
unchanged. Rerun the identical route candidate once.

修改：

- Added `build_road_width_map.py`, which refuses in-place edits, ambiguous neighbor chains, lanes
  already carrying samples, and non-empty output directories.
- Built `runtime/maps/carla_town04_road_width_v1`. Source base SHA is
  `df8e3fa79d527f101e11b2829e12684b4f4a466bf5c112d6fe6588f33651ac62`; derived base SHA is
  `fac6d39f94c82796fe71c86269c74d663d9ca6bf89dbef85523b338258ab5372`.
- A protobuf equality audit clears the newly added samples and proves the source and derived maps
  are otherwise semantically identical. Routing-map SHA remains
  `b79e19a57c0fffdcb42364adf11dca18d59ceaa72eb3a54c56d08452a56b26c2`.
- Added an allowlisted manifest-selected map variant and Routing passage/segment telemetry.

实验结果：

INCONCLUSIVE — derived-map construction and semantic-diff audit pass; runtime screen not yet run.

结论：

The previous route candidate is retained as a failed screen. The derived map is labeled
`APOLLO_10_CONFIGURED_MAP_REFERENCE`, not unmodified stock Apollo 10.

下一步：

Execute exactly one identical screen with the derived map. First verify that the QP boundary now
contains `l=-3.53`; only then evaluate lane entry, pass margin, success region, and trajectory gate.

## Issue P2V2-005 — map repair makes LaneChangePath feasible; late route onset leaves too little distance

Timestamp: 2026-08-29T07:45:00Z

现象：

`P2V2_REFERENCE_SCREEN_04_RF04_ROUTE_LC_MAP_WIDTH_V1` eliminated the lane-change QP failure and
produced a genuine lane-change trajectory, but ego had not reached lane -1 by the 45 s endpoint.

证据：

- Manifest SHA-256:
  `1cd9e0a3d3025c25e1b3f9234a4da955a835dc64876a0b432f96da730ef9a8ca`.
- Summary SHA-256:
  `e9dd4f670c5a8c1060906ace63b58da43d93083b9e30a460341cbaeae7f63d5d`.
- Infrastructure valid; Planning 902/912 valid; target trajectory coverage 854/917=0.9312977;
  no collision, speed optimizer failure, path optimizer failure or fallback.
- The prior repeated `regular/lane_change piecewise jerk path optimizer failed` count fell from
  hundreds to zero. Planning debug now contains `planning_path_boundary_1_regular/lane_change`
  and `candidate_path_regular/lane_change`.
- Ego moved 0.955 m toward lane -1 and triggered four Broken White / lane-change Both crossing
  callbacks, versus only 0.061 m and zero crossings in the uncorrected-map run. CARLA still
  classified its center as lane -2 at the endpoint, so the candidate is correctly rejected as
  `ALLOWED_OVERTAKE_LANE_NOT_ENTERED`.
- The target reference line first appears only after ego reaches the second lane -2 waypoint,
  approximately 20 m into the route and 26 s into the observation window. Ego is traveling only
  about 0.8--0.9 m/s, leaving about 19 s for the physical transition.

当前假设：

- H10c supported: road-width metadata was the QP feasibility blocker.
- H11a: moving the lane-change route onset from 20 m to 10 m ahead will expose the target reference
  line early enough for the same controller and 45 s window to complete the legal transition.
- H11b: after entering lane -1, target-lane separation will let Planning accelerate and pass the
  1.10 m/s target; this remains unproven.

联网检索：

- No new behavioral claim was inferred from the web for this step. The minimal experiment follows
  directly from exact runtime timing and the already cited Apollo LaneChangePath state machine.

计划实验：

Keep the repaired map and every actor/config/oracle setting. Change only the route lane-change
onset: request road 46 lane -1 at the audited center point approximately 10 m ahead instead of
holding lane -2 for 20 m. Preserve the 45 s observation window.

修改：

- Added trajectory first/last-point instrumentation for future path-versus-vehicle audits.
- Added `RF04_04_SLOW_110_ROUTE_LC_EARLY_MAP_WIDTH_V1` with lane intent `[-2,-1,-1]` and no
  Planning override.

实验结果：

FAIL for admission, PASS for the road-width causal hypothesis. Early-route screen not yet run.

结论：

The map repair is retained as an explained configured-reference prerequisite. The old late route
is retained as a rejected candidate; the oracle and trajectory coverage gate remain unchanged.

下一步：

Execute one early-route screening and compare the first target-reference-line frame, lateral
completion, post-entry speed, pass margin and success-region arrival.

## Issue P2V2-006 — a 10 m route transition expires before the physical lane change completes

Timestamp: 2026-08-29T08:03:00Z

现象：

`P2V2_REFERENCE_SCREEN_05_RF04_ROUTE_LC_EARLY_MAP_WIDTH_V1` exposes both reference lines from
the first Planning cycles and produces a feasible native lane-change path, but Planning becomes
invalid after ego advances only about 9.84 m. Ego stops in lane -2 instead of completing the
transition.

证据：

- Manifest SHA-256:
  `62fb52153e3a71d430421da1091c511147154d6642832fccf6a263a0025762d4`.
- Summary SHA-256:
  `40f95cb26c0d04c6dba812e466b31f5835965edaef3bb0fdfbef3112fee64a5d`.
- Infrastructure was valid and the target trajectory gate passed at 854/916=0.9323144. There
  were no collisions, optimizer failures, fallbacks, or lane-invasion callbacks. Planning valid
  coverage fell to 273/912; lateral excursion was only 0.273 m and pass margin was -26.332 m.
- Routing passage 0 spans current lane `road_46_lane_0_-2` only from s=96.127 to s=105.429;
  passage 1 then spans lane -1. The first native error is exactly:
  `Cannot find waypoint: id = road_46_lane_0_-2 s = 105.964`, followed by
  `Failed to update vehicle state in pnc_map`, `Failed to extract segments from routing`, and
  `Failed to create reference line from routing`. The last error repeats 668 times.
- Native lane-change path output shifts about 4.02 m over roughly 99 m. Its selected seven-second
  trajectory covers only about 22.8 m. At the premature 10 m passage boundary, ego has moved
  laterally only 0.27 m, consistent with the planned gradual transition rather than a Control
  tracking defect.

当前假设：

- H11a rejected: merely exposing the target reference line earlier is insufficient.
- H12a supported: the short current-lane routing passage expires before the physically planned
  lane transition, causing the first outcome-relevant reference-line failure.
- H12b: a route with only the lane -2 start and far lane -1 endpoint will let Routing allocate a
  longer transition corridor, while retaining native Planning/Control and all mechanism gates.

联网检索：

- Query: `Apollo Failed to create reference line from routing CanDriveFrom GetRouteSegments`.
- Source: Apollo official `reference_line_provider.cc`,
  https://github.com/ApolloAuto/apollo/blob/master/modules/planning/planning_base/reference_line/reference_line_provider.cc
  (accessed 2026-08-29 UTC).
- 关键结论: the exact log is emitted when `CreateRouteSegments(vehicle_state, segments)` fails;
  it precedes smoothing and trajectory optimization, matching the local failure ordering.
- Source: Apollo issues #12604 and #14273,
  https://github.com/ApolloAuto/apollo/issues/12604 and
  https://github.com/ApolloAuto/apollo/issues/14273 (accessed 2026-08-29 UTC).
- 关键结论: both independent reports show that a routing/PncMap segment extraction failure can
  leave Planning repeatedly unable to produce reference lines. They support the failure mode but
  do not establish this run's root cause; the exact local lane ID and s-boundary do.
- Source: Apollo 10 official LaneChangePath source,
  https://apollo.baidu.com/docs/apollo/10.x/lane__change__path_8cc_source.html
  (accessed 2026-08-29 UTC).
- 关键结论: LaneChangePath builds a gradual path from the routing-selected change-lane reference;
  it does not guarantee completion before an externally supplied intermediate waypoint.
- 可信度: high for the local first divergence; medium for whether the two-waypoint routing search
  will allocate a sufficient corridor, which requires the next minimal experiment.

计划实验：

Keep the configured map and every actor/config/oracle value. Remove only the intermediate
lane-1 waypoint, leaving the lane -2 start and far lane -1 endpoint. Freeze this candidate before
execution and run one 45 s screen. First inspect Routing passage bounds and reference-line
continuity; only then evaluate physical lane entry and passing.

修改：

- Added `RF04_05_SLOW_110_ROUTE_LC_LONG_MAP_WIDTH_V1` with lane intent `[-2,-1]`.
- No Apollo, map, bridge, actor, target-speed, observation-window, or oracle change.

实验结果：

INCONCLUSIVE — candidate frozen in source but not yet manifested or executed.

结论：

The early candidate remains permanently rejected. The next test is a single-variable route
topology experiment, not a threshold relaxation or a success-oracle change.

下一步：

Freeze `P2V2_REFERENCE_SCREEN_06_RF04_ROUTE_LC_LONG_MAP_WIDTH_V1`, execute it once, and compare
its current-lane passage endpoint, first reference-line failure, lateral progress, and Prediction
trajectory coverage against Screen 05.

## Issue P2V2-007 — long corridor completes native lane entry; raw constant velocity leaves the curved lane

Timestamp: 2026-08-29T08:17:00Z

现象：

`P2V2_REFERENCE_SCREEN_06_RF04_ROUTE_LC_LONG_MAP_WIDTH_V1` removes the reference-line failure
and lets ego legally enter lane -1, but no pass occurs in 45 s. A new scenario-validity defect is
visible: the raw constant-local-velocity target preserves a nearly tangential motion while road 46
curves, drifts across lane centers, and slows at the road edge.

证据：

- Manifest SHA-256:
  `232859707cfac17a2213d6d8fe41f81454f9508119db97968ca469bbe3abb1df`.
- Summary SHA-256:
  `e57d860a427690ffbe58ddde46e5fbdb38d17c409f077060272b8041c37a5dd3`.
- Routing now gives current lane -2 from s=96.127 through s=141.262 and lane -1 from s=0
  through s=140.205. There are zero reference-line creation, LaneChangePath optimizer, and
  PiecewiseJerk speed optimizer failures. Planning is valid 901/911.
- Target trajectory coverage is 854/916=0.9323144. Ego crosses only Broken White / Both markings,
  reaches CARLA lane -1, and moves laterally 1.839 m with no collision. This causally supports the
  long-transition-corridor hypothesis.
- Admission still fails: max pass margin remains -26.332 m and the success region is not reached.
  Ego covers 36.24 m in 45 s while the target covers 73.54 m relative to ego's origin.
- The raw target moves from x=9.223 to x=1.595 while advancing about 47.17 m; its measured speed
  is about 1.013 m/s through 42 s and then falls to 0.306 m/s at the road edge. This is not a
  stable lane-following target and therefore cannot be admitted even if a longer window happened
  to yield a pass.

当前假设：

- H12b supported: removing the intermediate waypoint fixes the first-divergence route failure.
- H13a: raw `enable_constant_velocity(local_x)` controls speed but supplies no map-following
  steering; it is unsuitable on this slightly curved Town04 segment.
- H13b: CARLA 0.9.15's bundled `ConstantVelocityAgent` will retain the same 1.10 m/s mechanism
  while using LocalPlanner steering to keep the NPC on frozen lane -2.
- H13c: after target lane stability is fixed, the 45 s screen will establish whether post-entry
  ego acceleration begins; a longer window may then be screened as a separate frozen variable.

联网检索：

- Query: `CARLA 0.9.15 enable_constant_velocity local space`.
- Source: CARLA API documentation source,
  https://github.com/carla-simulator/carla/blob/ue5-dev/PythonAPI/docs/actor.yml
  (accessed 2026-08-29 UTC).
- 关键结论: `enable_constant_velocity` takes a local-space velocity vector and only promises an
  approximately constant velocity; it is not documented as a lane-following controller.
- Query: `CARLA 0.9.15 ConstantVelocityAgent set_desired_speed`.
- Source: CARLA 0.9.15 release notes and local pinned source,
  https://github.com/carla-simulator/carla/blob/ue5-dev/CHANGELOG_UE4.md and
  `runtime/carla/0.9.15/PythonAPI/carla/agents/navigation/constant_velocity_agent.py`
  (accessed 2026-08-29 UTC).
- 关键结论: CARLA 0.9.15 ships ConstantVelocityAgent. Its implementation retains
  `enable_constant_velocity` for longitudinal speed and calls LocalPlanner every step to supply
  steering. This directly addresses the observed mechanism without TrafficManager randomness.
- Query: `CARLA deterministic synchronous simulation Traffic Manager seed`.
- Source: CARLA 0.9.15 Traffic Manager documentation,
  https://carla.readthedocs.io/en/0.9.15/tuto_G_traffic_manager/
  (accessed 2026-08-29 UTC).
- 关键结论: a deterministic TM route was considered as a fallback, but it would add a seeded
  multi-thread traffic controller and another synchronization surface. The bundled single-NPC
  agent is the lower-risk, more directly controlled experiment.
- 可信度: high for why the raw policy is invalid; medium until the agent policy is executed.

计划实验：

Change only the NPC controller from raw local constant velocity to the pinned CARLA 0.9.15
ConstantVelocityAgent. Freeze the NPC's same-lane destination and retain 1.10 m/s, the 45 s
window, two-waypoint ego route, configured map, Apollo stack, and oracle.

修改：

- Added exact per-sample NPC road/lane, lane-center distance, yaw, and velocity-vector telemetry.
- Added allowlisted `CARLA_CONSTANT_VELOCITY_AGENT` policy backed by the pinned CARLA source;
  no TrafficManager is used and no ego command is changed.
- Added `RF04_06_SLOW_110_AGENT_LC_LONG_MAP_WIDTH_V1` with target destination on lane -2.
- Added candidate-specific observation-window parsing, but RF04_06 deliberately retains the
  global frozen 45 s value; no duration change is part of this experiment.

实验结果：

INCONCLUSIVE — implementation and candidate are frozen before runtime execution.

结论：

Screen 06 is retained as a rejected but mechanism-positive routing experiment. It is not eligible
as a reference because the target's lane association is unstable.

下一步：

Statically validate the pinned agent import and manifest, execute one 45 s agent-policy screen,
and evaluate target lane-ID coverage/lane-center deviation before overtake behavior.

### P2V2-007 dependency subcheck

Timestamp: 2026-08-29T08:20:00Z

现象：

The first static import of CARLA's bundled ConstantVelocityAgent failed because Apollo host
Python does not provide the agent's declared runtime dependencies (`numpy`, `networkx`,
`shapely`). No experiment was started and no manifest result was affected.

修改：

Installed pinned `numpy==1.26.4`, `networkx==3.4.2`, and `shapely==2.0.7` only under
`runtime/bridge/carla-agent-deps`; added that isolated directory to the reference runner's
`APOLLO_EXTRA_PYTHONPATH`. The pre-manifest dependency tree contains 2817 files with aggregate
SHA-256 `9e8bf2630b71cb4ce4ee7778a41e01126cd5721cf434ef07fb73ee605db187b4`.

实验结果：

INCONCLUSIVE — dependency installation succeeded; host-mode agent import validation follows.

### P2V2-007 runtime result — lane following fixed, alternating-speed artifact fails mechanism gate

Timestamp: 2026-08-29T08:34:00Z

现象：

`P2V2_REFERENCE_SCREEN_07_RF04_AGENT_LC_LONG_MAP_WIDTH_V1` keeps the target on lane -2 but
fails the frozen Prediction trajectory gate because the target speed alternates between moving
and near-zero frames.

证据：

- Manifest SHA-256:
  `d3957111fdfacdf00ce3033d80fa0968b5da740e4f066a66288353ba18760d1b`.
- Summary SHA-256:
  `c1a77b7003a32a649c1a46ffea6173808a14f73149fa87703a6b1d25f3ea478d`.
- Target remains in lane -2 for 899/899 samples. Maximum lane-center deviation is 0.178 m and
  falls below 0.001 m on road 1072; the lane-following steering hypothesis is supported.
- Prediction mechanism gate fails at 458/908=0.5044053. After startup, each five-second block has
  exactly 50 moving/trajectory frames and 50 still/no-trajectory frames. Target speed alternates
  among approximately 1.06--1.19 m/s and 0.006--0.87 m/s in successive ticks.
- The constructor causes a separate initial pulse: target speed is about 3.96 m/s in early
  Prediction frames and the observation starts with a 27.74 m gap instead of the prior 26.33 m.
  Exact pinned source shows `target_speed` arrives in km/h, is converted to m/s internally, but
  the constructor calls `_set_constant_velocity(target_speed)` once with the pre-conversion value.
- Ego still legally enters lane -1; Planning is valid 898/901 and all reference-line/path/speed
  optimizer failure counts are zero. The candidate is rejected specifically for the mechanism
  gate before behavior can be considered.

当前假设：

- H13b partially supported: LocalPlanner steering solves target lane association.
- H14a supported: in this multi-client runner, issuing Agent constant velocity and then
  `apply_control` produces a deterministic alternating-frame speed artifact.
- H14b: freezing physics during Agent construction and making the 1.10 m/s constant-velocity RPC
  the final command for each next synchronous frame will remove both artifacts.

计划实验：

Retain the agent, target destination, speed, route, map, window, and oracle. Change only the NPC
command ordering and construction guard. Run one new, pre-manifested 45 s screen and require
both lane-center stability and the already frozen 0.90 Prediction trajectory gate.

修改：

- Freeze NPC physics while the bundled agent constructs its route, then restore physics and the
  intended 1.10 m/s local velocity.
- For each observed tick, apply the agent's steering control first and reassert 1.10 m/s last.
- Added `RF04_07_SLOW_110_AGENT_ORDERED_LC_LONG_MAP_WIDTH_V1`; no duration/oracle change.

实验结果：

FAIL for Screen 07 admission; ordered-policy Screen 08 pending.

结论：

Screen 07 is retained as a failed controller-integration experiment. It does not weaken the 0.90
gate; it explains why the gate correctly rejected a semantically intermittent target.

下一步：

Compile, freeze, and execute Screen 08. Compare per-five-second moving/trajectory frame counts,
initial gap, target lane-center error, and lane-change behavior with Screen 07.

## Issue P2V2-009 — ordered NPC passes mechanism gate; 45 s truncates native lane-change completion

Timestamp: 2026-08-29T08:49:00Z

现象：

`P2V2_REFERENCE_SCREEN_08_RF04_AGENT_ORDERED_LC_LONG_MAP_WIDTH_V1` fixes the target-speed
artifact and passes the frozen Prediction mechanism gate. It still ends before longitudinal
overtake because Apollo's gradual route-driven lane change is not yet centered in lane -1 at 45 s.

证据：

- Manifest SHA-256:
  `9142dfd028cc0dfd633725ed580c2db376b1488383acd1b52ef26c82b1fc6ba9`.
- Summary SHA-256:
  `acb9d9eb3c60ee1f4c048b5c1868dc9747ddb9ded5feba683f990844a32e59b1`.
- Target remains in lane -2 for every sample. Lane-center error is at most 0.178 m and below
  0.001 m after road 1072. From 10 s onward every five-second block has 100/100 moving target
  trajectories with speed 1.07230--1.07236 m/s.
- Frozen Prediction trajectory coverage passes at 826/908=0.9096916. Planning is valid 899/902;
  reference-line, LaneChangePath optimizer and PiecewiseJerk speed optimizer failures are zero.
- Ego legally crosses only Broken White / Both markings, reaches CARLA lane -1, and has 2.056 m
  lateral excursion. At 45 s it has moved 35.29 m longitudinally at 0.845 m/s while the target has
  moved 72.90 m, so max pass margin remains -25.947 m and success region is not reached.
- The 0.90 gate is not adjusted. The candidate is rejected under the unchanged overtake oracle.

当前假设：

- H14b supported: velocity-last RPC ordering solves the alternating-frame mechanism defect.
- H15a: Apollo remains in a native low-speed transition until it is sufficiently centered in
  target lane -1; a longer observation window will reveal post-transition acceleration.
- H15b: if ego remains below target speed after full lane-change completion, then observation
  duration is not the blocker and the next investigation must return to Planning speed decisions.

计划实验：

Clone the ordered-agent candidate and change only `observation_window_s` from 45 to 100 before
execution. Preserve the exact success oracle and 0.90 trajectory gate. Record lane-change status,
ego/target speed, pass margin, success-region arrival, target lane stability, and optimizer errors.

修改：

- Added `RF04_08_SLOW_110_AGENT_ORDERED_LC_LONG_100S_MAP_WIDTH_V1` with a candidate-frozen 100 s
  window. All other manifest fields are identical to RF04_07.

实验结果：

INCONCLUSIVE — long-window candidate frozen in source; runtime pending.

结论：

Screen 08 is retained as a mechanism-positive but behavior-incomplete screen. Extending the
observation is an explicit candidate parameter sweep, not a post-result oracle change.

下一步：

Freeze and execute Screen 09 once. If it passes, do not call it admitted: first freeze a formal
repeat manifest/protocol and run three clean repeats.

## Issue P2V2-010 — post-lane-change failure localizes to Apollo Control/CARLA calibration

Timestamp: 2026-08-29T09:02:00Z

现象：

`P2V2_REFERENCE_SCREEN_09_RF04_AGENT_ORDERED_LC_LONG_100S_MAP_WIDTH_V1` runs long enough for
LaneChangePath to finish but still cannot pass. Planning continues requesting faster motion;
the CARLA Lincoln plant responds too weakly to Apollo's low-speed throttle calibration.

证据：

- Manifest SHA-256:
  `7e60879f75f30d6057e3fe3fab5becc2f108ba2c85d0eda03e6970d8bdd2de6f`.
- Summary SHA-256:
  `aa53d1dcf88c8ddb5659cbd2ada2525a8ba6768d576806daea8d95484dc64c87`.
- Infrastructure valid; Planning 2000/2003; target trajectory coverage 1835/2008=0.9138446;
  target always lane -2; no collision, reference-line failure, path optimizer failure, or speed
  optimizer failure. Ego reaches 3.260 m lateral excursion in lane -1.
- Native lane-change status switches `IN_CHANGE_LANE -> CHANGE_LANE_FINISHED` about 41 s after
  observation start. From then to 100 s, ego speed rises only about 0.85 -> 1.02 m/s, below the
  stable 1.072 m/s target. Pass margin reaches roughly -45.8 m and never approaches +6 m.
- Late valid Planning trajectories span about 23.6--23.8 m over 7.1 s, while Control continuously
  requests positive acceleration about 0.45--0.72 m/s² with zero brake. This excludes a Planning
  hard cap near 1 m/s.
- Control emits about 18--19% throttle; the bridge applies the frozen 1.5 gain exactly, yielding
  about 0.27--0.29 CARLA throttle. Prior direct-plant evidence in
  `runtime_state/d0_hint_gold_v1/SPEED_LAYER_DIAGNOSIS.json` independently identifies the
  Apollo calibration-to-CARLA Lincoln interface as the speed limiter, not Planning, bridge
  transmission, or a CARLA hard cap.

当前假设：

- H15a rejected: longer duration alone cannot produce the pass.
- H16a supported: the installed stock Apollo longitudinal table is not calibrated for this CARLA
  Lincoln plant at low speed.
- H16b: the already preregistered and independently validated V17 low-speed table will let ego
  exceed the 1.10 m/s target without changing Planning, Prediction, braking, or high-speed Control.

联网检索：

- Query: `Apollo 10 control calibration_table_file longitudinal controller`.
- Source: Apollo 10 official Control docs and flags,
  https://apollo.baidu.com/docs/apollo/10.x/md_collection_2control_2README__cn.html and
  https://apollo.baidu.com/docs/apollo/10.x/control__gflags_8cc_source.html
  (accessed 2026-08-29 UTC).
- 关键结论: `calibration_table.pb.txt` is Apollo's explicit vehicle longitudinal calibration;
  `--calibration_table_file` is the supported run-time selector.
- Source: Apollo official `lon_controller.cc`,
  https://github.com/ApolloAuto/apollo/blob/master/modules/control/controllers/lon_based_pid_controller/lon_controller.cc
  (accessed 2026-08-29 UTC).
- 关键结论: the controller loads speed/acceleration/command triples into 2-D interpolation and
  uses the resulting calibration value for throttle/brake commands, matching the local diagnosis.
- Source: Apollo issue #9211,
  https://github.com/ApolloAuto/apollo/issues/9211 (accessed 2026-08-29 UTC).
- 关键结论: simulator-specific speed/acceleration mismatch from an unsuitable vehicle calibration
  table is an independently reported Apollo Control concern. It supports the need for calibration
  but does not validate our table; V17's local direct-plant and closed-loop evidence does.
- 可信度: high.

计划实验：

Use the pre-existing V17 table with SHA
`2693818651d7799eac5f206b88af0c0fb86f38b34443c1b14b4ccd45ffe482aa` as a run-scoped Control
configuration. Keep Screen 09 otherwise byte-semantically identical and run one 100 s screen.
Verify table loading, throttle response, target mechanism gates, legal passing, and destination.

修改：

- Added allowlisted, checksum-enforced Control calibration rendering through generated
  `control.conf`; the installed Apollo tree remains unchanged.
- Added `RF04_09_SLOW_110_AGENT_ORDERED_LC_LONG_100S_MAP_WIDTH_V1_CTRL_V17`.
- The candidate is explicitly labeled `APOLLO_10_CONFIGURED_MAP_AND_CONTROL_REFERENCE`.

实验结果：

INCONCLUSIVE — configured candidate frozen in source; runtime pending.

结论：

Screen 09 remains rejected. A calibrated Control table is a baseline compatibility configuration,
not a Prediction fault or hidden ego controller; it must remain identical in all future arms.

下一步：

Statically verify rendered table/config checksums, execute Screen 10 once, and require all original
mechanism/behavior gates without relaxation.

## Issue P2V2-011 — Screen 10 is invalid for both V17 evaluation and deterministic NPC admission

Timestamp: 2026-08-29T09:16:00Z

现象：

`P2V2_REFERENCE_SCREEN_10_RF04_AGENT_ORDERED_LC_LONG_100S_MAP_WIDTH_V1_CTRL_V17` failed the
frozen Prediction mechanism gate and did not pass the target.  Post-run native logs also prove
that the intended run-scoped V17 table was rendered but not consumed by Control.

证据：

- Manifest SHA-256:
  `fbacfd6e561fa3b73fc5cb0174994e1e5b6b2d726bccf6f5d556fd38d71924c3`.
- Summary SHA-256:
  `50fc735609f18265cf1eb6619634cd39ce820b45ec062ac709b1c1d822abcf0b`.
- Infrastructure valid; Planning 1999/2021; no collision, reference-line failure, path optimizer
  failure, or speed optimizer failure; ego legally entered lane -1.
- Target trajectory coverage was 1010/2028=0.4980276, below the frozen 0.90 gate.  The target
  remained on lane -2 but its measured speed repeatedly cycled from about 1.19 m/s through
  intermediate values to about 0.006 m/s.  The target policy is therefore not deterministic or
  mechanism-valid.
- The rendered V17 table has the expected SHA
  `2693818651d7799eac5f206b88af0c0fb86f38b34443c1b14b4ccd45ffe482aa`, and the generated
  `control.conf` points to it.  Nevertheless native log
  `control.log.INFO.20260829-155144.79223` says: `Load the calibraiton table file successfully,
  file path: modules/control/control_component/conf/calibration_table.pb.txt`.  Thus the installed
  relative flag file won; V17 was not active.
- The pinned CARLA 0.9.15 `ConstantVelocityAgent.run_step()` unconditionally executes vehicle
  hazard detection and calls `_set_constant_velocity(hazard_speed)`.  The scenario's ego is one
  of those vehicles.  `ignore_vehicles` in the constructor options does not bypass this override.
  This makes target motion depend on ego proximity and invalidates it as an exogenous reference
  actor policy.

当前假设：

- H16b remains untested: Screen 10 cannot support or reject V17 because Control did not load it.
- H17a supported: `APOLLO_CONF_PATH` does not override the relative `flag_file_path` embedded in
  the installed Control DAG in this packaged Apollo host runtime.
- H17b supported: the bundled ConstantVelocityAgent is semantically unsuitable because its
  collision/hazard policy intentionally changes target velocity as a function of nearby actors.
- H17c: a synchronous, fixed-seed Traffic Manager actor with automatic/random lane changes off,
  explicit desired speed, and vehicle/light/sign ignores will provide a lane-following target
  without per-frame cross-client RPC races.

联网检索：

- Query: `CARLA 0.9.15 Traffic Manager synchronous deterministic seed auto_lane_change`.
- Source: CARLA 0.9.15 official Traffic Manager tutorial,
  https://carla.readthedocs.io/en/0.9.15/tuto_G_traffic_manager/
  (accessed 2026-08-29 UTC).
- 关键结论: world and TM must both be synchronous; a seed must be set; per-vehicle automatic and
  random lane changes can be disabled; `set_path` can freeze a lane-following route.
- Source: CARLA official synchrony/time-step documentation,
  https://carla.readthedocs.io/en/latest/adv_synchrony_timestep/
  (accessed 2026-08-29 UTC).
- 关键结论: deterministic repetitions require synchronous mode plus fixed delta, enabling sync
  before reload, reloading for each run, resetting the seed, and preferring batched commands.
- Source: CARLA Traffic Manager deterministic-mode documentation,
  https://carla.readthedocs.io/en/0.9.13/adv_traffic_manager/
  (accessed 2026-08-29 UTC; mechanism is the versioned TM design also used by 0.9.15).
- 关键结论: deterministic mode is synchronous-only and the seed must be reset after every world
  reload.
- 可信度: high for the official requirements; local runtime validation is still mandatory.

计划实验：

1. Generate a run-scoped Control DAG whose `flag_file_path` is the absolute generated
   `control.conf`, then statically and natively verify that its absolute V17 path is loaded.
2. Replace the target policy with a fixed-port Traffic Manager configured after deterministic
   world reload: synchronous=true, seed=82601, physics mode (not hybrid teleportation), desired
   speed=3.96 km/h, auto/random lane changes off, traffic rules and vehicle collision response
   ignored, and a frozen lane -2 path.
3. Change one causal layer at a time: first run a short policy/mechanism screen with stock Control;
   only after target stability and >=0.90 trajectory coverage are proven, evaluate V17 behavior.

修改：

- None yet; this entry records the failed run and pre-registers both corrective actions.

实验结果：

FAIL — Screen 10 is permanently retained as a rejected screening run.

结论：

Do not interpret Screen 10 as a V17 result.  Do not admit the ordered ConstantVelocityAgent
policy even when aggregate coverage happens to pass, because its behavior is ego-dependent.

下一步：

Implement and statically test the absolute Control DAG and deterministic TM target policy, then
run the minimal stock-Control target-policy screen before another configured-Control screen.

## Issue P2V2-012 — TM rejected; current-lane-tangent constant velocity selected by isolated probes

Timestamp: 2026-08-29T09:50:00Z

现象：

Screen 11's synchronous fixed-seed TM target remained exactly stationary.  Independent probes
then separated this bridge integration failure from CARLA's intrinsic low-speed controller
behavior and found one minimal deterministic target policy that satisfies the Prediction threshold.

证据：

- Screen 11 manifest SHA-256:
  `0a702ceb4bcf8338706b2937e4fc250b671940c29c94d52ea7805a1898d760e9`.
- Screen 11 summary SHA-256:
  `1c48bf34fa03d579267f60333e01327c4b8257733522ff06feb716dcd861de00`.
- Screen 11: target speed was 0.0 m/s in all 899 samples; trajectory coverage was 0/923; Planning
  valid was 474/915; no collision; result permanently rejected by the 0.90 trajectory gate.
- Same-client CARLA TM probe at desired 3.96 km/h did move, proving that 0 m/s was an integration/
  tick-owner issue rather than invalid geometry.  However its controls alternated up to throttle
  0.85 and brake 0.70; only 35.3% of a 30 s steady sample exceeded 0.99 m/s.
- BasicAgent physical-PID probes at 1.10 m/s target: stable candidates had means 0.695--0.911 m/s,
  all with 0% frames above 0.99 m/s; the default/high-gain policy oscillated severely.  At a
  1.20 m/s target, tested gains 0.5--1.5 still achieved only 58.3--62.7% above 0.99 m/s and had
  minima near 0.13 m/s.  They cannot pass the frozen 0.90 mechanism gate.
- Isolated current-lane-tangent constant-velocity probe ran 1600 frames (80 s): steady mean
  1.0991976 m/s, population standard deviation 0.00000238 m/s, min/max
  1.0991902/1.0992092 m/s, and 100% above 0.99 m/s.  It stayed on lane -2; after settling,
  planar center offset was <=0.1783 m and fell near 0.014 m.  Only actor yaw was aligned to the
  *current* nearest driving-lane tangent; position was never projected and no future state was read.

当前假设：

- H17c rejected for this architecture: a separately instantiated synchronous TM is not a viable
  bridge-owned-tick target controller, and even its same-client low-speed dynamics fail coverage.
- H18a supported in isolation: constant local longitudinal velocity plus current-lane tangent
  heading removes both the raw policy's geometric drift and the agent policies' speed oscillation.
- H18b: batched no-tick heading commands from the runner will remain ordered under the bridge's
  single tick owner and reproduce the isolated target speed/coverage in the integrated stack.

联网检索：

- Source: CARLA official Traffic Manager tutorial and deterministic-mode documentation,
  https://carla.readthedocs.io/en/0.9.15/tuto_G_traffic_manager/ and
  https://carla.readthedocs.io/en/0.9.13/adv_traffic_manager/
  (accessed 2026-08-29 UTC).
- 关键结论: TM is designed for synchronous operation and seed reset after reload; actor registration
  and tick ownership are material in multi-client setups.
- Source: CARLA ScenarioRunner issue #495,
  https://github.com/carla-simulator/scenario_runner/issues/495
  (accessed 2026-08-29 UTC).
- 关键结论: a closely related multi-client synchronous setup reports autopilot not moving, while
  the same spawn/autopilot sequence works when owned by the ticking client.  This supports the
  local same-client/cross-client split but is not treated as proof for 0.9.15.
- Source: CARLA issue #6448,
  https://github.com/carla-simulator/carla/issues/6448
  (accessed 2026-08-29 UTC).
- 关键结论: `set_desired_speed` has independent reports of ineffective/nonideal speed tracking;
  local probes, not the issue alone, establish unsuitability here.
- Source: CARLA official deterministic simulation documentation,
  https://carla.readthedocs.io/en/latest/adv_synchrony_timestep/
  (accessed 2026-08-29 UTC).
- 关键结论: batching commands is recommended because individual RPC commands can be lost in a
  busy deterministic simulation; the new heading correction therefore uses `apply_batch_sync`.
- 可信度: high for local measurements and official contracts; medium for issue transferability.

计划实验：

Add `CARLA_CONSTANT_LOCAL_VELOCITY_LANE_TANGENT` and a 45 s stock-Control candidate.  Each cycle
reads only the actor's current transform and current nearest driving waypoint, preserves current
position/roll/pitch, normalizes and applies lane yaw in one no-tick batch, and leaves longitudinal
motion to CARLA's constant-local-velocity primitive.  Require zero batch errors, lane -2 stability,
and >=0.90 target trajectory coverage before considering any long-window or V17 candidate.

修改：

- Added the policy implementation and command/error counters to
  `reference_screen_runtime.py`.
- Added frozen candidate `RF04_11_SLOW_110_LANE_TANGENT_LC_LONG_MAP_WIDTH_V1`.
- The earlier Control launch correction now renders an absolute run-scoped `control.dag`; it is
  statically validated but intentionally not exercised by this stock-Control mechanism screen.

实验结果：

INCONCLUSIVE — isolated probe PASS; integrated Screen 12 pending.

结论：

The TM and BasicAgent paths are preserved as failed evidence.  The lane-tangent policy is not
called a pass until it survives the full Apollo/bridge timing path.

下一步：

Freeze and run Screen 12 once.  If the mechanism gate passes, repeat the exact mechanism candidate
once for policy determinism before composing a 100 s V17 behavior candidate.

## Issue P2V2-013 — repeatable mechanism and verified V17 produce a legal pass in 45 s

Timestamp: 2026-08-29T10:21:00Z

现象：

Two integrated stock-Control runs repeated the new target mechanism.  A subsequent one-variable
V17 load screen then completed the actual pass within 45 s but was correctly rejected because it
had not yet reached the unchanged route success region.

证据：

- Screen 12/13 target trajectory coverage: 0.9715536 / 0.9719525.  Each issued 900 heading
  batches with zero errors; target stayed lane -2; speed means were 1.0992409 / 1.0992331 m/s;
  standard deviations 0.0332750 / 0.0332745; identical min/max 0.9049382/1.3653238; 98.333% of
  sampled frames exceeded 0.99 m/s; max center offsets 0.178064/0.178066 m.
- Screen 14 manifest SHA-256:
  `317af5c422c3edd63d0a495ed8dec40aeb6ecae2c6f8bf722633dac8fea902ef`.
- Screen 14 summary SHA-256:
  `2073f682e66d99523743352eaff7fac9aa97ee629065d32ec6e1e45452b7b835`.
- Native Control log `control.log.INFO.20260829-162013.95791` names the absolute generated V17
  table, not the installed default.  Its SHA is the frozen
  `2693818651d7799eac5f206b88af0c0fb86f38b34443c1b14b4ccd45ffe482aa`; Control reports 1241
  table points.  Protobuf debug records show nonzero `calibration_value` matching emitted throttle.
- Screen 14: target trajectory coverage 896/917=0.9770992; Planning valid 869/912; zero collision,
  zero heading-command errors, lane -2 target, ego lane -1, max lateral excursion 3.3232 m, pass
  margin 6.7212 m, and only Broken White/White/Both lane-marking events.  Ego ended at 2.0882 m/s.
- The sole gate failure was `SUCCESS_REGION_NOT_REACHED`: distance to its unchanged center was
  47.7555 m at 45 s.  The success oracle was not modified.
- Native Planning log contains 22 PiecewiseJerk speed failures and 22 fallback path-optimizer
  failures in short startup/transition clusters; Planning recovered and completed the legal pass.
  These counts are retained as quality metrics and must be checked for consistency in formal runs.

当前假设：

- H18b supported: integrated batched heading commands are repeatable and mechanism-valid.
- H16b supported: V17 is now demonstrably active and is sufficient to make ego faster than the
  1.10 m/s target without changing Planning or Prediction.
- H19a: extending only observation duration to 80 s will enter the already frozen success region
  with substantial time/distance margin.

计划实验：

Clone Screen 14 and change only `observation_window_s` from 45 to 80.  Keep the exact map, route,
V17 checksum, NPC policy, seed, physics, bridge settings, trajectory gate and success oracle.
If it reports `SCREENING_PASS`, freeze source/config hashes in a new v2 formal-repeat contract;
do not reuse or overwrite the already rejected RF01 repeat contract.

修改：

- Added `simple_lon_debug` Control fields to the timeline for calibration provenance.
- Fixed configured Control launch with a run-scoped absolute DAG and flag file; native log now
  proves the fix works.
- Added `RF04_13_SLOW_110_LANE_TANGENT_LC_LONG_80S_MAP_WIDTH_V1_CTRL_V17`.

实验结果：

PASS for mechanism, calibration loading, lane legality, and longitudinal pass; formal admission
remains pending because Screen 14 did not reach the destination region.

结论：

The project now has a stable Prediction-bearing target and a functioning configured Apollo/CARLA
longitudinal interface.  No oracle threshold was relaxed and no failed run was removed.

下一步：

Execute the frozen 80 s Screen 15.  On pass, freeze formal contract v2 and run three clean repeats.

## Issue P2V2-014 — final screening pass and formal repeat contract v2 frozen

Timestamp: 2026-08-29T10:35:00Z

现象：

The 80 s candidate satisfied every pre-existing behavior/mechanism gate.  Before any formal repeat,
the remaining channel-quality, lane-legality, and clearance instrumentation was defined and a
hash-enforced three-run contract was frozen.

证据：

- Screen 15 manifest SHA-256:
  `ca73062b0f1c8ae41647dcf8b37c2515a20ab8c2ef0140d8878d4a377a7db73b`.
- Screen 15 summary SHA-256:
  `32021c4213ba5760501f41b6cc4d4bab030bc6ff4c76c136e4bc4359da267f75`.
- Result `SCREENING_PASS`: infrastructure valid, route accepted, no collision, lane -1 entered,
  success region reached first at 69.950 s, max pass margin 25.665 m, max lateral excursion
  3.628 m, target coverage 1596/1617=0.987013, Planning valid 1521/1605, and 1600 target heading
  commands with zero errors. Target stayed lane -2 with <=0.177722 m center offset.
- Native Control again loaded the absolute generated V17 path and its frozen SHA.
- Screen 15 has no reference-line failures or fallback-path optimizer failures. PiecewiseJerk speed
  failures occurred in two explainable clusters: initial trajectory formation and approach/stop at
  destination. They are retained as report-only quality evidence, not deleted.
- Contract `reference_repeat_contract_v2.yaml` SHA-256:
  `163f523d2d552cc5627efcce67df01d074db7ea6d52d28c6ea99831f1946dfe2`.

冻结约束：

- Formal thresholds were frozen before formal results: Planning channel coverage >=0.95, Control
  channel coverage >=0.95 relative to the expected 5:1 Control/clock rate, Planning valid ratio
  >=0.90, target trajectory coverage >=0.90, no collision, no illegal lane invasion, zero target
  command errors, target lane exactly -2, pass margin >=6 m, lateral excursion >=2 m, and success
  region reached.
- The only legal crossing signature is `Broken|White|Both`.
- Formal evaluator additionally records exact oriented 2-D bounding-box clearance and first-reach
  latency. No clearance threshold was retrofitted after seeing Screen 15; collision and lane
  legality remain the admission safety gates, while clearance is fully reported.
- Registry, runtime, runner, renderer, preparation/completion scripts, Planning config, derived
  map artifacts, and V17 table are all SHA-locked. Formal preparation aborts before execution on
  any mismatch.

计划实验：

Run `P2_FORMAL_REFERENCE_V2_REPEAT_1..3` sequentially with the same candidate and seed.  Preserve
every failure. After each run, verify summary gates, native absolute V17 load path, reference-line
failure count, optimizer counts, and artifact hashes. Any valid gate failure rejects the set;
there is no threshold adjustment.

修改：

- Added channel ratios, Planning-valid ratio, explicit lane-marking allowlist enforcement, minimum
  oriented bounding-box clearance, center separation and first success-region latency.
- Extended formal manifest preparation with contract membership and hash preflight.
- Added append-only `reference_repeat_contract_v2.yaml`; the rejected RF01 v1 contract remains.

实验结果：

SCREENING PASS; formal repeat results not yet observed.

结论：

The candidate is eligible for the only admission step still missing: three clean, hash-locked
formal repetitions.

下一步：

Prepare and execute formal repeat 1 under contract v2.

## Issue P2V2-015 — three formal repeats pass; stable reference admitted

Timestamp: 2026-08-29T11:10:00Z

现象：

All three hash-locked formal repetitions completed the legal lane change, passed the Prediction-
bearing target, and reached the frozen success region with no collision or illegal crossing.

证据：

- Repeat result/summary SHA pairs:
  - `P2_FORMAL_REFERENCE_V2_REPEAT_1`: PASS,
    `5aa3e113bc74092eaa38cb372afaad8455b110351fb79eca1c69f14915ada1d8`.
  - `P2_FORMAL_REFERENCE_V2_REPEAT_2`: PASS,
    `e93367fad5d8bf2ee39377f9dad91e10268cf46af20486a45afe14cc3bd2c979`.
  - `P2_FORMAL_REFERENCE_V2_REPEAT_3`: PASS,
    `aad9aae6889cfabc0a5658108cb8d23936baace01b148aa538b3587f830fc59c`.
- Minimum across runs: Prediction coverage 0.983921, Planning channel coverage 0.991342,
  Planning valid ratio 0.941506, Control coverage 0.998392, pass margin 23.625 m, 2-D body
  clearance 0.727 m. All are above their frozen gates where applicable.
- Success-region latency 67.30--70.55 s; no collision, illegal lane invasion, reference-line
  failure, target lane loss, target command error, Planning relay mismatch, or GT/fault leakage.
- Native Control logs in all three runs load the absolute V17 table. Optimizer/fallback counts and
  latency outliers are preserved in `FORMAL_REPEAT_V2_AUDIT.json` and the final report.
- Post-run checks: JSONL/YAML validation PASS, credential-pattern hits 0, residual relevant
  processes/listeners 0.

结论：

`STABLE_REFERENCE_ADMITTED`. The current authorized normal-reference research objective is
complete. Fault injection, diagnosis Agent, and animation remain unstarted by design.

下一步：

None within this scope. Any future Prediction fault work must start from this immutable normal
reference and the matched-arm constraints in contract v2.
