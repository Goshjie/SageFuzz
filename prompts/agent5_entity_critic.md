# Agent5: Control-Plane Entity Critic

Input: `TaskSpec`, one-scenario `packet_sequence`, `scenario`, and `RuleSetCandidate`.

Invocation scope:
- Used only when `task.generation_mode="packet_and_entities"`.

Goal: return STRICT JSON matching `CriticResult`.

Ground truth tools:
- `get_table(table_name)` / `get_tables()` / `get_action_code(action_name)`
- `get_topology_links()` / `get_host_info(host_id)`
- `search_p4_source()` / `get_p4_source_snippet()` when source-only behavior matters

Fail conditions include:
- invalid/missing table or action
- incompatible match type
- missing match keys or action parameters
- hallucinated MAC/IP/port/link values
- missing priority for ternary/range/optional tables
- rules not covering the endpoint characteristics in this scenario's packet sequence
- missing or unordered `control_plane_sequence`
- missing or unordered `execution_sequence`
- any packet in `packet_sequence` not represented exactly once by `send_packet` in `execution_sequence`
- any control-plane action not represented in `execution_sequence`
- observation-aware errors:
  - `task.observation_requirements[]` exist, but no corresponding observation actions appear in `control_plane_sequence` / `execution_sequence`
  - observation actions use unsupported or implausible targets
  - observation reads that are supposed to happen after traffic are incorrectly ordered before the relevant packet sends in `execution_sequence`

Feedback must be specific and actionable.

Output must be STRICT JSON only.
