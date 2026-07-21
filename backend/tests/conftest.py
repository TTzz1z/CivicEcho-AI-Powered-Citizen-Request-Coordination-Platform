"""Test fixtures: keep unit tests hermetic and deterministic.

Unit tests must never call the real LLM. We force rule-based AI regardless of
the container environment so assertions on rule output stay stable.
"""
import os

# Override any container-provided key before app modules read settings.
os.environ["AI_API_KEY"] = ""
os.environ["AI_PROVIDER"] = "rules"

from app.config import get_settings  # noqa: E402
import app.llm_client as llm_client  # noqa: E402

get_settings.cache_clear()
llm_client._client = None
