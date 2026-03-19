#!/usr/bin/env python3
"""
Detect changed modules in a PR by comparing local files against metadata.
This detects NEW versions that are not yet in metadata.json.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def detect_new_versions(registry_path: str = ".") -> Dict[str, List[str]]:
    """
    Detect new versions by comparing directory structure with metadata.json.
    Returns modules and their new versions that exist in filesystem but not in metadata.
    """
    modules_path = Path(registry_path) / "modules"
    if not modules_path.exists():
        return {}

    changed_modules: Dict[str, List[str]] = {}

    for module_dir in modules_path.iterdir():
        if not module_dir.is_dir():
            continue

        module_name = module_dir.name
        metadata_path = module_dir / "metadata.json"

        # Get existing versions from metadata
        existing_versions: Set[str] = set()
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                existing_versions = set(metadata.get('versions', []))
            except (json.JSONDecodeError, IOError):
                pass

        # Find new versions in filesystem
        new_versions: List[str] = []
        for item in module_dir.iterdir():
            if item.is_dir() and (item / "source.json").exists():
                version = item.name
                if version not in existing_versions:
                    new_versions.append(version)

        if new_versions:
            # Sort versions semantically
            try:
                from registry import Version
                new_versions.sort(key=lambda v: Version.parse(v))
            except Exception:
                new_versions.sort()
            changed_modules[module_name] = new_versions

    return changed_modules


def detect_metadata_changes(registry_path: str = ".") -> List[str]:
    """Detect modules with modified metadata.json (new modules or metadata updates)."""
    modules_path = Path(registry_path) / "modules"
    if not modules_path.exists():
        return []

    changed_modules: List[str] = []

    for module_dir in modules_path.iterdir():
        if not module_dir.is_dir():
            continue

        module_name = module_dir.name
        metadata_path = module_dir / "metadata.json"

        # Check if metadata exists
        if metadata_path.exists():
            # This could be a new module or metadata update
            # We consider it changed if there are version directories
            has_versions = any(
                item.is_dir() and (item / "source.json").exists()
                for item in module_dir.iterdir()
            )
            if has_versions:
                changed_modules.append(module_name)

    return changed_modules


def main():
    parser = argparse.ArgumentParser(
        description='Detect new module versions by comparing filesystem with metadata.json'
    )
    parser.add_argument('--registry-path', default='.', help='Registry root path')
    parser.add_argument('--output', help='Output JSON file path')
    args = parser.parse_args()

    new_versions = detect_new_versions(args.registry_path)

    output = {
        'new_versions': new_versions,
        'module_count': len(new_versions),
        'version_count': sum(len(v) for v in new_versions.values())
    }

    json_output = json.dumps(output, indent=2)

    if args.output:
        Path(args.output).write_text(json_output)
    else:
        print(json_output)

    # Set GitHub Actions outputs if running in CI
    if 'GITHUB_OUTPUT' in os.environ:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"modules={json.dumps(list(new_versions.keys()))}\n")
            f.write(f"module_count={len(new_versions)}\n")
            f.write(f"has_changes={'true' if new_versions else 'false'}\n")


if __name__ == '__main__':
    main()
