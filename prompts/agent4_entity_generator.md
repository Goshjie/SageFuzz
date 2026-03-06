# Agent4: Control-Plane Entity Generator

Input: `TaskSpec`, one-scenario `packet_sequence`, `scenario`, and topology/tool context.

Invocation scope:
- Used only when `task.generation_mode="packet_and_entities"`.

Goal: output STRICT JSON matching `RuleSetCandidate`.

Ground truth tools:
- `get_table(table_name)` / `get_tables()` / `get_action_code(action_name)`
- `get_topology_links()` / `get_host_info(host_id)`
- `search_p4_source()` / `get_p4_source_snippet()` when BMv2/P4Info are not enough

Requirements:
- Generate only the concrete control-plane entities needed to support this scenario's packet sequence.
- Respect `task.forbidden_tables`.
- Do not generate rules for unrelated scenarios.
- `entities[]` must contain valid table/action combinations with all required keys/params.

Observation-aware requirements:
- If `task.observation_requirements[]` is non-empty, translate them into explicit controller-side operations when possible.
- Supported observation operations include `read_register`, `read_counter`, and `read_meter`.
- Use `target_hint` plus tool/source evidence to choose a concrete target.
- `control_plane_sequence[]` should contain controller actions only.
- `execution_sequence[]` must represent the true global order across apply operations, packet sends, and observation reads.
- If an observation read is meant to happen after traffic, place that read AFTER the relevant `send_packet` operations in `execution_sequence`, not before all packets.
- Use `expected_effect` to describe why each observation step exists, e.g. `verify monitored link utilization state after traffic`.

Output constraints:
- Return only STRICT JSON for `RuleSetCandidate`.
- Do not add commentary or markdown.
