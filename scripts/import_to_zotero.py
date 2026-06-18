import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SKILL_DIR = Path(__file__).resolve().parents[1]
UPDATE_IMPORT_CACHE = SKILL_DIR / "scripts" / "update_import_cache.py"
DEFAULT_TIMEOUT = 25
DEFAULT_LIMIT = 50
MAX_COLLECTION_PAGES = 20
MAX_ITEM_QUERY_PAGES = 3


def iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def slug_now() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def normalize_doi(doi: str) -> str:
    doi = (doi or "").strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi.strip()


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def ieee_document_id(value: str) -> str:
    value = value or ""
    match = re.search(r"ieeexplore\.ieee\.org/(?:document|stamp/stamp\.jsp\?tp=&arnumber=)/(\d+)", value, re.I)
    if match:
        return match.group(1)
    match = re.search(r"(?:arnumber=|document/)(\d+)", value, re.I)
    return match.group(1) if match else ""


def item_identity(title: str, doi: str = "", url: str = "") -> tuple[str, str]:
    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        return f"doi:{normalized_doi}", "doi"
    ieee_id = ieee_document_id(url)
    if ieee_id:
        return f"ieee:{ieee_id}", "ieee_document_id"
    if url:
        return f"url:{url.strip().lower()}", "url"
    title_hash = hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:16]
    return f"title:{title_hash}", "title_hash"


def has_bad_chinese_encoding(value: str) -> bool:
    value = value or ""
    if re.fullmatch(r"[?\s]+", value) and "?" in value:
        return True
    bad_markers = ("ç", "Ã", "è¯", "²¾", "莽", "虏", "戮", "猫")
    return any(marker in value for marker in bad_markers)


def split_key_value(line: str) -> tuple[str, str]:
    line = line.strip()
    if line.startswith("-"):
        line = line[1:].strip()
    for separator in ("：", ":"):
        if separator in line:
            key, value = line.split(separator, 1)
            return key.strip(), value.strip()
    return "", line


def strip_markdown_link(value: str) -> tuple[str, str]:
    match = re.match(r"\[(.*?)\]\((.*?)\)", value.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return value.strip(), ""


def parse_report_date(text: str) -> str:
    match = re.search(r"#\s+Zotero\s+论文订阅周报\s+(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    match = re.search(r"Zotero论文订阅周报-(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else datetime.now().strftime("%Y-%m-%d")


@dataclass
class ReportEntry:
    title: str
    url: str = ""
    doi: str = ""
    chinese_title: str = ""
    source: str = ""
    date: str = ""
    abstract: str = ""
    tier: str = ""
    display_id: str = ""
    score: str = ""
    is_top3: bool = False
    is_a: bool = False
    top_rank: int = 0
    report_date: str = ""
    report_path: str = ""
    source_sections: list[str] = field(default_factory=list)

    def key(self) -> str:
        return item_identity(self.title, self.doi, self.url)[0]

    def ieee_id(self) -> str:
        return ieee_document_id(self.url)

    def tags(self) -> list[str]:
        tags = ["Codex-Radar", "Zotero-RSS"]
        if self.report_date:
            tags.append(f"Radar-{self.report_date}")
        if self.is_top3:
            tags.append("Top3")
        if self.is_a:
            tags.append("A档")
        return list(dict.fromkeys(tags))


def parse_report(path: Path) -> list[ReportEntry]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    report_date = parse_report_date(text)
    entries: list[ReportEntry] = []
    top_entries = parse_top3(lines, report_date, path)
    a_entries = parse_a_tier(lines, report_date, path)
    entries.extend(top_entries)
    entries.extend(a_entries)
    return merge_report_entries(entries)


def collect_bullets(lines: list[str], start: int) -> tuple[list[str], int]:
    bullets: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if re.match(r"^\d+\.\s+\[", stripped) or re.match(r"^###\s+[ABC]\d+\.", stripped) or stripped.startswith("## "):
            break
        if stripped.startswith("-"):
            bullets.append(stripped)
        index += 1
    return bullets, index


def apply_category_rank(entry: ReportEntry, value: str) -> None:
    tier_match = re.search(r"([ABC])\s*档\s*第\s*\d+\s*/\s*共\s*\d+", value)
    if tier_match:
        tier = tier_match.group(1).upper()
        entry.tier = tier
        if tier == "A":
            entry.is_a = True
    score_match = re.search(r"分数\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)", value)
    if score_match:
        entry.score = score_match.group(1)


def apply_bullets(entry: ReportEntry, bullets: list[str]) -> None:
    for bullet in bullets:
        key, value = split_key_value(bullet)
        if not key:
            continue
        if key == "中文题目":
            entry.chinese_title = value
        elif key == "来源":
            entry.source = value
        elif key == "日期":
            entry.date = value
        elif key == "链接":
            label, url = strip_markdown_link(value)
            entry.url = url or label
        elif key.upper() == "DOI":
            entry.doi = normalize_doi(value)
        elif key == "分数":
            entry.score = value
        elif key == "类别内排名":
            apply_category_rank(entry, value)
        elif key == "英文摘要":
            entry.abstract = value


def parse_top3(lines: list[str], report_date: str, path: Path) -> list[ReportEntry]:
    entries: list[ReportEntry] = []
    in_top = False
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("## "):
            in_top = "最值得精读" in stripped
            if in_top:
                index += 1
                continue
            if entries:
                break
        if in_top:
            match = re.match(r"^(\d+)\.\s+\[(.*?)\]\((.*?)\)", stripped)
            if match:
                top_rank = int(match.group(1))
                entry = ReportEntry(
                    title=match.group(2).strip(),
                    url=match.group(3).strip(),
                    is_top3=True,
                    top_rank=top_rank,
                    tier="",
                    report_date=report_date,
                    report_path=str(path),
                    source_sections=["top3"],
                )
                bullets, next_index = collect_bullets(lines, index + 1)
                apply_bullets(entry, bullets)
                entries.append(entry)
                index = next_index
                continue
        index += 1
    return entries


def parse_a_tier(lines: list[str], report_date: str, path: Path) -> list[ReportEntry]:
    entries: list[ReportEntry] = []
    in_a = False
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("## "):
            in_a = bool(re.match(r"^##\s+A\s*档", stripped))
            if in_a:
                index += 1
                continue
            if entries:
                break
        if in_a:
            match = re.match(r"^###\s+(A\d+)\.\s+(.*)", stripped)
            if match:
                entry = ReportEntry(
                    title=match.group(2).strip(),
                    display_id=match.group(1),
                    tier="A",
                    is_a=True,
                    report_date=report_date,
                    report_path=str(path),
                    source_sections=["a"],
                )
                bullets, next_index = collect_bullets(lines, index + 1)
                apply_bullets(entry, bullets)
                entries.append(entry)
                index = next_index
                continue
        index += 1
    return entries


def merge_report_entries(entries: list[ReportEntry]) -> list[ReportEntry]:
    merged: dict[str, ReportEntry] = {}
    for entry in entries:
        key = entry.key()
        existing = merged.get(key)
        if not existing:
            merged[key] = entry
            continue
        existing.is_top3 = existing.is_top3 or entry.is_top3
        existing.is_a = existing.is_a or entry.is_a
        existing.source_sections = list(dict.fromkeys(existing.source_sections + entry.source_sections))
        if entry.top_rank and not existing.top_rank:
            existing.top_rank = entry.top_rank
        for attr in ("url", "doi", "chinese_title", "source", "date", "abstract", "tier", "display_id", "score"):
            if not getattr(existing, attr) and getattr(entry, attr):
                setattr(existing, attr, getattr(entry, attr))
    return list(merged.values())


def select_scope(entries: list[ReportEntry], scope: str) -> list[ReportEntry]:
    if scope == "top3":
        selected = [entry for entry in entries if entry.is_top3]
        return sorted(selected, key=lambda entry: entry.top_rank or 999)
    if scope == "a":
        return [entry for entry in entries if entry.is_a]
    if scope == "top3+a":
        return entries
    raise ValueError(f"unsupported scope: {scope}")


class ZoteroApiError(RuntimeError):
    pass


class ZoteroClient:
    def __init__(self, api_key: str, library_id: str, library_type: str = "user", timeout: int = DEFAULT_TIMEOUT):
        if not api_key:
            raise ValueError("ZOTERO_API_KEY is required")
        if not library_id:
            raise ValueError("ZOTERO_LIBRARY_ID is required")
        self.api_key = api_key
        self.library_id = library_id
        self.library_type = library_type or "user"
        self.timeout = timeout
        self.base_url = self._base_url()

    @classmethod
    def from_env(cls, timeout: int = DEFAULT_TIMEOUT) -> "ZoteroClient":
        return cls(
            os.environ.get("ZOTERO_API_KEY", "").strip(),
            os.environ.get("ZOTERO_LIBRARY_ID", "").strip(),
            os.environ.get("ZOTERO_LIBRARY_TYPE", "user").strip() or "user",
            timeout,
        )

    def _base_url(self) -> str:
        root = "groups" if self.library_type.lower().startswith("group") else "users"
        return f"https://api.zotero.org/{root}/{self.library_id}"

    def url(self, path: str, params: dict | None = None) -> str:
        path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{path}"
        if params:
            clean_params = {key: value for key, value in params.items() if value is not None and value != ""}
            query = urllib.parse.urlencode(clean_params)
            if query:
                url = f"{url}?{query}"
        return url

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        payload=None,
        extra_headers: dict | None = None,
        not_found_none: bool = False,
    ):
        headers = {
            "Zotero-API-Key": self.api_key,
            "Zotero-API-Version": "3",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        if extra_headers:
            headers.update(extra_headers)
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url(path, params), data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                if not body:
                    return None
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and not_found_none:
                return None
            detail = exc.read().decode("utf-8", errors="replace")
            raise ZoteroApiError(f"Zotero API {method} {path} failed with {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ZoteroApiError(f"Zotero API {method} {path} failed: {exc}") from exc

    def get(self, path: str, params: dict | None = None, not_found_none: bool = False):
        return self.request("GET", path, params=params, not_found_none=not_found_none)

    def post(self, path: str, payload):
        return self.request("POST", path, payload=payload)

    def put(self, path: str, payload, version: int | None = None):
        headers = {}
        if version is not None:
            headers["If-Unmodified-Since-Version"] = str(version)
        return self.request("PUT", path, payload=payload, extra_headers=headers)

    def paged_get(self, path: str, params: dict | None = None, max_pages: int = MAX_ITEM_QUERY_PAGES) -> list[dict]:
        items: list[dict] = []
        params = dict(params or {})
        limit = int(params.get("limit") or DEFAULT_LIMIT)
        params["limit"] = limit
        for page in range(max_pages):
            params["start"] = page * limit
            batch = self.get(path, params=params) or []
            if not isinstance(batch, list):
                break
            items.extend(batch)
            if len(batch) < limit:
                break
        return items


def collection_data(collection: dict) -> dict:
    return collection.get("data", collection)


def collection_key(collection: dict) -> str:
    return collection.get("key") or collection_data(collection).get("key", "")


def collection_name(collection: dict) -> str:
    return collection_data(collection).get("name", "")


def collection_parent(collection: dict):
    parent = collection_data(collection).get("parentCollection")
    return parent if parent not in (False, None) else ""


def load_all_collections(client: ZoteroClient) -> list[dict]:
    return client.paged_get("/collections", params={"limit": 100}, max_pages=MAX_COLLECTION_PAGES)


def collection_path_for_key(key: str, by_key: dict[str, dict]) -> str:
    pieces = []
    seen = set()
    current = key
    while current and current not in seen and current in by_key:
        seen.add(current)
        collection = by_key[current]
        pieces.append(collection_name(collection))
        current = collection_parent(collection)
    return "/".join(reversed([piece for piece in pieces if piece]))


def resolve_collection(client: ZoteroClient, path: str, cached_key: str = "") -> dict:
    path = "/".join(piece.strip() for piece in path.split("/") if piece.strip())
    stale_keys = []
    cached_match = None
    if cached_key:
        cached = client.get(f"/collections/{cached_key}", not_found_none=True)
        if cached:
            all_collections = load_all_collections(client)
            by_key = {collection_key(collection): collection for collection in all_collections if collection_key(collection)}
            cached_path = collection_path_for_key(cached_key, by_key)
            if cached_path == path:
                cached_match = {"key": cached_key, "path": cached_path, "source": "cached_key_verified"}
            else:
                stale_keys.append({"key": cached_key, "reason": "path_mismatch", "path": cached_path})
        else:
            stale_keys.append({"key": cached_key, "reason": "404"})
    all_collections = load_all_collections(client)
    by_key = {collection_key(collection): collection for collection in all_collections if collection_key(collection)}
    matches = []
    for key in by_key:
        full_path = collection_path_for_key(key, by_key)
        if full_path == path:
            matches.append({"key": key, "path": full_path})
    if cached_match:
        return {
            "path": path,
            "key": cached_match["key"],
            "exists": True,
            "ambiguous": False,
            "resolution_source": "cached_key_verified",
            "stale_keys": stale_keys,
            "create_missing": [],
        }
    if len(matches) == 1:
        return {
            "path": path,
            "key": matches[0]["key"],
            "exists": True,
            "ambiguous": False,
            "resolution_source": "path",
            "stale_keys": stale_keys,
            "create_missing": [],
        }
    if len(matches) > 1:
        return {
            "path": path,
            "key": "",
            "exists": False,
            "ambiguous": True,
            "matches": matches,
            "resolution_source": "ambiguous_path",
            "stale_keys": stale_keys,
            "create_missing": [],
        }
    return {
        "path": path,
        "key": "",
        "exists": False,
        "ambiguous": False,
        "resolution_source": "missing_path",
        "stale_keys": stale_keys,
        "create_missing": missing_collection_segments(path, by_key),
    }


def missing_collection_segments(path: str, by_key: dict[str, dict]) -> list[str]:
    parts = [piece.strip() for piece in path.split("/") if piece.strip()]
    missing = []
    parent_key = ""
    built = []
    for part in parts:
        built.append(part)
        found = ""
        for key, collection in by_key.items():
            if collection_name(collection) == part and (collection_parent(collection) or "") == parent_key:
                found = key
                break
        if found:
            parent_key = found
            continue
        missing = parts[len(built) - 1 :]
        break
    return missing


def create_collection_path(client: ZoteroClient, path: str) -> str:
    parts = [piece.strip() for piece in path.split("/") if piece.strip()]
    parent_key = ""
    for part in parts:
        all_collections = load_all_collections(client)
        found = ""
        for collection in all_collections:
            if collection_name(collection) == part and (collection_parent(collection) or "") == parent_key:
                found = collection_key(collection)
                break
        if found:
            parent_key = found
            continue
        payload = [{"name": part, "parentCollection": parent_key or False}]
        result = client.post("/collections", payload)
        successful = result.get("successful", {}) if isinstance(result, dict) else {}
        if not successful:
            raise ZoteroApiError(f"failed to create collection segment: {part}")
        first = next(iter(successful.values()))
        parent_key = first.get("key") or first.get("data", {}).get("key")
        if not parent_key:
            raise ZoteroApiError(f"Zotero did not return a key for collection segment: {part}")
    return parent_key


def zotero_data(item: dict) -> dict:
    return item.get("data", item)


def zotero_key(item: dict) -> str:
    return item.get("key") or zotero_data(item).get("key", "")


def zotero_version(item: dict) -> int:
    return int(item.get("version") or zotero_data(item).get("version") or 0)


def zotero_deleted(item: dict) -> bool:
    return bool(zotero_data(item).get("deleted"))


def zotero_collections(item: dict) -> list[str]:
    return list(zotero_data(item).get("collections") or [])


def zotero_tags(item: dict) -> list[str]:
    tags = zotero_data(item).get("tags") or []
    return [tag.get("tag", "") if isinstance(tag, dict) else str(tag) for tag in tags]


def zotero_doi(item: dict) -> str:
    return normalize_doi(zotero_data(item).get("DOI", ""))


def zotero_url(item: dict) -> str:
    return str(zotero_data(item).get("url") or "").strip()


def zotero_title(item: dict) -> str:
    return str(zotero_data(item).get("title") or "").strip()


def is_parent_literature_item(item: dict) -> bool:
    item_type = zotero_data(item).get("itemType", "")
    return item_type not in {"attachment", "note", "annotation"}


def item_matches_entry(item: dict, entry: ReportEntry) -> bool:
    data = zotero_data(item)
    if not is_parent_literature_item(item):
        return False
    if entry.doi and normalize_doi(data.get("DOI", "")) == normalize_doi(entry.doi):
        return True
    if entry.url and str(data.get("url", "")).strip().lower() == entry.url.strip().lower():
        return True
    entry_ieee = entry.ieee_id()
    if entry_ieee and entry_ieee == ieee_document_id(str(data.get("url", ""))):
        return True
    if normalize_title(entry.title) and normalize_title(data.get("title", "")) == normalize_title(entry.title):
        return True
    return False


def index_collection_items(client: ZoteroClient, collection_key_value: str) -> list[dict]:
    if not collection_key_value:
        return []
    return client.paged_get(
        f"/collections/{collection_key_value}/items",
        params={"limit": 100, "itemType": "-attachment"},
        max_pages=MAX_COLLECTION_PAGES,
    )


def query_items(client: ZoteroClient, query: str, title_only: bool = False, trash: bool = False) -> list[dict]:
    if not query:
        return []
    path = "/items/trash" if trash else "/items"
    params = {
        "q": query,
        "limit": 10,
        "itemType": "-attachment",
    }
    if title_only:
        params["qmode"] = "titleCreatorYear"
    return client.paged_get(path, params=params, max_pages=1)


def duplicate_lookup(client: ZoteroClient, entry: ReportEntry, collection_items: list[dict]) -> dict:
    result = {
        "active": [],
        "trash": [],
        "attachment_only": [],
        "queries": [],
        "query_degraded": False,
        "fallback_skipped_reason": "",
    }
    for item in collection_items:
        if item_matches_entry(item, entry):
            result["active"].append(item)
    if result["active"]:
        result["queries"].append("target_collection_index")
        return result

    exact_queries = []
    if entry.doi:
        exact_queries.append(("doi", entry.doi))
    if entry.ieee_id():
        exact_queries.append(("ieee_document_id", entry.ieee_id()))
    if entry.url:
        exact_queries.append(("url", entry.url))

    try:
        for query_name, query_value in exact_queries:
            result["queries"].append(query_name)
            for item in query_items(client, query_value):
                if item_matches_entry(item, entry):
                    result["active"].append(item)
            for item in query_items(client, query_value, trash=True):
                if item_matches_entry(item, entry):
                    result["trash"].append(item)
            if result["active"] or result["trash"]:
                return dedupe_lookup_result(result)
        if entry.title:
            result["queries"].append("title_fallback")
            for item in query_items(client, entry.title, title_only=True):
                if item_matches_entry(item, entry):
                    result["active"].append(item)
            for item in query_items(client, entry.title, title_only=True, trash=True):
                if item_matches_entry(item, entry):
                    result["trash"].append(item)
    except ZoteroApiError as exc:
        result["query_degraded"] = True
        result["fallback_skipped_reason"] = str(exc)
    return dedupe_lookup_result(result)


def dedupe_lookup_result(result: dict) -> dict:
    for key in ("active", "trash", "attachment_only"):
        seen = set()
        unique = []
        for item in result[key]:
            key_value = zotero_key(item)
            if key_value and key_value not in seen:
                seen.add(key_value)
                unique.append(item)
        result[key] = unique
    return result


def item_summary(item: dict) -> dict:
    data = zotero_data(item)
    return {
        "key": zotero_key(item),
        "version": zotero_version(item),
        "title": data.get("title", ""),
        "doi": normalize_doi(data.get("DOI", "")),
        "url": data.get("url", ""),
        "deleted": bool(data.get("deleted")),
        "collections": list(data.get("collections") or []),
    }


def entry_to_plan_dict(entry: ReportEntry) -> dict:
    key, id_type = item_identity(entry.title, entry.doi, entry.url)
    return {
        "identity": key,
        "id_type": id_type,
        "title": entry.title,
        "chinese_title": entry.chinese_title,
        "doi": normalize_doi(entry.doi),
        "url": entry.url,
        "ieee_document_id": entry.ieee_id(),
        "source": entry.source,
        "date": entry.date,
        "abstract": entry.abstract,
        "tier": entry.tier,
        "display_id": entry.display_id,
        "score": entry.score,
        "is_top3": entry.is_top3,
        "is_a": entry.is_a,
        "top_rank": entry.top_rank,
        "source_sections": entry.source_sections,
        "report_date": entry.report_date,
        "report_path": entry.report_path,
        "tags": entry.tags(),
    }


def classify_entry(entry: ReportEntry, lookup: dict, restore_mode: str, collection_key_value: str) -> dict:
    planned = entry_to_plan_dict(entry)
    planned["queries"] = lookup.get("queries", [])
    planned["query_degraded"] = lookup.get("query_degraded", False)
    planned["fallback_skipped_reason"] = lookup.get("fallback_skipped_reason", "")
    planned["target_collection_key"] = collection_key_value
    if lookup.get("query_degraded"):
        planned["status"] = "unresolved"
        planned["action"] = "requires_user_decision"
        return planned
    active = lookup.get("active", [])
    trash = lookup.get("trash", [])
    if len(active) > 1 or len(trash) > 1:
        planned["status"] = "suspicious_duplicate"
        planned["action"] = "requires_user_decision"
        planned["matches"] = [item_summary(item) for item in active + trash]
        return planned
    if active:
        planned["status"] = "active_existing"
        planned["action"] = "update_existing"
        planned["zotero_item"] = item_summary(active[0])
        return planned
    if trash:
        planned["status"] = "deleted_trash_match"
        planned["action"] = "restore"
        planned["restore_mode"] = restore_mode
        planned["zotero_item"] = item_summary(trash[0])
        return planned
    planned["status"] = "new"
    planned["action"] = "create"
    return planned


def runtime_state_dir_for_source(source: Path) -> Path:
    return source.resolve().parent / ".zotero-literature-radar"


def plan_output_path(workspace: Path, state_dir: Path, explicit: str = "") -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_absolute() else workspace / path
    return state_dir / "import-plans" / f"import-plan-{slug_now()}.json"


def cached_collection_key(state_dir: Path, collection_path: str) -> str:
    cache_path = state_dir / "imported-items.json"
    if not cache_path.exists():
        return ""
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    for entry in data.get("items", {}).values():
        if not isinstance(entry, dict):
            continue
        if entry.get("target_collection") == collection_path and entry.get("target_collection_key"):
            return str(entry.get("target_collection_key"))
    return ""


def create_dry_run(args: argparse.Namespace) -> dict:
    workspace = Path(args.workspace).expanduser().resolve()
    source = Path(args.source).expanduser()
    if not source.is_absolute():
        source = workspace / source
    state_dir = runtime_state_dir_for_source(source)
    entries = select_scope(parse_report(source), args.scope)
    if not entries:
        raise ValueError(f"no report entries found for scope: {args.scope}")
    client = ZoteroClient.from_env(timeout=args.timeout)
    cached_key = args.collection_key or cached_collection_key(state_dir, args.collection)
    collection = resolve_collection(client, args.collection, cached_key)
    plan = {
        "schema_version": 1,
        "created_at": iso_now(),
        "source": str(source),
        "workspace": str(workspace),
        "runtime_state_dir": str(state_dir),
        "scope": args.scope,
        "restore_mode": args.restore_mode,
        "collection": collection,
        "tags_default": ["Codex-Radar", "Zotero-RSS"],
        "query_degraded": False,
        "fallback_skipped_reason": "",
        "entries": [],
        "groups": {
            "active_existing": [],
            "deleted_trash_matches": [],
            "items_to_create": [],
            "items_requiring_decision": [],
            "unresolved_items": [],
        },
    }
    if collection.get("ambiguous"):
        plan["blocking_error"] = "target_collection_ambiguous"
        plan["groups"]["items_requiring_decision"] = [entry_to_plan_dict(entry) for entry in entries]
        return plan
    collection_items = []
    if collection.get("exists") and collection.get("key"):
        collection_items = index_collection_items(client, collection["key"])
    for entry in entries:
        lookup = duplicate_lookup(client, entry, collection_items)
        planned = classify_entry(entry, lookup, args.restore_mode, collection.get("key", ""))
        plan["entries"].append(planned)
        if planned.get("query_degraded"):
            plan["query_degraded"] = True
            if planned.get("fallback_skipped_reason"):
                plan["fallback_skipped_reason"] = planned["fallback_skipped_reason"]
        status = planned.get("status")
        if status == "active_existing":
            plan["groups"]["active_existing"].append(planned)
        elif status == "deleted_trash_match":
            plan["groups"]["deleted_trash_matches"].append(planned)
        elif status == "new":
            plan["groups"]["items_to_create"].append(planned)
        elif status == "unresolved":
            plan["groups"]["unresolved_items"].append(planned)
            plan["groups"]["items_requiring_decision"].append(planned)
        else:
            plan["groups"]["items_requiring_decision"].append(planned)
    return plan


def write_plan(plan: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_plan_summary(plan: dict, output_path: Path | None = None) -> None:
    summary = {
        "plan": str(output_path) if output_path else "",
        "source": plan.get("source", ""),
        "scope": plan.get("scope", ""),
        "collection": plan.get("collection", {}),
        "entry_count": len(plan.get("entries", [])),
        "active_existing": len(plan.get("groups", {}).get("active_existing", [])),
        "deleted_trash_matches": len(plan.get("groups", {}).get("deleted_trash_matches", [])),
        "items_to_create": len(plan.get("groups", {}).get("items_to_create", [])),
        "items_requiring_decision": len(plan.get("groups", {}).get("items_requiring_decision", [])),
        "query_degraded": plan.get("query_degraded", False),
        "blocking_error": plan.get("blocking_error", ""),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def crossref_lookup(entry: dict, timeout: int = 15) -> dict:
    doi = normalize_doi(entry.get("doi", ""))
    if doi:
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    else:
        query = urllib.parse.urlencode({"query.title": entry.get("title", ""), "rows": 1})
        url = f"https://api.crossref.org/works?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "zotero-literature-radar/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}
    message = data.get("message", {})
    if "items" in message:
        items = message.get("items") or []
        message = items[0] if items else {}
        titles = message.get("title") or []
        if not titles or normalize_title(titles[0]) != normalize_title(entry.get("title", "")):
            return {}
    return map_crossref(message)


def map_crossref(message: dict) -> dict:
    if not message:
        return {}
    result = {}
    if message.get("DOI"):
        result["DOI"] = normalize_doi(message.get("DOI", ""))
    titles = message.get("title") or []
    if titles:
        result["title"] = titles[0]
    containers = message.get("container-title") or []
    if containers:
        result["publicationTitle"] = containers[0]
    if message.get("URL"):
        result["url"] = message.get("URL")
    if message.get("volume"):
        result["volume"] = str(message.get("volume"))
    if message.get("issue"):
        result["issue"] = str(message.get("issue"))
    if message.get("page"):
        result["pages"] = str(message.get("page"))
    issn = message.get("ISSN") or []
    if issn:
        result["ISSN"] = issn[0]
    date_parts = (message.get("published-print") or message.get("published-online") or message.get("issued") or {}).get("date-parts") or []
    if date_parts and date_parts[0]:
        result["date"] = "-".join(f"{part:02d}" if index else str(part) for index, part in enumerate(date_parts[0]))
    creators = []
    for author in message.get("author") or []:
        creator = {"creatorType": "author"}
        if author.get("given") or author.get("family"):
            creator["firstName"] = author.get("given", "")
            creator["lastName"] = author.get("family", "")
        elif author.get("name"):
            creator["name"] = author.get("name")
        if creator.get("lastName") or creator.get("name"):
            creators.append(creator)
    if creators:
        result["creators"] = creators
    return result


def title_translation_extra(existing_extra: str, chinese_title: str, overwrite: bool = False) -> str:
    existing_extra = existing_extra or ""
    if not chinese_title:
        return existing_extra
    line = f"titleTranslation: {chinese_title}"
    pattern = re.compile(r"^titleTranslation\s*:\s*.*$", re.I | re.M)
    if pattern.search(existing_extra):
        return pattern.sub(line, existing_extra) if overwrite else existing_extra
    if existing_extra.strip():
        return existing_extra.rstrip() + "\n" + line
    return line


def merge_tags(existing_tags: list, required_tags: list[str]) -> list[dict]:
    seen = []
    for tag in existing_tags or []:
        tag_value = tag.get("tag", "") if isinstance(tag, dict) else str(tag)
        if tag_value and tag_value not in seen:
            seen.append(tag_value)
    for tag_value in required_tags:
        if tag_value and tag_value not in seen:
            seen.append(tag_value)
    return [{"tag": tag_value} for tag_value in seen]


def update_item_payload(item: dict, entry: dict, collection_key_value: str, restore: bool, restore_mode: str) -> dict:
    data = dict(zotero_data(item))
    collections = list(data.get("collections") or [])
    if collection_key_value and collection_key_value not in collections:
        collections.append(collection_key_value)
    data["collections"] = collections
    data["tags"] = merge_tags(data.get("tags", []), entry.get("tags", []))
    if restore:
        data["deleted"] = False
    data["extra"] = title_translation_extra(data.get("extra", ""), entry.get("chinese_title", ""))
    if restore and restore_mode == "full_metadata_update":
        metadata = crossref_lookup(entry)
        metadata.setdefault("DOI", normalize_doi(entry.get("doi", "")))
        metadata.setdefault("url", entry.get("url", ""))
        metadata.setdefault("abstractNote", entry.get("abstract", ""))
        for key, value in metadata.items():
            if value:
                data[key] = value
    return data


def new_item_payload(entry: dict, collection_key_value: str) -> dict:
    metadata = crossref_lookup(entry)
    payload = {
        "itemType": "journalArticle",
        "title": metadata.get("title") or entry.get("title", ""),
        "DOI": metadata.get("DOI") or normalize_doi(entry.get("doi", "")),
        "url": metadata.get("url") or entry.get("url", ""),
        "abstractNote": metadata.get("abstractNote") or entry.get("abstract", ""),
        "collections": [collection_key_value] if collection_key_value else [],
        "tags": merge_tags([], entry.get("tags", [])),
        "extra": title_translation_extra("", entry.get("chinese_title", "")),
    }
    for key in ("publicationTitle", "date", "creators", "volume", "issue", "pages", "ISSN"):
        if metadata.get(key):
            payload[key] = metadata[key]
    if not payload.get("date") and entry.get("date"):
        payload["date"] = entry["date"]
    return payload


def verify_item(client: ZoteroClient, key: str, entry: dict, collection_key_value: str, verify_doi: bool = True) -> dict:
    item = client.get(f"/items/{key}")
    data = zotero_data(item)
    errors = []
    if data.get("deleted"):
        errors.append("item still deleted")
    if collection_key_value and collection_key_value not in (data.get("collections") or []):
        errors.append("target collection missing")
    tag_values = zotero_tags(item)
    for tag in entry.get("tags", []):
        if tag not in tag_values:
            errors.append(f"missing tag: {tag}")
    expected_doi = normalize_doi(entry.get("doi", ""))
    if verify_doi and expected_doi and normalize_doi(data.get("DOI", "")) != expected_doi:
        errors.append("DOI mismatch")
    chinese_title = entry.get("chinese_title", "")
    extra = data.get("extra", "") or ""
    if chinese_title and f"titleTranslation: {chinese_title}" not in extra:
        if "titleTranslation:" not in extra:
            errors.append("titleTranslation missing")
    if has_bad_chinese_encoding(extra) or any(has_bad_chinese_encoding(tag) for tag in tag_values):
        errors.append("Chinese encoding verification failed")
    return {
        "ok": not errors,
        "errors": errors,
        "key": key,
        "version": zotero_version(item),
        "data": data,
    }


def update_import_cache(workspace: Path, state_dir: Path, results: list[dict]) -> None:
    if not results:
        return
    payload_path = state_dir / "import-plans" / f"import-cache-update-{slug_now()}.json"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(json.dumps({"items": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        str(UPDATE_IMPORT_CACHE),
        "--workspace",
        str(workspace),
        "--state-dir",
        str(state_dir),
        "--input",
        str(payload_path),
    ]
    import subprocess

    completed = subprocess.run(command, text=True, capture_output=True, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"update_import_cache.py failed: {completed.stderr or completed.stdout}")


def execute_plan(args: argparse.Namespace) -> dict:
    workspace = Path(args.workspace).expanduser().resolve()
    plan_path = Path(args.plan).expanduser()
    if not plan_path.is_absolute():
        plan_path = workspace / plan_path
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    state_dir = Path(plan.get("runtime_state_dir") or runtime_state_dir_for_source(Path(plan.get("source", plan_path)))).expanduser()
    if not state_dir.is_absolute():
        state_dir = workspace / state_dir
    if not args.execute:
        raise ValueError("--execute is required to run a plan")
    if plan.get("blocking_error"):
        raise ValueError(f"plan has blocking error: {plan.get('blocking_error')}")
    if plan.get("groups", {}).get("items_requiring_decision") or plan.get("groups", {}).get("unresolved_items"):
        raise ValueError("plan contains unresolved items requiring user decision")
    client = ZoteroClient.from_env(timeout=args.timeout)
    collection_info = resolve_collection(client, plan["collection"]["path"], plan["collection"].get("key", ""))
    if collection_info.get("ambiguous"):
        raise ValueError("target collection is ambiguous at execute time")
    collection_key_value = collection_info.get("key", "")
    if not collection_key_value:
        collection_key_value = create_collection_path(client, plan["collection"]["path"])
    results = {
        "plan": str(plan_path),
        "collection": {"path": plan["collection"]["path"], "key": collection_key_value},
        "processed": [],
        "failed": [],
        "stopped": False,
    }
    cache_updates = []
    for entry in plan.get("entries", []):
        action = entry.get("action")
        status = entry.get("status")
        try:
            if action == "update_existing":
                key = entry["zotero_item"]["key"]
                item = client.get(f"/items/{key}")
                payload = update_item_payload(item, entry, collection_key_value, restore=False, restore_mode=plan.get("restore_mode", "minimal"))
                client.put(f"/items/{key}", payload, version=zotero_version(item))
                verification = verify_item(client, key, entry, collection_key_value, verify_doi=False)
                import_status = "active_existing"
            elif action == "restore":
                key = entry["zotero_item"]["key"]
                item = client.get(f"/items/{key}")
                payload = update_item_payload(item, entry, collection_key_value, restore=True, restore_mode=entry.get("restore_mode") or plan.get("restore_mode", "full_metadata_update"))
                client.put(f"/items/{key}", payload, version=zotero_version(item))
                verification = verify_item(client, key, entry, collection_key_value)
                import_status = "restored"
            elif action == "create":
                payload = new_item_payload(entry, collection_key_value)
                response = client.post("/items", [payload])
                successful = response.get("successful", {}) if isinstance(response, dict) else {}
                if not successful:
                    raise ZoteroApiError(f"create failed: {response}")
                created = next(iter(successful.values()))
                key = created.get("key") or created.get("data", {}).get("key")
                if not key:
                    raise ZoteroApiError(f"create response has no item key: {response}")
                time.sleep(0.5)
                verification = verify_item(client, key, entry, collection_key_value)
                import_status = "imported"
            else:
                continue
            if not verification["ok"]:
                raise ZoteroApiError("; ".join(verification["errors"]))
            processed = {
                "title": entry.get("title", ""),
                "doi": entry.get("doi", ""),
                "url": entry.get("url", ""),
                "zotero_key": verification["key"],
                "status": import_status,
                "action": action,
            }
            results["processed"].append(processed)
            cache_updates.append(
                {
                    "title": entry.get("title", ""),
                    "doi": entry.get("doi", ""),
                    "url": entry.get("url", ""),
                    "ieee_document_id": entry.get("ieee_document_id", ""),
                    "import_status": import_status,
                    "zotero_key": verification["key"],
                    "target_collection": plan["collection"]["path"],
                    "target_collection_key": collection_key_value,
                    "last_import_action": action,
                    "last_import_report": Path(plan.get("source", "")).name,
                    "last_import_verified_at": iso_now(),
                }
            )
        except Exception as exc:
            failure = {
                "title": entry.get("title", ""),
                "doi": entry.get("doi", ""),
                "url": entry.get("url", ""),
                "action": action,
                "status": status,
                "error": str(exc),
            }
            results["failed"].append(failure)
            cache_updates.append(
                {
                    "title": entry.get("title", ""),
                    "doi": entry.get("doi", ""),
                    "url": entry.get("url", ""),
                    "ieee_document_id": entry.get("ieee_document_id", ""),
                    "import_status": "failed",
                    "target_collection": plan["collection"]["path"],
                    "target_collection_key": collection_key_value,
                    "last_import_action": action or "unknown",
                    "last_import_report": Path(plan.get("source", "")).name,
                    "last_import_verified_at": iso_now(),
                    "failure_reason": str(exc),
                }
            )
            results["stopped"] = True
            break
    update_import_cache(workspace, state_dir, cache_updates)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run or execute Zotero imports from Zotero Literature Radar reports.")
    parser.add_argument("--workspace", default=".", help="Workspace root.")
    parser.add_argument("--source", default="", help="Radar report Markdown path for dry-run.")
    parser.add_argument("--scope", choices=["top3", "a", "top3+a"], default="top3", help="Report scope to import.")
    parser.add_argument("--collection", default="", help="Target Zotero collection path, for example Codex_Filter_Database/99_To_Read.")
    parser.add_argument("--collection-key", default="", help="Optional cached collection key hint.")
    parser.add_argument("--restore-mode", choices=["full_metadata_update", "minimal"], default="full_metadata_update")
    parser.add_argument("--dry-run-output", default="", help="Optional dry-run plan JSON path.")
    parser.add_argument("--execute", action="store_true", help="Execute a previously generated dry-run plan.")
    parser.add_argument("--plan", default="", help="Dry-run plan JSON path for --execute.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    if args.execute:
        if not args.plan:
            raise ValueError("--execute requires --plan")
        result = execute_plan(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result.get("failed") else 1

    if not args.source:
        raise ValueError("dry-run requires --source")
    if not args.collection:
        raise ValueError("dry-run requires --collection")
    workspace = Path(args.workspace).expanduser().resolve()
    plan = create_dry_run(args)
    state_dir = Path(plan["runtime_state_dir"])
    output_path = plan_output_path(workspace, state_dir, args.dry_run_output)
    write_plan(plan, output_path)
    print_plan_summary(plan, output_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)
