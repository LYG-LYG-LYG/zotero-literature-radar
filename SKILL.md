---
name: zotero-literature-radar
description: Generate configurable Zotero RSS/feed literature screening reports and Zotero literature-radar maintenance across any workspace. Use when Codex needs to read Zotero feed/subscription items, classify papers by user-editable research topics, produce A/B/C literature radar summaries, create Markdown reports in the active workspace, dry-run or import selected papers from reports or paper lists/files into Zotero collections with deleted/trash-aware duplicate checks and restore-mode metadata choices, or coordinate Zotero read/write operations with local Zotero preferred for reads and Zotero Web API preferred for writes.
---

# Zotero Literature Radar

## Purpose

Generate a Markdown literature radar report from Zotero RSS/feed items. The workflow is designed for recurring Codex automations and ad-hoc research monitoring in any workspace: read Zotero in read-only mode, classify feed items with a user-editable topic strategy, and write a dated `.md` report into the active workspace.

## Files And Configuration

- Use `scripts/generate_report.py` for report generation, `scripts/import_to_zotero.py` for dry-run/execute Zotero imports, and `scripts/update_import_cache.py` for recording verified Zotero import results.
- Treat `.codex/zotero-literature-radar/research-theme.md` in the active workspace as the only workspace theme source of truth.
- If the workspace theme is missing, initialize it from `%USERPROFILE%\.codex\zotero-literature-radar\research-theme.md` when present, otherwise from `templates/research-theme.md`.
- Runtime state lives under `<output_dir>/.zotero-literature-radar/`, where `output_dir` comes from `research-theme.md`.
- Report generation reads and writes `<output_dir>/.zotero-literature-radar/recommended-items.json` for recommendation history.
- Report generation reads `<output_dir>/.zotero-literature-radar/imported-items.json` as historical import status, then best-effort verifies cached Zotero keys for current display.
- Import dry-run plans and import-cache update payloads live under `<output_dir>/.zotero-literature-radar/import-plans/`.
- Read Zotero Web API credentials only from `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, and `ZOTERO_LIBRARY_TYPE` (`user` by default). Do not read notes, Markdown files, repository files, or other local documents for API keys unless the user explicitly asks for that fallback in the current turn.

## Zotero Access Policy

- Prefer local Zotero for reads: RSS/feed scans, metadata lookup, local full text, annotations, and collection inspection should use local Zotero/MCP/local DB when available.
- Prefer Zotero Web API for writes: creating, updating, deleting, tagging, moving collections, and other library mutations should use Zotero Web API credentials from environment variables.
- Treat local `zotero.sqlite` as read-only unless the user explicitly asks for local database maintenance and accepts the risk.
- When reading local `zotero.sqlite` while Zotero is running, account for SQLite WAL state. Prefer a read-only connection that sees current WAL contents, or copy `zotero.sqlite`, `zotero.sqlite-wal`, and `zotero.sqlite-shm` together before final status checks.
- For any requested Zotero write/import from a report or paper list/file, produce a dry-run plan first and wait for explicit user confirmation before mutating Zotero.
- Never delete parent items when the user asked to delete only attachments.

## Report Generation Workflow

Use this workflow when the user asks to generate, refresh, or update a Zotero subscription report. Report generation alone must not write Zotero.

1. Read `.codex/zotero-literature-radar/research-theme.md`; if missing, initialize it from the user-global theme or built-in template.
2. Resolve `output_dir`, then use `<output_dir>/.zotero-literature-radar/` as the runtime state directory.
3. Read Zotero RSS/feed entries and metadata from local Zotero in read-only mode.
4. Screen entries by the configured topics and A/B/C tier strategy.
5. Read runtime `recommended-items.json` for Top 3 and A-tier freshness ordering.
6. Read runtime `imported-items.json` as historical Zotero import status, then verify cached `zotero_key` values in read-only mode before displaying current import status.
7. Generate a Markdown report in the active workspace, using numbered same-day filenames instead of overwriting older reports.
8. After the report file is written, update only runtime `recommended-items.json`.
9. If the script summary says `polish_required: true`, run the Report Polish Workflow on the generated Markdown before treating the report as complete.
10. Report the generated path, raw item count, selected item count, A/B/C total counts, A/B/C displayed counts, and the three most worth-reading titles.

Example command:

```powershell
& '<python>' '<skill-dir>\scripts\generate_report.py' `
  --workspace '<workspace>'
```

Use `--theme '<path>\research-theme.md'` only when the workspace default theme should be overridden.

## Topic Strategy

Read `references/topic-config.md` when editing research themes, precision rules, A/B/C item limits, report output expectations, runtime state paths, or the relationship between the 7-day feed window and recommendation freshness.

Core fields in the JSON block inside `research-theme.md`:

- `lookback_days`: feed window to scan.
- `output_dir`: report folder, relative to workspace unless absolute.
- `max_items_per_tier`: A/B/C display limits.
- `zotero_sqlite`: optional local Zotero database path; omit it to use `ZOTERO_DB_PATH` or common local Zotero paths.
- `ignore_title_patterns`: regex patterns for non-paper feed items.
- `ignore_topic_patterns`: regex patterns for off-topic items.
- `topics[]`: scoring topics.

Each topic has:

- `tier`: default A/B/C classification.
- `weight`: score contribution per matched keyword.
- `required_any`: precision gate; when non-empty, at least one term must match.
- `keywords`: recall/scoring terms.

Use A for directly thesis-relevant topics, B for method-adjacent topics, and C for implementation or background supplements. Avoid hardcoding user topics in scripts.

## Report Freshness And Ranking

- Keep `lookback_days` as the candidate discovery window. Freshness only changes Top 3 and A-tier display ordering; it does not remove candidates from A/B/C totals.
- Key recommendation-cache papers by DOI first, then IEEE document ID, then URL, then normalized title hash.
- Top 3 should prefer high-scoring papers not previously recommended. If fewer than three new recommendations exist, fill remaining slots with still-relevant repeated papers and label them as repeated.
- A-tier display should prefer papers not previously displayed in A tier. A-tier totals still count every A candidate in the current feed window. B and C do not use freshness filtering.
- Category ranks are computed before freshness reordering and before `max_items_per_tier` truncation. Treat `A1`, `B1`, and `C1` as display numbers only.
- Every displayed paper should show both recommendation status and import status.

## Import Status Verification

Report generation must treat `imported-items.json` as history, not as final truth. A paper that was imported earlier may have been deleted or moved by the user later.

- Verify only cached entries that have a `zotero_key` and an active historical status such as `imported`, `restored`, or `active_existing`.
- Prefer local Zotero SQLite read-only key checks: query `items.key` and `deletedItems` to distinguish active, deleted/trash, and missing keys.
- Local key checks must use a short SQLite timeout and `PRAGMA busy_timeout` (about 0.5 seconds for report generation) so Zotero desktop locks do not stall automation.
- If a live local read is locked or raises `sqlite3.OperationalError`, close it and retry with an `immutable=1` read-only connection. If live and immutable checks both fail, mark the key as verification `error` rather than aborting the report.
- If the local key is missing or local verification errors and Zotero Web API credentials are available, use a bounded `/items/{key}` lookup as fallback.
- Do not do title search, full-library scans, duplicate checks, imports, restores, deletes, or cache writes during report generation.
- Show verified current state in the report: active remains `已导入 Zotero（KEY）` or equivalent; deleted/trash becomes `曾导入，现已在 Zotero 回收站/已删除（KEY）`; missing becomes `曾导入，现未找到（KEY）`; verification failure becomes `导入状态待复核（KEY）`.
- Verification failures must not stop report generation. Surface them as warnings in the report summary and JSON summary.
- Do not write deleted/missing/error verification results back to `imported-items.json`; that cache is updated only by confirmed Zotero import/write workflows.

## Report Polish Workflow

Use this workflow after `scripts/generate_report.py` creates a report. The script creates the screening, ranking, and structured draft; Codex must do the final Chinese writing pass in the same thread.

- Read the generated Markdown report and rewrite only report prose fields. Do not write Zotero, do not update `imported-items.json`, and do not change recommendation-cache state.
- Polish every displayed paper title into fluent Chinese: Top 3, A, B, and C sections all need a natural Chinese title.
- Polish abstracts only for Top 3 and displayed A-tier papers. Use the full English abstract in the report draft and produce a readable Chinese abstract, not word-by-word glossary substitution.
- Keep B-tier abstracts in English only. Do not add Chinese abstracts or Chinese key-point summaries for B-tier papers.
- C-tier papers should show Chinese title, screening reason, and bolded matched keywords only. Do not show abstracts for C-tier papers.
- Preserve English titles, links, DOI, rank lines, recommendation status, import status, and other factual metadata exactly unless there is an obvious formatting error.
- Keep matched keywords bolded where the script emits Markdown bold markers, especially in B and C sections.
- Treat the built-in glossary as terminology guidance only. It must not be used as final sentence translation, and generic single-word replacements such as `of`, `and`, `in`, `with`, and `for` must not appear as mechanical Chinese fragments in the final report.

## Zotero Import Workflow

Use this workflow only when the user explicitly asks to write, import, create, update, tag, move, restore, or add Zotero items from a report or another paper list/file. Do not regenerate a report unless the user explicitly asks.

For imports from this skill's own weekly report, prefer `scripts/import_to_zotero.py`. v1 supports report Markdown scopes `top3`, `a`, and `top3+a`. It does not download PDFs or create Zotero notes.

Example dry-run:

```powershell
& '<python>' '<skill-dir>\scripts\import_to_zotero.py' `
  --workspace '<workspace>' `
  --source '<workspace>\Literature Radar Reports\Zotero论文订阅周报-YYYY-MM-DD.md' `
  --scope top3 `
  --collection 'Codex_Filter_Database/99_To_Read'
```

Example execute after reviewing the plan:

```powershell
& '<python>' '<skill-dir>\scripts\import_to_zotero.py' `
  --workspace '<workspace>' `
  --execute `
  --plan '<workspace>\Literature Radar Reports\.zotero-literature-radar\import-plans\import-plan-YYYY-MM-DD-HHMMSS.json'
```

Import rules:

- The dry-run must parse source entries, enrich metadata from local Zotero/feed data when available, resolve the target collection by path/name through Zotero Web API, perform duplicate checks, and stop for confirmation.
- When parsing Top 3 entries from a radar report, read `类别内排名：A/B/C 档第 n / 共 m（分数：x）` as the tier hint. A Top 3 paper marked `A 档` must carry `tier=A`, `is_a=true`, and the `A档` tag even if it is not repeated in the displayed A-tier section.
- The requested collection path/name is authoritative. Cached collection keys from runtime `imported-items.json`, prior dry-runs, notes, or chat history are only hints and must be revalidated.
- Duplicate checks must distinguish active parent items, deleted/trash parent items, and attachment-only matches.
- Use bounded query strategy: target collection first, then exact identifiers such as item key, DOI, IEEE document ID, arXiv ID, and URL. Use title search only as fallback.
- On timeout, rate limit, or partial API failure, continue the dry-run with confirmed results and mark `query_degraded`, `unresolved_items`, and `fallback_skipped_reason`.
- Dry-runs must not update `recommended-items.json` or `imported-items.json`.
- `--execute` requires a dry-run plan file and must not write Zotero directly from Markdown.
- After every Zotero write, read the item back and verify deleted state, target collection, tags, DOI/metadata changes when applicable, and `titleTranslation:`.
- Only after read-back verification succeeds, update runtime `imported-items.json` through `scripts/update_import_cache.py`.

## Deleted/Trash And Restore Rules

- Zotero deletion is a soft-delete. A DB/API match is active only when the local item has no `deletedItems` row and the Web API item has no `data.deleted = 1`.
- A collection relationship is not enough to prove active presence. Deleted/trash matches remain conflicts even when their `collections` contains the target collection.
- Do not count PDFs, snapshots, or child items as existing parent papers.
- By default, deleted/trash matches require user decision. Do not restore, overwrite, or recreate until the user explicitly chooses restore, recreate, or skip.
- Restore supports `minimal restore` and `restore + full metadata update`.
- If the user only says to restore original items, recommend `restore + full metadata update`, list exact old/new/source field changes, and allow `minimal restore`.

## Title Translation Storage

- Zotero has no native `titleTranslation` field in the standard item schema; use the existing Zotero/Jasminum-style `Extra` convention: `titleTranslation: <Chinese title>`.
- Write Chinese titles only to `titleTranslation:`. Do not put Chinese titles in `title`, `shortTitle`, `Chinese Title:`, notes, or other custom Extra lines unless the user explicitly asks.
- Preserve an existing `titleTranslation:` by default. Overwrite it only when the dry-run clearly lists old and new values and the user confirms.
- Do not write `Screening Reason:`, `Source Feed:`, `Codex Radar Rank:`, or report file names into Zotero item metadata by default.
- Write Chinese text through a UTF-8-safe JSON body/file or escaped Unicode path. After writing, immediately read back the item and treat all-question-mark values, `??` tags, or mojibake as failures.

## Workflow Routing

- Report request only: run report generation and do not write Zotero.
- Import/write request only: run only the Zotero Import Workflow and stop at dry-run unless the user has already confirmed a plan.
- Report plus import in one turn: generate the report first, then stop at the import dry-run.
- Ambiguous import source: locate likely reports/files in the active workspace and ask the user to choose before building the dry-run.

## Weekly Automation Contract

Recurring weekly report automations should keep their prompt minimal and rely on this skill for execution details:

`使用 $zotero-literature-radar 生成每周 Zotero 订阅论文周报。完成后在当前线程简短汇报：生成的 md 文件路径、原始条目数、入选条目数、A/B/C 总数、A/B/C 展示数量，以及本周最值得精读的 3 篇标题。`

If a future task requires writing to Zotero, use Zotero Web API environment variables first and avoid reading workspace key notes or repository files unless explicitly requested.
