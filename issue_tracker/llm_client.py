import json
import time
import uuid
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


@dataclass(frozen=True)
class ChatCompletionResult:
    content: object
    usage: dict


def log_payload_preview(value, max_chars):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + f"... [日志已截断，原始长度 {len(value)} 字符]"


class OpenAICompatibleChatClient:
    """Call an OpenAI-compatible Chat Completions endpoint via the OpenAI SDK."""

    def __init__(self, app, client_factory=OpenAI):
        self.app = app
        self._client_factory = client_factory

    def create_issue_analysis(self, *, issue_number, messages, comments_count):
        config = self.app.config
        api_key = config["GLM_API_KEY"]
        if not api_key:
            raise RuntimeError("尚未配置 GLM_API_KEY")

        base_url = config["GLM_API_BASE_URL"].rstrip("/")
        endpoint = base_url + "/chat/completions"
        local_request_id = uuid.uuid4().hex
        request_payload = {
            "model": config["GLM_MODEL"],
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
            "response_format": {"type": "json_object"},
            "max_completion_tokens": config["GLM_MAX_OUTPUT_TOKENS"],
        }
        reasoning_effort = config["GLM_REASONING_EFFORT"]
        if reasoning_effort:
            request_payload["reasoning_effort"] = reasoning_effort
        self.app.logger.warning(
            "GLM request started id=%s issue=#%s url=%s model=%s comments=%s timeout=%ss",
            local_request_id,
            issue_number,
            endpoint,
            config["GLM_MODEL"],
            comments_count,
            config["GLM_REQUEST_TIMEOUT"],
        )
        if config["GLM_LOG_PAYLOADS"]:
            self.app.logger.warning(
                "GLM request payload id=%s payload=%s",
                local_request_id,
                log_payload_preview(request_payload, config["GLM_LOG_MAX_CHARS"]),
            )

        started_at = time.monotonic()
        client = self._client_factory(
            api_key=api_key,
            base_url=base_url + "/",
            timeout=config["GLM_REQUEST_TIMEOUT"],
            max_retries=0,
        )
        stream = None
        try:
            stream = client.chat.completions.create(**request_payload)
            return self._consume_stream(stream, local_request_id, started_at)
        except APIStatusError as error:
            return self._raise_status_error(error, local_request_id, started_at)
        except APITimeoutError as error:
            elapsed_ms = round((time.monotonic() - started_at) * 1000)
            self.app.logger.warning(
                "GLM request timeout id=%s elapsed_ms=%s error=%s",
                local_request_id,
                elapsed_ms,
                error,
            )
            raise RuntimeError("GLM API 请求超时") from error
        except APIConnectionError as error:
            elapsed_ms = round((time.monotonic() - started_at) * 1000)
            self.app.logger.warning(
                "GLM request transport error id=%s elapsed_ms=%s error=%s",
                local_request_id,
                elapsed_ms,
                error,
            )
            raise RuntimeError(f"GLM API 连接失败：{error}") from error
        finally:
            close_stream = getattr(stream, "close", None)
            if callable(close_stream):
                close_stream()
            client.close()

    def _consume_stream(self, stream, local_request_id, started_at):
        content_parts = []
        reasoning_chars = 0
        finish_reason = ""
        usage = {}
        chunk_count = 0
        upstream_request_id = ""

        for chunk in stream:
            chunk_count += 1
            upstream_request_id = upstream_request_id or str(
                getattr(chunk, "_request_id", "") or ""
            )
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = self._usage_to_dict(chunk_usage)

            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            current_finish_reason = getattr(choice, "finish_reason", None)
            if current_finish_reason:
                finish_reason = current_finish_reason
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            content = getattr(delta, "content", None)
            if isinstance(content, str):
                content_parts.append(content)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning is None:
                reasoning = getattr(delta, "reasoning", None)
            if isinstance(reasoning, str):
                reasoning_chars += len(reasoning)

        content = "".join(content_parts)
        elapsed_ms = round((time.monotonic() - started_at) * 1000)
        self.app.logger.warning(
            "GLM stream completed id=%s elapsed_ms=%s chunks=%s content_length=%s "
            "reasoning_length=%s finish_reason=%s upstream_request_id=%s",
            local_request_id,
            elapsed_ms,
            chunk_count,
            len(content),
            reasoning_chars,
            finish_reason or "<missing>",
            upstream_request_id or "<missing>",
        )
        if self.app.config["GLM_LOG_PAYLOADS"]:
            self.app.logger.warning(
                "GLM response payload id=%s body=%s",
                local_request_id,
                log_payload_preview(content, self.app.config["GLM_LOG_MAX_CHARS"]),
            )

        self._raise_if_truncated(finish_reason)
        if not content.strip():
            raise RuntimeError("GLM API 流式响应中没有分析结果")
        return ChatCompletionResult(content=content, usage=usage)

    @staticmethod
    def _usage_to_dict(usage):
        if isinstance(usage, dict):
            return usage
        model_dump = getattr(usage, "model_dump", None)
        if callable(model_dump):
            value = model_dump(exclude_none=True)
            return value if isinstance(value, dict) else {}
        return {}

    @staticmethod
    def _raise_if_truncated(finish_reason):
        if finish_reason == "length":
            raise RuntimeError(
                "GLM 输出达到长度上限（finish_reason=length），结果在 JSON 完成前被截断；"
                "请降低 GLM_REASONING_EFFORT，或提高 GLM_MAX_OUTPUT_TOKENS"
            )

    def _raise_status_error(self, error, local_request_id, started_at):
        response = error.response
        raw_response = response.text
        self._log_response(response, raw_response, local_request_id, started_at)
        self._raise_http_error(response.status_code, raw_response, cause=error)

    def _log_response(self, response, raw_response, local_request_id, started_at):
        elapsed_ms = round((time.monotonic() - started_at) * 1000)
        headers = response.headers
        content_type = headers.get("Content-Type", "")
        upstream_request_id = (
            headers.get("X-Request-ID")
            or headers.get("X-Zhipu-Request-ID")
            or headers.get("X-Trace-ID")
            or ""
        )
        self.app.logger.warning(
            "GLM response received id=%s status=%s elapsed_ms=%s content_type=%s "
            "content_length=%s upstream_request_id=%s",
            local_request_id,
            response.status_code,
            elapsed_ms,
            content_type or "<missing>",
            len(raw_response),
            upstream_request_id or "<missing>",
        )
        if self.app.config["GLM_LOG_PAYLOADS"]:
            self.app.logger.warning(
                "GLM response payload id=%s body=%s",
                local_request_id,
                log_payload_preview(
                    raw_response, self.app.config["GLM_LOG_MAX_CHARS"]
                ),
            )

    @staticmethod
    def _raise_http_error(status_code, raw_response, cause=None):
        try:
            error_payload = json.loads(raw_response)
            detail = error_payload.get("error", {}).get("message")
        except (ValueError, AttributeError):
            detail = None
        error = RuntimeError(
            f"GLM API 返回 {status_code}"
            + (f"：{str(detail)[:300]}" if detail else "")
        )
        if cause is None:
            raise error
        raise error from cause
