#!/usr/bin/env python3
"""
Generate bazel_registry.json and GitHub Pages index.
"""

import json
import os
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


def generate_modules_html(registry: RegistryClient, repo_name: str = "your-org/bcr") -> str:
    """Generate HTML for all modules."""
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

    if not modules:
        return '''<div class="empty-state">
            <div class="empty-state-icon">📦</div>
            <h3>No modules available yet</h3>
            <p>See README.md for instructions on adding modules.</p>
        </div>'''

    html = '<div class="modules-grid">\n'

    for module in modules:
        module_name = module['name']
        versions = module['versions']

        # Homepage HTML
        homepage_html = ''
        if module['homepage']:
            homepage_html = f'''<div class="module-homepage">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                    <a href="{module['homepage']}" target="_blank" rel="noopener">{module['homepage']}</a>
                </div>'''

        # Source code link (link to modules/ folder in GitHub repo)
        source_link = f"https://github.com/{repo_name}/tree/main/modules/{module_name}"

        # Generate versions HTML with expansion
        versions_html = generate_versions_html(module_name, versions)

        # Deprecated badge
        deprecated_html = ''
        if module['deprecated']:
            deprecated_html = f'''<div class="deprecated-badge">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="12" height="12"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                    Deprecated: {module['deprecated']}
                </div>'''

        # Quick dep code (use latest version - last in array)
        latest_version = versions[-1] if versions else '1.0.0'
        quick_dep = f"bazel_dep(name = '{module_name}', version = '{latest_version}')"

        # Build data attributes for search
        data_name = module_name.lower()
        data_versions = ' '.join(versions).lower()
        data_homepage = module['homepage'].lower() if module['homepage'] else ''

        html += f'''<div class="module-card" data-name="{data_name}" data-versions="{data_versions}" data-homepage="{data_homepage}">
                <div class="module-header">
                    <div class="module-title">
                        <div class="module-icon">
                            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path></svg>
                        </div>
                        <div class="module-name">{module_name}</div>
                    </div>
                    <div class="module-actions">
                        <a href="{source_link}" target="_blank" rel="noopener" class="action-btn">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"></path></svg>
                            Source
                        </a>
                    </div>
                </div>
                {homepage_html}
                <div class="versions-section">
                    {versions_html}
                </div>
                <div class="quick-dep">
                    <code class="quick-dep-code">{quick_dep}</code>
                    <button class="copy-btn" data-copy="{quick_dep}">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                        Copy
                    </button>
                </div>
                {deprecated_html}
            </div>\n'''

    html += '</div>'
    return html


def generate_versions_html(module_name: str, versions: List[str]) -> str:
    """Generate versions HTML with expansion (show first 5, hide rest)."""
    if not versions:
        return '<div class="versions"></div>'

    # Show first 5 versions, hide the rest
    visible_count = 5
    visible_versions = versions[:visible_count]
    hidden_versions = versions[visible_count:]

    def make_version_tag(version: str) -> str:
        dep_code = f"bazel_dep(name = '{module_name}', version = '{version}')"
        return f'<span class="version" data-dep="{dep_code}">{version}</span>'

    visible_html = ''.join(make_version_tag(v) for v in visible_versions)

    if hidden_versions:
        hidden_html = ''.join(make_version_tag(v) for v in hidden_versions)
        more_count = len(hidden_versions)
        return f'''<div class="versions">
                    {visible_html}
                    <span class="version version-more">+{more_count} more</span>
                </div>
                <div class="versions versions-collapsed">
                    {hidden_html}
                </div>'''
    else:
        return f'<div class="versions">{visible_html}</div>'


def generate_index_html(registry: RegistryClient, repo_name: str = "your-org/bcr") -> str:
    """Generate the GitHub Pages index HTML from template."""
    # Get template path
    script_dir = Path(__file__).parent
    template_path = script_dir / "index.html.temp"

    # Fallback to inline template if file not found
    if not template_path.exists():
        print(f"Warning: Template file not found at {template_path}, using inline template")
        return generate_index_html_inline(registry, repo_name)

    # Read template
    template = template_path.read_text()

    # Calculate values
    modules = []
    for module_name in sorted(registry.get_all_modules()):
        metadata = registry.get_metadata(module_name)
        if metadata is None:
            continue
        modules.append({
            'name': module_name,
            'versions': metadata.get('versions', []),
        })

    module_count = len(modules)
    version_count = sum(len(m['versions']) for m in modules)

    # Generate registry URL
    repo_owner, repo = repo_name.split('/') if '/' in repo_name else ('your-org', 'bcr')
    registry_url = f"https://{repo_owner}.github.io/{repo}"

    # Generate modules HTML
    modules_html = generate_modules_html(registry, repo_name)

    # Replace placeholders
    html = template
    html = html.replace('{{REPO_NAME}}', repo_name)
    html = html.replace('{{REGISTRY_URL}}', registry_url)
    html = html.replace('{{MODULE_COUNT}}', str(module_count))
    html = html.replace('{{VERSION_COUNT}}', str(version_count))
    html = html.replace('{{MODULES_HTML}}', modules_html)

    return html


def generate_index_html_inline(registry: RegistryClient, repo_name: str = "your-org/bcr") -> str:
    """Fallback inline HTML generation if template file is missing."""
    # This is a simplified version for fallback purposes
    modules_html = generate_modules_html(registry, repo_name)

    modules = []
    for module_name in sorted(registry.get_all_modules()):
        metadata = registry.get_metadata(module_name)
        if metadata is None:
            continue
        modules.append({'versions': metadata.get('versions', [])})

    module_count = len(modules)
    version_count = sum(len(m['versions']) for m in modules)

    repo_owner, repo = repo_name.split('/') if '/' in repo_name else ('your-org', 'bcr')
    registry_url = f"https://{repo_owner}.github.io/{repo}"

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{repo_name} - Bazel Registry</title>
    <style>
        body {{ font-family: sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .module {{ border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 8px; }}
        .version {{ display: inline-block; background: #e3f2fd; padding: 2px 8px; margin: 2px; border-radius: 4px; }}
    </style>
</head>
<body>
    <h1>{repo_name}</h1>
    <p>Registry URL: {registry_url}</p>
    <p>Modules: {module_count} | Versions: {version_count}</p>
    {modules_html}
</body>
</html>'''


def main():
    registry = RegistryClient('.')

    # Get repository name from environment or use default
    repo_name = os.environ.get('GITHUB_REPOSITORY', 'your-org/bcr')

    # Generate registry index
    index = generate_registry_index(registry)
    with open('bazel_registry.json', 'w') as f:
        json.dump(index, f, indent=2)

    print(f"Generated bazel_registry.json with {len(index['modules'])} modules")

    # Generate index.html from template
    html = generate_index_html(registry, repo_name)
    with open('index.html', 'w') as f:
        f.write(html)

    print(f"Generated index.html for {repo_name}")


if __name__ == '__main__':
    main()
