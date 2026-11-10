"""Hosted-model adapter, DISABLED by default ("available if the event allows hosted models").

It refuses to run unless TEMPO_ALLOW_EXTERNAL_LLM=1 AND ANTHROPIC_API_KEY are both set, so invoice data never
leaves the machine by accident. When enabled it uses structured outputs (`client.messages.parse` with
`output_format=<pydantic model>`) and returns the parsed JSON for the same verification as the local model.
No temperature/top_p/top_k is sent (the current API rejects them); numeric bounds are enforced in code.
The `anthropic` package is not a runtime dependency; install it only where this adapter is allowed.
"""

import os

from pydantic import BaseModel

from tempo.llm.provider import Completion, ExtractionFailed, LLMProvider, ModelCall, ProviderUnavailable

EXTRACT_MODEL_ENV = "TEMPO_ANTHROPIC_EXTRACT_MODEL"
DRAFT_MODEL_ENV = "TEMPO_ANTHROPIC_DRAFT_MODEL"
MAX_TOKENS = 2048


def external_allowed() -> bool:
    return os.environ.get("TEMPO_ALLOW_EXTERNAL_LLM") == "1" and bool(os.environ.get("ANTHROPIC_API_KEY"))


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        if not external_allowed():
            raise ProviderUnavailable(
                "hosted model disabled: set TEMPO_ALLOW_EXTERNAL_LLM=1 and ANTHROPIC_API_KEY to enable it"
            )
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderUnavailable("the `anthropic` package is not installed") from exc
        self._client = anthropic.Anthropic()
        self.model = os.environ.get(EXTRACT_MODEL_ENV, "claude-haiku-5-5")
        self._draft_model = os.environ.get(DRAFT_MODEL_ENV, "claude-sonnet-5-5")

    def complete(self, call: ModelCall, schema: type[BaseModel]) -> Completion:
        messages = call.messages()
        model = self._draft_model if call.task == "draft" else self.model
        try:
            response = self._client.messages.parse(
                model=model,
                max_tokens=MAX_TOKENS,
                system=messages[0]["content"],
                messages=messages[1:],
                output_format=schema,
            )
        except Exception as exc:  # transport and API errors: unavailable, never retried blindly
            raise ProviderUnavailable(f"anthropic call failed: {type(exc).__name__}") from exc
        parsed = getattr(response, "parsed_output", None)
        if parsed is None or getattr(response, "stop_reason", "") in ("refusal", "max_tokens"):
            raise ExtractionFailed(
                f"no structured output (stop_reason={getattr(response, 'stop_reason', None)})"
            )
        return Completion(parsed.model_dump_json(), self.name, model)
