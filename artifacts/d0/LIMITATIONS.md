# Apollo D0 limitations

- D0 stopped at the 12-episode smoke gate. D0-A1, split freeze, 36-episode
  generation, non-agent baselines, LLM policies, calibration, and equal-budget
  comparisons were not run.
- The study contains two deterministic Town01 traffic templates and one seed.
  It is a pilot, not a population-level benchmark.
- Perfect perception excludes sensor, detector, association, and tracking
  uncertainty from the evaluated responsibility set.
- The fault mechanisms are strong semantic-boundary perturbations rather than
  empirical models of a specific production defect.
- Mechanism activation was usually observable (33/36 repeats), but task impact
  was not (16/36 combined votes). Observable perturbation is therefore not
  equivalent to a diagnostically useful failure.
- Only 2/12 correct-domain probes removed the registered failure, and one of
  those episodes also had a wrong-domain false repair. Domain selectivity is
  inadequate.
- Forecast faults and control transport delay produced no task failures under
  the frozen envelope despite most mechanism signals being present.
- Two planning-constraint episodes and the lead control-gain episode produced
  repeatable failures without correct-domain repair, showing that the current
  probes do not form reliable causal tests.
- A transient Apollo route/planning initialization failure required one exact
  retry. Its original evidence is retained; it was not counted as a scientific
  negative.
- Statistical significance, bootstrap intervals, calibration, AURC, Brier,
  ECE, prediction-set metrics, and matched-risk cost are unavailable because
  the prerequisite benchmark failed.
- The data are synthetic and cannot certify safety or justify real-vehicle
  automated intervention.
- A public dataset release still requires an explicit code/data license,
  third-party redistribution review, archival identifier, maintainer contact,
  and release-time checksum/redaction audit.
