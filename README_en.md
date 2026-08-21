# Codex Paper Reader Skill

[简体中文](README.md) | English

`paper-reader` builds a local, traceable reader for scientific PDFs. It keeps the rendered PDF page as the visual source of truth and adds page overviews, coordinate-bound annotations, detailed figure/table teaching, formula explanations, optional page-scoped Chinese translations, and context-rich follow-up questions.

Current release: **2.7.1 (beta)**

> This project is an independent community Skill for Codex. It is not an official OpenAI project.

## Downloads and releases

- [Download the latest v2.7.1 package](https://github.com/piggymon907/codex-paper-reader-skill/releases/download/v2.7.1/paper-reader-v2.7.1.zip)
- [View all releases and changelogs](https://github.com/piggymon907/codex-paper-reader-skill/releases)
- [View the legacy v2.4.0 release](https://github.com/piggymon907/codex-paper-reader-skill/releases/tag/v2.4.0)

For new installations, use the release marked **Latest**.

## What it does

- Renders every provided PDF page and preserves the original layout.
- Maps explanations to exact page coordinates and verbatim source blocks.
- Provides reading, figure-teaching, and formula-teaching views.
- Explains every reviewed scientific figure/table and key formula without generating replacement artwork.
- Keeps Chinese translation optional and formula-safe.
- Prepares follow-up questions with the paper title, page, marker, source excerpt, explanation, and evidence status.
- Shows an optional **查实验数据来源** action only when a reviewed marker actually uses experimental measurements or has a specific unresolved experimental-data lead.

The experimental-data action does not automatically browse or download anything during reader construction. When selected, it prepares a focused follow-up that excludes simulations, theoretical calculations, model outputs, code, and literature-only parameters.

## What changed in 2.7.1

- Uses one source-bound teaching object for both the reading sidebar and the expanded figure/formula view, avoiding duplicate generation.
- Applies a standard/full teaching audit during the first explanation pass and repairs only failed objects.
- Records resumable checkpoints, coarse wall-clock analysis milestones, targeted-revision time, and known model/run settings without adding another model pass.
- Keeps per-paper browser QA to a short content/layout smoke test; full UI regression is reserved for interface or schema changes.
- Reports audit-trigger and teaching-length distributions for diagnosis only; they are not scientific-quality scores or hard word-count gates.

## Install

Ask Codex to install the skill from this repository's `paper-reader` directory:

```text
Install the paper-reader skill from
https://github.com/piggymon907/codex-paper-reader-skill/tree/main/paper-reader
```

Or copy the `paper-reader` directory into:

```text
$CODEX_HOME/skills/paper-reader
```

Restart or refresh Codex after a manual installation if the skill does not appear immediately.

The GitHub repository is arranged so Codex can install the `paper-reader` subdirectory directly; the repository-level README and license are not copied into the installed Skill.

## Runtime requirements

Codex Desktop may already provide the required workspace runtime. For a separate Python environment, install:

```bash
python -m pip install -r requirements.txt
```

The extraction workflow also requires Poppler's `pdftoppm` command on `PATH`. The Skill instructions tell Codex to use its bundled PDF runtime when available and to report a missing dependency instead of silently changing the workflow.

## Use

Attach a scientific PDF and ask, for example:

```text
Use $paper-reader to build a complete reader for this paper. Explain every figure and key formula. Do not translate unless I ask.
```

For an existing reader, a page-scoped translation request uses the faster translation-patch workflow rather than rebuilding and rereading the entire paper.

## Output

A normal build creates a paper-specific directory such as:

```text
Paper-Title-paper-reader-v2.7.1/
```

Open its `index.html` in a local browser. The output is static and portable as long as the complete directory is kept together.

## Scope and limitations

- Structural validation checks packaging, source alignment, text quality, and declared coverage. It does not prove the scientific interpretation correct.
- The main PDF and supplements actually supplied by the user define the default evidence scope.
- The Skill does not automatically audit missing supplements, datasets, code, cited papers, or the complete reference list.
- Formal quotation, fragile formulas, priority claims, and consequential conclusions still require checking the original PDF.
- PDF extraction quality varies. The build must stop or quarantine unsupported text rather than present damaged text as reliable prose.

## Privacy and network behavior

The packaged Skill contains no telemetry and the normal reader build does not make external network requests. Reader files remain local. A user-triggered follow-up may ask Codex to research a specific experimental-data source; any later web access is part of that explicit follow-up, not the default build.

## Repository layout

```text
paper-reader/
├── SKILL.md
├── agents/
├── assets/
├── references/
└── scripts/
```

The repository root contains user-facing installation material; the Skill directory contains only files required by the Skill itself.

## License

MIT. See [LICENSE](LICENSE).


