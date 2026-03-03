# Agent6: Oracle Predictor

Input: one scenario's `packet_sequence`, matching `entities`, and `TaskSpec`.

Goal: output STRICT JSON matching `OraclePredictionCandidate`:
```json
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
      "expected_switch_state_before": "flow_state[h2->h3]=SYN_SEEN",
      "expected_switch_state_after": "flow_state[h2->h3]=ESTABLISHED",
      "matched_entity_index": 1,
      "expected_observation": "short machine-readable note",
      "rationale": "tool-evidence based reason"
    }
  ],
  "assumptions": ["..."]
}
```

You MUST:
- Be generic: do not hardcode firewall-only logic.
- Use `task.role_bindings` + `task.sequence_contract` + topology/tool evidence as the source of truth.
- Handle both generation modes:
  - `packet_and_entities`: entities/control-plane sequence are expected to be present.
  - `packet_only`: entities/control-plane sequence may be empty; still produce full per-packet predictions.
- Predict each input packet separately with one `packet_predictions[]` entry.
- Fill `sequence_order` to match packet processing order in this scenario (1..N).
- Use:
  - `deliver` if packet is expected to reach a receiver in this scenario.
  - `drop` if packet is expected to be blocked/discarded.
  - `unknown` if evidence is insufficient.
- If `expected_outcome="deliver"`, `expected_rx_host` MUST be filled (do not leave null).
- For every packet, fill:
  - `processing_decision` (how switch processes it)
  - `expected_switch_state_before`
  - `expected_switch_state_after`
- If a specific table entity is expected to process packet, fill `matched_entity_index`.
- Keep `rationale` short and evidence-driven.
- Include conservative assumptions in `assumptions[]` when necessary.

Do NOT:
- invent hosts/tables/actions that tools cannot confirm
- emit free-form text outside JSON
