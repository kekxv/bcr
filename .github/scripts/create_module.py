#!/usr/bin/env python3
"""
快速创建 BCR 模块脚本。
支持创建新模块或添加新版本。
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request
import ssl
from pathlib import Path
from typing import Optional, Tuple


def calculate_sha256(data: bytes) -> str:
    """Calculate SHA256 hash and return base64 encoded."""
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode('ascii')


def download_and_hash(url: str) -> Tuple[bytes, str]:
    """Download URL content and return (data, integrity)."""
    ssl_context = ssl.create_default_context()
    req = urllib.request.Request(url, headers={'User-Agent': 'BCR-Create/1.0'})

    with urllib.request.urlopen(req, context=ssl_context, timeout=120) as response:
        data = response.read()

    return data, calculate_sha256(data)


def detect_strip_prefix(url: str) -> Optional[str]:
    """Detect strip_prefix from archive URL."""
    # Common patterns:
    # - SDL3-3.4.2.tar.gz -> SDL3-3.4.2
    # - repo-1.0.0.tar.gz -> repo-1.0.0
    # - v1.0.0.tar.gz -> repo-1.0.0 (need to guess)

    filename = url.split('/')[-1]

    # Remove .tar.gz, .tar.bz2, .tar.xz, .zip
    patterns = [
        r'^(.*?)\.tar\.gz$',
        r'^(.*?)\.tar\.bz2$',
        r'^(.*?)\.tar\.xz$',
        r'^(.*?)\.zip$',
        r'^(.*?)(?:\.tar)?\.gz$',
    ]

    for pattern in patterns:
        match = re.match(pattern, filename)
        if match:
            return match.group(1)

    return None


def get_github_release_url(repo: str, version: str) -> str:
    """
    Build GitHub release asset URL.
    repo format: owner/repo
    version format: v1.0.0 or 1.0.0
    """
    # Try common release asset naming patterns
    version_clean = version.lstrip('v')
    repo_name = repo.split('/')[-1]

    # Common patterns
    candidates = [
        f"https://github.com/{repo}/releases/download/{version}/{repo_name}-{version}.tar.gz",
        f"https://github.com/{repo}/releases/download/{version}/{repo_name}-{version_clean}.tar.gz",
        f"https://github.com/{repo}/releases/download/v{version_clean}/{repo_name}-{version}.tar.gz",
        f"https://github.com/{repo}/releases/download/v{version_clean}/{repo_name}-{version_clean}.tar.gz",
        f"https://github.com/{repo}/releases/download/{version}/{repo_name}.tar.gz",
        f"https://github.com/{repo}/archive/refs/tags/{version}.tar.gz",
        f"https://github.com/{repo}/archive/refs/tags/v{version_clean}.tar.gz",
    ]

    return candidates


def validate_url(url: str) -> bool:
    """Check if URL is accessible."""
    try:
        ssl_context = ssl.create_default_context()
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'BCR-Create/1.0'})
        urllib.request.urlopen(req, context=ssl_context, timeout=30)
        return True
    except:
        return False


def create_metadata(module_name: str, homepage: str, maintainers: list) -> dict:
    """Create metadata.json structure."""
    return {
        "homepage": homepage,
        "maintainers": maintainers,
        "repository": [f"github:{homepage.replace('https://github.com/', '').replace('http://github.com/', '')}"] if "github.com" in homepage else [],
        "versions": [],
        "yanked_versions": {}
    }


def create_source_json(url: str, strip_prefix: Optional[str] = None) -> Tuple[dict, bytes]:
    """Create source.json by downloading and hashing. Returns (source_dict, archive_data)."""
    print(f"Downloading {url}...")
    data, integrity = download_and_hash(url)

    # Auto-detect strip_prefix if not provided
    if strip_prefix is None:
        strip_prefix = detect_strip_prefix(url)
        if strip_prefix:
            print(f"Auto-detected strip_prefix: {strip_prefix}")

    source = {
        "url": url,
        "integrity": integrity,
        "strip_prefix": strip_prefix
    }

    return source, data


def create_presubmit_yaml(module_name: str) -> str:
    """Create a basic presubmit.yml."""
    return """matrix:
  bazel:
    - 7.x
    - 8.x
  platform:
    - ubuntu2404
    - macos
    - windows

tasks:
  verify_targets:
    name: Verify build targets
    platform: ${{ platform }}
    bazel: ${{ bazel }}
    build_targets:
      - "@{module}//..."
""".format(module=module_name)


def create_empty_module_bazel(module_name: str, version: str) -> str:
    """Create a minimal MODULE.bazel content."""
    return f'''module(
    name = "{module_name}",
    version = "{version}",
)
'''


def download_module_bazel(url: str) -> Optional[str]:
    """Download MODULE.bazel from URL."""
    try:
        ssl_context = ssl.create_default_context()
        req = urllib.request.Request(url, headers={'User-Agent': 'BCR-Create/1.0'})
        with urllib.request.urlopen(req, context=ssl_context, timeout=30) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        print(f"  Warning: Could not download MODULE.bazel from URL: {e}")
        return None


def get_module_bazel_from_archive(archive_data: bytes, strip_prefix: Optional[str]) -> Optional[str]:
    """Extract MODULE.bazel from downloaded archive."""
    import tarfile
    import zipfile
    import io

    try:
        # Try as tar.gz
        if strip_prefix:
            module_path = f"{strip_prefix}/MODULE.bazel"
        else:
            module_path = "MODULE.bazel"

        try:
            with tarfile.open(fileobj=io.BytesIO(archive_data), mode='r:gz') as tar:
                for member in tar.getmembers():
                    if member.name.endswith('MODULE.bazel') and not member.name.startswith('.'):
                        f = tar.extractfile(member)
                        if f:
                            return f.read().decode('utf-8')
        except:
            pass

        # Try as zip
        try:
            with zipfile.ZipFile(io.BytesIO(archive_data)) as zf:
                for name in zf.namelist():
                    if name.endswith('MODULE.bazel') and not name.startswith('.'):
                        return zf.read(name).decode('utf-8')
        except:
            pass

    except Exception as e:
        print(f"  Warning: Could not extract MODULE.bazel from archive: {e}")

    return None


def update_metadata_versions(metadata_path: Path, version: str):
    """Add version to metadata.json if not exists."""
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)

    versions = metadata.get('versions', [])
    if version not in versions:
        versions.append(version)
        # Sort versions (simple string sort for now)
        versions.sort()
        metadata['versions'] = versions

        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            f.write('\n')

        print(f"Added version {version} to metadata.json")


def create_module_interactive():
    """Interactive mode to create a module."""
    print("=" * 60)
    print("BCR Module Creator")
    print("=" * 60)
    print()

    # Get module name
    module_name = input("Module name (e.g., 'my_library'): ").strip()
    if not module_name:
        print("Error: Module name is required")
        sys.exit(1)

    # Check if module exists
    module_path = Path("modules") / module_name
    is_new_module = not module_path.exists()

    if is_new_module:
        print(f"\nCreating NEW module: {module_name}")
    else:
        print(f"\nAdding version to EXISTING module: {module_name}")
        # Show existing versions
        metadata_path = module_path / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)
            print(f"Existing versions: {', '.join(metadata.get('versions', []))}")
    print()

    # Get version
    version = input("Version (e.g., '1.0.0'): ").strip()
    if not version:
        print("Error: Version is required")
        sys.exit(1)

    # Check if version already exists
    version_path = module_path / version
    if version_path.exists():
        print(f"Error: Version {version} already exists for {module_name}")
        sys.exit(1)

    # Get source URL
    print("\nSource URL options:")
    print("  1. Direct URL to archive")
    print("  2. GitHub repo (auto-build release URL)")
    url_choice = input("Select (1 or 2): ").strip()

    url = None
    strip_prefix = None

    if url_choice == "2":
        repo = input("GitHub repo (format: owner/repo): ").strip()
        tag = input(f"Tag/Release (default: {version}): ").strip() or version

        candidates = get_github_release_url(repo, tag)
        print(f"\nTrying to detect release URL...")

        for candidate in candidates:
            print(f"  Checking: {candidate}")
            if validate_url(candidate):
                url = candidate
                print(f"  ✓ Found!")
                break

        if not url:
            print("  Could not auto-detect, using archive URL as fallback")
            url = candidates[-1]  # Use archive URL

        # Suggest strip_prefix based on repo name
        repo_name = repo.split('/')[-1]
        strip_prefix = f"{repo_name}-{tag.lstrip('v')}"
    else:
        url = input("Archive URL: ").strip()

    if not url:
        print("Error: URL is required")
        sys.exit(1)

    # Ask for strip_prefix confirmation
    auto_strip = detect_strip_prefix(url)
    if auto_strip:
        strip_input = input(f"Strip prefix [{auto_strip}]: ").strip()
        strip_prefix = strip_input or auto_strip
    else:
        strip_prefix = input("Strip prefix (leave empty if none): ").strip() or None

    # Download and create source.json
    print(f"\nDownloading archive...")
    try:
        source, archive_data = create_source_json(url, strip_prefix)
    except Exception as e:
        print(f"Error downloading: {e}")
        sys.exit(1)

    print(f"  Integrity: {source['integrity']}")
    print(f"  Strip prefix: {source.get('strip_prefix', 'None')}")

    # Create directories
    if is_new_module:
        module_path.mkdir(parents=True)

        # Get metadata info
        print("\nMetadata information:")
        homepage = input("Homepage URL: ").strip()
        maintainer_name = input("Maintainer name: ").strip()
        maintainer_email = input("Maintainer email: ").strip()
        maintainer_github = input("Maintainer GitHub username: ").strip()

        maintainers = [{
            "email": maintainer_email,
            "github": maintainer_github,
            "name": maintainer_name
        }]

        metadata = create_metadata(module_name, homepage, maintainers)
        metadata['versions'] = [version]

        with open(module_path / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
            f.write('\n')
        print(f"Created metadata.json")
    else:
        # Update existing metadata
        update_metadata_versions(module_path / "metadata.json", version)

    # Create version directory
    version_path.mkdir(parents=True)

    # Write source.json
    with open(version_path / "source.json", 'w') as f:
        json.dump(source, f, indent=2)
        f.write('\n')
    print(f"Created {version_path}/source.json")

    # Create presubmit.yml
    presubmit_content = create_presubmit_yaml(module_name)
    with open(version_path / "presubmit.yml", 'w') as f:
        f.write(presubmit_content)
    print(f"Created {version_path}/presubmit.yml")

    # Handle MODULE.bazel (mandatory)
    print("\n" + "-" * 40)
    print("MODULE.bazel is required for all modules.")
    print("-" * 40)

    module_bazel_content = None

    # 1. First, try to extract from the downloaded archive
    print("\n1. Checking archive for MODULE.bazel...")
    module_bazel_content = get_module_bazel_from_archive(archive_data, source.get('strip_prefix'))
    if module_bazel_content:
        print("   ✓ Found MODULE.bazel in archive")
    else:
        print("   ✗ Not found in archive")

    # 2. Ask user if they want to provide one
    if not module_bazel_content:
        print("\n2. How would you like to provide MODULE.bazel?")
        print("   1. From local file")
        print("   2. From URL")
        print("   3. Create empty one (will be created automatically)")
        choice = input("   Select (1-3, default: 3): ").strip() or "3"

        if choice == "1":
            file_path = input("   Path to MODULE.bazel: ").strip()
            if file_path and Path(file_path).exists():
                module_bazel_content = Path(file_path).read_text()
                print("   ✓ Loaded from file")
            else:
                print(f"   ✗ File not found: {file_path}")
        elif choice == "2":
            module_url = input("   URL to MODULE.bazel: ").strip()
            if module_url:
                module_bazel_content = download_module_bazel(module_url)
                if module_bazel_content:
                    print("   ✓ Downloaded from URL")
                else:
                    print("   ✗ Failed to download")

    # 3. Create empty one as fallback
    if not module_bazel_content:
        print("\n   Creating empty MODULE.bazel...")
        module_bazel_content = create_empty_module_bazel(module_name, version)
        print("   ✓ Created empty MODULE.bazel")

    # 4. Validate module name matches
    # Extract module name from MODULE.bazel content
    name_match = re.search(r'module\s*\([^)]*name\s*=\s*"([^"]+)"', module_bazel_content, re.DOTALL)
    if name_match:
        found_name = name_match.group(1)
        if found_name != module_name:
            print(f"\n   ⚠ Warning: MODULE.bazel has name='{found_name}' but module is '{module_name}'")
            fix = input("   Fix module name in MODULE.bazel? (y/n, default: y): ").strip().lower() or "y"
            if fix == "y":
                module_bazel_content = re.sub(
                    r'(name\s*=\s*")([^"]+)(")',
                    f'\\g<1>{module_name}\\g<3>',
                    module_bazel_content
                )
                print("   ✓ Fixed module name")

    # 5. Validate version matches
    version_match = re.search(r'version\s*=\s*"([^"]+)"', module_bazel_content)
    if version_match:
        found_version = version_match.group(1)
        if found_version != version:
            print(f"\n   ⚠ Warning: MODULE.bazel has version='{found_version}' but version is '{version}'")
            fix = input("   Fix version in MODULE.bazel? (y/n, default: y): ").strip().lower() or "y"
            if fix == "y":
                module_bazel_content = re.sub(
                    r'(version\s*=\s*")([^"]+)(")',
                    f'\\g<1>{version}\\g<3>',
                    module_bazel_content
                )
                print("   ✓ Fixed version")

    # Write MODULE.bazel
    with open(version_path / "MODULE.bazel", 'w') as f:
        f.write(module_bazel_content)
    print(f"\n   ✓ Created {version_path}/MODULE.bazel")

    # Ask about patches
    has_patches = input("\nDo you have patches to add? (y/n): ").strip().lower() == 'y'
    if has_patches:
        patches_dir = version_path / "patches"
        patches_dir.mkdir()

        while True:
            patch_path = input("Path to patch file (or empty to finish): ").strip()
            if not patch_path:
                break
            if Path(patch_path).exists():
                import shutil
                shutil.copy(patch_path, patches_dir / Path(patch_path).name)
                print(f"  Copied {Path(patch_path).name}")
            else:
                print(f"  File not found: {patch_path}")

        # Update source.json with patches
        patch_files = list(patches_dir.iterdir())
        if patch_files:
            with open(version_path / "source.json", 'r') as f:
                source = json.load(f)

            patches = {}
            for patch_file in patch_files:
                patch_data = patch_file.read_bytes()
                patches[patch_file.name] = calculate_sha256(patch_data)

            source['patches'] = patches
            source['patch_strip'] = 1

            with open(version_path / "source.json", 'w') as f:
                json.dump(source, f, indent=2)
                f.write('\n')
            print(f"Updated source.json with patches")

    print()
    print("=" * 60)
    print(f"Successfully created module: {module_name}@{version}")
    print("=" * 60)
    print()
    print("Next steps:")
    print(f"  1. Review the files in modules/{module_name}/{version}/")
    print(f"  2. Add any additional overlays or patches needed")
    print(f"  3. Test with: bazel build --registry=file://$(pwd) @{module_name}//...")
    print(f"  4. Commit and push to create a PR")


def main():
    parser = argparse.ArgumentParser(
        description='Create BCR module (new module or new version)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (recommended)
  %(prog)s

  # Create new module with minimal args
  %(prog)s --name my_lib --version 1.0.0 --url https://example.com/my_lib-1.0.0.tar.gz

  # Add version to existing module
  %(prog)s --name my_lib --version 1.1.0 --url https://example.com/my_lib-1.1.0.tar.gz
        """
    )

    parser.add_argument('--name', help='Module name')
    parser.add_argument('--version', help='Module version')
    parser.add_argument('--url', help='Source archive URL')
    parser.add_argument('--strip-prefix', help='Strip prefix for archive')
    parser.add_argument('--homepage', help='Module homepage')
    parser.add_argument('--github', help='GitHub repo (format: owner/repo)')
    parser.add_argument('--maintainer-name', help='Maintainer name')
    parser.add_argument('--maintainer-email', help='Maintainer email')
    parser.add_argument('--maintainer-github', help='Maintainer GitHub username')
    parser.add_argument('--module-bazel', help='Path to MODULE.bazel file (optional, will extract from archive or create empty if not provided)')
    parser.add_argument('--module-bazel-url', help='URL to download MODULE.bazel (optional)')

    args = parser.parse_args()

    # If any required args are missing, run interactive mode
    if not args.name or not args.version:
        create_module_interactive()
        return

    # Non-interactive mode (for CI/automation)
    module_name = args.name
    version = args.version
    module_path = Path("modules") / module_name
    is_new_module = not module_path.exists()

    if args.github:
        candidates = get_github_release_url(args.github, version)
        url = None
        for candidate in candidates:
            if validate_url(candidate):
                url = candidate
                break
        if not url:
            print(f"Error: Could not find valid URL for {args.github}@{version}")
            sys.exit(1)
    elif args.url:
        url = args.url
    else:
        print("Error: Either --url or --github is required")
        sys.exit(1)

    # Download and create source.json
    print(f"Downloading {url}...")
    try:
        source, archive_data = create_source_json(url, args.strip_prefix)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Create directories
    if is_new_module:
        module_path.mkdir(parents=True)

        if not args.homepage:
            print("Error: --homepage is required for new modules")
            sys.exit(1)

        maintainers = [{
            "email": args.maintainer_email or os.environ.get('GIT_EMAIL', 'unknown@example.com'),
            "github": args.maintainer_github or os.environ.get('GITHUB_USER', 'unknown'),
            "name": args.maintainer_name or args.maintainer_github or 'Unknown'
        }]

        metadata = create_metadata(module_name, args.homepage, maintainers)
        metadata['versions'] = [version]

        with open(module_path / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
            f.write('\n')
    else:
        update_metadata_versions(module_path / "metadata.json", version)

    # Create version directory
    version_path = module_path / version
    version_path.mkdir(parents=True)

    # Write source.json
    with open(version_path / "source.json", 'w') as f:
        json.dump(source, f, indent=2)
        f.write('\n')

    # Create presubmit.yml
    presubmit_content = create_presubmit_yaml(module_name)
    with open(version_path / "presubmit.yml", 'w') as f:
        f.write(presubmit_content)

    # Handle MODULE.bazel (mandatory)
    module_bazel_content = None

    # 1. Try provided file path
    if args.module_bazel:
        if Path(args.module_bazel).exists():
            module_bazel_content = Path(args.module_bazel).read_text()
            print(f"Loaded MODULE.bazel from {args.module_bazel}")
        else:
            print(f"Warning: MODULE.bazel file not found: {args.module_bazel}")

    # 2. Try provided URL
    if not module_bazel_content and args.module_bazel_url:
        module_bazel_content = download_module_bazel(args.module_bazel_url)
        if module_bazel_content:
            print(f"Downloaded MODULE.bazel from URL")
        else:
            print(f"Warning: Could not download MODULE.bazel from URL")

    # 3. Try extracting from archive
    if not module_bazel_content:
        module_bazel_content = get_module_bazel_from_archive(archive_data, source.get('strip_prefix'))
        if module_bazel_content:
            print(f"Extracted MODULE.bazel from archive")

    # 4. Create empty one as fallback
    if not module_bazel_content:
        module_bazel_content = create_empty_module_bazel(module_name, version)
        print(f"Created empty MODULE.bazel")

    # Write MODULE.bazel
    with open(version_path / "MODULE.bazel", 'w') as f:
        f.write(module_bazel_content)

    print(f"Created {module_name}@{version}")


if __name__ == '__main__':
    main()
