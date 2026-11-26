import math

import httpx

from app.config import OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, OLLAMA_EMBED_MODEL


class OllamaUnavailable(RuntimeError):
    pass


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = OLLAMA_BASE_URL
        self.chat_model = OLLAMA_CHAT_MODEL
        self.embed_model = OLLAMA_EMBED_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embed_model:
            raise OllamaUnavailable("Set OLLAMA_EMBED_MODEL to enable document indexing.")
        try:
            response = httpx.post(
                self.base_url + "/api/embed",
                json={"model": self.embed_model, "input": texts, "truncate": True},
                timeout=120.0,
            )
            response.raise_for_status()
            payload = response.json()
            vectors = payload.get("embeddings", []) if isinstance(payload, dict) else []
            if len(vectors) != len(texts) or not all(isinstance(vector, list) and vector for vector in vectors):
                raise OllamaUnavailable("Ollama returned an invalid embedding response.")
            normalized = [[float(value) for value in vector] for vector in vectors]
            if any(not math.isfinite(value) for vector in normalized for value in vector):
                raise OllamaUnavailable("Ollama returned non-finite embedding values.")
            dimensions = {len(vector) for vector in normalized}
            if len(dimensions) != 1:
                raise OllamaUnavailable("Ollama returned inconsistent embedding dimensions.")
            return normalized
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise OllamaUnavailable("Ollama embedding request failed.") from exc

    def chat(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if not self.chat_model:
            raise OllamaUnavailable("Set OLLAMA_CHAT_MODEL to enable AI answers.")
        payload = {
            "model": self.chat_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0.2},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            response = httpx.post(self.base_url + "/api/chat", json=payload, timeout=180.0)
            response.raise_for_status()
            payload = response.json()
            message = payload.get("message", {}) if isinstance(payload, dict) else {}
            content = message.get("content", "") if isinstance(message, dict) else ""
            if not isinstance(content, str) or not content.strip():
                raise OllamaUnavailable("Ollama returned an empty response.")
            return content.strip()
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise OllamaUnavailable("Ollama chat request failed.") from exc
