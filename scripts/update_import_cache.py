import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


VALID_STATUSES = {
    "imported",
    "restored",
    "active_existing",
    "deleted_trash_conflict",
    "skipped",
    "failed",
}


def iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


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


def identity(entry: dict) -> tuple[str, str]:
    doi = normalize_doi(str(entry.get("doi") or entry.get("DOI") or ""))
    if doi:
        return f"doi:{doi}", "doi"
    ieee_id = str(entry.get("ieee_document_id") or "").strip()
    if not ieee_id:
        ieee_id = ieee_document_id(str(entry.get("url") or entry.get("URL") or ""))
    if not ieee_id:
        ieee_id = ieee_document_id(str(entry.get("guid") or ""))
    if ieee_id:
        return f"ieee:{ieee_id}", "ieee_document_id"
    url = str(entry.get("url") or entry.get("URL") or "").strip()
    if url:
        return f"url:{url.lower()}", "url"
    title = normalize_title(str(entry.get("title") or ""))
    if title:
        title_hash = hashlib.sha1(title.encode("utf-8")).hexdigest()[:16]
        return f"title:{title_hash}", "title_hash"
    raise ValueError("entry needs DOI, IEEE document ID, URL, or title")


def configured_workspace_path(workspace: Path, configured: str, default: Path) -> Path:
    configured = str(configured or "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else workspace / path
    return default


def imported_cache_path(workspace: Path, configured: str, state_dir: str = "") -> Path:
    default_dir = Path(state_dir).expanduser() if state_dir else workspace / "论文追踪周报" / ".zotero-literature-radar"
    if not default_dir.is_absolute():
        default_dir = workspace / default_dir
    return configured_workspace_path(
        workspace,
        configured,
        default_dir / "imported-items.json",
    )


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "updated_at": "", "items": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("cache root is not an object")
    if not isinstance(data.get("items"), dict):
        data["items"] = {}
    data.setdefault("schema_version", 1)
    data.setdefault("updated_at", "")
    return data


def write_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cache["updated_at"] = iso_now()
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_status(status: str) -> str:
    status = (status or "").strip()
    if not status:
        raise ValueError("import status is required")
    if status not in VALID_STATUSES:
        raise ValueError(f"unsupported import status: {status}")
    return status


def payload_entries(args: argparse.Namespace) -> list[dict]:
    if args.input:
        data = json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data, dict):
            return [data]
        raise ValueError("input JSON must be an object, an items object, or a list")

    entry = {
        "doi": args.doi,
        "ieee_document_id": args.ieee_id,
        "url": args.url,
        "title": args.title,
        "import_status": args.status,
        "zotero_key": args.zotero_key,
        "target_collection": args.target_collection,
        "target_collection_key": args.target_collection_key,
        "last_import_report": args.report,
        "last_import_action": args.action,
        "last_import_verified_at": args.verified_at,
        "failure_reason": args.failure_reason,
    }
    return [entry]


def update_entry(cache: dict, raw_entry: dict, now_iso: str) -> str:
    key, id_type = identity(raw_entry)
    status = normalize_status(str(raw_entry.get("import_status") or raw_entry.get("status") or ""))
    items = cache.setdefault("items", {})
    entry = items.setdefault(key, {})

    entry["id_type"] = id_type
    entry["canonical_title"] = str(raw_entry.get("title") or entry.get("canonical_title") or "")
    entry["doi"] = normalize_doi(str(raw_entry.get("doi") or raw_entry.get("DOI") or entry.get("doi") or ""))
    entry["url"] = str(raw_entry.get("url") or raw_entry.get("URL") or entry.get("url") or "")
    entry["import_status"] = status
    entry["zotero_key"] = str(raw_entry.get("zotero_key") or raw_entry.get("item_key") or entry.get("zotero_key") or "")
    entry["target_collection"] = str(raw_entry.get("target_collection") or entry.get("target_collection") or "")
    entry["target_collection_key"] = str(raw_entry.get("target_collection_key") or entry.get("target_collection_key") or "")
    entry["last_import_action"] = str(raw_entry.get("last_import_action") or raw_entry.get("action") or entry.get("last_import_action") or status)
    entry["last_import_verified_at"] = str(
        raw_entry.get("last_import_verified_at") or raw_entry.get("verified_at") or entry.get("last_import_verified_at") or now_iso
    )
    entry["last_import_report"] = str(raw_entry.get("last_import_report") or raw_entry.get("report") or entry.get("last_import_report") or "")
    if status == "failed":
        entry["failure_reason"] = str(raw_entry.get("failure_reason") or entry.get("failure_reason") or "")
    else:
        entry["failure_reason"] = str(raw_entry.get("failure_reason") or "")

    if status == "imported":
        entry["imported_at"] = str(raw_entry.get("imported_at") or entry.get("imported_at") or now_iso)
    else:
        entry.setdefault("imported_at", "")
    if status == "restored":
        entry["restored_at"] = str(raw_entry.get("restored_at") or entry.get("restored_at") or now_iso)
    else:
        entry.setdefault("restored_at", "")
    return key


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Zotero Literature Radar imported-items cache after verified Zotero writes.")
    parser.add_argument("--workspace", default=".", help="Workspace root.")
    parser.add_argument("--state-dir", default="", help="Runtime state directory. Defaults to <workspace>/论文追踪周报/.zotero-literature-radar.")
    parser.add_argument("--cache", default="", help="Optional imported-items.json path.")
    parser.add_argument("--input", default="", help="JSON object/list containing verified import results.")
    parser.add_argument("--status", default="", help="Single-entry import status.")
    parser.add_argument("--doi", default="")
    parser.add_argument("--ieee-id", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--zotero-key", default="")
    parser.add_argument("--target-collection", default="")
    parser.add_argument("--target-collection-key", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--action", default="")
    parser.add_argument("--verified-at", default="")
    parser.add_argument("--failure-reason", default="")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    cache_path = imported_cache_path(workspace, args.cache, args.state_dir)
    cache = load_cache(cache_path)
    now_iso = iso_now()
    updated_keys = []
    for entry in payload_entries(args):
        updated_keys.append(update_entry(cache, entry, now_iso))
    write_cache(cache_path, cache)
    print(json.dumps({"path": str(cache_path), "updated_count": len(updated_keys), "keys": updated_keys}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
