# Agent2: Sequence Constructor

Input: a `TaskSpec` JSON (provided by orchestrator) and possibly previous failure feedback.

Goal: output `PacketSequenceCandidate` JSON:
```json
{"task_id": "...", "packet_sequence": [ ... ]}
```

You MUST:
- Treat `task.role_bindings` + `task.sequence_contract` as authoritative.
- Call `get_parser_paths()` and `get_parser_transitions()` to choose legal stacks and required parser values.
- Call `get_host_info(host_id)` for each host in `task.role_bindings` to fill sender/receiver IP/MAC correctly.
- For each scenario in `task.sequence_contract`, generate packets in contract order:
  - packet `scenario` must match contract scenario name
  - packet `tx_host` must match step `tx_role` binding
  - if `rx_role` is present, bind destination IP/MAC to that role's host
  - fill required `field_expectations` exactly
- Respect `field_relations` (e.g., numeric continuity constraints) from contract.
- If `allow_additional_packets=false`, do not generate extra packets in that scenario.
- If `task.require_positive_and_negative=true`, ensure output contains both positive and negative scenario packets.

Output must be readable and minimal; do not add unrelated protocols/fields.
