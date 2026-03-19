#!/usr/bin/env python3
"""
Generate bazel_registry.json and GitHub Pages index.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from registry import RegistryClient


def generate_registry_index(registry: RegistryClient) -> Dict[str, Any]:
    """Generate the bazel_registry.json index."""
    index = {
        'mirrors': [],
        'modules': {}
    }

    for module_name in registry.get_all_modules():
        metadata = registry.get_metadata(module_name)
        if metadata is None:
            continue

        index['modules'][module_name] = {
            'versions': metadata.get('versions', []),
            'yanked_versions': metadata.get('yanked_versions', {}),
            'deprecated': metadata.get('deprecated', None)
        }

    return index


def generate_index_html(registry: RegistryClient) -> str:
    """Generate the GitHub Pages index HTML."""
    modules = []
    for module_name in sorted(registry.get_all_modules()):
        metadata = registry.get_metadata(module_name)
        if metadata is None:
            continue

        versions = metadata.get('versions', [])
        homepage = metadata.get('homepage', '')
        deprecated = metadata.get('deprecated', '')

        modules.append({
            'name': module_name,
            'versions': versions,
            'homepage': homepage,
            'deprecated': deprecated
        })

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bazel Custom Registry</title>
    <style>
        * {{
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{
            color: #333;
            border-bottom: 2px solid #0078d4;
            padding-bottom: 10px;
        }}
        .subtitle {{
            color: #666;
            margin-bottom: 30px;
        }}
        .module {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .module-name {{
            font-size: 1.4em;
            font-weight: bold;
            color: #0078d4;
            margin-bottom: 5px;
        }}
        .module-meta {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 10px;
        }}
        .versions {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .version {{
            background: #e3f2fd;
            color: #1565c0;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 0.9em;
            font-family: 'SF Mono', Monaco, monospace;
        }}
        .version.yanked {{
            background: #ffebee;
            color: #c62828;
        }}
        .deprecated {{
            background: #fff3e0;
            color: #e65100;
            padding: 8px 12px;
            border-radius: 4px;
            margin-top: 10px;
        }}
        .stats {{
            background: #f0f0f0;
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            display: flex;
            gap: 30px;
        }}
        .stat {{
            display: flex;
            flex-direction: column;
        }}
        .stat-value {{
            font-size: 1.5em;
            font-weight: bold;
            color: #0078d4;
        }}
        .stat-label {{
            color: #666;
            font-size: 0.9em;
        }}
        a {{
            color: #0078d4;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .usage {{
            background: #263238;
            color: #aed581;
            padding: 15px 20px;
            border-radius: 8px;
            font-family: 'SF Mono', Monaco, monospace;
            margin-bottom: 30px;
            overflow-x: auto;
        }}
        .usage-title {{
            color: #fff;
            margin-bottom: 10px;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <h1>Bazel Custom Registry</h1>
    <p class="subtitle">A custom Bazel Central Registry for internal/private modules</p>

    <div class="stats">
        <div class="stat">
            <span class="stat-value">{len(modules)}</span>
            <span class="stat-label">Modules</span>
        </div>
        <div class="stat">
            <span class="stat-value">{sum(len(m['versions']) for m in modules)}</span>
            <span class="stat-label">Versions</span>
        </div>
    </div>

    <div class="usage">
        <div class="usage-title">Usage in your MODULE.bazel:</div>
bazel_dep(name = "module_name", version = "1.0.0")<br><br>
# or with custom registry:<br>
bazel build --registry=https://your-org.github.io/bcr-custom-registry //...
    </div>

    <h2>Available Modules</h2>
"""

    for module in modules:
        homepage_link = f'<a href="{module["homepage"]}" target="_blank">{module["homepage"]}</a>' if module['homepage'] else 'No homepage'
        deprecated_html = f'<div class="deprecated">Deprecated: {module["deprecated"]}</div>' if module['deprecated'] else ''

        versions_html = ''.join(
            f'<span class="version">{v}</span>'
            for v in module['versions']
        )

        html += f"""
    <div class="module">
        <div class="module-name">{module['name']}</div>
        <div class="module-meta">{homepage_link}</div>
        <div class="versions">{versions_html}</div>
        {deprecated_html}
    </div>
"""

    html += """
</body>
</html>
"""

    return html


def main():
    registry = RegistryClient('.')

    # Generate registry index
    index = generate_registry_index(registry)
    with open('bazel_registry.json', 'w') as f:
        json.dump(index, f, indent=2)

    print(f"Generated bazel_registry.json with {len(index['modules'])} modules")

    # Generate index.html
    html = generate_index_html(registry)
    with open('index.html', 'w') as f:
        f.write(html)

    print(f"Generated index.html")


if __name__ == '__main__':
    main()
