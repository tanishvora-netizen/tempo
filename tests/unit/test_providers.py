from pathlib import Path

import pytest

from tempo.llm.anthropic_provider import AnthropicProvider
from tempo.llm.cached_provider import CachedProvider, write_entry
from tempo.llm.provider import CacheMiss, ExtractionFailed, ModelCall, ProviderUnavailable, get_provider
from tempo.llm.schemas import TermsExtraction


def test_hosted_adapter_refuses_without_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.delenv("TEMPO_ALLOW_EXTERNAL_LLM", raising=False)

    with pytest.raises(ProviderUnavailable):
        AnthropicProvider()


def test_hosted_adapter_refuses_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPO_ALLOW_EXTERNAL_LLM", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ProviderUnavailable):
        AnthropicProvider()


def test_cached_mode_never_needs_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPO_PROVIDER", "cached")

    assert isinstance(get_provider(), CachedProvider)


def test_cache_miss_and_cached_failure_are_hard_failures(tmp_path: Path) -> None:
    provider = CachedProvider(tmp_path)
    call = ModelCall("extract", '{"blocks": []}')

    with pytest.raises(CacheMiss):
        provider.extract(call)

    write_entry(tmp_path, call, "ollama", "qwen3:8b", None, "model output truncated")
    with pytest.raises(ExtractionFailed):
        provider.extract(call)


def test_invalid_json_from_a_model_is_an_extraction_failure(tmp_path: Path) -> None:
    provider = CachedProvider(tmp_path)
    call = ModelCall("extract", '{"blocks": [1]}')
    write_entry(tmp_path, call, "ollama", "qwen3:8b", '{"terms_quote": 5}', None)

    with pytest.raises(ExtractionFailed):
        provider.extract(call)


def test_cache_key_depends_on_prompt_schema_and_document() -> None:
    a = ModelCall("extract", '{"x": 1}')
    b = ModelCall("extract", '{"x": 2}')

    assert a.key() != b.key()
    assert a.key() == ModelCall("extract", '{"x": 1}').key()
    assert TermsExtraction.model_config["extra"] == "forbid"
