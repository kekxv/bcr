#!/usr/bin/env python3
"""
Update source.json overlay hashes from files in the overlay directory.
"""

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Iterable, Tuple


def calculate_sha256(path: Path) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            sha256.update(chunk)
    return "sha256-" + base64.b64encode(sha256.digest()).decode("ascii")


def detect_indent(source_json: Path) -> int:
    for line in source_json.read_text().splitlines():
        if line.startswith("    "):
            return 4
        if line.startswith("  "):
            return 2
    return 2


def find_overlay_root(path: Path) -> Path:
    if path.name == "overlay":
        return path

    for candidate in [path, *path.parents]:
        if candidate.name == "overlay":
            return candidate

    if path.is_dir() and (path / "overlay").is_dir():
        return path / "overlay"

    raise ValueError(
        "Could not find overlay directory. Pass a module version directory, "
        "source.json, overlay directory, or a file under overlay/."
    )


def resolve_paths(input_path: Path) -> Tuple[Path, Path, Path]:
    path = input_path.resolve()

    if path.is_file() and path.name == "source.json":
        version_dir = path.parent
        overlay_root = version_dir / "overlay"
        return path, overlay_root, overlay_root

    overlay_root = find_overlay_root(path)
    version_dir = overlay_root.parent
    source_json = version_dir / "source.json"

    return source_json, overlay_root, path


def iter_overlay_files(target: Path, overlay_root: Path) -> Iterable[Path]:
    if not overlay_root.is_dir():
        raise ValueError(f"Overlay directory not found: {overlay_root}")

    if target == overlay_root.parent:
        target = overlay_root

    if target.is_file():
        yield target
        return

    if not target.is_dir():
        raise ValueError(f"Path not found: {target}")

    for path in sorted(target.rglob("*")):
        if path.is_file():
            yield path


def overlay_key(path: Path, overlay_root: Path) -> str:
    try:
        return path.relative_to(overlay_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"File is not under overlay directory: {path}") from exc


def update_overlay(source_json: Path, overlay_root: Path, target: Path) -> int:
    if not source_json.is_file():
        raise ValueError(f"source.json not found: {source_json}")

    with source_json.open() as f:
        source = json.load(f)

    existing_overlay = dict(source.get("overlay", {}))
    overlay_files = list(iter_overlay_files(target, overlay_root))
    new_hashes = {
        overlay_key(path, overlay_root): calculate_sha256(path)
        for path in overlay_files
    }

    if not new_hashes:
        raise ValueError(f"No overlay files found under: {target}")

    full_update = target == overlay_root or target == overlay_root.parent
    if full_update:
        overlay = {}
        remaining = dict(new_hashes)

        for key in existing_overlay:
            if key in remaining:
                overlay[key] = remaining.pop(key)

        for key in sorted(remaining):
            overlay[key] = remaining[key]
    else:
        overlay = dict(existing_overlay)
        overlay.update(new_hashes)

    changed_count = sum(
        1 for key, value in overlay.items()
        if existing_overlay.get(key) != value
    )
    changed_count += len(set(existing_overlay) - set(overlay))

    source["overlay"] = overlay
    indent = detect_indent(source_json)

    with source_json.open("w") as f:
        json.dump(source, f, indent=indent)
        f.write("\n")

    return changed_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calculate sha256 hashes for overlay files and update source.json."
    )
    parser.add_argument(
        "path",
        help=(
            "Path to a module version directory, source.json, overlay directory, "
            "overlay subdirectory, or overlay file."
        ),
    )
    args = parser.parse_args()

    try:
        source_json, overlay_root, target = resolve_paths(Path(args.path))
        updated_count = update_overlay(source_json, overlay_root, target)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Updated {updated_count} overlay hash(es) in {source_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
