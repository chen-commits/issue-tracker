import json
import unittest
from types import SimpleNamespace

from issue_tracker.triage import (
    REPRODUCTION_CHECKS, TRIAGE_PROMPT_VERSION, build_triage_messages,
    normalize_triage, triage_status,
)


class ReproductionTriageTestCase(unittest.TestCase):
    def setUp(self):
        self.details = {
            "execution": "vllm serve /models/example --tensor-parallel-size 8",
            "environment": "A2，8卡，example 模型，BF16，TP=8",
            "versions": "vllm-ascend 0.11.0，vllm 0.11.0，CANN 8.3，torch_npu 2.7.1",
            "trigger": 'curl localhost:8000/v1/completions -d \'{"model":"example","prompt":"hello"}\'',
            "oracle": "实际 HTTP 500，日志 ValueError: invalid shape；预期 HTTP 200 并返回生成文本",
        }
        self.context = {"body": "\n".join(self.details.values()), "comments": []}

    def payload(self):
        return {
            "category": "bug_candidate", "confidence": 0.99,
            "has_failure_report": True, "needs_review": False,
            "reason": "已提供环境、版本、启动命令、请求及错误判据",
            "evidence": [{"source": "正文", "quote": self.details["oracle"]}],
            "reproduction_readiness": "ready",
            "reproduction_checks": {key: {"status": "provided", "detail": detail,
                "evidence": [{"source": "正文", "quote": detail}]} for key, detail in self.details.items()},
        }

    def test_failure_claim_without_execution_machine_versions_is_not_reproducible(self):
        context = {"body": "这是 Bug！起服务失败，ValueError: invalid shape", "comments": []}
        payload = self.payload()
        payload["evidence"] = [{"source": "正文", "quote": "ValueError: invalid shape"}]
        payload.pop("reproduction_checks")
        result = normalize_triage(payload, context)
        self.assertEqual(result["category"], "uncertain")
        self.assertEqual(result["reproduction_readiness"], "insufficient")
        self.assertEqual(len(result["missing_reproduction_info"]), 5)
        self.assertTrue(result["needs_review"])
        self.assertFalse(result["auto_hidden"])

    def test_complete_evidenced_reproduction_is_ready(self):
        result = normalize_triage(self.payload(), self.context)
        self.assertEqual(result["category"], "bug_candidate")
        self.assertEqual(result["reproduction_readiness"], "ready")
        self.assertEqual(result["missing_reproduction_info"], [])
        self.assertFalse(result["needs_review"])

    def test_missing_any_required_dimension_downgrades_candidate(self):
        for key in REPRODUCTION_CHECKS:
            with self.subTest(key=key):
                payload = self.payload()
                payload["reproduction_checks"].pop(key)
                result = normalize_triage(payload, self.context)
                self.assertEqual(result["category"], "uncertain")
                self.assertEqual(result["reproduction_readiness"], "partial")
                self.assertIn(REPRODUCTION_CHECKS[key], result["missing_reproduction_info"])

    def test_fabricated_evidence_and_not_applicable_cannot_bypass_version_requirement(self):
        for check in [
            {"status": "provided", "detail": "latest", "evidence": [{"source": "正文", "quote": "latest"}]},
            {"status": "not_applicable", "detail": "无需版本", "evidence": [{"source": "正文", "quote": self.details["versions"]}]},
        ]:
            payload = self.payload()
            payload["reproduction_checks"]["versions"] = check
            result = normalize_triage(payload, self.context)
            self.assertEqual(result["reproduction_checks"]["versions"]["status"], "missing")
            self.assertNotEqual(result["reproduction_readiness"], "ready")

    def test_incomplete_context_or_model_uncertainty_prevents_ready(self):
        result = normalize_triage(self.payload(), self.context, incomplete=True)
        self.assertNotEqual(result["reproduction_readiness"], "ready")
        result = normalize_triage(self.payload(), {**self.context, "context_truncated": True})
        self.assertNotEqual(result["reproduction_readiness"], "ready")
        payload = self.payload()
        payload["reproduction_readiness"] = "partial"
        result = normalize_triage(payload, self.context)
        self.assertEqual(result["category"], "uncertain")

    def test_comments_can_supply_missing_reproduction_conditions(self):
        source = "评论:tester@2026-10-29T00:00:00Z"
        context = {"body": self.details["oracle"], "comments": [{
            "author": "tester", "created_at": "2026-10-29T00:00:00Z",
            "body": self.context["body"],
        }]}
        payload = self.payload()
        for check in payload["reproduction_checks"].values():
            check["evidence"][0]["source"] = source
        result = normalize_triage(payload, context)
        self.assertEqual(result["reproduction_readiness"], "ready")

    def test_prompt_explicitly_requires_test_execution_evidence(self):
        issue = {"repository": "example/repo", "number": 1, "title": "[Bug] failed",
                 "body": "起服务失败", "upstream_state": "open", "labels_json": '["bug"]',
                 "author": "reporter", "github_created_at": "now", "github_updated_at": "now", "notes": ""}
        messages, _ = build_triage_messages(SimpleNamespace(config={"GLM_MAX_INPUT_CHARS": 40000}), issue, [])
        prompt = messages[0]["content"]
        for text in ("测试人员现在能着手复现", "作者说“这是 Bug”不算失败判据", "没有启动命令、机器或版本", "不宣称已实际复现"):
            self.assertIn(text, prompt)

    def test_old_prompt_result_requires_review_but_manual_decision_is_preserved(self):
        issue = {"triage_json": json.dumps({"category": "bug_candidate", "prompt_version": "issue-triage-v1"}),
                 "triage_source_updated_at": "now", "github_updated_at": "now", "triage_needs_review": 0}
        self.assertTrue(triage_status(issue)["stale"])
        issue.update(manual_category="bug_candidate", manual_category_updated_at="now")
        result = triage_status(issue)
        self.assertEqual(result["effective_category"], "bug_candidate")
        self.assertFalse(result["stale"])
        self.assertTrue(result["ai_stale"])
        self.assertEqual(TRIAGE_PROMPT_VERSION, "issue-triage-v2")
