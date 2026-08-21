#!/usr/bin/env python3
"""Render a PDF and build separate reading-text and layout indexes.

The page image remains the visual source of truth. Pypdf supplies readable
text; pdfplumber supplies coordinates, formula crops, and visual captions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from statistics import median
from typing import Any

import pdfplumber
from PIL import Image
from pypdf import PdfReader

from run_tracker import finish_stage, start_stage


FORMULA_RE = re.compile(r"[=<>∑∫√±≤≥≈≃∂∇∞→←↔×÷]|\b(?:sin|cos|tan|exp|log)\s*\(")
FORMULA_FRAGMENT_RE = re.compile(r"\(cid:\d+\)|[∆µγν∈∑]")
EQUATION_NUMBER_RE = re.compile(r"\(\s*\d{1,3}\s*\)\s*$")
C0_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?[ivxlcdm\d]+$", re.IGNORECASE)
SECTION_RE = re.compile(
    r"^(?:\d{1,2}(?:\.\d+)*\s+|[IVXLCDM]+\.\s+|[A-Z]\.\s+)?"
    r"(?:abstract|introduction|background|materials?\s+and\s+methods?|methods?|"
    r"results?|discussion|conclusions?|acknowledg(?:e)?ments?|references|"
    r"supplement(?:ary|al)?(?:\s+(?:information|materials?))?|appendix)\b",
    re.IGNORECASE,
)
CAPTION_RE = re.compile(
    r"^(?P<label>(?:fig(?:ure)?\.?\s*\d+[A-Za-z]?|table\s*[IVXLCDM\d]+|scheme\s*\d+))\b",
    re.IGNORECASE,
)
VISUAL_REFERENCE_RE = re.compile(
    r"\b(?P<kind>fig(?:ure)?|table|scheme)\.?\s*(?P<number>[IVXLCDM]+|\d+)(?:[A-Za-z])?\b",
    re.IGNORECASE,
)
LONG_ALPHA_RE = re.compile(r"[A-Za-z]{30,}")
GLUE_RE = re.compile(r"(?:[a-z]{3,}[A-Z][a-z]{2,}|[A-Za-z][,;:][A-Za-z]|[a-z]\.[A-Z])")
LATEXIT_RE = re.compile(r"<latexit\b[^>]*>.*?</latexit>", re.IGNORECASE)
LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rounded_box(item: dict[str, Any]) -> dict[str, float]:
    return {
        "x0": round(float(item.get("x0", 0)), 2),
        "y0": round(float(item.get("top", item.get("y0", 0))), 2),
        "x1": round(float(item.get("x1", 0)), 2),
        "y1": round(float(item.get("bottom", item.get("y1", 0))), 2),
    }


def normalize_inline(text: str) -> str:
    # Some publisher PDFs expose LaTeXML accessibility payloads as literal
    # <latexit> tags followed by long base64-like data.  Preserve the location
    # as a damaged mathematical fragment, but never allow the payload to enter
    # readable prose, translation, or glued-word metrics.
    text = LATEXIT_RE.sub(" � ", text)
    text = C0_RE.sub(" � ", text)
    text = text.translate(LIGATURES).replace("\u00a0", " ").replace("\u200b", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[A-Za-z])\((?=[A-Za-z])", " (", text)
    text = re.sub(r"(?<=[,;:])(?=[A-Za-z])", " ", text)
    text = re.sub(r"(?<=[a-z\)])\.(?=[A-Z])", ". ", text)
    text = re.sub(r"(?<=\))(?=[A-Za-z])", " ", text)
    text = re.sub(r"\bandRis\b", "and R is", text)
    text = re.sub(
        r"\b(in|of|from|for|to|with|and|the|that)(?=[A-Z](?:[a-z]{2,}|\.\s))",
        r"\1 ",
        text,
    )
    text = re.sub(r"(?<=coli)(?=[a-z]{2,}\b)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=metabolite)(?=[ij]\b)", " ", text)
    text = re.sub(r"(?<=\d)\s+\.(?=\d)", ".", text)
    text = re.sub(r"\[\s+(?=\d)", "[", text)
    text = re.sub(r"\b(Table|Figure|Fig)\.\s+(?=[A-Z\d])", r"\1 ", text)
    return text


def strict_heading(text: str) -> bool:
    clean = normalize_inline(text)
    if not clean or len(clean) > 150 or clean.endswith((".", ",", ";")):
        return False
    if re.search(r"[=+−∆µ∑]|\b(?:kJ|mol|gDW|h−)", clean, re.IGNORECASE):
        return False
    if re.match(r"^appendix\s+[A-Z\d]+\s*[:.-]", clean, re.IGNORECASE):
        return len(clean) <= 100
    section_match = SECTION_RE.match(clean)
    if section_match:
        remainder = clean[section_match.end():].strip()
        return not remainder or bool(re.fullmatch(r"and\s+discussions?", remainder, re.IGNORECASE))
    if re.match(r"^[A-H]\.\s+\S", clean) and "," not in clean and clean.count(".") == 1:
        return len(clean) <= 100
    if re.match(r"^(?:\d{1,2}(?:\.\d+)+|[IVXLCDM]+\.)\s+\S", clean):
        words = re.findall(r"\S+", clean)
        return len(words) <= 12 and not formula_like(clean)
    words = re.findall(r"[A-Za-z]{2,}", clean)
    return 1 < len(words) <= 10 and clean.upper() == clean and len(clean) <= 90


def formula_like(text: str) -> bool:
    clean = normalize_inline(text)
    alpha_words = re.findall(r"[A-Za-z]{4,}", clean)
    return bool(
        ("�" in clean)
        or (FORMULA_RE.search(clean) and len(clean) <= 220)
        or (EQUATION_NUMBER_RE.search(clean) and len(alpha_words) <= 4)
        or (FORMULA_FRAGMENT_RE.search(clean) and len(clean) <= 70 and len(alpha_words) <= 1)
    )


def source_quality_flags(text: str) -> list[str]:
    flags: list[str] = []
    if LATEXIT_RE.search(text):
        flags.append("latexit_artifact")
    if C0_RE.search(text):
        flags.append("control_character")
    if re.search(r"\(cid:\d+\)", text):
        flags.append("cid_artifact")
    return flags


def formula_candidate_priority(text: str, quality_flags: list[str]) -> tuple[str, int, list[str]]:
    """Rank formula candidates without discarding low-confidence or damaged source material."""
    if quality_flags:
        return "damaged", 0, list(quality_flags)
    clean = normalize_inline(text)
    score = 0
    reasons: list[str] = []
    if EQUATION_NUMBER_RE.search(clean):
        score += 4
        reasons.append("numbered_equation")
    if "=" in clean:
        score += 3
        reasons.append("equality")
    operator_count = len(FORMULA_RE.findall(clean))
    if operator_count:
        score += min(3, operator_count)
        reasons.append("mathematical_operators")
    if len(clean) <= 160:
        score += 1
        reasons.append("compact_display")
    alpha_words = re.findall(r"[A-Za-z]{4,}", clean)
    if len(alpha_words) >= 12:
        score -= 2
        reasons.append("prose_heavy")
    if len(clean) > 220:
        score -= 2
        reasons.append("long_fragment")
    priority = "high" if score >= 7 else "medium" if score >= 4 else "low"
    return priority, score, reasons


def canonical_visual_id(kind: str, number: str) -> str:
    normalized_kind = "figure" if kind.lower().startswith("fig") else kind.lower()
    return f"{normalized_kind}:{number.upper()}"


def canonical_visual_id_from_text(text: str) -> str | None:
    match = VISUAL_REFERENCE_RE.match(text)
    if not match:
        return None
    return canonical_visual_id(match.group("kind"), match.group("number"))


def extract_layout_lines(page: Any) -> list[dict[str, Any]]:
    try:
        raw = page.extract_text_lines(
            layout=False, strip=True, return_chars=False, use_text_flow=True
        ) or []
    except Exception:
        raw = []
    lines: list[dict[str, Any]] = []
    for item in raw:
        text = normalize_inline(str(item.get("text", "")))
        box = rounded_box(item)
        if text and box["x1"] > box["x0"] and box["y1"] > box["y0"]:
            lines.append({"text": text, "bbox": box})
    if lines:
        return lines

    words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
    words = sorted(words, key=lambda word: (round(float(word["top"]), 1), float(word["x0"])))
    buckets: list[list[dict[str, Any]]] = []
    for word in words:
        if not buckets or abs(float(word["top"]) - float(buckets[-1][0]["top"])) > 3.0:
            buckets.append([word])
        else:
            buckets[-1].append(word)
    for bucket in buckets:
        bucket.sort(key=lambda word: float(word["x0"]))
        lines.append(
            {
                "text": normalize_inline(" ".join(str(word["text"]) for word in bucket)),
                "bbox": {
                    "x0": round(min(float(word["x0"]) for word in bucket), 2),
                    "y0": round(min(float(word["top"]) for word in bucket), 2),
                    "x1": round(max(float(word["x1"]) for word in bucket), 2),
                    "y1": round(max(float(word["bottom"]) for word in bucket), 2),
                },
            }
        )
    return lines


def merge_layout_formula_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [line for line in lines if formula_like(line["text"])]
    if not candidates:
        return []
    heights = [line["bbox"]["y1"] - line["bbox"]["y0"] for line in candidates]
    tolerance = max(7.0, (median(heights) if heights else 9.0) * 0.9)
    merged: list[dict[str, Any]] = []
    for line in candidates:
        should_split = not merged
        if merged:
            prior = merged[-1]
            gap = line["bbox"]["y0"] - prior["bbox"]["y1"]
            span = max(prior["bbox"]["y1"], line["bbox"]["y1"]) - min(
                prior["bbox"]["y0"], line["bbox"]["y0"]
            )
            should_split = (
                gap > tolerance
                or span > 96.0
                or bool(EQUATION_NUMBER_RE.search(prior["text"]))
            )
        if should_split:
            merged.append({"text": line["text"], "bbox": dict(line["bbox"])})
            continue
        prior = merged[-1]
        prior["text"] += " " + line["text"]
        prior["bbox"] = {
            "x0": min(prior["bbox"]["x0"], line["bbox"]["x0"]),
            "y0": min(prior["bbox"]["y0"], line["bbox"]["y0"]),
            "x1": max(prior["bbox"]["x1"], line["bbox"]["x1"]),
            "y1": max(prior["bbox"]["y1"], line["bbox"]["y1"]),
        }
    return merged


def clean_reading_lines(raw_text: str) -> list[dict[str, Any]]:
    source: list[dict[str, Any]] = []
    for raw_line in raw_text.splitlines():
        text = normalize_inline(raw_line)
        if text:
            source.append({"text": text, "quality_flags": source_quality_flags(raw_line)})
    output: list[dict[str, Any]] = []
    for item in source:
        line = item["text"]
        if output and output[-1]["text"].endswith("-") and line[:1].islower():
            output[-1]["text"] = output[-1]["text"][:-1] + line
            output[-1]["quality_flags"] = sorted(
                set(output[-1].get("quality_flags", [])) | set(item.get("quality_flags", []))
            )
        else:
            output.append(item)
    return output


def build_reading_blocks(raw_text: str, page_number: int) -> list[dict[str, Any]]:
    lines = clean_reading_lines(raw_text)
    blocks: list[dict[str, Any]] = []
    prose: list[dict[str, Any]] = []

    def flush_prose() -> None:
        if not prose:
            return
        text = normalize_inline(" ".join(item["text"] for item in prose))
        flags = sorted({flag for item in prose for flag in item.get("quality_flags", [])})
        if text:
            block = {"kind": "prose", "text": text, "translatable": not flags}
            if flags:
                block["quality_flags"] = flags
            blocks.append(block)
        prose.clear()

    for item in lines:
        line = item["text"]
        quality_flags = item.get("quality_flags", [])
        if PAGE_NUMBER_RE.match(line) and len(line) <= 12:
            continue
        if (
            blocks
            and blocks[-1].get("kind") == "caption"
            and not blocks[-1].get("_caption_open")
            and re.match(r"^(?:solid|dashed|dotted|symbols?|lines?|bars?|colors?|shaded|error\s+bars?)\b", line, re.IGNORECASE)
        ):
            blocks[-1]["_caption_open"] = True
        if blocks and blocks[-1].get("_caption_open"):
            blocks[-1]["text"] = normalize_inline(blocks[-1]["text"] + " " + line)
            blocks[-1]["quality_flags"] = sorted(
                set(blocks[-1].get("quality_flags", [])) | set(quality_flags)
            )
            blocks[-1]["translatable"] = not blocks[-1]["quality_flags"]
            if re.search(r"[.!?]\s*$", line) and len(blocks[-1]["text"]) >= 80:
                blocks[-1]["_caption_open"] = False
            continue
        caption_match = CAPTION_RE.match(line)
        if quality_flags or formula_like(line):
            flush_prose()
            blocks.append({
                "kind": "formula_reference",
                "text": line,
                "translatable": False,
                "quality_flags": quality_flags,
                "source_integrity": "damaged" if quality_flags else "candidate",
            })
        elif strict_heading(line):
            flush_prose()
            if blocks and blocks[-1].get("kind") == "heading":
                blocks[-1]["text"] = normalize_inline(blocks[-1]["text"] + " " + line)
            else:
                blocks.append({"kind": "heading", "text": line, "translatable": True})
        elif caption_match:
            flush_prose()
            blocks.append({
                "kind": "caption",
                "text": line,
                "label": caption_match.group("label"),
                "translatable": True,
                "_caption_open": not (re.search(r"[.!?]\s*$", line) and len(line) >= 80),
            })
        else:
            prose.append(item)
            current = " ".join(entry["text"] for entry in prose)
            if len(current) >= 420 or (len(current) >= 170 and re.search(r"[.!?]\s*$", line)):
                flush_prose()
    flush_prose()

    for index, block in enumerate(blocks, start=1):
        block.pop("_caption_open", None)
        block_id = f"p{page_number:03d}-b{index:03d}"
        block["id"] = block_id
        block["text_sha256"] = hashlib.sha256(block["text"].encode("utf-8")).hexdigest()
    return blocks


def visual_candidates(lines: list[dict[str, Any]], page_number: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for line in lines:
        match = CAPTION_RE.match(line["text"])
        if not match:
            continue
        # A real caption conventionally has a delimiter after its label
        # ("FIG. 2. ..." or "Table I. ..."). This rejects body references
        # such as "Fig. 2 shows ...", which otherwise create false visuals.
        remainder = line["text"][match.end():].lstrip()
        if not remainder.startswith((".", ":")):
            continue
        raw_label = re.sub(r"\s+", " ", match.group("label")).strip()
        key = re.sub(r"[^a-z0-9]+", "-", raw_label.lower()).strip("-") or "visual"
        seen[key] = seen.get(key, 0) + 1
        suffix = f"-{seen[key]}" if seen[key] > 1 else ""
        kind = "table" if raw_label.lower().startswith("table") else "figure"
        found.append(
            {
                "id": f"p{page_number:03d}-{key}{suffix}",
                "page": page_number,
                "kind": kind,
                "label": raw_label,
                "canonical_id": canonical_visual_id_from_text(raw_label),
                "caption_text": line["text"],
                "caption_bbox": line["bbox"],
                "requires_review": True,
            }
        )
    return found


def collect_visual_references(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for page in pages:
        page_number = int(page["number"])
        for block in page.get("text_blocks", []):
            if block.get("kind") not in {"prose", "heading", "caption"}:
                continue
            text = str(block.get("text", ""))
            for match in VISUAL_REFERENCE_RE.finditer(text):
                key = canonical_visual_id(match.group("kind"), match.group("number"))
                entry = grouped.setdefault(
                    key,
                    {
                        "canonical_id": key,
                        "kind": key.split(":", 1)[0],
                        "label": match.group(0),
                        "pages": [],
                        "block_ids": [],
                        "contexts": [],
                    },
                )
                if page_number not in entry["pages"]:
                    entry["pages"].append(page_number)
                block_id = str(block.get("id", ""))
                if block_id and block_id not in entry["block_ids"]:
                    entry["block_ids"].append(block_id)
                if len(entry["contexts"]) < 3:
                    start = max(0, match.start() - 70)
                    end = min(len(text), match.end() + 110)
                    context = text[start:end].strip()
                    if context not in entry["contexts"]:
                        entry["contexts"].append(context)
    return list(grouped.values())


def text_quality(blocks: list[dict[str, Any]]) -> dict[str, int]:
    readable = " ".join(
        block.get("text", "") for block in blocks
        if block.get("kind") in {"prose", "heading", "caption"} and block.get("translatable", True)
    )
    return {
        "long_alpha_runs": len(LONG_ALPHA_RE.findall(readable)),
        "cid_artifacts": readable.count("(cid:"),
        "suspicious_glue_boundaries": len(GLUE_RE.findall(readable)),
        "damaged_formula_references": sum(
            1 for block in blocks
            if block.get("kind") == "formula_reference" and block.get("source_integrity") == "damaged"
        ),
    }


def render_pages(pdf_path: Path, pages_dir: Path, dpi: int) -> list[Path]:
    converter = shutil.which("pdftoppm")
    if not converter:
        raise RuntimeError("pdftoppm was not found. Install Poppler or use the bundled PDF runtime.")
    converter_path = Path(converter)
    if converter_path.suffix.lower() in {".cmd", ".bat"} and len(converter_path.parents) >= 3:
        bundled = converter_path.parents[2] / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
        if bundled.is_file():
            converter = str(bundled)
    pages_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="paper-render-", dir=pages_dir.parent) as temp:
        prefix = Path(temp) / "page"
        result = subprocess.run(
            [converter, "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout or "unknown Poppler error").strip()
            raise RuntimeError(f"pdftoppm failed ({result.returncode}): {detail}")
        generated = sorted(Path(temp).glob("page-*.png"))
        if not generated:
            raise RuntimeError("Poppler completed without producing page images.")
        final_paths: list[Path] = []
        for number, source in enumerate(generated, start=1):
            target = pages_dir / f"page_{number:03d}.png"
            shutil.copy2(source, target)
            final_paths.append(target)
    return final_paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Source PDF path")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--dpi", type=int, default=144, help="Render DPI, default 144")
    parser.add_argument("--run-dir", help="Optional initialized run-tracking directory")
    args = parser.parse_args()

    started = time.perf_counter()
    pdf_path = Path(args.pdf).resolve()
    out_dir = Path(args.out_dir).resolve()
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")
    if args.dpi < 96:
        raise SystemExit("DPI must be at least 96 for readable source pages.")

    run_dir = Path(args.run_dir).resolve() if args.run_dir else None
    if run_dir:
        start_stage(run_dir, "extraction")

    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = render_pages(pdf_path, out_dir / "pages", args.dpi)
    pypdf = PdfReader(str(pdf_path))
    pages: list[dict[str, Any]] = []
    headings: list[dict[str, Any]] = []
    all_visuals: list[dict[str, Any]] = []
    all_quality = {
        "long_alpha_runs": 0,
        "cid_artifacts": 0,
        "suspicious_glue_boundaries": 0,
        "damaged_formula_references": 0,
    }
    formula_count = 0
    damaged_formula_count = 0

    with pdfplumber.open(pdf_path) as layout_pdf:
        metadata = {str(key): value for key, value in (layout_pdf.metadata or {}).items() if value is not None}
        if len(rendered) != len(layout_pdf.pages) or len(rendered) != len(pypdf.pages):
            raise RuntimeError("Rendered, pypdf, and pdfplumber page counts disagree.")
        for page_number, (layout_page, pypdf_page, image_path) in enumerate(
            zip(layout_pdf.pages, pypdf.pages, rendered), start=1
        ):
            blocks = build_reading_blocks(pypdf_page.extract_text() or "", page_number)
            quality = text_quality(blocks)
            for key, value in quality.items():
                all_quality[key] += value
            for block in blocks:
                if block["kind"] == "heading":
                    headings.append({"page": page_number, "block_id": block["id"], "text": block["text"]})

            layout_lines = extract_layout_lines(layout_page)
            formulas = merge_layout_formula_lines(layout_lines)
            for index, formula in enumerate(formulas, start=1):
                formula["id"] = f"p{page_number:03d}-formula-{index:02d}"
                formula["quality_flags"] = source_quality_flags(formula.get("text", ""))
                formula["source_integrity"] = "damaged" if formula["quality_flags"] else "pending_review"
                priority, score, reasons = formula_candidate_priority(
                    str(formula.get("text", "")), formula["quality_flags"]
                )
                formula["candidate_priority"] = priority
                formula["candidate_score"] = score
                formula["candidate_reasons"] = reasons
                if formula["source_integrity"] == "damaged":
                    damaged_formula_count += 1
            formula_count += len(formulas)
            visuals = visual_candidates(layout_lines, page_number)
            all_visuals.extend(visuals)

            with Image.open(image_path) as image:
                pixel_size = {"width": image.width, "height": image.height}
            pages.append(
                {
                    "number": page_number,
                    "width_pt": round(float(layout_page.width), 2),
                    "height_pt": round(float(layout_page.height), 2),
                    "image": f"pages/{image_path.name}",
                    "pixel_size": pixel_size,
                    "text_blocks": blocks,
                    "formula_blocks": formulas,
                    "visual_candidates": visuals,
                    "text_quality": quality,
                }
            )

    pdf_meta = {str(key).lstrip("/"): value for key, value in (pypdf.metadata or {}).items() if value is not None}
    title = metadata.get("Title") or pdf_meta.get("Title") or pdf_path.stem
    authors = metadata.get("Author") or pdf_meta.get("Author") or ""
    visual_references = collect_visual_references(pages)
    candidate_canonical_ids = {
        str(item.get("canonical_id")) for item in all_visuals if item.get("canonical_id")
    }
    unmatched_visual_references = [
        item for item in visual_references if item["canonical_id"] not in candidate_canonical_ids
    ]
    formula_priorities = {"high": 0, "medium": 0, "low": 0, "damaged": 0}
    for page in pages:
        for formula in page.get("formula_blocks", []):
            priority = str(formula.get("candidate_priority", "low"))
            formula_priorities[priority] = formula_priorities.get(priority, 0) + 1
    index = {
        "schema_version": "2.1",
        "source_pdf": str(pdf_path),
        "source_sha256": sha256_file(pdf_path),
        "metadata": {"title": title, "authors": authors, "page_count": len(pages), "pdf_metadata": metadata},
        "render": {"dpi": args.dpi, "engine": "pdftoppm"},
        "text_extraction": {"primary": "pypdf", "coordinates": "pdfplumber", "quality": all_quality},
        "pages": pages,
        "heading_candidates": headings,
        "visual_candidates": all_visuals,
        "visual_references": visual_references,
        "unmatched_visual_references": unmatched_visual_references,
        "formula_suspect_count": formula_count,
        "formula_damaged_count": damaged_formula_count,
        "formula_candidate_priorities": formula_priorities,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    output = out_dir / "paper_index.json"
    output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Indexed {len(pages)} pages to {output}")
    print(
        f"Headings: {len(headings)}; visuals: {len(all_visuals)}; "
        f"unmatched visual references: {len(unmatched_visual_references)}; formula crops: {formula_count}"
    )
    print(f"Text quality signals: {all_quality}")
    if run_dir:
        finish_stage(
            run_dir,
            "extraction",
            warnings=sum(int(value) for value in all_quality.values()),
            note=f"{len(pages)} pages; {len(all_visuals)} visual candidates; {formula_count} formula candidates",
        )
        start_stage(run_dir, "context_indexing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
