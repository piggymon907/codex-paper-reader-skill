---
name: paper-reader
description: Build or update a traceable scientific-PDF reader with a large faithful original-page view, page overviews and annotations, full-paper figure navigation, formula teaching, exact paragraph-bound evidence, formula-safe translations, contextual questions, and optional experimental-data provenance prompts. Use for biology, physics, biophysics, or other technical papers when the user wants rigorous graduate-level reading support without PPT generation, image generation, automatic external literature review, or a costly multi-agent workflow.
---

# Paper Reader

Tooling release: `2.7.1`. Keep the builder and validator from the same installed release.

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

1. Initialize resumable run tracking and establish coverage.
   - Create one paper-specific work directory and initialize it before extraction:

     ```bash
     python scripts/run_tracker.py init --work-dir WORK --input PAPER.pdf
     ```

   - Reuse the work directory only when the input hash, Skill version, and schema version still
     match. Otherwise start a new work directory; never silently reuse stale checkpoints.
   - Treat recorded phase durations as wall-clock elapsed time that may include tool waits,
     pauses, or reconnection gaps. Do not call them model-compute time. The host reconnect event
     itself may remain unavailable.
   - Pass model, reasoning effort, Fast state, translation scope, and reuse mode only when known;
     omit unavailable values so they remain `null`. If these conditions change after a resume,
     update them once with `run_tracker.py context`; do not infer them from elapsed time.
   - List the main PDF, supplements, and appendices actually provided.
   - Report missing, encrypted, unreadable, or excluded material.
   - Do not imply that cited external papers were examined.

2. Extract and render every page.

   ```bash
   python scripts/extract_paper.py PAPER.pdf --out-dir WORK/paper --run-dir WORK
   ```

   The script uses `pypdf` for reading text and `pdfplumber` for geometry. Read the text-quality signals, unmatched figure/table references, and damaged-formula counts before translating. Do not translate quarantined blocks. If glued words, `(cid:...)`, control characters, or unknown glyphs remain in a translatable block, fix extraction or mark the page unsupported.
   Keep every automatic formula candidate in the index, but do not visually inspect every low-value
   false positive. Review every `high` candidate and every equation promoted by the paper's own
   numbering, downstream references, figure dependencies, or main argument. During the normal
   whole-paper read, promote any scientifically necessary unnumbered equation regardless of its
   automatic rank. Inspect at least one non-key `low` or `damaged` candidate to calibrate the
   detector, then report the remaining ranked counts instead of opening them one by one.

3. Inspect the paper visually.
   - Inspect every page containing a numbered figure, table, scheme, or scientific diagram.
   - Inspect at least one dense prose page and every page containing a key displayed equation.
   - Review each automatic visual candidate. Add a reasoned exclusion only for decoration or a false caption match.
   - Reconcile `visual_references` against caption candidates. Resolve each unmatched internal reference or record a specific reviewed exclusion; never call candidate coverage “complete paper coverage” by itself.

4. Create the notes skeleton.

   ```bash
   python scripts/make_notes_template.py \
     --paper-index WORK/paper/paper_index.json \
     --out WORK/reader_notes.json \
     --run-dir WORK
   ```

   Read [references/data-contract.md](references/data-contract.md) before editing notes.
   The tracker closes context indexing and starts content analysis when the skeleton is created.
   During the same whole-paper structural scan, create the marker inventory for every scientific
   figure, table, and selected formula: assign its page, stable ID, `content_type`, source label,
   and paper-specific title before drafting long prose. Then initialize the teaching-audit
   skeleton from that inventory:

   ```bash
   python scripts/teaching_audit.py init \
     --notes WORK/reader_notes.json \
     --out WORK/teaching_audit.json \
     --run-dir WORK
   ```

   Classify every audit item before drafting long prose. Use `standard` only for a direct,
   single-operation object that is not central to a main claim and has no consequential panel,
   branch, cross-page, or downstream dependency. Use `full` whenever any explicit trigger applies:
   multi-panel/multi-condition structure, a reasoning chain, a main claim, downstream dependency,
   cross-page context, or a source conflict. A multi-panel or reasoning-heavy object cannot be
   downgraded to `standard`, and the decision must not depend on a hidden `teaching_priority` flag.

   Do not treat the audit as a second analysis pass. For each source object, inspect one evidence
   packet—crop, caption, necessary earlier definitions, and the later passage that interprets it—
   then fill the single delivered marker and its compact audit links together. The audit stores
   exact links into the marker, never a second copy of the answer. Generalization testing across
   other papers is a release-development activity, not part of a user's normal build.
   Save notes after each natural completed section or source object, then checkpoint the saved
   IDs in one local call. Do not impose a fixed item count and do not checkpoint unsaved text:

   ```bash
   python scripts/run_tracker.py checkpoint \
     --work-dir WORK --stage content_analysis \
     --item FIGURE-2 --item EQ-8 --artifact WORK/reader_notes.json
   ```

   Leave unavailable phases as `null`; do not invent token or timing values.
   Set `paper.experimental_data_status` to `present`, `absent`, or `uncertain` while reviewing the paper. Count only measurements produced by physical, biological, clinical, or instrument-based experiments, including reused public experimental measurements. Do not count simulations, theoretical calculations, model outputs, code, or literature parameters as experimental data.

5. Write useful, source-traceable explanations.
   - Use paper-specific titles.
   - Make the first sentence of `takeaway` identify a figure, table, or key formula when its subject would otherwise be ambiguous: use the source label (`Figure 2`, `Table 1`, `Eq. 8`) or a natural phrase such as “这张双面板图” or “该公式”. Continue naming the object wherever it improves clarity, but do not force every subsection or reading step to repeat the prefix.
   - Annotate for information gain, not page symmetry. A normal prose page usually needs 2-4 high-value markers; a reference-only page normally needs none. Keep mandatory coverage for every scientific figure and table.
   - Write for a research graduate student who may not already know this paper. Be technical and explicit without becoming childish; avoid decorative analogies.
   - Diagnose the reasoning gap behind hard prose: supply omitted definitions, variable roles, dependency order, comparison baseline, and the link between a displayed result and the claim. Do not merely repair grammar or restate compressed source wording.
   - Draft one marker from the source inventory. Keep `takeaway`, `how_to_read`, `supports`, and `does_not_support` independently useful in the sidebar; let the same marker's `prerequisites`, panel/symbol detail, derivation/dependency steps, and paper-specific sections provide the expanded teaching view. Never generate a separate sidebar version.
   - For a full-audit figure/table, explicitly teach: what the object is for; what variables, axes, groups, or baselines mean; the order in which to read components; whether one panel or processing step supplies quantities used by another; the consequential observations; how those observations support the stated conclusion; and the evidence boundary. For a full-audit formula, replace panel order with algebraic/branch/dependency order and downstream use.
   - Keep a non-trivial text or method marker self-contained enough to understand in the sidebar. A short marker may use roughly 200-500 Chinese characters across its structured fields, but never compress it into unexplained noun phrases.
   - Use roughly 450-900 Chinese characters for a simple scientific figure/table and 800-1600 for a key multi-panel or reasoning-heavy visual when that depth is necessary. These are effort guides, not UI truncation limits or hard validation thresholds.
   - For a key formula, normally include the equation crop, a complete-sentence takeaway, symbol meanings and units, dependency/derivation steps, applicable branch or range, common misreadings, and its downstream use. Use roughly 500-1200 Chinese characters when the formula is central; length alone is only a warning.
   - Store optional teaching fields as `prerequisites`, `reading_steps`, `key_values`, `symbols`, `derivation_steps`, `common_misreadings`, `source_checks`, and paper-specific `detail_sections`. Read [references/data-contract.md](references/data-contract.md) for their shapes.
   - State how to read the item, what it supports, what it does not support, and relevant assumptions or alternatives.
   - Keep `takeaway`, `how_to_read`, `explanation`, `supports`, and `does_not_support` non-duplicative; remove a marker that only rephrases its source.
   - Preserve comparison conditions, controls, statistical units, processing steps, and author qualifications.
   - Keep `direct`, `inference`, and `unknown` distinct.
   - For every `direct` marker, use a verbatim `source_text` excerpt and bind it to exact `block_ids`; never put a paraphrase in `source_text`.
   - Map each note to exact source coordinates. Use `visual_bbox` for the figure/table/formula crop and `bboxes` for caption or supporting passages.
   - When the paper itself contains a numerical, symbol, branch-label, or cross-reference conflict encountered during reading, mark it as unresolved instead of silently choosing an interpretation. Do not promise an exhaustive external peer review.
   - Add `experimental_data` only to a marker that actually uses experimental measurements or has a specific unresolved experimental-data lead. Do not add disabled or negative marker-level entries merely to fill the schema. Record its role and the exact Methods, caption, data-availability, supplement, repository, or source-paper clues already visible in the provided material.

   For every figure, table, and formula, complete these core checks during the first draft:

   1. Link to prose that identifies the object and its scientific question or operation.
   2. Link to the reading/use order rather than listing panel labels or symbols alone.
   3. Link to the explicit bridge from source observation/relation to the paper's conclusion.
   4. Link to what the object supports, does not support, and cannot resolve from the provided source.

   For every `full` item, additionally link to (a) the required background, variables, comparison
   baseline, units, or branch condition and (b) the panel, processing, algebraic, or downstream
   dependency chain. These checks must already be answered in the delivered marker.

   Record every source component, encoding/symbol, and consequential numerical/condition label in
   `source_inventory`; link each to a `coverage` record. Every item needs an original-crop/context
   `source_fidelity` factual check. A `full` item also needs a `reasoning_fidelity` check against the
   source and necessary context. A learner check contains only `note_field` and an exact
   `teaching_evidence` substring—never an `answer` copy. A component may be
   `bounded_source_limit` only with a specific reason and location; `missing`, `contradicted`, or
   `revise` cannot proceed to packaging. Do not invent content to make the audit pass.

   After the one-pass object analysis, run the audit checker:

   ```bash
   python scripts/teaching_audit.py check \
     --notes WORK/reader_notes.json \
     --audit WORK/teaching_audit.json \
     --out WORK/teaching-audit-report.json \
     --run-dir WORK
   ```

   If it fails, reopen only the listed object and make a targeted correction. Do not reread or
   regenerate every object. The report hash-binds the final teaching fields; if any teaching prose
   changes afterward, rerun this local checker.

   After drafting notes, bind every unique verbatim excerpt deterministically:

   ```bash
   python scripts/bind_evidence.py \
     --paper-index WORK/paper/paper_index.json \
     --notes WORK/reader_notes.json \
     --out WORK/reader_notes.bound.json \
     --run-dir WORK
   ```

   Review only the reported ambiguous or unmatched markers, then build from the bound file.
   Run the mechanical preflight before packaging. It checks schema, IDs, exact evidence binding,
   coordinates, required fields, and visual coverage; it does not decide scientific priority or
   prove interpretation quality:

   ```bash
   python scripts/preflight_notes.py \
     --paper-index WORK/paper/paper_index.json \
     --notes WORK/reader_notes.bound.json \
     --out WORK/preflight-report.json \
     --run-dir WORK
   ```

   Fix hard preflight errors. Treat length and optional object-naming findings as warnings, not
   reasons to pad prose or mechanically rewrite every subsection.

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
     --notes WORK/reader_notes.bound.json \
     --translations WORK/translations.json \
     --teaching-audit-report WORK/teaching-audit-report.json \
     --output-root OUTPUT \
     --run-dir WORK \
     --force

   # Use the exact OUTPUT_DIR printed by build_reader.py.
   python scripts/validate_reader.py OUTPUT/PRINTED-PAPER-READER-DIRECTORY --strict
   ```

   For a normal full build, use `--output-root`; the builder deterministically creates
   `<paper-title>-paper-reader-v2.7.1` with a path-safe, length-limited title. Keep
   `--out-dir` only for updating a known existing reader or for an explicitly chosen
   destination. Do not collapse new readers into a generic `reader` folder. Do not create
   a ZIP, README, or separate share package unless the user asks for one.

   The builder records the Skill and builder versions plus extraction-quality counters in
   `run_manifest.json`. The matching validator rejects a missing or mismatched version and
   cross-checks its observed text-quality counts against both the packaged paper index and
   the build manifest before writing the final report. These checks are local JSON/string
   comparisons; they must not trigger PDF re-extraction or model work.

   Read [references/quality-gates.md](references/quality-gates.md). Treat structural validation, exact source alignment, and scientific correctness as separate evidence. A structural `pass` never proves the interpretation scientifically correct.

9. Test the packaged HTML with tiered QA.
   - Give every new paper a short content/layout-driven browser smoke test with a five-minute target
     and hard stop. Check one representative reading page and overview, one annotation and return
     action, one representative figure, one key formula when present, one source-PDF link, and one
     contextual question payload. Select the crop with the most unusual aspect ratio when that is
     the main layout risk. Do not reread scientific content or re-exercise every fixed control in
     this per-paper smoke test. If the time box expires or a host/tool failure prevents completion,
     record a failed smoke with the exact untested checks instead of spending an open-ended hour.
   - Run the full browser regression only when the UI asset hash, schema, or interaction code
     changed, when smoke testing fails, or when the user explicitly asks. The full regression
     checks first/middle/last figures, wide and tall formulas, complete/partial/missing bilingual
     states when present, all navigation controls, desktop/narrow layouts, and question fallbacks.
   - Record what was actually checked; do not turn an unperformed full regression into a pass:

     ```bash
     python scripts/run_tracker.py start \
       --work-dir OUTPUT/PRINTED-PAPER-READER-DIRECTORY --stage browser_smoke
     # Perform the browser checks.
     python scripts/run_tracker.py qa \
       --work-dir OUTPUT/PRINTED-PAPER-READER-DIRECTORY --level smoke --status pass \
       --check reading --check annotation-return --check figure \
       --check formula --check source-link --check contextual-question
     ```

10. Report honestly.
   - Report pages rendered and pages visually inspected.
   - Report figure/table candidate count, explained count, and exclusions.
   - Report markers and translation coverage.
   - Report automatic formula detection separately from manual formula review.
   - Report teaching-audit item count, targeted corrections, bounded source limits, and warnings.
   - Report full-audit trigger counts and teaching-character distributions as diagnostics only;
     neither is a scientific-quality score or a hard length gate.
   - Use automatically recorded content-analysis milestones and targeted-revision timing. Do not
     add per-object timers or extra model passes merely to obtain more granular timing.
   - Read `build_report.md`, `validation-report.json`, and `qa-report.json` when present. Report their exact warning categories instead of regrouping them from memory.
   - Report validation layers, remaining manual checks, the material actually provided, elapsed phases, and unavailable token accounting.
   - Do not load a separate planning Skill for a normal run after native checkpoints are active. An unusually long or failing task may still use one; planning tools are not a diagnosed reconnect cause.

## Required UI behavior

- Default to faithful single-page reading mode with original PDF pages. Keep the PDF column wider than either sidebar on ordinary desktop widths.
- Keep `阅读模式`, `图解模式`, and `公式精讲` as top-level views. Keep `原文` and `双语` as language choices inside reading mode; do not replace the page overview or annotations with the teaching views.
- Keep page, section, mode, marker, zoom, and original-PDF controls reachable.
- Apply markers as coordinate overlays without changing PDF line breaks.
- Put a one-click `隐藏全部标注` / `显示全部标注` control above the four category filters and keep individual filters available.
- Selecting a marker opens its explanation; provide an obvious `返回本页导读` action that keeps the page unchanged. `Esc` may provide the same return.
- Every page overview must retain a short reading purpose followed by its expandable high-value markers. Do not remove these when adding figure or formula modes.
- Use `快速结论` for the highlighted takeaway callout. Do not use countdown-style labels such as `30 秒结论`.
- Keep recurring section headings short and consistent: use `快速结论`, `如何阅读`/`建议的阅读顺序`, and `详细解释` without appending a figure, table, panel, or equation label. Keep the scientific prose unambiguous with natural source-object references instead of decorating every UI heading or repeating the same prefix mechanically.
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
- Fill the teaching note and compact audit links during that same inspection. Never repeat the
  explanation inside the audit. Use full learner/reasoning checks only for explicitly triggered
  complex or central objects; every object still receives source-inventory and core checks. Do not
  add a routine second full model pass; only audit failures receive targeted correction.
- Use OCR only when a PDF genuinely lacks a usable text layer.
- Keep translation optional and page-scoped.
- Use `update_translations.py` for an existing reader; batch requested pages and build once.
- Do not repeat browser QA or regenerate archives for translation-only data changes.
- Reuse fixed HTML/CSS/JS assets; UI rebuilds must not reread the paper.
- Keep per-paper Browser QA to the short content/layout smoke test. Do not rerun the fixed-UI suite
  when the packaged asset hash, schema, and interaction code are unchanged.
- Keep the default full-build directory paper-specific and versioned; do not use a generic
  `reader` directory when building a new paper.
- Deliver a normal clickable `index.html` folder and, when requested, a ZIP. Never use or print an app-specific `::visualization` directive as the only way to open the reader.
- Stop after one functioning package unless the user authorizes regression testing.
- Do not expand a normal build into supplement, dataset, code, or reference-list auditing.
- Do not run the cross-paper cold-reader/generalization suite during a user's normal build. It is
  a development and release gate only.
- Classify experimental-data relevance during the existing content pass. Do not browse, download, or analyze data during a normal build; the provenance button only prepares an on-demand contextual follow-up.

## References

- [references/data-contract.md](references/data-contract.md): marker, visual, section, and translation schemas.
- [references/quality-gates.md](references/quality-gates.md): content, visual-coverage, interaction, and delivery checks.
