#!/usr/bin/env python3
"""Package a paper index, notes, translations, and the fixed reader UI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from run_tracker import (
    EVENTS_NAME,
    STATE_NAME,
    diagnostic_summary,
    finish_stage,
    load_state,
    stage_elapsed,
    start_stage,
)
from teaching_audit import AUDIT_SCHEMA_VERSION, teaching_notes_sha256
from version_info import BUILDER_VERSION, SCHEMA_VERSION, SKILL_NAME, SKILL_VERSION


OUTPUT_TITLE_LIMIT = 72


def load_object(path: Path, *, optional: bool = False) -> dict:
    if optional and not path.is_file():
        return {}
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_title_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    slug = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-_")
    slug = re.sub(r"[-_]{2,}", "-", slug)
    if len(slug) > OUTPUT_TITLE_LIMIT:
        slug = slug[:OUTPUT_TITLE_LIMIT].rstrip("-_")
    return slug or "paper"


def default_output_dir(output_root: Path, paper: dict, notes: dict, source_pdf: Path) -> Path:
    metadata = paper.get("metadata", {}) if isinstance(paper.get("metadata"), dict) else {}
    metadata_title = str(metadata.get("title", "")).strip()
    reviewed_title = str(notes.get("paper", {}).get("title", "")).strip()
    generic_titles = {"", "source", "paper", "untitled", "document"}
    title = (
        reviewed_title
        if metadata_title.casefold() in generic_titles and reviewed_title
        else metadata_title or reviewed_title or source_pdf.stem
    )
    return output_root / f"{safe_title_slug(title)}-paper-reader-v{SKILL_VERSION}"


def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-index", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--translations", help="Optional translations JSON")
    parser.add_argument(
        "--teaching-audit-report",
        help="Passing report from teaching_audit.py check; required for new full builds with figures/tables/formulas",
    )
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--out-dir", help="Exact reader directory (backward compatible)")
    destination.add_argument(
        "--output-root",
        help="Parent directory; creates <paper-title>-paper-reader-v<skill-version>",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--run-dir", help="Optional initialized run-tracking directory")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else None
    if run_dir:
        start_stage(run_dir, "build")

    index_path = Path(args.paper_index).resolve()
    notes_path = Path(args.notes).resolve()
    translations_path = Path(args.translations).resolve() if args.translations else None
    teaching_audit_path = (
        Path(args.teaching_audit_report).resolve() if args.teaching_audit_report else None
    )
    if teaching_audit_path is None and args.out_dir:
        existing_audit = Path(args.out_dir).resolve() / "teaching-audit-report.json"
        if existing_audit.is_file():
            teaching_audit_path = existing_audit
    paper = load_object(index_path)
    notes = load_object(notes_path)
    eligible_teaching_markers = [
        marker
        for page in notes.get("pages", {}).values()
        if isinstance(page, dict)
        for marker in page.get("markers", [])
        if isinstance(marker, dict) and marker.get("content_type") in {"figure", "table", "formula"}
    ]
    if args.output_root and eligible_teaching_markers and not teaching_audit_path:
        raise SystemExit(
            "A new full build containing figures/tables/formulas requires --teaching-audit-report"
        )
    teaching_audit = load_object(teaching_audit_path) if teaching_audit_path else None
    if teaching_audit is not None:
        if teaching_audit.get("audit_schema_version") != AUDIT_SCHEMA_VERSION:
            raise SystemExit("Teaching audit report belongs to a different audit schema")
        if teaching_audit.get("status") != "pass":
            raise SystemExit("Teaching audit report is not passing")
        expected_teaching_hash = teaching_notes_sha256(notes)
        if teaching_audit.get("teaching_notes_sha256") != expected_teaching_hash:
            raise SystemExit(
                "Teaching content changed after the teaching audit; rerun teaching_audit.py check"
            )
        audit_generator = teaching_audit.get("generator", {})
        if not isinstance(audit_generator, dict) or audit_generator.get("skill_version") != SKILL_VERSION:
            raise SystemExit("Teaching audit report belongs to a different Skill version")
    translations = (
        load_object(translations_path, optional=True)
        if translations_path
        else {"schema_version": SCHEMA_VERSION, "language": "zh-CN", "pages": {}}
    )
    translations["schema_version"] = SCHEMA_VERSION
    translations.setdefault("language", "zh-CN")
    translations.setdefault("pages", {})

    source_pdf = Path(str(paper.get("source_pdf", ""))).resolve()
    if not source_pdf.is_file():
        raise SystemExit(f"Source PDF recorded in paper index is missing: {source_pdf}")
    out_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else default_output_dir(Path(args.output_root).resolve(), paper, notes, source_pdf)
    )
    if (out_dir / "index.html").exists() and not args.force:
        raise SystemExit(f"Reader already exists: {out_dir}; use --force to update known files")

    template_dir = Path(__file__).resolve().parents[1] / "assets" / "reader"
    for name in ("index.html", "reader.css", "reader.js"):
        if not (template_dir / name).is_file():
            raise SystemExit(f"Missing reader template asset: {template_dir / name}")

    out_dir.mkdir(parents=True, exist_ok=True)
    page_out = out_dir / "assets" / "pages"
    page_out.mkdir(parents=True, exist_ok=True)
    source_out = out_dir / "assets" / "source.pdf"
    shutil.copy2(source_pdf, source_out)

    packaged_paper = json.loads(json.dumps(paper))
    for page in packaged_paper.get("pages", []):
        source_image = index_path.parent / str(page.get("image", ""))
        if not source_image.is_file():
            raise SystemExit(f"Missing rendered page image: {source_image}")
        target = page_out / source_image.name
        shutil.copy2(source_image, target)
        page["image"] = f"assets/pages/{target.name}"
    packaged_paper["source_pdf"] = "assets/source.pdf"

    data = {
        "schema_version": SCHEMA_VERSION,
        "paper": packaged_paper,
        "notes": notes,
        "translations": translations,
        "reader": {
            "skill_name": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "default_view": "reading",
            "default_language": "original",
            "single_page_only": True,
            "teaching_views": ["figures", "formulas"],
            "bilingual_behavior": "cached-translations-only",
            "question_host": "contextual-codex-follow-up-with-clipboard-fallback",
            "verification_scope": "local-source-structure-and-traceability",
        },
    }

    for name in ("reader.css", "reader.js"):
        shutil.copy2(template_dir / name, out_dir / name)
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    data_script = f"window.PAPER_READER_DATA={serialized};\n"
    (out_dir / "data.js").write_text(data_script, encoding="utf-8")
    asset_versions = {
        "reader.css": sha256(template_dir / "reader.css")[:12],
        "reader.js": sha256(template_dir / "reader.js")[:12],
        "data.js": hashlib.sha256(data_script.encode("utf-8")).hexdigest()[:12],
    }
    html = (template_dir / "index.html").read_text(encoding="utf-8")
    for asset_name, version in asset_versions.items():
        html = html.replace(asset_name, f"{asset_name}?v={version}")
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "reader-data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if teaching_audit_path:
        packaged_audit = out_dir / "teaching-audit-report.json"
        if teaching_audit_path != packaged_audit.resolve():
            shutil.copy2(teaching_audit_path, packaged_audit)
    pending_validation = {
        "schema_version": SCHEMA_VERSION,
        "structure": "pending",
        "source_alignment": "pending",
        "scientific_correctness": "not_proven_by_validator",
    }
    (out_dir / "validation-status.js").write_text(
        "window.PAPER_READER_VALIDATION="
        + json.dumps(pending_validation, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )

    complete_pages = 0
    partial_pages = 0
    for item in translations.get("pages", {}).values():
        if not isinstance(item, dict):
            continue
        if item.get("status") == "complete":
            complete_pages += 1
        elif item.get("status") == "partial":
            partial_pages += 1
    marker_count = sum(
        len(page.get("markers", []))
        for page in notes.get("pages", {}).values()
        if isinstance(page, dict)
    )
    all_markers = [
        marker
        for page in notes.get("pages", {}).values()
        if isinstance(page, dict)
        for marker in page.get("markers", [])
        if isinstance(marker, dict)
    ]
    figure_table_markers = sum(
        1 for marker in all_markers if marker.get("content_type") in {"figure", "table"}
    )
    formula_markers = sum(1 for marker in all_markers if marker.get("content_type") == "formula")
    visual_candidates = packaged_paper.get("visual_candidates", [])
    visual_candidate_ids = {
        str(item.get("id")) for item in visual_candidates if isinstance(item, dict) and item.get("id")
    }
    covered_visual_ids = {
        str(marker.get("visual_candidate_id"))
        for page in notes.get("pages", {}).values()
        if isinstance(page, dict)
        for marker in page.get("markers", [])
        if isinstance(marker, dict) and marker.get("visual_candidate_id")
    }
    excluded_visual_ids = {
        str(item.get("id"))
        for item in notes.get("paper", {}).get("excluded_visual_candidates", [])
        if isinstance(item, dict) and item.get("id") and str(item.get("reason", "")).strip()
    }
    run_metrics = notes.get("paper", {}).get("run_metrics", {})
    if not isinstance(run_metrics, dict):
        run_metrics = {}
    tracked_state = None
    if run_dir:
        finish_stage(run_dir, "build")
        tracked_state = load_state(run_dir)
        for name in (STATE_NAME, EVENTS_NAME):
            source = run_dir / name
            if source.is_file():
                shutil.copy2(source, out_dir / name)
    context_indexing_seconds = (
        stage_elapsed(tracked_state, "context_indexing")
        if tracked_state
        else run_metrics.get("context_indexing_seconds")
    )
    content_analysis_seconds = (
        stage_elapsed(tracked_state, "content_analysis")
        if tracked_state
        else run_metrics.get("content_analysis_seconds")
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator": {
            "skill_name": SKILL_NAME,
            "skill_version": SKILL_VERSION,
            "builder_version": BUILDER_VERSION,
        },
        "built_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "paper_index": {"name": index_path.name, "sha256": sha256(index_path)},
            "notes": {"name": notes_path.name, "sha256": sha256(notes_path)},
            "translations": (
                {"name": translations_path.name, "sha256": sha256(translations_path)}
                if translations_path and translations_path.is_file()
                else None
            ),
            "teaching_audit_report": (
                {"name": teaching_audit_path.name, "sha256": sha256(teaching_audit_path)}
                if teaching_audit_path
                else None
            ),
            "source_pdf": {"name": source_pdf.name, "sha256": sha256(source_pdf)},
        },
        "coverage": {
            "pages": len(packaged_paper.get("pages", [])),
            "markers": marker_count,
            "figure_table_markers": figure_table_markers,
            "formula_markers": formula_markers,
            "translation_complete_pages": complete_pages,
            "translation_partial_pages": partial_pages,
            "formula_suspect_blocks": packaged_paper.get("formula_suspect_count", 0),
            "formula_damaged_blocks": packaged_paper.get("formula_damaged_count", 0),
            "formula_candidate_priorities": packaged_paper.get("formula_candidate_priorities", {}),
            "visual_candidates": len(visual_candidate_ids),
            "visual_candidates_covered": len(visual_candidate_ids & covered_visual_ids),
            "visual_candidates_excluded": len(visual_candidate_ids & excluded_visual_ids),
            "visual_references": len(packaged_paper.get("visual_references", [])),
            "unmatched_visual_references": len(packaged_paper.get("unmatched_visual_references", [])),
        },
        "text_quality_at_build": packaged_paper.get("text_extraction", {}).get("quality", {}),
        "teaching_audit": (
            {
                "audit_schema_version": teaching_audit.get("audit_schema_version"),
                "status": teaching_audit.get("status"),
                "scope": teaching_audit.get("scope"),
                "teaching_notes_sha256": teaching_audit.get("teaching_notes_sha256"),
                "coverage": teaching_audit.get("coverage", {}),
                "warnings": len(teaching_audit.get("warnings", [])),
            }
            if teaching_audit
            else {"status": "not_required_for_existing-reader_update"}
        ),
        "timings_seconds": {
            "pdf_parse_and_render": paper.get("elapsed_seconds"),
            "context_indexing": context_indexing_seconds,
            "content_analysis": content_analysis_seconds,
            "packaging": round(time.perf_counter() - started, 3),
            "validation": None,
        },
        "run_tracking": (
            {
                "enabled": True,
                "state_file": STATE_NAME,
                "events_file": EVENTS_NAME,
                "timing_semantics": "stage wall-clock time; may include waiting or reconnection gaps",
                "run_context": tracked_state.get("run_context", {}),
                "stages": tracked_state.get("stages", {}),
                "milestones": tracked_state.get("milestones", {}),
                "diagnostics": diagnostic_summary(tracked_state),
            }
            if tracked_state
            else {
                "enabled": False,
                "timing_semantics": "only script-local timings are available",
            }
        ),
        "model_usage": {
            "calls": None,
            "input_tokens": None,
            "output_tokens": None,
            "image_calls": 0,
            "subagents": 0,
        },
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "run-status.js").write_text(
        "window.PAPER_READER_RUN="
        + json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print(f"Built paper reader with {manifest['coverage']['pages']} pages at {out_dir}")
    print(f"OUTPUT_DIR={out_dir}")
    print(f"Markers: {marker_count}; complete bilingual pages: {complete_pages}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
