#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from generate_diff import code_block, get_recursive_files
from check_platform_needed import get_presubmit_platforms
from get_test_platforms import DEFAULT_PLATFORMS, get_platforms_from_presubmit
from presubmit import PresubmitChecker, tasks_define_platforms, validate_public_https_url
from registry import resolve_within, validate_module_name, validate_version_name
from run_bazel_tests import (
    DEFAULT_BAZEL_OUTPUT_FLAGS,
    create_bazel_environment,
    extract_bazel_errors,
    get_presubmit_platforms as get_run_platforms,
    get_task_platforms,
    should_run_for_platform,
    shutdown_bazel,
    validate_bazel_flags,
    validate_target,
)


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
        self.assertEqual(
            validate_bazel_flags(['--cxxopt=-std=c++17'], 'build_flags'),
            ['--cxxopt=-std=c++17'],
        )
        self.assertEqual(
            validate_bazel_flags(['--cxxopt=/std:c++17'], 'build_flags'),
            ['--cxxopt=/std:c++17'],
        )

    def test_rejects_flag_as_target(self):
        with self.assertRaises(ValueError):
            validate_target('--action_env=GITHUB_TOKEN')

    def test_default_bazel_output_suppresses_low_severity_events(self):
        self.assertEqual(
            DEFAULT_BAZEL_OUTPUT_FLAGS,
            ('--noshow_progress', '--ui_event_filters=-debug,-info,-progress'),
        )

    def test_extracts_concise_bazel_errors(self):
        output = (
            'Computing main repo mapping:\n'
            'Analyzing: 18 targets\n'
            'ERROR: build failed\n'
            'file.cpp(10): error C2338: add /utf-8\n'
            'ERROR: build failed\n'
        )
        self.assertEqual(
            extract_bazel_errors(output),
            ['ERROR: build failed', 'file.cpp(10): error C2338: add /utf-8'],
        )

    @mock.patch('run_bazel_tests.subprocess.run')
    def test_shutdown_uses_requested_bazelisk_version(self, run):
        env = create_bazel_environment('8.x')

        shutdown_bazel(env)

        self.assertEqual(env['USE_BAZEL_VERSION'], '8.x')
        run.assert_called_once_with(
            ['bazel', 'shutdown', *DEFAULT_BAZEL_OUTPUT_FLAGS],
            env=env,
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

    def test_task_platform_lists_are_discovered_and_filtered(self):
        tasks = {
            'verify_targets': {'platforms': ['ubuntu2404', 'macos']},
            'verify_targets_windows': {'platforms': ['windows']},
        }
        self.assertEqual(
            get_run_platforms({}, tasks),
            ['ubuntu2404', 'macos', 'windows'],
        )
        self.assertTrue(should_run_for_platform(
            get_task_platforms(tasks['verify_targets']), 'ubuntu2404'))
        self.assertFalse(should_run_for_platform(
            get_task_platforms(tasks['verify_targets']), 'windows'))

        with tempfile.TemporaryDirectory() as directory:
            presubmit = Path(directory) / 'presubmit.yml'
            presubmit.write_text(
                'tasks:\n'
                '  verify_targets:\n'
                '    platforms: [ubuntu2404, macos]\n'
                '  verify_targets_windows:\n'
                '    platforms: [windows]\n'
            )
            expected = ['ubuntu2404', 'macos', 'windows']
            self.assertEqual(get_presubmit_platforms(presubmit), expected)
            self.assertEqual(get_platforms_from_presubmit(presubmit), expected)

    def test_task_platforms_must_be_a_string_list(self):
        for value in ('windows', [1]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                get_task_platforms({'platforms': value})

    def test_presubmit_accepts_platforms_in_every_task(self):
        tasks = {
            'verify_targets': {'platforms': ['ubuntu2404', 'macos']},
            'verify_targets_windows': {'platforms': ['windows']},
        }
        self.assertTrue(tasks_define_platforms(tasks))

        class FakeRegistry:
            def get_presubmit(self, module_name, version):
                return {'matrix': {'bazel': ['7.x', '8.x']}, 'tasks': tasks}

            def get_previous_version(self, module_name, version):
                return None

        checker = PresubmitChecker('.')
        checker.registry = FakeRegistry()
        results = checker.check_presubmit_yaml('khttpd', '0.3.0')
        self.assertFalse(any(
            result.name == 'presubmit-yaml/matrix-platform' and not result.passed
            for result in results
        ))
        self.assertTrue(any(
            result.name == 'presubmit-yaml' and result.passed
            for result in results
        ))

    def test_presubmit_rejects_incomplete_task_platforms(self):
        invalid_tasks = (
            {},
            {'verify_targets': {}},
            {'verify_targets': {'platforms': []}},
            {'verify_targets': {'platforms': 'windows'}},
            {
                'verify_targets': {'platforms': ['ubuntu2404']},
                'verify_targets_windows': {},
            },
        )
        for tasks in invalid_tasks:
            with self.subTest(tasks=tasks):
                self.assertFalse(tasks_define_platforms(tasks))


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

    def test_presubmit_trigger_label_is_persistent(self):
        workflow = (SCRIPT_DIR.parent / 'workflows' / 'presubmit.yml').read_text()
        authorize_step = workflow.split('id: authorize-run', 1)[1].split(
            '- name: Detect changed modules', 1)[0]
        self.assertIn('pr.labels ?? []', authorize_step)
        self.assertNotIn("context.payload.action === 'labeled'", authorize_step)

    def test_presubmit_maintainer_authorization_uses_trusted_user_ids(self):
        workflow = (SCRIPT_DIR.parent / 'workflows' / 'presubmit.yml').read_text()
        authorize_step = workflow.split('id: authorize-run', 1)[1].split(
            '- name: Detect changed modules', 1)[0]

        # Changed modules come from the API and metadata comes from the immutable
        # base SHA, so the PR cannot authorize itself by editing either helper
        # scripts or metadata.json.
        self.assertIn('github.rest.pulls.listFiles', authorize_step)
        self.assertIn('file.previous_filename', authorize_step)
        self.assertIn('files.length !== pr.changed_files', authorize_step)
        self.assertIn('github.rest.repos.getContent', authorize_step)
        self.assertIn('ref: pr.base.sha', authorize_step)

        # Maintainer authorization is all-modules and ID-only. In particular,
        # there must be no fallback to the mutable GitHub login field.
        self.assertIn('authorizedForAllModules', authorize_step)
        self.assertIn('maintainer.github_user_id === authorId', authorize_step)
        self.assertNotRegex(authorize_step, r'maintainer\.github(?!_user_id)')

    def test_auto_merge_is_bound_to_successful_presubmit_and_tested_sha(self):
        workflow = (SCRIPT_DIR.parent / 'workflows' /
                    'presubmit-auto-merge.yml').read_text()
        self.assertIn("workflows: ['Presubmit Checks']", workflow)
        self.assertIn("workflow_run.conclusion == 'success'", workflow)
        self.assertIn("workflow_run.event == 'pull_request'", workflow)
        self.assertIn("pr.base.ref !== 'main'", workflow)
        self.assertIn('pr.head.sha !== run.head_sha', workflow)
        self.assertIn('sha: run.head_sha', workflow)
        self.assertIn('currentPr.mergeable !== true', workflow)

    def test_auto_merge_uses_trusted_all_module_maintainer_ids(self):
        workflow = (SCRIPT_DIR.parent / 'workflows' /
                    'presubmit-auto-merge.yml').read_text()
        self.assertIn('files.length !== pr.changed_files', workflow)
        self.assertIn('file.previous_filename', workflow)
        self.assertIn('changedModules.size > 0', workflow)
        self.assertIn('ref: pr.base.sha', workflow)
        self.assertIn('maintainer.github_user_id === authorId', workflow)
        self.assertNotRegex(workflow, r'maintainer\.github(?!_user_id)')


if __name__ == '__main__':
    unittest.main()
