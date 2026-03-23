import subprocess
import unittest
from unittest import mock

from scripts import nightly


class NightlyTests(unittest.TestCase):
    def test_bool_arg(self) -> None:
        self.assertTrue(nightly.bool_arg("true"))
        self.assertFalse(nightly.bool_arg("false"))

    def test_build_commit_message_uses_short_sha(self) -> None:
        message = nightly.build_commit_message({"commit_sha": "1234567890abcdef"})

        self.assertEqual("Update metrics for 1234567890ab", message)

    @mock.patch("scripts.nightly.run")
    def test_commit_results_skips_commit_when_staged_diff_is_empty(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = [
            subprocess.CompletedProcess(["git", "add"], 0, "", ""),
            subprocess.CompletedProcess(["git", "diff"], 0, "", ""),
        ]

        committed = nightly.commit_results("master", {"commit_sha": "abc"})

        self.assertFalse(committed)

    @mock.patch("scripts.nightly.run")
    def test_commit_results_commits_and_pushes_when_changes_exist(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = [
            subprocess.CompletedProcess(["git", "add"], 0, "", ""),
            subprocess.CompletedProcess(["git", "diff"], 1, "", ""),
            subprocess.CompletedProcess(["git", "commit"], 0, "", ""),
            subprocess.CompletedProcess(["git", "push"], 0, "", ""),
        ]

        committed = nightly.commit_results("master", {"commit_sha": "1234567890abcdef"})

        self.assertTrue(committed)
        self.assertEqual("commit", run_mock.call_args_list[2].args[1])
        self.assertEqual("push", run_mock.call_args_list[3].args[1])


if __name__ == "__main__":
    unittest.main()
