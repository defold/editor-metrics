import unittest

from scripts import fetch_defold_build


def make_release(tag_name: str, editor_commit_sha: str, *, prerelease: bool = True, target_commitish: str = "dev") -> dict[str, object]:
    return {
        "tag_name": tag_name,
        "target_commitish": target_commitish,
        "prerelease": prerelease,
        "body": f"Channel=alpha sha1: {editor_commit_sha}",
    }


class FetchDefoldBuildTests(unittest.TestCase):
    def test_editor_sha_accepts_legacy_editor_channel_format(self) -> None:
        self.assertEqual(
            "a" * 40,
            fetch_defold_build.editor_sha(f"Editor channel=alpha sha1: {'a' * 40}"),
        )

    def test_sha_matches_prefix(self) -> None:
        self.assertTrue(fetch_defold_build.sha_matches("abcdef123456", "abcdef"))

    def test_choose_release_uses_latest_dev_alpha_without_requested_sha(self) -> None:
        releases = [
            make_release("1.9.0-alpha", "a" * 40),
            make_release("1.8.9", "b" * 40, prerelease=False),
        ]

        chosen = fetch_defold_build.choose_release(releases)

        self.assertEqual("1.9.0-alpha", chosen["tag_name"])

    def test_choose_release_for_editor_sha_matches_prefix(self) -> None:
        releases = [
            make_release("1.9.0-alpha", "a" * 40),
            make_release("1.9.1-alpha", "b" * 40),
        ]

        chosen = fetch_defold_build.choose_release_for_editor_sha(releases, "bbbbbbbb")

        self.assertEqual("1.9.1-alpha", chosen["tag_name"])

    def test_choose_release_for_editor_sha_rejects_missing_match(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "could not find alpha release"):
            fetch_defold_build.choose_release_for_editor_sha([make_release("1.9.0-alpha", "a" * 40)], "deadbeef")


if __name__ == "__main__":
    unittest.main()
