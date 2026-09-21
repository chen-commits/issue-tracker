import json
import re
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


def recover_malformed_chat_content(raw_response):
    """Recover content from gateways that fail to JSON-escape message.content."""
    match = re.search(
        r'"content"\s*:\s*"(?P<content>\{.*?\})"\s*,\s*'
        r'"(?:reasoning_content|finish_reason)"\s*:',
        raw_response,
        flags=re.DOTALL,
    )
    if not match:
        return None
    try:
        parsed = json.loads(match.group("content"))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


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
            "stream": False,
            "response_format": {"type": "json_object"},
        }
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
        try:
            sdk_response = client.chat.completions.with_raw_response.create(
                **request_payload
            )
            http_response = getattr(sdk_response, "http_response", sdk_response)
            return self._parse_response(
                http_response, local_request_id, started_at
            )
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
            client.close()

    def _parse_response(self, response, local_request_id, started_at):
        raw_response = response.text
        self._log_response(response, raw_response, local_request_id, started_at)
        if response.status_code >= 400:
            self._raise_http_error(response.status_code, raw_response)

        try:
            result = json.loads(raw_response)
        except json.JSONDecodeError as error:
            recovered = recover_malformed_chat_content(raw_response)
            if recovered is None:
                raise RuntimeError("GLM API 返回了无效 JSON") from error
            self.app.logger.warning(
                "GLM response recovered from malformed gateway JSON id=%s",
                local_request_id,
            )
            return ChatCompletionResult(content=recovered, usage={})

        if not isinstance(result, dict):
            raise RuntimeError("GLM API 返回了无效响应结构")
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("GLM API 响应中没有分析结果") from error
        usage = result.get("usage")
        return ChatCompletionResult(
            content=content,
            usage=usage if isinstance(usage, dict) else {},
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
