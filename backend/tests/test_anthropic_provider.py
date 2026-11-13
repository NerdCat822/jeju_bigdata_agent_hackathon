"""클라우드 공급자: 실제 API를 부르지 않고(가짜 전송 계층) 요청 형식과 응답 처리를 확인해요."""

import json

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from meomulmeong.llm.anthropic_provider import FALLBACK_BETA, AnthropicProvider  # noqa: E402
from meomulmeong.llm.base import ExplainOut, LLMError, ParseOut  # noqa: E402


def message(text: str, stop_reason: str = "end_turn", model: str = "claude-opus-5-5") -> dict:
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": text}] if text else [],
            "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 120, "output_tokens": 30}}


def provider(handler, model: str = "claude-opus-5-5") -> tuple[AnthropicProvider, list]:
    seen: list = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    p = AnthropicProvider(model)
    p._client = anthropic.Anthropic(api_key="test-key", max_retries=0,
                                    http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(wrapped)))
    return p, seen


def test_request_shape_and_parsing():
    p, seen = provider(lambda r: httpx2.Response(200, json=message(json.dumps({"explanation": "방문자는 늘었어요."}))))
    out = p.generate("시스템 지침", "근거: …", ExplainOut, purpose="explain")
    assert out.explanation == "방문자는 늘었어요."
    req = seen[0]
    body = json.loads(req.content)
    assert req.url.path == "/v1/messages" and FALLBACK_BETA in req.headers["anthropic-beta"]
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 16000
    assert body["system"] == "시스템 지침" and body["messages"] == [{"role": "user", "content": "근거: …"}]
    assert body["fallbacks"] == "default"  # 거절에 대비한 서버 측 대체 모델
    fmt = body["output_config"]["format"]
    assert body["output_config"]["effort"] == "low" and fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False and fmt["schema"]["required"] == ["explanation"]
    assert "temperature" not in body and "thinking" not in body  # 최신 모델은 샘플링 값을 받지 않아요
    assert p.usage.calls == 1 and p.usage.input_tokens == 120 and p.is_cloud


def test_parse_schema_is_strict():
    schema = ParseOut.model_json_schema()
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])


def test_refusal_and_empty_output_raise():
    p, _ = provider(lambda r: httpx2.Response(200, json=message("", stop_reason="refusal")))
    with pytest.raises(LLMError, match="거절"):
        p.generate("s", "u", ExplainOut)
    p, _ = provider(lambda r: httpx2.Response(200, json=message("이건 JSON이 아니에요")))
    with pytest.raises(LLMError, match="형식"):
        p.generate("s", "u", ExplainOut)


def test_auth_and_server_errors_are_wrapped():
    err = {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
    p, _ = provider(lambda r: httpx2.Response(401, json=err))
    with pytest.raises(LLMError, match="인증"):
        p.generate("s", "u", ExplainOut)
    p, _ = provider(lambda r: httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}}))
    with pytest.raises(LLMError, match="서버 오류"):
        p.generate("s", "u", ExplainOut)


def test_drops_fallbacks_when_rejected():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        body = json.loads(request.content)
        if "fallbacks" in body:
            err = {"type": "error", "error": {"type": "invalid_request_error", "message": "fallbacks: not supported on this platform"}}
            return httpx2.Response(400, json=err)
        return httpx2.Response(200, json=message(json.dumps({"explanation": "ok"})))

    p, seen = provider(handler)
    assert p.generate("s", "u", ExplainOut).explanation == "ok"
    assert calls["n"] == 2 and "fallbacks" not in json.loads(seen[1].content)
    p.generate("s", "u", ExplainOut)
    assert calls["n"] == 3  # 한 번 거절되면 그 뒤로는 보내지 않아요


def test_older_models_skip_fallbacks():
    p, seen = provider(lambda r: httpx2.Response(200, json=message(json.dumps({"explanation": "ok"}), model="claude-haiku-5-5")),
                       model="claude-haiku-5-5")
    p.generate("s", "u", ExplainOut)
    assert "fallbacks" not in json.loads(seen[0].content)
