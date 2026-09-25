# LiteLLM AI Dashboard Prototype

Provider-agnostic AI-assisted dashboard with Dash + DMC 2.0.

## Quick Start

```bash
cd dev/litellm-prototype
cp .env.example .env        # add your API key
uv sync                     # install deps
uv run python app.py        # http://localhost:8050
```

Set `LLM_MODEL` in `.env` to any provider: `anthropic/claude-sonnet-4-20250514`, `gpt-4o`, `ollama/llama3`, etc.
