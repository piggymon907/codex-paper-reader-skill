#!/usr/bin/env python3
"""Create a reviewable notes skeleton from a paper index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from version_info import SCHEMA_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-index", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    index_path = Path(args.paper_index).resolve()
    data = json.loads(index_path.read_text(encoding="utf-8"))
    pages = data.get("pages", [])
    title = data.get("metadata", {}).get("title", index_path.parent.name)

    sections = []
    for heading in data.get("heading_candidates", [])[:40]:
        if not isinstance(heading, dict) or not str(heading.get("text", "")).strip():
            continue
        sections.append(
            {
                "id": f"section-{len(sections) + 1:02d}",
                "label": str(heading["text"]).strip(),
                "start_page": int(heading.get("page", 1)),
                "end_page": int(heading.get("page", 1)),
                "candidate": True,
            }
        )

    result = {
        "schema_version": SCHEMA_VERSION,
        "paper": {
            "title": title,
            "experimental_data_status": "uncertain",
            "sections": sections,
            "section_candidates_require_review": bool(sections),
            "excluded_visual_candidates": [],
            "excluded_visual_references": [],
            "run_metrics": {
                "context_indexing_seconds": None,
                "content_analysis_seconds": None,
            },
        },
        "pages": {
            str(page["number"]): {
                "overview": "",
                "markers": [],
                "visual_candidates": page.get("visual_candidates", []),
            }
            for page in pages
        },
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote notes skeleton for {len(pages)} pages to {out}")
    print(f"Section candidates requiring review: {len(sections)}")
    print(f"Visual candidates requiring coverage review: {len(data.get('visual_candidates', []))}")
    print(
        "Figure/table references without a located caption: "
        f"{len(data.get('unmatched_visual_references', []))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
