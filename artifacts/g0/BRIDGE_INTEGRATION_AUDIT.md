# Apollo–CARLA bridge audit

## Selected upstream baseline

- Repository: `https://github.com/guardstrikelab/carla_apollo_bridge.git`
- Pinned commit: `b0c2e088fb703ec5c601cd20616112b46150b180` (2024-09-09)
- License: Apache-2.0 at repository root. Individual files also retain their upstream Intel/CARLA MIT notices where present.
- Upstream claim: tested with CARLA 0.9.14 and Apollo 8.0.0. The documented Docker workflow is not valid in this AutoDL environment and will not be executed.
- Local source path: `runtime/bridge/apollo-carla`.

## Why this candidate

The source already implements the smallest required bidirectional CyberRT boundary and ships Apollo maps for CARLA Town01. It publishes clock, localization, chassis and optional obstacle/sensor messages, and subscribes to Apollo `ControlCommand` to apply CARLA throttle/brake/steer. This is a smaller and more auditable adaptation than adding ROS 1 plus two serial bridges.

## Native message boundary

| Direction | Cyber channel | Message | Bridge behavior |
|---|---|---|---|
| CARLA → Apollo | `/clock` | `cyber.proto.Clock` | simulator elapsed time |
| CARLA → Apollo | `/apollo/localization/pose` | `LocalizationEstimate` | pose, velocity, acceleration, heading |
| CARLA → Apollo | `/apollo/canbus/chassis` | `Chassis` | speed and current actuation percentages |
| CARLA → Apollo | `/tf` | `TransformStampeds` | world/localization transform |
| Apollo → CARLA | `/apollo/control` | `ControlCommand` | throttle/brake percentages and signed steering percentage |

The upstream pseudo-object sensor can publish CARLA actor truth as `PerceptionObstacles`. It is disabled for the first empty-road PnC gate and must never be exposed to the diagnostic observation path as oracle evidence.

## Coordinate, unit and timing audit

- CARLA uses Unreal's left-handed coordinates; the bridge preserves `x`, negates `y`, and converts angles from degrees to radians.
- The Town01 Apollo map is coupled to an additional yaw convention in the upstream transform helper; it must be checked against lane/map localization before declaring A1 PASS.
- CARLA speed is m/s. Apollo throttle, brake and steering commands are percentages; the bridge divides by 100 and negates steering for CARLA.
- The bridge owns the single synchronous world tick at `fixed_delta_seconds=0.05`. Each tick publishes simulator clock/state before accepting the next command. Queue depth is 10 for state publishers.

## Required Apollo 10 host-mode adaptation gates

1. Do not execute any upstream Docker scripts or copy to `/apollo`.
2. Resolve Apollo 10 package Python/protobuf paths from the installed host environment, then run import-level checks before editing compatibility code.
3. Use a Python 3.10 CARLA 0.9.15 client installed under `runtime/bridge/`, not the bundled Python 3.7/CARLA 0.9.14 egg and not an activated Conda environment.
4. Point the bridge at `127.0.0.1:2000`, keep Town01 and 0.05 s synchronous tick, and install map artifacts through the AEM workspace path from `runtime/maps`.
5. Start only localization/chassis/control data needed for empty-road PnC. Add no CARLA ground-truth obstacle feed unless a later gate explicitly records its privilege and isolation.
6. Verify localization/map alignment, Cyber channel rates, control range/sign, graceful shutdown and absence of residual actors/processes before three repeats.

## Known upstream risks under test

- Version gap: Apollo 8 → 10 and CARLA 0.9.14 → 0.9.15.
- The upstream installer mutates `~/.bashrc`, assumes `/apollo`, and installs with system pip; it will not be used.
- Some helper imports reference `modules.data.proto.frame_pb2`; Apollo 10 package availability is not assumed and will be tested after `buildtool` resolves dependencies.
- Upstream shutdown/thread code and random spawn selection are insufficient for deterministic repeat evidence; a bounded runner with fixed spawn/route and explicit cleanup is required.
- Upstream steering correction ratios (0.70 right/0.85 left) are empirical. They are not accepted silently; raw Apollo command, converted command and applied CARLA command must all be logged.
