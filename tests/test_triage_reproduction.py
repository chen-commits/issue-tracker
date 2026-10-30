import json
import unittest
from types import SimpleNamespace

from issue_tracker.ai_analysis import build_issue_context
from issue_tracker.application import suggested_identification

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
        self.assertEqual(TRIAGE_PROMPT_VERSION, "issue-triage-v3")

    def issue(self, body, title="[Bug] sample"):
        return {"repository": "example/repo", "number": 20172, "title": title, "body": body,
                "upstream_state": "open", "labels_json": "[]", "author": "reporter",
                "github_created_at": "now", "github_updated_at": "now", "notes": ""}

    def final_result(self, normalized):
        return suggested_identification({"triage_json": json.dumps({**normalized, "prompt_version": TRIAGE_PROMPT_VERSION}),
                                         "github_updated_at": "now", "triage_source_updated_at": "now",
                                         "triage_hidden": normalized["auto_hidden"], "triage_needs_review": normalized["needs_review"],
                                         "manual_category": "", "identification_result": ""})

    def test_body_longer_than_old_half_budget_is_sent_in_full_with_workaround(self):
        body = "environment log\n" * 1400 + "\nrun_p.sh\nrun_d.sh\nexport HCCL_INTRA_ROCE_ENABLE=1"
        self.assertGreater(len(body), 20000)
        self.assertLess(len(body), 40000)
        context = build_issue_context(SimpleNamespace(config={"GLM_MAX_INPUT_CHARS": 40000}), self.issue(body), [], False)
        self.assertEqual(context["body"], body)
        self.assertFalse(context["context_truncated"])
        self.assertEqual(context["input_stats"]["body_sent_chars"], len(body))

    def test_long_comment_is_not_arbitrarily_cut_at_5000_characters(self):
        comment = {"user": {"login": "tester"}, "created_at": "now", "body": "x" * 7000 + "\n完整启动脚本在这里"}
        context = build_issue_context(SimpleNamespace(config={"GLM_MAX_INPUT_CHARS": 40000}), self.issue("short"), [comment], False)
        self.assertEqual(context["comments"][0]["body"], comment["body"])
        self.assertFalse(context["context_truncated"])

    def test_over_budget_input_is_explicit_and_cannot_be_called_hard_to_reproduce(self):
        context = build_issue_context(SimpleNamespace(config={"GLM_MAX_INPUT_CHARS": 5000}),
                                      self.issue("environment\n" + "x" * 12000 + "\nrun_d.sh\nValueError"), [], False)
        self.assertTrue(context["context_truncated"])
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False)), 5000)
        self.assertIn("run_d.sh", context["body"])
        payload = self.payload()
        payload["evidence"] = [{"source": "正文", "quote": "ValueError"}]
        payload["failure_evidence"] = payload["evidence"]
        normalized = normalize_triage(payload, context)
        self.assertTrue(normalized["input_incomplete"])
        self.assertEqual(self.final_result(normalized), "待分析")

    def test_documents_and_nightly_tracking_do_not_require_machine_or_launch_scripts(self):
        examples = [
            ("[Doc]: 版本适配说明", "The doc issue\nSuggest a potential alternative/fix\npatch.zip", "documentation", "文档说明及补丁附件"),
            ("Nightly Daily test failure - please check", "Nightly reported failures\nFailed test cases: AssertionError\nMerged PRs in this window, please check", "tracking", "Nightly失败汇总通知，供关联PR排查"),
        ]
        for title, body, category, reason in examples:
            with self.subTest(category=category):
                payload = {"category": category, "reason": reason, "confidence": 0.99,
                           "has_failure_report": False, "needs_review": False,
                           "evidence": [{"source": "标题", "quote": title}]}
                normalized = normalize_triage(payload, {"title": title, "body": body, "comments": []})
                self.assertEqual(self.final_result(normalized), "非问题")
                self.assertEqual(normalized["missing_reproduction_info"], [])
                self.assertEqual(normalized["reproduction_readiness"], "not_applicable")

    def test_non_defect_classification_with_failure_flag_is_a_conflict_not_hard_to_reproduce(self):
        payload = {"category": "documentation", "confidence": 0.99, "has_failure_report": True,
                   "needs_review": False, "evidence": [{"source": "正文", "quote": "文档问题"}]}
        normalized = normalize_triage(payload, {"body": "文档问题", "comments": []})
        self.assertTrue(normalized["classification_conflict"])
        self.assertEqual(self.final_result(normalized), "待分析")

    def test_failure_claim_without_actual_failure_evidence_is_not_hard_to_reproduce(self):
        payload = {"category": "uncertain", "confidence": 0.99, "has_failure_report": True,
                   "needs_review": True, "evidence": [{"source": "正文", "quote": "请排查"}]}
        normalized = normalize_triage(payload, {"body": "请排查", "comments": []})
        self.assertEqual(self.final_result(normalized), "待分析")

    def test_unread_essential_script_attachment_is_not_product_reproduction_difficulty(self):
        payload = self.payload()
        payload["requires_unread_attachments"] = True
        context = {**self.context, "body": self.context["body"] + "\n[request.py](https://github.com/user-attachments/files/123/request.py)"}
        normalized = normalize_triage(payload, context)
        self.assertTrue(normalized["requires_unread_attachments"])
        self.assertEqual(self.final_result(normalized), "待分析")
        self.assertIn("附件", normalized["reason"])
