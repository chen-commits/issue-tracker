import base64
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

import requests
from openpyxl import load_workbook

from issue_tracker.application import (
    create_app,
    ensure_issue_columns,
    get_connection,
    github_request,
    incremental_sync_since,
    load_env_file,
    next_link_url,
    perform_sync,
)
from issue_tracker.batch_analysis import process_next_batch_item
from issue_tracker.ai_analysis import AI_PROMPT_VERSION, build_issue_analysis_messages
from issue_tracker.priority import explicit_version_key


def chat_stream(*chunks):
    stream = mock.MagicMock()
    stream.__iter__.return_value = iter(chunks)
    return stream


def chat_chunk(content=None, *, finish_reason=None, usage=None, request_id=""):
    choices = []
    if content is not None or finish_reason is not None:
        choices.append(
            SimpleNamespace(
                delta=SimpleNamespace(content=content, reasoning_content=None),
                finish_reason=finish_reason,
            )
        )
    return SimpleNamespace(
        choices=choices,
        usage=usage,
        _request_id=request_id,
    )


class IssueTrackerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(Path(self.temp_dir.name) / "test.db"),
                "APP_USERNAME": "tester",
                "APP_PASSWORD": "secret",
                "GITHUB_SSL_VERIFY": True,
                "GLM_API_KEY": "",
            }
        )
        self.client = self.app.test_client()
        token = base64.b64encode(b"tester:secret").decode()
        self.headers = {"Authorization": f"Basic {token}"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        old = now - timedelta(days=60)
        with get_connection(self.app) as connection:
            connection.executemany(
                """
                INSERT INTO issues (
                    number, repository, title, body, html_url, upstream_state,
                    author, labels_json, github_created_at, github_updated_at,
                    comment_count, first_synced_at, last_synced_at,
                    identification_result, value_level, missed_test_reason,
                    supplemental_test, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        101,
                        "vllm-project/vllm-ascend",
                        "Recent failure",
                        "reproduction",
                        "https://github.com/example/issues/101",
                        "open",
                        "alice",
                        '["bug"]',
                        now.isoformat(),
                        now.isoformat(),
                        1,
                        now.isoformat(),
                        now.isoformat(),
                        "确认问题",
                        "高",
                        "未覆盖并发组合",
                        "增加并发回归测试",
                        "优先分析",
                    ),
                    (
                        2,
                        "vllm-project/vllm-ascend",
                        "Old closed issue",
                        "old body",
                        "https://github.com/example/issues/2",
                        "closed",
                        "bob",
                        "[]",
                        old.isoformat(),
                        old.isoformat(),
                        0,
                        now.isoformat(),
                        now.isoformat(),
                        "",
                        "",
                        "",
                        "",
                        "",
                    ),
                ],
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_authentication_is_required(self):
        response = self.client.get("/api/issues")
        self.assertEqual(response.status_code, 401)

    def test_index_is_served_from_package_static_directory(self):
        response = self.client.get("/", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        response.close()
        self.assertIn("vLLM Ascend Issue", html)
        self.assertIn("列设置", html)
        self.assertIn("问题分析", html)
        self.assertIn("漏测原因", html)
        self.assertIn("补充测试", html)
        self.assertIn('class="editor-workspace"', html)
        self.assertIn('id="aiSuggestionPlaceholder"', html)
        self.assertIn("全部采纳", html)
        self.assertNotIn('class="filter-band"', html)
        self.assertEqual(html.count('id="clearFilters"'), 1)

    def test_recent_identified_filter(self):
        response = self.client.get(
            "/api/issues?created=last_month&identified=确认问题",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["number"], 101)

    def test_created_date_range_includes_the_complete_end_date(self):
        issue_date = datetime.fromisoformat(
            self.client.get("/api/issues/101", headers=self.headers)
            .get_json()["github_created_at"]
        ).date().isoformat()
        response = self.client.get(
            f"/api/issues?created_from={issue_date}&created_to={issue_date}",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["number"] for item in response.get_json()["items"]], [101]
        )

    def test_created_date_range_rejects_an_inverted_range(self):
        response = self.client.get(
            "/api/issues?created_from=2026-08-05&created_to=2026-08-04",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("开始日期", response.get_json()["error"])

    def test_default_order_is_created_time_descending(self):
        response = self.client.get("/api/issues", headers=self.headers)
        numbers = [item["number"] for item in response.get_json()["items"]]
        self.assertEqual(numbers, [101, 2])

    def test_column_text_filters_match_full_dataset(self):
        response = self.client.get(
            "/api/issues?missed=并发&supplemental=回归&notes=优先",
            headers=self.headers,
        )
        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["number"], 101)

    def test_excel_export_uses_filters_and_visible_columns(self):
        response = self.client.get(
            "/api/issues/export?missed=并发&columns=issue,missed,notes",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.mimetype,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        workbook = load_workbook(BytesIO(response.data), read_only=True)
        rows = list(workbook.active.iter_rows(values_only=True))
        self.assertEqual(rows[0], ("Issue", "漏测原因", "备注"))
        self.assertEqual(len(rows), 2)
        self.assertIn("#101", rows[1][0])

    def test_excel_export_can_contain_only_issue_column(self):
        response = self.client.get(
            "/api/issues/export?state=closed&columns=issue",
            headers=self.headers,
        )
        workbook = load_workbook(BytesIO(response.data), read_only=True)
        rows = list(workbook.active.iter_rows(values_only=True))
        self.assertEqual(rows[0], ("Issue",))
        self.assertEqual(len(rows), 2)
        self.assertIn("#2", rows[1][0])

    def test_excel_export_includes_version_and_ai_analysis_columns(self):
        self.client.patch(
            "/api/issues/101",
            headers=self.headers,
            json={
                "affected_version": "v0.11.0rc1",
                "version_support_status": "下个版本支持",
                "ai_analysis": "## 结论\n\n需要补充回归测试",
            },
        )
        response = self.client.get(
            "/api/issues/export?columns=issue,version,version_support,ai_analysis",
            headers=self.headers,
        )
        workbook = load_workbook(BytesIO(response.data), read_only=True)
        rows = list(workbook.active.iter_rows(values_only=True))
        self.assertEqual(
            rows[0], ("Issue", "问题版本", "版本支持情况", "AI分析结论")
        )
        self.assertEqual(rows[1][1:], (
            "v0.11.0rc1",
            "下个版本支持",
            "## 结论\n\n需要补充回归测试",
        ))

    def test_manual_analysis_can_be_updated(self):
        response = self.client.patch(
            "/api/issues/101",
            headers=self.headers,
            json={
                "summary_zh": "可复现的启动失败",
                "missed_test_reason": "未覆盖对应配置组合",
                "is_closed_loop": "是",
                "affected_version": "v0.11.0rc1",
                "version_support_status": "下个版本支持",
                "ai_analysis": "## 结论\n\n- 可稳定复现",
                "title": "must not be changed",
            },
        )
        self.assertEqual(response.status_code, 200)
        detail = self.client.get("/api/issues/101", headers=self.headers).get_json()
        self.assertEqual(detail["summary_zh"], "可复现的启动失败")
        self.assertEqual(detail["is_closed_loop"], "是")
        self.assertEqual(detail["affected_version"], "v0.11.0rc1")
        self.assertEqual(detail["version_support_status"], "下个版本支持")
        self.assertIn("<h2>结论</h2>", detail["ai_analysis_html"])
        self.assertEqual(detail["title"], "Recent failure")

        filtered = self.client.get(
            "/api/issues?closed_loop=是", headers=self.headers
        ).get_json()
        self.assertEqual(filtered["total"], 1)

        filtered = self.client.get(
            "/api/issues?version=v0.11&version_support=下个版本支持&ai_analysis=稳定复现",
            headers=self.headers,
        ).get_json()
        self.assertEqual(filtered["total"], 1)

    def test_ai_analysis_requires_server_side_api_key(self):
        response = self.client.post(
            "/api/issues/101/ai-analysis", headers=self.headers
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("GLM_API_KEY", response.get_json()["error"])

    def test_ai_analysis_returns_preview_without_updating_issue(self):
        self.app.config["GLM_API_KEY"] = "test-secret-key"
        content = json.dumps(
            {
                "summary_zh": "启动阶段可以稳定复现失败",
                "value_level": "高",
                "source_type": "用户暴露",
                "conclusion_status": "待确认",
                "identification_result": "确认问题",
                "missed_test_reason": "缺少对应配置组合",
                "supplemental_test": "增加启动回归用例",
                "affected_version": "v0.11.0",
                "version_support_status": "待确认",
                "ai_analysis": "## 判断依据\n\n正文包含稳定报错。",
                "confidence": 0.84,
            },
            ensure_ascii=False,
        )
        stream = chat_stream(
            chat_chunk(content[:40], request_id="upstream-test-request"),
            chat_chunk(content[40:]),
            chat_chunk(finish_reason="stop"),
            chat_chunk(usage={"total_tokens": 321}),
        )
        sdk_client = mock.MagicMock()
        sdk_client.chat.completions.create.return_value = stream
        self.app.config["GLM_LOG_PAYLOADS"] = True

        with self.assertLogs(self.app.logger, level="WARNING") as logs, mock.patch(
            "issue_tracker.application.fetch_issue_comments",
            return_value=[
                {
                    "user": {"login": "reviewer"},
                    "created_at": "2026-08-04T12:00:00Z",
                    "body": "同样可以复现",
                }
            ],
        ), mock.patch.object(
            self.app.extensions["glm_client"],
            "_client_factory",
            return_value=sdk_client,
        ) as client_factory:
            response = self.client.post(
                "/api/issues/101/ai-analysis", headers=self.headers
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["suggestion"]["summary_zh"], "启动阶段可以稳定复现失败")
        self.assertEqual(payload["suggestion"]["confidence"], 0.84)
        self.assertNotIn("missed_test_reason", payload["suggestion"])
        self.assertIn("<h2>判断依据</h2>", payload["ai_analysis_html"])
        self.assertEqual(payload["comments_included"], 1)
        self.assertEqual(payload["usage"]["total_tokens"], 321)
        self.assertEqual(
            client_factory.call_args.kwargs["api_key"], "test-secret-key"
        )
        self.assertEqual(
            client_factory.call_args.kwargs["base_url"],
            "https://open.bigmodel.cn/api/paas/v4/",
        )
        self.assertEqual(
            sdk_client.chat.completions.create.call_args.kwargs["response_format"],
            {"type": "json_object"},
        )
        self.assertEqual(
            sdk_client.chat.completions.create.call_args.kwargs["reasoning_effort"],
            "high",
        )
        self.assertEqual(
            sdk_client.chat.completions.create.call_args.kwargs[
                "max_completion_tokens"
            ],
            16384,
        )
        self.assertTrue(sdk_client.chat.completions.create.call_args.kwargs["stream"])
        stream.close.assert_called_once_with()
        sdk_client.close.assert_called_once_with()
        logged = "\n".join(logs.output)
        self.assertIn("GLM request payload", logged)
        self.assertIn("GLM response payload", logged)
        self.assertIn("upstream-test-request", logged)
        self.assertNotIn("test-secret-key", logged)

        detail = self.client.get("/api/issues/101", headers=self.headers).get_json()
        self.assertEqual(detail["summary_zh"], "")
        self.assertEqual(detail["ai_analysis"], "")

    def test_ai_analysis_discards_invalid_enum_values(self):
        self.app.config["GLM_API_KEY"] = "test-secret-key"
        content = json.dumps({
                "summary_zh": "需要人工判断",
                "value_level": "最高",
                "ai_analysis": "## 判断依据\n\n信息不足。",
                "confidence": 8,
            }, ensure_ascii=False)
        sdk_client = mock.MagicMock()
        sdk_client.chat.completions.create.return_value = chat_stream(
            chat_chunk(content), chat_chunk(finish_reason="stop")
        )

        with mock.patch(
            "issue_tracker.application.fetch_issue_comments", return_value=[]
        ), mock.patch.object(
            self.app.extensions["glm_client"],
            "_client_factory",
            return_value=sdk_client,
        ):
            response = self.client.post(
                "/api/issues/101/ai-analysis", headers=self.headers
            )

        suggestion = response.get_json()["suggestion"]
        self.assertEqual(suggestion["value_level"], "")
        self.assertEqual(suggestion["confidence"], 1)

    def test_ai_analysis_reports_empty_stream(self):
        self.app.config.update(
            GLM_API_KEY="test-secret-key",
            GLM_LOG_PAYLOADS=True,
        )
        sdk_client = mock.MagicMock()
        sdk_client.chat.completions.create.return_value = chat_stream(
            chat_chunk(finish_reason="stop")
        )

        with self.assertLogs(self.app.logger, level="WARNING") as logs, mock.patch(
            "issue_tracker.application.fetch_issue_comments", return_value=[]
        ), mock.patch.object(
            self.app.extensions["glm_client"],
            "_client_factory",
            return_value=sdk_client,
        ):
            response = self.client.post(
                "/api/issues/101/ai-analysis", headers=self.headers
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("流式响应中没有分析结果", response.get_json()["error"])
        logged = "\n".join(logs.output)
        self.assertIn("GLM stream completed", logged)
        self.assertIn("content_length=0", logged)
        self.assertNotIn("test-secret-key", logged)

    def test_ai_analysis_reassembles_json_split_across_stream_chunks(self):
        self.app.config["GLM_API_KEY"] = "test-secret-key"
        content = json.dumps(
            {
                "summary_zh": "流式分析可以拼接",
                "value_level": "低",
                "identification_result": "待分析",
                "ai_analysis": "## 判断依据\n\n需要人工确认。",
                "confidence": 0.75,
            },
            ensure_ascii=False,
        )
        sdk_client = mock.MagicMock()
        sdk_client.chat.completions.create.return_value = chat_stream(
            chat_chunk(content[:17]),
            chat_chunk(content[17:61]),
            chat_chunk(content[61:]),
            chat_chunk(finish_reason="stop"),
        )

        with self.assertLogs(self.app.logger, level="WARNING") as logs, mock.patch(
            "issue_tracker.application.fetch_issue_comments", return_value=[]
        ), mock.patch.object(
            self.app.extensions["glm_client"],
            "_client_factory",
            return_value=sdk_client,
        ):
            response = self.client.post(
                "/api/issues/101/ai-analysis", headers=self.headers
            )

        self.assertEqual(response.status_code, 200)
        suggestion = response.get_json()["suggestion"]
        self.assertEqual(suggestion["summary_zh"], "流式分析可以拼接")
        self.assertEqual(suggestion["confidence"], 0.75)
        self.assertIn("chunks=4", "\n".join(logs.output))

    def test_ai_analysis_reports_truncated_stream(self):
        self.app.config["GLM_API_KEY"] = "test-secret-key"
        sdk_client = mock.MagicMock()
        sdk_client.chat.completions.create.return_value = chat_stream(
            chat_chunk('{"summary_zh":"输出到一半","supplemental_test":"未完成'),
            chat_chunk(finish_reason="length"),
        )

        with mock.patch(
            "issue_tracker.application.fetch_issue_comments", return_value=[]
        ), mock.patch.object(
            self.app.extensions["glm_client"],
            "_client_factory",
            return_value=sdk_client,
        ):
            response = self.client.post(
                "/api/issues/101/ai-analysis", headers=self.headers
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("finish_reason=length", response.get_json()["error"])
        self.assertNotIn("无效 JSON", response.get_json()["error"])

    def test_selected_batch_analysis_persists_suggestion_without_overwriting_issue(self):
        self.app.config["GLM_API_KEY"] = "test-secret-key"
        response = self.client.post(
            "/api/ai-batches",
            headers=self.headers,
            json={
                "scope": "selected",
                "issue_numbers": [101],
                "skip_existing": True,
            },
        )

        self.assertEqual(response.status_code, 202)
        job = response.get_json()
        self.assertEqual(job["scope"], "selected")
        self.assertEqual(job["total_count"], 1)
        self.assertEqual(job["status"], "queued")

        def analyzer(app, number):
            self.assertEqual(number, 101)
            return {
                "suggestion": {
                    "summary_zh": "AI 批量建议",
                    "value_level": "高",
                    "source_type": "用户暴露",
                    "conclusion_status": "待确认",
                    "identification_result": "确认问题",
                    "missed_test_reason": "缺少组合覆盖",
                    "supplemental_test": "增加组合测试",
                    "affected_version": "v1.0",
                    "version_support_status": "待确认",
                    "ai_analysis": "## 判断依据\n\n批量分析内容",
                    "confidence": 0.9,
                },
                "ai_analysis_html": "<h2>判断依据</h2><p>批量分析内容</p>",
                "model": app.config["GLM_MODEL"],
                "prompt_version": "issue-analysis-v1",
                "comments_included": 1,
                "usage": {"total_tokens": 100},
                "warnings": [],
            }

        processed = process_next_batch_item(
            self.app, analyzer, lambda: "2026-09-21T10:00:00Z"
        )
        self.assertTrue(processed)

        status = self.client.get(
            f"/api/ai-batches/{job['id']}", headers=self.headers
        ).get_json()
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["success_count"], 1)

        detail = self.client.get("/api/issues/101", headers=self.headers).get_json()
        self.assertEqual(detail["summary_zh"], "")
        self.assertEqual(detail["ai_analysis"], "")
        self.assertEqual(detail["ai_suggestion"]["suggestion"]["summary_zh"], "AI 批量建议")
        self.assertEqual(detail["ai_suggestion"]["usage"]["total_tokens"], 100)

        run_id = detail["ai_suggestion"]["run_id"]
        saved = self.client.patch(
            "/api/issues/101",
            headers=self.headers,
            json={"summary_zh": "人工确认后的内容", "_ai_run_id": run_id},
        )
        self.assertEqual(saved.status_code, 200)
        with get_connection(self.app) as connection:
            run = connection.execute(
                "SELECT applied_at FROM ai_analysis_runs WHERE id = ?", (run_id,)
            ).fetchone()
        self.assertTrue(run["applied_at"])

    def test_filtered_batch_analysis_freezes_all_matching_issues(self):
        self.app.config["GLM_API_KEY"] = "test-secret-key"
        response = self.client.post(
            "/api/ai-batches",
            headers=self.headers,
            json={
                "scope": "filtered",
                "filters": {"state": "closed"},
                "skip_existing": False,
            },
        )

        self.assertEqual(response.status_code, 202)
        job = response.get_json()
        self.assertEqual(job["total_count"], 1)
        self.assertEqual(job["filters"], {"state": "closed"})
        self.assertEqual(job["items"][0]["issue_number"], 2)

    def test_unchanged_successful_batch_result_is_reused(self):
        self.app.config["GLM_API_KEY"] = "test-secret-key"
        first = self.client.post(
            "/api/ai-batches",
            headers=self.headers,
            json={"scope": "selected", "issue_numbers": [2]},
        ).get_json()

        def analyzer(app, number):
            return {
                "suggestion": {
                    "summary_zh": "历史问题建议",
                    "ai_analysis": "## 判断依据\n\n信息充分。",
                    "confidence": 0.8,
                },
                "ai_analysis_html": "<h2>判断依据</h2>",
                "model": app.config["GLM_MODEL"],
                "prompt_version": "issue-analysis-v1",
                "comments_included": 0,
                "usage": {},
                "warnings": [],
            }

        process_next_batch_item(
            self.app, analyzer, lambda: "2026-09-21T10:00:00Z"
        )
        second = self.client.post(
            "/api/ai-batches",
            headers=self.headers,
            json={
                "scope": "selected",
                "issue_numbers": [2],
                "skip_existing": True,
            },
        ).get_json()

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["skipped_count"], 1)
        self.assertEqual(second["items"][0]["status"], "skipped")

    def test_prompt_requires_reproduction_details_without_inventing_environment(self):
        with get_connection(self.app) as connection:
            issue = dict(connection.execute("SELECT * FROM issues WHERE number = 101").fetchone())
        messages = build_issue_analysis_messages(self.app, issue, [])
        prompt = messages[0]["content"]
        self.assertIn("模型配置", prompt)
        self.assertIn("A2/A3/A5", prompt)
        self.assertIn("待确认", prompt)
        self.assertIn("不要返回 missed_test_reason", prompt)
        self.assertNotIn("missed_test_reason", messages[1]["content"])
        self.assertEqual(AI_PROMPT_VERSION, "issue-analysis-v2")

    def test_priority_view_excludes_doc_low_value_and_uncertain_reproduction(self):
        with get_connection(self.app) as connection:
            connection.execute(
                "UPDATE issues SET value_level = '高', affected_version = 'v0.11.0' WHERE number = 101"
            )
            connection.execute(
                "UPDATE issues SET value_level = '中', affected_version = 'v0.12.0' WHERE number = 2"
            )
            for number, level, source in (
                (101, "高", "用户暴露"),
                (2, "中", "用户暴露"),
            ):
                suggestion = {
                    "summary_zh": "可复现缺陷",
                    "value_level": "高" if number == 101 else "中",
                    "source_type": source,
                    "identification_result": "确认问题",
                    "reproducibility_level": level,
                    "priority_reason": "有触发条件、版本和日志",
                    "confidence": 0.8,
                }
                connection.execute(
                    """
                    INSERT INTO ai_analysis_runs (
                        issue_number, model, prompt_version, issue_fingerprint,
                        suggestion_json, created_at
                    ) VALUES (?, 'glm-test', ?, 'test', ?, '2026-09-22T00:00:00Z')
                    """,
                    (number, AI_PROMPT_VERSION, json.dumps(suggestion, ensure_ascii=False)),
                )

        response = self.client.get("/api/issues?priority=1", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["total"], 2)
        self.assertEqual([item["number"] for item in payload["items"]], [101, 2])
        self.assertEqual(payload["items"][0]["priority_rank"], 1)
        self.assertEqual(payload["items"][0]["priority_reason"], "有触发条件、版本和日志")
        self.assertNotIn("suggestion_json", payload["items"][0])

        with get_connection(self.app) as connection:
            connection.execute(
                "UPDATE issues SET labels_json = '[\"documentation\"]' WHERE number = 101"
            )
        filtered = self.client.get("/api/issues?priority=1", headers=self.headers).get_json()
        self.assertEqual([item["number"] for item in filtered["items"]], [2])

    def test_priority_version_comparison_stays_within_product_family(self):
        self.assertEqual(explicit_version_key("CANN 9.2.0"), ("cann", (9, 2, 0)))
        self.assertEqual(
            explicit_version_key("v0.12.0", "vllm-project/vllm-ascend"),
            ("vllm-ascend", (0, 12, 0)),
        )
        self.assertIsNone(explicit_version_key("未提供版本"))

    def test_priority_view_prefers_newer_explicit_version_when_quality_equal(self):
        with get_connection(self.app) as connection:
            for number, version in ((101, "v0.11.0"), (2, "v0.12.0")):
                connection.execute(
                    "UPDATE issues SET value_level = '高', affected_version = ? WHERE number = ?",
                    (version, number),
                )
                suggestion = {
                    "summary_zh": "可复现缺陷",
                    "value_level": "高",
                    "source_type": "用户暴露",
                    "identification_result": "确认问题",
                    "reproducibility_level": "高",
                    "confidence": 0.8,
                }
                connection.execute(
                    """
                    INSERT INTO ai_analysis_runs (
                        issue_number, model, prompt_version, issue_fingerprint,
                        suggestion_json, created_at
                    ) VALUES (?, 'glm-test', ?, 'test', ?, '2026-09-22T00:00:00Z')
                    """,
                    (number, AI_PROMPT_VERSION, json.dumps(suggestion, ensure_ascii=False)),
                )
        payload = self.client.get("/api/issues?priority=1", headers=self.headers).get_json()
        self.assertEqual([item["number"] for item in payload["items"]], [2, 101])

    def test_batch_items_can_be_analyzed_concurrently_without_duplicate_claims(self):
        self.app.config["GLM_API_KEY"] = "test-secret-key"
        job = self.client.post(
            "/api/ai-batches",
            headers=self.headers,
            json={
                "scope": "selected",
                "issue_numbers": [101, 2],
                "skip_existing": False,
            },
        ).get_json()
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        active = 0
        maximum_active = 0
        analyzed_numbers = []

        def analyzer(app, number):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
                analyzed_numbers.append(number)
            barrier.wait(timeout=3)
            with lock:
                active -= 1
            return {
                "suggestion": {
                    "summary_zh": f"Issue #{number} 的建议",
                    "ai_analysis": "## 判断依据\n\n并发分析。",
                    "confidence": 0.8,
                },
                "ai_analysis_html": "<h2>判断依据</h2>",
                "model": app.config["GLM_MODEL"],
                "prompt_version": "issue-analysis-v1",
                "comments_included": 0,
                "usage": {},
                "warnings": [],
            }

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: process_next_batch_item(
                        self.app,
                        analyzer,
                        lambda: "2026-09-21T10:00:00Z",
                    ),
                    range(2),
                )
            )

        self.assertEqual(results, [True, True])
        self.assertEqual(maximum_active, 2)
        self.assertEqual(set(analyzed_numbers), {101, 2})
        status = self.client.get(
            f"/api/ai-batches/{job['id']}", headers=self.headers
        ).get_json()
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["success_count"], 2)

    def test_existing_database_is_migrated_without_losing_rows(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE issues (number INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO issues(number) VALUES (7)")

        ensure_issue_columns(connection)

        row = connection.execute(
            """
            SELECT number, is_closed_loop, affected_version,
                   version_support_status, ai_analysis
            FROM issues WHERE number = 7
            """
        ).fetchone()
        self.assertEqual(row["number"], 7)
        self.assertEqual(row["is_closed_loop"], "")
        self.assertEqual(row["affected_version"], "")
        self.assertEqual(row["version_support_status"], "")
        self.assertEqual(row["ai_analysis"], "")
        connection.close()

    def test_invalid_version_support_status_is_rejected(self):
        response = self.client.patch(
            "/api/issues/101",
            headers=self.headers,
            json={"version_support_status": "随便填写"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("版本支持情况", response.get_json()["error"])

    def test_markdown_preview_is_rendered_and_sanitized(self):
        response = self.client.post(
            "/api/markdown/render",
            headers=self.headers,
            json={
                "markdown": "# 分析\n\n|场景|结果|\n|-|-|\n|并发|失败|\n\n"
                "[危险链接](javascript:alert(1))<script>alert(2)</script>"
            },
        )
        self.assertEqual(response.status_code, 200)
        rendered = response.get_json()["html"]
        self.assertIn("<h1>分析</h1>", rendered)
        self.assertIn("<table>", rendered)
        self.assertNotIn("javascript:", rendered)
        self.assertNotIn("<script", rendered)

    def test_cursor_pagination_uses_next_link(self):
        link = (
            '<https://api.github.com/repos/example/repo/issues?after=abc>; rel="next", '
            '<https://api.github.com/repos/example/repo/issues?before=xyz>; rel="prev"'
        )
        self.assertEqual(
            next_link_url(link),
            "https://api.github.com/repos/example/repo/issues?after=abc",
        )

    def test_incremental_sync_overlaps_previous_success_time(self):
        self.assertEqual(
            incremental_sync_since("2026-08-04T12:00:00Z", 5),
            "2026-08-04T11:55:00Z",
        )

    def test_full_sync_uses_stable_created_order_without_since(self):
        with get_connection(self.app) as connection:
            connection.execute(
                "UPDATE sync_state SET last_success_at = ? WHERE id = 1",
                ("2026-08-04T12:00:00Z",),
            )

        rate = {"remaining": "100", "limit": "5000"}
        with mock.patch(
            "issue_tracker.application.github_request",
            return_value=([], rate, None),
        ) as request_issues:
            self.assertTrue(perform_sync(self.app, full=True))

        request_issues.assert_called_once_with(
            self.app, url=None, since=None, sort="created"
        )

    def test_incremental_sync_uses_overlap_and_updated_order(self):
        with get_connection(self.app) as connection:
            connection.execute(
                "UPDATE sync_state SET last_success_at = ? WHERE id = 1",
                ("2026-08-04T12:00:00Z",),
            )

        rate = {"remaining": "100", "limit": "5000"}
        with mock.patch(
            "issue_tracker.application.github_request",
            return_value=([], rate, None),
        ) as request_issues:
            self.assertTrue(perform_sync(self.app))

        request_issues.assert_called_once_with(
            self.app,
            url=None,
            since="2026-08-04T11:55:00Z",
            sort="updated",
        )

    def test_manual_sync_requests_a_full_reconciliation(self):
        with mock.patch("issue_tracker.application.threading.Thread") as thread:
            response = self.client.post("/api/sync", headers=self.headers)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(thread.call_args.kwargs["kwargs"], {"full": True})
        thread.return_value.start.assert_called_once_with()

    def test_github_ssl_verification_can_be_disabled(self):
        self.app.config["GITHUB_SSL_VERIFY"] = False
        response = mock.MagicMock()
        response.status_code = 200
        response.json.return_value = []
        response.headers = {}

        with mock.patch.object(
            self.app.extensions["github_http"],
            "get",
            return_value=response,
        ) as get:
            github_request(self.app)

        self.assertFalse(get.call_args[1]["verify"])

    def test_incomplete_github_response_is_retried(self):
        response = mock.MagicMock()
        response.status_code = 200
        response.json.return_value = []
        response.headers = {}

        with mock.patch.object(
            self.app.extensions["github_http"],
            "get",
            side_effect=[
                requests.exceptions.ChunkedEncodingError("partial response"),
                response,
            ],
        ) as get, mock.patch("issue_tracker.application.time.sleep") as sleep:
            payload, _, _ = github_request(self.app)

        self.assertEqual(payload, [])
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_rate_limit_error_recommends_authenticated_token(self):
        response = mock.MagicMock()
        response.status_code = 403
        response.text = '{"message":"rate limit exceeded"}'
        response.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1234567890",
        }

        with mock.patch.object(
            self.app.extensions["github_http"],
            "get",
            return_value=response,
        ), self.assertRaisesRegex(RuntimeError, "GITHUB_TOKEN"):
            github_request(self.app)

    def test_env_file_is_loaded_without_overriding_process_environment(self):
        env_file = Path(self.temp_dir.name) / ".env"
        env_file.write_text(
            "APP_USERNAME=file-user\nGITHUB_SSL_VERIFY=false\n",
            encoding="utf-8",
        )

        with mock.patch.dict(os.environ, {"APP_USERNAME": "process-user"}, clear=True):
            load_env_file(env_file)
            self.assertEqual(os.environ["APP_USERNAME"], "process-user")
            self.assertEqual(os.environ["GITHUB_SSL_VERIFY"], "false")


if __name__ == "__main__":
    unittest.main()
