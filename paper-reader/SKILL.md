---
name: paper-reader
description: Build or update a traceable scientific-PDF reader with a large faithful original-page view, page overviews and annotations, full-paper figure navigation, formula teaching, exact paragraph-bound evidence, formula-safe translations, contextual questions, and optional experimental-data provenance prompts. Use for biology, physics, biophysics, or other technical papers when the user wants rigorous graduate-level reading support without PPT generation, image generation, automatic external literature review, or a costly multi-agent workflow.
---

# Paper Reader

Tooling release: `2.4.0`. Keep the builder and validator from the same installed release.

## Boundaries

Build only the paper reader. Do not generate PPTs, slide cards, or decorative images. Do not start subagents by default. Use deterministic scripts for rendering, packaging, and validation.

Treat the rendered PDF page as the visual source of truth. Extracted text, translations, and explanations are aids, not substitutes for quotation, citation, fragile formulas, priority claims, or consequential interpretation.

Use one evidence object for both the reading sidebar and the full teaching view. Do not generate a short sidebar explanation and a second independent long explanation. The sidebar selects the useful summary fields; figure and formula modes reveal every structured field from the same marker.

Process the main PDF and any supplement the user actually provides. Do not fetch or audit code, datasets, cited papers, every reference, or missing supplements unless the user explicitly requests that broader research. State the available scope without treating absent external material as a failed reader build.

Use `python` in the examples as the resolved interpreter. If it is unavailable on `PATH`, use the Python path returned by the bundled Codex workspace dependency runtime; do not install a second runtime merely to follow the examples.

## Select the workflow

- **Translation patch:** Use the fast path below when an existing reader, paper index, notes file, and output directory already exist and the request only adds or replaces cached translations.
- **Full build:** Use the full workflow for a new PDF, changed extraction, changed notes, changed UI/schema, or unresolved reader failure.

Do not run the full workflow for a translation-only request.

## Translation-patch fast path

1. Confirm the existing `paper_index.json`, `reader_notes.json`, `translations.json`, and reader output. Inspect only the requested page images and text-quality signals. Do not reread the whole paper or re-review its figures, formulas, and annotations.
2. Export one patch template for all requested pages:

   ```bash
   python scripts/update_translations.py prepare \
     --paper-index WORK/paper/paper_index.json \
     --translations WORK/translations.json \
     --pages 1,2 \
     --out WORK/translation-patch.json
   ```

3. Translate all requested prose blocks in one model pass. Fill each `translation` field; keep its block ID, kind, source text, and `source_sha256` unchanged. Translate headings and captions when present. Preserve variables, numeric values, units, citations, abbreviations, email addresses, Latin species names, and established terminology. Do not translate or reconstruct `formula_reference` blocks.
4. Apply the patch and update the reader once:

   ```bash
   python scripts/update_translations.py apply \
     --paper-index WORK/paper/paper_index.json \
     --notes WORK/reader_notes.json \
     --translations WORK/translations.json \
     --patch WORK/translation-patch.json \
     --out-dir OUTPUT/EXISTING-PAPER-READER-DIRECTORY
   ```

   The script verifies source hashes, required prose coverage, protected tokens, strict reader validation, and unchanged PDF/page assets. It builds one staging package and atomically updates the known reader files.
5. If the script passes and neither UI nor schema changed, do not run browser regression, rebuild a second package, reread other pages, or regenerate a share ZIP. Run browser QA only after UI/schema changes, a validation failure, or an explicit request. Create a ZIP only when the user asks for a new distributable package.
6. Report requested pages, translated block counts, validation status, and any protected-token or unsupported-text failure. Token accounting may remain unavailable.

For several requested pages, prepare and apply one combined patch so packaging and validation happen once. Do not read the data-contract or quality-gates references for a routine translation patch unless the script reports a schema or validation problem.

## Full-build workflow

1. Establish coverage.
   - List the main PDF, supplements, and appendices actually provided.
   - Report missing, encrypted, unreadable, or excluded material.
   - Do not imply that cited external papers were examined.

2. Extract and render every page.

   ```bash
   python scripts/extract_paper.py PAPER.pdf --out-dir WORK/paper
   ```

   The script uses `pypdf` for reading text and `pdfplumber` for geometry. Read the text-quality signals, unmatched figure/table references, and damaged-formula counts before translating. Do not translate quarantined blocks. If glued words, `(cid:...)`, control characters, or unknown glyphs remain in a translatable block, fix extraction or mark the page unsupported.

3. Inspect the paper visually.
   - Inspect every page containing a numbered figure, table, scheme, or scientific diagram.
   - Inspect at least one dense prose page and every page containing a key displayed equation.
   - Review each automatic visual candidate. Add a reasoned exclusion only for decoration or a false caption match.
   - Reconcile `visual_references` against caption candidates. Resolve each unmatched internal reference or record a specific reviewed exclusion; never call candidate coverage “complete paper coverage” by itself.

4. Create the notes skeleton.

   ```bash
   python scripts/make_notes_template.py \
     --paper-index WORK/paper/paper_index.json \
     --out WORK/reader_notes.json
   ```

   Read [references/data-contract.md](references/data-contract.md) before editing notes.
   Record measured `context_indexing_seconds` and `content_analysis_seconds` under `paper.run_metrics` when available. Leave an unavailable phase as `null`; do not invent token or timing values. Packaging and validation scripts add their own wall times.
   Set `paper.experimental_data_status` to `present`, `absent`, or `uncertain` while reviewing the paper. Count only measurements produced by physical, biological, clinical, or instrument-based experiments, including reused public experimental measurements. Do not count simulations, theoretical calculations, model outputs, code, or literature parameters as experimental data.

5. Write useful, source-traceable explanations.
   - Use paper-specific titles.
   - For every figure, table, and key formula, make the first sentence of `takeaway`, `how_to_read` (or the first `reading_steps` item), and `explanation` identify its subject explicitly: use the source label when available (`Figure 2`, `Table 1`, `Eq. 8`) or a natural phrase such as “这张双面板图” or “该参数表”. State what the object shows, compares, summarizes, or defines. Identify the object once at the start of each block; do not repeat the same prefix in every later sentence or paragraph.
   - Annotate for information gain, not page symmetry. A normal prose page usually needs 2-4 high-value markers; a reference-only page normally needs none. Keep mandatory coverage for every scientific figure and table.
   - Write for a research graduate student who may not already know this paper. Be technical and explicit without becoming childish; avoid decorative analogies.
   - Diagnose the reasoning gap behind hard prose: supply omitted definitions, variable roles, dependency order, comparison baseline, and the link between a displayed result and the claim. Do not merely repair grammar or restate compressed source wording.
   - Keep a non-trivial text or method marker self-contained enough to understand in the sidebar. A short marker may use roughly 200-500 Chinese characters across its structured fields, but never compress it into unexplained noun phrases.
   - Use roughly 450-900 Chinese characters for a simple scientific figure/table and 800-1600 for a key multi-panel or reasoning-heavy visual when that depth is necessary. These are effort guides, not UI truncation limits.
   - For a key formula, normally include the equation crop, a complete-sentence takeaway, symbol meanings and units, dependency/derivation steps, applicable branch or range, common misreadings, and its downstream use. Use roughly 500-1200 Chinese characters when the formula is central.
   - Store optional teaching fields as `prerequisites`, `reading_steps`, `key_values`, `symbols`, `derivation_steps`, `common_misreadings`, `source_checks`, and paper-specific `detail_sections`. Read [references/data-contract.md](references/data-contract.md) for their shapes.
   - State how to read the item, what it supports, what it does not support, and relevant assumptions or alternatives.
   - Keep `takeaway`, `how_to_read`, `explanation`, `supports`, and `does_not_support` non-duplicative; remove a marker that only rephrases its source.
   - Preserve comparison conditions, controls, statistical units, processing steps, and author qualifications.
   - Keep `direct`, `inference`, and `unknown` distinct.
   - For every `direct` marker, use a verbatim `source_text` excerpt and bind it to exact `block_ids`; never put a paraphrase in `source_text`.
   - Map each note to exact source coordinates. Use `visual_bbox` for the figure/table/formula crop and `bboxes` for caption or supporting passages.
   - When the paper itself contains a numerical, symbol, branch-label, or cross-reference conflict encountered during reading, mark it as unresolved instead of silently choosing an interpretation. Do not promise an exhaustive external peer review.
   - Add `experimental_data` only to a marker that actually uses experimental measurements or has a specific unresolved experimental-data lead. Do not add disabled or negative marker-level entries merely to fill the schema. Record its role and the exact Methods, caption, data-availability, supplement, repository, or source-paper clues already visible in the provided material.

   After drafting notes, bind every unique verbatim excerpt deterministically:

   ```bash
   python scripts/bind_evidence.py \
     --paper-index WORK/paper/paper_index.json \
     --notes WORK/reader_notes.json \
     --out WORK/reader_notes.bound.json
   ```

   Review only the reported ambiguous or unmatched markers, then build from the bound file.

6. Cover every scientific visual.
   - Match each figure/table candidate to a `figure` or `table` marker through `visual_candidate_id`.
   - For multi-panel figures, provide an overall reading path plus panel-specific explanations when needed. Explain why panels appear in that order and whether one panel depends on quantities extracted from another.
   - Exclude only verified false positives or non-scientific decoration, with a written reason.
   - Do not call the reader complete while any visual candidate is uncovered.
   - Include quantitative values, axes, units, panels, controls, sample size, uncertainty, statistical method, fitting range, data origin, and preprocessing when the source provides them. State “not reported” rather than inventing missing details.
   - Do not infer a visual only from its caption or neighboring paragraph. Read enough prior method, variable definitions, and later interpretation to explain the complete evidence chain. When required context is elsewhere, list exact cross-page equations, methods, figures, or supplement references under `source_checks`.

7. Add translations only at requested coverage.
   - Store translations separately in `translations.json`; never replace extracted English.
   - Prefer no translation or selected pages by default. Cache by stable block ID.
   - Mark a page `complete` only when every prose block has a translation.
   - Preserve variables, units, references, and terminology.
   - Never retype formulas or redraw figures; bilingual mode uses exact source crops for annotated visuals.
   - Set `formula_source_status` on every formula marker to `verified`, `damaged`, or `not_detected`. Any status other than `verified` must require source checking.
   - The packaged HTML is static. It displays cached translations only. Do not pretend that an in-page button can stream or automatically receive a translation. A missing page may offer a copyable chat request.

8. Build and validate.

   ```bash
   python scripts/build_reader.py \
     --paper-index WORK/paper/paper_index.json \
     --notes WORK/reader_notes.json \
     --translations WORK/translations.json \
     --output-root OUTPUT \
     --force

   # Use the exact OUTPUT_DIR printed by build_reader.py.
   python scripts/validate_reader.py OUTPUT/PRINTED-PAPER-READER-DIRECTORY --strict
   ```

   For a normal full build, use `--output-root`; the builder deterministically creates
   `<paper-title>-paper-reader-v2.4.0` with a path-safe, length-limited title. Keep
   `--out-dir` only for updating a known existing reader or for an explicitly chosen
   destination. Do not collapse new readers into a generic `reader` folder. Do not create
   a ZIP, README, or separate share package unless the user asks for one.

   The builder records the Skill and builder versions plus extraction-quality counters in
   `run_manifest.json`. The matching validator rejects a missing or mismatched version and
   cross-checks its observed text-quality counts against both the packaged paper index and
   the build manifest before writing the final report. These checks are local JSON/string
   comparisons; they must not trigger PDF re-extraction or model work.

   Read [references/quality-gates.md](references/quality-gates.md). Treat structural validation, exact source alignment, and scientific correctness as separate evidence. A structural `pass` never proves the interpretation scientifically correct.

9. Test the packaged HTML.
   - Check reading mode first: navigation, zoom, section links, every annotation, current-page PDF link, the page overview, page highlights, and return-to-page-overview.
   - Check bilingual mode on one complete, one partial, and one missing page when those states exist.
   - Check figure mode with the first, a middle, and the last figure/table. Check formula mode with both a wide and a tall crop. Confirm preview navigation, aspect-fit sizing, source enlargement, return to the exact original page, and no clipped explanation.
   - Check contextual questions with and without a selected marker. Confirm the visible context includes paper, page, and selected item.
   - Check a point-level question. Confirm the prepared prompt also includes locator, verbatim source excerpt when available, current explanation, claim status, and the selected teaching-section title.
   - Check desktop and narrow layouts without horizontal clipping.

10. Report honestly.
   - Report pages rendered and pages visually inspected.
   - Report figure/table candidate count, explained count, and exclusions.
   - Report markers and translation coverage.
   - Report automatic formula detection separately from manual formula review.
   - Report validation layers, remaining manual checks, the material actually provided, elapsed phases, and unavailable token accounting.

## Required UI behavior

- Default to faithful single-page reading mode with original PDF pages. Keep the PDF column wider than either sidebar on ordinary desktop widths.
- Keep `阅读模式`, `图解模式`, and `公式精讲` as top-level views. Keep `原文` and `双语` as language choices inside reading mode; do not replace the page overview or annotations with the teaching views.
- Keep page, section, mode, marker, zoom, and original-PDF controls reachable.
- Apply markers as coordinate overlays without changing PDF line breaks.
- Put a one-click `隐藏全部标注` / `显示全部标注` control above the four category filters and keep individual filters available.
- Selecting a marker opens its explanation; provide an obvious `返回本页导读` action that keeps the page unchanged. `Esc` may provide the same return.
- Every page overview must retain a short reading purpose followed by its expandable high-value markers. Do not remove these when adding figure or formula modes.
- Use `快速结论` for the highlighted takeaway callout. Do not use countdown-style labels such as `30 秒结论`.
- Keep recurring section headings short and consistent: use `快速结论`, `如何阅读`/`建议的阅读顺序`, and `详细解释` without appending a figure, table, panel, or equation label. Put the source-object identity in the first sentence of the scientific prose instead of decorating the UI heading.
- Figure and formula modes must provide a full-paper preview strip like a slide navigator. Selecting an item shows one original source crop followed by its complete teaching explanation. Use aspect-fit constraints so tall or narrow crops do not expand to the container width and become excessively large.
- Give every whole-item and teaching-section question action a visibly filled light-green or light-blue style; do not rely on a white button against a white page.
- Show `查实验数据来源` only for markers whose `experimental_data.status` is `present` or `uncertain`. Give it a distinct muted blue treatment and visual separation from ordinary green question actions. Do not show it for theory-only, simulation-only, or model-only items.
- Make figures and tables visibly identifiable as such in the page overview.
- In bilingual mode, put Chinese after its original prose block, show annotation chips, and retain original source crops for annotated figures, tables, and formulas.
- Use the paper's actual section structure rather than a universal outline.
- Use bold, separated analysis subheadings.
- Do not show a permanent generic question box. Reveal a contextual composer only after `针对本页提问` or `针对本条注解提问` is chosen.
- Include paper title, page, selected marker, locator, verbatim source context, current explanation, claim status, and selected teaching point in the follow-up. Use `window.openai.sendFollowUpMessage` in Codex and a robust clipboard/manual-copy fallback elsewhere.
- For an experimental-data provenance follow-up, also include the recorded experimental role, origin classification, source hints, and reported identifiers. Ask only for the experimental measurements supporting the selected item; explicitly exclude simulation outputs, models, code, and theoretical parameters. If no experimental dataset exists, stop and say so instead of substituting other resources.
- Keep an explicit source-check warning.
- In every figure/formula `回原文核对` section, include an in-reader action that selects the current marker on its source page, buttons for valid cross-page `p.N` references found in the locator/check list, and a direct original-PDF page link.
- Show structural status, direct-source binding coverage, and the warning that scientific correctness is not proved by the validator as separate items.
- Show a compact collapsible `生成概况` in the left reading sidebar. Show page/figure/formula coverage, structural-validation status, and the number of automatic warnings that still need review. Show one `总耗时` only when every required phase has a reliable recorded duration; otherwise omit timing from the user UI. Keep phase-level timings in `run_manifest.json`, never display `0.0 秒` or `未记录` rows as if they were useful user metrics, and never fabricate a total.

## Cost controls

- Never call image generation or create a PPT.
- Never assign one agent per page, section, or figure.
- Scan the whole-paper structure once, then spend explanation effort on all scientific visuals plus key formulas, claims, methods, and caveats; do not allocate an equal semantic budget to every page.
- Read the paper text once and reuse its index.
- Bind verbatim evidence with `bind_evidence.py`; spend model attention only on unmatched or ambiguous items.
- Read each figure crop once and cache the explanation data.
- Use OCR only when a PDF genuinely lacks a usable text layer.
- Keep translation optional and page-scoped.
- Use `update_translations.py` for an existing reader; batch requested pages and build once.
- Do not repeat browser QA or regenerate archives for translation-only data changes.
- Reuse fixed HTML/CSS/JS assets; UI rebuilds must not reread the paper.
- Keep the default full-build directory paper-specific and versioned; do not use a generic
  `reader` directory when building a new paper.
- Deliver a normal clickable `index.html` folder and, when requested, a ZIP. Never use or print an app-specific `::visualization` directive as the only way to open the reader.
- Stop after one functioning package unless the user authorizes regression testing.
- Do not expand a normal build into supplement, dataset, code, or reference-list auditing.
- Classify experimental-data relevance during the existing content pass. Do not browse, download, or analyze data during a normal build; the provenance button only prepares an on-demand contextual follow-up.

## References

- [references/data-contract.md](references/data-contract.md): marker, visual, section, and translation schemas.
- [references/quality-gates.md](references/quality-gates.md): content, visual-coverage, interaction, and delivery checks.
