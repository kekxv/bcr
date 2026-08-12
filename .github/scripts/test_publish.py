#!/usr/bin/env python3

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import fork_detector
import init_ruleset
import publish_action
import template_processor


class TemplateTests(unittest.TestCase):
    def test_single_and_double_braces_are_equivalent(self):
        context = {"TAG": "v1.2.3", "VERSION": "1.2.3"}
        self.assertEqual(
            template_processor.substitute_placeholders("{TAG} {{TAG}}", context),
            "v1.2.3 v1.2.3",
        )

    def test_json_values_are_rendered_recursively(self):
        value = {
            "url": "https://example.test/{{TAG}}",
            "nested": ["{VERSION}", {"{{TAG}}": "{TAG}"}],
        }
        self.assertEqual(
            template_processor.substitute_value(value, {"TAG": "v2", "VERSION": "2"}),
            {
                "url": "https://example.test/v2",
                "nested": ["2", {"v2": "v2"}],
            },
        )

    def test_template_tree_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "overlay").mkdir()
            (root / "overlay" / "leak").symlink_to("/etc/passwd")
            with self.assertRaises(ValueError):
                template_processor.load_templates(root)


class VersionTests(unittest.TestCase):
    def test_historical_bcr_versions_do_not_force_lexical_sort(self):
        versions = ["2.9.0", "2.10.0", "2.5.0.bcr.beta.1"]
        self.assertEqual(
            publish_action.sort_versions(versions),
            ["2.5.0.bcr.beta.1", "2.9.0", "2.10.0"],
        )

    def test_release_precedes_bcr_revision(self):
        self.assertEqual(
            publish_action.sort_versions(["1.0.0.bcr.2", "1.0.0", "1.0.0-beta"]),
            ["1.0.0-beta", "1.0.0", "1.0.0.bcr.2"],
        )


class PublisherTests(unittest.TestCase):
    def test_end_to_end_new_module_uses_metadata_and_both_template_styles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ruleset = root / "ruleset"
            registry = root / "registry"
            templates = ruleset / ".bcr"
            templates.mkdir(parents=True)
            (registry / "modules").mkdir(parents=True)
            (templates / "metadata.template.json").write_text(json.dumps({
                "homepage": "https://github.com/{OWNER}/{REPO}",
                "maintainers": [{"github": "{{OWNER}}", "email": "dev@example.test"}],
                "repository": ["github:{OWNER}/{REPO}"],
                "versions": [],
            }))
            (templates / "source.template.json").write_text(json.dumps({
                "url": "https://example.test/releases/{{TAG}}/source.tar.gz",
                "strip_prefix": "{REPO}-{{VERSION}}",
                "extra": {"tag": "{TAG}"},
            }))
            (templates / "MODULE.bazel").write_text(
                'module(name = "demo", version = "{{VERSION}}")\n'
            )

            argv = [
                "publish_action.py", "--tag-name", "v1.2.3", "--module-name", "demo",
                "--registry-path", str(registry), "--ruleset-path", str(ruleset),
            ]
            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "acme/demo"}, clear=False), \
                 mock.patch.object(publish_action, "download_archive", return_value="sha256-test"):
                self.assertEqual(publish_action.main(), 0)

            module_root = registry / "modules" / "demo"
            metadata = json.loads((module_root / "metadata.json").read_text())
            source = json.loads((module_root / "1.2.3" / "source.json").read_text())
            module_bazel = (module_root / "1.2.3" / "MODULE.bazel").read_text()
            self.assertEqual(metadata["homepage"], "https://github.com/acme/demo")
            self.assertEqual(metadata["versions"], ["1.2.3"])
            self.assertEqual(source["strip_prefix"], "demo-1.2.3")
            self.assertEqual(source["extra"]["tag"], "v1.2.3")
            self.assertIn('version = "1.2.3"', module_bazel)

    def test_new_module_requires_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            with self.assertRaisesRegex(ValueError, "metadata.template.json"):
                publish_action.build_metadata(path, None, "1.0.0")

    def test_existing_metadata_is_preserved_and_extended(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            path.write_text(json.dumps({
                "homepage": "https://existing.example",
                "maintainers": [{"github": "owner", "email": "dev@example.test"}],
                "repository": ["github:owner/demo"],
                "versions": ["2.9.0", "2.5.0.bcr.beta.1"],
                "yanked_versions": {},
            }))
            metadata = publish_action.build_metadata(
                path, {"homepage": "https://must-not-overwrite.example"}, "2.10.0"
            )
            self.assertEqual(metadata["homepage"], "https://existing.example")
            self.assertEqual(
                metadata["versions"],
                ["2.5.0.bcr.beta.1", "2.9.0", "2.10.0"],
            )

    def test_paths_and_private_downloads_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                publish_action.resolve_within(Path(directory), "../secret")
        for url in ("file:///etc/passwd", "http://example.com/a", "https://127.0.0.1/a"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                publish_action.validate_public_https_url(url)


class ForkStrategyTests(unittest.TestCase):
    def test_same_owner_does_not_depend_on_api_lookup(self):
        with mock.patch.object(fork_detector, "get_github_api") as api:
            self.assertEqual(
                fork_detector.detect_strategy("acme/rules", "acme/bcr", "", "token"),
                ("SAME_OWNER", "PAT", "acme/bcr"),
            )
            api.assert_not_called()

    def test_registry_fork_pushes_to_fork_and_requires_pat(self):
        repo_data = {
            "owner": {"login": "alice"},
            "parent": {"full_name": "upstream/bcr"},
        }
        with mock.patch.object(fork_detector, "get_github_api", return_value=repo_data):
            self.assertEqual(
                fork_detector.detect_strategy("alice/bcr", "upstream/bcr", "", "token"),
                ("SAME_REGISTRY_FORK", "PAT", "alice/bcr"),
            )


class WorkflowTests(unittest.TestCase):
    def test_actions_are_sha_pinned_and_tokens_are_not_outputs(self):
        workflow = (SCRIPT_DIR.parent / "workflows" / "publish_to_bcr.yml").read_text()
        for line in workflow.splitlines():
            if "uses:" in line and not "/.github/workflows/" in line:
                action = line.split("uses:", 1)[1].split("#", 1)[0].strip()
                if action.startswith("actions/"):
                    self.assertRegex(action, r"@[0-9a-f]{40}$")
        self.assertNotIn("tok=${{", workflow)
        self.assertNotIn("const mod = '${{", workflow)
        self.assertGreaterEqual(workflow.count("if: failure()"), 3)
        self.assertIn("GITHUB_STEP_SUMMARY", workflow)
        self.assertIn("html.escape(details)", workflow)

    def test_initializer_passes_registry_and_fork(self):
        rendered = init_ruleset.WORKFLOW_TEMPLATE.format(
            bcr="upstream/bcr", bcr_fork="alice/bcr", module_name="demo"
        )
        self.assertIn('registry: "upstream/bcr"', rendered)
        self.assertIn('registry_fork: "alice/bcr"', rendered)


if __name__ == "__main__":
    unittest.main()
