# Publish to BCR

可复用的 GitHub Actions workflow，用于自动发布模块到 Bazel Central Registry。

## 使用方法

在 ruleset 仓库创建 workflow：

```yaml
# .github/workflows/publish.yml
name: Publish to BCR

on:
  release:
    types: [published]

jobs:
  publish:
    uses: owner/bcr/.github/workflows/publish_to_bcr.yml@publish-to-bcr
    with:
      tag_name: ${{ github.event.release.tag_name }}
      module_name: "your_module"
```

## 输入参数

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `tag_name` | 是 | - | Release tag |
| `module_name` | 是 | - | 模块名 |
| `registry` | 否 | 调用者仓库 | 目标 BCR |
| `registry_fork` | 否 | - | BCR fork (跨仓库 PR) |
| `tag_prefix` | 否 | `v` | Tag 前缀 |
| `templates_dir` | 否 | `.bcr` | 模板目录 |
| `draft` | 否 | `true` | Draft PR |
| `source_url` | 否 | 自动生成 | Source URL |
| `strip_prefix` | 否 | 自动检测 | Strip prefix |

## 模板结构

在 ruleset 仓库创建 `.bcr/` 目录：

```
.bcr/
├── metadata.template.json  # 可选
├── source.template.json    # 可选
├── presubmit.yml           # 可选
├── MODULE.bazel            # 可选
├── patches/                # 可选
└── overlay/                # 可选
```

占位符：`{OWNER}`, `{REPO}`, `{VERSION}`, `{TAG}`, `{MODULE}`

## Fork 检测

自动识别仓库关系：
- **SAME_REGISTRY**: 同仓库操作
- **SAME_REGISTRY_FORK**: ruleset 是 BCR 的 fork
- **EXTERNAL_FORK**: 使用 registry_fork 参数

## 分支命名

创建的分支：`{module_name}.{version}`

示例：`sdl3.3.4.2`