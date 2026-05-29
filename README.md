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
│   │   ├── generate_diff.py     # Module diff generation
│   │   └── create_module.py     # Quick module creation script
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

### Quick Create Module (Recommended)

Use the helper script to quickly create a new module or add a new version:

```bash
# Interactive mode (recommended)
python3 .github/scripts/create_module.py

# Non-interactive mode - new module
python3 .github/scripts/create_module.py \
  --name my_library \
  --version 1.0.0 \
  --github owner/repo \
  --homepage https://github.com/owner/repo \
  --maintainer-name "Your Name" \
  --maintainer-email "you@example.com"

# Non-interactive mode - add version to existing module
python3 .github/scripts/create_module.py \
  --name my_library \
  --version 1.1.0 \
  --url https://github.com/owner/repo/releases/download/v1.1.0/my_library-1.1.0.tar.gz
```

The script will:
- Auto-detect GitHub release URLs (supports multiple naming formats)
- Calculate source integrity hash automatically
- Detect `strip_prefix` from archive filename
- Generate `presubmit.yml` with default configuration
- Support adding MODULE.bazel and patches interactively
- Update `metadata.json` version list

### Adding a New Module (Manual)

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

---

## 中文文档 (Chinese Documentation)

### 快速开始

本仓库是一个自定义 Bazel Central Registry (BCR)，可以托管在 GitHub Pages 上。

### 快速创建模块

使用辅助脚本快速创建新模块或添加新版本：

```bash
# 交互模式（推荐）
python3 .github/scripts/create_module.py

# 非交互模式 - 创建新模块
python3 .github/scripts/create_module.py \
  --name my_library \
  --version 1.0.0 \
  --github owner/repo \
  --homepage https://github.com/owner/repo \
  --maintainer-name "Your Name" \
  --maintainer-email "you@example.com"

# 非交互模式 - 给现有模块添加新版本
python3 .github/scripts/create_module.py \
  --name my_library \
  --version 1.1.0 \
  --url https://github.com/owner/repo/releases/download/v1.1.0/my_library-1.1.0.tar.gz
```

脚本功能：
- 自动检测 GitHub Release URL（支持多种命名格式）
- 自动计算源码完整性哈希
- 自动检测 `strip_prefix`
- 生成默认配置的 `presubmit.yml`
- 支持交互式添加 MODULE.bazel 和补丁
- 自动更新 `metadata.json` 版本列表

### 手动添加模块

1. 在 `modules/<模块名>/` 下创建目录
2. 创建 `metadata.json` 包含模块信息
3. 创建版本目录 `modules/<模块名>/<版本>/`
4. 添加 `source.json` 包含归档 URL 和完整性哈希
5. 添加 `presubmit.yml` 包含构建/测试任务
6. 可选：添加 `MODULE.bazel` 和/或补丁文件

### 使用本注册表

在 `MODULE.bazel` 中：

```starlark
bazel_dep(name = "my-private-module", version = "1.0.0")
```

使用自定义注册表：

```bash
bazel build --registry=https://your-org.github.io/bcr-custom-registry //...
```

或在 `.bazelrc` 中：

```
build --registry=https://your-org.github.io/bcr-custom-registry
```

### 跳过检查

可以在 PR 评论中跳过特定检查：

```
@bcr skip_check url-stability-check
```

支持的跳过选项：
- `url-stability-check` - 跳过 URL 稳定性验证
- `module-dot-bazel-check` - 跳过 MODULE.bazel 验证
- `presubmit-yaml-check` - 跳过 presubmit.yml 验证
- `attestations-check` - 跳过 attestations 验证
- `source-integrity-check` - 跳过源码下载/完整性检查

### GitHub Pages 设置

1. 进入仓库设置 → Pages
2. 源：从分支部署
3. 分支：`gh-pages`（由发布工作流自动创建）
4. 注册表将可在 `https://<组织>.github.io/<仓库>/` 访问

### Presubmit 检查

所有检查在一个 GitHub Actions 任务中运行，节省资源：

1. **格式验证** - JSON/YAML 语法
2. **元数据验证** - metadata.json 结构和版本一致性
3. **源码完整性** - 下载并验证归档校验和
4. **URL 稳定性** - 确保发布 URL 稳定（非 GitHub 归档）
5. **MODULE.bazel** - 验证模块名匹配
6. **Presubmit 配置** - 验证 presubmit.yml 结构
7. **Attestations** - 验证 attestations.json（如果存在）
