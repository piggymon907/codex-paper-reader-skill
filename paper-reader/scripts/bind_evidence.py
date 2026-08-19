#!/usr/bin/env python3
"""Bind verbatim marker excerpts to stable text-block IDs without semantic guessing."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def page_map(index: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(page["number"]): page
        for page in index.get("pages", [])
        if isinstance(page, dict) and str(page.get("number", "")).isdigit()
    }


def unique_window_match(
    source_text: str, blocks: list[dict[str, Any]], max_blocks: int
) -> tuple[list[str] | None, str]:
    source = normalized(source_text)
    if not source:
        return None, "missing-source"
    matches: list[list[str]] = []
    usable = [
        block for block in blocks
        if isinstance(block, dict) and str(block.get("id", "")).strip()
    ]
    for start in range(len(usable)):
        texts: list[str] = []
        ids: list[str] = []
        for end in range(start, min(len(usable), start + max_blocks)):
            texts.append(str(usable[end].get("text", "")))
            ids.append(str(usable[end]["id"]))
            if source in normalized(" ".join(texts)):
                matches.append(list(ids))
                break
    deduplicated: list[list[str]] = []
    for item in matches:
        if item not in deduplicated:
            deduplicated.append(item)
    if deduplicated:
        shortest = min(len(item) for item in deduplicated)
        deduplicated = [item for item in deduplicated if len(item) == shortest]
    if len(deduplicated) == 1:
        return deduplicated[0], "bound"
    if len(deduplicated) > 1:
        return None, "ambiguous"
    return None, "not-found"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-index", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--out", help="Write updated notes here")
    parser.add_argument("--in-place", action="store_true", help="Replace --notes atomically")
    parser.add_argument("--replace", action="store_true", help="Re-evaluate existing block_ids")
    parser.add_argument("--max-blocks", type=int, default=3)
    args = parser.parse_args()

    if args.in_place == bool(args.out):
        raise SystemExit("Choose exactly one of --out or --in-place")
    if args.max_blocks < 1 or args.max_blocks > 6:
        raise SystemExit("--max-blocks must be between 1 and 6")

    index_path = Path(args.paper_index).resolve()
    notes_path = Path(args.notes).resolve()
    output_path = notes_path if args.in_place else Path(args.out).resolve()
    index = load_object(index_path)
    notes = load_object(notes_path)
    pages = page_map(index)
    counts = {"bound": 0, "kept": 0, "missing-source": 0, "ambiguous": 0, "not-found": 0}
    unresolved: list[dict[str, Any]] = []

    for page_key, page_notes in notes.get("pages", {}).items():
        number = int(page_key)
        blocks = pages.get(number, {}).get("text_blocks", [])
        for marker in page_notes.get("markers", []):
            if not isinstance(marker, dict):
                continue
            existing = marker.get("block_ids")
            if isinstance(existing, list) and existing and not args.replace:
                counts["kept"] += 1
                continue
            match, status = unique_window_match(
                str(marker.get("source_text", "")), blocks, args.max_blocks
            )
            counts[status] += 1
            if match:
                marker["block_ids"] = match
            else:
                marker["block_ids"] = []
                unresolved.append(
                    {
                        "page": number,
                        "marker_id": marker.get("id"),
                        "claim_status": marker.get("claim_status"),
                        "status": status,
                    }
                )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.evidence-bind.tmp")
    temporary.write_text(json.dumps(notes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    print(f"Evidence binding: {counts}")
    print(f"Unresolved markers: {len(unresolved)}")
    for item in unresolved:
        print(
            f"  page {item['page']} marker {item['marker_id']}: "
            f"{item['status']} ({item['claim_status']})"
        )
    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
