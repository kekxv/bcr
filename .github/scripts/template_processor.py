#!/usr/bin/env python3
"""
模板处理器 - 从 ruleset 的 .bcr/ 目录加载和处理模板。
"""

import argparse
import base64
import hashlib
import json
import os
import yaml
from pathlib import Path
from typing import Any, Dict


def calculate_integrity(data: bytes) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode('ascii')


def substitute_placeholders(content: str, context: Dict[str, str]) -> str:
    for key, value in context.items():
        content = content.replace(f"{{{key}}}", value)
    return content


def load_templates(templates_dir: Path) -> Dict[str, Any]:
    if not templates_dir.exists():
        return {}

    templates = {}

    for name, filename in [('metadata', 'metadata.template.json'), ('source', 'source.template.json')]:
        path = templates_dir / filename
        if path.exists():
            templates[name] = json.loads(path.read_text())

    for name, filename in [('presubmit', 'presubmit.yml'), ('module_bazel', 'MODULE.bazel')]:
        path = templates_dir / filename
        if path.exists():
            templates[name] = path.read_text()

    patches_dir = templates_dir / 'patches'
    if patches_dir.exists():
        templates['patches'] = {}
        templates['patches_data'] = {}
        for f in patches_dir.glob("*.patch"):
            data = f.read_bytes()
            templates['patches'][f.name] = calculate_integrity(data)
            templates['patches_data'][f.name] = data

    overlay_dir = templates_dir / 'overlay'
    if overlay_dir.exists():
        templates['overlay'] = {}
        templates['overlay_data'] = {}
        for f in overlay_dir.rglob("*"):
            if f.is_file() and not f.name.startswith('.'):
                rel = str(f.relative_to(overlay_dir))
                data = f.read_bytes()
                templates['overlay'][rel] = calculate_integrity(data)
                templates['overlay_data'][rel] = data

    return templates


def process_templates(templates: Dict[str, Any], context: Dict[str, str]) -> Dict[str, Any]:
    processed = {}

    for key in ['metadata', 'source']:
        if key in templates:
            processed[key] = {}
            for k, v in templates[key].items():
                processed[key][k] = substitute_placeholders(v, context) if isinstance(v, str) else v

    for key in ['presubmit', 'module_bazel']:
        if key in templates:
            processed[key] = substitute_placeholders(templates[key], context)

    for key in ['patches', 'patches_data', 'overlay', 'overlay_data']:
        processed[key] = templates.get(key, {})

    return processed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--templates-dir', default='.bcr')
    parser.add_argument('--owner', default='')
    parser.add_argument('--repo', default='')
    parser.add_argument('--version', default='')
    parser.add_argument('--tag', default='')
    parser.add_argument('--module-name', default='')
    args = parser.parse_args()

    context = {
        'OWNER': args.owner, 'REPO': args.repo, 'VERSION': args.version,
        'TAG': args.tag, 'MODULE': args.module_name,
    }

    templates = load_templates(Path(args.templates_dir))
    processed = process_templates(templates, context)

    github_output = os.environ.get('GITHUB_OUTPUT', '')
    if github_output:
        with open(github_output, 'a') as f:
            for key in ['metadata', 'source', 'presubmit', 'module_bazel']:
                f.write(f"has_{key}={'true' if key in processed else 'false'}\n")


if __name__ == '__main__':
    main()