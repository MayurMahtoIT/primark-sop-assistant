"""Thin wrapper over Mesh API's OpenAI-compatible Chat Completions endpoint."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


class LLM:
    def __init__(
        self, api_key: str, base_url: str, default_model_id: str, max_tokens: int, temperature: float
    ):
        if not api_key:
            raise ValueError("MESH_API_KEY is required for generation")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=90.0, max_retries=2)
        self._model_id = default_model_id
        self._max_tokens = max_tokens
        self._temperature = temperature

    def generate(
        self,
        system: str,
        messages: list[dict[str, str]],
        *,
        model_id: str | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, Usage]:
        chat_messages = [{"role": "system", "content": system}]
        chat_messages.extend({"role": item["role"], "content": item["content"]} for item in messages)
        response = self._client.chat.completions.create(
            model=model_id or self._model_id,
            messages=chat_messages,
            max_tokens=max_tokens or self._max_tokens,
            temperature=self._temperature,
        )
        answer = response.choices[0].message.content or ""
        usage = response.usage
        return answer.strip(), Usage(
            usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0
        )
