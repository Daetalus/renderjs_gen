from __future__ import annotations

from abc import ABC, abstractmethod
import json
import time
from typing import Any, Callable, Mapping

import requests


DEFAULT_INFERENCE_BASE_URL = "http://localhost"
DEFAULT_INFERENCE_MODEL = "bartowski/google_gemma-4-26B-A4B-it-GGUF:IQ4_XS"
DEFAULT_TIMEOUT = 120.0


class InferenceClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class InferenceClient(ABC):
    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_schema: dict[str, Any] | None = None,
        stream: bool = False,
        on_token: Callable[[str], None] | None = None,
        on_event: Callable[[str], None] | None = None,
    ) -> str:
        raise NotImplementedError


class LlamaCppClient(InferenceClient):
    def __init__(
        self,
        base_url: str = DEFAULT_INFERENCE_BASE_URL,
        *,
        model: str = DEFAULT_INFERENCE_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        api_key: str | None = None,
        session: requests.Session | None = None,
        extra_headers: Mapping[str, str] | None = None,
        max_retries: int = 2,
        retry_backoff: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self.session = session or requests.Session()
        self.extra_headers = dict(extra_headers or {})
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff = max(0.0, float(retry_backoff))

    @property
    def chat_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def complete(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_schema: dict[str, Any] | None = None,
        stream: bool = False,
        on_token: Callable[[str], None] | None = None,
        on_event: Callable[[str], None] | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "n_predict": max_tokens,
            "stream": stream,
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": json_schema,
                },
            }

        last_error: InferenceClientError | None = None
        max_attempts = self.max_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                self._emit_event(
                    on_event,
                    "Inference call "
                    f"attempt {attempt}/{max_attempts} started "
                    f"(stream={stream}, json_schema={'yes' if json_schema is not None else 'no'}, "
                    f"messages={len(messages)}, max_tokens={max_tokens})",
                )
                if stream:
                    result = self._complete_streaming(
                        payload,
                        on_token=on_token,
                        on_event=on_event,
                        attempt=attempt,
                        max_attempts=max_attempts,
                    )
                else:
                    result = self._complete_once(
                        payload,
                        on_event=on_event,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        subrequest_label="primary non-stream",
                    )
                self._emit_event(
                    on_event,
                    f"Inference call attempt {attempt}/{max_attempts} succeeded with {len(result)} chars",
                )
                return result
            except InferenceClientError as exc:
                last_error = exc
                self._emit_event(
                    on_event,
                    "Inference call attempt "
                    f"{attempt}/{max_attempts} failed: {exc} "
                    f"(retryable={exc.retryable})",
                )
                if not exc.retryable or attempt > self.max_retries:
                    raise
                self._emit_event(
                    on_event,
                    f"Retrying after {self.retry_backoff * attempt:.1f}s backoff",
                )
                time.sleep(self.retry_backoff * attempt)
        if last_error is not None:
            raise last_error
        raise InferenceClientError("Inference request failed without a detailed error.")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _complete_once(
        self,
        payload: dict[str, Any],
        *,
        on_event: Callable[[str], None] | None = None,
        attempt: int | None = None,
        max_attempts: int | None = None,
        subrequest_label: str = "non-stream",
    ) -> str:
        if attempt is not None and max_attempts is not None:
            self._emit_event(
                on_event,
                f"Attempt {attempt}/{max_attempts} {subrequest_label} subrequest started",
            )
        try:
            response = self.session.post(
                self.chat_url,
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise InferenceClientError(
                f"Request error while calling {self.chat_url}: {exc}",
                retryable=True,
            ) from exc

        self._emit_event(
            on_event,
            "Attempt "
            f"{attempt}/{max_attempts} {subrequest_label} subrequest received "
            f"HTTP status={response.status_code} url={response.url}",
        )
        self._raise_for_error_response(response)
        try:
            body = response.json()
        except ValueError as exc:
            raise InferenceClientError(
                f"Inference endpoint returned non-JSON response from {self.chat_url}: {response.text[:500]!r}",
                retryable=False,
            ) from exc
        return self._extract_content(body)

    def _complete_streaming(
        self,
        payload: dict[str, Any],
        *,
        on_token: Callable[[str], None] | None,
        on_event: Callable[[str], None] | None = None,
        attempt: int | None = None,
        max_attempts: int | None = None,
    ) -> str:
        stream_payload = dict(payload)
        stream_payload["stream"] = True
        if attempt is not None and max_attempts is not None:
            self._emit_event(
                on_event,
                f"Attempt {attempt}/{max_attempts} streaming subrequest started",
            )
        try:
            with self.session.post(
                self.chat_url,
                json=stream_payload,
                headers=self._headers(),
                timeout=self.timeout,
                stream=True,
            ) as response:
                self._emit_event(
                    on_event,
                    "Attempt "
                    f"{attempt}/{max_attempts} streaming subrequest received "
                    f"HTTP status={response.status_code} url={response.url}",
                )
                self._raise_for_error_response(response)
                parts: list[str] = []
                for raw_line in response.iter_lines(chunk_size=1, decode_unicode=True):
                    if raw_line is None:
                        continue
                    line = raw_line.strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line == "[DONE]":
                        continue
                    try:
                        body = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = self._extract_stream_chunk(body)
                    if not token:
                        continue
                    parts.append(token)
                    if on_token is not None:
                        on_token(token)
        except requests.RequestException as exc:
            raise InferenceClientError(
                f"Streaming request error while calling {self.chat_url}: {exc}",
                retryable=True,
            ) from exc

        text = "".join(parts)
        if not text.strip():
            self._emit_event(
                on_event,
                f"Attempt {attempt}/{max_attempts} streaming subrequest contained no token content; "
                "falling back to non-stream subrequest",
            )
            fallback_payload = dict(payload)
            fallback_payload["stream"] = False
            return self._complete_once(
                fallback_payload,
                on_event=on_event,
                attempt=attempt,
                max_attempts=max_attempts,
                subrequest_label="fallback non-stream",
            )
        return text

    def _raise_for_error_response(self, response: requests.Response) -> None:
        if response.status_code < 400:
            return
        try:
            detail = response.text[:1000]
        except Exception:
            detail = "<unavailable>"
        raise InferenceClientError(
            f"{response.status_code} Server Error for url: {response.url}. Response preview: {detail!r}",
            status_code=response.status_code,
            retryable=response.status_code >= 500,
        )

    @staticmethod
    def _extract_stream_chunk(body: dict[str, Any]) -> str:
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                delta = first.get("delta")
                if isinstance(delta, dict):
                    return LlamaCppClient._extract_message_text(delta)
                message = first.get("message")
                if isinstance(message, dict):
                    return LlamaCppClient._extract_message_text(message)
        text = LlamaCppClient._extract_text_content(body.get("content"))
        if text:
            return text
        return LlamaCppClient._extract_text_content(body.get("reasoning_content"))

    @staticmethod
    def _extract_content(body: dict[str, Any]) -> str:
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InferenceClientError(f"Unexpected inference response: {body!r}") from exc

        text = LlamaCppClient._extract_message_text(message)
        if text:
            return text
        raise InferenceClientError(f"Unsupported message content format: {message!r}")

    @staticmethod
    def _extract_message_text(message: Any) -> str:
        if isinstance(message, dict):
            text = LlamaCppClient._extract_text_content(message.get("content"))
            if text:
                return text
            return LlamaCppClient._extract_text_content(message.get("reasoning_content"))
        return LlamaCppClient._extract_text_content(message)

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
        return ""

    @staticmethod
    def _emit_event(callback: Callable[[str], None] | None, message: str) -> None:
        if callback is not None:
            callback(message)
