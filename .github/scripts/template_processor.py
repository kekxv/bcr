#!/usr/bin/env python3
"""Load and safely render the templates used by the BCR publisher."""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict


PLACEHOLDER_RE = re.compile(
    r"\{\{([A-Z][A-Z0-9_]*)\}\}|\{([A-Z][A-Z0-9_]*)\}"
)


def calculate_integrity(data: bytes) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def substitute_placeholders(content: str, context: Dict[str, str]) -> str:
    """Replace both {KEY} and {{KEY}} placeholders in one pass."""
    def replace(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        return str(context[key]) if key in context else match.group(0)

    return PLACEHOLDER_RE.sub(replace, content)


def substitute_value(value: Any, context: Dict[str, str]) -> Any:
    """Recursively render strings in JSON-compatible structures."""
    if isinstance(value, str):
        return substitute_placeholders(value, context)
    if isinstance(value, list):
        return [substitute_value(item, context) for item in value]
    if isinstance(value, dict):
        return {
            substitute_placeholders(key, context) if isinstance(key, str) else key:
            substitute_value(item, context)
            for key, item in value.items()
        }
    return value


def ensure_safe_tree(root: Path) -> Path:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Template directory not found: {root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symbolic links are not allowed in templates: {path}")
        path.resolve().relative_to(root)
    return root


def load_templates(templates_dir: Path) -> Dict[str, Any]:
    if not templates_dir.exists():
        return {}
    templates_dir = ensure_safe_tree(templates_dir)
    templates: Dict[str, Any] = {}

    for name, filename in (
        ("metadata", "metadata.template.json"),
        ("source", "source.template.json"),
    ):
        path = templates_dir / filename
        if path.is_file():
            templates[name] = json.loads(path.read_text(encoding="utf-8"))

    for name, filename in (("presubmit", "presubmit.yml"), ("module_bazel", "MODULE.bazel")):
        path = templates_dir / filename
        if path.is_file():
            templates[name] = path.read_text(encoding="utf-8")

    patches_dir = templates_dir / "patches"
    if patches_dir.is_dir():
        templates["patches"] = {}
        templates["patches_data"] = {}
        for path in sorted(patches_dir.glob("*.patch")):
            data = path.read_bytes()
            templates["patches"][path.name] = calculate_integrity(data)
            templates["patches_data"][path.name] = data

    overlay_dir = templates_dir / "overlay"
    if overlay_dir.is_dir():
        templates["overlay"] = {}
        templates["overlay_data"] = {}
        for path in sorted(overlay_dir.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                relative = path.relative_to(overlay_dir).as_posix()
                data = path.read_bytes()
                templates["overlay"][relative] = calculate_integrity(data)
                templates["overlay_data"][relative] = data

    return templates


def process_templates(templates: Dict[str, Any], context: Dict[str, str]) -> Dict[str, Any]:
    processed = {
        key: substitute_value(templates[key], context)
        for key in ("metadata", "source", "presubmit", "module_bazel")
        if key in templates
    }
    for key in ("patches", "patches_data", "overlay", "overlay_data"):
        processed[key] = templates.get(key, {})
    return processed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--templates-dir", default=".bcr")
    parser.add_argument("--owner", default="")
    parser.add_argument("--repo", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--tag", default="")
    parser.add_argument("--module-name", default="")
    args = parser.parse_args()

    context = {
        "OWNER": args.owner,
        "REPO": args.repo,
        "VERSION": args.version,
        "TAG": args.tag,
        "MODULE": args.module_name,
    }
    try:
        processed = process_templates(load_templates(Path(args.templates_dir)), context)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as handle:
            for key in ("metadata", "source", "presubmit", "module_bazel"):
                handle.write(f"has_{key}={'true' if key in processed else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
