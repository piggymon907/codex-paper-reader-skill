#!/usr/bin/env python3
"""Prepare and safely apply cached page translations to an existing paper reader."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from version_info import SCHEMA_VERSION, SKILL_VERSION


TRANSLATABLE_KINDS = {"prose", "heading", "caption"}
CITATION_RE = re.compile(r"\[([0-9][0-9,\s\-–—]*)\]")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
IDENTIFIER_RE = re.compile(
    r"\b(?:[A-Za-z\u0370-\u03ff]+_[A-Za-z0-9\u0370-\u03ff]+|"
    r"[a-z]+[A-Z]{2,}[A-Za-z0-9]*|[A-Z]{2,}[A-Za-z0-9]*|"
    r"(?:[A-Z][a-z]?\d*){2,})\b"
)
UNIT_RE = re.compile(
    r"(?<![A-Za-z])(?:kJ|mol|mmol|µmol|μmol|gDW|Cmol|mM|µM|μM)"
    r"(?:[⁻−\-]?[¹²³⁰0-9]+)?(?![A-Za-z])"
)
CONTEXT_UNIT_RE = re.compile(
    r"(?<=\d)\s*(?P<unit>J|K|h|s|M)(?P<power>[\-]?[0-9]+)?(?![A-Za-z])"
)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
SCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉", "01234567890123456789")
ROOT_OUTPUT_FILES = (
    "reader.css",
    "reader.js",
    "data.js",
    "reader-data.json",
    "index.html",
    "run_manifest.json",
    "validation-report.json",
    "validation-status.js",
    "run-status.js",
    "build_report.md",
)
TRACKING_OUTPUT_FILES = ("run-state.json", "run-events.jsonl", "qa-report.json")


def load_object(path: Path, *, optional: bool = False) -> dict[str, Any]:
    if optional and not path.is_file():
        return {}
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_pages(raw: str) -> list[int]:
    values: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        number = int(item)
        if number < 1:
            raise ValueError(f"Invalid page number: {number}")
        if number not in values:
            values.append(number)
    if not values:
        raise ValueError("No page numbers were supplied")
    return values


def page_map(paper: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for page in paper.get("pages", []):
        if isinstance(page, dict) and page.get("number") is not None:
            result[int(page["number"])] = page
    return result


def block_map(page: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(block["id"]): block
        for block in page.get("text_blocks", [])
        if isinstance(block, dict) and block.get("id")
    }


def normalized_citations(text: str) -> Counter[str]:
    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", value.replace("—", "–").replace("-", "–"))

    return Counter(normalize(value) for value in CITATION_RE.findall(text))


def protected_tokens(text: str, *, include_identifiers: bool = True) -> Counter[str]:
    normalized = text.translate(SCRIPT_DIGITS).replace("−", "-")
    tokens: list[str] = []
    tokens.extend(EMAIL_RE.findall(normalized))
    tokens.extend(GREEK_RE.findall(normalized))
    if include_identifiers:
        tokens.extend(IDENTIFIER_RE.findall(normalized))
    tokens.extend(UNIT_RE.findall(normalized))
    tokens.extend(
        f"{match.group('unit')}{match.group('power') or ''}"
        for match in CONTEXT_UNIT_RE.finditer(normalized)
    )
    tokens.extend(NUMBER_RE.findall(normalized))
    return Counter(tokens)


def missing_counter(required: Counter[str], actual: Counter[str]) -> list[str]:
    missing: list[str] = []
    for token, count in required.items():
        deficit = count - actual[token]
        if deficit > 0:
            missing.extend([token] * deficit)
    return missing


def validate_translation(block_id: str, source: str, translation: str, kind: str) -> None:
    problems: list[str] = []
    missing_citations = missing_counter(normalized_citations(source), normalized_citations(translation))
    if missing_citations:
        problems.append("citations=" + ", ".join(missing_citations))
    include_identifiers = kind != "heading"
    missing_tokens = missing_counter(
        protected_tokens(source, include_identifiers=include_identifiers),
        protected_tokens(translation, include_identifiers=include_identifiers),
    )
    if missing_tokens:
        problems.append("protected_tokens=" + ", ".join(missing_tokens))
    if problems:
        raise ValueError(f"{block_id}: translation omitted protected source content ({'; '.join(problems)})")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        str(path.relative_to(root)).replace("\\", "/"): file_hash(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def run_checked(command: list[str]) -> None:
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {' '.join(command)}")


def prepare(args: argparse.Namespace) -> int:
    index_path = Path(args.paper_index).resolve()
    output_path = Path(args.out).resolve()
    if output_path.exists() and not args.force:
        raise SystemExit(f"Patch template already exists: {output_path}; use --force to replace it")
    paper = load_object(index_path)
    pages = page_map(paper)
    translations = load_object(Path(args.translations).resolve(), optional=True) if args.translations else {}
    cached_pages = translations.get("pages", {}) if isinstance(translations.get("pages", {}), dict) else {}
    patch: dict[str, Any] = {"schema_version": "1.0", "language": "zh-CN", "pages": {}}
    for number in parse_pages(args.pages):
        page = pages.get(number)
        if not page:
            raise ValueError(f"Page {number} is not present in the paper index")
        cached = cached_pages.get(str(number), {}) if isinstance(cached_pages, dict) else {}
        cached_blocks = cached.get("blocks", {}) if isinstance(cached, dict) else {}
        prepared_blocks: dict[str, Any] = {}
        for block in page.get("text_blocks", []):
            if (
                not isinstance(block, dict)
                or block.get("kind") not in TRANSLATABLE_KINDS
                or block.get("translatable", True) is False
            ):
                continue
            block_id = str(block.get("id", ""))
            source = str(block.get("text", ""))
            if not block_id or not source.strip():
                continue
            prepared_blocks[block_id] = {
                "kind": block.get("kind"),
                "source_sha256": block.get("text_sha256") or text_sha256(source),
                "source": source,
                "translation": str(cached_blocks.get(block_id, "")) if isinstance(cached_blocks, dict) else "",
            }
        patch["pages"][str(number)] = {"status": "complete", "blocks": prepared_blocks}
    atomic_write(output_path, json_bytes(patch))
    print(f"Prepared translation patch for {len(patch['pages'])} page(s): {output_path}")
    return 0


def merge_patch(
    paper: dict[str, Any], translations: dict[str, Any], patch: dict[str, Any]
) -> tuple[dict[str, Any], dict[int, tuple[int, int]]]:
    pages = page_map(paper)
    merged = json.loads(json.dumps(translations or {}))
    merged["schema_version"] = SCHEMA_VERSION
    merged.setdefault("language", patch.get("language") or "zh-CN")
    merged.setdefault("pages", {})
    if not isinstance(merged["pages"], dict):
        raise ValueError("translations.pages must be an object")
    patch_pages = patch.get("pages", {})
    if not isinstance(patch_pages, dict) or not patch_pages:
        raise ValueError("Patch contains no pages")
    coverage: dict[int, tuple[int, int]] = {}
    for page_key, page_patch in patch_pages.items():
        number = int(page_key)
        page = pages.get(number)
        if not page:
            raise ValueError(f"Patch references missing page {number}")
        if not isinstance(page_patch, dict) or not isinstance(page_patch.get("blocks"), dict):
            raise ValueError(f"Page {number}: patch blocks must be an object")
        current_blocks = block_map(page)
        existing_page = merged["pages"].get(str(number), {})
        existing_blocks = existing_page.get("blocks", {}) if isinstance(existing_page, dict) else {}
        next_blocks = dict(existing_blocks) if isinstance(existing_blocks, dict) else {}
        for block_id, payload in page_patch["blocks"].items():
            if block_id not in current_blocks:
                raise ValueError(f"Page {number}: unknown block ID {block_id}")
            if not isinstance(payload, dict):
                raise ValueError(f"Page {number} {block_id}: patch entry must be an object")
            current = current_blocks[block_id]
            if current.get("kind") not in TRANSLATABLE_KINDS or current.get("translatable", True) is False:
                raise ValueError(f"Page {number} {block_id}: source block is not safe for translation")
            source = str(current.get("text", ""))
            expected_hash = str(current.get("text_sha256") or text_sha256(source))
            if str(payload.get("source_sha256", "")) != expected_hash:
                raise ValueError(f"Page {number} {block_id}: source hash changed; prepare a fresh patch")
            if str(payload.get("source", "")) != source:
                raise ValueError(f"Page {number} {block_id}: source text changed; prepare a fresh patch")
            translation = str(payload.get("translation", "")).strip()
            if translation:
                validate_translation(block_id, source, translation, str(current.get("kind", "")))
                next_blocks[block_id] = translation
        prose_ids = [
            block_id for block_id, block in current_blocks.items()
            if block.get("kind") == "prose" and block.get("translatable", True) is not False
        ]
        missing = [block_id for block_id in prose_ids if not str(next_blocks.get(block_id, "")).strip()]
        requested_status = str(page_patch.get("status", "complete"))
        if requested_status == "complete" and missing:
            raise ValueError(f"Page {number}: complete patch is missing {len(missing)} prose translation(s)")
        actual_status = "complete" if not missing else "partial"
        merged["pages"][str(number)] = {"status": actual_status, "blocks": next_blocks}
        coverage[number] = (len(prose_ids) - len(missing), len(prose_ids))
    return merged, coverage


def install_staging(staging: Path, out_dir: Path, prior_asset_hashes: dict[str, str]) -> None:
    staged_assets = tree_hashes(staging / "assets")
    if prior_asset_hashes and staged_assets != prior_asset_hashes:
        raise ValueError("Translation-only build changed PDF/page assets; refusing to update the reader")
    if not out_dir.exists():
        shutil.move(str(staging), str(out_dir))
        return
    if not prior_asset_hashes:
        shutil.copytree(staging / "assets", out_dir / "assets", dirs_exist_ok=True)
    for name in ROOT_OUTPUT_FILES:
        source = staging / name
        if not source.is_file():
            raise FileNotFoundError(f"Staging build omitted required output: {source}")
        destination = out_dir / name
        temp = destination.with_name(f".{destination.name}.translation-update.tmp")
        shutil.copy2(source, temp)
        os.replace(temp, destination)
    for name in TRACKING_OUTPUT_FILES:
        source = staging / name
        if not source.is_file():
            continue
        destination = out_dir / name
        temp = destination.with_name(f".{destination.name}.translation-update.tmp")
        shutil.copy2(source, temp)
        os.replace(temp, destination)


def apply_patch(args: argparse.Namespace) -> int:
    index_path = Path(args.paper_index).resolve()
    notes_path = Path(args.notes).resolve()
    translations_path = Path(args.translations).resolve()
    patch_path = Path(args.patch).resolve()
    out_dir = Path(args.out_dir).resolve()
    paper = load_object(index_path)
    current_translations = load_object(translations_path, optional=True)
    patch = load_object(patch_path)
    merged, coverage = merge_patch(paper, current_translations, patch)
    for number, (translated, total) in coverage.items():
        print(f"Page {number}: translated prose blocks {translated}/{total}")
    if args.dry_run:
        print("Dry run passed; no files were changed")
        return 0

    prior_bytes = translations_path.read_bytes() if translations_path.is_file() else None
    prior_assets = tree_hashes(out_dir / "assets")
    prior_output_files = {
        name: (out_dir / name).read_bytes() if (out_dir / name).is_file() else None
        for name in ROOT_OUTPUT_FILES + TRACKING_OUTPUT_FILES
    }
    script_dir = Path(__file__).resolve().parent
    build_script = script_dir / "build_reader.py"
    validate_script = script_dir / "validate_reader.py"
    staging_parent = out_dir.parent
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.translation-build-", dir=staging_parent))
    try:
        atomic_write(translations_path, json_bytes(merged))
        build_command = [
            sys.executable,
            str(build_script),
            "--paper-index", str(index_path),
            "--notes", str(notes_path),
            "--translations", str(translations_path),
            "--out-dir", str(staging),
            "--force",
        ]
        existing_audit = out_dir / "teaching-audit-report.json"
        if existing_audit.is_file():
            build_command.extend(["--teaching-audit-report", str(existing_audit)])
        run_checked(build_command)
        prior_state_path = out_dir / "run-state.json"
        if prior_state_path.is_file():
            prior_state = load_object(prior_state_path)
            if prior_state.get("skill_version") == SKILL_VERSION:
                for name in ("run-state.json", "run-events.jsonl", "qa-report.json"):
                    source = out_dir / name
                    if source.is_file():
                        shutil.copy2(source, staging / name)
                prior_manifest = load_object(out_dir / "run_manifest.json", optional=True)
                staged_manifest_path = staging / "run_manifest.json"
                staged_manifest = load_object(staged_manifest_path)
                if prior_manifest.get("run_tracking", {}).get("enabled"):
                    staged_manifest["run_tracking"] = prior_manifest["run_tracking"]
                    for key in ("pdf_parse_and_render", "context_indexing", "content_analysis"):
                        prior_value = prior_manifest.get("timings_seconds", {}).get(key)
                        if prior_value is not None:
                            staged_manifest.setdefault("timings_seconds", {})[key] = prior_value
                    atomic_write(staged_manifest_path, json_bytes(staged_manifest))
        run_checked([sys.executable, str(validate_script), "--strict", str(staging)])
        install_staging(staging, out_dir, prior_assets)
    except Exception:
        if prior_bytes is None:
            translations_path.unlink(missing_ok=True)
        else:
            atomic_write(translations_path, prior_bytes)
        if out_dir.exists():
            for name, content in prior_output_files.items():
                destination = out_dir / name
                if content is None:
                    destination.unlink(missing_ok=True)
                else:
                    atomic_write(destination, content)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    print(f"Updated cached translations and reader: {out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Export a source-hashed translation patch")
    prepare_parser.add_argument("--paper-index", required=True)
    prepare_parser.add_argument("--translations", help="Existing translations to prefill")
    prepare_parser.add_argument("--pages", required=True, help="Comma-separated one-based page numbers")
    prepare_parser.add_argument("--out", required=True)
    prepare_parser.add_argument("--force", action="store_true")
    prepare_parser.set_defaults(handler=prepare)

    apply_parser = subparsers.add_parser("apply", help="Validate, merge, build, and install translations")
    apply_parser.add_argument("--paper-index", required=True)
    apply_parser.add_argument("--notes", required=True)
    apply_parser.add_argument("--translations", required=True)
    apply_parser.add_argument("--patch", required=True)
    apply_parser.add_argument("--out-dir", required=True)
    apply_parser.add_argument("--dry-run", action="store_true")
    apply_parser.set_defaults(handler=apply_patch)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
