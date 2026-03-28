#!/usr/bin/env python3
"""
Check if a platform is needed for testing based on modules' presubmit.yml configurations.
Outputs 'needed=true' or 'needed=false' for GitHub Actions.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

import yaml

# Platform to (OS, arch) mapping
PLATFORM_TO_OS_ARCH = {
    # Debian variants (x86_64)
    'debian10': ('linux', 'x86_64'),
    'debian11': ('linux', 'x86_64'),
    'debian12': ('linux', 'x86_64'),
    # Ubuntu variants (x86_64)
    'ubuntu2404': ('linux', 'x86_64'),
    'ubuntu2004': ('linux', 'x86_64'),
    'ubuntu2204': ('linux', 'x86_64'),
    # Ubuntu/Linux ARM64
    'ubuntu2404_arm64': ('linux', 'arm64'),
    'ubuntu_arm64': ('linux', 'arm64'),
    'linux_arm64': ('linux', 'arm64'),
    # macOS variants (arm64 on modern runners)
    'macos': ('macos', 'arm64'),
    'macos_arm64': ('macos', 'arm64'),
    'macos14': ('macos', 'arm64'),
    'macos15': ('macos', 'arm64'),
    # Windows (x86_64)
    'windows': ('windows', 'x86_64'),
}


def get_platform_os_arch(platform: str) -> tuple:
    """Get the (OS, arch) tuple for a platform."""
    return PLATFORM_TO_OS_ARCH.get(platform, (platform, 'x86_64'))


def get_presubmit_platforms(presubmit_path: Path) -> List[str]:
    """Get platforms from presubmit.yml."""
    if not presubmit_path.exists():
        return ['ubuntu2404', 'macos', 'windows']  # Default platforms
    
    try:
        with open(presubmit_path, 'r') as f:
            config = yaml.safe_load(f)
        
        matrix = config.get('matrix', {})
        platforms = matrix.get('platform', [])
        
        if not platforms:
            # Check tasks for platform definitions
            tasks = config.get('tasks', {})
            for task_name, task_config in tasks.items():
                if 'platform' in task_config:
                    task_platform = task_config['platform']
                    if isinstance(task_platform, str) and not task_platform.startswith('${'):
                        platforms.append(task_platform)
        
        return platforms if platforms else ['ubuntu2404', 'macos', 'windows']
        
    except (yaml.YAMLError, IOError):
        return ['ubuntu2404', 'macos', 'windows']


def is_platform_needed(platform: str, modules_path: Path, all_changes: Dict[str, List[str]]) -> bool:
    """
    Check if any module needs testing on the given platform.
    Matches both OS and architecture.
    """
    current_os, current_arch = get_platform_os_arch(platform)
    
    for module_name, versions in all_changes.items():
        for version in versions:
            presubmit_path = modules_path / module_name / version / 'presubmit.yml'
            presubmit_platforms = get_presubmit_platforms(presubmit_path)
            
            # Check if any presubmit platform matches current OS and arch
            for presubmit_platform in presubmit_platforms:
                presubmit_os, presubmit_arch = get_platform_os_arch(presubmit_platform)
                # Match OS, and if arch is specified, match arch too
                if presubmit_os == current_os:
                    # If presubmit specifies arm64, only match arm64
                    # If presubmit specifies x86_64 (or generic), match both
                    if presubmit_arch == current_arch:
                        return True
                    # Generic platforms (debian10, ubuntu2404) match x86_64 runners
                    # But also allow them to match arm64 if explicitly specified
                    if presubmit_arch == 'x86_64' and current_arch == 'x86_64':
                        return True
    
    return False


def main():
    parser = argparse.ArgumentParser(
        description='Check if platform is needed for testing'
    )
    parser.add_argument('--platform', required=True, help='Platform to check')
    parser.add_argument('--changes-json', required=True, help='JSON file with changed modules')
    parser.add_argument('--registry-path', default='.', help='Registry root path')
    args = parser.parse_args()
    
    # Read changes
    changes_path = Path(args.changes_json)
    if not changes_path.exists():
        print(f"Error: Changes file not found: {changes_path}", file=sys.stderr)
        sys.exit(1)
    
    with open(changes_path, 'r') as f:
        changes = json.load(f)
    
    # Get all changes
    all_changes = changes.get('all_changes', {})
    if not all_changes:
        all_changes = changes.get('modified_versions', {})
    if not all_changes:
        all_changes = changes.get('new_versions', {})
    
    modules_path = Path(args.registry_path) / 'modules'
    
    needed = is_platform_needed(args.platform, modules_path, all_changes)
    
    # Output result
    print(f"Platform '{args.platform}' needed: {needed}")
    
    # Set GitHub Actions output
    if 'GITHUB_OUTPUT' in os.environ:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"needed={'true' if needed else 'false'}\n")
    
    sys.exit(0)


if __name__ == '__main__':
    main()