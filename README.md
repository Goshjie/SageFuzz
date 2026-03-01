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

# Install deps (networkx+pydot are required to load DOT graphs; `openai` is required for OpenAILike)
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Option A: provide model+intent via config file (recommended)
cp seedgen_config.example.yaml seedgen_config.yaml
# edit seedgen_config.yaml (fill api_key and intent)
.venv/bin/python -m sagefuzz_seedgen.cli --config seedgen_config.yaml

# Option B: if intent is missing, Agent1 will ask questions interactively in the terminal.

# Optional: if provider/network is unstable, increase timeout/retries
.venv/bin/python -m sagefuzz_seedgen.cli --config seedgen_config.yaml --model-timeout 120 --model-retries 3
```

Tests (no model required):
```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
```

激活并使用
source .venv/bin/activate
python -m sagefuzz_seedgen.cli --config seedgen_config.yaml
