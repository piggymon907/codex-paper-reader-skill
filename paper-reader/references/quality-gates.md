# Paper Reader quality gates

- [Source fidelity](#source-fidelity)
- [Reading-text quality](#reading-text-quality)
- [Figure and table coverage](#figure-and-table-coverage)
- [Formula safety](#formula-safety)
- [Explanations](#explanations)
- [Translation](#translation)
- [Interaction](#interaction)
- [Delivery](#delivery)

## Source fidelity

- Render every PDF page successfully.
- Default to the original page image, not extracted text.
- Keep marker overlays separate from source layout.
- Keep every source box within page bounds.
- Keep the current-page original PDF link working.
- Never label extracted text as a layout-faithful reproduction.

## Reading-text quality

- Use a text-layer extractor before OCR; OCR only pages without usable text.
- Fail on alphabetic runs of 30 or more characters caused by lost spaces.
- Fail on `(cid:...)` artifacts in displayed prose or translations.
- Reject invisible C0 controls and unknown-glyph placeholders in every translatable block.
- Quarantine damaged mathematical fragments as non-translatable formula references.
- Review suspicious punctuation/case glue, dehyphenation, headings, author metadata, and column order.
- Do not start translation until the page's English reading text passes.

## Figure and table coverage

- Review every caption-based visual candidate.
- Reconcile internal figure/table mentions independently from caption candidates; unresolved references prevent a complete claim unless reviewed as external or supplementary.
- Require each real scientific figure/table/scheme to have a marker, source crop, and explanation.
- Require an explicit reason for each excluded candidate.
- Explain purpose, encodings, panels, conditions, controls, observations, supported claims, unsupported claims, and limitations as applicable.
- Visually compare every delivered figure/table crop with its PDF page.
- Report candidate, explained, and excluded counts.
- Never describe coverage of discovered candidates as guaranteed recall of every real visual.

## Formula safety

- Keep equations, variables, indices, units, signs, superscripts, subscripts, and equation numbers in source crops.
- Never reconstruct a fragile equation from extracted text in bilingual mode.
- Treat automatic formula detection as a candidate list, not proof of complete formula coverage.
- Retain all ranked candidates, but visually review every high candidate plus every equation
  promoted by numbering, downstream references, figures, or the paper's argument. Inspect at least
  one non-key low/damaged candidate to calibrate false positives; do not open every low-ranked
  candidate mechanically.
- Report damaged automatic candidates separately. Require `formula_source_status` for every delivered formula explanation.
- Visually compare every key formula crop and at least one non-key automatic candidate.

## Explanations

- Explain the scientific issue rather than paraphrase the highlighted sentence.
- Make the explanation understandable to a research graduate student who has not already internalized this paper. Keep technical precision; do not replace reasoning with cute analogies.
- Reject compressed noun piles, unexplained symbols, missing dependency order, or a result statement that never explains how the authors obtained it.
- For each figure, table, and key formula, make `takeaway` identify the object when the subject
  would otherwise be ambiguous. Use natural object references elsewhere when helpful; do not
  force every subsection to repeat a mechanical prefix.
- Keep non-trivial text and method markers useful in the sidebar. Use roughly 450-900 Chinese characters for a simple scientific visual and 800-1600 for a key multi-panel or reasoning-heavy visual when needed. Treat these as review warnings, never hard character-count gates.
- For a key formula, include the source crop, symbol roles and units, applicable branch/range, dependency or derivation steps, downstream use, and common misreadings. Do not treat formula length as a reason to omit explanation.
- Distinguish `direct`, `inference`, and `unknown`.
- Require every `direct` marker to bind a verbatim source excerpt to stable `block_ids`.
- Preserve controls, statistical units, processing, assumptions, qualifications, and alternatives.
- For every delivered figure, table, and formula, require a completed first-pass teaching-audit
  item. Its source inventory must cover panels/components and axes/encodings or equation symbols;
  four compact learner links must point into delivered prose that identifies the object, explains
  reading/use order, connects evidence to conclusion, and states boundaries. The audit must not
  duplicate the answer.
- Require a full audit for multi-panel, multi-condition, reasoning-heavy, main-claim, dependent,
  cross-page, or source-conflicted objects. A full item additionally links prerequisites/variables
  and the panel/algebra/downstream dependency chain, and includes a reasoning-fidelity check. A
  standard item still requires complete inventory coverage and a source-fidelity check.
- Reject `missing`, `contradicted`, or `revise` audit states. Allow a bounded source limit only with
  a specific missing supplement/cited source/fragile formula reason and a visible source warning.
- Run the audit while generating the object explanation, not as a routine second full model pass.
  Reopen only failed objects. Cross-paper pedagogical evaluation is a release gate, not a per-paper
  user cost.
- A passing teaching-audit report proves that the required self-review artifact was completed and
  hash-bound. It does not prove the explanation scientifically correct.

## Translation

- Translate only requested pages or cached coverage.
- Put Chinese after the corresponding original prose block.
- Preserve symbols, units, references, names, and technical terminology.
- Mark incomplete coverage `partial`.
- Show annotated figures, tables, and formulas as exact source crops.
- Do not imply live in-page translation in the static package.

## Interaction

- Only one PDF page is active.
- Original mode is the default.
- Sticky controls remain reachable.
- Reading mode retains the page overview and expandable marker list. Figure and formula modes do not replace them.
- Section links, page controls, modes, zoom, filters, and marker selection work.
- A master marker control hides and restores all four annotation categories without removing the individual filters.
- Selecting a marker updates the analysis panel.
- `返回本页导读` clears the marker without changing pages; `Esc` provides the same route.
- Bilingual mode shows annotation chips even when block-level anchors are unavailable.
- The question composer is collapsed by default and shows its page/selection context before sending.
- Long questions grow without clipping.
- Whole-item and point-level question buttons have a visible filled tint. A point-level prepared question contains the paper, page, marker, locator, verbatim source context, current explanation, claim status, and teaching-point title.
- Experimental-data provenance actions appear only on markers with a reviewed `present` or `uncertain` experimental-data lead. They are visually distinct from ordinary question actions and prepare a context-rich follow-up that excludes simulations, models, code, and theoretical parameters.
- Figure/formula preview strips include every eligible marker in paper order and return to the exact page/marker.
- Recurring headings stay plain and consistent (`快速结论`, `如何阅读`/`建议的阅读顺序`, `详细解释`); the scientific prose names the current object often enough to stay unambiguous without repeating it mechanically in every block.
- Every `回原文核对` block can return to its selected source marker, jump to valid referenced paper pages, and open the corresponding page in the original PDF.
- Tall and narrow crops use both width and height constraints; visually confirm they are not enlarged to full-page width.
- Clipboard rejection falls back to visible manual copy.
- Desktop and narrow layouts avoid horizontal clipping.
- Reset both horizontal and vertical page-canvas scroll positions after changing pages.
- Display a compact `生成概况` sidebar disclosure with coverage, structural status, and automatic-warning count. Show a total duration only when all required phases are recorded; keep phase-level or unavailable timing details out of the user UI and in `run_manifest.json`. Confirm the visible payload matches the manifest and validation status after validation completes.
- Confirm `reader-data.json`, `run_manifest.json`, and the validator identify the same
  Paper Reader release. Recompute text-quality counters from packaged reading blocks and
  require them to match both `paper.text_extraction.quality` and
  `run_manifest.text_quality_at_build`. This is an in-memory consistency check, not a reason
  to re-extract the PDF.

## Delivery

- `validate_reader.py --strict` passes.
- Keep structural validation, direct-source alignment, and scientific correctness as separate statuses; never present a structural pass as scientific proof.
- Browser interaction and visual PDF comparison are tested separately.
- Run a content/layout-driven Browser smoke test for every new paper with a five-minute target and
  hard stop. Test one representative reading page, annotation-return path, representative figure,
  key formula when present, source link, and contextual-question payload; prefer the crop with the
  most unusual aspect ratio. Do not reread the paper in Browser or repeat every fixed control. Run
  the full fixed-UI regression only after a UI/schema/interaction change, a smoke failure, or an
  explicit request. Record the tested level, exact checks, elapsed wall time, and any untested item
  in `qa-report.json`; a time-boxed incomplete check is not a pass.
- Keep the accepted prior package unchanged until regression checks pass.
- Keep shared manifests free of absolute input and workspace paths.
- Deliver the ordinary reader folder through its `index.html` and optional ZIP. Do not depend on an app-only visualization directive.
- Report unresolved text, figure, translation, or formula limitations explicitly.
- Generate `build_report.md` from `run_manifest.json`, `validation-report.json`, and the recorded
  Browser QA. Preserve the validator's actual warning categories instead of renaming them from
  memory.
- Keep length and stylistic guidance as warnings. Hard failures cover broken schema, invalid or
  missing evidence bindings, invalid coordinates, missing required fields, uncovered visuals,
  and unsafe formula-source states.
- Preserve hashed, atomic run state and append-only phase events. Report stage durations as
  wall-clock time; do not infer model compute or reconnect causes from them.
- Report only the main paper and supplements actually provided. Do not require code, datasets, cited papers, or the entire reference list unless the user explicitly expands scope.
- Record whether the provided paper contains experimental measurements. A theory- or simulation-only paper must not gain a generic data/resource button merely because it contains model outputs or supplementary figures.
