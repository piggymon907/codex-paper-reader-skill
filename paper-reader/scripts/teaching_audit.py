#!/usr/bin/env python3
"""Create and validate a source-object teaching audit for Paper Reader notes.

The audit is deliberately separate from the delivered reader schema.  It makes
the model's figure/formula self-review observable and mechanically requires a
completed source inventory, links into the delivered teaching prose, coverage
ledger, and source-fidelity checks.  It still does not prove scientific
correctness.  The audit deliberately does not duplicate the explanation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from run_tracker import (
    append_event,
    ensure_stage_running,
    finish_stage,
    finish_stage_if_running,
    record_milestone,
    start_stage,
)
from version_info import SCHEMA_VERSION, SKILL_NAME, SKILL_VERSION


AUDIT_SCHEMA_VERSION = "1.1"
ELIGIBLE_TYPES = {"figure", "table", "formula"}
ALLOWED_COMPLEXITIES = {"simple", "multi_panel", "reasoning_heavy"}
ALLOWED_AUDIT_LEVELS = {"standard", "full"}
ALLOWED_FULL_TRIGGERS = {
    "multi_panel",
    "multi_curve_or_condition",
    "reasoning_chain",
    "main_claim",
    "downstream_dependency",
    "cross_page_context",
    "source_conflict",
}
CORE_LEARNER_CHECKS = (
    "object_and_question",
    "reading_or_use_order",
    "evidence_to_conclusion",
    "boundaries",
)
FULL_LEARNER_CHECKS = (
    "prerequisites_and_variables",
    "dependency_chain",
)
ALLOWED_COVERAGE = {"covered", "bounded_source_limit", "missing"}
ALLOWED_FACT_STATUS = {"verified", "corrected", "unresolved", "contradicted"}
ALLOWED_FACT_KINDS = {"source_fidelity", "reasoning_fidelity", "source_limit"}
ALLOWED_VERDICTS = {"pass", "pass_with_source_limit", "revise"}
PLACEHOLDERS = {"", "todo", "tbd", "review_required", "待填写", "待核对", "unknown"}
BINDING_FIELDS = {
    "block_ids",
    "bboxes",
    "visual_bbox",
    "crop_bbox",
    "source_text",
    "visual_candidate_id",
    "locator",
    "claim_status",
    "must_check_source",
    "formula_source_status",
}
TEACHING_FIELDS = (
    "takeaway",
    "how_to_read",
    "explanation",
    "supports",
    "does_not_support",
    "limitations",
    "prerequisites",
    "reading_steps",
    "key_values",
    "symbols",
    "derivation_steps",
    "common_misreadings",
    "source_checks",
    "detail_sections",
    "panels",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def eligible_markers(notes: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    result: list[tuple[int, dict[str, Any]]] = []
    pages = notes.get("pages", {})
    if not isinstance(pages, dict):
        return result
    for page_key, page in pages.items():
        try:
            page_number = int(page_key)
        except (TypeError, ValueError):
            continue
        if not isinstance(page, dict):
            continue
        for marker in page.get("markers", []):
            if isinstance(marker, dict) and marker.get("content_type") in ELIGIBLE_TYPES:
                result.append((page_number, marker))
    return result


def semantic_marker(marker: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in marker.items() if key not in BINDING_FIELDS}


def teaching_notes_sha256(notes: dict[str, Any]) -> str:
    payload = {
        "schema_version": notes.get("schema_version"),
        "paper_title": notes.get("paper", {}).get("title"),
        "items": [
            {"page": page, "marker": semantic_marker(marker)}
            for page, marker in eligible_markers(notes)
        ],
    }
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() not in PLACEHOLDERS


def nonempty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(nonempty_text(item) for item in value)
    )


def flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten_text(item) for item in value)
    return str(value) if value is not None else ""


def normalize_text(value: Any) -> str:
    return " ".join(flatten_text(value).split()).casefold()


def teaching_character_count(marker: dict[str, Any]) -> int:
    """Count non-whitespace teaching characters as a diagnostic, never a pass gate."""
    text = " ".join(flatten_text(marker.get(field)) for field in TEACHING_FIELDS)
    return len("".join(text.split()))


def length_summary(values: list[int]) -> dict[str, int | float | None]:
    if not values:
        return {
            "count": 0,
            "total": 0,
            "minimum": None,
            "median": None,
            "maximum": None,
        }
    return {
        "count": len(values),
        "total": sum(values),
        "minimum": min(values),
        "median": round(float(median(values)), 1),
        "maximum": max(values),
    }


def audit_template(notes: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for page, marker in eligible_markers(notes):
        items.append(
            {
                "marker_id": marker.get("id", ""),
                "page": page,
                "content_type": marker.get("content_type"),
                "title": marker.get("title", ""),
                "complexity": "review_required",
                "audit_level": "review_required",
                "audit_reason": "",
                "full_audit_triggers": [],
                "source_inventory": {
                    "components": [],
                    "encodings_or_symbols": [],
                    "numeric_or_condition_labels": [],
                },
                "learner_check": {
                    "object_and_question": {"note_field": "", "teaching_evidence": ""},
                    "reading_or_use_order": {"note_field": "", "teaching_evidence": ""},
                    "evidence_to_conclusion": {"note_field": "", "teaching_evidence": ""},
                    "boundaries": {"note_field": "", "teaching_evidence": ""},
                    "prerequisites_and_variables": {"note_field": "", "teaching_evidence": ""},
                    "dependency_chain": {"note_field": "", "teaching_evidence": ""},
                },
                "coverage": [],
                "factual_checks": [],
                "unresolved_source_limits": [],
                "verdict": "revise",
                "revision_summary": "",
            }
        )
    return {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "generator": {"skill_name": SKILL_NAME, "skill_version": SKILL_VERSION},
        "created_at": utc_now(),
        "initial_teaching_notes_sha256": teaching_notes_sha256(notes),
        "scope": (
            "model-performed source-object teaching and fidelity review; "
            "not independent expert proof of scientific correctness"
        ),
        "items": items,
    }


def check_audit(notes: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    current_hash = teaching_notes_sha256(notes)
    if audit.get("audit_schema_version") != AUDIT_SCHEMA_VERSION:
        errors.append(
            "Teaching audit schema mismatch: "
            f"expected {AUDIT_SCHEMA_VERSION}, found {audit.get('audit_schema_version')!r}"
        )
    # The note and audit item are intentionally filled together during the first
    # source-object pass, so the skeleton's initial hash may change.  The checked
    # report below stamps the final semantic hash; build_reader rejects any note
    # edits made after that report.

    markers = {str(marker.get("id", "")): (page, marker) for page, marker in eligible_markers(notes)}
    items = audit.get("items", [])
    if not isinstance(items, list):
        errors.append("audit.items must be a list")
        items = []
    item_map: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append(f"Audit item {index} must be an object")
            continue
        marker_id = str(item.get("marker_id", "")).strip()
        if not marker_id:
            errors.append(f"Audit item {index} lacks marker_id")
            continue
        if marker_id in item_map:
            errors.append(f"Duplicate teaching audit item: {marker_id}")
            continue
        item_map[marker_id] = item

    missing_items = sorted(set(markers) - set(item_map))
    extra_items = sorted(set(item_map) - set(markers))
    if missing_items:
        errors.append(f"Missing teaching audit items: {', '.join(missing_items)}")
    if extra_items:
        errors.append(f"Audit references unknown or ineligible markers: {', '.join(extra_items)}")

    pass_count = 0
    limited_count = 0
    corrected_count = 0
    standard_count = 0
    full_count = 0
    trigger_counts: Counter[str] = Counter()
    complexity_counts: Counter[str] = Counter()
    content_type_counts: Counter[str] = Counter()
    lengths_by_level: dict[str, list[int]] = {"all": [], "standard": [], "full": []}
    for marker_id, (page, marker) in markers.items():
        item = item_map.get(marker_id)
        if not item:
            continue
        prefix = f"Page {page} {marker_id}"
        content_type_counts[str(marker.get("content_type", "unknown"))] += 1
        if item.get("content_type") != marker.get("content_type"):
            errors.append(f"{prefix}: content_type does not match notes")
        if item.get("complexity") not in ALLOWED_COMPLEXITIES:
            errors.append(f"{prefix}: complexity must be reviewed")
        complexity = item.get("complexity")
        if complexity in ALLOWED_COMPLEXITIES:
            complexity_counts[str(complexity)] += 1
        audit_level = item.get("audit_level")
        if audit_level not in ALLOWED_AUDIT_LEVELS:
            errors.append(f"{prefix}: audit_level must be standard or full")
        elif audit_level == "standard":
            standard_count += 1
        else:
            full_count += 1
        if not nonempty_text(item.get("audit_reason")):
            errors.append(f"{prefix}: audit_reason must explain the selected audit level")
        triggers = item.get("full_audit_triggers")
        if not isinstance(triggers, list) or not all(
            isinstance(value, str) and value in ALLOWED_FULL_TRIGGERS for value in triggers
        ):
            errors.append(f"{prefix}: full_audit_triggers contains an unsupported value")
            triggers = []
        if len(triggers) != len(set(triggers)):
            errors.append(f"{prefix}: full_audit_triggers contains duplicates")
        trigger_counts.update(triggers)
        character_count = teaching_character_count(marker)
        lengths_by_level["all"].append(character_count)
        if audit_level in {"standard", "full"}:
            lengths_by_level[str(audit_level)].append(character_count)
        if audit_level == "full" and not triggers:
            errors.append(f"{prefix}: full audit requires at least one explicit trigger")
        if complexity == "multi_panel" and "multi_panel" not in triggers:
            errors.append(f"{prefix}: multi_panel complexity must record the multi_panel trigger")
        if complexity == "reasoning_heavy" and "reasoning_chain" not in triggers:
            errors.append(f"{prefix}: reasoning_heavy complexity must record the reasoning_chain trigger")
        if triggers and audit_level != "full":
            errors.append(f"{prefix}: any full-audit trigger requires audit_level=full")
        if complexity in {"multi_panel", "reasoning_heavy"} and audit_level != "full":
            errors.append(f"{prefix}: complex source objects require the full learner audit")

        inventory = item.get("source_inventory")
        if not isinstance(inventory, dict):
            errors.append(f"{prefix}: source_inventory must be an object")
            inventory = {}
        components = inventory.get("components")
        encodings = inventory.get("encodings_or_symbols")
        labels = inventory.get("numeric_or_condition_labels")
        if not nonempty_string_list(components):
            errors.append(f"{prefix}: source_inventory.components is empty")
            components = []
        if not nonempty_string_list(encodings):
            errors.append(f"{prefix}: source_inventory.encodings_or_symbols is empty")
        if not isinstance(labels, list) or not all(nonempty_text(value) for value in labels):
            errors.append(f"{prefix}: numeric_or_condition_labels must be a list of reviewed strings")

        learner = item.get("learner_check")
        if not isinstance(learner, dict):
            errors.append(f"{prefix}: learner_check must be an object")
            learner = {}
        for field, linked in learner.items():
            if isinstance(linked, dict) and "answer" in linked:
                errors.append(
                    f"{prefix}: learner_check.{field} duplicates an answer; "
                    "store the answer only in the delivered marker"
                )
        required_checks = list(CORE_LEARNER_CHECKS)
        if audit_level == "full":
            required_checks.extend(FULL_LEARNER_CHECKS)
        for field in required_checks:
            linked = learner.get(field)
            if not isinstance(linked, dict):
                errors.append(f"{prefix}: learner_check.{field} must link to delivered teaching prose")
                continue
            note_field = str(linked.get("note_field", "")).strip()
            teaching_evidence = str(linked.get("teaching_evidence", "")).strip()
            if note_field not in marker:
                errors.append(f"{prefix}: learner_check.{field} lacks a valid note_field")
            elif not teaching_evidence:
                errors.append(f"{prefix}: learner_check.{field} lacks teaching_evidence")
            elif normalize_text(teaching_evidence) not in normalize_text(marker.get(note_field)):
                errors.append(
                    f"{prefix}: learner_check.{field} evidence is not present in {note_field}"
                )

        coverage = item.get("coverage")
        if not isinstance(coverage, list):
            errors.append(f"{prefix}: coverage must be a list")
            coverage = []
        coverage_map: dict[str, dict[str, Any]] = {}
        for entry in coverage:
            if not isinstance(entry, dict):
                errors.append(f"{prefix}: each coverage entry must be an object")
                continue
            source_element = str(entry.get("source_element", "")).strip()
            if not source_element:
                errors.append(f"{prefix}: coverage entry lacks source_element")
                continue
            status = entry.get("status")
            if status not in ALLOWED_COVERAGE:
                errors.append(f"{prefix}: invalid coverage status for {source_element!r}")
            if status == "missing":
                errors.append(f"{prefix}: teaching coverage is missing for {source_element!r}")
            if status == "bounded_source_limit" and not nonempty_text(entry.get("note")):
                errors.append(f"{prefix}: bounded source limit needs a specific note for {source_element!r}")
            note_field = str(entry.get("note_field", "")).strip()
            teaching_evidence = str(entry.get("teaching_evidence", "")).strip()
            if note_field not in marker:
                errors.append(f"{prefix}: coverage for {source_element!r} lacks a valid note_field")
            elif not teaching_evidence:
                errors.append(f"{prefix}: coverage for {source_element!r} lacks teaching_evidence")
            elif normalize_text(teaching_evidence) not in normalize_text(marker.get(note_field)):
                errors.append(
                    f"{prefix}: teaching_evidence for {source_element!r} is not present in {note_field}"
                )
            coverage_map[source_element.casefold()] = entry
        inventory_elements = list(components)
        if isinstance(encodings, list):
            inventory_elements.extend(encodings)
        if isinstance(labels, list):
            inventory_elements.extend(labels)
        for component in inventory_elements:
            if component.casefold() not in coverage_map:
                errors.append(f"{prefix}: source inventory element lacks coverage record: {component!r}")

        facts = item.get("factual_checks")
        if not isinstance(facts, list) or not facts:
            errors.append(f"{prefix}: factual_checks is empty")
            facts = []
        has_unresolved = False
        has_corrected = False
        fact_kinds: set[str] = set()
        for fact in facts:
            if not isinstance(fact, dict):
                errors.append(f"{prefix}: each factual check must be an object")
                continue
            if not nonempty_text(fact.get("claim")) or not nonempty_text(fact.get("source")):
                errors.append(f"{prefix}: factual check requires claim and source")
            status = fact.get("status")
            kind = fact.get("kind")
            if kind not in ALLOWED_FACT_KINDS:
                errors.append(f"{prefix}: factual check requires a supported kind")
            else:
                fact_kinds.add(kind)
            if status not in ALLOWED_FACT_STATUS:
                errors.append(f"{prefix}: invalid factual-check status {status!r}")
            if status == "contradicted":
                errors.append(f"{prefix}: contradicted teaching claim remains unresolved")
            if status == "unresolved":
                has_unresolved = True
                if not nonempty_text(fact.get("note")):
                    errors.append(f"{prefix}: unresolved factual check needs a reason")
            if status == "corrected":
                has_corrected = True
        if "source_fidelity" not in fact_kinds:
            errors.append(f"{prefix}: factual_checks must include source_fidelity")
        if audit_level == "full" and "reasoning_fidelity" not in fact_kinds:
            errors.append(f"{prefix}: full audit must include reasoning_fidelity")

        limits = item.get("unresolved_source_limits")
        if not isinstance(limits, list) or not all(nonempty_text(value) for value in limits):
            errors.append(f"{prefix}: unresolved_source_limits must be a list of specific strings")
            limits = []
        verdict = item.get("verdict")
        if verdict not in ALLOWED_VERDICTS:
            errors.append(f"{prefix}: invalid verdict {verdict!r}")
        elif verdict == "revise":
            errors.append(f"{prefix}: teaching audit still requires revision")
        elif verdict == "pass_with_source_limit":
            limited_count += 1
            if not limits and not has_unresolved and not any(
                entry.get("status") == "bounded_source_limit" for entry in coverage if isinstance(entry, dict)
            ):
                errors.append(f"{prefix}: source-limited verdict lacks a specific source limit")
            if not marker.get("must_check_source"):
                warnings.append(f"{prefix}: source-limited audit but marker does not set must_check_source")
        elif verdict == "pass":
            pass_count += 1
            if has_unresolved or limits:
                errors.append(f"{prefix}: pass verdict conflicts with unresolved source limits")
        if has_corrected:
            corrected_count += 1
            if not nonempty_text(item.get("revision_summary")):
                errors.append(f"{prefix}: corrected claim requires revision_summary")

    return {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "generator": {"skill_name": SKILL_NAME, "skill_version": SKILL_VERSION},
        "checked_at": utc_now(),
        "status": "pass" if not errors else "fail",
        "scope": (
            "structural evidence that a source-object teaching self-audit was completed; "
            "does not prove independent scientific correctness"
        ),
        "teaching_notes_sha256": current_hash,
        "coverage": {
            "eligible_markers": len(markers),
            "audit_items": len(item_map),
            "pass": pass_count,
            "pass_with_source_limit": limited_count,
            "corrected_during_audit": corrected_count,
            "standard_audit": standard_count,
            "full_audit": full_count,
            "full_audit_trigger_counts": dict(sorted(trigger_counts.items())),
            "complexity_counts": dict(sorted(complexity_counts.items())),
            "content_type_counts": dict(sorted(content_type_counts.items())),
            "teaching_characters": {
                level: length_summary(values)
                for level, values in lengths_by_level.items()
            },
        },
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="Create an audit skeleton from notes")
    init_parser.add_argument("--notes", required=True)
    init_parser.add_argument("--out", required=True)
    init_parser.add_argument("--run-dir")
    check_parser = subparsers.add_parser("check", help="Validate a completed teaching audit")
    check_parser.add_argument("--notes", required=True)
    check_parser.add_argument("--audit", required=True)
    check_parser.add_argument("--out", required=True)
    check_parser.add_argument("--run-dir")
    args = parser.parse_args()

    notes_path = Path(args.notes).resolve()
    notes = load_object(notes_path)
    run_dir = Path(args.run_dir).resolve() if args.run_dir else None
    if args.command == "init":
        output = Path(args.out).resolve()
        value = audit_template(notes)
        atomic_json(output, value)
        if run_dir:
            record_milestone(
                run_dir,
                "audit_skeleton_initialized",
                {"eligible_items": len(value["items"])},
            )
            append_event(
                run_dir,
                {"event": "teaching_audit_initialized", "items": len(value["items"])},
            )
        print(f"Teaching audit skeleton: {len(value['items'])} item(s) at {output}")
        return 0

    if run_dir:
        finish_stage_if_running(run_dir, "targeted_revision")
        start_stage(run_dir, "teaching_audit_check")
    try:
        audit = load_object(Path(args.audit).resolve())
        if run_dir:
            record_milestone(
                run_dir,
                "teaching_draft_ready",
                {"audit_items": len(audit.get("items", []))},
            )
        report = check_audit(notes, audit)
    except Exception:
        if run_dir:
            finish_stage(run_dir, "teaching_audit_check", status="failed", errors=1)
            ensure_stage_running(run_dir, "targeted_revision")
        raise
    output = Path(args.out).resolve()
    atomic_json(output, report)
    if run_dir:
        finish_stage(
            run_dir,
            "teaching_audit_check",
            status="completed" if report["status"] == "pass" else "failed",
            errors=len(report["errors"]),
            warnings=len(report["warnings"]),
        )
        record_milestone(
            run_dir,
            "teaching_audit_checked",
            {
                "status": report["status"],
                "errors": len(report["errors"]),
                "warnings": len(report["warnings"]),
                "coverage": report.get("coverage", {}),
            },
        )
        if report["status"] != "pass":
            ensure_stage_running(run_dir, "targeted_revision")
    print(
        f"Teaching audit {report['status']}: "
        f"{len(report['errors'])} error(s), {len(report['warnings'])} warning(s)"
    )
    print(f"Report: {output}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
