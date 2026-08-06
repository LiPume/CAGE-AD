# G0 source checkpoint

These files were collected from the server that produced `APOLLO_GO`. They are retained as an auditable source mapping, not as a bundled Apollo/CARLA environment. The original scripts resolved paths relative to the G0 bundle; new reusable D0 modules use the four `CAGE_*_ROOT` variables instead.

The historical Python package is not a dependency of CAGE-AD. The copied A2 diagnostic fixture was made self-contained without changing its golden output. The CARLA launcher now invokes the preserved packaged runtime directly.

Original collection hashes and normalized artifact notes are in `artifacts/g0/SOURCE_PROVENANCE.yaml`.
