#!/usr/bin/env python3
"""
Fork 检测脚本 - 检测 ruleset 仓库与 BCR registry 的关系。
"""

import argparse
import json
import os
import sys
import urllib.request
import ssl
from typing import Optional, Tuple


def parse_args():
    parser = argparse.ArgumentParser(description='检测 ruleset 仓库与 BCR registry 的关系')
    parser.add_argument('--repository', required=True, help='Ruleset 仓库 (owner/repo)')
    parser.add_argument('--registry', required=True, help='BCR registry 仓库 (owner/repo)')
    parser.add_argument('--registry-fork', default='', help='BCR registry 的 fork (owner/repo)')
    return parser.parse_args()


def get_github_api(url: str, token: str) -> Optional[dict]:
    """调用 GitHub API 获取数据。"""
    ssl_context = ssl.create_default_context()
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'BCR-ForkDetector/1.0'
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"API 调用失败: {e}")
        return None


def detect_strategy(repository: str, registry: str, registry_fork: str, token: str) -> Tuple[str, str]:
    """检测发布策略。返回: (strategy, token_type)"""
    if repository == registry:
        return "SAME_REGISTRY", "GITHUB_TOKEN"

    repo_url = f"https://api.github.com/repos/{repository}"
    repo_data = get_github_api(repo_url, token)

    if repo_data:
        parent = repo_data.get('parent', {})
        if parent.get('full_name') == registry:
            return "SAME_REGISTRY_FORK", "GITHUB_TOKEN"

    if registry_fork:
        return "EXTERNAL_FORK", "PAT"

    return "NEEDS_FORK_CONFIG", "PAT"


def main():
    args = parse_args()
    token = os.environ.get('GITHUB_TOKEN', '')

    if not token:
        print("错误: 未设置 GITHUB_TOKEN 环境变量")
        sys.exit(1)

    strategy, token_type = detect_strategy(
        args.repository, args.registry, args.registry_fork, token
    )

    target_registry = args.registry_fork or args.registry

    print(f"strategy={strategy}")
    print(f"token_type={token_type}")
    print(f"registry_fork={target_registry}")

    github_output = os.environ.get('GITHUB_OUTPUT', '')
    if github_output:
        with open(github_output, 'a') as f:
            f.write(f"strategy={strategy}\n")
            f.write(f"token_type={token_type}\n")
            f.write(f"registry_fork={target_registry}\n")

    if strategy == 'NEEDS_FORK_CONFIG':
        print("\n错误: 请提供 registry_fork 参数")
        sys.exit(1)


if __name__ == '__main__':
    main()