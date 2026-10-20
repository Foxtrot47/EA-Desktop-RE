import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ea_custom_launcher import (
    _is_parent_path,
    build_origin2_uri,
    ensure_ea_broker,
    launch_activity,
    load_library_config,
    save_library_mapping,
)


class Origin2UriTests(unittest.TestCase):
    def test_offer_launch(self):
        self.assertEqual(
            build_origin2_uri("game/launch", identifier="Origin.OFR.50.0000001"),
            "origin2://game/launch?contextType=OFFER&id=Origin.OFR.50.0000001",
        )

    def test_slug_and_arguments_are_encoded(self):
        self.assertEqual(
            build_origin2_uri(
                "game/launch",
                identifier="test game",
                context_type="SLUG",
                cmd_params="--language en_US",
            ),
            "origin2://game/launch?contextType=SLUG&id=test+game&cmdParams=--language+en_US",
        )

    def test_library_open_needs_no_identifier(self):
        self.assertEqual(build_origin2_uri("library/open"), "origin2://library/open")

    def test_launch_requires_identifier(self):
        with self.assertRaises(ValueError):
            build_origin2_uri("game/launch")

    def test_install_root_matches_child_working_directory(self):
        self.assertTrue(_is_parent_path(r"E:\Games\Example", r"E:\Games\Example\bin"))
        self.assertFalse(_is_parent_path(r"E:\Games\Example", r"E:\Games\Other"))

    def test_mapping_round_trip_and_replacement(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "library.json"
            save_library_mapping(
                name="Example",
                install_location=r"E:\Games\Example",
                identifier="first-slug",
                context="SLUG",
                path=path,
            )
            save_library_mapping(
                name="Example",
                install_location=r"E:\Games\Example",
                identifier="Origin.OFR.50.123",
                context="OFFER",
                cmd_params="-language en_US",
                path=path,
            )
            self.assertEqual(
                load_library_config(path),
                [
                    {
                        "name": "Example",
                        "install_location": r"E:\Games\Example",
                        "context": "OFFER",
                        "id": "Origin.OFR.50.123",
                        "cmd_params": "-language en_US",
                    }
                ],
            )

    def test_launch_activity_returns_structured_markers_only(self):
        with TemporaryDirectory() as directory:
            log = Path(directory) / "EADesktop.log"
            log.write_text(
                "\n".join(
                    (
                        "[2026-10-16T10:00:00.000Z] [GAME] Issuing launch: workingDirectory[E:\\Game] offer[Offer.1] content[42] gameArgs []",
                        "[2026-10-16T10:00:01.000Z] Successful launch. IDs: offerKey.offerId=[Offer.1]",
                        "[2026-10-16T10:00:02.000Z] Cloud Sync entry point pre game launch",
                        "[2026-10-16T10:00:03.000Z] Cloud sync completed successfully, cloudId: [42]",
                        "[2026-10-16T10:01:03.000Z] Game process terminated",
                        "[2026-10-16T10:01:04.000Z] Game process exit code=[7]",
                        "[2026-10-16T10:01:05.000Z] Post game cloud sync completed successfully",
                    )
                ),
                encoding="utf-8",
            )
            activity = launch_activity("Offer.1", Path(directory))
            self.assertEqual(activity.state, "complete")
            self.assertEqual(activity.exit_code, 7)
            self.assertEqual(activity.requested_at, "2026-10-16T10:00:00.000Z")

    @patch("ea_custom_launcher.subprocess.Popen")
    @patch("ea_custom_launcher.resolve_ea_launcher")
    @patch("ea_custom_launcher._process_running")
    def test_cold_start_uses_supported_silent_launcher(self, running, resolve_launcher, popen):
        running.side_effect = (False, True)
        resolve_launcher.return_value = Path(r"C:\EA\EALauncher.exe")
        with patch.object(Path, "is_file", return_value=True):
            self.assertTrue(ensure_ea_broker(timeout=0.5))
        popen.assert_called_once_with(
            [r"C:\EA\EALauncher.exe", "-silent"], close_fds=True
        )

    @patch("ea_custom_launcher._process_running", return_value=True)
    def test_cold_start_skips_launcher_when_broker_is_running(self, _running):
        self.assertFalse(ensure_ea_broker(timeout=0.01))


if __name__ == "__main__":
    unittest.main()
