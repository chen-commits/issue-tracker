"""Evidence-based ordering for AI-analyzed, actionable Issues."""

import json
import re


VERSION_PATTERN = re.compile(r"(?<![\w.])v?(\d+)\.(\d+)(?:\.(\d+))?(?!\d)", re.I)
EXCLUDED_LABELS = {"documentation", "docs", "doc", "rfc", "question", "discussion"}
VERSION_FAMILIES = ("vllm-ascend", "torch_npu", "torch-npu", "cann", "vllm")


def explicit_version_key(value, repository=""):
    """Return a product family and explicit version, without cross-product comparison."""
    match = VERSION_PATTERN.search(value or "")
    if not match:
        return None
    prefix = (value or "")[: match.start()].casefold()[-40:]
    family = next((name for name in VERSION_FAMILIES if name in prefix), None)
    if not family and re.fullmatch(r"\s*v?\d+\.\d+(?:\.\d+)?\s*", value or "", re.I):
        family = repository.rsplit("/", 1)[-1].casefold()
    if not family:
        return None
    if family == "torch-npu":
        family = "torch_npu"
    return family, tuple(int(part or 0) for part in match.groups())


def priority_candidate(issue, suggestion):
    if not isinstance(suggestion, dict):
        return None
    labels = {str(label).casefold() for label in json.loads(issue["labels_json"] or "[]")}
    title = issue["title"].strip().casefold()
    if labels & EXCLUDED_LABELS or re.match(r"^\[(?:doc|rfc)\]", title):
        return None
    if suggestion.get("source_type") == "RFC/非缺陷":
        return None
    if suggestion.get("identification_result") == "非问题":
        return None

    reproducibility = suggestion.get("reproducibility_level")
    value = issue["value_level"] or suggestion.get("value_level")
    if reproducibility not in {"高", "中"} or value not in {"高", "中"}:
        return None

    version = issue["affected_version"] or suggestion.get("affected_version")
    try:
        confidence = max(0.0, min(1.0, float(suggestion.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "reproducibility_score": 2 if reproducibility == "高" else 1,
        "value_score": 2 if value == "高" else 1,
        "version_key": explicit_version_key(version, issue["repository"]),
        "confidence": confidence,
        "reproducibility_level": reproducibility,
        "priority_reason": str(suggestion.get("priority_reason") or "")[:160],
    }


def rank_priority_issues(connection, where_clause="", parameters=()):
    """Return ranked rows with metadata; unaudited Issues are not silently ranked."""
    rows = connection.execute(
        f"""
        SELECT issues.*, runs.suggestion_json
        FROM issues
        JOIN ai_analysis_runs AS runs ON runs.id = (
            SELECT id FROM ai_analysis_runs
            WHERE issue_number = issues.number
            ORDER BY id DESC LIMIT 1
        )
        {where_clause}
        """,
        parameters,
    ).fetchall()
    ranked = []
    for row in rows:
        try:
            suggestion = json.loads(row["suggestion_json"])
            metadata = priority_candidate(row, suggestion)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if metadata:
            ranked.append((row, metadata))
    family_versions = {}
    for _, metadata in ranked:
        version_key = metadata["version_key"]
        if version_key:
            family_versions.setdefault(version_key[0], set()).add(version_key[1])
    family_positions = {
        family: {version: index + 1 for index, version in enumerate(sorted(versions))}
        for family, versions in family_versions.items()
    }
    for row, metadata in ranked:
        version_key = metadata["version_key"]
        recency = 0.0
        if version_key:
            positions = family_positions[version_key[0]]
            recency = positions[version_key[1]] / len(positions)
        metadata["sort_key"] = (
            metadata["reproducibility_score"],
            metadata["value_score"],
            recency,
            metadata["confidence"],
            row["github_created_at"],
            row["number"],
        )
    ranked.sort(key=lambda entry: entry[1]["sort_key"], reverse=True)
    return ranked
