"""Resolve platform declarations in presubmit.yml configurations."""

import re
from typing import Any, Optional


_MATRIX_REFERENCES = (
    re.compile(r"^\$\{\{\s*([^{}]+?)\s*\}\}$"),
    re.compile(r"^\$\{\s*([^{}]+?)\s*\}$"),
)


def get_task_platforms(task_config: dict, matrix: Optional[dict] = None):
    """Return a task's concrete platform restrictions, or None if unrestricted."""
    if 'platforms' in task_config:
        platforms = task_config['platforms']
        if not isinstance(platforms, list) or not all(
                isinstance(item, str) and item for item in platforms):
            raise ValueError("task.platforms must be a list of non-empty strings")
        return platforms

    platform = task_config.get('platform')
    if platform is None:
        return None
    if not isinstance(platform, str):
        raise ValueError("task.platform must be a string")

    match = None
    for pattern in _MATRIX_REFERENCES:
        match = pattern.fullmatch(platform)
        if match:
            break
    if not match:
        return [platform]
    if not isinstance(matrix, dict):
        raise ValueError("task.platform matrix reference requires a matrix")

    matrix_key = match.group(1)
    if matrix_key.startswith('matrix.'):
        matrix_key = matrix_key[len('matrix.') :]
    platforms = matrix.get(matrix_key)
    if not isinstance(platforms, list) or not platforms or not all(
            isinstance(item, str) and item for item in platforms):
        raise ValueError(
            f"task.platform references invalid matrix entry {matrix_key!r}")
    return platforms


def get_configured_platforms(
        matrix: Any, tasks: Any, default_platforms: list[str]) -> list[str]:
    """Resolve all concrete platforms required by a presubmit configuration."""
    if not isinstance(matrix, dict) or not isinstance(tasks, dict):
        return list(default_platforms)

    if 'platform' in matrix:
        platforms = matrix['platform']
        if not isinstance(platforms, list):
            raise ValueError("matrix.platform must be a list")
        if platforms:
            return platforms

    platforms = []
    for task_config in tasks.values():
        if not isinstance(task_config, dict):
            return list(default_platforms)
        task_platforms = get_task_platforms(task_config, matrix)
        if task_platforms is None:
            return list(default_platforms)
        platforms.extend(task_platforms)

    return list(dict.fromkeys(platforms)) if platforms else list(default_platforms)
