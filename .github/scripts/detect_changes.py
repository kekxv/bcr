#!/usr/bin/env python3
"""
Detect changed modules in a PR by comparing local files against metadata.
This detects NEW versions that are not yet in metadata.json AND
MODIFIED versions that have changes in git diff.
"""

import argparse
import json
import os
import subprocess
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


def detect_modified_versions(registry_path: str = ".") -> Dict[str, List[str]]:
    """
    Detect modified versions by git diff against origin/main.
    Returns modules and their modified versions.
    """
    modules_path = Path(registry_path) / "modules"
    if not modules_path.exists():
        return {}

    changed_modules: Dict[str, List[str]] = {}

    try:
        # Get changed files in modules/ directory
        result = subprocess.run(
            ['git', 'diff', '--name-status', 'origin/main', '--', 'modules/'],
            capture_output=True, text=True, check=True
        )

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue

            parts = line.split('\t')
            if len(parts) < 2:
                continue

            status = parts[0][0]  # A=Added, M=Modified, D=Deleted, R=Renamed
            file_path = parts[-1]

            # Parse path: modules/<name>/<version>/file
            path_parts = file_path.split('/')
            if len(path_parts) >= 3:
                module_name = path_parts[1]
                version = path_parts[2]

                # Skip if not a version directory (metadata.json, README.md, etc.)
                if version in ['metadata.json', 'README.md']:
                    continue

                # Check if this is a valid version (has source.json)
                version_path = modules_path / module_name / version
                if version_path.is_dir() and (version_path / "source.json").exists():
                    if module_name not in changed_modules:
                        changed_modules[module_name] = []
                    if version not in changed_modules[module_name]:
                        changed_modules[module_name].append(version)

    except subprocess.CalledProcessError:
        # Git diff failed, return empty
        pass

    # Sort versions
    for module_name in changed_modules:
        try:
            from registry import Version
            changed_modules[module_name].sort(key=lambda v: Version.parse(v))
        except Exception:
            changed_modules[module_name].sort()

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
        description='Detect new and modified module versions'
    )
    parser.add_argument('--registry-path', default='.', help='Registry root path')
    parser.add_argument('--output', help='Output JSON file path')
    args = parser.parse_args()

    # Detect both new versions (not in metadata) and modified versions (git diff)
    new_versions = detect_new_versions(args.registry_path)
    modified_versions = detect_modified_versions(args.registry_path)

    # Merge new and modified versions
    all_changes: Dict[str, List[str]] = {}
    for module_name, versions in new_versions.items():
        if module_name not in all_changes:
            all_changes[module_name] = []
        for v in versions:
            if v not in all_changes[module_name]:
                all_changes[module_name].append(v)

    for module_name, versions in modified_versions.items():
        if module_name not in all_changes:
            all_changes[module_name] = []
        for v in versions:
            if v not in all_changes[module_name]:
                all_changes[module_name].append(v)

    # Sort versions in each module
    for module_name in all_changes:
        try:
            from registry import Version
            all_changes[module_name].sort(key=lambda v: Version.parse(v))
        except Exception:
            all_changes[module_name].sort()

    output = {
        'new_versions': new_versions,
        'modified_versions': modified_versions,
        'all_changes': all_changes,
        'module_count': len(all_changes),
        'version_count': sum(len(v) for v in all_changes.values())
    }

    json_output = json.dumps(output, indent=2)

    if args.output:
        Path(args.output).write_text(json_output)
    else:
        print(json_output)

    # Set GitHub Actions outputs if running in CI
    if 'GITHUB_OUTPUT' in os.environ:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"modules={json.dumps(list(all_changes.keys()))}\n")
            f.write(f"module_count={len(all_changes)}\n")
            f.write(f"has_changes={'true' if all_changes else 'false'}\n")


if __name__ == '__main__':
    main()
