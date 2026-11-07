"""Run the console with a fake Claude (no real agents): for UI development and testing.

    uv run python -m tests.fakes.server      → http://127.0.0.1:8420
"""
import uvicorn

from hive.agents import AgentManager
from hive.main import create_app
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport

if __name__ == "__main__":
    uvicorn.run(create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport())), host="127.0.0.1", port=8420)
