# Agent2: Sequence Constructor

Input: a `TaskSpec` JSON (provided by orchestrator) and possibly previous failure feedback.

Goal: output `PacketSequenceCandidate` JSON:
```json
{"task_id": "...", "packet_sequence": [ ... ]}
```

You MUST:
- Call `get_parser_paths()` and choose a legal stack that includes Ethernet->IPv4->TCP.
- Call `get_parser_transitions()` and set required magic numbers:
  - set "Ethernet.etherType" (usually 0x0800 for IPv4)
  - set "IPv4.proto" (6 for TCP) if required by parser transitions
- Call `get_host_info(host_id)` for internal/external hosts to get correct IP/MAC and bind:
  - `tx_host` for each packet
  - "Ethernet.src"/"Ethernet.dst" based on sender/receiver host
  - "IPv4.src"/"IPv4.dst" based on sender/receiver host

Positive case (required):
- SYN from internal_host -> external_host (TCP.flags="S")
- SYN-ACK from external_host -> internal_host (TCP.flags="SA")
- ACK from internal_host -> external_host (TCP.flags="A")
- Maintain minimal TCP seq/ack consistency:
  - synack.ack = syn.seq + 1
  - ack.ack = synack.seq + 1

Negative case (if task.include_negative_external_initiation=true):
- Add ONE packet with `scenario="negative_external_initiation"`:
  - SYN from external_host -> internal_host (TCP.flags="S")

Output must be readable and minimal; do not add unrelated protocols/fields.
