# Zotero Literature Radar

Zotero Literature Radar is a Codex skill for turning Zotero RSS/feed subscriptions into configurable literature screening reports. It reads recent Zotero feed items, scores them against user-defined research topics, writes a Markdown report, and can optionally dry-run and import selected papers into Zotero collections.

The current version does not require Zotero MCP. It uses local Zotero SQLite for read-only feed/report generation and Zotero Web API for confirmed write/import workflows.

## Features

- Generate Markdown literature radar reports from Zotero RSS/feed items.
- Configure research themes with A/B/C topic tiers, precision gates, keywords, ignore patterns, and display limits.
- Prefer fresh Top 3 and A-tier recommendations using a local recommendation cache.
- Show current Zotero import status from a verified import cache.
- Polish report prose through Codex after the script produces a structured draft.
- Dry-run Zotero imports before writing.
- Import Top 3, A-tier, or Top3+A papers into a Zotero collection after confirmation.
- Store Chinese title translations in Zotero `Extra` as `titleTranslation: ...`.
- Keep runtime state inside the report output directory instead of the skill directory.

## Requirements

- Codex desktop or another Codex environment that supports local skills.
- Zotero desktop with RSS/feed subscriptions already configured.
- Python 3.10 or newer. Python 3.11+ is recommended.
- No required third-party Python packages; scripts use the Python standard library.
- For report generation: readable local Zotero `zotero.sqlite`.
- For Zotero imports/writes: Zotero Web API credentials in environment variables.

Report generation does not require a Zotero Web API key.

## Install

Copy this folder into your Codex skills directory:

```text
~/.codex/skills/zotero-literature-radar
```

On Windows, this is usually:

```text
%USERPROFILE%\.codex\skills\zotero-literature-radar
```

The skill directory must contain `SKILL.md` at its root.

## Configure Zotero Reads

The report generator looks for Zotero SQLite in common locations:

```text
%USERPROFILE%\Zotero\zotero.sqlite
~/Zotero/zotero.sqlite
%APPDATA%\Zotero\zotero.sqlite
```

You can override this with:

```text
ZOTERO_DB_PATH=/path/to/zotero.sqlite
```

or by setting `zotero_sqlite` in the workspace theme file.

## Configure Zotero Writes

Only import/write workflows require Zotero Web API credentials:

```text
ZOTERO_API_KEY=your_zotero_api_key
ZOTERO_LIBRARY_ID=your_library_id
ZOTERO_LIBRARY_TYPE=user
```

Use `ZOTERO_LIBRARY_TYPE=group` for group libraries.

Do not store API keys in Obsidian notes, Git repositories, or skill files.

## Workspace Theme

Each workspace should have its own theme file:

```text
.codex/zotero-literature-radar/research-theme.md
```

If the file is missing, the skill initializes it from `templates/research-theme.md`.

The theme contains one JSON block. Important fields:

- `lookback_days`: feed window in days.
- `output_dir`: report folder, relative to the workspace unless absolute.
- `max_items_per_tier`: displayed A/B/C paper limits.
- `ignore_title_patterns`: regex patterns for non-paper feed entries.
- `ignore_topic_patterns`: regex patterns for irrelevant topics.
- `topics`: scoring topics with `tier`, `weight`, `required_any`, and `keywords`.

Example themes are in `examples/`.

## Generate A Report

In Codex, ask:

```text
Use $zotero-literature-radar to generate a weekly Zotero subscription paper report.
```

The default report path is:

```text
<output_dir>/Zotero论文订阅周报-YYYY-MM-DD.md
```

If a same-day report already exists, the script writes:

```text
Zotero论文订阅周报-YYYY-MM-DD-02.md
Zotero论文订阅周报-YYYY-MM-DD-03.md
```

Runtime state is stored under:

```text
<output_dir>/.zotero-literature-radar/
```

This runtime directory is not intended for manual note-taking.

## Import Papers Into Zotero

Imports are intentionally two-step.

First ask Codex for a dry-run, for example:

```text
Use $zotero-literature-radar to dry-run import the Top3 papers from this report into Codex_Filter_Database/99_To_Read.
```

Review the dry-run plan. Only after confirmation should Codex execute the plan and write to Zotero.

The import workflow can:

- Resolve the target collection.
- Detect active existing items.
- Detect deleted/trash conflicts.
- Create new journalArticle items.
- Restore deleted/trash items when explicitly confirmed.
- Add tags and collection membership.
- Write Chinese title translations only to `Extra` as `titleTranslation: ...`.
- Update `imported-items.json` only after read-back verification succeeds.

## Obsidian Workflow

This skill works well when your Codex workspace is an Obsidian vault.

Recommended vault layout:

```text
your-vault/
  .codex/zotero-literature-radar/research-theme.md
  Literature Radar Reports/
  Reading Notes/
```

For Chinese vaults, these names are also natural:

```text
论文追踪周报/
论文阅读报告/
```

Suggested workflow:

- Generate weekly reports into a dedicated report folder.
- Read and search the reports directly in Obsidian.
- Link each Top 3 paper to a separate reading note when you decide to read it deeply.
- Keep screening reasons in Markdown reports, not in Zotero metadata.
- Keep runtime cache files out of normal note workflows.

Suggested frontmatter for manually curated report notes:

```yaml
---
type: literature-radar
source: zotero-rss
date: 2026-01-01
tags:
  - zotero
  - literature-radar
---
```

If you sync your Obsidian vault to GitHub, ignore generated reports, runtime caches, import plans, API keys, and private notes unless you intentionally want to publish them.

## Automation Prompt

A compact weekly automation prompt can be:

```text
Use $zotero-literature-radar to generate a weekly Zotero subscription paper report. After finishing, briefly report the generated Markdown path, raw item count, selected item count, A/B/C total counts, A/B/C displayed counts, and this week's three most worth-reading paper titles.
```

Keep Zotero imports as a separate confirmed workflow unless you intentionally want a dry-run after report generation.

## What This Skill Does Not Require

- It does not require Zotero MCP.
- It does not require pyzotero.
- It does not require a local web server.
- It does not download PDFs by default.
- It does not write to Zotero during report generation.

## Safety Notes

- Local Zotero SQLite is treated as read-only.
- Zotero writes use Web API credentials from environment variables.
- Dry-run comes before every Zotero write/import.
- Deleted/trash matches are treated as conflicts and require user confirmation.
- The import cache records history, but report generation verifies current Zotero state before display.

