import json
import unittest

from interchange_review.updater import parse_release, version_tuple


class UpdaterTest(unittest.TestCase):
    def test_version_tuple(self) -> None:
        self.assertEqual(version_tuple("v3.6.0"), (3, 6, 0))
        self.assertIsNone(version_tuple("3.6"))
        self.assertGreater(version_tuple("3.10.0"), version_tuple("3.6.9"))

    def test_release_parser_selects_architecture_asset_and_digest(self) -> None:
        payload = {
            "tag_name": "v3.6.0",
            "name": "K-GSS v3.6.0",
            "body": "update notes",
            "html_url": "https://example.test/release",
            "assets": [
                {"name": "other.exe", "browser_download_url": "https://example.test/other", "size": 1},
                {
                    "name": "K-GSS_v3.6.0.exe",
                    "browser_download_url": "https://example.test/kgss",
                    "digest": "sha256:" + "a" * 64,
                    "size": 123,
                },
                {
                    "name": "K-GSS_v3.6.0_windows-x64.exe",
                    "browser_download_url": "https://example.test/kgss-x64",
                    "digest": "sha256:" + "b" * 64,
                    "size": 124,
                },
                {
                    "name": "K-GSS_v3.6.0_windows-arm64.exe",
                    "browser_download_url": "https://example.test/kgss-arm64",
                    "digest": "sha256:" + "c" * 64,
                    "size": 125,
                },
            ],
        }
        release = parse_release(json.dumps(payload), "x64")
        self.assertEqual(release.version, "3.6.0")
        self.assertEqual(release.asset_url, "https://example.test/kgss-x64")
        self.assertEqual(release.digest, "sha256:" + "b" * 64)
        self.assertEqual(release.architecture, "x64")

        arm_release = parse_release(json.dumps(payload), "arm64")
        self.assertEqual(arm_release.asset_url, "https://example.test/kgss-arm64")
        self.assertEqual(arm_release.digest, "sha256:" + "c" * 64)
        self.assertEqual(arm_release.architecture, "arm64")

    def test_release_parser_keeps_legacy_x64_compatibility(self) -> None:
        payload = {
            "tag_name": "v3.6.0",
            "assets": [{"name": "K-GSS_v3.6.0.exe", "browser_download_url": "legacy", "size": 1}],
        }
        self.assertEqual(parse_release(json.dumps(payload), "x64").asset_url, "legacy")

    def test_release_parser_requires_expected_asset(self) -> None:
        with self.assertRaises(ValueError):
            parse_release(json.dumps({"tag_name": "v3.6.0", "assets": []}), "arm64")


if __name__ == "__main__":
    unittest.main()
