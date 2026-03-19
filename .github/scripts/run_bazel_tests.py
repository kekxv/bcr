#!/usr/bin/env python3
"""
Run Bazel tests according to presubmit.yml configuration.
"""

import json
import yaml
import subprocess
import sys
from pathlib import Path


def run_bazel_tests(registry_path: Path = Path('.')):
    """Run bazel tests according to presubmit.yml for changed modules."""

    # Read detected changes
    with open('changes.json') as f:
        changes = json.load(f)

    if not changes.get('new_versions'):
        print("No new modules to test")
        return 0

    failed = []

    for module_name, versions in changes['new_versions'].items():
        for version in versions:
            print(f"\n{'='*60}")
            print(f"Testing {module_name}@{version}")
            print('='*60)

            presubmit_path = registry_path / 'modules' / module_name / version / 'presubmit.yml'

            if not presubmit_path.exists():
                print(f"Warning: presubmit.yml not found for {module_name}@{version}")
                continue

            # Read presubmit.yml
            with open(presubmit_path) as f:
                config = yaml.safe_load(f)

            matrix = config.get('matrix', {})
            bazel_versions = matrix.get('bazel', ['7.x'])
            platforms = matrix.get('platform', ['ubuntu2404'])

            tasks = config.get('tasks', {})

            for task_name, task_config in tasks.items():
                build_targets = task_config.get('build_targets', [])
                test_targets = task_config.get('test_targets', [])

                if not build_targets and not test_targets:
                    print(f"  No targets defined for task: {task_name}")
                    continue

                # Use first bazel version and platform
                bazel_version = bazel_versions[0]

                print(f"\n  Task: {task_name}")
                print(f"  Bazel version: {bazel_version}")

                # Create temporary test workspace
                test_dir = Path('/tmp/bcr_test') / f"{module_name}_{version}"
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
                    # Remove @module// prefix for local workspace
                    if actual_target.startswith(f'@{module_name}//'):
                        actual_target = actual_target[len(f'@{module_name}'):]
                    elif actual_target.startswith('@'):
                        # Keep other external deps
                        pass

                    print(f"\n    Building: {target}")

                    result = subprocess.run(
                        ['bazel', 'build', actual_target,
                         '--registry=file://' + str(registry_path.absolute()),
                         '--enable_bzlmod',
                         '--nocheck_direct_dependencies'],
                        cwd=test_dir,
                        capture_output=True,
                        text=True
                    )

                    if result.returncode != 0:
                        print(f"    FAILED: {result.stderr}")
                        failed.append(f"{module_name}@{version}: {target}")
                    else:
                        print(f"    SUCCESS")

                # Run test targets
                for target in test_targets:
                    actual_target = target.replace('${{ module }}', module_name)
                    if actual_target.startswith(f'@{module_name}//'):
                        actual_target = actual_target[len(f'@{module_name}'):]

                    print(f"\n    Testing: {target}")

                    result = subprocess.run(
                        ['bazel', 'test', actual_target,
                         '--registry=file://' + str(registry_path.absolute()),
                         '--enable_bzlmod',
                         '--nocheck_direct_dependencies'],
                        cwd=test_dir,
                        capture_output=True,
                        text=True
                    )

                    if result.returncode != 0:
                        print(f"    FAILED: {result.stderr}")
                        failed.append(f"{module_name}@{version}: {target}")
                    else:
                        print(f"    SUCCESS")

    if failed:
        print(f"\n{'='*60}")
        print(f"FAILED: {len(failed)} target(s)")
        print('='*60)
        for f in failed:
            print(f"  - {f}")
        return 1
    else:
        print(f"\n{'='*60}")
        print("All tests passed!")
        print('='*60)
        return 0


if __name__ == '__main__':
    sys.exit(run_bazel_tests())
