#!/usr/bin/env python3
"""Validate structure, content quality, visual coverage, and UI contracts."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from run_tracker import (
    STATE_NAME,
    diagnostic_summary,
    finish_stage,
    load_state,
    stage_elapsed,
    start_stage,
    write_build_report,
)
from teaching_audit import AUDIT_SCHEMA_VERSION, teaching_notes_sha256
from version_info import BUILDER_VERSION, SCHEMA_VERSION, SKILL_NAME, SKILL_VERSION, VALIDATOR_VERSION


ALLOWED_CATEGORIES = {"context", "evidence", "technical", "caveat"}
ALLOWED_CLAIMS = {"direct", "inference", "unknown"}
ALLOWED_CONTENT_TYPES = {"text", "figure", "table", "formula", "method"}
ALLOWED_FORMULA_SOURCE_STATUS = {"verified", "damaged", "not_detected"}
ALLOWED_EXPERIMENTAL_DATA_STATUS = {"present", "absent", "uncertain"}
ALLOWED_MARKER_EXPERIMENTAL_STATUS = {"present", "uncertain"}
ALLOWED_EXPERIMENTAL_ORIGINS = {"author_generated", "reused_external", "mixed", "uncertain"}
LONG_ALPHA_RE = re.compile(r"[A-Za-z]{30,}")
GLUE_RE = re.compile(r"(?:[a-z]{3,}[A-Z][a-z]{2,}|[A-Za-z][,;:][A-Za-z]|[a-z]\.[A-Z])")
C0_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
OBJECT_SUBJECT_RE = {
    "figure": re.compile(r"(?:\b(?:figure|fig\.)\s*\d+|(?:这张|该|本)?图(?:表|像)?|面板)", re.IGNORECASE),
    "table": re.compile(r"(?:\btable\s*[A-Za-z0-9]+|(?:这张|该|本)?表(?:格)?)", re.IGNORECASE),
    "formula": re.compile(r"(?:\b(?:eq\.|equation)\s*\(?[A-Za-z]?\d+|(?:该|本|这条)?公式|(?:该|本)?式\s*[（(]?[A-Za-z]?\d+)", re.IGNORECASE),
}


def boxes_for(marker: dict[str, Any]) -> list[dict[str, Any]]:
    boxes = marker.get("bboxes") or ([marker.get("bbox")] if marker.get("bbox") else [])
    visual = marker.get("visual_bbox") or marker.get("crop_bbox")
    if visual:
        boxes = list(boxes) + [visual]
    return [box for box in boxes if isinstance(box, dict)]


def explanation_length(marker: dict[str, Any]) -> int:
    values = [
        marker.get("takeaway"), marker.get("how_to_read"), marker.get("explanation"),
        marker.get("supports"), marker.get("does_not_support"), marker.get("limitations"),
        marker.get("caveats"),
    ]
    for panel in marker.get("panels", []) if isinstance(marker.get("panels"), list) else []:
        if isinstance(panel, dict):
            values.extend([panel.get("summary"), panel.get("explanation")])
    for field in (
        "prerequisites", "background", "reading_steps", "key_values", "key_observations",
        "symbols", "derivation_steps", "use_steps", "common_misreadings", "source_checks",
        "detail_sections",
    ):
        value = marker.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, dict):
                    values.extend(str(part) for part in item.values() if isinstance(part, (str, int, float)))
    return len("".join(str(value or "").strip() for value in values))


def normalize_evidence(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def first_sentence_identifies_object(value: Any, content_type: str) -> bool:
    text = normalize_evidence(str(value or ""))
    first_sentence = re.split(r"[。！？!?]", text, maxsplit=1)[0][:180]
    pattern = OBJECT_SUBJECT_RE.get(content_type)
    return bool(pattern and pattern.search(first_sentence))


def count_c0_strings(value: Any) -> int:
    if isinstance(value, str):
        return len(C0_RE.findall(value))
    if isinstance(value, dict):
        return sum(count_c0_strings(item) for item in value.values())
    if isinstance(value, list):
        return sum(count_c0_strings(item) for item in value)
    return 0


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reader_dir")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    reader_dir = Path(args.reader_dir).resolve()
    tracking_enabled = (reader_dir / STATE_NAME).is_file()
    if tracking_enabled:
        start_stage(reader_dir, "validation")
    errors: list[str] = []
    warnings: list[str] = []
    structure_checks: list[str] = []
    content_checks: list[str] = []
    required = [
        "index.html", "reader.css", "reader.js", "data.js", "reader-data.json",
        "run_manifest.json", "validation-status.js", "run-status.js",
    ]
    for name in required:
        if not (reader_dir / name).is_file():
            errors.append(f"Missing required file: {name}")
    if not tracking_enabled:
        warnings.append(
            "Run tracking is unavailable; stage wall-clock timing and checkpoint history are incomplete"
        )
    try:
        data = json.loads((reader_dir / "reader-data.json").read_text(encoding="utf-8")) if not errors else {}
    except Exception as exc:
        errors.append(f"Invalid reader-data.json: {exc}")
        data = {}

    paper = data.get("paper", {}) if isinstance(data, dict) else {}
    notes = data.get("notes", {}) if isinstance(data, dict) else {}
    translations = data.get("translations", {}) if isinstance(data, dict) else {}
    reader_metadata = data.get("reader", {}) if isinstance(data, dict) else {}
    if reader_metadata.get("skill_name") != SKILL_NAME:
        errors.append("Reader data is missing the expected paper-reader skill identity")
    if reader_metadata.get("skill_version") != SKILL_VERSION:
        errors.append(
            "Reader data skill version mismatch: "
            f"expected {SKILL_VERSION}, found {reader_metadata.get('skill_version')!r}"
        )
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"Reader schema version mismatch: expected {SCHEMA_VERSION}, "
            f"found {data.get('schema_version')!r}"
        )
    if notes.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"Notes schema version mismatch: expected {SCHEMA_VERSION}, "
            f"found {notes.get('schema_version')!r}"
        )
    if translations.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"Translations schema version mismatch: expected {SCHEMA_VERSION}, "
            f"found {translations.get('schema_version')!r}"
        )
    pages = paper.get("pages", []) if isinstance(paper, dict) else []
    note_title = str(notes.get("paper", {}).get("title", "")).strip() if isinstance(notes, dict) else ""
    if not note_title:
        errors.append("Reviewed paper title is missing from notes.paper.title")
    elif note_title.lower() in {"source", "paper", "untitled", "document"}:
        errors.append(f"Reviewed paper title is still a generic placeholder: {note_title!r}")
    note_control_characters = count_c0_strings(notes)
    if note_control_characters:
        errors.append(f"Notes contain {note_control_characters} invisible C0 control character(s)")
    notes_paper = notes.get("paper", {}) if isinstance(notes, dict) else {}
    experimental_data_status = str(notes_paper.get("experimental_data_status", "")).strip()
    if experimental_data_status not in ALLOWED_EXPERIMENTAL_DATA_STATUS:
        errors.append(
            "notes.paper.experimental_data_status must be present, absent, or uncertain"
        )
    page_by_number = {
        int(page.get("number")): page for page in pages
        if isinstance(page, dict) and str(page.get("number", "")).isdigit()
    }
    if not pages:
        errors.append("Paper index contains no pages")
    elif sorted(page_by_number) != list(range(1, len(pages) + 1)):
        errors.append(f"Page numbers are not contiguous: {sorted(page_by_number)}")
    else:
        structure_checks.append(f"contiguous pages: {len(pages)}")

    source_pdf = reader_dir / str(paper.get("source_pdf", ""))
    if not source_pdf.is_file():
        errors.append(f"Packaged source PDF is missing: {paper.get('source_pdf')}")

    image_count = 0
    all_block_ids: dict[int, set[str]] = {}
    all_blocks: dict[int, dict[str, dict[str, Any]]] = {}
    long_runs = 0
    cid_artifacts = 0
    glue_boundaries = 0
    for number, page in page_by_number.items():
        image_path = reader_dir / str(page.get("image", ""))
        if not image_path.is_file():
            errors.append(f"Page {number}: rendered image is missing")
        else:
            try:
                with Image.open(image_path) as image:
                    image.verify()
                image_count += 1
            except Exception as exc:
                errors.append(f"Page {number}: unreadable image: {exc}")
        if float(page.get("width_pt", 0)) <= 0 or float(page.get("height_pt", 0)) <= 0:
            errors.append(f"Page {number}: invalid PDF dimensions")
        block_ids: set[str] = set()
        block_map: dict[str, dict[str, Any]] = {}
        for block in page.get("text_blocks", []):
            block_id = str(block.get("id", ""))
            if not block_id or block_id in block_ids:
                errors.append(f"Page {number}: missing or duplicate text block id {block_id!r}")
            block_ids.add(block_id)
            block_map[block_id] = block
            if block.get("kind") not in {"prose", "heading", "caption", "formula_reference"}:
                errors.append(f"Page {number} block {block_id}: invalid kind {block.get('kind')}")
            if block.get("kind") in {"prose", "heading", "caption"}:
                text = str(block.get("text", ""))
                if block.get("translatable", True) is False:
                    warnings.append(f"Page {number} block {block_id}: readable block is quarantined from translation")
                long_runs += len(LONG_ALPHA_RE.findall(text))
                cid_artifacts += text.count("(cid:")
                glue_boundaries += len(GLUE_RE.findall(text))
                if C0_RE.search(text) or "�" in text:
                    errors.append(f"Page {number} block {block_id}: readable text contains an unresolved glyph")
        all_block_ids[number] = block_ids
        all_blocks[number] = block_map
    if long_runs:
        errors.append(f"Extracted reading text contains {long_runs} alphabetic runs of 30+ characters")
    if cid_artifacts:
        errors.append(f"Extracted reading text contains {cid_artifacts} unresolved (cid:...) artifacts")
    if glue_boundaries:
        message = f"Extracted reading text contains {glue_boundaries} suspicious punctuation/case glue boundaries"
        (errors if args.strict and glue_boundaries > max(5, len(pages)) else warnings).append(message)
    content_checks.append(f"reading-text quality: long-runs={long_runs}, cid={cid_artifacts}, glue={glue_boundaries}")
    recorded_quality = paper.get("text_extraction", {}).get("quality", {})
    if not isinstance(recorded_quality, dict):
        recorded_quality = {}
    quality_pairs = {
        "long_alpha_runs": long_runs,
        "cid_artifacts": cid_artifacts,
        "suspicious_glue_boundaries": glue_boundaries,
    }
    for field, observed in quality_pairs.items():
        recorded = recorded_quality.get(field)
        if recorded != observed:
            errors.append(
                f"Text-quality count mismatch for {field}: index records {recorded!r}, "
                f"validator observed {observed}"
            )
    content_checks.append("text-quality counters cross-checked against packaged paper index")

    formula_candidates = 0
    damaged_formula_candidates = 0
    quarantined_formula_references = 0
    for number, page in page_by_number.items():
        for block in page.get("text_blocks", []):
            if block.get("kind") == "formula_reference" and (
                block.get("source_integrity") == "damaged" or block.get("quality_flags")
            ):
                quarantined_formula_references += 1
        for formula in page.get("formula_blocks", []):
            formula_candidates += 1
            text = str(formula.get("text", ""))
            if (
                formula.get("source_integrity") == "damaged"
                or formula.get("quality_flags")
                or "(cid:" in text
                or C0_RE.search(text)
                or "�" in text
            ):
                damaged_formula_candidates += 1
    if quarantined_formula_references:
        warnings.append(
            f"Quarantined {quarantined_formula_references} damaged formula fragment(s) from translation"
        )
    if damaged_formula_candidates:
        warnings.append(
            f"Automatic formula candidates include {damaged_formula_candidates} damaged item(s); "
            "use source crops and mark selected formulas explicitly"
        )
    recorded_damaged_formula_references = recorded_quality.get("damaged_formula_references")
    if recorded_damaged_formula_references != quarantined_formula_references:
        errors.append(
            "Text-quality count mismatch for damaged_formula_references: "
            f"index records {recorded_damaged_formula_references!r}, "
            f"validator observed {quarantined_formula_references}"
        )
    content_checks.append(
        f"formula safety: candidates={formula_candidates}, damaged={damaged_formula_candidates}, "
        f"quarantined-reading-fragments={quarantined_formula_references}"
    )

    sections = notes.get("paper", {}).get("sections", []) if isinstance(notes, dict) else []
    previous_start = 0
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            errors.append(f"Section {index}: expected an object")
            continue
        start = int(section.get("start_page", 0) or 0)
        end = int(section.get("end_page", 0) or 0)
        if not str(section.get("label", "")).strip():
            errors.append(f"Section {index}: label is missing")
        if start < 1 or end < start or end > len(pages):
            errors.append(f"Section {index}: invalid page range {start}-{end}")
        if start < previous_start:
            errors.append(f"Section {index}: sections are not ordered")
        previous_start = start
        if section.get("candidate"):
            warnings.append(f"Section {index} is still marked as an automatic candidate")

    marker_ids: set[str] = set()
    marker_count = 0
    visual_marker_count = 0
    direct_marker_count = 0
    direct_marker_bound = 0
    experimental_data_marker_count = 0
    covered_visual_ids: set[str] = set()
    notes_pages = notes.get("pages", {}) if isinstance(notes, dict) else {}
    for page_key, page_notes in notes_pages.items():
        try:
            number = int(page_key)
        except ValueError:
            errors.append(f"Notes page key is not numeric: {page_key}")
            continue
        page = page_by_number.get(number)
        if not page:
            errors.append(f"Notes reference missing page {number}")
            continue
        for marker_index, marker in enumerate(page_notes.get("markers", []), start=1):
            marker_count += 1
            prefix = f"Page {number} marker {marker_index}"
            marker_id = str(marker.get("id", "")).strip()
            if not marker_id:
                errors.append(f"{prefix}: id is missing")
            elif marker_id in marker_ids:
                errors.append(f"{prefix}: duplicate id {marker_id}")
            marker_ids.add(marker_id)
            if marker.get("category") not in ALLOWED_CATEGORIES:
                errors.append(f"{prefix}: invalid category {marker.get('category')}")
            if marker.get("claim_status") not in ALLOWED_CLAIMS:
                errors.append(f"{prefix}: invalid claim_status {marker.get('claim_status')}")
            content_type = marker.get("content_type", "text")
            if content_type not in ALLOWED_CONTENT_TYPES:
                errors.append(f"{prefix}: invalid content_type {content_type}")
            for field in ("title", "takeaway", "explanation", "locator"):
                if not str(marker.get(field, "")).strip():
                    errors.append(f"{prefix}: {field} is missing")
            if content_type in {"figure", "table", "formula"} and not first_sentence_identifies_object(
                marker.get("takeaway"), content_type
            ):
                warnings.append(
                    f"{prefix}: takeaway could identify the current {content_type} more explicitly"
                )
            useful_length = explanation_length(marker)
            minimum = 250 if content_type in {"figure", "table"} else 150
            if useful_length < minimum:
                message = f"{prefix}: explanation detail {useful_length} chars is below {minimum}"
                warnings.append(message)
            if marker.get("teaching_priority") == "key":
                teaching_minimum = 800 if content_type in {"figure", "table"} else 500 if content_type == "formula" else 250
                if useful_length < teaching_minimum:
                    warnings.append(
                        f"{prefix}: key teaching explanation detail {useful_length} chars is below {teaching_minimum}"
                    )
            marker_block_ids = marker.get("block_ids", []) if isinstance(marker.get("block_ids"), list) else []
            for block_id in marker_block_ids:
                if block_id not in all_block_ids.get(number, set()):
                    errors.append(f"{prefix}: unknown block_id {block_id}")
            if marker.get("claim_status") == "direct":
                direct_marker_count += 1
                source_text = normalize_evidence(str(marker.get("source_text", "")))
                bound_text = normalize_evidence(" ".join(
                    str(all_blocks[number][block_id].get("text", ""))
                    for block_id in marker_block_ids
                    if block_id in all_blocks.get(number, {})
                ))
                binding_ok = True
                if not marker_block_ids:
                    errors.append(f"{prefix}: direct evidence requires block_ids")
                    binding_ok = False
                if not source_text:
                    errors.append(f"{prefix}: direct evidence requires a verbatim source_text excerpt")
                    binding_ok = False
                elif marker_block_ids and (not bound_text or source_text not in bound_text):
                    errors.append(f"{prefix}: source_text is not a verbatim substring of its bound blocks")
                    binding_ok = False
                if binding_ok:
                    direct_marker_bound += 1
            if content_type in {"figure", "table"}:
                visual_marker_count += 1
                candidate_id = str(marker.get("visual_candidate_id", "")).strip()
                if not candidate_id:
                    errors.append(f"{prefix}: figure/table marker lacks visual_candidate_id")
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
                    message = f"{prefix}: formula_source_status must be verified, damaged, or not_detected"
                    (errors if args.strict else warnings).append(message)
                elif formula_status != "verified" and not marker.get("must_check_source"):
                    errors.append(f"{prefix}: an unverified formula must set must_check_source")
                if marker.get("teaching_priority") == "key" and not marker.get("visual_bbox"):
                    errors.append(f"{prefix}: key formula requires a reviewed visual_bbox source crop")
            experimental_data = marker.get("experimental_data")
            if experimental_data is not None:
                experimental_data_marker_count += 1
                if not isinstance(experimental_data, dict):
                    errors.append(f"{prefix}: experimental_data must be an object")
                else:
                    marker_data_status = str(experimental_data.get("status", "")).strip()
                    if marker_data_status not in ALLOWED_MARKER_EXPERIMENTAL_STATUS:
                        errors.append(f"{prefix}: experimental_data.status must be present or uncertain")
                    origin = str(experimental_data.get("origin", "")).strip()
                    if origin not in ALLOWED_EXPERIMENTAL_ORIGINS:
                        errors.append(
                            f"{prefix}: experimental_data.origin must be author_generated, "
                            "reused_external, mixed, or uncertain"
                        )
                    if not str(experimental_data.get("role", "")).strip():
                        errors.append(f"{prefix}: experimental_data.role is missing")
                    source_hints = experimental_data.get("source_hints")
                    if (
                        not isinstance(source_hints, list)
                        or not source_hints
                        or any(not isinstance(item, str) or not item.strip() for item in source_hints)
                    ):
                        errors.append(
                            f"{prefix}: experimental_data.source_hints requires non-empty strings"
                        )
                    identifiers = experimental_data.get("reported_identifiers")
                    if identifiers is not None and (
                        not isinstance(identifiers, list)
                        or any(not isinstance(item, str) or not item.strip() for item in identifiers)
                    ):
                        errors.append(
                            f"{prefix}: experimental_data.reported_identifiers must contain strings"
                        )
            boxes = boxes_for(marker)
            if not boxes:
                errors.append(f"{prefix}: no source box")
            for box_index, box in enumerate(boxes, start=1):
                try:
                    x0, y0, x1, y1 = (float(box[name]) for name in ("x0", "y0", "x1", "y1"))
                except Exception:
                    errors.append(f"{prefix} box {box_index}: incomplete coordinates")
                    continue
                if not (0 <= x0 < x1 <= float(page["width_pt"])):
                    errors.append(f"{prefix} box {box_index}: x coordinates outside page")
                if not (0 <= y0 < y1 <= float(page["height_pt"])):
                    errors.append(f"{prefix} box {box_index}: y coordinates outside page")

    if experimental_data_status == "absent" and experimental_data_marker_count:
        errors.append(
            "Paper is marked experimental-data absent but marker-level experimental_data entries exist"
        )
    if experimental_data_status == "present" and not experimental_data_marker_count:
        errors.append(
            "Paper is marked experimental-data present but no marker has an experimental_data entry"
        )
    content_checks.append(
        f"experimental-data provenance: paper={experimental_data_status or 'missing'}, "
        f"markers={experimental_data_marker_count}"
    )

    candidate_ids = {
        str(item.get("id")) for item in paper.get("visual_candidates", [])
        if isinstance(item, dict) and item.get("id")
    }
    excluded_items = notes.get("paper", {}).get("excluded_visual_candidates", [])
    excluded_ids: set[str] = set()
    for item in excluded_items if isinstance(excluded_items, list) else []:
        if not isinstance(item, dict) or not str(item.get("id", "")).strip() or not str(item.get("reason", "")).strip():
            errors.append("Each excluded_visual_candidates entry requires id and reason")
            continue
        excluded_ids.add(str(item["id"]))
    unknown_coverage = (covered_visual_ids | excluded_ids) - candidate_ids
    if unknown_coverage:
        errors.append(f"Notes reference unknown visual candidate ids: {sorted(unknown_coverage)}")
    uncovered = candidate_ids - covered_visual_ids - excluded_ids
    if uncovered:
        errors.append(f"Uncovered figure/table candidates: {sorted(uncovered)}")
    content_checks.append(
        f"visual coverage: candidates={len(candidate_ids)}, explained={len(candidate_ids & covered_visual_ids)}, excluded={len(candidate_ids & excluded_ids)}"
    )

    referenced_canonical_ids = {
        str(item.get("canonical_id")) for item in paper.get("visual_references", [])
        if isinstance(item, dict) and item.get("canonical_id")
    }
    candidate_canonical_ids = {
        str(item.get("canonical_id")) for item in paper.get("visual_candidates", [])
        if isinstance(item, dict) and item.get("canonical_id")
    }
    unmatched_references = referenced_canonical_ids - candidate_canonical_ids
    excluded_reference_items = notes.get("paper", {}).get("excluded_visual_references", [])
    excluded_reference_ids: set[str] = set()
    for item in excluded_reference_items if isinstance(excluded_reference_items, list) else []:
        if not isinstance(item, dict) or not str(item.get("canonical_id", "")).strip() or not str(item.get("reason", "")).strip():
            errors.append("Each excluded_visual_references entry requires canonical_id and reason")
            continue
        excluded_reference_ids.add(str(item["canonical_id"]))
    unresolved_references = unmatched_references - excluded_reference_ids
    if unresolved_references:
        errors.append(
            "Figure/table references were found in text but no caption candidate was located: "
            f"{sorted(unresolved_references)}"
        )
    content_checks.append(
        f"visual-reference reconciliation: referenced={len(paper.get('visual_references', []))}, "
        f"unlocated={len(unmatched_references)}, reviewed-exclusions={len(unmatched_references & excluded_reference_ids)}"
    )

    complete_translation_pages = 0
    partial_translation_pages = 0
    for page_key, translation in (translations.get("pages", {}) if isinstance(translations, dict) else {}).items():
        try:
            number = int(page_key)
        except ValueError:
            errors.append(f"Translation page key is not numeric: {page_key}")
            continue
        page = page_by_number.get(number)
        if not page:
            errors.append(f"Translations reference missing page {number}")
            continue
        status = translation.get("status")
        if status not in {"complete", "partial"}:
            errors.append(f"Page {number}: translation status must be complete or partial")
            continue
        translated = translation.get("blocks", {})
        prose_ids = [
            block["id"] for block in page.get("text_blocks", [])
            if block.get("kind") == "prose" and block.get("translatable", True) is not False
        ]
        missing = [block_id for block_id in prose_ids if not str(translated.get(block_id, "")).strip()]
        translated_text = " ".join(str(value) for value in translated.values())
        if "(cid:" in translated_text:
            errors.append(f"Page {number}: translation contains unresolved (cid:...) artifacts")
        if C0_RE.search(translated_text) or "�" in translated_text:
            errors.append(f"Page {number}: translation contains control characters or unresolved glyphs")
        if status == "complete":
            complete_translation_pages += 1
            if missing:
                errors.append(f"Page {number}: marked complete but missing {len(missing)} prose translations")
        else:
            partial_translation_pages += 1
            if not missing:
                warnings.append(f"Page {number}: marked partial although all prose blocks are translated")

    css = (reader_dir / "reader.css").read_text(encoding="utf-8") if (reader_dir / "reader.css").is_file() else ""
    html = (reader_dir / "index.html").read_text(encoding="utf-8") if (reader_dir / "index.html").is_file() else ""
    js = (reader_dir / "reader.js").read_text(encoding="utf-8") if (reader_dir / "reader.js").is_file() else ""
    if not re.search(r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important", css, re.DOTALL):
        errors.append("CSS lacks a non-overridable [hidden] rule")
    heading_rule = re.search(r"\.analysis-block\s+h3\s*\{[^}]*font-weight:\s*(\d+)", css, re.DOTALL)
    if not heading_rule or int(heading_rule.group(1)) < 700:
        errors.append("Analysis subheadings are not explicitly bold enough")
    for element_id in (
        "readingViewMode", "figureViewMode", "formulaViewMode", "originalMode", "bilingualMode",
        "pageImage", "markerLayer", "bilingualView", "analysisContent", "explainerWorkspace",
        "explainerNavigation", "explainerSourceCanvas", "explainerContent", "questionWhole",
        "experimentalDataAction",
        "analysisPanel", "backToPage", "questionToggle", "questionComposer", "questionInput",
        "verificationSummary", "runMetrics", "markerMasterToggle", "pageScroller",
    ):
        if f'id="{element_id}"' not in html:
            errors.append(f"Reader HTML is missing required element #{element_id}")
    if re.search(r"aria-label=\"阅读模式\"\s+hidden", html):
        errors.append("Reading mode controls are hidden in the template")
    if "replicate，而不是单帧" in html:
        errors.append("Reader still contains the paper-specific demo question placeholder")
    for behavior in (
        "sendFollowUpMessage", "drawSourceCrop", "renderMarkers", "renderVisualCards",
        "clearMarkerSelection", "backToPage", "analysisPanel.scrollTop", "pageScroller.scrollLeft",
        "preparedQuestion", "renderVerificationSummary", "renderExplainerNavigation", "buildTeachingSections",
        "openExplainerItemInReading", "openReadingAt", "createSourceBody", "source-actions",
        "renderRunMetrics", "toggleAllMarkers", "currentExplanation", "证据状态",
        "生成概况", "warning_count", "结构验证通过", "需核对",
        "experimentalDataInfo", "openExperimentalDataComposer", "experimental-data-source",
        "只追踪支撑当前项目的实验测量数据",
    ):
        if behavior not in js:
            errors.append(f"Reader JavaScript is missing behavior: {behavior}")
    if 'mode: "bilingual"' in js or 'setMode("bilingual")' in js.split("initialize();")[0][-300:]:
        warnings.append("Review default-mode logic; a hard-coded bilingual default may remain")
    if "30 秒结论" in html or "30 秒结论" in js:
        errors.append("Reader still uses the rejected countdown-style takeaway label")
    if "本次生成记录" in html or "本次生成记录" in js:
        errors.append("Reader still uses the rejected phase-detail build-record label")
    if "objectHeading(" in js or "objectLabel(" in js:
        errors.append("Reader still appends source-object labels to recurring section headings")
    if "::visualization" in html or "::visualization" in js:
        errors.append("Reader depends on an app-specific visualization directive")
    if "horizontalPan" in html or "horizontalPan" in js:
        errors.append("Reader still includes the rejected custom horizontal-pan control")
    if "max-height: min(62vh" not in css or ".source-crop-canvas.crop-tall" not in css:
        errors.append("Reader lacks aspect-safe height constraints for tall source crops")
    question_rule = re.search(r"\.question-action\s*\{[^}]*background:\s*([^;]+)", css, re.DOTALL)
    if not question_rule or "transparent" in question_rule.group(1) or "#fff" in question_rule.group(1).lower():
        errors.append("Context question actions do not have a visible filled tint")
    data_action_rule = re.search(
        r"\.experimental-data-action\s*\{[^}]*background:\s*([^;]+)", css, re.DOTALL
    )
    if not data_action_rule or "transparent" in data_action_rule.group(1) or "#fff" in data_action_rule.group(1).lower():
        errors.append("Experimental-data action does not have a distinct filled tint")

    try:
        manifest = json.loads((reader_dir / "run_manifest.json").read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"Invalid run_manifest.json: {exc}")
        manifest = {}
    generator = manifest.get("generator", {}) if isinstance(manifest, dict) else {}
    if not isinstance(generator, dict):
        generator = {}
    expected_versions = {
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "builder_version": BUILDER_VERSION,
    }
    for field, expected in expected_versions.items():
        if generator.get(field) != expected:
            errors.append(
                f"run_manifest generator {field} mismatch: expected {expected!r}, "
                f"found {generator.get(field)!r}"
            )
    manifest_quality = manifest.get("text_quality_at_build", {}) if isinstance(manifest, dict) else {}
    if manifest_quality != recorded_quality:
        errors.append(
            "run_manifest text_quality_at_build does not match the packaged paper index"
        )
    for name, item in (manifest.get("inputs", {}) if isinstance(manifest, dict) else {}).items():
        if not isinstance(item, dict):
            continue
        if "path" in item:
            errors.append(f"run_manifest input {name} exposes a filesystem path")
        value = str(item.get("name", ""))
        if value and (Path(value).is_absolute() or "\\" in value or "/" in value):
            errors.append(f"run_manifest input {name} must contain only a file name")

    eligible_teaching_markers = [
        marker
        for page in notes.get("pages", {}).values()
        if isinstance(page, dict)
        for marker in page.get("markers", [])
        if isinstance(marker, dict) and marker.get("content_type") in {"figure", "table", "formula"}
    ]
    if eligible_teaching_markers:
        audit_path = reader_dir / "teaching-audit-report.json"
        if not audit_path.is_file():
            errors.append("Reader with figures/tables/formulas lacks teaching-audit-report.json")
        else:
            try:
                teaching_audit = json.loads(audit_path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"Invalid teaching-audit-report.json: {exc}")
                teaching_audit = {}
            current_teaching_hash = teaching_notes_sha256(notes)
            if teaching_audit.get("audit_schema_version") != AUDIT_SCHEMA_VERSION:
                errors.append("Packaged teaching audit uses a different audit schema")
            if teaching_audit.get("status") != "pass":
                errors.append("Packaged teaching audit report is not passing")
            if teaching_audit.get("teaching_notes_sha256") != current_teaching_hash:
                errors.append("Packaged notes changed after the teaching audit")
            audit_manifest = manifest.get("teaching_audit", {}) if isinstance(manifest, dict) else {}
            if not isinstance(audit_manifest, dict) or audit_manifest.get("status") != "pass":
                errors.append("run_manifest does not record a passing teaching audit")
            elif audit_manifest.get("audit_schema_version") != AUDIT_SCHEMA_VERSION:
                errors.append("run_manifest teaching-audit schema does not match the validator")
            elif audit_manifest.get("teaching_notes_sha256") != current_teaching_hash:
                errors.append("run_manifest teaching-audit hash does not match packaged notes")
            else:
                content_checks.append(
                    "teaching self-audit: completed and hash-bound; scientific correctness remains unproven"
                )

    source_alignment_status = (
        "pass" if direct_marker_count > 0 and direct_marker_bound == direct_marker_count else "fail"
    )
    validation_layers = {
        "structure": "pass" if not errors else "fail",
        "source_alignment": source_alignment_status,
        "scientific_correctness": "not_proven_by_validator",
        "external_materials": "not_required_unless_user_supplies_or_requests",
    }

    report = {
        "schema_version": SCHEMA_VERSION,
        "validator": {
            "skill_name": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "validator_version": VALIDATOR_VERSION,
        },
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "strict": bool(args.strict),
        "status": "pass" if not errors else "fail",
        "coverage": {
            "pages": len(pages), "page_images_readable": image_count, "sections": len(sections),
            "markers": marker_count, "visual_markers": visual_marker_count,
            "experimental_data_markers": experimental_data_marker_count,
            "visual_candidates": len(candidate_ids), "visual_candidates_covered": len(candidate_ids & covered_visual_ids),
            "visual_candidates_excluded": len(candidate_ids & excluded_ids),
            "translation_complete_pages": complete_translation_pages,
            "translation_partial_pages": partial_translation_pages,
            "formula_suspect_blocks": paper.get("formula_suspect_count", 0),
            "formula_damaged_blocks": damaged_formula_candidates,
            "formula_candidate_priorities": paper.get("formula_candidate_priorities", {}),
            "direct_markers": direct_marker_count,
            "direct_markers_bound": direct_marker_bound,
            "visual_references": len(paper.get("visual_references", [])),
            "unmatched_visual_references": len(unmatched_references),
        },
        "validation_layers": validation_layers,
        "structure_checks": structure_checks,
        "content_checks": content_checks,
        "errors": errors,
        "warnings": warnings,
        "manual_checks_still_required": [
            "browser interaction at desktop and narrow viewport",
            "all numbered figure/table crops and explanations",
            "representative formula fidelity",
            "scientific interpretation beyond structural and source-alignment checks",
        ],
    }
    reader_dir.mkdir(parents=True, exist_ok=True)
    (reader_dir / "validation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    status_payload = {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "validator_version": VALIDATOR_VERSION,
        **validation_layers,
        "direct_markers": direct_marker_count,
        "direct_markers_bound": direct_marker_bound,
        "experimental_data_markers": experimental_data_marker_count,
        "warning_count": len(warnings),
    }
    (reader_dir / "validation-status.js").write_text(
        "window.PAPER_READER_VALIDATION="
        + json.dumps(status_payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    tracked_state = None
    if tracking_enabled:
        finish_stage(
            reader_dir,
            "validation",
            status="completed" if not errors else "failed",
            errors=len(errors),
            warnings=len(warnings),
        )
        tracked_state = load_state(reader_dir)
    if isinstance(manifest, dict):
        validation_seconds = (
            stage_elapsed(tracked_state, "validation")
            if tracked_state
            else round(time.perf_counter() - started, 3)
        )
        manifest.setdefault("timings_seconds", {})["validation"] = validation_seconds
        if tracked_state:
            manifest["run_tracking"] = {
                "enabled": True,
                "state_file": STATE_NAME,
                "events_file": "run-events.jsonl",
                "timing_semantics": "stage wall-clock time; may include waiting or reconnection gaps",
                "run_context": tracked_state.get("run_context", {}),
                "stages": tracked_state.get("stages", {}),
                "milestones": tracked_state.get("milestones", {}),
                "diagnostics": diagnostic_summary(tracked_state),
            }
        manifest["validation"] = {
            "validator_version": VALIDATOR_VERSION,
            "skill_version": SKILL_VERSION,
            "status": report["status"],
            "errors": len(errors),
            "warnings": len(warnings),
            "text_quality": {
                "long_alpha_runs": long_runs,
                "cid_artifacts": cid_artifacts,
                "suspicious_glue_boundaries": glue_boundaries,
            },
        }
        (reader_dir / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (reader_dir / "run-status.js").write_text(
            "window.PAPER_READER_RUN="
            + json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
            + ";\n",
            encoding="utf-8",
        )
        write_build_report(reader_dir)
    print(f"Validation {report['status']}: {len(errors)} error(s), {len(warnings)} warning(s)")
    print(f"Report: {reader_dir / 'validation-report.json'}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
