# Topic Configuration Reference

Use `.codex/zotero-literature-radar/research-theme.md` in the active workspace as the human-editable source of truth and runtime config.

Runtime state is separate from theme configuration:

- Theme config: `.codex/zotero-literature-radar/research-theme.md`
- Recommendation cache: `<output_dir>/.zotero-literature-radar/recommended-items.json`
- Import cache: `<output_dir>/.zotero-literature-radar/imported-items.json`
- Import plans: `<output_dir>/.zotero-literature-radar/import-plans/`

The only `.codex/zotero-literature-radar` file required by the current workflow is `research-theme.md`.

## Theme Markdown Format

Put one fenced `json` block in `research-theme.md`. Keep the block focused on research intent, not runtime history.

Common fields:

- `lookback_days`: RSS/feed discovery window in days.
- `output_dir`: report output directory, relative to the workspace unless absolute.
- `max_items_per_tier`: A/B/C display limits, for example `{ "A": 8, "B": 12, "C": 12 }`.
- `zotero_sqlite`: optional local Zotero database path; omit it to use `ZOTERO_DB_PATH` or common local Zotero paths.
- `ignore_title_patterns`: regex patterns for non-paper feed entries.
- `ignore_topic_patterns`: regex patterns for irrelevant topics.
- `topics`: topic scoring definitions.

Minimal topic:

```json
{
  "id": "my-topic",
  "name": "My research theme",
  "tier": "A",
  "weight": 5,
  "required_any": ["pmsm", "motor drive"],
  "keywords": ["efficiency optimization", "loss minimization"]
}
```

Rules:

- `required_any` is the precision gate. If the list is non-empty, at least one term must appear in the title or abstract.
- `keywords` are recall/scoring terms. At least one keyword must match.
- Higher `weight` makes the topic rank higher within its tier.
- If one paper matches several topics, the strongest tier wins: A > B > C.
- Use broad English terms because IEEE RSS metadata is usually English.
- Tighten precision by strengthening `required_any`, adding ignore patterns, reducing noisy keywords, or lowering `max_items_per_tier`.
- Increase recall by adding synonyms to `keywords` or broadening `required_any` carefully.

## Report Behavior

- `lookback_days` discovers candidates; runtime `recommended-items.json` controls repeated Top 3 and A-tier display.
- Top 3 and A-tier displays should prefer papers not previously recommended/displayed, while A/B/C total counts still include all matching feed candidates in the current window.
- B and C tiers do not use freshness filtering by default.
- Runtime `imported-items.json` records historical Zotero import/restore/existing status. Report generation uses it as a hint, then best-effort verifies cached `zotero_key` values before display.
- Import status verification is read-only: prefer local SQLite key checks against `items.key` and `deletedItems`, using a short SQLite timeout and `PRAGMA busy_timeout` so Zotero desktop locks do not stall automation.
- If live local verification is locked or raises an operational SQLite error, retry with an `immutable=1` read-only connection; if local verification is still missing or errored and credentials exist, fall back to Zotero Web API `/items/{key}`.
- If a cached key is now deleted/trash, report `曾导入，现已在 Zotero 回收站/已删除（KEY）`; if missing, report `曾导入，现未找到（KEY）`; if verification fails, report `导入状态待复核（KEY）`.
- Report generation must not update `imported-items.json`; only confirmed Zotero import/write workflows update that cache.
- Reports should show both selected totals and displayed counts, number papers within each tier, show category rank separately from display number, and display both recommendation status and Zotero import status.
- Use a two-stage writing strategy: the script generates a structured draft, then Codex polishes the generated Markdown in the same thread.
- All displayed papers need polished Chinese titles: Top 3, A, B, and C.
- Abstract handling is tiered: Top 3 and displayed A-tier papers get polished Chinese abstracts; B-tier papers keep English abstracts only; C-tier papers do not show abstracts.
- B and C tiers should show matched keywords in Markdown bold, for example `**efficiency optimization**` or `**PMSM**`.
- Do not treat glossary substitution as final translation. The glossary is terminology guidance only, and generic word replacements such as `of`, `and`, `in`, `with`, and `for` should not be used to produce report prose.
- Default report filenames should not overwrite same-day reports. Use `Zotero论文订阅周报-YYYY-MM-DD.md` first, then `Zotero论文订阅周报-YYYY-MM-DD-02.md`, `-03.md`, and so on. Explicit `--output` keeps its overwrite semantics.

## Zotero Import Notes

When importing papers into Zotero collections from a radar report or another paper list/file, generate a dry-run list first and wait for explicit confirmation before writing. Use local Zotero/feed data for reads, Crossref for DOI/metadata enrichment, and Zotero Web API for writes. New Chinese titles belong only in `Extra` as `titleTranslation: <Chinese title>`; do not write `Chinese Title:`, screening reasons, source feed names, ranks, or report names into Zotero item metadata by default.

For this skill's own weekly reports, use `scripts/import_to_zotero.py` as the formal v1 import entrypoint. It supports `--source <report.md>`, `--scope top3|a|top3+a`, and `--collection <collection path>`. The default mode is dry-run and writes an import plan JSON under `<output_dir>/.zotero-literature-radar/import-plans/`; Zotero writes require a second command with `--execute --plan <plan.json>`. v1 does not download PDFs or create Zotero notes.

When parsing Top 3 entries from this skill's reports, read the `类别内排名` line as a tier hint. If it says `A 档第 n / 共 m（分数：x）`, the import entry should retain `tier=A`, `is_a=true`, the parsed score when available, and the `A档` tag even when that paper is not also shown in the A-tier display list.

The requested collection path/name is authoritative. Cached collection keys from prior runs, runtime `imported-items.json`, or dry-runs are only hints; every dry-run and confirmed write must resolve the target collection by path/name through Zotero Web API. If an old key returns 404 or points to a different path, ignore it and show the stale key plus final resolved key in the dry-run. If multiple same-name collections cannot be disambiguated by path, stop and ask the user to choose.

Import duplicate checks should use a bounded query strategy: check the target collection first, then exact identifiers such as item key, DOI, IEEE document ID, arXiv ID, and URL. Normalized title or full-title search is fallback only. Avoid broad full-library title searches and unbounded pagination. If Web API queries timeout or partially fail, keep the dry-run alive with confirmed results and mark `query_degraded`, `unresolved_items`, and `fallback_skipped_reason`; unresolved items require user decision and must not be silently created.

For non-radar sources, report-only fields are optional: tier, rank, Chinese title, screening reason, and report date may be missing. Prefer DOI extraction, then arXiv ID/URL, then Crossref title search; use publisher webpage scraping only as fallback. If no Chinese title is present, do not write `titleTranslation:`. If no tier/rank is present, do not add `Top3` or `A档` tags unless the user explicitly specifies the import category.

Zotero deletion is a soft-delete: DB/API visibility does not equal active UI presence. Local duplicate checks must query `deletedItems`, and Web API checks must inspect `data.deleted`. Deleted/trash matches are not active existing items, even if their `collections` still contains the target collection. Attachment-only matches must also be separated because a matching PDF or child item is not proof that the parent paper exists actively.

When restoring deleted/trash items, dry-run must show whether the restore is `minimal restore` or `restore + full metadata update`. Minimal restore only clears deleted state, restores/adds the target collection, tags, and `titleTranslation:`. Full metadata update also fills high-confidence DOI/Crossref/local-feed fields such as DOI, URL, publication title, date, creators, volume, issue, pages, ISSN, and abstract.

Chinese Web API writes must be UTF-8 safe and verified after writing. Use a UTF-8 JSON body/file or escaped Unicode rather than shell text that may pass through a non-UTF-8 code page. After PATCH/POST, read back the item and treat all-question-mark `titleTranslation:`, `??` tags, or mojibake as failure signals, not successful import.

Prefer constructing Zotero Web API URLs in Python or JavaScript. If PowerShell must build a URL, avoid `$base?format=json`; use `${base}?format=json`, `('{0}?format=json' -f $base)`, or explicit concatenation so query strings are not misparsed as part of a variable name.

After Zotero import/update succeeds and read-back verification passes, update runtime `imported-items.json` with `scripts/update_import_cache.py`. Do not update this import cache during dry-run. Ordinary report generation only updates runtime `recommended-items.json` after the Markdown file is successfully written.

When reading local Zotero while the desktop app is open, account for WAL state. Prefer a read-only connection that sees current WAL contents, or copy `zotero.sqlite`, `zotero.sqlite-wal`, and `zotero.sqlite-shm` together to a temporary directory before final status checks. Do not rely only on `immutable=1` for final import/delete status.

Importing from an existing report or another paper list/file must not regenerate the report unless the user explicitly asks for regeneration. If report generation and import are requested together, generate the report first and stop at the import dry-run.
