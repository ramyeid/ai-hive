"""Run the console with a fake Claude (no real agents): for UI development and testing.

    .venv/bin/python -m tests.run_fake      → http://127.0.0.1:8420
"""
import uvicorn

from server.agents import AgentManager
from server.main import create_app
from tests.fake_claude import FakeClient

if __name__ == "__main__":
    uvicorn.run(create_app(AgentManager(FakeClient)), host="127.0.0.1", port=8420)
