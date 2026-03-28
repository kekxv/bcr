#!/usr/bin/env python3
"""
Unified presubmit check script.
Runs all validations in a single job to conserve GitHub Actions minutes.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from registry import RegistryClient, Version

# Valid checks that can be skipped
VALID_SKIP_CHECKS = {
    'url-stability-check',
    'module-dot-bazel-check',
    'presubmit-yaml-check',
    'attestations-check',
    'source-integrity-check',
}

# Label to skip check mapping (label -> check name)
LABEL_TO_SKIP_CHECK = {
    'url-stability': 'url-stability-check',
    'skip-url-stability': 'url-stability-check',
    'skip-url-stability-check': 'url-stability-check',
}


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'


class CheckResult:
    """Result of a single check."""
    def __init__(self, name: str, passed: bool, message: str = "", fixable: bool = False):
        self.name = name
        self.passed = passed
        self.message = message
        self.fixable = fixable

    def __str__(self) -> str:
        status = f"{Colors.GREEN}✓{Colors.RESET}" if self.passed else f"{Colors.RED}✗{Colors.RESET}"
        return f"{status} {self.name}: {self.message}"


class PresubmitChecker:
    """Main presubmit checker class."""

    def __init__(self, registry_path: str = ".", skip_checks: Optional[Set[str]] = None, fix: bool = False):
        self.registry = RegistryClient(registry_path)
        self.skip_checks = skip_checks or set()
        self.fix = fix
        self.results: Dict[str, List[CheckResult]] = {}
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def detect_changed_modules(self) -> List[Tuple[str, Optional[str], str]]:
        """
        Detect changed modules by git diff.
        Returns list of (module_name, version, change_type) tuples.
        change_type can be: 'new', 'modified', 'deleted'
        """
        changes: List[Tuple[str, Optional[str], str]] = []

        try:
            # Get changed files in modules/ directory
            result = subprocess.run(
                ['git', 'diff', '--name-status', 'origin/main', '--', 'modules/'],
                capture_output=True, text=True, check=True
            )

            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue

                parts = line.split('\t')
                if len(parts) < 2:
                    continue

                status = parts[0][0]  # A=Added, M=Modified, D=Deleted, R=Renamed
                file_path = parts[-1]

                # Parse path: modules/<name>/<version>/file
                path_parts = file_path.split('/')
                if len(path_parts) >= 3:
                    module_name = path_parts[1]
                    version = path_parts[2] if len(path_parts) >= 3 else None

                    # Skip if not a version directory
                    if version in ['metadata.json', 'README.md']:
                        version = None

                    change_type = 'new' if status == 'A' else 'modified' if status == 'M' else 'deleted'
                    changes.append((module_name, version, change_type))

            # Also check for new modules (metadata.json added)
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split('\t')
                if len(parts) >= 2 and parts[0][0] == 'A' and parts[-1].endswith('metadata.json'):
                    module_name = parts[-1].split('/')[1]
                    changes.append((module_name, None, 'new'))

        except subprocess.CalledProcessError:
            # Fall back to detect_new_versions if git diff fails
            print(f"{Colors.YELLOW}Warning: Could not get git diff, falling back to metadata comparison{Colors.RESET}")
            for module_name, version in self.detect_new_versions():
                changes.append((module_name, version, 'new'))

        # Remove duplicates
        seen = set()
        unique_changes = []
        for module_name, version, change_type in changes:
            key = (module_name, version)
            if key not in seen:
                seen.add(key)
                unique_changes.append((module_name, version, change_type))

        return unique_changes

    def check_json_yaml_format(self, module_name: str, version: Optional[str]) -> List[CheckResult]:
        """Validate JSON and YAML file formats."""
        results = []
        version_path = self.registry.modules_path / module_name / (version or "")

        files_to_check = []
        if version:
            files_to_check = list(version_path.glob("*.json")) + list(version_path.glob("*.yml")) + list(version_path.glob("*.yaml"))
        else:
            # Check metadata.json
            metadata_path = self.registry.modules_path / module_name / "metadata.json"
            if metadata_path.exists():
                files_to_check.append(metadata_path)

        for file_path in files_to_check:
            try:
                if file_path.suffix == '.json':
                    with open(file_path, 'r') as f:
                        json.load(f)
                else:
                    with open(file_path, 'r') as f:
                        yaml.safe_load(f)
                results.append(CheckResult(f"format/{file_path.name}", True, "Valid format"))
            except (json.JSONDecodeError, yaml.YAMLError) as e:
                results.append(CheckResult(
                    f"format/{file_path.name}",
                    False,
                    f"Invalid format: {e}",
                    fixable=False
                ))

        return results

    def check_metadata(self, module_name: str) -> List[CheckResult]:
        """Validate metadata.json structure."""
        results = []
        metadata = self.registry.get_metadata(module_name)

        if metadata is None:
            return [CheckResult("metadata", False, "metadata.json not found", fixable=False)]

        # Check required fields
        required_fields = ['homepage', 'maintainers', 'versions']
        for field in required_fields:
            if field not in metadata:
                results.append(CheckResult(f"metadata/{field}", False, f"Missing required field: {field}"))

        # Check versions match directory structure
        versions = metadata.get('versions', [])
        actual_versions = []
        module_path = self.registry.modules_path / module_name
        for item in module_path.iterdir():
            if item.is_dir() and (item / "source.json").exists():
                actual_versions.append(item.name)

        # Sort both for comparison
        try:
            versions_sorted = sorted(versions, key=lambda v: Version.parse(v))
            actual_versions_sorted = sorted(actual_versions, key=lambda v: Version.parse(v))
        except ValueError:
            versions_sorted = sorted(versions)
            actual_versions_sorted = sorted(actual_versions)

        if set(versions) != set(actual_versions):
            missing = set(actual_versions) - set(versions)
            extra = set(versions) - set(actual_versions)
            msg = []
            if missing:
                msg.append(f"Versions in metadata but not in directory: {missing}")
            if extra:
                msg.append(f"Versions in directory but not in metadata: {extra}")
            results.append(CheckResult(
                "metadata/versions-match",
                False,
                "; ".join(msg),
                fixable=True
            ))
        else:
            results.append(CheckResult("metadata/versions-match", True, "Versions match"))

        # Check maintainers
        maintainers = metadata.get('maintainers', [])
        if not maintainers:
            results.append(CheckResult("metadata/maintainers", False, "No maintainers listed"))
        else:
            for i, maintainer in enumerate(maintainers):
                if 'email' not in maintainer:
                    results.append(CheckResult(f"metadata/maintainer-{i}/email", False, "Missing email"))
                if 'github' not in maintainer:
                    results.append(CheckResult(f"metadata/maintainer-{i}/github", False, "Missing github"))

        return results

    def check_source_integrity(self, module_name: str, version: str) -> List[CheckResult]:
        """Download and verify source integrity."""
        results = []
        source = self.registry.get_source(module_name, version)

        if source is None:
            return [CheckResult("source", False, "source.json not found")]

        url = source.get('url')
        expected_integrity = source.get('integrity')
        strip_prefix = source.get('strip_prefix', '')

        if not url:
            return [CheckResult("source/url", False, "URL not specified")]

        if not expected_integrity:
            return [CheckResult("source/integrity", False, "Integrity not specified")]

        # Parse integrity (format: "sha256-BASE64")
        if not expected_integrity.startswith('sha256-'):
            return [CheckResult("source/integrity-format", False, "Only sha256 integrity is supported")]

        try:
            import base64
            expected_hash = base64.b64decode(expected_integrity[7:]).hex()
        except Exception:
            return [CheckResult("source/integrity-format", False, "Invalid integrity format")]

        # Download and verify
        try:
            import urllib.request
            import ssl

            # Create SSL context that allows us to download
            ssl_context = ssl.create_default_context()

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                req = urllib.request.Request(url, headers={'User-Agent': 'BCR-Presubmit/1.0'})
                with urllib.request.urlopen(req, context=ssl_context, timeout=60) as response:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        tmp.write(chunk)
                tmp_path = tmp.name

            # Calculate hash
            sha256 = hashlib.sha256()
            with open(tmp_path, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    sha256.update(chunk)

            actual_hash = sha256.hexdigest()

            if actual_hash == expected_hash:
                results.append(CheckResult("source/integrity", True, "Integrity verified"))
            else:
                results.append(CheckResult(
                    "source/integrity",
                    False,
                    f"Hash mismatch: expected {expected_hash}, got {actual_hash}",
                    fixable=True
                ))

            # Verify strip_prefix if specified
            if strip_prefix:
                strip_prefix_result = self._verify_strip_prefix(tmp_path, url, strip_prefix)
                results.append(strip_prefix_result)

            os.unlink(tmp_path)

        except Exception as e:
            results.append(CheckResult("source/download", False, f"Failed to download: {e}"))

        # Verify overlay file integrity
        overlay = source.get('overlay', {})
        if overlay:
            overlay_path = self.registry.modules_path / module_name / version / "overlay"
            for overlay_file, expected_integrity in overlay.items():
                file_path = overlay_path / overlay_file
                if not file_path.exists():
                    results.append(CheckResult(
                        f"overlay/{overlay_file}",
                        False,
                        f"Overlay file not found: {overlay_file}",
                        fixable=False
                    ))
                    continue

                # Calculate hash of overlay file
                sha256 = hashlib.sha256()
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        sha256.update(chunk)

                # Convert to expected format (sha256-BASE64)
                import base64
                actual_integrity = "sha256-" + base64.b64encode(sha256.digest()).decode('ascii')

                if actual_integrity == expected_integrity:
                    results.append(CheckResult(f"overlay/{overlay_file}", True, "Integrity verified"))
                else:
                    results.append(CheckResult(
                        f"overlay/{overlay_file}",
                        False,
                        f"Hash mismatch: expected {expected_integrity}, got {actual_integrity}",
                        fixable=True
                    ))

        # Verify patch file integrity
        patches = source.get('patches', {})
        if patches:
            patches_path = self.registry.modules_path / module_name / version / "patches"
            for patch_file, expected_integrity in patches.items():
                file_path = patches_path / patch_file
                if not file_path.exists():
                    results.append(CheckResult(
                        f"patch/{patch_file}",
                        False,
                        f"Patch file not found: {patch_file}",
                        fixable=False
                    ))
                    continue

                # Calculate hash of patch file
                sha256 = hashlib.sha256()
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        sha256.update(chunk)

                # Convert to expected format (sha256-BASE64)
                actual_integrity = "sha256-" + base64.b64encode(sha256.digest()).decode('ascii')

                if actual_integrity == expected_integrity:
                    results.append(CheckResult(f"patch/{patch_file}", True, "Integrity verified"))
                else:
                    results.append(CheckResult(
                        f"patch/{patch_file}",
                        False,
                        f"Hash mismatch: expected {expected_integrity}, got {actual_integrity}",
                        fixable=True
                    ))

        return results

    def _verify_strip_prefix(self, archive_path: str, url: str, strip_prefix: str) -> CheckResult:
        """Verify that the strip_prefix matches the archive structure."""
        try:
            # Determine archive type from URL
            if url.endswith('.tar.gz') or url.endswith('.tgz'):
                extractor = tarfile.open(archive_path, 'r:gz')
                file_list = extractor.getnames()
            elif url.endswith('.tar.bz2'):
                extractor = tarfile.open(archive_path, 'r:bz2')
                file_list = extractor.getnames()
            elif url.endswith('.tar.xz'):
                extractor = tarfile.open(archive_path, 'r:xz')
                file_list = extractor.getnames()
            elif url.endswith('.zip'):
                extractor = zipfile.ZipFile(archive_path, 'r')
                file_list = extractor.namelist()
            else:
                return CheckResult("source/strip_prefix", True, f"Unknown archive type, cannot verify strip_prefix")

            # Get the top-level directory of each file
            top_dirs = set()
            for name in file_list:
                # Skip directories (end with /)
                if name.endswith('/'):
                    continue
                parts = name.split('/')
                if len(parts) > 1:
                    top_dirs.add(parts[0])

            if not top_dirs:
                return CheckResult("source/strip_prefix", False, f"No top-level directory found in archive")

            # Check if strip_prefix matches the top-level directory
            if len(top_dirs) == 1:
                actual_prefix = list(top_dirs)[0]
                if actual_prefix == strip_prefix:
                    return CheckResult("source/strip_prefix", True, f"strip_prefix '{strip_prefix}' verified")
                else:
                    return CheckResult(
                        "source/strip_prefix",
                        False,
                        f"strip_prefix mismatch: configured '{strip_prefix}', but archive contains '{actual_prefix}'",
                        fixable=True
                    )
            else:
                # Multiple top-level items
                return CheckResult(
                    "source/strip_prefix",
                    False,
                    f"strip_prefix '{strip_prefix}' specified but archive has multiple top-level items: {sorted(top_dirs)}",
                    fixable=True
                )

        except Exception as e:
            return CheckResult("source/strip_prefix", False, f"Failed to verify strip_prefix: {e}")

    def check_url_stability(self, module_name: str, version: str) -> List[CheckResult]:
        """Check if URL is a stable release archive."""
        if 'url-stability-check' in self.skip_checks:
            return [CheckResult("url-stability", True, "Skipped by request")]

        source = self.registry.get_source(module_name, version)
        if source is None:
            return []

        url = source.get('url', '')

        # Check for GitHub releases URL pattern
        # Stable: https://github.com/<org>/<repo>/releases/download/<version>/<file>
        # Unstable: https://github.com/<org>/<repo>/archive/<ref>.tar.gz
        stable_pattern = r'https://github\.com/[^/]+/[^/]+/releases/download/[^/]+/[^/]+$'
        archive_pattern = r'https://github\.com/[^/]+/[^/]+/archive/'

        if re.match(stable_pattern, url):
            return [CheckResult("url-stability", True, "Stable release URL")]
        elif re.search(archive_pattern, url):
            return [CheckResult(
                "url-stability",
                False,
                "GitHub archive URLs are not stable (checksum may change). Use release assets instead.",
                fixable=False
            )]
        else:
            # Non-GitHub URLs - warn but don't fail
            return [CheckResult(
                "url-stability",
                True,
                f"Non-GitHub URL: {url}. Please ensure it is a stable archive.",
                fixable=False
            )]

    def check_module_dot_bazel(self, module_name: str, version: str) -> List[CheckResult]:
        """Verify MODULE.bazel if present."""
        if 'module-dot-bazel-check' in self.skip_checks:
            return [CheckResult("module-bazel", True, "Skipped by request")]

        results = []
        module_content = self.registry.get_module_dot_bazel(module_name, version)

        if module_content is None:
            # MODULE.bazel is optional if patches will add it
            return [CheckResult("module-bazel", True, "Not present (may be added via patches)")]

        # Basic syntax check
        if 'module(' not in module_content:
            results.append(CheckResult("module-bazel/syntax", False, "Missing module() call"))

        # Check name matches
        name_match = re.search(r'module\([^)]*name\s*=\s*"([^"]+)"', module_content, re.DOTALL)
        if name_match:
            declared_name = name_match.group(1)
            if declared_name != module_name:
                results.append(CheckResult(
                    "module-bazel/name",
                    False,
                    f"Module name mismatch: declared '{declared_name}', expected '{module_name}'"
                ))
        else:
            results.append(CheckResult("module-bazel/name", False, "Could not parse module name"))

        # Check version matches
        version_match = re.search(r'module\([^)]*version\s*=\s*"([^"]+)"', module_content, re.DOTALL)
        if version_match:
            declared_version = version_match.group(1)
            if declared_version != version:
                results.append(CheckResult(
                    "module-bazel/version",
                    False,
                    f"Module version mismatch: declared '{declared_version}', expected '{version}' (directory name)"
                ))
        else:
            results.append(CheckResult("module-bazel/version", False, "Could not parse module version"))

        if not results:
            results.append(CheckResult("module-bazel", True, "Valid"))

        return results

    def check_presubmit_yaml(self, module_name: str, version: str) -> List[CheckResult]:
        """Check presubmit.yml configuration."""
        if 'presubmit-yaml-check' in self.skip_checks:
            return [CheckResult("presubmit-yaml", True, "Skipped by request")]

        presubmit = self.registry.get_presubmit(module_name, version)

        if presubmit is None:
            return [CheckResult("presubmit-yaml", False, "presubmit.yml not found", fixable=True)]

        results = []

        # Check matrix structure
        matrix = presubmit.get('matrix', {})
        if not matrix:
            results.append(CheckResult("presubmit-yaml/matrix", False, "Missing matrix configuration"))
        else:
            if 'platform' not in matrix:
                results.append(CheckResult("presubmit-yaml/matrix-platform", False, "Missing platform in matrix"))
            if 'bazel' not in matrix:
                results.append(CheckResult("presubmit-yaml/matrix-bazel", False, "Missing bazel in matrix"))

        # Check tasks
        tasks = presubmit.get('tasks', {})
        if not tasks:
            results.append(CheckResult("presubmit-yaml/tasks", False, "No tasks defined"))

        for task_name, task_config in tasks.items():
            if 'platform' not in task_config:
                results.append(CheckResult(f"presubmit-yaml/task-{task_name}/platform", False, "Missing platform"))
            if 'bazel' not in task_config:
                results.append(CheckResult(f"presubmit-yaml/task-{task_name}/bazel", False, "Missing bazel version"))

        # Check for changes from previous version
        prev_version = self.registry.get_previous_version(module_name, version)
        if prev_version:
            prev_presubmit = self.registry.get_presubmit(module_name, prev_version)
            if prev_presubmit and presubmit != prev_presubmit:
                results.append(CheckResult(
                    "presubmit-yaml/changes",
                    True,
                    f"Presubmit changed from version {prev_version}",
                    fixable=False
                ))

        if not results:
            results.append(CheckResult("presubmit-yaml", True, "Valid configuration"))

        return results

    def check_attestations(self, module_name: str, version: str) -> List[CheckResult]:
        """Check attestations if present."""
        if 'attestations-check' in self.skip_checks:
            return [CheckResult("attestations", True, "Skipped by request")]

        attestations = self.registry.get_attestations(module_name, version)

        if attestations is None:
            # Attestations are optional
            return []

        results = []

        # Validate attestations structure
        if 'attestations' not in attestations:
            results.append(CheckResult("attestations/structure", False, "Missing 'attestations' key"))
        else:
            for att in attestations.get('attestations', []):
                if 'format' not in att:
                    results.append(CheckResult("attestations/format", False, "Missing format"))
                if 'url' not in att:
                    results.append(CheckResult("attestations/url", False, "Missing URL"))

        return results

    def run_checks(self, module_name: str, version: Optional[str], change_type: str = 'new') -> List[CheckResult]:
        """Run all checks for a module/version."""
        results = []

        # Always check metadata
        results.extend(self.check_metadata(module_name))

        # Check JSON/YAML format
        results.extend(self.check_json_yaml_format(module_name, version))

        if version:
            # Version-specific checks
            # Run source integrity check for both new and modified versions
            if 'source-integrity-check' not in self.skip_checks:
                results.extend(self.check_source_integrity(module_name, version))

            results.extend(self.check_url_stability(module_name, version))
            results.extend(self.check_module_dot_bazel(module_name, version))
            results.extend(self.check_presubmit_yaml(module_name, version))
            results.extend(self.check_attestations(module_name, version))

        return results

    def generate_report(self, output_path: Optional[str] = None) -> str:
        """Generate a markdown report of all results."""
        # Start with summary table format
        lines = ["| 检查项 | 状态 |\n", "| :--- | :--- |\n"]

        total_checks = 0
        passed_checks = 0
        failed_checks = []

        for module_name, versions in self.results.items():
            for version, results in versions.items():
                version_str = f"@{version}" if version else ""
                module_header = f"**{module_name}{version_str}**"

                for result in results:
                    total_checks += 1
                    status = "✅" if result.passed else "❌"
                    if not result.passed:
                        failed_checks.append((module_name, version, result))
                    else:
                        passed_checks += 1

                    check_name = result.name
                    message = result.message if result.message else ""
                    lines.append(f"| {module_header}: {check_name} | {status} {message} |\n")

        # Summary section
        lines.append("\n")
        lines.append("---\n\n")
        lines.append("### 统计\n\n")
        lines.append(f"| 总计 | 通过 | 失败 |\n")
        lines.append(f"| :---: | :---: | :---: |\n")
        lines.append(f"| {total_checks} | {passed_checks} | {len(failed_checks)} |\n")

        if failed_checks:
            lines.append("\n### ❌ 失败的检查\n\n")
            for module_name, version, result in failed_checks:
                version_str = f"@{version}" if version else ""
                lines.append(f"- `{module_name}{version_str}`: **{result.name}**")
                if result.message:
                    lines.append(f"  - {result.message}")
                if result.fixable:
                    lines.append(f"  - 💡 可通过 `--fix` 参数自动修复")

        report = "".join(lines)

        if output_path:
            Path(output_path).write_text(report)

        return report

    def run(self, pr_number: Optional[str] = None):
        """Run all presubmit checks on changed modules."""
        print(f"{Colors.BLUE}Running presubmit checks...{Colors.RESET}")
        if self.skip_checks:
            print(f"  Skipping: {', '.join(self.skip_checks)}")
        print()

        changes = self.detect_changed_modules()

        if not changes:
            print(f"{Colors.YELLOW}No changed modules detected.{Colors.RESET}")
            return 0

        print(f"Detected {len(changes)} changed module(s):\n")

        exit_code = 0

        for module_name, version, change_type in changes:
            version_str = f"@{version}" if version else ""
            change_indicator = "[NEW]" if change_type == 'new' else "[MODIFIED]" if change_type == 'modified' else "[DELETED]"
            print(f"{Colors.BLUE}Checking {module_name}{version_str} {change_indicator}...{Colors.RESET}")

            # Skip deleted versions
            if change_type == 'deleted':
                print(f"  {Colors.YELLOW}Skipping checks for deleted version{Colors.RESET}")
                continue

            results = self.run_checks(module_name, version, change_type)

            # Store results
            if module_name not in self.results:
                self.results[module_name] = {}
            self.results[module_name][version or "metadata"] = results

            # Print results
            for result in results:
                if result.passed:
                    print(f"  {Colors.GREEN}✓{Colors.RESET} {result.name}")
                else:
                    print(f"  {Colors.RED}✗{Colors.RESET} {result.name}: {result.message}")
                    exit_code = 1

            print()

        # Generate report
        report = self.generate_report('.github/presubmit-results.md')
        print(report)

        return exit_code


def main():
    parser = argparse.ArgumentParser(
        description='BCR Presubmit Checks - Validates new module versions'
    )
    parser.add_argument('--pr-number', help='PR number for comment')
    parser.add_argument('--pr-labels', help='Space-separated PR labels (for skip checks)')
    parser.add_argument('--skip-checks', nargs='+', help='Checks to skip')
    parser.add_argument('--fix', action='store_true', help='Auto-fix where possible')
    args = parser.parse_args()

    skip_checks = set(args.skip_checks or [])

    # Parse skip checks from PR labels
    # Format 1: skip-<check-name> (e.g., skip-url-stability-check)
    # Format 2: direct label mapping (e.g., url-stability)
    if args.pr_labels:
        for label in args.pr_labels.split():
            # Check direct label mapping first
            if label in LABEL_TO_SKIP_CHECK:
                check_name = LABEL_TO_SKIP_CHECK[label]
                skip_checks.add(check_name)
                print(f"Will skip check: {check_name} (from label '{label}')")
            # Check skip-<check-name> format
            elif label.startswith('skip-'):
                check_name = label[5:]  # Remove 'skip-' prefix
                if check_name in VALID_SKIP_CHECKS:
                    skip_checks.add(check_name)
                    print(f"Will skip check: {check_name} (from label '{label}')")

    invalid = skip_checks - VALID_SKIP_CHECKS
    if invalid:
        print(f"Invalid skip checks: {invalid}", file=sys.stderr)
        print(f"Valid options: {VALID_SKIP_CHECKS}", file=sys.stderr)
        sys.exit(1)

    checker = PresubmitChecker(skip_checks=skip_checks, fix=args.fix)
    exit_code = checker.run(args.pr_number)

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
