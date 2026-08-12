#!/usr/bin/env python3
"""Generate a Bazel Central Registry module entry."""

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Iterable

from template_processor import load_templates, process_templates, substitute_placeholders


MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
MODULE_RE = re.compile(r"^[a-z][a-z0-9._-]*$")
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]*$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def validate_component(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def resolve_within(root: Path, relative: str | Path) -> Path:
    root = root.resolve()
    relative = Path(relative)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"Unsafe relative path: {relative}")
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"Symbolic links are not allowed: {current}")
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path escapes root: {relative}")
    return resolved


def natural_tokens(value: str) -> tuple[tuple[int, Any], ...]:
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token.lower())
        for token in re.findall(r"\d+|\D+", value)
    )


def version_key(value: str) -> tuple[Any, ...]:
    normalized = value[1:] if value.startswith("v") else value
    match = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)", normalized)
    if not match:
        return (1, natural_tokens(normalized))
    major, minor, patch = (int(match.group(i) or 0) for i in range(1, 4))
    suffix = match.group(4)
    if not suffix:
        stage = (2, ())  # release
    elif suffix.startswith(".bcr."):
        stage = (3, natural_tokens(suffix[5:]))  # BCR revision
    else:
        stage = (1, natural_tokens(suffix.lstrip("-._")))  # prerelease
    return (0, major, minor, patch, *stage)


def sort_versions(versions: Iterable[str]) -> list[str]:
    return sorted(versions, key=version_key)


def calculate_integrity(data: bytes) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def validate_public_https_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Source URL must be public HTTPS without embedded credentials")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError(f"Source host resolves to a non-public address: {ip}")


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_archive(url: str) -> str:
    print(f"下载: {url}")
    validate_public_https_url(url)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        SafeRedirectHandler(),
    )
    request = urllib.request.Request(url, headers={"User-Agent": "BCR-Publish/1.0"})
    downloaded = 0
    sha256 = hashlib.sha256()
    with opener.open(request, timeout=120) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Source archive exceeds the 1 GiB limit")
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            downloaded += len(chunk)
            if downloaded > MAX_DOWNLOAD_BYTES:
                raise ValueError("Source archive exceeds the 1 GiB limit")
            sha256.update(chunk)
    return "sha256-" + base64.b64encode(sha256.digest()).decode("ascii")


def update_module_version(content: str, version: str) -> str:
    if "{VERSION}" in content or "{{VERSION}}" in content:
        return substitute_placeholders(content, {"VERSION": version})
    module_match = re.search(r"module\s*\((.*?)\)", content, re.DOTALL)
    if not module_match:
        raise ValueError("MODULE.bazel does not contain a module() declaration")
    block = module_match.group(1)
    if re.search(r'version\s*=\s*"[^"]*"', block):
        new_block = re.sub(r'version\s*=\s*"[^"]*"', f'version = "{version}"', block, count=1)
    else:
        name_match = re.search(r'name\s*=\s*"[^"]*"', block)
        if not name_match:
            raise ValueError("module() declaration does not contain a name")
        new_block = block.replace(name_match.group(0), f"{name_match.group(0)}, version = \"{version}\"", 1)
    return content[:module_match.start(1)] + new_block + content[module_match.end(1):]


def build_metadata(existing_path: Path, template: Dict[str, Any] | None, version: str) -> Dict[str, Any]:
    if existing_path.exists():
        metadata = json.loads(existing_path.read_text(encoding="utf-8"))
    elif template:
        metadata = dict(template)
    else:
        raise ValueError("New modules require metadata.template.json")

    required = ("homepage", "maintainers", "repository")
    missing = [key for key in required if not metadata.get(key)]
    if missing:
        raise ValueError(f"metadata is missing required fields: {', '.join(missing)}")
    versions = list(metadata.get("versions", []))
    if version not in versions:
        versions.append(version)
    metadata["versions"] = sort_versions(versions)
    metadata.setdefault("yanked_versions", {})
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 BCR module entry")
    parser.add_argument("--tag-name", required=True)
    parser.add_argument("--module-name", required=True)
    parser.add_argument("--registry-path", default="registry")
    parser.add_argument("--ruleset-path", default=".")
    parser.add_argument("--tag-prefix", default="v")
    parser.add_argument("--templates-dir", default=".bcr")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--strip-prefix", default="")
    args = parser.parse_args()

    try:
        module_name = validate_component(args.module_name, MODULE_RE, "module name")
        version = args.tag_name[len(args.tag_prefix):] if args.tag_name.startswith(args.tag_prefix) else args.tag_name
        version = validate_component(version, VERSION_RE, "version")
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        validate_component(repository, REPOSITORY_RE, "GITHUB_REPOSITORY")
        owner, repository_name = repository.split("/", 1)

        registry_root = Path(args.registry_path).resolve()
        ruleset_root = Path(args.ruleset_path).resolve()
        templates_path = resolve_within(ruleset_root, args.templates_dir)
        context = {
            "OWNER": owner,
            "REPO": repository_name,
            "VERSION": version,
            "TAG": args.tag_name,
            "MODULE": module_name,
        }
        templates = process_templates(load_templates(templates_path), context)

        source_template = dict(templates.get("source", {}))
        url = args.source_url or source_template.get("url") or (
            f"https://github.com/{owner}/{repository_name}/archive/refs/tags/{args.tag_name}.tar.gz"
        )
        integrity = download_archive(url)

        if args.strip_prefix:
            strip_prefix = args.strip_prefix
        elif "strip_prefix" in source_template:
            strip_prefix = source_template.get("strip_prefix")
        else:
            strip_prefix = f"{repository_name}-{version}"

        modules_root = registry_root / "modules"
        if modules_root.is_symlink():
            raise ValueError(f"Symbolic links are not allowed: {modules_root}")
        modules_root.mkdir(parents=True, exist_ok=True)
        module_root = resolve_within(modules_root, module_name)
        entry = resolve_within(module_root, version)
        if entry.exists():
            raise ValueError(f"Module version already exists: {module_name}@{version}")

        metadata_path = resolve_within(module_root, "metadata.json")
        metadata = build_metadata(metadata_path, templates.get("metadata"), version)

        module_content = templates.get("module_bazel")
        if not module_content:
            root_module = resolve_within(ruleset_root, "MODULE.bazel")
            if not root_module.is_file():
                raise ValueError("MODULE.bazel not found in templates or repository root")
            module_content = update_module_version(root_module.read_text(encoding="utf-8"), version)

        entry.mkdir(parents=True)
        source = source_template
        source.update({"url": url, "integrity": integrity})
        if strip_prefix:
            source["strip_prefix"] = strip_prefix
        else:
            source.pop("strip_prefix", None)
        if templates.get("patches"):
            source.update({"patches": templates["patches"], "patch_strip": 1})
        if templates.get("overlay"):
            source["overlay"] = templates["overlay"]

        (entry / "source.json").write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
        (entry / "MODULE.bazel").write_text(module_content, encoding="utf-8")
        if templates.get("presubmit"):
            (entry / "presubmit.yml").write_text(templates["presubmit"], encoding="utf-8")

        for directory, values in (("patches", templates.get("patches_data", {})),
                                  ("overlay", templates.get("overlay_data", {}))):
            for name, content in values.items():
                target = resolve_within(entry / directory, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)

        module_root.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

        branch = f"{module_name}.{version}"
        print(f"版本: {version}")
        print(f"entry_path={entry}")
        print(f"branch_name={branch}")
        if output := os.environ.get("GITHUB_OUTPUT"):
            with open(output, "a", encoding="utf-8") as handle:
                handle.write(
                    f"module_name={module_name}\nversion={version}\n"
                    f"entry_path={entry}\nbranch_name={branch}\n"
                )
        return 0
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
