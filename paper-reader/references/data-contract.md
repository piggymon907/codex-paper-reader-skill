# Paper Reader data contract

## Build identity

Release `2.4.0` writes the following immutable build identity into `run_manifest.json`:

```json
{
  "generator": {
    "skill_name": "paper-reader",
    "skill_version": "2.4.0",
    "builder_version": "2.4.0"
  },
  "text_quality_at_build": {
    "long_alpha_runs": 0,
    "cid_artifacts": 0,
    "suspicious_glue_boundaries": 0,
    "damaged_formula_references": 0
  }
}
```

After validation, the manifest also records `validation.validator_version`, validation
status, warning/error counts, and the validator's observed text-quality counts. Treat a
missing or different release identity as a validation failure rather than silently applying
new quality rules to an old package.

## Coordinates

Use PDF points with a top-left origin. Keep page dimensions in `paper_index.json`; convert to percentages only in the browser.

```json
{"x0": 72.0, "y0": 144.0, "x1": 420.0, "y1": 188.0}
```

Use several `bboxes` for discontinuous source lines. Use one `visual_bbox` for the source crop containing a figure, table, or formula.

## Notes

```json
{
  "schema_version": "2.2",
  "paper": {
    "title": "Full paper title",
    "experimental_data_status": "present",
    "sections": [
      {"id": "results", "label": "Results", "start_page": 4, "end_page": 8}
    ],
    "excluded_visual_candidates": [
      {"id": "p001-figure-1", "reason": "Journal cover thumbnail, not a scientific figure."}
    ],
    "excluded_visual_references": [
      {"canonical_id": "figure:7", "reason": "Reference is explicitly to an unprovided supplement."}
    ]
  },
  "pages": {
    "4": {
      "overview": "本页建立统计单位并解释 Figure 2。",
      "markers": [
        {
          "id": "p004-figure-2",
          "category": "evidence",
          "content_type": "figure",
          "visual_candidate_id": "p004-fig-2",
          "figure_label": "Figure 2",
          "title": "Figure 2：重复实验层级的效应估计",
          "takeaway": "Figure 2 显示，每个点代表独立重复的估计，而不是单帧数据。",
          "how_to_read": "阅读 Figure 2 时，先看横轴条件，再比较各重复的点估计与误差范围。",
          "explanation": "Figure 2 汇总了实验设计、变量、处理步骤与作者采用的读法。",
          "supports": "支持条件 A 与响应方向一致。",
          "does_not_support": "不能单凭该图证明唯一机制。",
          "limitations": "样本量和替代机制仍限制解释。",
          "panels": [
            {"label": "A", "explanation": "原始轨迹与基线。"},
            {"label": "B-C", "explanation": "重复层级汇总及模型比较。"}
          ],
          "prerequisites": "读图前需要区分单帧、重复实验和重复层级估计。",
          "reading_steps": [
            "阅读 Figure 2 时，先确认横纵轴及每个点的统计单位。",
            "再比较独立重复之间的方向与不确定性。",
            "最后把图中观察与作者的机制解释分开。"
          ],
          "key_values": [
            {"label": "统计单位", "value": "independent replicate", "meaning": "每个点不是单帧数据"}
          ],
          "common_misreadings": ["不要把帧数当作独立样本量。"],
          "source_checks": ["核对图注是否报告样本量和误差定义。"],
          "locator": "Results, p.4, Figure 2",
          "claim_status": "direct",
          "source_text": "Each point represents an independent replicate estimate.",
          "block_ids": ["p004-b006", "p004-b007"],
          "visual_bbox": {"x0": 66, "y0": 120, "x1": 530, "y1": 430},
          "bboxes": [
            {"x0": 66, "y0": 438, "x1": 530, "y1": 486}
          ],
          "must_check_source": false,
          "experimental_data": {
            "status": "present",
            "origin": "author_generated",
            "role": "Figure 2 plots replicate-level measurements generated in this study.",
            "source_hints": ["Methods, p.3", "Data availability statement"],
            "reported_identifiers": ["GEO: GSE000000"]
          }
        }
      ]
    }
  }
}
```

## Experimental-data provenance

Set `paper.experimental_data_status` to exactly one of:

- `present`: the provided paper directly uses experimental measurements;
- `absent`: the provided paper is theory-, simulation-, or model-only and no experimental measurements support its delivered results;
- `uncertain`: the paper appears to rely on experimental measurements, but the provided material does not identify them clearly enough.

Do not interpret simulation output, fitted model output, theoretical calculations, source code, metabolic reconstructions, or literature-derived constants as experimental data. Reused public measurements do count when they directly support the current paper.

Add `experimental_data` only to a marker for which an on-demand provenance question is useful. Its fields are:

- `status`: `present` or `uncertain`;
- `origin`: `author_generated`, `reused_external`, `mixed`, or `uncertain`;
- `role`: a complete sentence stating how the measurements support this marker;
- `source_hints`: one or more specific locations already found in the provided paper, such as a Methods subsection, figure caption, Data availability statement, supplement, accession, DOI, or cited source paper;
- `reported_identifiers`: optional accession numbers, repository names, DOI values, or URLs stated by the paper.

When `paper.experimental_data_status` is `absent`, omit every marker-level `experimental_data` object and show no provenance action. When it is `present`, provide at least one marker-level object. `uncertain` may have a marker-level object only when there is a specific lead to investigate. The reader action prepares a contextual follow-up; it does not browse, download, or analyze data during the normal build.

## Teaching fields

The reading sidebar and the full figure/formula view consume the same marker. Keep concise orientation in the existing core fields and add teaching depth only where useful:

For a figure, table, or key formula, keep recurring UI headings plain. Identify the source object once in the first sentence of `takeaway`, `how_to_read` (and the first `reading_steps` item when present), and `explanation`. Store the whole source-object label in `figure_label` (`Figure 2`, not `Figure 2A-C`); describe panel coverage in `panels` or the prose.

- `prerequisites`: complete-sentence background needed before the item can be understood;
- `reading_steps`: ordered strings describing where to look or what to substitute first;
- `key_values`: objects with `label`, optional `value`, and `meaning`/`explanation`;
- `symbols`: formula-table objects with `symbol`, `meaning`, `unit`/`range`, and `source`/`note`;
- `derivation_steps` or `use_steps`: ordered strings. Distinguish a source-stated derivation from the reader's algebraic reconstruction;
- `common_misreadings`: explicit technical confusions to avoid;
- `source_checks`: specific reasons and locations that may require the original paper, another page, or an unprovided supplement;
- `detail_sections`: paper-specific sections shaped as `{"title": "...", "body": "..."}` or `{"title": "...", "items": ["..."], "ordered": true}`.

Do not fill every optional field mechanically. Use the fields that close a real reasoning gap. For a key figure, normally provide `prerequisites` or equivalent context, a reading sequence, panel/encoding detail, evidence boundaries, and specific source checks. For a key formula, normally provide `symbols`, derivation/use steps, applicability, and common misreadings.

Use one `visual_bbox` containing the complete source object for every delivered figure, table, and formula. `bboxes` may still point to captions or supporting prose. Do not force a tall or narrow crop to full container width in the UI.

Allowed `content_type` values:

- `text`: concepts, claims, and ordinary prose;
- `figure`: numbered or unnumbered scientific figures and schemes;
- `table`: scientific tables;
- `formula`: equations, derivations, and parameter relations;
- `method`: experimental, computational, statistical, or data-processing procedures.

Allowed marker categories:

- `context`: definitions and background;
- `evidence`: observations, data, figures, and statistical support;
- `technical`: formulas, methods, assumptions, and processing;
- `caveat`: limitations, uncertainty, boundaries, and alternatives.

Allowed `claim_status` values: `direct`, `inference`, `unknown`.

For every `direct` marker, `source_text` must be a verbatim substring of the text in its `block_ids`. Put paraphrases only in explanation fields. `bind_evidence.py` fills only unique exact matches and reports anything that still needs review.

Formula markers additionally require `formula_source_status`:

- `verified`: the source crop and symbols were visually checked against the PDF;
- `damaged`: extraction contains an unknown glyph or other corruption; set `must_check_source`;
- `not_detected`: the formula was located manually rather than trusted from automatic extraction; set `must_check_source` until visually reviewed.

Set `must_check_source` for quotations, unresolved context, consequential conclusions, fragile formulas, or any explanation that should not be relied on without the complete original passage.

## Visual coverage

`paper_index.json` exposes caption-based `visual_candidates`. Every candidate must be either:

1. linked from a `figure` or `table` marker with `visual_candidate_id`; or
2. listed in `paper.excluded_visual_candidates` with a specific review reason.

The candidate caption box is not automatically the figure box. Inspect the page and set `visual_bbox` around the complete scientific visual. A multi-panel figure normally has one crop plus panel explanations.

`visual_references` is a separate reconciliation ledger collected from figure/table mentions in reading text. Every `unmatched_visual_references` entry must be located or listed in `excluded_visual_references` with a reviewed reason. Candidate coverage and reference reconciliation are different checks.

## Sections

Use actual bookmarks, table-of-contents entries, or explicit headings. Page ranges must be ordered and within the PDF. Remove `candidate: true` after review.

## Translations

```json
{
  "schema_version": "2.2",
  "language": "zh-CN",
  "pages": {
    "4": {
      "status": "complete",
      "blocks": {
        "p004-b001": "完整段落译文。",
        "p004-b002": "下一段完整译文。"
      }
    }
  }
}
```

`complete` means every translatable `prose` block on that page has a non-empty translation. Use `partial` otherwise. A block with `translatable: false` is quarantined and must not appear in a translation patch. Formula-reference blocks are not translated; annotated formulas use exact source crops. Captions may be translated, but the original visual and caption remain available.
