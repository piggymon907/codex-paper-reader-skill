#!/usr/bin/env python3
"""Run fast mechanical checks on bound notes before packaging a reader."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run_tracker import (
    ensure_stage_running,
    finish_stage,
    finish_stage_if_running,
    start_stage,
)
from validate_reader import (
    ALLOWED_CATEGORIES,
    ALLOWED_CLAIMS,
    ALLOWED_CONTENT_TYPES,
    ALLOWED_FORMULA_SOURCE_STATUS,
    ALLOWED_MARKER_EXPERIMENTAL_STATUS,
    boxes_for,
    explanation_length,
    first_sentence_identifies_object,
    normalize_evidence,
)
from version_info import SCHEMA_VERSION, SKILL_NAME, SKILL_VERSION


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def page_map(index: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(page["number"]): page
        for page in index.get("pages", [])
        if isinstance(page, dict) and str(page.get("number", "")).isdigit()
    }


def bbox_valid(box: dict[str, Any], page: dict[str, Any]) -> bool:
    try:
        x0, y0, x1, y1 = (float(box[key]) for key in ("x0", "y0", "x1", "y1"))
        width, height = float(page["width_pt"]), float(page["height_pt"])
    except (KeyError, TypeError, ValueError):
        return False
    return 0 <= x0 < x1 <= width + 1 and 0 <= y0 < y1 <= height + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-index", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-dir", help="Optional initialized run-tracking directory")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else None
    if run_dir:
        finish_stage_if_running(run_dir, "targeted_revision")
        start_stage(run_dir, "preflight")
    index_path = Path(args.paper_index).resolve()
    notes_path = Path(args.notes).resolve()
    index = load_object(index_path)
    notes = load_object(notes_path)
    pages = page_map(index)
    errors: list[str] = []
    warnings: list[str] = []

    if notes.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"Notes schema mismatch: expected {SCHEMA_VERSION}, found {notes.get('schema_version')!r}"
        )
    if not pages:
        errors.append("Paper index contains no usable pages")
    notes_pages = notes.get("pages", {})
    if not isinstance(notes_pages, dict):
        errors.append("notes.pages must be an object")
        notes_pages = {}

    candidate_ids = {
        str(item.get("id"))
        for item in index.get("visual_candidates", [])
        if isinstance(item, dict) and item.get("id")
    }
    excluded_ids: set[str] = set()
    for item in notes.get("paper", {}).get("excluded_visual_candidates", []):
        if not isinstance(item, dict):
            errors.append("Each excluded visual candidate must be an object")
            continue
        item_id = str(item.get("id", ""))
        if item_id not in candidate_ids:
            errors.append(f"Excluded visual candidate is unknown: {item_id!r}")
        if not str(item.get("reason", "")).strip():
            errors.append(f"Excluded visual candidate lacks a reason: {item_id!r}")
        excluded_ids.add(item_id)

    marker_ids: set[str] = set()
    covered_visual_ids: set[str] = set()
    marker_count = 0
    direct_count = 0
    direct_bound = 0
    for page_key, page_notes in notes_pages.items():
        try:
            number = int(page_key)
        except (TypeError, ValueError):
            errors.append(f"Invalid notes page key: {page_key!r}")
            continue
        source_page = pages.get(number)
        if not source_page:
            errors.append(f"Notes reference unknown page {number}")
            continue
        if not isinstance(page_notes, dict):
            errors.append(f"Page {number} notes must be an object")
            continue
        source_blocks = {
            str(block.get("id")): block
            for block in source_page.get("text_blocks", [])
            if isinstance(block, dict) and block.get("id")
        }
        markers = page_notes.get("markers", [])
        if not isinstance(markers, list):
            errors.append(f"Page {number} markers must be a list")
            continue
        for marker_index, marker in enumerate(markers, start=1):
            marker_count += 1
            prefix = f"Page {number} marker {marker_index}"
            if not isinstance(marker, dict):
                errors.append(f"{prefix}: marker must be an object")
                continue
            marker_id = str(marker.get("id", "")).strip()
            if not marker_id:
                errors.append(f"{prefix}: id is missing")
            elif marker_id in marker_ids:
                errors.append(f"{prefix}: duplicate id {marker_id}")
            marker_ids.add(marker_id)
            content_type = str(marker.get("content_type", "text"))
            if marker.get("category") not in ALLOWED_CATEGORIES:
                errors.append(f"{prefix}: invalid category {marker.get('category')!r}")
            if marker.get("claim_status") not in ALLOWED_CLAIMS:
                errors.append(f"{prefix}: invalid claim_status {marker.get('claim_status')!r}")
            if content_type not in ALLOWED_CONTENT_TYPES:
                errors.append(f"{prefix}: invalid content_type {content_type!r}")
            for field in ("title", "takeaway", "explanation", "locator"):
                if not str(marker.get(field, "")).strip():
                    errors.append(f"{prefix}: {field} is missing")

            useful_length = explanation_length(marker)
            minimum = 250 if content_type in {"figure", "table"} else 150
            if useful_length < minimum:
                warnings.append(
                    f"{prefix}: explanation detail {useful_length} chars is below the {minimum}-char guide"
                )
            if marker.get("teaching_priority") == "key":
                guide = 800 if content_type in {"figure", "table"} else 500 if content_type == "formula" else 250
                if useful_length < guide:
                    warnings.append(
                        f"{prefix}: key teaching detail {useful_length} chars is below the {guide}-char guide"
                    )
            if content_type in {"figure", "table", "formula"} and not first_sentence_identifies_object(
                marker.get("takeaway"), content_type
            ):
                warnings.append(
                    f"{prefix}: takeaway could identify the current {content_type} more explicitly"
                )

            for box in boxes_for(marker):
                if not bbox_valid(box, source_page):
                    errors.append(f"{prefix}: invalid or out-of-page bbox {box!r}")
            if content_type in {"figure", "table"}:
                candidate_id = str(marker.get("visual_candidate_id", ""))
                if candidate_id not in candidate_ids:
                    errors.append(f"{prefix}: unknown or missing visual_candidate_id {candidate_id!r}")
                else:
                    covered_visual_ids.add(candidate_id)
                if not (marker.get("visual_bbox") or marker.get("crop_bbox")):
                    errors.append(f"{prefix}: figure/table marker lacks visual_bbox")
                for field in ("how_to_read", "supports", "does_not_support"):
                    if not str(marker.get(field, "")).strip():
                        errors.append(f"{prefix}: figure/table marker lacks {field}")
            if content_type == "formula":
                formula_status = str(marker.get("formula_source_status", ""))
                if formula_status not in ALLOWED_FORMULA_SOURCE_STATUS:
                    errors.append(f"{prefix}: invalid formula_source_status {formula_status!r}")
                elif formula_status != "verified" and not marker.get("must_check_source"):
                    errors.append(f"{prefix}: unverified formula must set must_check_source")
                if marker.get("teaching_priority") == "key" and not marker.get("visual_bbox"):
                    errors.append(f"{prefix}: key formula requires a reviewed visual_bbox")

            experimental_data = marker.get("experimental_data")
            if experimental_data is not None:
                if not isinstance(experimental_data, dict):
                    errors.append(f"{prefix}: experimental_data must be an object")
                elif experimental_data.get("status") not in ALLOWED_MARKER_EXPERIMENTAL_STATUS:
                    errors.append(f"{prefix}: invalid marker experimental_data status")

            block_ids = marker.get("block_ids", [])
            if not isinstance(block_ids, list):
                errors.append(f"{prefix}: block_ids must be a list")
                block_ids = []
            for block_id in block_ids:
                if block_id not in source_blocks:
                    errors.append(f"{prefix}: unknown block_id {block_id}")
            if marker.get("claim_status") == "direct":
                direct_count += 1
                if not block_ids:
                    errors.append(f"{prefix}: direct marker lacks bound block_ids")
                    continue
                source_text = normalize_evidence(str(marker.get("source_text", "")))
                bound_text = normalize_evidence(
                    " ".join(str(source_blocks[block_id].get("text", "")) for block_id in block_ids if block_id in source_blocks)
                )
                if not source_text or source_text not in bound_text:
                    errors.append(f"{prefix}: source_text is not verbatim within bound blocks")
                else:
                    direct_bound += 1

    uncovered = candidate_ids - covered_visual_ids - excluded_ids
    if uncovered:
        errors.append(f"Uncovered visual candidates: {', '.join(sorted(uncovered))}")

    report = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"skill_name": SKILL_NAME, "skill_version": SKILL_VERSION},
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not errors else "fail",
        "scope": "mechanical notes/schema/evidence checks; not scientific correctness",
        "coverage": {
            "pages": len(pages),
            "markers": marker_count,
            "visual_candidates": len(candidate_ids),
            "visual_candidates_covered": len(candidate_ids & covered_visual_ids),
            "visual_candidates_excluded": len(candidate_ids & excluded_ids),
            "direct_markers": direct_count,
            "direct_markers_bound": direct_bound,
        },
        "errors": errors,
        "warnings": warnings,
    }
    output_path = Path(args.out).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    if run_dir:
        finish_stage(
            run_dir,
            "preflight",
            status="completed" if not errors else "failed",
            errors=len(errors),
            warnings=len(warnings),
        )
        if errors:
            ensure_stage_running(run_dir, "targeted_revision")
    print(f"Preflight {report['status']}: {len(errors)} error(s), {len(warnings)} warning(s)")
    print(f"Report: {output_path}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
