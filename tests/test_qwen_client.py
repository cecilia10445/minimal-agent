import json
from unittest.mock import MagicMock

import openai
import pytest

from src.config import LLMSettings
from src.qwen_client import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMServiceError,
    LLMTimeoutError,
    LLMResponseParseError,
    OpenAICompatibleLLMClient,
)


def _make_settings(**kwargs) -> LLMSettings:
    defaults = dict(
        api_key="sk-test",
        base_url="https://test.example.com/v1",
        model="qwen-test",
        enable_thinking=False,
        request_timeout=30,
        max_retries=1,
    )
    defaults.update(kwargs)
    return LLMSettings(**defaults)


def _mock_message(content=None, tool_calls=None):
    class FakeMessage:
        def __init__(self, content, tool_calls):
            self.content = content
            self.tool_calls = tool_calls or []

    return FakeMessage(content=content, tool_calls=tool_calls or [])


def _mock_tool_call(id, name, arguments: dict):
    class FakeFunction:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    class FakeToolCall:
        def __init__(self, id, function):
            self.id = id
            self.function = function
            self.type = "function"

    return FakeToolCall(id=id, function=FakeFunction(name=name, arguments=json.dumps(arguments)))


def _mock_response(choices):
    class FakeChoice:
        def __init__(self, message):
            self.message = message

    class FakeResponse:
        def __init__(self, choices):
            self.choices = [FakeChoice(m) for m in choices]

    return FakeResponse(choices)


class MockCompletions:
    def __init__(self, parent):
        self._parent = parent

    def create(self, **kwargs):
        self._parent.call_kwargs = kwargs
        if self._parent._raise_error:
            raise self._parent._raise_error
        resp = self._parent.responses[self._parent._index]
        self._parent._index += 1
        return resp


class MockChat:
    def __init__(self, parent):
        self.completions = MockCompletions(parent)


class MockSDK:
    def __init__(self, responses=None, raise_error=None):
        self.responses = responses or []
        self._index = 0
        self._raise_error = raise_error
        self.call_kwargs = None
        self.chat = MockChat(self)


class TestTextResponse:
    def test_plain_text(self):
        settings = _make_settings()
        sdk = MockSDK(responses=[_mock_response([_mock_message(content="Hello!")])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        result = client.complete(messages=[{"role": "user", "content": "Hi"}], tools=[])
        assert result.content == "Hello!"
        assert result.tool_calls == []
        assert result.decision_summary == "Hello!"

    def test_content_none(self):
        settings = _make_settings()
        sdk = MockSDK(responses=[_mock_response([_mock_message(content=None)])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        result = client.complete(messages=[{"role": "user", "content": "Hi"}], tools=[])
        assert result.content is None
        assert result.tool_calls == []


class TestToolCall:
    def test_single_tool_call(self):
        settings = _make_settings()
        msg = _mock_message(
            content=None,
            tool_calls=[
                _mock_tool_call(id="call_1", name="calculator", arguments={"expression": "1+1"}),
            ],
        )
        sdk = MockSDK(responses=[_mock_response([msg])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        result = client.complete(messages=[{"role": "user", "content": "calc"}], tools=[])
        assert result.content is None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_1"
        assert result.tool_calls[0].name == "calculator"
        assert result.tool_calls[0].arguments == {"expression": "1+1"}

    def test_multiple_tool_calls(self):
        settings = _make_settings()
        msg = _mock_message(
            content=None,
            tool_calls=[
                _mock_tool_call(id="c1", name="calculator", arguments={"expression": "1+1"}),
                _mock_tool_call(id="c2", name="search", arguments={"keywords": "python"}),
            ],
        )
        sdk = MockSDK(responses=[_mock_response([msg])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        result = client.complete(messages=[], tools=[])
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "calculator"
        assert result.tool_calls[1].name == "search"

    def test_content_with_tool_calls(self):
        settings = _make_settings()
        msg = _mock_message(
            content="I will calculate",
            tool_calls=[
                _mock_tool_call(id="c1", name="calculator", arguments={"expression": "2+3"}),
            ],
        )
        sdk = MockSDK(responses=[_mock_response([msg])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        result = client.complete(messages=[], tools=[])
        assert result.content == "I will calculate"
        assert len(result.tool_calls) == 1

    def test_arguments_parsed_as_dict(self):
        settings = _make_settings()
        msg = _mock_message(
            content=None,
            tool_calls=[
                _mock_tool_call(id="c1", name="calculator", arguments={"a": 1}),
            ],
        )
        sdk = MockSDK(responses=[_mock_response([msg])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        result = client.complete(messages=[], tools=[])
        assert isinstance(result.tool_calls[0].arguments, dict)
        assert result.tool_calls[0].arguments == {"a": 1}

    def test_arguments_not_object(self):
        settings = _make_settings()

        class FakeFunction:
            def __init__(self):
                self.name = "calc"
                self.arguments = json.dumps([1, 2, 3])

        class FakeToolCall:
            def __init__(self):
                self.id = "c1"
                self.function = FakeFunction()
                self.type = "function"

        class FakeMessage:
            def __init__(self):
                self.content = None
                self.tool_calls = [FakeToolCall()]

        sdk = MockSDK(responses=[_mock_response([FakeMessage()])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        with pytest.raises(LLMResponseParseError, match="must be a JSON object"):
            client.complete(messages=[], tools=[])

    def test_arguments_invalid_json(self):
        settings = _make_settings()

        class FakeFunction:
            def __init__(self):
                self.name = "calc"
                self.arguments = "not json at all"

        class FakeToolCall:
            def __init__(self):
                self.id = "c1"
                self.function = FakeFunction()
                self.type = "function"

        class FakeMessage:
            def __init__(self):
                self.content = None
                self.tool_calls = [FakeToolCall()]

        sdk = MockSDK(responses=[_mock_response([FakeMessage()])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        with pytest.raises(LLMResponseParseError, match="not valid JSON"):
            client.complete(messages=[], tools=[])


class TestEmptyChoices:
    def test_no_choices(self):
        settings = _make_settings()

        class FakeResponse:
            def __init__(self):
                self.choices = []

        sdk = MockSDK(responses=[FakeResponse()])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        with pytest.raises(LLMResponseParseError, match="no choices"):
            client.complete(messages=[], tools=[])


class TestAPIErrors:
    def _fake_response(self):
        req = MagicMock()
        resp = MagicMock()
        resp.request = req
        return resp

    def test_authentication_error(self):
        settings = _make_settings()
        sdk = MockSDK(raise_error=openai.AuthenticationError(
            "Incorrect API key", response=self._fake_response(), body={}
        ))
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        with pytest.raises(LLMAuthenticationError):
            client.complete(messages=[], tools=[])

    def test_rate_limit_error(self):
        settings = _make_settings()
        sdk = MockSDK(raise_error=openai.RateLimitError(
            "Rate limited", response=self._fake_response(), body={}
        ))
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        with pytest.raises(LLMRateLimitError):
            client.complete(messages=[], tools=[])

    def test_timeout_error(self):
        settings = _make_settings()
        sdk = MockSDK(raise_error=openai.APITimeoutError("Request timed out"))
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        with pytest.raises(LLMTimeoutError):
            client.complete(messages=[], tools=[])

    def test_service_error(self):
        settings = _make_settings()
        sdk = MockSDK(raise_error=openai.APIStatusError(
            "Internal error", response=self._fake_response(), body={}
        ))
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        with pytest.raises(LLMServiceError):
            client.complete(messages=[], tools=[])

    def test_api_key_not_in_message(self):
        settings = _make_settings()
        sdk = MockSDK(raise_error=openai.AuthenticationError(
            "Incorrect API key", response=self._fake_response(), body={}
        ))
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        try:
            client.complete(messages=[], tools=[])
        except LLMAuthenticationError as e:
            msg = str(e).lower()
            assert "sk-test" not in msg


class TestRequestParams:
    def test_params_sent(self):
        settings = _make_settings(model="qwen-par-test", enable_thinking=True)
        sdk = MockSDK(responses=[_mock_response([_mock_message(content="ok")])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        client.complete(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "calc"}}],
        )
        kwargs = sdk.call_kwargs
        assert kwargs["model"] == "qwen-par-test"
        assert kwargs["messages"] == [{"role": "user", "content": "hello"}]
        assert len(kwargs["tools"]) == 1
        assert kwargs["tool_choice"] == "auto"
        assert kwargs["extra_body"]["enable_thinking"] is True

    def test_enable_thinking_false(self):
        settings = _make_settings(enable_thinking=False)
        sdk = MockSDK(responses=[_mock_response([_mock_message(content="ok")])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        client.complete(messages=[], tools=[])
        assert sdk.call_kwargs["extra_body"]["enable_thinking"] is False


class TestNoToolExecution:
    def test_no_tool_execution_in_adapter(self):
        settings = _make_settings()
        sdk = MockSDK(responses=[_mock_response([_mock_message(content="ok")])])
        client = OpenAICompatibleLLMClient(settings=settings, sdk_client=sdk)
        result = client.complete(messages=[], tools=[])
        # Only returns LLMResponse; never executes tools
        assert isinstance(result.content, str)
