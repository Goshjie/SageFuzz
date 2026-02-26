from agno.agent import Agent
from agno.models.openai.like import OpenAILike
from agno.tools import tool
from os import getenv

@tool(name="get_weather")
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return f"Weather in {city}: 72°F, sunny"

@tool(name="calculate_tip")
def calculate_tip(bill: float, tip_percent: float = 18.0) -> float:
    """Calculate tip amount for a restaurant bill."""
    return bill * (tip_percent / 100)

agent = Agent(
    model=OpenAILike(
        id="doubao-seed-2.0-code",
        api_key=getenv("AGNO_API_KEY", ""),
        base_url=getenv("AGNO_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3"),
        # api_base="https://api-slb.packyapi.com/v1"  # 自定义 URL
    ),
    markdown=True,
    tools=[get_weather, calculate_tip]
)

if __name__ == "__main__":
    agent.print_response("What's an 18% tip on a $85 bill?")
