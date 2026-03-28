#!/usr/bin/env python3
"""
Run Bazel tests according to presubmit.yml configuration.
"""

import argparse
import json
import os
import yaml
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description='Run Bazel tests for BCR modules')
    parser.add_argument('--platform', required=True, help='Platform name (e.g., ubuntu2404, macos, windows, linux_arm64)')
    parser.add_argument('--changes-json', required=True, help='JSON file with changed modules')
    return parser.parse_args()


def get_github_runner_platform(platform_name: str) -> str:
    """Map presubmit platform to GitHub Actions runner OS."""
    mapping = {
        # Debian variants
        'debian10': 'linux',
        'debian11': 'linux',
        'debian12': 'linux',
        # Ubuntu variants
        'ubuntu2404': 'linux',
        'ubuntu2004': 'linux',
        'ubuntu2204': 'linux',
        'ubuntu2404_arm64': 'linux',
        'ubuntu_arm64': 'linux',
        'linux_arm64': 'linux',
        # macOS variants
        'macos': 'macos',
        'macos_arm64': 'macos',
        'macos14': 'macos',
        'macos15': 'macos',
        # Windows
        'windows': 'windows',
    }
    return mapping.get(platform_name, platform_name)


def should_run_for_platform(presubmit_platforms: list, current_platform: str) -> bool:
    """Check if current platform matches any of the presubmit platforms."""
    current_runner = get_github_runner_platform(current_platform)

    for p in presubmit_platforms:
        runner = get_github_runner_platform(p)
        if runner == current_runner:
            return True
    return False


def run_bazel_tests(platform: str, changes_json_path: str = None, registry_path: Path = None):
    """Run bazel tests according to presubmit.yml for changed modules."""

    # Use current directory as registry if not specified
    if registry_path is None:
        registry_path = Path.cwd()

    # Ensure absolute path
    registry_path = registry_path.absolute()

    # Convert to file URL (Windows paths need forward slashes)
    # On Windows, D:\path becomes file:///D:/path
    registry_url = registry_path.as_uri()

    # Read detected changes
    if changes_json_path:
        changes_file = Path(changes_json_path)
    else:
        changes_file = registry_path / 'changes.json'

    if not changes_file.exists():
        print(f"Error: changes.json not found at {changes_file}", file=sys.stderr)
        return 1

    with open(changes_file) as f:
        changes = json.load(f)

    # Get all_changes or modified_versions or new_versions
    all_changes = changes.get('all_changes', {})
    if not all_changes:
        all_changes = changes.get('modified_versions', {})
    if not all_changes:
        all_changes = changes.get('new_versions', {})

    if not all_changes:
        print("No modules to test")
        return 0

    failed = []
    skipped = []
    passed = []

    for module_name, versions in all_changes.items():
        for version in versions:
            print(f"\n{'='*60}")
            print(f"Testing {module_name}@{version} on platform: {platform}")
            print(f"Registry path: {registry_path}")
            print('='*60)

            presubmit_path = registry_path / 'modules' / module_name / version / 'presubmit.yml'

            if not presubmit_path.exists():
                print(f"[SKIP] presubmit.yml not found for {module_name}@{version}")
                skipped.append(f"{module_name}@{version}")
                continue

            # Read presubmit.yml
            with open(presubmit_path) as f:
                config = yaml.safe_load(f)

            matrix = config.get('matrix', {})
            presubmit_platforms = matrix.get('platform', ['ubuntu2404'])

            # Check if current platform is in the matrix
            if not should_run_for_platform(presubmit_platforms, platform):
                print(f"[SKIP] platform '{platform}' not in presubmit.yml matrix: {presubmit_platforms}")
                skipped.append(f"{module_name}@{version}:{platform}")
                continue

            print(f"[OK] Platform '{platform}' matched presubmit.yml matrix: {presubmit_platforms}")

            # Get all bazel versions from presubmit.yml and test each one
            bazel_versions = matrix.get('bazel', ['7.x'])
            tasks = config.get('tasks', {})

            for bazel_ver in bazel_versions:
                print(f"\n>>> Testing with Bazel version: {bazel_ver} <<<")

                # Shutdown any existing Bazel server to avoid conflicts
                subprocess.run(['bazel', 'shutdown'], capture_output=True)

                # Set the bazel version using bazelisk via USE_BAZEL_VERSION env var
                env = os.environ.copy()
                env['USE_BAZEL_VERSION'] = bazel_ver

                for task_name, task_config in tasks.items():
                    build_targets = task_config.get('build_targets', [])
                    test_targets = task_config.get('test_targets', [])

                    if not build_targets and not test_targets:
                        print(f"  No targets defined for task: {task_name}")
                        continue

                    print(f"\n  Task: {task_name}")

                    # Create temporary test workspace (cross-platform)
                    temp_base = Path(tempfile.gettempdir()) / 'bcr_test'
                    test_dir = temp_base / f"{module_name}_{version}"
                    test_dir.mkdir(parents=True, exist_ok=True)

                    # Create MODULE.bazel
                    module_content = f'''module(name = "test_workspace", version = "1.0.0")

bazel_dep(name = "{module_name}", version = "{version}")
'''
                    (test_dir / "MODULE.bazel").write_text(module_content)

                    # Create BUILD.bazel
                    (test_dir / "BUILD.bazel").write_text('')

                    # Run build targets
                    for target in build_targets:
                        # Replace ${{ }} variables
                        actual_target = target.replace('${{ module }}', module_name)

                        print(f"\n    Building: {target}")

                        result = subprocess.run(
                            ['bazel', 'build', actual_target,
                             '--registry=' + registry_url,
                             '--registry=https://bcr.bazel.build',
                             '--enable_bzlmod'],
                            cwd=test_dir,
                            capture_output=True,
                            text=True,
                            env=env
                        )

                        if result.returncode != 0:
                            print(f"    FAILED: {result.stderr}")
                            failed.append(f"{module_name}@{version}: {target} (Bazel {bazel_ver})")
                        else:
                            print(f"    SUCCESS")
                            passed.append(f"{module_name}@{version}: {target} (Bazel {bazel_ver})")

                    # Run test targets
                    for target in test_targets:
                        # Replace ${{ }} variables
                        actual_target = target.replace('${{ module }}', module_name)

                        print(f"\n    Testing: {target}")

                        result = subprocess.run(
                            ['bazel', 'test', actual_target,
                             '--registry=' + registry_url,
                             '--registry=https://bcr.bazel.build',
                             '--enable_bzlmod'],
                            cwd=test_dir,
                            capture_output=True,
                            text=True,
                            env=env
                        )

                        if result.returncode != 0:
                            print(f"    FAILED: {result.stderr}")
                            failed.append(f"{module_name}@{version}: {target} (Bazel {bazel_ver})")
                        else:
                            print(f"    SUCCESS")
                            passed.append(f"{module_name}@{version}: {target} (Bazel {bazel_ver})")

    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY for platform: {platform}")
    print('='*60)

    if skipped:
        print(f"\n[SKIP] Skipped ({len(skipped)}):")
        for s in skipped:
            print(f"  - {s}")

    if passed:
        print(f"\n[PASS] Passed ({len(passed)}):")
        for p in passed:
            print(f"  - {p}")

    if failed:
        print(f"\n[FAIL] Failed ({len(failed)}):")
        for f in failed:
            print(f"  - {f}")
        return 1
    else:
        print(f"\n[PASS] All tests passed!")
        return 0


if __name__ == '__main__':
    args = parse_args()
    sys.exit(run_bazel_tests(args.platform, changes_json_path=args.changes_json))