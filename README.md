# Bazel Custom Registry

A custom Bazel Central Registry (BCR) for hosting internal/private Bazel modules.

## Overview

This repository implements a Bazel Central Registry that can be hosted on GitHub Pages. It includes:

- Automated presubmit checks for all module submissions
- GitHub Actions workflows for validation and publishing
- Support for skip-check comments (e.g., `@bcr skip_check url-stability-check`)
- Automatic module diff generation between versions
- JSON Schema validation for metadata files

## Directory Structure

```
bcr-custom-registry/
├── .github/
│   ├── scripts/
│   │   ├── registry.py          # Core registry utilities
│   │   ├── detect_changes.py    # Detect changed modules in PRs
│   │   ├── presubmit.py         # Unified presubmit checks
│   │   ├── publish.py           # Registry publishing
│   │   └── generate_diff.py     # Module diff generation
│   └── workflows/
│       ├── presubmit.yml        # PR validation workflow
│       ├── publish.yml          # Publish to GitHub Pages
│       ├── generate_diff.yml    # Generate version diffs
│       └── skip_check.yml       # Handle skip check commands
├── modules/                     # Module definitions
│   └── example-lib/
│       ├── metadata.json        # Module metadata
│       └── 1.0.0/
│           ├── source.json      # Source archive info
│           ├── MODULE.bazel     # Module definition
│           └── presubmit.yml    # Presubmit configuration
├── bazel_registry.json          # Registry index (auto-generated)
├── metadata.schema.json         # JSON Schema for metadata
├── index.html                   # GitHub Pages homepage
└── README.md                    # This file
```

## Usage

### Adding a New Module

1. Create a directory under `modules/<module-name>/`
2. Create `metadata.json` with module information
3. Create version directory `modules/<module-name>/<version>/`
4. Add `source.json` with archive URL and integrity hash
5. Add `presubmit.yml` with build/test tasks
6. Optional: Add `MODULE.bazel` and/or patches

### Using This Registry

In your `MODULE.bazel`:

```starlark
bazel_dep(name = "my-private-module", version = "1.0.0")
```

With custom registry:

```bash
bazel build --registry=https://your-org.github.io/bcr-custom-registry //...
```

Or in `.bazelrc`:

```
build --registry=https://your-org.github.io/bcr-custom-registry
```

## Skip Checks

You can skip specific presubmit checks by commenting on the PR:

```
@bcr skip_check url-stability-check
```

Valid skip options:
- `url-stability-check` - Skip URL stability validation
- `module-dot-bazel-check` - Skip MODULE.bazel validation
- `presubmit-yaml-check` - Skip presubmit.yml validation
- `attestations-check` - Skip attestations validation
- `source-integrity-check` - Skip source download/integrity check

## GitHub Pages Setup

1. Go to Repository Settings → Pages
2. Source: Deploy from a branch
3. Branch: `gh-pages` (auto-created by publish workflow)
4. Your registry will be available at `https://<org>.github.io/<repo>/`

## Presubmit Checks

All checks run in a single GitHub Actions job to conserve resources:

1. **Format Validation** - JSON/YAML syntax
2. **Metadata Validation** - metadata.json structure and version consistency
3. **Source Integrity** - Download and verify archive checksums
4. **URL Stability** - Ensure release URLs are stable (not GitHub archives)
5. **MODULE.bazel** - Verify module name matches
6. **Presubmit Config** - Validate presubmit.yml structure
7. **Attestations** - Validate attestations.json if present

## License

Apache 2.0
