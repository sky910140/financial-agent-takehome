from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MAX_COMPLETION_TOKENS = 600
DEFAULT_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    model: str
    text: str
    used_remote_model: bool
    error: str | None = None


class ModelGateway:
    """Only the two required primary reasoning models are configured here."""

    def __init__(
        self,
        doubao_api_key: str | None = None,
        deepseek_api_key: str | None = None,
        *,
        doubao_base_url: str | None = None,
        deepseek_base_url: str | None = None,
        doubao_model: str | None = None,
        deepseek_model: str | None = None,
    ) -> None:
        self.providers = {
            "doubao": {
                "key": doubao_api_key if doubao_api_key is not None else os.getenv("DOUBAO_API_KEY"),
                "base_url": doubao_base_url or os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"),
                "model": doubao_model or os.getenv("DOUBAO_MODEL", "doubao-seed-evolving"),
            },
            "deepseek": {
                "key": deepseek_api_key if deepseek_api_key is not None else os.getenv("DEEPSEEK_API_KEY"),
                "base_url": deepseek_base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions"),
                "model": deepseek_model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            },
        }

    def complete(
        self,
        provider: str,
        system: str,
        user: str,
        *,
        max_tokens: int = MAX_COMPLETION_TOKENS,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> ModelResponse:
        if provider not in self.providers:
            raise ValueError(f"Unsupported primary model provider: {provider}")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if timeout < 1:
            raise ValueError("timeout must be positive")
        settings = self.providers[provider]
        key = settings["key"]
        if not key:
            return ModelResponse("offline", str(settings["model"]), "", False, "API key is not configured")
        request_body: dict[str, object] = {
            "model": settings["model"],
            "temperature": 0,
            # Keep the three sequential model stages responsive for an interactive CLI.
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if provider == "doubao":
            request_body["thinking"] = {"type": "disabled"}
        payload = json.dumps(request_body).encode("utf-8")
        request = Request(
            str(settings["base_url"]),
            data=payload,
            method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            text = body["choices"][0]["message"]["content"].strip()
            if not text:
                return ModelResponse("offline", str(settings["model"]), "", False, "Remote model returned empty content")
            return ModelResponse(provider, str(settings["model"]), text, True)
        except HTTPError as exc:
            return ModelResponse("offline", str(settings["model"]), "", False, f"HTTP {exc.code}: remote request unavailable")
        except (URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
            return ModelResponse("offline", str(settings["model"]), "", False, f"{type(exc).__name__}: remote request unavailable")
