#!/usr/bin/env python3
"""
Ruleset 初始化脚本 - 快速创建 workflow 和 .bcr 文件夹。

用法：
  python init_ruleset.py --module-name "my_module" --bcr "owner/bcr"

将创建：
  - .github/workflows/publish_to_bcr.yml
  - .bcr/
    ├── metadata.template.json
    ├── source.template.json
    ├── presubmit.yml
    └── MODULE.bazel
"""

import argparse
import json
import os
import sys
from pathlib import Path


WORKFLOW_TEMPLATE = '''name: Publish to BCR

on:
  release:
    types: [published]

jobs:
  publish:
    uses: {bcr}/.github/workflows/publish_to_bcr.yml@publish-to-bcr
    with:
      tag_name: ${{{{ github.event.release.tag_name }}}}
      module_name: "{module_name}"
    secrets:
      publish_token: ${{{{ secrets.BCR_PUBLISH_TOKEN }}}}
'''

METADATA_TEMPLATE = '''{{
  "homepage": "https://github.com/{owner}/{repo}",
  "maintainers": [
    {{
      "email": "your@email.com",
      "github": "{github_user}"
    }}
  ],
  "repository": ["github:{owner}/{repo}"],
  "versions": [],
  "yanked_versions": {{}}
}}
'''

SOURCE_TEMPLATE = '''{{
  "url": "https://github.com/{owner}/{repo}/releases/download/{{{{TAG}}}}/{repo}-{{{{VERSION}}}}.tar.gz",
  "strip_prefix": "{repo}-{{{{VERSION}}}}"
}}
'''

PRESUBMIT_TEMPLATE = '''matrix:
  platform:
    - ubuntu2404
    - macos
    - windows
  bazel:
    - 7.x
    - 8.x

tasks:
  verify_targets:
    name: Verify build targets
    platform: ${{{{ platform }}}}
    bazel: ${{{{ bazel }}}}
    build_targets:
      - '@{module_name}//...'
'''

MODULE_BAZEL_TEMPLATE = '''module(
    name = "{module_name}",
    version = "{{{{VERSION}}}}",
)
'''


def parse_args():
    parser = argparse.ArgumentParser(description='初始化 ruleset 仓库的 BCR 发布配置')
    parser.add_argument('--module-name', required=True, help='模块名')
    parser.add_argument('--bcr', required=True, help='BCR 仓库 (owner/repo)')
    parser.add_argument('--owner', default='', help='仓库 owner（默认从 git 获取）')
    parser.add_argument('--repo', default='', help='仓库名（默认从 git 获取）')
    parser.add_argument('--github-user', default='', help='GitHub 用户名')
    parser.add_argument('--force', action='store_true', help='覆盖已存在的文件')
    parser.add_argument('--dry-run', action='store_true', help='只显示将创建的文件')
    return parser.parse_args()


def get_git_info():
    """从 git 获取仓库信息。"""
    import subprocess
    try:
        result = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # 解析 git URL
            if url.startswith('git@github.com:'):
                url = url.replace('git@github.com:', '')
            elif url.startswith('https://github.com/'):
                url = url.replace('https://github.com/', '')
            if url.endswith('.git'):
                url = url[:-4]
            parts = url.split('/')
            if len(parts) >= 2:
                return parts[0], parts[1]
    except:
        pass
    return '', ''


def main():
    args = parse_args()

    # 获取仓库信息
    owner = args.owner
    repo = args.repo
    if not owner or not repo:
        git_owner, git_repo = get_git_info()
        owner = owner or git_owner
        repo = repo or git_repo

    if not owner or not repo:
        print("错误: 无法确定仓库信息，请使用 --owner 和 --repo 参数")
        sys.exit(1)

    github_user = args.github_user or owner

    print(f"模块名: {args.module_name}")
    print(f"仓库: {owner}/{repo}")
    print(f"BCR: {args.bcr}")
    print(f"GitHub 用户: {github_user}")
    print()

    # 创建目录
    workflow_dir = Path(".github/workflows")
    bcr_dir = Path(".bcr")

    files = {
        workflow_dir / "publish_to_bcr.yml": WORKFLOW_TEMPLATE.format(
            bcr=args.bcr, module_name=args.module_name
        ),
        bcr_dir / "metadata.template.json": METADATA_TEMPLATE.format(
            owner=owner, repo=repo, github_user=github_user
        ),
        bcr_dir / "source.template.json": SOURCE_TEMPLATE.format(
            owner=owner, repo=repo
        ),
        bcr_dir / "presubmit.yml": PRESUBMIT_TEMPLATE.format(
            module_name=args.module_name
        ),
        bcr_dir / "MODULE.bazel": MODULE_BAZEL_TEMPLATE.format(
            module_name=args.module_name
        ),
    }

    if args.dry_run:
        print("将创建以下文件：")
        for path in files:
            print(f"  {path}")
        return

    # 创建文件
    for path, content in files.items():
        if path.exists() and not args.force:
            print(f"跳过（已存在）: {path}")
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"创建: {path}")

    print()
    print("=" * 50)
    print("初始化完成！")
    print()
    print("下一步：")
    print("1. 编辑 .bcr/metadata.template.json 填写正确的维护者信息")
    print("2. 编辑 .bcr/MODULE.bazel 添加依赖")
    print("3. 如需跨仓库 PR，设置 secret: BCR_PUBLISH_TOKEN")
    print("4. 创建 release 测试发布流程")
    print()
    print("注意：如果模块不在仓库根目录，需要配置 moduleRoots")


if __name__ == '__main__':
    main()