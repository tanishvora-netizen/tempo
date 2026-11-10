"""Local open-weights model served by Ollama on 127.0.0.1. Invoice data never leaves the machine."""

import os
import time

from pydantic import BaseModel

from tempo.llm.provider import (
    Completion,
    ExtractionFailed,
    LLMProvider,
    ModelCall,
    ProviderUnavailable,
    local_model_tag,
)

DEFAULT_HOST = "http://127.0.0.1:11434"
TIMEOUT_S = 180.0
RETRY_BACKOFF_S = 2.0
NUM_CTX = 8192


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        from ollama import Client

        self.model = model or local_model_tag()
        self.host = host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
        self._client = Client(host=self.host, timeout=TIMEOUT_S)

    def is_available(self) -> bool:
        """True if Ollama answers and has the model pulled."""
        try:
            names = {m.model for m in self._client.list().models}
        except Exception:
            return False
        return self.model in names

    def complete(self, call: ModelCall, schema: type[BaseModel]) -> Completion:
        response = self._chat_with_one_retry(call, schema)
        if getattr(response, "done_reason", None) == "length":
            raise ExtractionFailed("model output truncated (num_ctx or num_predict reached)")
        content = response.message.content or ""
        if not content.strip():
            raise ExtractionFailed("empty model output (refusal or no answer)")
        return Completion(content, self.name, self.model)

    def _chat_with_one_retry(self, call: ModelCall, schema: type[BaseModel]):
        """Retry once, with backoff, on transport errors only; never on bad answers."""
        from ollama import ResponseError

        kwargs = {
            "model": self.model,
            "messages": call.messages(),
            "format": schema.model_json_schema(),
            "options": {"temperature": 0, "num_ctx": NUM_CTX},
        }
        if self.model.startswith("qwen3"):
            kwargs["think"] = False
        for attempt in range(2):
            try:
                return self._client.chat(**kwargs)
            except ResponseError as exc:
                raise ProviderUnavailable(f"ollama error: {exc.error}") from exc
            except (ConnectionError, OSError, TimeoutError) as exc:
                if attempt == 1:
                    raise ProviderUnavailable(f"ollama unreachable at {self.host}: {exc}") from exc
                time.sleep(RETRY_BACKOFF_S)
            except Exception as exc:
                if "connect" not in str(exc).lower() or attempt == 1:
                    raise ProviderUnavailable(f"ollama transport error: {exc}") from exc
                time.sleep(RETRY_BACKOFF_S)
        raise ProviderUnavailable("unreachable")
