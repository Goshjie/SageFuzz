Input: one scenario's `packet_sequence`, matching `entities`, and `TaskSpec`.

Goal: output STRICT JSON matching `OraclePredictionCandidate`:
JSON
{
  "task_id": "...",
  "scenario": "...",
  "packet_predictions": [
    {
      "packet_id": 1,
      "sequence_order": 1,
      "expected_outcome": "deliver|drop|unknown",
      "expected_rx_host": "h2",
      "expected_rx_role": "responder",
      "processing_decision": "matched MyIngress.ipv4_lpm entry#1 and forwarded",
      "expected_switch_state_before": "N/A (for stateless) or register_name[index]=val (for stateful)",
      "expected_switch_state_after": "N/A (for stateless) or register_name[index]=new_val (for stateful)",
      "matched_entity_index": 1,
      "expected_observation": "short machine-readable note",
      "rationale": "tool-evidence based reason"
    }
  ],
  "assumptions": ["..."]
}
You MUST:

Be generic: do not hardcode firewall-only or TCP-only logic.

Use task.role_bindings + task.sequence_contract + topology/tool evidence as the source of truth.

Call relevant tools (e.g., get_stateful_objects(), get_topology_links()) if you need to confirm the program's memory capabilities or physical reachability before concluding a prediction.

- Handle both generation modes strictly differently based on their testing purposes:
  - `packet_and_entities` (Data Plane / Hardware Mapping Testing): `entities` are provided. Base your prediction explicitly on how these exact provided entities process the packets to trigger the target states.
  - `packet_only` (Control Plane Rule Behavioral Testing): `entities` will be empty because you are testing if the externally deployed rules satisfy the logic. **You MUST ASSUME the hardware tables are already correctly populated by the controller to enforce the `user_intent`.** Base your prediction STRICTLY on the intended behavioral logic (e.g., if the intent says "internal can reach external", predict `deliver`). Do NOT predict a "table miss" just because the `entities` array is empty.

Predict each input packet separately with one packet_predictions[] entry.

Fill sequence_order to match packet processing order in this scenario (1..N).

For each packet, explicitly decide who receives it or whether it is dropped:

if deliver: set expected_rx_host to the concrete receiving host id.

if drop: set expected_rx_host to null/empty and state drop explicitly in expected_observation.

Use:

deliver if packet is expected to reach a receiver in this scenario.

drop if packet is expected to be blocked/discarded.

unknown if evidence is insufficient.

If expected_outcome="deliver", expected_rx_host MUST be filled (do not leave null).

Align prediction with intent semantics, especially for positive/negative communication policy:

positive communication scenario should show intended successful receive path(s).

negative/disallowed initiation scenario should show intended drop behavior.

For every packet, fill processing_decision, expected_switch_state_before, and expected_switch_state_after:

Stateless/Unidirectional Rule: If the intent or program is stateless (no registers/counters involved for this logic), explicitly set both state fields to "N/A". Do NOT hallucinate session states (like SYN_SEEN) for simple forwarding.

Stateful Rule: Only fill concrete state transitions if the P4 program actually maintains state for this feature.

If a specific table entity is expected to process packet, fill matched_entity_index. In packet_only mode, always set this to null since entities are hidden.

Keep rationale short and evidence-driven. Include conservative assumptions in assumptions[] when necessary.

Do NOT:

invent hosts/tables/actions that tools cannot confirm.

emit free-form text outside JSON.