Input: one scenario's `packet_sequence`, matching `entities`, and `TaskSpec`.

Goal: output STRICT JSON matching `OraclePredictionCandidate`.

You MUST:
- Be generic: do not hardcode firewall-only or TCP-only logic.
- Use `task.role_bindings`, `task.sequence_contract`, `task.intent_category`, `task.observation_focus`, `task.observation_method`, `task.expected_observation_semantics`, and tool evidence as the source of truth.
- For telemetry/query packets, ground your prediction on the actual parser/source-defined packet format; do not reason from an invented generic query packet if the program uses custom probe headers.
- Call relevant tools (e.g. `get_stateful_objects()`, `get_topology_links()`) if you need to confirm state or reachability.
- When packet outcomes depend on source-level conditions not explicit in entities, use `search_p4_source()` and `get_p4_source_snippet()`.

Generation-mode rule:
- `packet_and_entities`: base prediction on the exact provided entities plus the scenario packets.
- `packet_only`: entities are hidden/empty because control-plane rules are externally deployed. Assume the deployed rules are intended to satisfy the user intent; do not predict a table miss merely because `entities[]` is empty.

Per-packet prediction rules:
- Predict each packet separately with one `packet_predictions[]` entry.
- Fill `sequence_order` to match packet processing order in this scenario.
- For each packet, decide whether it is delivered, dropped, or unknown.
- If `expected_outcome="deliver"`, `expected_rx_host` MUST be set.
- If `expected_outcome="drop"`, leave `expected_rx_host` empty and make the drop explicit in `processing_decision` / `expected_observation`.

State and observation rules:
- Always fill `processing_decision`, `expected_switch_state_before`, and `expected_switch_state_after`.
- For stateless/simple forwarding logic, use `N/A` if no relevant switch state exists.
- Only describe concrete state transitions when the program or task evidence supports them.
- For `telemetry_monitoring` or `state_observation` intents:
  - `expected_observation` must describe what the operator/controller should observe after this packet or after the cumulative scenario progression.
  - Do not treat packet delivery alone as sufficient proof of monitoring success.
  - Use `task.expected_observation_semantics` and scenario `expected_observation` to describe the expected metric/state trend, even when the exact numeric value is unknown.
  - If the scenario is cumulative (e.g. repeated traffic should increase a monitored metric), reflect that in `expected_switch_state_after` and `expected_observation` as a monotonic/trend description rather than inventing exact numbers.

Examples of acceptable telemetry-style observation wording:
- `expected_switch_state_after`: `monitored_link_counter increased relative to previous packet`
- `expected_observation`: `controller-visible monitored link utilization should be non-zero after scenario traffic`
- `expected_observation`: `selected path-load register should reflect traffic on the h1->h3 path`

Keep `rationale` short and evidence-driven. Use `assumptions[]` conservatively when exact target/index/value cannot be proven.

Output must be STRICT JSON only.
