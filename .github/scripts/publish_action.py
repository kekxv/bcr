#!/usr/bin/env python3
"""
发布 Action - 生成 BCR entry 文件。
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import urllib.request
import ssl
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Version:
    major: int = 0
    minor: int = 0
    patch: int = 0
    prerelease: Optional[str] = None
    bcr_patch: int = 0

    @classmethod
    def parse(cls, v: str) -> "Version":
        v = v.lstrip('v')
        m = re.match(r'^(.+)\.bcr\.(\d+)$', v)
        bcr = int(m.group(2)) if m else 0
        v = m.group(1) if m else v
        m = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-(.+))?$', v)
        if not m:
            raise ValueError(v)
        return cls(int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0), m.group(4), bcr)

    def __lt__(self, o: "Version") -> bool:
        if (self.major, self.minor, self.patch) != (o.major, o.minor, o.patch):
            return (self.major, self.minor, self.patch) < (o.major, o.minor, o.patch)
        if self.prerelease is None and o.prerelease:
            return False
        if self.prerelease and o.prerelease is None:
            return True
        if self.prerelease != o.prerelease:
            return (self.prerelease or "") < (o.prerelease or "")
        return self.bcr_patch < o.bcr_patch

    def __eq__(self, o: object) -> bool:
        return isinstance(o, Version) and (self.major, self.minor, self.patch, self.prerelease, self.bcr_patch) == (o.major, o.minor, o.patch, o.prerelease, o.bcr_patch)

    def __le__(self, o): return self == o or self < o
    def __gt__(self, o): return not self <= o
    def __ge__(self, o): return not self < o


def sort_versions(versions: List[str]) -> List[str]:
    try:
        return sorted(versions, key=Version.parse)
    except:
        return sorted(versions)


def calculate_integrity(data: bytes) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode('ascii')


def substitute(content: str, ctx: Dict[str, str]) -> str:
    for k, v in ctx.items():
        content = content.replace(f"{{{k}}}", v)
    return content


def download_archive(url: str) -> Tuple[bytes, str]:
    print(f"下载: {url}")
    ssl_ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={'User-Agent': 'BCR-Publish/1.0'})
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=120) as resp:
        data = resp.read()
    return data, calculate_integrity(data)


def load_templates(path: Path, ctx: Dict[str, str]) -> Dict[str, Any]:
    if not path.exists():
        return {}
    t = {}
    for n, f in [('metadata', 'metadata.template.json'), ('source', 'source.template.json')]:
        p = path / f
        if p.exists():
            d = json.loads(p.read_text())
            t[n] = {k: substitute(v, ctx) if isinstance(v, str) else v for k, v in d.items()}
    for n, f in [('presubmit', 'presubmit.yml'), ('module_bazel', 'MODULE.bazel')]:
        p = path / f
        if p.exists():
            t[n] = substitute(p.read_text(), ctx)
    patches_dir = path / 'patches'
    if patches_dir.exists():
        t['patches'] = {}
        t['patches_data'] = {}
        for f in patches_dir.glob("*.patch"):
            d = f.read_bytes()
            t['patches'][f.name] = calculate_integrity(d)
            t['patches_data'][f.name] = d
    overlay_dir = path / 'overlay'
    if overlay_dir.exists():
        t['overlay'] = {}
        t['overlay_data'] = {}
        for f in overlay_dir.rglob("*"):
            if f.is_file() and not f.name.startswith('.'):
                r = str(f.relative_to(overlay_dir))
                d = f.read_bytes()
                t['overlay'][r] = calculate_integrity(d)
                t['overlay_data'][r] = d
    return t


def main():
    parser = argparse.ArgumentParser(description='生成 BCR module entry')
    parser.add_argument('--tag-name', required=True)
    parser.add_argument('--module-name', required=True)
    parser.add_argument('--registry-path', default='registry')
    parser.add_argument('--ruleset-path', default='.')
    parser.add_argument('--tag-prefix', default='v')
    parser.add_argument('--templates-dir', default='.bcr')
    parser.add_argument('--source-url', default='')
    parser.add_argument('--strip-prefix', default='')
    args = parser.parse_args()

    version = args.tag_name[len(args.tag_prefix):] if args.tag_name.startswith(args.tag_prefix) else args.tag_name
    print(f"版本: {version}")

    repo = os.environ.get('GITHUB_REPOSITORY', '')
    owner, name = repo.split('/') if repo else ('', '')

    ctx = {'OWNER': owner, 'REPO': name, 'VERSION': version, 'TAG': args.tag_name, 'MODULE': args.module_name}

    t = load_templates(Path(args.ruleset_path) / args.templates_dir, ctx)

    url = args.source_url or t.get('source', {}).get('url') or f"https://github.com/{owner}/{name}/archive/refs/tags/{args.tag_name}.tar.gz"
    data, integrity = download_archive(url)

    # Determine strip_prefix:
    # 1. Command line --strip-prefix takes precedence
    # 2. Template value (including empty string "") means user explicitly wants that value
    # 3. Default to "{name}-{version}" only if template has no strip_prefix key at all
    source_template = t.get('source', {})
    if args.strip_prefix:
        strip = args.strip_prefix
    elif 'strip_prefix' in source_template:
        # User explicitly set strip_prefix in template (could be "" to disable)
        strip = source_template['strip_prefix']
    else:
        strip = f"{name}-{version}"
    print(f"Strip prefix: {strip}")

    entry = Path(args.registry_path) / "modules" / args.module_name / version
    entry.mkdir(parents=True, exist_ok=True)

    source = {"url": url, "integrity": integrity}
    if strip:
        source["strip_prefix"] = strip
    if t.get('patches'):
        source["patches"] = t['patches']
        source["patch_strip"] = 1
    if t.get('overlay'):
        source["overlay"] = t['overlay']

    (entry / "source.json").write_text(json.dumps(source, indent=2) + '\n')

    # MODULE.bazel - required, priority: .bcr template > root MODULE.bazel > error
    if t.get('module_bazel'):
        (entry / "MODULE.bazel").write_text(t['module_bazel'])
        print("使用 .bcr/MODULE.bazel 模板")
    else:
        # Check root MODULE.bazel in ruleset
        root_module = Path(args.ruleset_path) / "MODULE.bazel"
        if root_module.exists():
            content = root_module.read_text()
            original = content

            # First try placeholder substitution
            if '{VERSION}' in content:
                content = substitute(content, ctx)
            else:
                # Need to update version only in module() block, not bazel_dep etc.
                # Find module() block and update version within it

                # Match module(...) - handle multi-line with re.DOTALL
                module_match = re.search(r'module\s*\((.*?)\)', content, re.DOTALL)
                if module_match:
                    module_block = module_match.group(1)

                    # Check if version exists in module block
                    if re.search(r'version\s*=\s*"[^"]*"', module_block):
                        # Replace existing version in module block
                        new_block = re.sub(
                            r'version\s*=\s*"[^"]*"',
                            f'version = "{version}"',
                            module_block
                        )
                    else:
                        # Add version after name attribute
                        name_match = re.search(r'name\s*=\s*"[^"]*"', module_block)
                        if name_match:
                            # Find the position after name attribute
                            new_block = module_block.replace(
                                name_match.group(0),
                                f'{name_match.group(0)}, version = "{version}"'
                            )
                        else:
                            # No name in module block - shouldn't happen
                            print("警告: module() 块中未找到 name 属性")
                            new_block = module_block

                    # Replace the entire module block
                    content = content.replace(module_block, new_block)

            (entry / "MODULE.bazel").write_text(content)
            if content != original:
                print("使用根目录 MODULE.bazel（版本已更新）")
            else:
                print("使用根目录 MODULE.bazel")
        else:
            print("错误: MODULE.bazel 未找到")
            print("请提供以下之一:")
            print("  1. .bcr/MODULE.bazel 模板文件")
            print("  2. 根目录 MODULE.bazel 文件")
            sys.exit(1)

    # presubmit.yml - optional, use template if available, otherwise skip
    if t.get('presubmit'):
        (entry / "presubmit.yml").write_text(t['presubmit'])
        print("使用 .bcr/presubmit.yml 模板")
    else:
        print("跳过 presubmit.yml（未找到 .bcr/presubmit.yml 模板）")

    if t.get('patches_data'):
        (entry / "patches").mkdir(exist_ok=True)
        for n, d in t['patches_data'].items():
            (entry / "patches" / n).write_bytes(d)

    if t.get('overlay_data'):
        (entry / "overlay").mkdir(exist_ok=True)
        for n, d in t['overlay_data'].items():
            p = entry / "overlay" / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(d)

    meta_path = Path(args.registry_path) / "modules" / args.module_name / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"versions": [], "yanked_versions": {}}
    if version not in meta["versions"]:
        meta["versions"].append(version)
        meta["versions"] = sort_versions(meta["versions"])
    meta_path.write_text(json.dumps(meta, indent=2) + '\n')

    branch = f"{args.module_name}.{version}"
    print(f"entry_path={entry}")
    print(f"branch_name={branch}")

    if out := os.environ.get('GITHUB_OUTPUT'):
        with open(out, 'a') as f:
            f.write(f"module_name={args.module_name}\nversion={version}\nentry_path={entry}\nbranch_name={branch}\n")


if __name__ == '__main__':
    main()