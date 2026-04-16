from __future__ import annotations

from inference_client import LlamaCppClient
from tests.http_test_server import JsonResponse, StreamingResponse, run_json_server


def test_complete_posts_expected_payload() -> None:
    def responder(path, body):
        assert path == "/v1/chat/completions"
        assert body == {
            "model": "qwen",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.15,
            "n_predict": 123,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": {"type": "object"},
                },
            },
        }
        return {
            "choices": [
                {
                    "message": {
                        "content": "final answer",
                    }
                }
            ]
        }

    with run_json_server(responder) as (base_url, state):
        client = LlamaCppClient(
            base_url=base_url,
            api_key="EMPTY",
            model="qwen",
            timeout=55.0,
        )
        result = client.complete(
            [{"role": "user", "content": "hello"}],
            temperature=0.15,
            max_tokens=123,
            json_schema={"type": "object"},
        )

    assert result == "final answer"
    assert len(state.requests) == 1
    assert state.requests[0].path == "/v1/chat/completions"
    assert state.requests[0].headers["Authorization"] == "Bearer EMPTY"


def test_complete_accepts_v1_base_url_and_list_content() -> None:
    def responder(path, body):
        assert path == "/v1/chat/completions"
        assert body["messages"] == [{"role": "user", "content": "ping"}]
        assert body["stream"] is False
        return {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "hello "},
                            {"type": "text", "text": "world"},
                        ]
                    }
                }
            ]
        }

    with run_json_server(responder) as (base_url, state):
        client = LlamaCppClient(base_url=f"{base_url}/v1")
        result = client.complete([{"role": "user", "content": "ping"}])

    assert result == "hello world"
    assert state.requests[0].path == "/v1/chat/completions"


def test_complete_uses_reasoning_content_when_content_is_empty() -> None:
    def responder(path, body):
        assert path == "/v1/chat/completions"
        assert body["stream"] is False
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "json from reasoning channel",
                    }
                }
            ]
        }

    with run_json_server(responder) as (base_url, _):
        client = LlamaCppClient(base_url=base_url)
        result = client.complete([{"role": "user", "content": "ping"}])

    assert result == "json from reasoning channel"


def test_complete_streams_sse_chunks() -> None:
    tokens: list[str] = []

    def responder(path, body):
        assert path == "/v1/chat/completions"
        assert body["stream"] is True
        return StreamingResponse(
            chunks=[
                'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n',
                'data: {"choices":[{"delta":{"content":"world"}}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

    with run_json_server(responder) as (base_url, _):
        client = LlamaCppClient(base_url=base_url)
        result = client.complete(
            [{"role": "user", "content": "ping"}],
            stream=True,
            on_token=tokens.append,
        )

    assert result == "hello world"
    assert tokens == ["hello ", "world"]


def test_complete_retries_on_retryable_server_error() -> None:
    call_count = {"value": 0}
    events: list[str] = []

    def responder(path, body):
        assert path == "/v1/chat/completions"
        call_count["value"] += 1
        if call_count["value"] == 1:
            return JsonResponse(body={"error": "temporary failure"}, status=500)
        return {
            "choices": [
                {
                    "message": {
                        "content": "ok after retry",
                    }
                }
            ]
        }

    with run_json_server(responder) as (base_url, state):
        client = LlamaCppClient(base_url=base_url, max_retries=1, retry_backoff=0.0)
        result = client.complete([{"role": "user", "content": "retry me"}], on_event=events.append)

    assert result == "ok after retry"
    assert len(state.requests) == 2
    assert any("Inference call attempt 1/2 started" in event for event in events)
    assert any("Inference call attempt 1/2 failed" in event for event in events)
    assert any("Inference call attempt 2/2 succeeded" in event for event in events)


def test_complete_falls_back_to_non_stream_when_stream_returns_no_tokens() -> None:
    call_count = {"value": 0}

    def responder(path, body):
        assert path == "/v1/chat/completions"
        call_count["value"] += 1
        if call_count["value"] == 1:
            assert body["stream"] is True
            return StreamingResponse(chunks=["data: [DONE]\n\n"])
        assert body["stream"] is False
        return {
            "choices": [
                {
                    "message": {
                        "content": "fallback non-stream response",
                    }
                }
            ]
        }

    with run_json_server(responder) as (base_url, state):
        client = LlamaCppClient(base_url=base_url)
        result = client.complete(
            [{"role": "user", "content": "ping"}],
            stream=True,
        )

    assert result == "fallback non-stream response"
    assert len(state.requests) == 2


def test_complete_streaming_reads_reasoning_content_chunks() -> None:
    tokens: list[str] = []

    def responder(path, body):
        assert path == "/v1/chat/completions"
        assert body["stream"] is True
        return StreamingResponse(
            chunks=[
                'data: {"choices":[{"delta":{"reasoning_content":"hello "}}]}\n\n',
                'data: {"choices":[{"delta":{"reasoning_content":"world"}}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )

    with run_json_server(responder) as (base_url, _):
        client = LlamaCppClient(base_url=base_url)
        result = client.complete(
            [{"role": "user", "content": "ping"}],
            stream=True,
            on_token=tokens.append,
        )

    assert result == "hello world"
    assert tokens == ["hello ", "world"]
