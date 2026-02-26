意图驱动的P4程序测试

## Packet Sequence Seedgen (Stage-2 prototype)

This repo currently focuses on the "multi-agent generate input pkt packet_sequence" stage described in `point_1.md`.

Runtime notes:
- Use `python3.12` (Agno Team import fails under python3=3.8 in this environment).
- The generator loads build artifacts deterministically (DOT/JSON/P4Info/Topology) and exposes tool functions to agents.

Run (requires model env vars):
```bash
export AGNO_API_KEY=...
export AGNO_MODEL_ID=doubao-seed-2.0-code
export AGNO_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3

python3.12 -m sagefuzz_seedgen.cli
```

Tests (no model required):
```bash
python3.12 -m unittest discover -s tests -p 'test_*.py' -q
```
