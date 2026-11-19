#!/usr/bin/env python3
"""Package the MusicPlus source project as a release-ready .elyx archive.

This intentionally creates a source archive (not .pyc bytecode). The archive
root is the contents of MusicPlus/, so refmap.yml is at the ZIP root as required
by the exteraGram Elyx format.
"""

from __future__ import annotations

import ast
import sys
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("Missing dependency: run `python -m pip install pyyaml`.") from exc

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "MusicPlus"
OUTPUT_DIR = ROOT / "dist"
EXCLUDED_DIRS = {
    ".git", ".elyx", ".elyxbuilder", "builds", "__pycache__",
    ".venv", "venv", ".idea", ".vscode",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def load_metadata() -> tuple[dict, dict]:
    refmap_path = PROJECT / "refmap.yml"
    if not refmap_path.is_file():
        raise SystemExit(f"Missing {refmap_path}")

    refmap = yaml.safe_load(refmap_path.read_text(encoding="utf-8")) or {}
    metadata_rel = refmap.get("metainfo")
    if not metadata_rel:
        raise SystemExit("refmap.yml does not declare a 'metainfo' file")

    metadata_path = PROJECT / metadata_rel
    if not metadata_path.is_file() or PROJECT.resolve() not in metadata_path.resolve().parents:
        raise SystemExit(f"Invalid or missing metadata path: {metadata_rel}")
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}

    for field in ("id", "name", "version"):
        if not metadata.get(field):
            raise SystemExit(f"metainfo.yml is missing required field: {field}")
    return refmap, metadata


def main() -> None:
    if not PROJECT.is_dir():
        raise SystemExit(f"Project directory not found: {PROJECT}")

    refmap, metadata = load_metadata()

    # Validate all Python files before packaging.
    python_files = sorted(PROJECT.rglob("*.py"))
    for source in python_files:
        relative = source.relative_to(PROJECT)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        try:
            ast.parse(source.read_text(encoding="utf-8"), filename=str(relative))
        except SyntaxError as exc:
            raise SystemExit(f"Python syntax error in {relative}: {exc}") from exc

    version = str(metadata["version"])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = OUTPUT_DIR / f"MusicPlus-v{version}.elyx"

    included = []
    for path in sorted(PROJECT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(PROJECT)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        included.append((path, relative.as_posix()))

    if not any(name == "refmap.yml" for _, name in included):
        raise SystemExit("refmap.yml would not be placed at the archive root")
    metadata_rel = str(refmap.get("metainfo", ""))
    if not any(name == metadata_rel for _, name in included):
        raise SystemExit(f"Metadata file is not included in the archive: {metadata_rel}")

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, archive_name in included:
            archive.write(source, archive_name)

    with zipfile.ZipFile(archive_path, "r") as archive:
        names = set(archive.namelist())
        refmap = yaml.safe_load(archive.read("refmap.yml")) or {}
        metainfo = refmap.get("metainfo")
        if not metainfo or metainfo not in names:
            raise SystemExit("Built archive has an invalid refmap/metainfo reference")

    print(f"Built {archive_path.relative_to(ROOT)} ({archive_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
