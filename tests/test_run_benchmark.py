import unittest
from unittest import mock

from scripts import run_benchmark


class RunBenchmarkTests(unittest.TestCase):
    def test_build_sample_can_record_open_timeout(self) -> None:
        sample = run_benchmark.build_sample(
            "defold/big-synthetic-project",
            {
                "editor_commit_sha": "abc",
                "editor_commit_time": "2026-03-23T12:00:00Z",
                "release_tag": "1.2.3-alpha",
                "platform": "macos-arm64",
            },
            123,
            open_time_ms=600000,
            status="failed",
            error="timed out waiting for project open",
        )

        self.assertEqual("failed", sample["status"])
        self.assertEqual(600000, sample["open_time_ms"])
        self.assertIsNone(sample["build_time_ms"])

    def test_build_sample_can_record_build_timeout(self) -> None:
        sample = run_benchmark.build_sample(
            "defold/big-synthetic-project",
            {
                "editor_commit_sha": "abc",
                "editor_commit_time": "2026-03-23T12:00:00Z",
                "release_tag": "1.2.3-alpha",
                "platform": "macos-arm64",
            },
            123,
            open_result={"open_time_ms": 510000},
            build_time_ms=600000,
            status="failed",
            error="timed out waiting for build after 600000 ms",
        )

        self.assertEqual(510000, sample["open_time_ms"])
        self.assertEqual(600000, sample["build_time_ms"])
        self.assertEqual("failed", sample["status"])

    @mock.patch("scripts.run_benchmark.BUILD_HEARTBEAT_SECONDS", 1)
    def test_trigger_build_logs_heartbeat_while_waiting(self) -> None:
        started = mock.Mock()

        def slow_http_json(url: str, *, method: str = "GET", timeout: float = 10.0) -> tuple[int, object | None, str]:
            started()
            import time

            time.sleep(1.2)
            return 200, {"success": True}, ""

        with mock.patch("scripts.run_benchmark.http_json", side_effect=slow_http_json), mock.patch(
            "scripts.run_benchmark.log"
        ) as log_mock:
            result = run_benchmark.trigger_build(8080, 10)

        self.assertEqual({"success": True}, result["build_response"])
        self.assertTrue(started.called)
        self.assertTrue(any("waiting for build:" in call.args[0] for call in log_mock.call_args_list))


if __name__ == "__main__":
    unittest.main()
