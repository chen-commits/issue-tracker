"""Server-side model profiles and asynchronous connection diagnostics."""

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit

from .ai_analysis import parse_ai_json
from .llm_client import OpenAICompatibleChatClient


FIELDS = {
    "base_url": "GLM_API_BASE_URL", "model": "GLM_MODEL", "api_key": "GLM_API_KEY",
    "timeout": "GLM_REQUEST_TIMEOUT", "reasoning_effort": "GLM_REASONING_EFFORT",
    "max_output_tokens": "GLM_MAX_OUTPUT_TOKENS", "json_mode": "LLM_JSON_MODE",
    "send_temperature": "LLM_SEND_TEMPERATURE", "token_parameter": "LLM_TOKEN_PARAMETER",
}
DEFAULTS = {"json_mode": True, "send_temperature": True, "token_parameter": "max_completion_tokens"}


def now():
    return datetime.now(timezone.utc).isoformat()


def connect(app):
    connection = sqlite3.connect(app.config["DB_PATH"], timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_model_settings(app):
    with closing(connect(app)) as connection, connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS model_profiles (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, config_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_settings (
                id INTEGER PRIMARY KEY CHECK(id = 1), active_id TEXT NOT NULL
            );
            INSERT OR IGNORE INTO model_settings VALUES(1, 'env');
            CREATE TABLE IF NOT EXISTS model_connection_tests (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, elapsed_ms INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '', result_json TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL, completed_at TEXT
            );
        """)
        connection.execute(
            "UPDATE model_connection_tests SET status = 'failed', message = '服务已重启，请重新测试', completed_at = ? WHERE status = 'running'",
            (now(),),
        )
    app.extensions["model_test_slots"] = threading.BoundedSemaphore(2)


def environment_config(app):
    return {field: app.config.get(key, DEFAULTS.get(field)) for field, key in FIELDS.items()}


def load_profile(app, profile_id):
    if profile_id == "env":
        return {"id": "env", "name": "环境变量配置", "config": environment_config(app)}
    with closing(connect(app)) as connection:
        row = connection.execute("SELECT * FROM model_profiles WHERE id = ?", (profile_id,)).fetchone()
    if row is None:
        raise ValueError("模型配置不存在")
    return {"id": row["id"], "name": row["name"], "config": json.loads(row["config_json"])}


def public_profile(profile):
    config = {key: value for key, value in profile["config"].items() if key != "api_key"}
    return {"id": profile["id"], "name": profile["name"], **config,
            "has_api_key": bool(profile["config"].get("api_key"))}


def get_settings(app):
    with closing(connect(app)) as connection:
        active_id = connection.execute("SELECT active_id FROM model_settings WHERE id = 1").fetchone()[0]
        rows = connection.execute("SELECT * FROM model_profiles ORDER BY name, id").fetchall()
    profiles = [public_profile(load_profile(app, "env"))]
    profiles.extend(public_profile({"id": row["id"], "name": row["name"],
                                    "config": json.loads(row["config_json"])}) for row in rows)
    return {"active_id": active_id, "profiles": profiles}


def validate_config(app, payload):
    if not isinstance(payload, dict):
        raise ValueError("模型配置必须是 JSON 对象")
    if payload.get("profile_id") is not None and not isinstance(payload["profile_id"], str):
        raise ValueError("模型配置 ID 无效")
    previous = None
    if payload.get("profile_id"):
        previous = load_profile(app, str(payload["profile_id"]))["config"]
    result = {}
    for field in ("base_url", "model", "reasoning_effort"):
        value = payload.get(field, "")
        if not isinstance(value, str) or len(value) > 2000:
            raise ValueError(f"{field} 格式无效")
        result[field] = value.strip()
    parsed = urlsplit(result["base_url"])
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("API 地址必须是完整的 HTTP/HTTPS 基础地址，不含账号、查询参数或片段")
    result["base_url"] = result["base_url"].rstrip("/")
    if result["base_url"].endswith("/chat/completions"):
        raise ValueError("请填写 API 基础地址，不包含 /chat/completions")
    if not result["model"] or any(char.isspace() for char in result["model"]):
        raise ValueError("请填写有效的模型 ID")
    for field, low, high in (("timeout", 10, 600), ("max_output_tokens", 512, 131072)):
        raw = payload.get(field)
        if isinstance(raw, bool) or not isinstance(raw, int) or not low <= raw <= high:
            raise ValueError(f"{field} 必须是 {low}～{high} 之间的整数")
        result[field] = raw
    for field in ("json_mode", "send_temperature"):
        value = payload.get(field, DEFAULTS[field])
        if not isinstance(value, bool):
            raise ValueError(f"{field} 必须是布尔值")
        result[field] = value
    parameter = payload.get("token_parameter", "max_completion_tokens")
    if parameter not in ("max_completion_tokens", "max_tokens"):
        raise ValueError("输出 token 参数无效")
    result["token_parameter"] = parameter
    key = payload.get("api_key", "")
    if not isinstance(key, str) or len(key) > 4096 or "\n" in key or "\r" in key:
        raise ValueError("API Key 格式无效")
    # Reusing an existing secret is allowed only for the same saved endpoint.
    if not key.strip() and previous and result["base_url"] == previous["base_url"].rstrip("/"):
        key = previous.get("api_key", "")
    if not key.strip():
        raise ValueError("请填写 API Key；修改 API 地址后需要重新填写密钥")
    result["api_key"] = key.strip()
    return result


def save_profile(app, payload):
    config = validate_config(app, payload)
    name = payload.get("name", "")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError("配置名称不能为空，且不能超过 100 个字符")
    profile_id = payload.get("profile_id")
    if profile_id in (None, "", "env"):
        profile_id = uuid.uuid4().hex
    with closing(connect(app)) as connection, connection:
        connection.execute(
            """INSERT INTO model_profiles(id, name, config_json, updated_at) VALUES(?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,
               config_json=excluded.config_json, updated_at=excluded.updated_at""",
            (profile_id, name.strip(), json.dumps(config), now()),
        )
    return public_profile({"id": profile_id, "name": name.strip(), "config": config})


def activate_profile(app, profile_id):
    profile = load_profile(app, profile_id)
    if not profile["config"].get("api_key"):
        raise ValueError("该模型尚未配置 API Key")
    with closing(connect(app)) as connection, connection:
        connection.execute("UPDATE model_settings SET active_id = ? WHERE id = 1", (profile_id,))


def model_context(app, override=None):
    if override is None and getattr(app, "_model_snapshot", False):
        return app
    if override is None:
        with closing(connect(app)) as connection:
            profile_id = connection.execute("SELECT active_id FROM model_settings WHERE id = 1").fetchone()[0]
        config = load_profile(app, profile_id)["config"]
    else:
        config = override
    runtime = dict(app.config)
    runtime.update({key: config[field] for field, key in FIELDS.items()})
    runtime["MODEL_CONFIG_SNAPSHOT"] = config
    if config != environment_config(app):
        digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        runtime["MODEL_CACHE_KEY"] = config["model"] + ":" + digest
    view = SimpleNamespace(config=runtime, logger=app.logger,
                           extensions=dict(app.extensions), _model_snapshot=True)
    # Preserve the original client for the unchanged environment configuration.
    if config != environment_config(app):
        view.extensions["glm_client"] = OpenAICompatibleChatClient(
            view, client_factory=app.extensions["glm_client"]._client_factory
        )
    return view


def get_connection_test(app, test_id):
    with closing(connect(app)) as connection:
        row = connection.execute("SELECT * FROM model_connection_tests WHERE id = ?", (test_id,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["result"] = json.loads(result.pop("result_json"))
    return result


def start_connection_test(app, payload):
    config = validate_config(app, payload)
    slots = app.extensions["model_test_slots"]
    if not slots.acquire(blocking=False):
        raise RuntimeError("已有两个连接测试运行中，请稍后重试")
    test_id = uuid.uuid4().hex
    try:
        with closing(connect(app)) as connection, connection:
            connection.execute("INSERT INTO model_connection_tests(id,status,started_at) VALUES(?,'running',?)", (test_id, now()))
    except Exception:
        slots.release()
        raise

    def run():
        started = time.monotonic()
        status, message, result = "failed", "", {}
        try:
            view = model_context(app, override=config)
            view.config["GLM_LOG_PAYLOADS"] = False
            # Always create the client with the test snapshot, even for environment defaults.
            client = OpenAICompatibleChatClient(view, app.extensions["glm_client"]._client_factory)
            completion = client.create_issue_analysis(
                issue_number=f"connection-test:{test_id}", comments_count=0,
                messages=[{"role": "user", "content": '仅输出 JSON 对象：{"ok":true}，不要附加其他文字。'}],
            )
            if parse_ai_json(completion.content).get("ok") is not True:
                raise ValueError("模型已返回内容，但未通过 JSON 指令验证")
            status, message = "succeeded", "模型可用：流式请求与 JSON 返回验证通过"
            result = {"model": config["model"], "response": str(completion.content)[:500], "usage": completion.usage}
        except Exception as error:
            # Upstream errors can echo credentials. Never expose them in test results.
            message = str(error).replace(config["api_key"], "[REDACTED]")[:2000]
        finally:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            try:
                with closing(connect(app)) as connection, connection:
                    connection.execute(
                        "UPDATE model_connection_tests SET status=?,elapsed_ms=?,message=?,result_json=?,completed_at=? WHERE id=?",
                        (status, elapsed_ms, message, json.dumps(result), now(), test_id),
                    )
                app.logger.warning("Model connection test id=%s status=%s elapsed_ms=%s", test_id, status, elapsed_ms)
            finally:
                slots.release()

    try:
        threading.Thread(target=run, name=f"model-test-{test_id[:8]}", daemon=True).start()
    except Exception:
        slots.release()
        with closing(connect(app)) as connection, connection:
            connection.execute("UPDATE model_connection_tests SET status='failed',message='无法启动测试线程',completed_at=? WHERE id=?", (now(), test_id))
        raise
    return test_id
