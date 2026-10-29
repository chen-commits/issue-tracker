import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
from openai import APIStatusError

from issue_tracker.application import create_app, get_connection, perform_issue_analysis
from issue_tracker.batch_analysis import process_next_batch_item
from issue_tracker.model_settings import model_context


class ModelSettingsTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = {
            "TESTING": True, "DB_PATH": str(Path(self.directory.name) / "test.db"),
            "APP_USERNAME": "tester", "APP_PASSWORD": "password",
            "GLM_API_KEY": "", "GLM_MODEL": "env-model", "GLM_API_BASE_URL": "https://env.example/v1",
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Basic " + base64.b64encode(b"tester:password").decode()}

    def profile_payload(self, **overrides):
        result = {
            "name": "测试服务", "base_url": "https://model.example/v1", "model": "test-model",
            "api_key": "private-test-key", "timeout": 90, "max_output_tokens": 4096,
            "reasoning_effort": "", "json_mode": False, "send_temperature": False,
            "token_parameter": "max_tokens",
        }
        result.update(overrides)
        return result

    def save(self, **overrides):
        response = self.client.put("/api/model-settings/profiles", headers=self.headers, json=self.profile_payload(**overrides))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertNotIn("private-test-key", response.get_data(as_text=True))
        return response.get_json()["profile"]["id"]

    def activate(self, profile_id):
        response = self.client.post("/api/model-settings/activate", headers=self.headers, json={"profile_id": profile_id})
        self.assertEqual(response.status_code, 200)

    def seed_issue(self):
        with get_connection(self.app) as connection:
            connection.execute("""INSERT INTO issues(number,repository,title,body,html_url,upstream_state,
                github_created_at,github_updated_at,first_synced_at,last_synced_at)
                VALUES(7,'example/repo','新增模型支持','希望支持新模型','https://example/issues/7','open',
                       '2026-10-29T00:00:00Z','2026-10-29T00:00:00Z','now','now')""")

    def sdk_client(self, content):
        client = mock.MagicMock()
        client.chat.completions.create.side_effect = lambda **kwargs: iter([
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason="stop")], usage=None),
        ])
        return client

    def synchronous_thread(self):
        return mock.patch("issue_tracker.model_settings.threading.Thread", side_effect=lambda **kwargs: SimpleNamespace(start=kwargs["target"]))

    def test_settings_are_authenticated_and_never_echo_credentials(self):
        self.assertEqual(self.client.get("/api/model-settings").status_code, 401)
        self.app.config["GLM_API_KEY"] = "environment-secret"
        profile_id = self.save()
        response = self.client.get("/api/model-settings", headers=self.headers)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        serialized = response.get_data(as_text=True)
        self.assertNotIn("environment-secret", serialized)
        self.assertNotIn("private-test-key", serialized)
        profiles = response.get_json()["profiles"]
        self.assertTrue(next(p for p in profiles if p["id"] == profile_id)["has_api_key"])
        self.assertTrue(all("api_key" not in p for p in profiles))

    def test_save_activate_restart_and_environment_fallback(self):
        profile_id = self.save()
        self.assertEqual(self.client.get("/api/model-settings", headers=self.headers).get_json()["active_id"], "env")
        self.activate(profile_id)
        restarted = create_app(self.config)
        self.assertEqual(model_context(restarted).config["GLM_MODEL"], "test-model")
        self.assertEqual(model_context(restarted).config["GLM_API_KEY"], "private-test-key")
        self.app.config["GLM_API_KEY"] = "env-secret"
        self.activate("env")
        self.assertEqual(model_context(self.app).config["GLM_MODEL"], "env-model")

    def test_blank_key_preserves_only_same_endpoint_secret(self):
        profile_id = self.save()
        self.save(profile_id=profile_id, api_key="", model="another-model")
        self.activate(profile_id)
        self.assertEqual(model_context(self.app).config["GLM_API_KEY"], "private-test-key")
        response = self.client.put("/api/model-settings/profiles", headers=self.headers, json=self.profile_payload(
            profile_id=profile_id, api_key="", base_url="https://different.example/v1",
        ))
        self.assertEqual(response.status_code, 400)
        self.assertIn("重新填写", response.get_json()["error"])

    def test_invalid_profile_parameters_are_rejected(self):
        for override in [
            {"base_url": "file:///etc/passwd"}, {"base_url": "https://user:pass@example/v1"},
            {"base_url": "https://example/v1/chat/completions"}, {"timeout": 0}, {"timeout": True},
            {"max_output_tokens": 5}, {"model": ""}, {"json_mode": "false"},
            {"api_key": "bad\nkey"}, {"token_parameter": "invalid"}, {"profile_id": "missing"},
            {"profile_id": []},
        ]:
            with self.subTest(override=override):
                response = self.client.put("/api/model-settings/profiles", headers=self.headers, json=self.profile_payload(**override))
                self.assertEqual(response.status_code, 400)

    def test_selected_profile_drives_real_analysis_request_parameters(self):
        self.seed_issue()
        self.activate(self.save())
        sdk = self.sdk_client('{"summary_zh":"完整分析"}')
        with mock.patch("issue_tracker.application.ensure_issue_triage", return_value={"filtered": False}), mock.patch(
            "issue_tracker.application.fetch_issue_comments", return_value=[]
        ), mock.patch.object(self.app.extensions["glm_client"], "_client_factory", return_value=sdk) as factory:
            response = self.client.post("/api/issues/7/ai-analysis", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["model"], "test-model")
        self.assertEqual(factory.call_args.kwargs["base_url"], "https://model.example/v1/")
        self.assertEqual(factory.call_args.kwargs["timeout"], 90)
        arguments = sdk.chat.completions.create.call_args.kwargs
        self.assertEqual(arguments["max_tokens"], 4096)
        self.assertNotIn("max_completion_tokens", arguments)
        for name in ("reasoning_effort", "temperature", "response_format"):
            self.assertNotIn(name, arguments)

    def test_switching_same_model_to_another_endpoint_invalidates_triage_cache(self):
        self.seed_issue()
        first = self.save()
        second = self.save(base_url="https://another.example/v1", name="另一服务")
        sdk = self.sdk_client(json.dumps({
            "category": "feature_request", "confidence": 0.99, "reason": "请求新模型",
            "evidence": [{"source": "正文", "quote": "希望支持新模型"}],
            "has_failure_report": False, "needs_review": False,
        }))
        with mock.patch("issue_tracker.application.fetch_issue_comments", return_value=[]), mock.patch.object(
            self.app.extensions["glm_client"], "_client_factory", return_value=sdk,
        ):
            self.activate(first)
            self.assertTrue(self.client.post("/api/issues/7/ai-analysis", headers=self.headers).get_json()["filtered"])
            self.activate(second)
            self.assertTrue(self.client.post("/api/issues/7/ai-analysis", headers=self.headers).get_json()["filtered"])
        self.assertEqual(sdk.chat.completions.create.call_count, 2)

    def test_queued_batch_keeps_original_model_after_switch_and_never_exposes_secret(self):
        self.seed_issue()
        first = self.save(model="first-model")
        second = self.save(model="second-model", name="第二个模型")
        self.activate(first)
        response = self.client.post("/api/ai-batches", headers=self.headers, json={"scope": "selected", "issue_numbers": [7]})
        self.assertEqual(response.status_code, 202)
        self.assertNotIn("private-test-key", response.get_data(as_text=True))
        self.assertNotIn("model_config_json", response.get_json())
        self.activate(second)
        analyzer = mock.Mock(return_value={"task_type": "filtered", "filtered": True})
        process_next_batch_item(self.app, analyzer, lambda: "2026-10-29T00:00:00Z")
        self.assertEqual(analyzer.call_args.args[0].config["GLM_MODEL"], "first-model")

    def test_connection_test_is_async_uses_draft_and_does_not_activate_it(self):
        sdk = self.sdk_client('{"ok":true}')
        with self.synchronous_thread(), mock.patch.object(self.app.extensions["glm_client"], "_client_factory", return_value=sdk):
            response = self.client.post("/api/model-settings/tests", headers=self.headers, json=self.profile_payload())
        self.assertEqual(response.status_code, 202)
        result = self.client.get(f"/api/model-settings/tests/{response.get_json()['id']}", headers=self.headers).get_json()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"]["response"], '{"ok":true}')
        self.assertNotIn("private-test-key", json.dumps(result))
        settings = self.client.get("/api/model-settings", headers=self.headers).get_json()
        self.assertEqual(settings["active_id"], "env")
        self.assertEqual(len(settings["profiles"]), 1)

    def test_connection_test_reports_504_and_redacts_echoed_key(self):
        sdk = mock.MagicMock()
        sdk.chat.completions.create.side_effect = APIStatusError(
            "upstream timeout", response=httpx.Response(504, request=httpx.Request("POST", "https://model.example/v1/chat/completions"),
                json={"error": {"message": "gateway timeout private-test-key"}}), body={},
        )
        with self.synchronous_thread(), mock.patch.object(self.app.extensions["glm_client"], "_client_factory", return_value=sdk):
            response = self.client.post("/api/model-settings/tests", headers=self.headers, json=self.profile_payload())
        result = self.client.get(f"/api/model-settings/tests/{response.get_json()['id']}", headers=self.headers).get_json()
        self.assertEqual(result["status"], "failed")
        self.assertIn("504", result["message"])
        self.assertIn("[REDACTED]", result["message"])
        self.assertNotIn("private-test-key", json.dumps(result))

    def test_non_json_model_output_fails_verification(self):
        sdk = self.sdk_client("hello")
        with self.synchronous_thread(), mock.patch.object(self.app.extensions["glm_client"], "_client_factory", return_value=sdk):
            response = self.client.post("/api/model-settings/tests", headers=self.headers, json=self.profile_payload())
        result = self.client.get(f"/api/model-settings/tests/{response.get_json()['id']}", headers=self.headers).get_json()
        self.assertEqual(result["status"], "failed")
        self.assertIn("JSON", result["message"])

    def test_connection_tests_limit_concurrency_and_restart_marks_interrupted_tests(self):
        # Keep threads unstarted to represent two outstanding network requests.
        with mock.patch("issue_tracker.model_settings.threading.Thread"):
            first = self.client.post("/api/model-settings/tests", headers=self.headers, json=self.profile_payload())
            second = self.client.post("/api/model-settings/tests", headers=self.headers, json=self.profile_payload())
            third = self.client.post("/api/model-settings/tests", headers=self.headers, json=self.profile_payload())
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(third.status_code, 429)
        restarted = create_app(self.config).test_client()
        result = restarted.get(f"/api/model-settings/tests/{first.get_json()['id']}", headers=self.headers).get_json()
        self.assertEqual(result["status"], "failed")
        self.assertIn("重启", result["message"])

    def test_legacy_batch_uses_environment_connection_after_profile_switch(self):
        self.seed_issue()
        self.app.config["GLM_API_KEY"] = "env-secret"
        job = self.client.post("/api/ai-batches", headers=self.headers, json={
            "scope": "selected", "issue_numbers": [7],
        }).get_json()
        with get_connection(self.app) as connection:
            connection.execute("UPDATE ai_batch_jobs SET model_config_json = '{}' WHERE id = ?", (job["id"],))
        self.activate(self.save())
        analyzer = mock.Mock(return_value={"task_type": "filtered", "filtered": True})
        process_next_batch_item(self.app, analyzer, lambda: "2026-10-29T00:00:00Z")
        self.assertEqual(analyzer.call_args.args[0].config["GLM_API_BASE_URL"], "https://env.example/v1")
        self.assertEqual(analyzer.call_args.args[0].config["GLM_MODEL"], "env-model")

    def test_page_exposes_model_tab_without_embedding_any_secret(self):
        self.save()
        response = self.client.get("/", headers=self.headers)
        self.assertIn('id="modelsTab"', response.get_data(as_text=True))
        self.assertIn('id="testModelConnection"', response.get_data(as_text=True))
        self.assertNotIn("private-test-key", response.get_data(as_text=True))
        response.close()
