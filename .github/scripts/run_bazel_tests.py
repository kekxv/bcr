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


MODULE_BAZEL_DEPS_KEYS = ('module_bazel_deps', 'extra_bazel_deps')
MODULE_BAZEL_EXTRA_KEYS = ('module_bazel_extra', 'module_bazel_append', 'extra_module_bazel')


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


def _as_list(value):
  """Normalize scalar/list YAML values to a list."""
  if value is None:
    return []
  if isinstance(value, list):
    return value
  return [value]


def _quote_bazel_string(value) -> str:
  return json.dumps(str(value))


def _render_bazel_value(value) -> str:
  if isinstance(value, bool):
    return 'True' if value else 'False'
  if isinstance(value, (int, float)):
    return str(value)
  return _quote_bazel_string(value)


def render_bazel_dep(dep) -> str:
  """Render one module_bazel_deps entry as a bazel_dep(...) line."""
  if isinstance(dep, str):
    stripped = dep.strip()
    if stripped.startswith('bazel_dep('):
      return stripped
    raise ValueError(f"String module_bazel_deps entries must be complete bazel_dep(...) calls: {dep}")

  if not isinstance(dep, dict):
    raise ValueError(f"module_bazel_deps entries must be mappings or bazel_dep(...) strings: {dep}")

  if 'name' not in dep:
    raise ValueError(f"module_bazel_deps entry is missing required 'name': {dep}")

  ordered_keys = ['name', 'version', 'repo_name', 'dev_dependency', 'max_compatibility_level']
  parts = []

  for key in ordered_keys:
    if key in dep:
      parts.append(f"{key} = {_render_bazel_value(dep[key])}")

  for key in sorted(dep.keys()):
    if key not in ordered_keys:
      parts.append(f"{key} = {_render_bazel_value(dep[key])}")

  return f"bazel_dep({', '.join(parts)})"


def collect_module_bazel_deps(config: dict, task_config: dict) -> list:
  """Collect extra bazel_dep entries from top-level and task-level config."""
  deps = []
  for source in (config, config.get('test_module', {}), config.get('bcr_test_module', {}), task_config):
    if not isinstance(source, dict):
      continue
    for key in MODULE_BAZEL_DEPS_KEYS:
      deps.extend(_as_list(source.get(key)))
  return deps


def collect_module_bazel_extra(config: dict, task_config: dict) -> str:
  """Collect raw MODULE.bazel fragments from top-level and task-level config."""
  fragments = []
  for source in (config, config.get('test_module', {}), config.get('bcr_test_module', {}), task_config):
    if not isinstance(source, dict):
      continue
    for key in MODULE_BAZEL_EXTRA_KEYS:
      value = source.get(key)
      if value:
        fragments.append(str(value).strip())
  return "\n\n".join(fragments)


def create_test_module_content(module_name: str, version: str, config: dict, task_config: dict) -> str:
  """Create MODULE.bazel content for the temporary test workspace."""
  lines = [
    'module(name = "test_workspace", version = "1.0.0")',
    '',
    f'bazel_dep(name = "{module_name}", version = "{version}")',
  ]

  extra_deps = collect_module_bazel_deps(config, task_config)
  if extra_deps:
    lines.append('')
    for dep in extra_deps:
      lines.append(render_bazel_dep(dep))

  extra_content = collect_module_bazel_extra(config, task_config)
  if extra_content:
    lines.extend(['', extra_content])

  lines.append('')
  return "\n".join(lines)


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
        subprocess.run(['bazel', 'shutdown'])

        # Set the bazel version using bazelisk via USE_BAZEL_VERSION env var
        env = os.environ.copy()
        env['USE_BAZEL_VERSION'] = bazel_ver

        for task_name, task_config in tasks.items():
          build_targets = task_config.get('build_targets', [])
          test_targets = task_config.get('test_targets', [])

          # 支持 BCR 规范的 build_flags, test_flags，兼容 build_args/test_args 写法
          build_flags = task_config.get('build_flags', task_config.get('build_args', []))
          test_flags = task_config.get('test_flags', task_config.get('test_args', []))

          # 支持自定义的 bazelrc
          bazelrc_content = task_config.get('bazelrc', '')

          if not build_targets and not test_targets:
            print(f"  No targets defined for task: {task_name}")
            continue

          print(f"\n  Task: {task_name}")

          # Create temporary test workspace (加上 task_name 防止不同 task 的 .bazelrc 互相污染)
          temp_base = Path(tempfile.gettempdir()) / 'bcr_test'
          test_dir = temp_base / f"{module_name}_{version}_{task_name}"
          test_dir.mkdir(parents=True, exist_ok=True)

          # Create MODULE.bazel
          try:
            module_content = create_test_module_content(module_name, version, config, task_config)
          except ValueError as e:
            print(f"    Invalid MODULE.bazel test configuration: {e}")
            failed.append(f"{module_name}@{version}: {task_name} (invalid MODULE.bazel test configuration)")
            continue
          (test_dir / "MODULE.bazel").write_text(module_content)
          print(f"    Created MODULE.bazel with {len(module_content.splitlines())} lines")

          # Create BUILD.bazel
          (test_dir / "BUILD.bazel").write_text('')

          # Create .bazelrc 如果存在配置
          bazelrc_file = test_dir / ".bazelrc"
          if bazelrc_content:
            bazelrc_file.write_text(bazelrc_content)
            print(f"    Created .bazelrc with {len(bazelrc_content.splitlines())} lines")
          elif bazelrc_file.exists():
            # 清理上次可能遗留的 .bazelrc
            bazelrc_file.unlink()

          # Run build targets
          for target in build_targets:
            # Replace ${{ }} variables
            actual_target = target.replace('${{ module }}', module_name)

            print(f"\n    Building: {target}")

            cmd = ['bazel', 'build', actual_target,
                   '--registry=' + registry_url,
                   '--registry=https://bcr.bazel.build',
                   '--enable_bzlmod']

            # 附加 build args
            if build_flags:
              cmd.extend(build_flags)

            # 去掉 capture_output=True，允许实时将输出打印到控制台
            result = subprocess.run(
              cmd,
              cwd=test_dir,
              env=env
            )

            if result.returncode != 0:
              print(f"    FAILED: (See Bazel output above for details)")
              failed.append(f"{module_name}@{version}: {target} (Bazel {bazel_ver})")
            else:
              print(f"    SUCCESS")
              passed.append(f"{module_name}@{version}: {target} (Bazel {bazel_ver})")

          # Run test targets
          for target in test_targets:
            # Replace ${{ }} variables
            actual_target = target.replace('${{ module }}', module_name)

            print(f"\n    Testing: {target}")

            cmd = ['bazel', 'test', actual_target,
                   '--registry=' + registry_url,
                   '--registry=https://bcr.bazel.build',
                   '--enable_bzlmod']

            # 测试通常也需要 build args 来进行编译
            if build_flags:
              cmd.extend(build_flags)
            # 附加 test args
            if test_flags:
              cmd.extend(test_flags)

            # 去掉 capture_output=True，允许实时将输出打印到控制台
            result = subprocess.run(
              cmd,
              cwd=test_dir,
              env=env
            )

            if result.returncode != 0:
              print(f"    FAILED: (See Bazel output above for details)")
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
