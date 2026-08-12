#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from generate_diff import code_block, get_recursive_files
from check_platform_needed import get_presubmit_platforms
from get_test_platforms import DEFAULT_PLATFORMS, get_platforms_from_presubmit
from presubmit import validate_public_https_url
from registry import resolve_within, validate_module_name, validate_version_name
from run_bazel_tests import DEFAULT_BAZEL_OUTPUT_FLAGS, validate_bazel_flags, validate_target


class SafePathTests(unittest.TestCase):
    def test_rejects_parent_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in ('', '../secret', '/etc/passwd', 'dir/../../secret', 'dir\\secret'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    resolve_within(root, value)

    @unittest.skipUnless(os.name == 'nt', 'Windows-specific Path rendering')
    def test_accepts_normal_windows_path_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / 'khttpd' / '0.3.0' / 'presubmit.yml'
            self.assertEqual(
                resolve_within(root, Path('khttpd') / '0.3.0' / 'presubmit.yml'),
                expected.resolve(),
            )

    def test_rejects_file_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / 'bcr-security-test-secret'
            outside.write_text('secret')
            try:
                (root / 'leak').symlink_to(outside)
                with self.assertRaises(ValueError):
                    resolve_within(root, 'leak')
            finally:
                outside.unlink(missing_ok=True)

    def test_diff_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            version = Path(directory)
            overlay = version / 'overlay'
            overlay.mkdir()
            (overlay / 'normal.txt').write_text('ok')
            (overlay / 'leak.txt').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                get_recursive_files(version, 'overlay')

    def test_module_and_version_names_are_components(self):
        self.assertEqual(validate_module_name('good_module'), 'good_module')
        self.assertEqual(validate_version_name('1.2.3.bcr.1'), '1.2.3.bcr.1')
        for value in ('../module', 'Bad Module', '/tmp/module'):
            with self.assertRaises(ValueError):
                validate_module_name(value)


class RenderingAndBazelTests(unittest.TestCase):
    def test_code_fence_cannot_be_closed_by_content(self):
        block = code_block('before\n```\nafter', 'text')
        self.assertTrue(block[0].startswith('````text'))
        self.assertEqual(block[0][:-4], block[-1])

    def test_rejects_secret_forwarding_flags(self):
        for flag in ('--action_env=GITHUB_TOKEN', '--repo_env=TOKEN=x', '--remote_header=x=y'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                validate_bazel_flags([flag], 'build_flags')
        self.assertEqual(validate_bazel_flags(['--verbose_failures'], 'build_flags'), ['--verbose_failures'])

    def test_rejects_flag_as_target(self):
        with self.assertRaises(ValueError):
            validate_target('--action_env=GITHUB_TOKEN')

    def test_default_bazel_output_suppresses_low_severity_events(self):
        self.assertEqual(
            DEFAULT_BAZEL_OUTPUT_FLAGS,
            ('--ui_event_filters=-debug,-info,-progress',),
        )


class PlatformConfigTests(unittest.TestCase):
    def test_invalid_presubmit_shapes_use_default_platforms(self):
        with tempfile.TemporaryDirectory() as directory:
            presubmit = Path(directory) / 'presubmit.yml'
            for content in ('', '[]', 'matrix: []', 'matrix:\n  platform: windows', 'tasks: []'):
                with self.subTest(content=content):
                    presubmit.write_text(content)
                    self.assertEqual(get_presubmit_platforms(presubmit), DEFAULT_PLATFORMS)
                    self.assertEqual(get_platforms_from_presubmit(presubmit), DEFAULT_PLATFORMS)


class NetworkTests(unittest.TestCase):
    def test_rejects_non_https_and_private_addresses(self):
        for url in ('http://example.com/archive.tar.gz', 'file:///etc/passwd',
                    'https://127.0.0.1/archive.tar.gz', 'https://[::1]/archive.tar.gz'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_public_https_url(url)


class WorkflowTests(unittest.TestCase):
    def test_skip_workflow_never_interpolates_comment_body(self):
        workflow = (SCRIPT_DIR.parent / 'workflows' / 'skip_check.yml').read_text()
        self.assertNotIn('${{ github.event.comment.body }}', workflow)
        allowed = workflow.split('const allowedChecks', 1)[1].split(']);', 1)[0]
        self.assertNotIn('presubmit-auto-run', allowed)

    def test_bazel_job_has_no_token_environment(self):
        workflow = (SCRIPT_DIR.parent / 'workflows' / 'presubmit.yml').read_text()
        bazel_job = workflow.split('  bazel-test:', 1)[1].split('  bazel-test-result:', 1)[0]
        self.assertNotIn('secrets.GITHUB_TOKEN', bazel_job)
        self.assertIn('persist-credentials: false', bazel_job)
        self.assertNotIn('checks: write', bazel_job)


if __name__ == '__main__':
    unittest.main()
