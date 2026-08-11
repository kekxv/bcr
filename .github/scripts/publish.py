#!/usr/bin/env python3
"""Generate the Bazel registry index and its static GitHub Pages site."""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from registry import RegistryClient


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).with_name("index.html.temp")


def repository_parts(repo_name: str) -> tuple[str, str]:
    """Return a safe owner/repository pair for GitHub Pages URLs."""
    parts = [part for part in repo_name.strip("/").split("/") if part]
    return (parts[0], parts[1]) if len(parts) == 2 else ("your-org", "bcr")


def repository_name() -> str:
    """Read the repository name from Actions or the local Git remote."""
    if value := os.environ.get("GITHUB_REPOSITORY"):
        return value
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"github\.com(?::|/)([^/]+)/([^/]+?)(?:\.git)?$", result.stdout.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else "your-org/bcr"


def module_update_dates(limit: int = 200) -> dict[str, str]:
    """Find the most recent commit date for each module."""
    result = subprocess.run(
        [
            "git", "log", "-n", str(limit), "--format=@@%cs", "--name-only",
            "--", "modules/",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}

    dates: dict[str, str] = {}
    current_date = ""
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("@@"):
            current_date = line[2:]
            continue
        parts = line.split("/")
        if len(parts) >= 2 and parts[0] == "modules":
            dates.setdefault(parts[1], current_date)
    return dates


def collect_modules(registry: RegistryClient) -> list[dict[str, Any]]:
    """Collect the public module metadata used by the static site."""
    update_dates = module_update_dates()
    modules: list[dict[str, Any]] = []

    for name in registry.get_all_modules():
        metadata = registry.get_metadata(name)
        if metadata is None:
            continue
        versions = metadata.get("versions", [])
        modules.append(
            {
                "name": name,
                "versions": versions,
                "latest_version": versions[-1] if versions else "",
                "homepage": metadata.get("homepage", ""),
                "repository": metadata.get("repository", []),
                "deprecated": metadata.get("deprecated") or None,
                "yanked_versions": metadata.get("yanked_versions", {}),
                "updated_at": update_dates.get(name, ""),
            }
        )

    return sorted(modules, key=lambda module: module["name"].lower())


def generate_registry_index(registry: RegistryClient) -> dict[str, Any]:
    """Generate the Bazel-compatible bazel_registry.json index."""
    modules: dict[str, Any] = {}
    for name in registry.get_all_modules():
        metadata = registry.get_metadata(name)
        if metadata is None:
            continue
        modules[name] = {
            "versions": metadata.get("versions", []),
            "yanked_versions": metadata.get("yanked_versions", {}),
            "deprecated": metadata.get("deprecated") or None,
        }
    return {"mirrors": [], "modules": modules}


def generate_site_data(registry: RegistryClient, repo_name: str) -> dict[str, Any]:
    """Generate the JSON document consumed by the static page."""
    owner, repo = repository_parts(repo_name)
    modules = collect_modules(registry)
    recent = sorted(
        (module for module in modules if module["updated_at"]),
        key=lambda module: module["updated_at"],
        reverse=True,
    )[:4]
    if not recent:
        recent = modules[:4]

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repository": repo_name,
        "repository_url": f"https://github.com/{owner}/{repo}",
        "registry_url": f"https://{owner}.github.io/{repo}",
        "stats": {
            "modules": len(modules),
            "versions": sum(len(module["versions"]) for module in modules),
            "deprecated": sum(bool(module["deprecated"]) for module in modules),
        },
        "recent_modules": [module["name"] for module in recent],
        "modules": modules,
    }


def generate_index_html(repo_name: str) -> str:
    """Render the small static shell; module data stays in registry-data.json."""
    if not TEMPLATE.exists():
        raise FileNotFoundError(f"Page template not found: {TEMPLATE}")
    return TEMPLATE.read_text(encoding="utf-8").replace(
        "{{REPO_NAME}}", html.escape(repo_name)
    )


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    registry = RegistryClient(str(ROOT))
    repo_name = repository_name()

    registry_index = generate_registry_index(registry)
    site_data = generate_site_data(registry, repo_name)
    write_json(ROOT / "bazel_registry.json", registry_index)
    write_json(ROOT / "registry-data.json", site_data)
    (ROOT / "index.html").write_text(
        generate_index_html(repo_name), encoding="utf-8"
    )

    print(
        f"Generated bazel_registry.json, registry-data.json and index.html "
        f"for {len(site_data['modules'])} modules"
    )


if __name__ == "__main__":
    main()
