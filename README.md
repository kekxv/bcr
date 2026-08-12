# Publish to BCR

可复用的 GitHub Actions workflow，用于自动发布模块到 Bazel Central Registry。

## 快速开始

在 ruleset 仓库运行初始化脚本：

```bash
# 下载并运行
curl -sSL https://raw.githubusercontent.com/kekxv/bcr/publish-to-bcr/.github/scripts/init_ruleset.py | \
  python3 - --module-name "my_module" --bcr "kekxv/bcr"
```

或手动下载：

```bash
# 克隆后运行
python3 .github/scripts/init_ruleset.py \
  --module-name "my_module" \
  --bcr "kekxv/bcr" \
  --bcr-fork "your_username/bcr" \
  --github-user "your_username"
```

脚本将创建：
- `.github/workflows/publish_to_bcr.yml` - 发布 workflow
- `.bcr/` - 模板目录
  - `metadata.template.json`
  - `source.template.json`
  - `presubmit.yml`
  - `MODULE.bazel`

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
    uses: kekxv/bcr/.github/workflows/publish_to_bcr.yml@publish-to-bcr
    with:
      tag_name: ${{ github.event.release.tag_name }}
      module_name: "your_module"
      registry: "kekxv/bcr"
      registry_fork: "your_username/bcr"
    secrets:
      publish_token: ${{ secrets.BCR_PUBLISH_TOKEN }}
```

## 输入参数

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `tag_name` | 是 | - | Release tag |
| `module_name` | 是 | - | 模块名 |
| `registry` | 否 | `kekxv/bcr` | 目标 BCR |
| `registry_fork` | 否 | - | BCR fork (跨仓库 PR) |
| `tag_prefix` | 否 | `v` | Tag 前缀 |
| `templates_dir` | 否 | `.bcr` | 模板目录 |
| `draft` | 否 | `false` | Draft PR |
| `source_url` | 否 | 自动生成 | Source URL |
| `strip_prefix` | 否 | 自动检测 | Strip prefix |

## 模板结构

在 ruleset 仓库创建 `.bcr/` 目录：

```
.bcr/
├── metadata.template.json  # 新模块必需，已有模块可选
├── source.template.json    # 可选
├── presubmit.yml           # 可选
├── MODULE.bazel            # 可选；缺省时使用仓库根 MODULE.bazel
├── patches/                # 可选
└── overlay/                # 可选
```

占位符支持单、双花括号两种形式，效果相同：

- `{OWNER}` 或 `{{OWNER}}`
- `{REPO}` 或 `{{REPO}}`
- `{VERSION}` 或 `{{VERSION}}`
- `{TAG}` 或 `{{TAG}}`
- `{MODULE}` 或 `{{MODULE}}`

JSON 模板中的嵌套对象、数组、键和值都会递归处理。

## Fork 检测

自动识别仓库关系：
- **SAME_REGISTRY**: 同仓库操作
- **SAME_REGISTRY_FORK**: ruleset 是 BCR 的 fork
- **EXTERNAL_FORK**: 使用 registry_fork 参数

跨仓库创建 PR（包括 `SAME_REGISTRY_FORK`）需要设置
`BCR_PUBLISH_TOKEN`，因为仓库级 `GITHUB_TOKEN` 无法写入上游 registry。

## 分支命名

创建的分支：`{module_name}.{version}`

示例：`sdl3.3.4.2`
