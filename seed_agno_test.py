from __future__ import annotations

import sys
from os import getenv


def _ensure_supported_python() -> None:
    if sys.version_info < (3, 9):
        cur = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise SystemExit(
            "Unsupported Python runtime detected: "
            f"{cur}. Please use Python 3.9+ (recommended: .venv/bin/python, currently 3.12).\n"
            "Example: .venv/bin/python seed_agno_test.py"
        )


def main() -> None:
    _ensure_supported_python()

    from agno.agent import Agent
    from agno.models.openai.like import OpenAILike
    from agno.tools import tool

    @tool(name="get_weather")
    def get_weather(city: str) -> str:
        """Get current weather for a city."""
        return f"Weather in {city}: 72F, sunny"

    @tool(name="calculate_tip")
    def calculate_tip(bill: float, tip_percent: float = 18.0) -> float:
        """Calculate tip amount for a restaurant bill."""
        return bill * (tip_percent / 100)

    agent = Agent(
        model=OpenAILike(
            id="gpt-5.4",
            api_key=getenv("AGNO_API_KEY", "clp_d626a8778880522f5b9bed7848c72a00810ecc9dc44c9b99e08ccf8591231d4b"),
            base_url=getenv("AGNO_BASE_URL", "https://api-vip.codex-for.me/v1"),
            # api_base="https://api-slb.packyapi.com/v1"  # custom URL
        ),
        markdown=True,
        tools=[get_weather, calculate_tip],
    )

    # This gateway rejects non-streaming calls with HTTP 400.
    agent.print_response("你是什么模型？", stream=True)


if __name__ == "__main__":
    main()
