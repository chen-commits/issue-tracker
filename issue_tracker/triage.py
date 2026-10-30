"""Conservative AI triage, independent of manually maintained test analysis."""

import hashlib
import json
import math
import re

from .ai_analysis import build_issue_context, parse_ai_json
from .triage_prompt import TRIAGE_SYSTEM_PROMPT


TRIAGE_PROMPT_VERSION = "issue-triage-v4"
CATEGORIES = {
    "bug_candidate": "Bug 候选",
    "feature_request": "功能需求",
    "documentation": "文档问题",
    "question": "使用咨询",
    "rfc_discussion": "RFC / 讨论",
    "tracking": "跟踪事项或通知",
    "uncertain": "待确认",
}
NON_BUG_CATEGORIES = set(CATEGORIES) - {"bug_candidate", "uncertain"}
REPRODUCTION_CHECKS = {
    "execution": "执行入口/启动脚本",
    "environment": "机器和关键配置",
    "versions": "软件版本或提交",
    "trigger": "触发输入/步骤",
    "oracle": "实际异常和预期判据",
}


def text_value(value):
    return value.strip() if isinstance(value, str) else ""


def text_items(value):
    return [item.strip() for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def normalize_test_plan(value):
    if not isinstance(value, dict):
        return None, ""
    decision = value.get("decision")
    if decision not in ("需要", "不需要", "待补充"):
        decision = "待补充"
    types = list(dict.fromkeys(item for item in text_items(value.get("types")) if item in {"功能", "性能"}))
    plan = {key: text_value(value.get(key)) for key in ("reason", "service_setup", "request", "baseline")}
    plan.update(decision=decision, types=types,
                functional_assertions=text_items(value.get("functional_assertions")),
                performance_assertions=text_items(value.get("performance_assertions")),
                missing_info=text_items(value.get("missing_info")))
    if decision == "需要":
        for key, label in (("service_setup", "服务启动方式"), ("request", "触发请求或压测入口")):
            if not plan[key] and label not in plan["missing_info"]:
                plan["missing_info"].append(label)
        for kind, key in (("功能", "functional_assertions"), ("性能", "performance_assertions")):
            label = kind + "验证判据"
            if kind in types and not plan[key] and label not in plan["missing_info"]:
                plan["missing_info"].append(label)
    lines = [f"是否补充集成测试：{decision}" + ("（" + "/".join(types) + "）" if types else "")]
    for key, label in (("reason", "理由"), ("service_setup", "拉起服务"), ("request", "请求/压测"),
                       ("functional_assertions", "功能断言"), ("performance_assertions", "性能断言"),
                       ("baseline", "对照基线"), ("missing_info", "待补充")):
        if plan[key]:
            lines.append(label + "：" + ("；".join(plan[key]) if isinstance(plan[key], list) else plan[key]))
    return plan, "\n".join(lines)


def triage_analysis_fields(snapshot):
    fields = {key: text_value(snapshot.get(key)) for key in ("summary_zh", "supplemental_test")}
    if snapshot.get("value_level") in ("高", "中", "低"):
        fields["value_level"] = snapshot["value_level"]
    return {key: value for key, value in fields.items() if value}

# Reused by lists, exports, priority views, and filtered batch selection.
FRESH_SQL = f"(triage_source_updated_at = github_updated_at AND triage_source_updated_at != '' AND COALESCE(json_extract(triage_json, '$.prompt_version'), '') = '{TRIAGE_PROMPT_VERSION}')"
REPRODUCIBLE_SQL = f"""({FRESH_SQL}
    AND identification_result NOT IN ('非问题', '难以复现')
    AND COALESCE(NULLIF(manual_category, ''), json_extract(triage_json, '$.category')) = 'bug_candidate'
    AND json_extract(triage_json, '$.reproduction_readiness') = 'ready')"""
MANUAL_FRESH_SQL = "(manual_category_updated_at = github_updated_at AND manual_category_updated_at != '')"
HIDDEN_SQL = f"""(
    identification_result = '非问题' OR (identification_result = '' AND (
    (manual_category IN ('feature_request', 'documentation', 'question', 'rfc_discussion', 'tracking')
        AND {MANUAL_FRESH_SQL})
    OR (manual_category = '' AND triage_hidden = 1 AND {FRESH_SQL})
)))"""
PENDING_SQL = f"""(identification_result NOT IN ('确认问题', '非问题', '难以复现') AND NOT {HIDDEN_SQL} AND (
    identification_result = '待分析'
    OR (manual_category != '' AND (manual_category = 'uncertain' OR NOT {MANUAL_FRESH_SQL}))
    OR (manual_category = '' AND (NOT {FRESH_SQL} OR triage_needs_review = 1))
))"""


def triage_fingerprint(issue, model):
    values = [issue.get(key, "") for key in (
        "repository", "number", "title", "body", "labels_json",
        "upstream_state", "github_updated_at", "comment_count",
    )]
    return hashlib.sha256(json.dumps(
        [values, model, TRIAGE_PROMPT_VERSION], ensure_ascii=False
    ).encode("utf-8")).hexdigest()


def build_triage_messages(app, issue, comments, incomplete_comments=False):
    # Share the input budget and escaping rules with detailed analysis.
    context = build_issue_context(app, issue, comments, include_existing=False, comments_complete=not incomplete_comments)
    system = TRIAGE_SYSTEM_PROMPT
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)}], context


def normalize_triage(content, context, incomplete=False):
    payload = parse_ai_json(content)
    category = payload.get("category")
    if not isinstance(category, str) or category not in CATEGORIES:
        category = "uncertain"
    non_issue = payload.get("is_non_issue")
    if non_issue == "yes":
        category = category if category in NON_BUG_CATEGORIES else "rfc_discussion"
    elif non_issue == "no":
        category = "bug_candidate"
    elif non_issue == "uncertain":
        category = "uncertain"
    try:
        confidence = float(payload.get("confidence", 0))
        confidence = max(0.0, min(1.0, confidence)) if math.isfinite(confidence) else 0.0
    except (ValueError, TypeError):
        confidence = 0.0
    sources = {"标题": context.get("title", ""), "正文": context["body"]}
    for comment in context["comments"]:
        sources[f"评论:{comment['author']}@{comment['created_at']}"] = comment["body"]
    def verified_evidence(raw):
        valid = []
        for item in raw[:5] if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            source, quote = item.get("source"), item.get("quote")
            if isinstance(source, str) and isinstance(quote, str) and quote.strip() and quote in sources.get(source, ""):
                valid.append({"source": source, "quote": quote[:500]})
        return valid

    evidence = verified_evidence(payload.get("evidence"))
    raw_failure = payload.get("has_failure_report")
    failure = raw_failure is True
    checks = {}
    raw_checks = payload.get("reproduction_checks")
    raw_checks = raw_checks if isinstance(raw_checks, dict) else {}
    for key, label in REPRODUCTION_CHECKS.items():
        raw = raw_checks.get(key)
        raw = raw if isinstance(raw, dict) else {}
        references = verified_evidence(raw.get("evidence"))
        detail = str(raw.get("detail") or "")[:1000]
        status = raw.get("status")
        acceptable = status == "provided" or (key == "environment" and status == "not_applicable")
        if not acceptable or not references or not detail.strip():
            status = "missing"
        checks[key] = {"status": status, "detail": detail or f"待补充{label}", "evidence": references}
    missing = [label for key, label in REPRODUCTION_CHECKS.items() if checks[key]["status"] == "missing"]
    linked_material = context["body"] + "\n" + "\n".join(comment["body"] for comment in context["comments"])
    attachment_limited = (category not in NON_BUG_CATEGORIES
                          and payload.get("requires_unread_attachments") is True
                          and bool(re.search(r"https?://", linked_material)))
    partial_input = incomplete or context.get("comments_complete") is False or bool(context.get("context_truncated")) or attachment_limited
    failure_evidence = verified_evidence(payload.get("failure_evidence"))
    if failure and not failure_evidence and checks["oracle"]["status"] == "provided":
        failure_evidence = checks["oracle"]["evidence"]
    conflict = category in NON_BUG_CATEGORIES and (failure or bool(failure_evidence))
    readiness = "not_applicable"
    if category in {"bug_candidate", "uncertain"}:
        readiness = "ready" if (payload.get("reproduction_readiness") == "ready"
                                and not missing and not partial_input and evidence and failure and failure_evidence) else (
            "partial" if any(checks[key]["status"] == "provided" for key in ("execution", "versions", "trigger")) else "insufficient"
        )
    if category == "bug_candidate" and readiness != "ready":
        category = "uncertain"
        payload = dict(payload)
        payload["reason"] = ("暂不进入可复现 Bug 候选；待补充：" + "、".join(missing)
                             if missing else "复现上下文不完整或尚未确认必要条件齐备，待复核")
    if partial_input:
        payload = dict(payload)
        payload["reason"] = ("关键复现资料在未读取的附件或外链中，需读取后再判断"
                             if attachment_limited else "本次输入未完整提供，需补齐正文或评论后再判断，不能据此认定原文缺少复现条件")
    if category in NON_BUG_CATEGORIES:
        checks, missing = {}, []
    review = (payload.get("needs_review") is not False or type(raw_failure) is not bool or partial_input or not evidence
              or category == "uncertain" or confidence < 0.95
              or conflict)
    hidden = (category in NON_BUG_CATEGORIES and confidence >= 0.95
              and bool(evidence) and not failure and not review)
    warnings = []
    if incomplete or context.get("comments_complete") is False:
        warnings.append("评论未完整读取，本次不自动过滤")
    if context.get("context_truncated"):
        warnings.append("输入内容有截断，本次不自动过滤")
    if not evidence:
        warnings.append("缺少可核实的原文依据，本次不自动过滤")
    if attachment_limited:
        warnings.append("关键附件或外链未读取，不据此判断产品难以复现")
    if readiness in {"partial", "insufficient"} and not partial_input:
        warnings.append("待补充复现信息：" + "、".join(missing) if missing else "输入不完整，暂不进入可复现 Bug 候选")
    integration_test, supplemental_test = normalize_test_plan(payload.get("integration_test"))
    value_level = payload.get("value_level")
    value_level = value_level if value_level in ("高", "中", "低") else ""
    return {"category": category, "confidence": confidence,
            "summary_zh": " ".join(text_value(payload.get("summary_zh")).split()),
            "is_non_issue": non_issue if non_issue in ("yes", "no", "uncertain") else (
                "yes" if category in NON_BUG_CATEGORIES and not conflict else "no" if failure_evidence else "uncertain"),
            "value_level": value_level, "value_reason": text_value(payload.get("value_reason")),
            "integration_test": integration_test, "supplemental_test": supplemental_test,
            "reason": str(payload.get("reason") or "信息不足")[:1000],
            "evidence": evidence, "has_failure_report": failure,
            "failure_evidence": failure_evidence, "classification_conflict": conflict,
            "input_incomplete": partial_input, "input_stats": context.get("input_stats", {}),
            "requires_unread_attachments": attachment_limited,
            "needs_review": review, "auto_hidden": hidden, "warnings": warnings,
            "reproduction_readiness": readiness, "reproduction_checks": checks,
            "missing_reproduction_info": missing}


def triage_status(issue):
    result = json.loads(issue.get("triage_json") or "{}")
    manual = issue.get("manual_category", "")
    fresh = (bool(issue.get("triage_source_updated_at"))
             and issue["triage_source_updated_at"] == issue["github_updated_at"]
             and result.get("prompt_version") == TRIAGE_PROMPT_VERSION)
    manual_fresh = bool(issue.get("manual_category_updated_at")) and issue["manual_category_updated_at"] == issue["github_updated_at"]
    filtered = ((manual in NON_BUG_CATEGORIES and manual_fresh) if manual
                else bool(issue.get("triage_hidden")) and fresh)
    pending = ((manual == "uncertain" or not manual_fresh) if manual
               else not fresh or bool(issue.get("triage_needs_review", 1)))
    identification = issue.get("identification_result", "")
    if identification in {"确认问题", "非问题", "待分析", "难以复现"}:
        filtered = identification == "非问题"
        pending = identification == "待分析"
    return {"ai": result or None, "manual_category": manual,
            "source_updated_at": issue.get("triage_source_updated_at", ""),
            "effective_category": manual or result.get("category", "uncertain"),
            "filtered": bool(filtered), "needs_review": bool(pending),
            "stale": (not manual_fresh if manual else bool(result) and not fresh),
            "ai_stale": bool(result) and not fresh,
            "reviewed_at": issue.get("manual_reviewed_at", ""),
            "reviewed_by": issue.get("manual_reviewed_by", "")}
