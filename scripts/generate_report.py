import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


FIELD_NAMES = ("title", "publicationTitle", "date", "DOI", "url", "abstractNote")
SKILL_DIR = Path(__file__).resolve().parents[1]
ACTIVE_IMPORT_STATUSES = {"imported", "restored", "active_existing"}
LOCAL_IMPORT_STATUS_TIMEOUT_SECONDS = 0.5


@dataclass
class Match:
    topic_id: str
    topic_name: str
    tier: str
    weight: int
    keywords: list[str] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)


@dataclass
class Paper:
    item_id: int
    feed_name: str
    date_added: str
    date_modified: str
    guid: str
    title: str
    date: str
    doi: str
    url: str
    abstract: str
    matches: list[Match]
    score: int
    tier: str
    tier_rank: int = 0
    tier_total: int = 0
    seen_key: str = ""
    seen_id_type: str = ""
    top_freshness_status: str = "新增"
    a_freshness_status: str = "新增"
    import_status_text: str = "未导入"



def default_zotero_db_path() -> Path:
    candidates = []
    env_path = os.environ.get("ZOTERO_DB_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())

    home = Path.home()
    userprofile = Path(os.environ.get("USERPROFILE", str(home))).expanduser()
    appdata = os.environ.get("APPDATA", "").strip()
    candidates.extend([
        userprofile / "Zotero" / "zotero.sqlite",
        home / "Zotero" / "zotero.sqlite",
    ])
    if appdata:
        candidates.append(Path(appdata) / "Zotero" / "zotero.sqlite")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else Path("zotero.sqlite")


def resolve_theme_path(workspace: Path, explicit: str) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (workspace / ".codex" / "zotero-literature-radar" / "research-theme.md").resolve()


def user_global_theme_path() -> Path:
    userprofile = Path(os.environ.get("USERPROFILE", str(Path.home()))).expanduser()
    return userprofile / ".codex" / "zotero-literature-radar" / "research-theme.md"


def skill_template_theme_path() -> Path:
    return SKILL_DIR / "templates" / "research-theme.md"


def extract_theme_config(markdown: str) -> dict:
    patterns = (
        r"```json\s+([\s\S]*?)```",
        r"```topics-json\s+([\s\S]*?)```",
        r"```zotero-topics\s+([\s\S]*?)```",
    )
    for pattern in patterns:
        match = re.search(pattern, markdown, re.I)
        if match:
            return json.loads(match.group(1))
    raise ValueError("No JSON config block found in theme markdown.")


def default_config_init() -> dict:
    return {
        "source": "workspace",
        "initialized": False,
        "theme_source": "",
        "theme_written": False,
        "error": "",
    }


def iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def parse_sort_date(value: str) -> datetime:
    value = (value or "").strip()
    if not value:
        return datetime.min
    for fmt, length in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(value[:length], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.min


def normalize_doi(doi: str) -> str:
    doi = (doi or "").strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi.strip()


def ieee_document_id(value: str) -> str:
    value = value or ""
    match = re.search(r"ieeexplore\.ieee\.org/(?:document|stamp/stamp\.jsp\?tp=&arnumber=)/(\d+)", value, re.I)
    if match:
        return match.group(1)
    match = re.search(r"(?:arnumber=|document/)(\d+)", value, re.I)
    return match.group(1) if match else ""


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def paper_seen_identity(paper: Paper) -> tuple[str, str]:
    doi = normalize_doi(paper.doi)
    if doi:
        return f"doi:{doi}", "doi"
    ieee_id = ieee_document_id(paper.url) or ieee_document_id(paper.guid)
    if ieee_id:
        return f"ieee:{ieee_id}", "ieee_document_id"
    if paper.url:
        return f"url:{paper.url.strip().lower()}", "url"
    title_hash = hashlib.sha1(normalize_title(paper.title).encode("utf-8")).hexdigest()[:16]
    return f"title:{title_hash}", "title_hash"


def resolve_output_dir(workspace: Path, config: dict) -> Path:
    output_dir = Path(config.get("output_dir", "论文追踪周报"))
    return output_dir if output_dir.is_absolute() else workspace / output_dir


def runtime_state_dir(output_dir: Path) -> Path:
    return output_dir / ".zotero-literature-radar"


def recommended_cache_path(state_dir: Path) -> Path:
    return state_dir / "recommended-items.json"


def imported_cache_path(state_dir: Path) -> Path:
    return state_dir / "imported-items.json"


def load_seen_cache(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {"schema_version": 1, "updated_at": "", "items": {}}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("cache root is not an object")
        if not isinstance(data.get("items"), dict):
            data["items"] = {}
        data.setdefault("schema_version", 1)
        data.setdefault("updated_at", "")
        return data, ""
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"schema_version": 1, "updated_at": "", "items": {}}, f"{type(exc).__name__}: {exc}"


def write_seen_cache(path: Path, cache: dict) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        cache["updated_at"] = iso_now()
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ""
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"


def base_cache_entry(paper: Paper, id_type: str, now_iso: str) -> dict:
    return {
        "id_type": id_type,
        "canonical_title": paper.title,
        "doi": normalize_doi(paper.doi),
        "url": paper.url,
        "first_seen_at": now_iso,
        "last_seen_at": now_iso,
        "first_recommended_at": "",
        "last_recommended_at": "",
        "recommendation_count": 0,
        "first_a_displayed_at": "",
        "last_a_displayed_at": "",
        "a_display_count": 0,
        "last_tier": paper.tier,
        "last_score": paper.score,
    }


def update_seen_observation(cache: dict, papers: list[Paper], now_iso: str) -> None:
    items = cache.setdefault("items", {})
    for paper in papers:
        key, id_type = paper_seen_identity(paper)
        paper.seen_key = key
        paper.seen_id_type = id_type
        entry = items.get(key)
        if not isinstance(entry, dict):
            entry = base_cache_entry(paper, id_type, now_iso)
            items[key] = entry
        entry.setdefault("first_seen_at", now_iso)
        entry["last_seen_at"] = now_iso
        entry["id_type"] = id_type
        entry["canonical_title"] = paper.title
        entry["doi"] = normalize_doi(paper.doi)
        entry["url"] = paper.url
        entry["last_tier"] = paper.tier
        entry["last_score"] = paper.score
        entry.setdefault("first_recommended_at", "")
        entry.setdefault("last_recommended_at", "")
        entry.setdefault("recommendation_count", 0)
        entry.setdefault("first_a_displayed_at", "")
        entry.setdefault("last_a_displayed_at", "")
        entry.setdefault("a_display_count", 0)


def assign_seen_identities(papers: list[Paper]) -> None:
    for paper in papers:
        paper.seen_key, paper.seen_id_type = paper_seen_identity(paper)


def history_snapshot(cache: dict) -> dict:
    return {
        "schema_version": cache.get("schema_version", 1),
        "updated_at": cache.get("updated_at", ""),
        "items": {
            key: dict(value)
            for key, value in cache.get("items", {}).items()
            if isinstance(value, dict)
        },
    }


def cache_zotero_key(entry: dict | None) -> str:
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("zotero_key") or "").strip()


def import_status_label(entry: dict | None, verification: dict | None = None) -> str:
    if not entry:
        return "未导入"
    status = str(entry.get("import_status") or "").strip()
    labels = {
        "": "未导入",
        "unknown": "未导入",
        "imported": "已导入 Zotero",
        "restored": "已恢复到 Zotero",
        "active_existing": "Zotero 中已有活动条目",
        "deleted_trash_conflict": "回收站冲突",
        "failed": "导入失败",
        "skipped": "已跳过",
    }
    zotero_key = cache_zotero_key(entry)
    verification_state = str((verification or {}).get("state") or "")
    if zotero_key and verification_state == "deleted":
        return f"曾导入，现已在 Zotero 回收站/已删除（{zotero_key}）"
    if zotero_key and verification_state == "missing":
        return f"曾导入，现未找到（{zotero_key}）"
    if zotero_key and verification_state == "error":
        return f"导入状态待复核（{zotero_key}）"
    label = labels.get(status, f"导入状态：{status}")
    if zotero_key and status in {"imported", "restored", "active_existing"}:
        label = f"{label}（{zotero_key}）"
    if status == "failed" and entry.get("failure_reason"):
        label = f"{label}：{entry.get('failure_reason')}"
    return label


def assign_import_statuses(papers: list[Paper], imported_cache: dict, verification: dict | None = None) -> None:
    items = imported_cache.get("items", {})
    verification = verification or {}
    for paper in papers:
        entry = items.get(paper.seen_key)
        verify_result = None
        if isinstance(entry, dict):
            verify_result = verification.get(cache_zotero_key(entry))
        paper.import_status_text = import_status_label(entry if isinstance(entry, dict) else None, verify_result)


def import_entries_to_verify(papers: list[Paper], imported_cache: dict) -> dict[str, dict]:
    items = imported_cache.get("items", {})
    entries: dict[str, dict] = {}
    for paper in papers:
        entry = items.get(paper.seen_key)
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("import_status") or "").strip()
        key = cache_zotero_key(entry)
        if key and status in ACTIVE_IMPORT_STATUSES:
            entries.setdefault(key, entry)
    return entries


def query_local_import_status(con: sqlite3.Connection, keys: list[str]) -> dict[str, dict]:
    cur = con.cursor()
    results = {key: {"state": "missing", "source": "local"} for key in keys}
    for start in range(0, len(keys), 200):
        chunk = keys[start : start + 200]
        placeholders = ",".join("?" for _ in chunk)
        rows = cur.execute(
            f"""
            select i.key as itemKey, i.itemID, di.itemID as deletedItemID
            from items i
            left join deletedItems di on di.itemID = i.itemID
            where i.key in ({placeholders})
            """,
            chunk,
        ).fetchall()
        for row in rows:
            key = str(row["itemKey"])
            state = "deleted" if row["deletedItemID"] is not None else "active"
            old = results.get(key)
            if not old or old.get("state") != "active":
                results[key] = {"state": state, "source": "local", "item_id": int(row["itemID"])}
    return results


def read_local_import_status_once(db_path: Path, keys: list[str], immutable: bool) -> dict[str, dict]:
    con = connect_readonly(db_path, immutable=immutable, timeout=LOCAL_IMPORT_STATUS_TIMEOUT_SECONDS)
    try:
        return query_local_import_status(con, keys)
    finally:
        con.close()


def local_import_status_by_key(db_path: Path, keys: list[str]) -> tuple[dict[str, dict], list[str]]:
    if not keys:
        return {}, []
    warnings: list[str] = []
    try:
        return read_local_import_status_once(db_path, keys, immutable=False), warnings
    except sqlite3.Error as exc:
        warnings.append(f"local live read failed, used immutable fallback: {type(exc).__name__}: {exc}")

    try:
        return read_local_import_status_once(db_path, keys, immutable=True), warnings
    except sqlite3.Error as exc:
        warnings.append(f"local immutable read failed: {type(exc).__name__}: {exc}")
        return {
            key: {"state": "error", "source": "local", "warning": str(exc)}
            for key in keys
        }, warnings


def zotero_api_config_available() -> bool:
    return bool(os.environ.get("ZOTERO_API_KEY", "").strip() and os.environ.get("ZOTERO_LIBRARY_ID", "").strip())


def zotero_api_item_status(key: str, timeout: int = 12) -> dict:
    api_key = os.environ.get("ZOTERO_API_KEY", "").strip()
    library_id = os.environ.get("ZOTERO_LIBRARY_ID", "").strip()
    library_type = os.environ.get("ZOTERO_LIBRARY_TYPE", "user").strip() or "user"
    library_segment = "groups" if library_type == "group" else "users"
    quoted_key = urllib.parse.quote(key, safe="")
    url = f"https://api.zotero.org/{library_segment}/{urllib.parse.quote(library_id, safe='')}/items/{quoted_key}"
    request = urllib.request.Request(
        url,
        headers={
            "Zotero-API-Key": api_key,
            "Accept": "application/json",
            "User-Agent": "zotero-literature-radar/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"state": "missing", "source": "web_api"}
        return {"state": "error", "source": "web_api", "warning": f"HTTP {exc.code}: {exc.reason}"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"state": "error", "source": "web_api", "warning": f"{type(exc).__name__}: {exc}"}
    item_data = data.get("data", data) if isinstance(data, dict) else {}
    if item_data.get("deleted"):
        return {"state": "deleted", "source": "web_api"}
    return {"state": "active", "source": "web_api"}


def verify_import_cache_statuses(papers: list[Paper], imported_cache: dict, db_path: Path) -> tuple[dict[str, dict], dict]:
    entries = import_entries_to_verify(papers, imported_cache)
    keys = sorted(entries)
    results: dict[str, dict] = {}
    warnings: list[str] = []
    if keys:
        try:
            results, warnings = local_import_status_by_key(db_path, keys)
        except sqlite3.Error as exc:
            warnings.append(f"local import status verification failed: {type(exc).__name__}: {exc}")
            results = {key: {"state": "error", "source": "local", "warning": str(exc)} for key in keys}

    api_available = zotero_api_config_available()
    for key in keys:
        current = results.get(key, {"state": "missing", "source": "local"})
        if current.get("state") in {"missing", "error"} and api_available:
            current = zotero_api_item_status(key)
            if current.get("state") == "error" and current.get("warning"):
                warnings.append(f"{key}: {current.get('warning')}")
        results[key] = current

    counts = {"checked": len(keys), "active": 0, "deleted": 0, "missing": 0, "error": 0}
    for result in results.values():
        state = str(result.get("state") or "error")
        if state not in counts:
            state = "error"
        counts[state] += 1
    return results, {"counts": counts, "warnings": warnings, "web_api_fallback_available": api_available}


def seen_status(entry: dict | None, mode: str) -> str:
    if not entry:
        return "新增"
    if mode == "top" and entry.get("last_recommended_at"):
        count = int(entry.get("recommendation_count") or 0)
        suffix = f"，推荐次数 {count}" if count else ""
        return f"重复推荐：上次精读 {entry.get('last_recommended_at')}{suffix}"
    if mode == "a" and entry.get("last_a_displayed_at"):
        count = int(entry.get("a_display_count") or 0)
        suffix = f"，A 类展示次数 {count}" if count else ""
        return f"已展示：上次 A 类展示 {entry.get('last_a_displayed_at')}{suffix}"
    if entry.get("last_seen_at") and entry.get("last_seen_at") != entry.get("first_seen_at"):
        return f"已见过但未推荐：首次出现 {entry.get('first_seen_at')}"
    return "新增"


def freshness_sort_key(paper: Paper, cache: dict, mode: str) -> tuple:
    entry = cache.get("items", {}).get(paper.seen_key, {})
    if mode == "top":
        seen_group = 1 if entry.get("last_recommended_at") else 0
    elif mode == "a":
        seen_group = 1 if entry.get("last_a_displayed_at") else 0
    else:
        seen_group = 0
    dt = parse_sort_date(paper.date or paper.date_added)
    date_rank = -(dt.toordinal() * 86400 + dt.hour * 3600 + dt.minute * 60 + dt.second)
    return (seen_group, -paper.score, date_rank, paper.title.lower())


def ranked_tier_sort_key(paper: Paper) -> tuple:
    dt = parse_sort_date(paper.date or paper.date_added)
    date_rank = -(dt.toordinal() * 86400 + dt.hour * 3600 + dt.minute * 60 + dt.second)
    return (-paper.score, date_rank, paper.title.lower())


def assign_tier_ranks(grouped: dict[str, list[Paper]]) -> None:
    for tier, tier_papers in grouped.items():
        ranked = sorted(tier_papers, key=ranked_tier_sort_key)
        total = len(ranked)
        for index, paper in enumerate(ranked, 1):
            paper.tier_rank = index
            paper.tier_total = total


def mark_recommended(cache: dict, papers: list[Paper], now_iso: str) -> None:
    items = cache.setdefault("items", {})
    for paper in papers:
        entry = items.setdefault(paper.seen_key, base_cache_entry(paper, paper.seen_id_type, now_iso))
        entry.setdefault("first_recommended_at", now_iso)
        if not entry.get("first_recommended_at"):
            entry["first_recommended_at"] = now_iso
        entry["last_recommended_at"] = now_iso
        entry["recommendation_count"] = int(entry.get("recommendation_count") or 0) + 1


def mark_a_displayed(cache: dict, papers: list[Paper], now_iso: str) -> None:
    items = cache.setdefault("items", {})
    for paper in papers:
        entry = items.setdefault(paper.seen_key, base_cache_entry(paper, paper.seen_id_type, now_iso))
        entry.setdefault("first_a_displayed_at", now_iso)
        if not entry.get("first_a_displayed_at"):
            entry["first_a_displayed_at"] = now_iso
        entry["last_a_displayed_at"] = now_iso
        entry["a_display_count"] = int(entry.get("a_display_count") or 0) + 1


def unique_default_output_path(output_dir: Path, now: datetime) -> Path:
    base = output_dir / f"Zotero论文订阅周报-{now:%Y-%m-%d}.md"
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = output_dir / f"Zotero论文订阅周报-{now:%Y-%m-%d}-{index:02d}.md"
        if not candidate.exists():
            return candidate
        index += 1


def initialize_workspace_theme(theme_path: Path, source_theme: Path, source_name: str) -> dict:
    init = default_config_init()
    init["source"] = source_name
    init["initialized"] = True
    init["theme_source"] = str(source_theme)
    markdown = source_theme.read_text(encoding="utf-8-sig")
    config = extract_theme_config(markdown)
    try:
        theme_path.parent.mkdir(parents=True, exist_ok=True)
        theme_path.write_text(markdown, encoding="utf-8")
        init["theme_written"] = True
    except OSError as exc:
        init["error"] = f"{type(exc).__name__}: {exc}"
    config["_config_init"] = init
    config["_theme_path"] = str(theme_path if init["theme_written"] else source_theme)
    return config


def fallback_theme_source() -> tuple[Path | None, str]:
    global_theme = user_global_theme_path()
    if global_theme.exists():
        return global_theme, "user_global"
    template = skill_template_theme_path()
    if template.exists():
        return template, "skill_template"
    return None, ""


def load_runtime_config(theme_path: Path, explicit_theme: bool = False) -> dict:
    if theme_path.exists():
        config = extract_theme_config(theme_path.read_text(encoding="utf-8-sig"))
        config["_config_init"] = default_config_init()
        config["_config_init"]["source"] = "explicit_theme" if explicit_theme else "workspace"
        config["_theme_path"] = str(theme_path)
        return config

    if explicit_theme:
        raise FileNotFoundError(f"Research theme not found: {theme_path}")

    source_theme, source_name = fallback_theme_source()
    if not source_theme:
        raise FileNotFoundError(f"Research theme not found: {theme_path}")
    return initialize_workspace_theme(theme_path, source_theme, source_name)


def rx_list(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in patterns]


def contains(text: str, term: str) -> bool:
    return term.lower() in text


def clean_value(value) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.lower() == "null" else value


def connect_readonly(db_path: Path, immutable: bool = True, timeout: float = 5.0) -> sqlite3.Connection:
    uri = "file:" + str(db_path).replace("\\", "/") + "?mode=ro"
    if immutable:
        uri += "&immutable=1"
    con = sqlite3.connect(uri, uri=True, timeout=timeout)
    con.execute(f"pragma busy_timeout={max(0, int(timeout * 1000))}")
    con.row_factory = sqlite3.Row
    return con


def item_field(cur: sqlite3.Cursor, item_id: int, field_name: str) -> str:
    row = cur.execute(
        """
        select v.value
        from itemData d
        join fields f on f.fieldID = d.fieldID
        join itemDataValues v on v.valueID = d.valueID
        where d.itemID = ? and f.fieldName = ?
        """,
        (item_id, field_name),
    ).fetchone()
    return clean_value(row["value"] if row else "")


def recent_feed_items(cur: sqlite3.Cursor, lookback_days: int) -> list[dict]:
    rows = cur.execute(
        """
        select
            i.itemID,
            fds.name as feedName,
            i.dateAdded,
            i.dateModified,
            fi.guid
        from feedItems fi
        join items i on i.itemID = fi.itemID
        join feeds fds on fds.libraryID = i.libraryID
        where datetime(i.dateAdded) >= datetime('now', ?)
           or datetime(i.dateModified) >= datetime('now', ?)
        order by datetime(i.dateAdded) desc, i.itemID desc
        """,
        (f"-{lookback_days} days", f"-{lookback_days} days"),
    ).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        for name in FIELD_NAMES:
            item[name] = item_field(cur, row["itemID"], name)
        items.append(item)
    return items


def is_ignored(item: dict, title_patterns: list[re.Pattern], topic_patterns: list[re.Pattern]) -> tuple[bool, str]:
    title = item.get("title") or ""
    text = f"{title} {item.get('abstractNote') or ''}"
    for pat in title_patterns:
        if pat.search(title):
            return True, f"title:{pat.pattern}"
    for pat in topic_patterns:
        if pat.search(text):
            return True, f"topic:{pat.pattern}"
    return False, ""


def score_item(item: dict, topics: list[dict]) -> tuple[int, str, list[Match]]:
    text = f"{item.get('title') or ''} {item.get('abstractNote') or ''}".lower()
    matches: list[Match] = []
    score = 0
    tier_rank = {"A": 3, "B": 2, "C": 1}
    best_tier = ""

    for topic in topics:
        required = [t for t in topic.get("required_any", []) if contains(text, t)]
        if topic.get("required_any") and not required:
            continue
        hits = [t for t in topic.get("keywords", []) if contains(text, t)]
        if not hits:
            continue
        weight = int(topic.get("weight", 1))
        topic_score = weight * len(hits) + len(required)
        score += topic_score
        tier = str(topic.get("tier", "C")).upper()
        if not best_tier or tier_rank.get(tier, 0) > tier_rank.get(best_tier, 0):
            best_tier = tier
        matches.append(
            Match(
                topic_id=str(topic.get("id", "")),
                topic_name=str(topic.get("name", topic.get("id", ""))),
                tier=tier,
                weight=weight,
                keywords=hits,
                required_terms=required,
            )
        )

    return score, best_tier or "C", matches


def build_papers(items: list[dict], config: dict) -> tuple[list[Paper], list[dict]]:
    title_patterns = rx_list(config.get("ignore_title_patterns", []))
    topic_patterns = rx_list(config.get("ignore_topic_patterns", []))
    topics = config.get("topics", [])
    papers: list[Paper] = []
    ignored: list[dict] = []

    for item in items:
        ignored_flag, reason = is_ignored(item, title_patterns, topic_patterns)
        if ignored_flag:
            ignored.append({"itemID": item["itemID"], "title": item.get("title", ""), "reason": reason})
            continue
        score, tier, matches = score_item(item, topics)
        if not matches:
            continue
        papers.append(
            Paper(
                item_id=int(item["itemID"]),
                feed_name=item.get("feedName", ""),
                date_added=item.get("dateAdded", ""),
                date_modified=item.get("dateModified", ""),
                guid=item.get("guid", ""),
                title=item.get("title", ""),
                date=item.get("date", ""),
                doi=item.get("DOI", ""),
                url=item.get("url", "") or item.get("guid", ""),
                abstract=item.get("abstractNote", ""),
                matches=matches,
                score=score,
                tier=tier,
            )
        )

    return sorted(papers, key=lambda p: ({"A": 3, "B": 2, "C": 1}.get(p.tier, 0), p.score), reverse=True), ignored


def short(text: str, limit: int = 320) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


TRANSLATION_PHRASES = (
    ("maximum torque per ampere-based", "基于最大转矩电流比的"),
    ("control performance improvement", "控制性能提升"),
    ("permanent magnet synchronous motor", "永磁同步电机"),
    ("permanent magnet synchronous motors", "永磁同步电机"),
    ("permanent magnet synchronous machine", "永磁同步电机"),
    ("permanent magnet synchronous machines", "永磁同步电机"),
    ("maximum torque per ampere", "最大转矩电流比"),
    ("state-threshold", "状态阈值"),
    ("second-order", "二阶"),
    ("terminal attractor", "终端吸引子"),
    ("heavy-duty traction", "重载牵引"),
    ("open-end winding", "开绕组"),
    ("deadbeat predictive current control", "无差拍预测电流控制"),
    ("deadbeat", "无差拍"),
    ("quasi-resonant", "准谐振"),
    ("multiloop", "多环"),
    ("harmonic torque suppression", "谐波转矩抑制"),
    ("direct torque control", "直接转矩控制"),
    ("model predictive current control", "模型预测电流控制"),
    ("model predictive torque control", "模型预测转矩控制"),
    ("model predictive control", "模型预测控制"),
    ("model-free predictive current control", "无模型预测电流控制"),
    ("model-free adaptive", "无模型自适应"),
    ("sliding mode control", "滑模控制"),
    ("sliding mode observer", "滑模观测器"),
    ("extended state observer", "扩张状态观测器"),
    ("state observer", "状态观测器"),
    ("disturbance compensation", "扰动补偿"),
    ("disturbance rejection", "扰动抑制"),
    ("sensorless control", "无位置传感器控制"),
    ("speed control", "速度控制"),
    ("speed loop", "速度环"),
    ("current control", "电流控制"),
    ("torque control", "转矩控制"),
    ("current harmonic", "电流谐波"),
    ("harmonic suppression", "谐波抑制"),
    ("active damping", "主动阻尼"),
    ("torsional stiffness", "扭转刚度"),
    ("trajectory tracking", "轨迹跟踪"),
    ("trajectory optimization", "轨迹优化"),
    ("energy efficiency", "能效"),
    ("energy optimization", "能量优化"),
    ("efficiency optimization", "效率优化"),
    ("loss minimization", "损耗最小化"),
    ("copper loss", "铜耗"),
    ("iron loss", "铁耗"),
    ("core loss", "铁心损耗"),
    ("efficiency map", "效率地图"),
    ("loss model", "损耗模型"),
    ("switching loss", "开关损耗"),
    ("inverter loss", "逆变器损耗"),
    ("current stress", "电流应力"),
    ("continuous operation", "连续运行"),
    ("load disturbances", "负载扰动"),
    ("model mismatch", "模型失配"),
    ("control chattering", "控制抖振"),
    ("modulation strategy", "调制策略"),
    ("space vector modulation", "空间矢量调制"),
    ("pulsewidth modulation", "脉宽调制"),
    ("common-mode voltage", "共模电压"),
    ("common-mode current", "共模电流"),
    ("electric traction", "电牵引"),
    ("traction systems", "牵引系统"),
    ("traction system", "牵引系统"),
    ("systems", "系统"),
    ("system", "系统"),
    ("motor drive", "电机驱动"),
    ("motor drives", "电机驱动"),
    ("electric machine", "电机"),
    ("electric machines", "电机"),
    ("induction motor", "感应电机"),
    ("induction motors", "感应电机"),
    ("five-phase", "五相"),
    ("dual three-phase", "双三相"),
    ("three-phase", "三相"),
    ("open-circuit fault", "开路故障"),
    ("open-phase fault", "缺相故障"),
    ("fault diagnosis", "故障诊断"),
    ("thermal control", "热控制"),
    ("high-speed", "高速"),
    ("improvement", "提升"),
    ("improved", "改进的"),
    ("robust", "鲁棒"),
    ("adaptive", "自适应"),
    ("optimal", "最优"),
    ("optimization", "优化"),
    ("predictive", "预测"),
    ("observer", "观测器"),
    ("control strategy", "控制策略"),
    ("control method", "控制方法"),
    ("experimental results", "实验结果"),
    ("simulation results", "仿真结果"),
    ("this paper proposes", "本文提出"),
    ("this paper presents", "本文提出"),
    ("this article proposes", "本文提出"),
    ("this article presents", "本文提出"),
    ("the proposed method", "所提方法"),
    ("the proposed control", "所提控制方法"),
    ("compared with", "与之相比"),
    ("is proposed", "被提出"),
    ("is presented", "被提出"),
    ("is investigated", "被研究"),
    ("is analyzed", "被分析"),
    ("is designed", "被设计"),
    ("is developed", "被开发"),
    ("are proposed", "被提出"),
    ("are presented", "被提出"),
    ("results show", "结果表明"),
    ("demonstrate", "表明"),
    ("improve", "提高"),
    ("improves", "提高"),
    ("reduce", "降低"),
    ("reduces", "降低"),
    ("based on", "基于"),
)


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def glossary_translate(text: str, limit: int | None = 520) -> str:
    text = " ".join((text or "").split())
    if limit is not None and limit > 0:
        text = short(text, limit)
    if not text:
        return "暂无摘要。"
    if has_cjk(text):
        return text
    translated = text
    for src, dst in sorted(TRANSLATION_PHRASES, key=lambda pair: len(pair[0]), reverse=True):
        pattern = re.escape(src).replace(r"\ ", r"\s+")
        if src[:1].isalnum():
            pattern = r"(?<![A-Za-z])" + pattern
        if src[-1:].isalnum():
            pattern = pattern + r"(?![A-Za-z])"
        translated = re.sub(pattern, dst, translated, flags=re.I)
    translated = re.sub(r"\b(a|an|the)\b\s*", "", translated, flags=re.I)
    translated = re.sub(r"\s*-\s*", "-", translated)
    translated = re.sub(r"\s*,\s*", "，", translated)
    translated = re.sub(r"\.\s+", "。", translated)
    translated = re.sub(r"\s+", " ", translated).strip()
    translated = translated.replace("PMSMs", "PMSM").replace("PMSM s", "PMSM")
    translated = translated.replace("提高d", "改进的")
    translated = translated.replace("基于最大转矩电流比的 直接转矩控制 的", "基于最大转矩电流比的直接转矩控制的")
    return translated


def polish_title_placeholder(title: str) -> str:
    title = " ".join((title or "").split())
    return f"待 Codex 润色。英文题名：{title}" if title else "待 Codex 润色。"


def polish_abstract_placeholder(abstract: str) -> str:
    abstract = " ".join((abstract or "").split())
    if not abstract:
        return "暂无摘要。"
    return f"待 Codex 润色。英文摘要：{abstract}"


def tier_limit(max_items: dict, tier: str, total: int) -> int:
    return max(0, min(int(max_items.get(tier, total)), total))


def paper_keywords(paper: Paper, limit: int = 12) -> list[str]:
    keywords = []
    for match in paper.matches:
        keywords.extend(match.keywords)
    return list(dict.fromkeys(keywords[:limit]))


def format_keywords(keywords: list[str], bold: bool = False) -> str:
    if not keywords:
        return "无"
    if bold:
        return "；".join(f"**{keyword}**" for keyword in keywords)
    return "；".join(keywords)


def tier_reason(paper: Paper, include_keywords: bool = True) -> str:
    topics = []
    for match in paper.matches:
        topics.append(match.topic_name)
    topics_s = "；".join(dict.fromkeys(topics))
    if not include_keywords:
        return f"匹配主题：{topics_s}。"
    keywords_s = format_keywords(paper_keywords(paper))
    return f"匹配主题：{topics_s}。关键词：{keywords_s}。"


def action_for_tier(tier: str) -> str:
    return {"A": "精读", "B": "略读", "C": "存档/补充阅读"}.get(tier, "待判断")


def rank_line(paper: Paper) -> str:
    return f"{paper.tier} 档第 {paper.tier_rank} / 共 {paper.tier_total}（分数：{paper.score}）"


def append_top_paper_details(lines: list[str], paper: Paper) -> None:
    lines.append(f"   - 中文题目：{polish_title_placeholder(paper.title)}")
    lines.append(f"   - 来源：{paper.feed_name}")
    lines.append(f"   - 类别内排名：{rank_line(paper)}")
    lines.append(f"   - 推荐状态：{paper.top_freshness_status}")
    lines.append(f"   - 导入状态：{paper.import_status_text}")
    lines.append(f"   - 建议：{action_for_tier(paper.tier)}")
    lines.append(f"   - 理由：{tier_reason(paper)}")
    lines.append(f"   - 中文摘要：{polish_abstract_placeholder(paper.abstract)}")
    lines.append("   - 阅读建议：优先判断其方法、实验对象和损耗/效率建模是否可迁移到当前研究问题。")


def append_tier_paper_details(lines: list[str], tier: str, paper: Paper) -> None:
    lines.append(f"- 中文题目：{polish_title_placeholder(paper.title)}")
    lines.append(f"- 来源：{paper.feed_name}")
    lines.append(f"- 日期：{paper.date or paper.date_added}")
    lines.append(f"- 链接：{paper.url}")
    if paper.doi:
        lines.append(f"- DOI：{paper.doi}")
    lines.append(f"- 类别内排名：{rank_line(paper)}")
    lines.append(f"- 导入状态：{paper.import_status_text}")
    if tier == "A":
        lines.append(f"- 展示状态：{paper.a_freshness_status}")
    lines.append(f"- 建议动作：{action_for_tier(tier)}")
    if tier == "A":
        lines.append(f"- 筛选理由：{tier_reason(paper)}")
        lines.append(f"- 中文摘要：{polish_abstract_placeholder(paper.abstract)}")
    elif tier == "B":
        lines.append(f"- 筛选理由：{tier_reason(paper, include_keywords=False)}")
        lines.append(f"- 关键词：{format_keywords(paper_keywords(paper), bold=True)}")
        lines.append(f"- 英文摘要：{paper.abstract or '暂无摘要。'}")
    else:
        lines.append(f"- 筛选理由：{tier_reason(paper, include_keywords=False)}")
        lines.append(f"- 关键词：{format_keywords(paper_keywords(paper), bold=True)}")


def render_report(
    papers: list[Paper],
    ignored: list[dict],
    config: dict,
    source_count: int,
    cache: dict,
    cache_warning: str = "",
) -> tuple[str, list[Paper], dict[str, list[Paper]]]:
    now = datetime.now()
    max_items = config.get("max_items_per_tier", {})
    grouped = {tier: [paper for paper in papers if paper.tier == tier] for tier in ("A", "B", "C")}
    for tier in ("A", "B", "C"):
        grouped[tier] = sorted(grouped[tier], key=ranked_tier_sort_key)
    assign_tier_ranks(grouped)
    displayed = {tier: tier_limit(max_items, tier, len(grouped[tier])) for tier in ("A", "B", "C")}
    display_groups = {tier: list(grouped[tier]) for tier in ("A", "B", "C")}
    if grouped["A"]:
        display_groups["A"] = sorted(grouped["A"], key=lambda paper: freshness_sort_key(paper, cache, "a"))
    for paper in display_groups["A"][: displayed["A"]]:
        paper.a_freshness_status = seen_status(cache.get("items", {}).get(paper.seen_key), "a")

    top_pool = grouped["A"] or [paper for tier in ("A", "B", "C") for paper in grouped[tier]]
    top = sorted(top_pool, key=lambda paper: freshness_sort_key(paper, cache, "top"))[:3]
    for paper in top:
        paper.top_freshness_status = seen_status(cache.get("items", {}).get(paper.seen_key), "top")
    has_new_top = any(not cache.get("items", {}).get(paper.seen_key, {}).get("last_recommended_at") for paper in top)

    lines = [
        f"# Zotero 论文订阅周报 {now:%Y-%m-%d}",
        "",
        "## 总览",
        "",
        f"- 生成时间：{now:%Y-%m-%d %H:%M}",
        f"- 检索窗口：最近 {config.get('lookback_days', 7)} 天",
        f"- 原始订阅条目：{source_count}",
        f"- 规则忽略条目：{len(ignored)}",
        f"- 入选条目总数：{len(papers)}",
        f"- A/B/C 入选总数：A {len(grouped['A'])} / B {len(grouped['B'])} / C {len(grouped['C'])}",
        (
            "- A/B/C 报告展示："
            f"A 展示 {displayed['A']} / 共 {len(grouped['A'])}；"
            f"B 展示 {displayed['B']} / 共 {len(grouped['B'])}；"
            f"C 展示 {displayed['C']} / 共 {len(grouped['C'])}"
        ),
        "",
    ]
    if cache_warning:
        lines.extend([f"- Cache warning：{cache_warning}", ""])
    config_init = config.get("_config_init", {})
    if config_init.get("initialized"):
        source = config_init.get("source", "")
        lines.append(f"- 配置初始化：已从 {source} 初始化当前工作区主题配置。")
        if config_init.get("error"):
            lines.append(f"- 配置初始化 warning：{config_init.get('error')}")
        lines.append("")

    lines.extend(["## 本周最值得精读", ""])

    if not top:
        lines.append("- 本周没有匹配到值得精读的条目。")
    elif not has_new_top:
        lines.append("- 本次无新增精读，以下为仍建议关注的重复项。")
    for index, paper in enumerate(top, 1):
        lines.append(f"{index}. [{paper.title}]({paper.url})")
        append_top_paper_details(lines, paper)
    lines.append("")

    for tier in ("A", "B", "C"):
        total = len(grouped[tier])
        limit = tier_limit(max_items, tier, total)
        lines.append(f"## {tier} 档（展示 {limit} / 共 {total}）")
        lines.append("")
        if not total:
            lines.append("- 无")
            lines.append("")
            continue
        if tier == "A":
            lines.append("- 本档优先展示新增论文，已推荐过的高相关论文仅在名额不足时补入；类别内排名仍按基础评分计算。")
            lines.append("")
        for index, paper in enumerate(display_groups[tier][:limit], 1):
            lines.append(f"### {tier}{index}. {paper.title}")
            lines.append("")
            append_tier_paper_details(lines, tier, paper)
            lines.append("")

    lines.extend(
        [
            "## 下周关键词建议",
            "",
            "- 检查 A 档是否仍过宽；如果噪声多，给 A 档主题增加更强的 `required_any`。",
            "- 若漏掉效率优化论文，在 `research-theme.md` 中增加同义词，如 `efficiency-oriented control`、`minimum current control`、`loss-model-based control`。",
            "- 若逆变器/调制条目太多，把 `inverter-modulation-loss` 的 `tier` 保持为 C，或提高其 `required_any` 约束。",
            "",
            "## 配置文件",
            "",
            f"- `{config.get('_config_path', '')}`",
        ]
    )
    return "\n".join(lines) + "\n", top, {tier: display_groups[tier][: displayed[tier]] for tier in ("A", "B", "C")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Zotero feed literature radar Markdown report.")
    parser.add_argument("--theme", default="", help="Path to research-theme.md. Defaults to <workspace>/.codex/zotero-literature-radar/research-theme.md.")
    parser.add_argument("--workspace", default=".", help="Workspace root for relative output_dir.")
    parser.add_argument("--output", default="", help="Optional explicit output Markdown path.")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    theme_path = resolve_theme_path(workspace, args.theme)
    config = load_runtime_config(theme_path, explicit_theme=bool(args.theme))
    runtime_theme_path = str(config.get("_theme_path") or theme_path)
    config["_config_path"] = runtime_theme_path
    config["_theme_path"] = runtime_theme_path

    db_config = str(config.get("zotero_sqlite", "")).strip()
    db_path = Path(db_config).expanduser() if db_config else default_zotero_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"Zotero database not found: {db_path}")

    con = connect_readonly(db_path)
    try:
        cur = con.cursor()
        items = recent_feed_items(cur, int(config.get("lookback_days", 7)))
    finally:
        con.close()

    output_dir = resolve_output_dir(workspace, config)
    state_dir = runtime_state_dir(output_dir)

    papers, ignored = build_papers(items, config)
    now_iso = iso_now()
    recommended_path = recommended_cache_path(state_dir)
    imported_path = imported_cache_path(state_dir)
    recommended_cache, recommended_warning = load_seen_cache(recommended_path)
    imported_cache, imported_warning = load_seen_cache(imported_path)
    cache_history = history_snapshot(recommended_cache)
    assign_seen_identities(papers)
    import_verification, import_verification_summary = verify_import_cache_statuses(papers, imported_cache, db_path)
    assign_import_statuses(papers, imported_cache, import_verification)
    update_seen_observation(recommended_cache, papers, now_iso)
    cache_warnings = []
    if recommended_warning:
        cache_warnings.append(f"recommended cache: {recommended_warning}")
    if imported_warning:
        cache_warnings.append(f"imported cache: {imported_warning}")
    for warning in import_verification_summary.get("warnings", []):
        cache_warnings.append(f"import status verification: {warning}")
    report, top_papers, display_groups = render_report(papers, ignored, config, len(items), cache_history, "; ".join(cache_warnings))

    if args.output:
        output_path = Path(args.output).expanduser()
        if not output_path.is_absolute():
            output_path = workspace / output_path
    else:
        output_path = unique_default_output_path(output_dir, datetime.now())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    mark_recommended(recommended_cache, top_papers, now_iso)
    mark_a_displayed(recommended_cache, display_groups.get("A", []), now_iso)
    recommended_write_warning = write_seen_cache(recommended_path, recommended_cache)
    cache_write_warnings = []
    if recommended_write_warning:
        cache_write_warnings.append(f"recommended cache: {recommended_write_warning}")
    if cache_write_warnings:
        cache_warning = "; ".join(cache_write_warnings)
        report = report.replace(
            "## 本周最值得精读",
            f"- Cache warning：{cache_warning}\n\n## 本周最值得精读",
            1,
        )
        output_path.write_text(report, encoding="utf-8")

    polish_title_count = len(top_papers) + sum(len(display_groups.get(tier, [])) for tier in ("A", "B", "C"))
    polish_abstract_count = len(top_papers) + len(display_groups.get("A", []))
    summary = {
        "output": str(output_path),
        "source_count": len(items),
        "selected_count": len(papers),
        "tiers": {tier: len([p for p in papers if p.tier == tier]) for tier in ("A", "B", "C")},
        "displayed": {tier: len(display_groups.get(tier, [])) for tier in ("A", "B", "C")},
        "top_titles": [paper.title for paper in top_papers],
        "polish_required": True,
        "polish_scope": {
            "title_count": polish_title_count,
            "abstract_count": polish_abstract_count,
            "titles": "top3 and displayed A/B/C papers",
            "abstracts": "top3 and displayed A-tier papers",
        },
        "recommended_cache": {
            "path": str(recommended_path),
            "warning": recommended_warning or recommended_write_warning,
        },
        "imported_cache": {
            "path": str(imported_path),
            "warning": imported_warning,
        },
        "import_status_verification": import_verification_summary,
        "runtime_state_dir": str(state_dir),
        "config_init": config.get("_config_init", {}),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

