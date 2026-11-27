import os
import pytest
from shorts_generator.config import LLM_CATALOG
from shorts_generator.highlights import _parse_llm_target, _get_effective_llm_path, _PROVIDER_SEMAPHORES, _PROVIDER_SLEEP
from server.main import _PROVIDER_KEY_ENV, _get_model_group

def test_tokenrouter_in_catalog():
    tr_entry = next((e for e in LLM_CATALOG if e["repo"] == "tokenrouter"), None)
    assert tr_entry is not None
    assert tr_entry["filename"] == "qwen/qwen3.8-max-free"
    assert "TokenRouter" in tr_entry["label"]

def test_tokenrouter_parsing():
    provider, model = _parse_llm_target("qwen/qwen3.8-max-free")
    assert provider == "tokenrouter"
    assert model == "qwen/qwen3.8-max-free"

    provider2, model2 = _parse_llm_target("api:tokenrouter:qwen/qwen3.8-max-free")
    assert provider2 == "tokenrouter"
    assert model2 == "qwen/qwen3.8-max-free"

def test_provider_semaphores_and_sleep():
    assert "tokenrouter" in _PROVIDER_SEMAPHORES
    assert "nvidia" in _PROVIDER_SEMAPHORES
    assert _PROVIDER_SLEEP.get("nvidia") >= 1.5
    assert _PROVIDER_SLEEP.get("tokenrouter") == 0.2

def test_provider_key_env():
    assert _PROVIDER_KEY_ENV.get("tokenrouter") == "TOKENROUTER_API_KEY"
    assert _PROVIDER_KEY_ENV.get("nvidia") == "NVIDIA_API_KEY"

def test_model_group_helper():
    assert _get_model_group({"repo": "tokenrouter"}) == "TokenRouter (Free Flagship)"
    assert _get_model_group({"repo": "nvidia"}) == "NVIDIA NIM API"
    assert _get_model_group({"repo": "groq"}) == "Groq API (Ultra-Fast 70B)"

def test_effective_llm_path_preservation():
    os.environ["TOKENROUTER_API_KEY"] = "sk-test"
    # Auto routing routes to TokenRouter
    assert "tokenrouter" in _get_effective_llm_path("auto", "strategy")
    # Explicit model choice is preserved
    assert _get_effective_llm_path("openai/gpt-oss-120b", "strategy") == "openai/gpt-oss-120b"
