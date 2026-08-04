import base64
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from issue_tracker.application import create_app, get_connection, next_link_url


class IssueTrackerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DB_PATH": str(Path(self.temp_dir.name) / "test.db"),
                "APP_USERNAME": "tester",
                "APP_PASSWORD": "secret",
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
                    identification_result, value_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        self.assertIn("vLLM Ascend Issue", response.get_data(as_text=True))

    def test_recent_identified_filter(self):
        response = self.client.get(
            "/api/issues?created=last_month&identified=确认问题",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["number"], 101)

    def test_manual_analysis_can_be_updated(self):
        response = self.client.patch(
            "/api/issues/101",
            headers=self.headers,
            json={
                "summary_zh": "可复现的启动失败",
                "missed_test_reason": "未覆盖对应配置组合",
                "title": "must not be changed",
            },
        )
        self.assertEqual(response.status_code, 200)
        detail = self.client.get("/api/issues/101", headers=self.headers).get_json()
        self.assertEqual(detail["summary_zh"], "可复现的启动失败")
        self.assertEqual(detail["title"], "Recent failure")

    def test_cursor_pagination_uses_next_link(self):
        link = (
            '<https://api.github.com/repos/example/repo/issues?after=abc>; rel="next", '
            '<https://api.github.com/repos/example/repo/issues?before=xyz>; rel="prev"'
        )
        self.assertEqual(
            next_link_url(link),
            "https://api.github.com/repos/example/repo/issues?after=abc",
        )


if __name__ == "__main__":
    unittest.main()
