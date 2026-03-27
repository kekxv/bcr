#!/usr/bin/env python3
"""
Get test platforms from changed modules' presubmit.yml configurations.
Outputs a JSON matrix configuration for GitHub Actions.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Set

import yaml

# BCR platform to GitHub Actions runner mapping
PLATFORM_TO_RUNNER = {
    # Debian variants -> ubuntu-latest
    'debian10': 'ubuntu-latest',
    'debian11': 'ubuntu-latest',
    'debian12': 'ubuntu-latest',
    
    # Ubuntu variants
    'ubuntu2004': 'ubuntu-latest',
    'ubuntu2204': 'ubuntu-latest',
    'ubuntu2404': 'ubuntu-latest',
    'ubuntu2404_arm64': 'ubuntu-24.04-arm',
    'ubuntu_arm64': 'ubuntu-24.04-arm',
    
    # macOS variants
    'macos': 'macos-latest',
    'macos_arm64': 'macos-latest',  # macos-latest now runs on M1
    'macos14': 'macos-latest',
    'macos15': 'macos-latest',
    
    # Windows
    'windows': 'windows-latest',
    
    # Linux ARM64 generic
    'linux_arm64': 'ubuntu-24.04-arm',
}

# Default platforms if no presubmit.yml found
DEFAULT_PLATFORMS = ['ubuntu2404', 'macos', 'windows']


def get_platforms_from_presubmit(presubmit_path: Path) -> List[str]:
    """Extract platforms from presubmit.yml matrix configuration."""
    if not presubmit_path.exists():
        return DEFAULT_PLATFORMS
    
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
        
        return platforms if platforms else DEFAULT_PLATFORMS
        
    except (yaml.YAMLError, IOError):
        return DEFAULT_PLATFORMS


def get_required_runners(modules_path: Path, changed_modules: Dict[str, List[str]]) -> Set[str]:
    """
    Get all required GitHub Actions runners from changed modules.
    Returns a set of runner OS types.
    """
    runners: Set[str] = set()
    
    for module_name, versions in changed_modules.items():
        for version in versions:
            version_path = modules_path / module_name / version
            presubmit_path = version_path / 'presubmit.yml'
            
            platforms = get_platforms_from_presubmit(presubmit_path)
            
            for platform in platforms:
                runner = PLATFORM_TO_RUNNER.get(platform)
                if runner:
                    runners.add(runner)
                else:
                    # Unknown platform, use ubuntu-latest as fallback
                    print(f"Warning: Unknown platform '{platform}', using ubuntu-latest", file=sys.stderr)
                    runners.add('ubuntu-latest')
    
    return runners


def main():
    parser = argparse.ArgumentParser(
        description='Get test platforms from presubmit.yml configurations'
    )
    parser.add_argument('--registry-path', default='.', help='Registry root path')
    parser.add_argument('--changes-json', required=True, help='JSON file with changed modules')
    parser.add_argument('--output', help='Output JSON file path')
    args = parser.parse_args()
    
    # Read changes
    changes_path = Path(args.changes_json)
    if not changes_path.exists():
        print(f"Error: Changes file not found: {changes_path}", file=sys.stderr)
        sys.exit(1)
    
    with open(changes_path, 'r') as f:
        changes = json.load(f)
    
    # Get all_changes or modified_versions or new_versions
    all_changes = changes.get('all_changes', {})
    if not all_changes:
        all_changes = changes.get('modified_versions', {})
    if not all_changes:
        all_changes = changes.get('new_versions', {})
    
    if not all_changes:
        # No changes - output empty matrix
        output = {'include': []}
    else:
        modules_path = Path(args.registry_path) / 'modules'
        runners = get_required_runners(modules_path, all_changes)
        
        # Build matrix include list
        # Map runners back to platform names for display
        runner_to_platform = {
            'ubuntu-latest': 'ubuntu2404',
            'ubuntu-24.04-arm': 'linux_arm64',
            'macos-latest': 'macos',
            'windows-latest': 'windows',
        }
        
        include = []
        for runner in sorted(runners):
            platform = runner_to_platform.get(runner, runner)
            include.append({
                'platform': platform,
                'os': runner
            })
        
        output = {'include': include}
    
    json_output = json.dumps(output, indent=2)
    
    if args.output:
        Path(args.output).write_text(json_output)
    else:
        print(json_output)
    
    # Set GitHub Actions outputs if running in CI
    if 'GITHUB_OUTPUT' in os.environ:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            # Output compact JSON for matrix
            f.write(f"matrix={json.dumps(output)}\n")


if __name__ == '__main__':
    main()