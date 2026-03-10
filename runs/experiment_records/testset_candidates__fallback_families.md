# Fallback-Family Test-Set Candidates

Created on `2026-03-10`.

This note tracks external candidate programs for the program families that
currently rely most on fallback in SageFuzz.

## Scope

Included families:

- `telemetry_monitoring`
- `threshold_state_accumulation`
- `load_distribution_congestion_feedback`

Excluded for now:

- `stateful_policy_firewall`
- `path_failover_fast_reroute`

Reason:

- The included families are the current weak spots where testcase generation is
  most dependent on fallback or where semantic grounding is still incomplete.

## Task Recognition Markers

`telemetry_monitoring`

- Family aliases:
  `telemetry`, `monitoring`, `probe_observation`, `state_observation`
- Chinese/intent markers:
  `监控`, `观测`, `探测`, `利用率`, `probe`, `统计`
- Expected task traits:
  probe/query packet path, register/counter observation, observation-driven testcase, often `packet_only`

`threshold_state_accumulation`

- Family aliases:
  `heavy_hitter`, `threshold_enforcement`, `per_flow_state`, `stateful_threshold`
- Chinese/intent markers:
  `阈值`, `计数`, `累计`, `超阈值`, `重流`, `heavy hitter`
- Expected task traits:
  same-flow repetition, threshold crossing, drop after accumulation, different-flow isolation

`load_distribution_congestion_feedback`

- Family aliases:
  `load_distribution`, `ecmp`, `load_balancing`, `congestion_feedback`, `path_spreading`
- Chinese/intent markers:
  `负载均衡`, `分流`, `拥塞`, `反馈`, `路径切换`, `ECMP`
- Expected task traits:
  multiple distinct flows, pre-disturbance path spreading, post-disturbance path adaptation, operator action grounding

## Candidate Programs

### High Priority

`MRI`

- Family: `telemetry_monitoring`
- Source repo: `p4lang/tutorials`
- Path hint: `exercises/mri`
- Why:
  telemetry-style program with per-hop metadata export; close to `Link Monitor` but not identical
- Suggested role:
  first external telemetry test program

`P4-INT`

- Family: `telemetry_monitoring`
- Source repo: `laofan13/P4-INT`
- Why:
  richer telemetry/INT semantics than the local `Link Monitor`
- Suggested role:
  second telemetry test program after MRI

`Tutorial Load Balancing`

- Family: `load_distribution_congestion_feedback`
- Source repo: `p4lang/tutorials`
- Path hint: `exercises/load_balance`
- Why:
  low-friction ECMP/load-spreading benchmark; ideal to test whether the fallback model learned multi-flow dispersion
- Suggested role:
  first external load-distribution test program

### Medium Priority

`QCMP`

- Family: `load_distribution_congestion_feedback`
- Source repo: `In-Network-Machine-Learning/QCMP`
- Why:
  closer to congestion-aware feedback style than tutorial ECMP; better semantic match for CALB
- Suggested role:
  advanced load-distribution / congestion-feedback test program

`PRECISION-bmv2 or related heavy-hitter variant`

- Family: `threshold_state_accumulation`
- Source repo: `Princeton-Cabernet/p4-projects`
- Why:
  closest public family match to local `Heavy Hitter Detector`
- Suggested role:
  preferred threshold/state-accumulation external test program once repository layout is confirmed

### Low Priority / Backup

`P4Pir`

- Family: `threshold_state_accumulation`
- Source repo: `In-Network-Machine-Learning/P4Pir`
- Why:
  broader stateful detection family; not a pure heavy-hitter program
- Suggested role:
  backup option only if a cleaner heavy-hitter candidate is unavailable

## Recommended Next Step

Start with these four as the practical external test-set pool:

1. `MRI`
2. `P4-INT`
3. `Tutorial Load Balancing`
4. `QCMP`

Then continue searching for a cleaner threshold/state-accumulation external
program before finalizing the `Heavy Hitter Detector` family test set.
