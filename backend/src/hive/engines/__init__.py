"""Which providers the console can run agents on, and which engine runs each one.

To add another OpenAI-compatible provider, add a Provider entry here. Nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import AgentEngine, EngineConfig, EngineHooks


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    engine: str                    # "claude" | "openai"
    base_url: str = ""             # default API address (editable in Settings)
    key_env: str = ""              # environment variable that can hold the key
    stream: bool = True            # stream replies while tools are enabled
    usage_in_stream: bool = False  # supports stream_options.include_usage
    models: tuple[str, ...] = ()   # suggestions only; any model name can be typed
    note: str = ""


PROVIDERS = {p.id: p for p in [
    Provider("claude", "Claude", "claude", models=("opus", "sonnet", "haiku"),
             note="Runs through Claude Code with this machine's Claude login, ANTHROPIC_API_KEY or Bedrock/Vertex settings."),
    Provider("openai", "OpenAI", "openai", "https://api.openai.com/v1", "OPENAI_API_KEY",
             usage_in_stream=True, models=("gpt-5.5", "gpt-5.4-mini"),
             note="Use a model that supports the Chat Completions API."),
    Provider("deepseek", "DeepSeek", "openai", "https://api.deepseek.com", "DEEPSEEK_API_KEY",
             models=("deepseek-v4-pro", "deepseek-flash")),
    Provider("qwen", "Qwen", "openai", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY",
             stream=False, models=("qwen-max", "qwen-plus"),
             note="Alibaba Cloud Model Studio. Keys only work in their own region; use your region's compatible-mode address. Replies arrive all at once (no streaming with tools)."),
    Provider("kimi", "Kimi", "openai", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY",
             models=("kimi-k2-0905-preview", "kimi-k2-thinking"),
             note="Moonshot AI. Use https://api.moonshot.cn/v1 for a mainland-China account."),
]}


def make_engine(config: EngineConfig, hooks: EngineHooks, *, claude_client_factory=None,
                http_transport=None) -> AgentEngine:
    provider = PROVIDERS[config.provider]
    if provider.engine == "claude":
        from .claude import ClaudeCodeEngine
        kwargs = {"client_factory": claude_client_factory} if claude_client_factory else {}
        return ClaudeCodeEngine(config, hooks, **kwargs)
    from .openai_compat import OpenAICompatibleEngine
    return OpenAICompatibleEngine(config, hooks, provider, transport=http_transport)
