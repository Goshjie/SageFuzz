from agno.agent import Agent
from agno.models.openai.like import OpenAILike
from agno.models.dashscope import DashScope


model = DashScope(
    id="qwen2.5-7b-instruct",
    api_key="sk-e84e7a4b3f734ba4ba035076a828c674",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    timeout=120,
    max_retries=2,
)

agent = Agent(
    name="SmokeTestAgent",
    model=model,
    markdown=False,
    use_json_mode=True,
    instructions=(
        "You are a strict JSON generator. "
        "Return only valid JSON with keys: status, message, score."
    ),
)
prompt = """
Return a JSON object only.
Requirements:
- status: "ok"
- message: one short sentence
- score: integer 1
"""
resp = agent.run(prompt)
print(resp.content)
