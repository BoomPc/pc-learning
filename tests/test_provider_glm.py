import json
import httpx
import pytest
from math_agent.config import Settings
from math_agent.provider import DeepSeek, ModelError


def glm_settings(tmp_path, **kw):
    return Settings(data_dir=tmp_path, api_key="fake-glm-key", access_token="a" * 40,
                    redis_url="", max_calls=12, api_style="glm",
                    base_url="https://open.bigmodel.cn/api/anthropic", **kw)


def anthropic_response(blocks, stop_reason="end_turn"):
    return {"content": blocks, "stop_reason": stop_reason, "model": "glm-5.3-flash",
            "usage": {"input_tokens": 11, "output_tokens": 7}}


def test_glm_anthropic_tool_roundtrip_and_history_conversion(tmp_path):
    requests = []
    def handler(request):
        assert request.url.path.endswith("/v1/messages")
        assert request.headers["x-api-key"] == "fake-glm-key"
        body = json.loads(request.content); requests.append(body)
        if len(requests) == 1:
            return httpx.Response(200, json=anthropic_response(
                [{"type": "thinking", "thinking": "private"},
                 {"type": "tool_use", "id": "t1", "name": "calculate", "input": {"expr": "1+1"}}],
                "tool_use"))
        return httpx.Response(200, json=anthropic_response(
            [{"type": "text", "text": "```json\n{\"result\": 2}\n```"}]))
    audit = []
    history = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": [
            {"type": "text", "text": "读图"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]},
        {"role": "assistant", "content": None, "reasoning_content": "must not be sent",
         "tool_calls": [{"id": "t1", "type": "function",
                         "function": {"name": "calculate", "arguments": "{\"expr\": \"1+1\"}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "{\"ok\": true}"},
    ]
    client = DeepSeek(glm_settings(tmp_path), lambda *x: audit.append(x), httpx.MockTransport(handler))
    try:
        tools = [{"type": "function", "function": {"name": "calculate", "description": "d",
                  "parameters": {"type": "object", "properties": {}}}}]
        assert client.generate("solve", history, tools=tools,
                               dispatch=lambda *args: {"ok": True}) == {"result": 2}
        assert len(requests) == 2
        first = requests[0]
        assert first["system"] == "system prompt"
        assert first["thinking"] == {"type": "enabled"}
        assert json.dumps(first, ensure_ascii=False).find("must not be sent") == -1
        assert first["tools"] == [{"name": "calculate", "description": "d",
                                   "input_schema": {"type": "object", "properties": {}}}]
        image = first["messages"][0]["content"][1]
        assert image == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}}
        tool_use = first["messages"][1]["content"][0]
        assert tool_use == {"type": "tool_use", "id": "t1", "name": "calculate", "input": {"expr": "1+1"}}
        tool_result = first["messages"][2]["content"][0]
        assert tool_result == {"type": "tool_result", "tool_use_id": "t1", "content": "{\"ok\": true}"}
    finally:
        client.close()


def test_glm_http_error_no_retry(tmp_path):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(429, json={"error": {"code": "1113", "message": "quota"}})
    client = DeepSeek(glm_settings(tmp_path), lambda *args: None, httpx.MockTransport(handler))
    try:
        with pytest.raises(ModelError):
            client.generate("source", [{"role": "user", "content": "json"}])
        assert len(calls) == 1
        assert calls[0]["thinking"] == {"type": "disabled"}
    finally:
        client.close()


def test_glm_final_round_omits_tools_but_keeps_output(tmp_path):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=anthropic_response([{"type": "text", "text": "{\"ok\": true}"}]))
    client = DeepSeek(glm_settings(tmp_path), lambda *args: None, httpx.MockTransport(handler))
    try:
        tools = [{"type": "function", "function": {"name": "calculate", "parameters": {"type": "object", "properties": {}}}}]
        message, finish = client.request("review", [{"role": "user", "content": "final"}],
                                         tools, tool_choice="none")
        assert finish == "stop" and message["content"] == "{\"ok\": true}"
        assert "tools" not in requests[0] and "tool_choice" not in requests[0]
        assert requests[0]["max_tokens"] > 0
    finally:
        client.close()
