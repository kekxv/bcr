#!/usr/bin/env python3
"""Core registry utilities for BCR operations."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import re


@dataclass
class Version:
    """Semantic version representation for comparison."""
    major: int
    minor: int = 0
    patch: int = 0
    prerelease: Optional[str] = None
    bcr_patch: int = 0  # BCR-specific patch number (e.g., .bcr.1)

    @classmethod
    def parse(cls, version_str: str) -> "Version":
        """Parse a version string into a Version object."""
        # Remove leading 'v' if present
        version_str = version_str.lstrip('v')

        # Check for BCR patch suffix (e.g., .bcr.1)
        bcr_match = re.match(r'^(.+)\.bcr\.(\d+)$', version_str)
        bcr_patch = 0
        if bcr_match:
            version_str = bcr_match.group(1)
            bcr_patch = int(bcr_match.group(2))

        # Parse semver components
        match = re.match(
            r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-(.+))?$',
            version_str
        )
        if not match:
            raise ValueError(f"Invalid version string: {version_str}")

        major = int(match.group(1))
        minor = int(match.group(2)) if match.group(2) else 0
        patch = int(match.group(3)) if match.group(3) else 0
        prerelease = match.group(4)

        return cls(major, minor, patch, prerelease, bcr_patch)

    def __str__(self) -> str:
        result = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            result += f"-{self.prerelease}"
        if self.bcr_patch > 0:
            result += f".bcr.{self.bcr_patch}"
        return result

    def __lt__(self, other: "Version") -> bool:
        # First compare major.minor.patch
        if (self.major, self.minor, self.patch) != (other.major, other.minor, other.patch):
            return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

        # Then compare prerelease (prerelease < release)
        if self.prerelease is None and other.prerelease is not None:
            return False
        if self.prerelease is not None and other.prerelease is None:
            return True
        if self.prerelease != other.prerelease:
            return (self.prerelease or "") < (other.prerelease or "")

        # Finally compare bcr_patch (higher bcr_patch = newer)
        # e.g., 0.11.0.bcr.1 > 0.11.0
        return self.bcr_patch < other.bcr_patch

    def __le__(self, other: "Version") -> bool:
        return self == other or self < other

    def __gt__(self, other: "Version") -> bool:
        return not self <= other

    def __ge__(self, other: "Version") -> bool:
        return not self < other

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return False
        return (self.major, self.minor, self.patch, self.prerelease, self.bcr_patch) == \
               (other.major, other.minor, other.patch, other.prerelease, other.bcr_patch)


class RegistryClient:
    """Client for interacting with the Bazel registry."""

    def __init__(self, registry_path: str = "."):
        self.registry_path = Path(registry_path)
        self.modules_path = self.registry_path / "modules"

    def get_all_modules(self) -> List[str]:
        """Get a list of all module names in the registry."""
        if not self.modules_path.exists():
            return []

        modules = []
        for item in self.modules_path.iterdir():
            if item.is_dir():
                metadata_file = item / "metadata.json"
                if metadata_file.exists():
                    modules.append(item.name)
        return sorted(modules)

    def get_metadata(self, module_name: str) -> Optional[Dict[str, Any]]:
        """Get the metadata for a module."""
        metadata_path = self.modules_path / module_name / "metadata.json"
        if not metadata_path.exists():
            return None

        with open(metadata_path, 'r') as f:
            return json.load(f)

    def get_source(self, module_name: str, version: str) -> Optional[Dict[str, Any]]:
        """Get the source information for a specific module version."""
        source_path = self.modules_path / module_name / version / "source.json"
        if not source_path.exists():
            return None

        with open(source_path, 'r') as f:
            return json.load(f)

    def get_presubmit(self, module_name: str, version: str) -> Optional[Dict[str, Any]]:
        """Get the presubmit configuration for a specific module version."""
        presubmit_path = self.modules_path / module_name / version / "presubmit.yml"
        if not presubmit_path.exists():
            # Try module-level presubmit
            presubmit_path = self.modules_path / module_name / "presubmit.yml"
            if not presubmit_path.exists():
                return None

        import yaml
        with open(presubmit_path, 'r') as f:
            return yaml.safe_load(f)

    def get_module_dot_bazel(self, module_name: str, version: str) -> Optional[str]:
        """Get the MODULE.bazel content for a specific module version."""
        module_path = self.modules_path / module_name / version / "MODULE.bazel"
        if not module_path.exists():
            return None

        with open(module_path, 'r') as f:
            return f.read()

    def contains(self, module_name: str, version: Optional[str] = None) -> bool:
        """Check if a module or specific version exists."""
        module_path = self.modules_path / module_name
        if not module_path.exists():
            return False

        if version is None:
            return True

        version_path = module_path / version
        return version_path.exists() and version_path.is_dir()

    def get_versions(self, module_name: str) -> List[str]:
        """Get all versions of a module, sorted."""
        metadata = self.get_metadata(module_name)
        if metadata is None:
            return []
        return metadata.get("versions", [])

    def get_previous_version(self, module_name: str, version: str) -> Optional[str]:
        """Get the version immediately before the given version."""
        versions = self.get_versions(module_name)
        if version not in versions:
            return None

        idx = versions.index(version)
        if idx == 0:
            return None
        return versions[idx - 1]

    def update_versions(self, module_name: str) -> None:
        """Update the versions list in metadata.json based on directory structure."""
        module_path = self.modules_path / module_name
        if not module_path.exists():
            return

        # Find all version directories
        versions = []
        for item in module_path.iterdir():
            if item.is_dir() and item.name != ".git":
                # Check if it has a source.json (valid version)
                if (item / "source.json").exists():
                    versions.append(item.name)

        # Sort versions semantically (oldest first, newest last)
        try:
            versions.sort(key=lambda v: Version.parse(v))
        except ValueError:
            versions.sort()

        # Update metadata
        metadata_path = module_path / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
        else:
            metadata = {}

        metadata["versions"] = versions

        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

    def get_attestations(self, module_name: str, version: str) -> Optional[Dict[str, Any]]:
        """Get attestations for a specific module version."""
        attestations_path = self.modules_path / module_name / version / "attestations.json"
        if not attestations_path.exists():
            return None

        with open(attestations_path, 'r') as f:
            return json.load(f)

    def list_patches(self, module_name: str, version: str) -> List[Path]:
        """List all patch files for a module version."""
        patches_dir = self.modules_path / module_name / version / "patches"
        if not patches_dir.exists():
            return []
        return sorted(patches_dir.glob("*.patch"))
