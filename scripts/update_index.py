#!/usr/bin/env python3
"""Create extera-plugins.json from a built Elyx archive and release asset URL."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import zipfile

try:
    import yaml
except ImportError as exc:
    raise SystemExit("Missing dependency: run `python -m pip install pyyaml`.") from exc

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "extera-plugins.json"
REPOSITORY = {
    "schema": 1,
    "name": "AJ Plugins · Music +",
    "description": "Music + for ExteraGram — library, lyrics and queue management.",
    "author": "@AJ_Plugins",
    "homepage": "https://github.com/hesCalledAJ/MusicPlus",
}
METADATA_FIELDS = (
    "id", "name", "description", "author", "version", "icon",
    "app_version", "sdk_version", "requirements",
)


def read_archive(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "refmap.yml" not in names:
            raise SystemExit(f"{path}: refmap.yml is not at the archive root")
        refmap = yaml.safe_load(archive.read("refmap.yml")) or {}
        metadata_path = refmap.get("metainfo")
        if not metadata_path or metadata_path not in names:
            raise SystemExit(f"{path}: refmap.yml points to a missing metainfo file")
        metadata = yaml.safe_load(archive.read(metadata_path)) or {}
    return {str(key).strip("_"): value for key, value in metadata.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--asset-url", required=True)
    parser.add_argument("--output", type=Path, default=INDEX_PATH)
    args = parser.parse_args()

    if not args.asset_url.startswith("https://"):
        raise SystemExit("--asset-url must be an HTTPS URL")
    if not args.archive.is_file():
        raise SystemExit(f"Archive not found: {args.archive}")

    metadata = read_archive(args.archive)
    for field in ("id", "name", "version"):
        if not metadata.get(field):
            raise SystemExit(f"Archive metadata is missing required field: {field}")

    data = args.archive.read_bytes()
    entry = {key: metadata[key] for key in METADATA_FIELDS if key in metadata and metadata[key] is not None}
    if entry.get("description") == "{plugin_description}":
        entry["description"] = (
            "Reimagines the music experience inside Telegram, with a library, "
            "lyrics and better queue management."
        )
    entry.update({
        "category": ["media"],
        "file": args.asset_url,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

    previous = {}
    existing_index = ROOT / "extera-plugins.json"
    if existing_index.exists():
        try:
            previous = json.loads(existing_index.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    existing = [p for p in previous.get("plugins", []) if p.get("id") != entry["id"]]
    output = {**REPOSITORY, "plugins": existing + [entry]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output} for {entry['name']} {entry['version']}")


if __name__ == "__main__":
    main()
