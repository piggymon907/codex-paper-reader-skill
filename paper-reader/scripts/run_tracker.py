#!/usr/bin/env python3
"""Record auditable wall-clock stages, checkpoints, and manual QA results."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from version_info import SCHEMA_VERSION, SKILL_NAME, SKILL_VERSION


STATE_SCHEMA = "1.1"
STATE_NAME = "run-state.json"
EVENTS_NAME = "run-events.jsonl"
QA_REPORT_NAME = "qa-report.json"
BUILD_REPORT_NAME = "build_report.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def append_event(work_dir: Path, payload: dict[str, Any]) -> None:
    event = {
        "timestamp": utc_now(),
        "skill_version": SKILL_VERSION,
        "schema_version": SCHEMA_VERSION,
        **payload,
    }
    work_dir.mkdir(parents=True, exist_ok=True)
    with (work_dir / EVENTS_NAME).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def state_path(work_dir: Path) -> Path:
    return work_dir / STATE_NAME


def load_state(work_dir: Path) -> dict[str, Any]:
    path = state_path(work_dir)
    if not path.is_file():
        raise FileNotFoundError(
            f"Run state not found: {path}. Initialize it before starting tracked stages."
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Run state must be a JSON object: {path}")
    if value.get("skill_version") != SKILL_VERSION or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            "Run state belongs to a different Skill/schema release; use a new work directory."
        )
    return value


def save_state(work_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    atomic_json(state_path(work_dir), state)


def normalize_run_context(value: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a bounded run-context record without inventing unavailable values."""
    value = value or {}
    return {
        "model": str(value["model"]).strip()[:120] if value.get("model") else None,
        "reasoning_effort": (
            str(value["reasoning_effort"]).strip()[:40]
            if value.get("reasoning_effort")
            else None
        ),
        "fast_mode": value.get("fast_mode"),
        "translation_scope": (
            str(value["translation_scope"]).strip()[:120]
            if value.get("translation_scope")
            else None
        ),
        "reuse_mode": value.get("reuse_mode"),
    }


def update_run_context(work_dir: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Record known execution conditions; null fields remain explicitly unknown."""
    state = load_state(work_dir)
    context = normalize_run_context(value)
    recorded_at = utc_now()
    state["run_context"] = context
    state.setdefault("run_context_history", []).append(
        {"recorded_at": recorded_at, **context}
    )
    save_state(work_dir, state)
    append_event(work_dir, {"event": "run_context_recorded", "run_context": context})
    return context


def init_run(
    work_dir: Path,
    input_path: Path,
    run_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    fingerprint = {"name": input_path.name, "sha256": sha256_file(input_path)}
    path = state_path(work_dir)
    if path.is_file():
        state = load_state(work_dir)
        if state.get("input") != fingerprint:
            raise ValueError(
                "Input hash changed. Keep the existing run intact and start a new work directory."
            )
        if run_context and any(value is not None for value in run_context.values()):
            update_run_context(work_dir, run_context)
            state = load_state(work_dir)
        append_event(work_dir, {"event": "run_resumed"})
        return state, True
    now = utc_now()
    state = {
        "state_schema": STATE_SCHEMA,
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "input": fingerprint,
        "created_at": now,
        "updated_at": now,
        "stages": {},
        "checkpoints": {},
        "milestones": {},
        "run_context": normalize_run_context(run_context),
        "run_context_history": [],
    }
    state["run_context_history"].append(
        {"recorded_at": now, **state["run_context"]}
    )
    save_state(work_dir, state)
    append_event(
        work_dir,
        {
            "event": "run_initialized",
            "input": fingerprint,
            "run_context": state["run_context"],
        },
    )
    return state, False


def record_milestone(
    work_dir: Path,
    name: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a lightweight wall-clock milestone to state and the event log."""
    name = str(name).strip()
    if not name or len(name) > 80:
        raise ValueError("Milestone name must contain 1-80 characters")
    state = load_state(work_dir)
    record: dict[str, Any] = {"timestamp": utc_now()}
    if details:
        record["details"] = details
    state.setdefault("milestones", {}).setdefault(name, []).append(record)
    save_state(work_dir, state)
    append_event(
        work_dir,
        {"event": "milestone_recorded", "milestone": name, **record},
    )
    return record


def start_stage(work_dir: Path, stage: str) -> dict[str, Any]:
    state = load_state(work_dir)
    stages = state.setdefault("stages", {})
    current = stages.get(stage)
    if isinstance(current, dict) and current.get("status") == "running":
        resumed_at = utc_now()
        prior_attempt = int(current.get("attempt", 1))
        prior_duration = max(
            0.0,
            (parse_time(resumed_at) - parse_time(current["started_at"])).total_seconds(),
        )
        attempts = list(current.get("attempts", []))
        if attempts:
            attempts[-1].update(
                {
                    "finished_at": resumed_at,
                    "elapsed_seconds": round(prior_duration, 3),
                    "status": "interrupted",
                }
            )
        attempt = prior_attempt + 1
        attempts.append({"attempt": attempt, "started_at": resumed_at, "status": "running"})
        current.update(
            {
                "status": "running",
                "attempt": attempt,
                "started_at": resumed_at,
                "finished_at": None,
                "elapsed_seconds": round(
                    sum(float(item.get("elapsed_seconds", 0) or 0) for item in attempts), 3
                ),
                "attempts": attempts,
            }
        )
        save_state(work_dir, state)
        append_event(
            work_dir,
            {
                "event": "stage_resumed",
                "stage": stage,
                "attempt": attempt,
                "prior_attempt": prior_attempt,
                "prior_attempt_status": "interrupted",
            },
        )
        return current
    attempt = int(current.get("attempt", 0)) + 1 if isinstance(current, dict) else 1
    started_at = utc_now()
    attempts = list(current.get("attempts", [])) if isinstance(current, dict) else []
    attempts.append({"attempt": attempt, "started_at": started_at, "status": "running"})
    stages[stage] = {
        "status": "running",
        "attempt": attempt,
        "started_at": started_at,
        "finished_at": None,
        "elapsed_seconds": None,
        "error_count": 0,
        "warning_count": 0,
        "attempts": attempts,
    }
    save_state(work_dir, state)
    append_event(work_dir, {"event": "stage_started", "stage": stage, "attempt": attempt})
    return stages[stage]


def finish_stage(
    work_dir: Path,
    stage: str,
    *,
    status: str = "completed",
    errors: int = 0,
    warnings: int = 0,
    note: str | None = None,
) -> dict[str, Any]:
    if status not in {"completed", "failed", "interrupted"}:
        raise ValueError(f"Unsupported stage status: {status}")
    state = load_state(work_dir)
    current = state.setdefault("stages", {}).get(stage)
    if not isinstance(current, dict) or current.get("status") != "running":
        current = start_stage(work_dir, stage)
        state = load_state(work_dir)
        current = state["stages"][stage]
    finished_at = utc_now()
    duration = max(0.0, (parse_time(finished_at) - parse_time(current["started_at"])).total_seconds())
    current.update(
        {
            "status": status,
            "finished_at": finished_at,
            "error_count": int(errors),
            "warning_count": int(warnings),
        }
    )
    if note:
        current["note"] = str(note)[:500]
    attempts = current.get("attempts", [])
    if attempts:
        attempts[-1].update(
            {
                "finished_at": finished_at,
                "elapsed_seconds": round(duration, 3),
                "status": status,
                "error_count": int(errors),
                "warning_count": int(warnings),
            }
        )
    current["elapsed_seconds"] = round(
        sum(
            float(item.get("elapsed_seconds", 0) or 0)
            for item in attempts
            if isinstance(item, dict)
        ),
        3,
    )
    save_state(work_dir, state)
    event: dict[str, Any] = {
        "event": "stage_finished",
        "stage": stage,
        "attempt": current.get("attempt", 1),
        "status": status,
        "elapsed_seconds": round(duration, 3),
        "errors": int(errors),
        "warnings": int(warnings),
    }
    if note:
        event["note"] = str(note)[:500]
    append_event(work_dir, event)
    return current


def finish_stage_if_running(
    work_dir: Path,
    stage: str,
    *,
    status: str = "completed",
    errors: int = 0,
    warnings: int = 0,
    note: str | None = None,
) -> dict[str, Any] | None:
    """Finish only an active stage, avoiding phantom attempts on repeated scripts."""
    state = load_state(work_dir)
    current = state.get("stages", {}).get(stage)
    if not isinstance(current, dict) or current.get("status") != "running":
        return None
    return finish_stage(
        work_dir,
        stage,
        status=status,
        errors=errors,
        warnings=warnings,
        note=note,
    )


def ensure_stage_running(work_dir: Path, stage: str) -> dict[str, Any]:
    """Start a stage only when it is not already active."""
    state = load_state(work_dir)
    current = state.get("stages", {}).get(stage)
    if isinstance(current, dict) and current.get("status") == "running":
        return current
    return start_stage(work_dir, stage)


def checkpoint(
    work_dir: Path, stage: str, item_ids: list[str], artifact: Path | None = None
) -> None:
    state = load_state(work_dir)
    artifact_info: dict[str, Any] | None = None
    if artifact:
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        artifact_info = {"name": artifact.name, "sha256": sha256_file(artifact)}
    stage_items = state.setdefault("checkpoints", {}).setdefault(stage, {})
    now = utc_now()
    for item_id in item_ids:
        stage_items[item_id] = {
            "status": "completed",
            "updated_at": now,
            "artifact": artifact_info,
        }
    save_state(work_dir, state)
    append_event(
        work_dir,
        {
            "event": "checkpoint_saved",
            "stage": stage,
            "items": item_ids,
            "artifact": artifact_info,
        },
    )


def stage_elapsed(state: dict[str, Any], stage: str) -> float | None:
    item = state.get("stages", {}).get(stage, {})
    if not isinstance(item, dict) or item.get("status") != "completed":
        return None
    value = item.get("elapsed_seconds")
    return round(float(value), 3) if isinstance(value, (int, float)) else None


def _first_stage_time(state: dict[str, Any], stage: str, field: str) -> str | None:
    item = state.get("stages", {}).get(stage, {})
    attempts = item.get("attempts", []) if isinstance(item, dict) else []
    for attempt in attempts:
        if isinstance(attempt, dict) and attempt.get(field):
            return str(attempt[field])
    return None


def _last_stage_time(state: dict[str, Any], stage: str, field: str) -> str | None:
    item = state.get("stages", {}).get(stage, {})
    attempts = item.get("attempts", []) if isinstance(item, dict) else []
    for attempt in reversed(attempts):
        if isinstance(attempt, dict) and attempt.get(field):
            return str(attempt[field])
    return None


def _milestone_time(state: dict[str, Any], name: str, *, last: bool = False) -> str | None:
    records = state.get("milestones", {}).get(name, [])
    if not isinstance(records, list):
        return None
    ordered = reversed(records) if last else iter(records)
    for record in ordered:
        if isinstance(record, dict) and record.get("timestamp"):
            return str(record["timestamp"])
    return None


def _elapsed_between(start: str | None, finish: str | None) -> float | None:
    if not start or not finish:
        return None
    return round(max(0.0, (parse_time(finish) - parse_time(start)).total_seconds()), 3)


def diagnostic_summary(state: dict[str, Any]) -> dict[str, Any]:
    """Derive non-overlapping content milestones without claiming model compute time."""
    content_start = _first_stage_time(state, "content_analysis", "started_at")
    content_finish = _last_stage_time(state, "content_analysis", "finished_at")
    audit_initialized = _milestone_time(state, "audit_skeleton_initialized")
    draft_ready = _milestone_time(state, "teaching_draft_ready")
    audit_checked = _milestone_time(state, "teaching_audit_checked", last=True)
    binding_ready = _milestone_time(state, "analysis_ready_for_binding", last=True)
    revision = state.get("stages", {}).get("targeted_revision", {})
    revision_attempts = revision.get("attempts", []) if isinstance(revision, dict) else []
    return {
        "timing_semantics": (
            "derived wall-clock intervals; may include tool waits, pauses, or reconnect gaps"
        ),
        "content_analysis_segments_seconds": {
            "inventory_and_audit_setup": _elapsed_between(content_start, audit_initialized),
            "classification_drafting_and_embedded_review": _elapsed_between(
                audit_initialized, draft_ready
            ),
            "post_audit_finalization": _elapsed_between(
                audit_checked, binding_ready or content_finish
            ),
        },
        "targeted_revision": {
            "elapsed_seconds": stage_elapsed(state, "targeted_revision"),
            "attempts": len(revision_attempts),
        },
    }


def write_build_report(reader_dir: Path) -> Path:
    """Create a deterministic delivery report from machine-readable build artifacts."""
    manifest_path = reader_dir / "run_manifest.json"
    validation_path = reader_dir / "validation-report.json"
    if not manifest_path.is_file() or not validation_path.is_file():
        raise FileNotFoundError("run_manifest.json and validation-report.json are required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    qa_path = reader_dir / QA_REPORT_NAME
    qa = json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.is_file() else None
    coverage = validation.get("coverage", {}) if isinstance(validation, dict) else {}
    warnings = validation.get("warnings", []) if isinstance(validation, dict) else []
    errors = validation.get("errors", []) if isinstance(validation, dict) else []
    teaching_audit = manifest.get("teaching_audit", {}) if isinstance(manifest, dict) else {}
    audit_coverage = (
        teaching_audit.get("coverage", {}) if isinstance(teaching_audit, dict) else {}
    )
    run_tracking = manifest.get("run_tracking", {}) if isinstance(manifest, dict) else {}
    lines = [
        "# Paper Reader build report",
        "",
        f"- Release: {SKILL_VERSION}",
        f"- Structural validation: {validation.get('status', 'unknown')}",
        f"- Source alignment: {validation.get('validation_layers', {}).get('source_alignment', 'unknown')}",
        "- Scientific correctness: not proven by the automatic validator",
        f"- Errors: {len(errors)}",
        f"- Automatic warnings: {len(warnings)}",
        "",
        "## Coverage",
        "",
        f"- Pages: {coverage.get('pages', 'unknown')}",
        f"- Markers: {coverage.get('markers', 'unknown')}",
        f"- Figure/table candidates: {coverage.get('visual_candidates', 'unknown')}",
        f"- Figure/table candidates covered: {coverage.get('visual_candidates_covered', 'unknown')}",
        f"- Figure/table candidates excluded: {coverage.get('visual_candidates_excluded', 'unknown')}",
        f"- Automatically detected formula candidates: {coverage.get('formula_suspect_blocks', 'unknown')}",
        f"- Damaged formula candidates: {coverage.get('formula_damaged_blocks', 'unknown')}",
        f"- Formula triage: {json.dumps(coverage.get('formula_candidate_priorities', {}), ensure_ascii=False, sort_keys=True)}",
        "",
        "## Teaching self-audit",
        "",
        f"- Status: {teaching_audit.get('status', 'unknown')}",
        f"- Eligible source objects: {audit_coverage.get('eligible_markers', 'unknown')}",
        f"- Standard audits: {audit_coverage.get('standard_audit', 'unknown')}",
        f"- Full audits: {audit_coverage.get('full_audit', 'unknown')}",
        f"- Full-audit triggers: {json.dumps(audit_coverage.get('full_audit_trigger_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- Complexity distribution: {json.dumps(audit_coverage.get('complexity_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- Teaching-character diagnostics: {json.dumps(audit_coverage.get('teaching_characters', {}), ensure_ascii=False, sort_keys=True)}",
        f"- Corrected during audit: {audit_coverage.get('corrected_during_audit', 'unknown')}",
        f"- Passed with bounded source limit: {audit_coverage.get('pass_with_source_limit', 'unknown')}",
        f"- Audit warnings: {teaching_audit.get('warnings', 'unknown')}",
        "- Interpretation: completion of the hash-bound self-audit is recorded; scientific correctness is not independently proven.",
        "",
        "## Automatic warnings",
        "",
    ]
    lines.extend(f"- {item}" for item in warnings)
    if not warnings:
        lines.append("- None")
    lines.extend(["", "## Browser QA", ""])
    if isinstance(qa, dict):
        lines.extend(
            [
                f"- Level: {qa.get('level', 'unknown')}",
                f"- Status: {qa.get('status', 'unknown')}",
                f"- Checks: {', '.join(str(item) for item in qa.get('checks', [])) or 'not listed'}",
            ]
        )
        if qa.get("note"):
            lines.append(f"- Note: {qa['note']}")
    else:
        lines.append("- Not yet recorded")
    lines.extend(
        [
            "",
            "## Run diagnostics",
            "",
            f"- Run context: {json.dumps(run_tracking.get('run_context', {}), ensure_ascii=False, sort_keys=True)}",
            f"- Content-analysis segments: {json.dumps(run_tracking.get('diagnostics', {}).get('content_analysis_segments_seconds', {}), ensure_ascii=False, sort_keys=True)}",
            f"- Targeted revision: {json.dumps(run_tracking.get('diagnostics', {}).get('targeted_revision', {}), ensure_ascii=False, sort_keys=True)}",
        ]
    )
    lines.extend(
        [
            "",
            "## Timing interpretation",
            "",
            f"- {manifest.get('run_tracking', {}).get('timing_semantics', 'Only recorded script timings are available.')}",
            "- Host reconnect events are not visible unless the host explicitly exposes them.",
            "",
        ]
    )
    report_path = reader_dir / BUILD_REPORT_NAME
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def record_qa(
    work_dir: Path,
    *,
    level: str,
    status: str,
    checks: list[str],
    note: str | None,
) -> dict[str, Any]:
    if level not in {"smoke", "full"}:
        raise ValueError("QA level must be smoke or full")
    if status not in {"pass", "fail"}:
        raise ValueError("QA status must be pass or fail")
    stage = f"browser_{level}"
    stage_state = finish_stage(
        work_dir,
        stage,
        status="completed" if status == "pass" else "failed",
        errors=0 if status == "pass" else 1,
        note=note,
    )
    report = {
        "schema_version": STATE_SCHEMA,
        "skill_version": SKILL_VERSION,
        "recorded_at": utc_now(),
        "level": level,
        "status": status,
        "checks": checks,
        "note": note,
        "elapsed_seconds": stage_state.get("elapsed_seconds"),
    }
    atomic_json(work_dir / QA_REPORT_NAME, report)
    manifest_path = work_dir / "run_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(manifest, dict):
            manifest["qa"] = report
            current_state = load_state(work_dir)
            manifest["run_tracking"] = {
                "enabled": True,
                "state_file": STATE_NAME,
                "events_file": EVENTS_NAME,
                "timing_semantics": "stage wall-clock time; may include waiting or reconnection gaps",
                "run_context": current_state.get("run_context", {}),
                "stages": current_state.get("stages", {}),
                "milestones": current_state.get("milestones", {}),
                "diagnostics": diagnostic_summary(current_state),
            }
            atomic_json(manifest_path, manifest)
            (work_dir / "run-status.js").write_text(
                "window.PAPER_READER_RUN="
                + json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
                + ";\n",
                encoding="utf-8",
            )
    if (work_dir / "validation-report.json").is_file():
        write_build_report(work_dir)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create or resume a hashed run state")
    init_parser.add_argument("--work-dir", required=True)
    init_parser.add_argument("--input", required=True)
    init_parser.add_argument("--model")
    init_parser.add_argument("--reasoning-effort")
    init_parser.add_argument(
        "--fast-mode", choices=("enabled", "disabled", "unknown")
    )
    init_parser.add_argument("--translation-scope")
    init_parser.add_argument(
        "--reuse-mode",
        choices=("cold", "paper_index", "notes", "reader", "unknown"),
    )

    context_parser = subparsers.add_parser(
        "context", help="Record changed model or execution conditions"
    )
    context_parser.add_argument("--work-dir", required=True)
    context_parser.add_argument("--model")
    context_parser.add_argument("--reasoning-effort")
    context_parser.add_argument(
        "--fast-mode", choices=("enabled", "disabled", "unknown")
    )
    context_parser.add_argument("--translation-scope")
    context_parser.add_argument(
        "--reuse-mode",
        choices=("cold", "paper_index", "notes", "reader", "unknown"),
    )

    for command in ("start", "finish"):
        item = subparsers.add_parser(command)
        item.add_argument("--work-dir", required=True)
        item.add_argument("--stage", required=True)
        if command == "finish":
            item.add_argument("--status", choices=("completed", "failed", "interrupted"), default="completed")
            item.add_argument("--errors", type=int, default=0)
            item.add_argument("--warnings", type=int, default=0)
            item.add_argument("--note")

    checkpoint_parser = subparsers.add_parser("checkpoint")
    checkpoint_parser.add_argument("--work-dir", required=True)
    checkpoint_parser.add_argument("--stage", required=True)
    checkpoint_parser.add_argument("--item", action="append", required=True)
    checkpoint_parser.add_argument("--artifact")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--work-dir", required=True)

    qa_parser = subparsers.add_parser("qa")
    qa_parser.add_argument("--work-dir", required=True)
    qa_parser.add_argument("--level", choices=("smoke", "full"), required=True)
    qa_parser.add_argument("--status", choices=("pass", "fail"), required=True)
    qa_parser.add_argument("--check", action="append", default=[])
    qa_parser.add_argument("--note")

    args = parser.parse_args()
    work_dir = Path(args.work_dir).resolve()
    if args.command == "init":
        state, resumed = init_run(
            work_dir,
            Path(args.input).resolve(),
            {
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
                "fast_mode": args.fast_mode,
                "translation_scope": args.translation_scope,
                "reuse_mode": args.reuse_mode,
            },
        )
        print(f"Run {'resumed' if resumed else 'initialized'}: {state_path(work_dir)}")
    elif args.command == "context":
        context = update_run_context(
            work_dir,
            {
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
                "fast_mode": args.fast_mode,
                "translation_scope": args.translation_scope,
                "reuse_mode": args.reuse_mode,
            },
        )
        print(f"Run context recorded: {json.dumps(context, ensure_ascii=False)}")
    elif args.command == "start":
        stage = start_stage(work_dir, args.stage)
        print(f"Stage {args.stage} running (attempt {stage['attempt']})")
    elif args.command == "finish":
        stage = finish_stage(
            work_dir,
            args.stage,
            status=args.status,
            errors=args.errors,
            warnings=args.warnings,
            note=args.note,
        )
        print(f"Stage {args.stage}: {stage['status']} in {stage['elapsed_seconds']}s")
    elif args.command == "checkpoint":
        checkpoint(
            work_dir,
            args.stage,
            args.item,
            Path(args.artifact).resolve() if args.artifact else None,
        )
        print(f"Checkpointed {len(args.item)} item(s) for {args.stage}")
    elif args.command == "qa":
        report = record_qa(
            work_dir,
            level=args.level,
            status=args.status,
            checks=args.check,
            note=args.note,
        )
        print(f"Browser {args.level} QA: {report['status']}")
    else:
        print(json.dumps(load_state(work_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
