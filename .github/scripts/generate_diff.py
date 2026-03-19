#!/usr/bin/env python3
"""
Generate diff between a new module version and its previous version.
Compares filesystem (new version) with metadata.json's previous version.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from registry import RegistryClient


def load_json_or_yaml(content: str, ext: str) -> Any:
    """Parse JSON or YAML content."""
    if ext == '.json':
        return json.loads(content)
    else:
        return yaml.safe_load(content)


def diff_dicts(old: Dict, new: Dict, path: str = "") -> List[str]:
    """Generate a simple diff between two dicts."""
    changes = []

    all_keys = set(old.keys()) | set(new.keys())

    for key in sorted(all_keys):
        key_path = f"{path}.{key}" if path else key

        if key not in old:
            changes.append(f"+ {key_path}: {json.dumps(new[key])}")
        elif key not in new:
            changes.append(f"- {key_path}: {json.dumps(old[key])}")
        elif isinstance(old[key], dict) and isinstance(new[key], dict):
            changes.extend(diff_dicts(old[key], new[key], key_path))
        elif old[key] != new[key]:
            changes.append(f"- {key_path}: {json.dumps(old[key])}")
            changes.append(f"+ {key_path}: {json.dumps(new[key])}")

    return changes


def detect_new_versions(registry: RegistryClient) -> List[Tuple[str, Optional[str]]]:
    """
    Detect new versions by comparing filesystem with metadata.json.
    Returns list of (module_name, version) tuples for new versions.
    """
    changes: List[Tuple[str, Optional[str]]] = []

    for module_dir in registry.modules_path.iterdir():
        if not module_dir.is_dir():
            continue

        module_name = module_dir.name
        metadata = registry.get_metadata(module_name)
        existing_versions = set(metadata.get('versions', [])) if metadata else set()

        # If no metadata, this is a new module
        if metadata is None:
            changes.append((module_name, None))
            continue

        # Find new versions
        for item in module_dir.iterdir():
            if item.is_dir() and (item / "source.json").exists():
                version = item.name
                if version not in existing_versions:
                    changes.append((module_name, version))

    return changes


def read_file_content(path: Path) -> Optional[str]:
    """Read file content if it exists."""
    if not path.exists():
        return None
    try:
        return path.read_text()
    except IOError:
        return None


def diff_version(registry: RegistryClient, module_name: str, version: str) -> Optional[str]:
    """Generate diff for a specific new version against its previous version."""
    version_path = registry.modules_path / module_name / version

    lines = [f"## {module_name}@{version}\n"]

    # Get previous version from metadata
    metadata = registry.get_metadata(module_name)
    versions = metadata.get('versions', []) if metadata else []

    try:
        # Find the position where new version would be inserted
        from registry import Version as V
        new_v = V.parse(version)
        prev_version = None
        for v in versions:
            if V.parse(v) < new_v:
                prev_version = v
            else:
                break
    except Exception:
        # Fallback: just get the last version
        prev_version = versions[-1] if versions else None

    # Files to compare
    files_to_diff = ['source.json', 'MODULE.bazel', 'presubmit.yml']
    has_changes = False

    for filename in files_to_diff:
        new_content = read_file_content(version_path / filename)

        if new_content is None:
            continue

        # Try to get previous version content
        if prev_version:
            old_path = registry.modules_path / module_name / prev_version / filename
            old_content = read_file_content(old_path)
        else:
            old_content = None

        if old_content is None:
            lines.append(f"### {filename} (new)")
            lines.append("```")
            lines.append(new_content)
            lines.append("```")
            lines.append("")
            has_changes = True
            continue

        if old_content != new_content:
            has_changes = True
            lines.append(f"### {filename}")

            # Try structured diff for JSON/YAML
            if filename.endswith('.json') or filename.endswith('.yml') or filename.endswith('.yaml'):
                try:
                    old_data = load_json_or_yaml(old_content, Path(filename).suffix)
                    new_data = load_json_or_yaml(new_content, Path(filename).suffix)
                    changes = diff_dicts(old_data, new_data)
                    if changes:
                        lines.append("```diff")
                        lines.extend(changes)
                        lines.append("```")
                except Exception:
                    lines.append("```")
                    lines.append(new_content)
                    lines.append("```")
            else:
                lines.append("```")
                lines.append(new_content)
                lines.append("```")

            lines.append("")

    if not has_changes:
        return None

    return "\n".join(lines)


def diff_new_module(registry: RegistryClient, module_name: str) -> Optional[str]:
    """Generate info for a completely new module."""
    module_path = registry.modules_path / module_name
    metadata_path = module_path / "metadata.json"

    lines = [f"## {module_name} (new module)\n"]

    # Show metadata
    metadata_content = read_file_content(metadata_path)
    if metadata_content:
        lines.append("### metadata.json")
        lines.append("```json")
        lines.append(metadata_content)
        lines.append("```")
        lines.append("")

    # List all versions found
    versions = []
    for item in module_path.iterdir():
        if item.is_dir() and (item / "source.json").exists():
            versions.append(item.name)

    if versions:
        lines.append(f"### Versions: {', '.join(sorted(versions))}")
        lines.append("")

        # Show first version details
        first_version = sorted(versions)[0]
        version_path = module_path / first_version

        for filename in ['source.json', 'MODULE.bazel', 'presubmit.yml']:
            content = read_file_content(version_path / filename)
            if content:
                lines.append(f"### {first_version}/{filename}")
                ext = filename.split('.')[-1]
                lines.append(f"```{ext}")
                lines.append(content)
                lines.append("```")
                lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Generate diff between new module versions and their previous versions'
    )
    parser.add_argument('--output', required=True, help='Output file path')
    args = parser.parse_args()

    registry = RegistryClient('.')
    changes = detect_new_versions(registry)

    if not changes:
        print("No new versions detected")
        Path(args.output).write_text("# No new module versions detected\n")
        return 0

    sections = []

    for module_name, version in changes:
        if version:
            diff = diff_version(registry, module_name, version)
        else:
            diff = diff_new_module(registry, module_name)

        if diff:
            sections.append(diff)

    if sections:
        header = "# Module Version Diff\n\n"
        header += "Comparing new versions with their previous versions:\n\n"
        report = header + "\n".join(sections)
    else:
        report = "# No significant changes detected\n"

    Path(args.output).write_text(report)
    print(f"Generated diff report at {args.output}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
