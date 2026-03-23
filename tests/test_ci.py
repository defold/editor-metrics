import unittest

from scripts import ci


class CiTests(unittest.TestCase):
    def test_snapshot_branch_name_uses_ci_prefix_for_push(self) -> None:
        self.assertEqual("ci/abc123", ci.snapshot_branch_name("abc123", "push"))

    def test_snapshot_branch_name_uses_dispatch_prefix_for_workflow_dispatch(self) -> None:
        self.assertEqual("dispatch/abc123", ci.snapshot_branch_name("abc123", "workflow_dispatch"))

    def test_parse_workflow_inputs(self) -> None:
        self.assertEqual(
            [("editor_sha", "abc123"), ("commit_to_default_branch", "false")],
            ci.parse_workflow_inputs(["editor_sha=abc123", "commit_to_default_branch=false"]),
        )

    def test_parse_workflow_inputs_requires_name_value_format(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "NAME=VALUE"):
            ci.parse_workflow_inputs(["editor_sha"])


if __name__ == "__main__":
    unittest.main()
