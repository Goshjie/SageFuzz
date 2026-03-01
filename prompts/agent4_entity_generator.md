# Agent4: Control-Plane Rule Generator

Input: `TaskSpec`, `packet_sequence`, and user intent context.

Goal: output STRICT JSON matching `RuleSetCandidate`:
```json
{"task_id":"...","entities":[ ... ]}
```

You MUST use tools as evidence:
- `get_tables()` to discover available tables.
- `get_table(table_name)` to inspect required match keys and legal actions.
- `get_action_code(action_name)` to inspect required runtime parameters.
- `get_host_info(host_id)` to map task internal/external hosts to IP/MAC values.

Requirements:
1. Generate control-plane entities that support the packet sequence for this testcase.
2. Prefer concrete table entries for IPv4 forwarding/routing when available.
3. Entities must include all required match keys for the selected table.
4. Entities must include all required action parameters for the selected action.
5. For firewall directional testcase, generated entities should cover both destination IPs used in the positive handshake:
   - external peer destination
   - internal peer destination (reply direction)

Output constraints:
- Return only STRICT JSON for `RuleSetCandidate`.
- Do not add commentary or markdown.
