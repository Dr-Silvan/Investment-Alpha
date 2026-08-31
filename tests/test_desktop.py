import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop


class DesktopLauncherTests(unittest.TestCase):
    def test_server_is_closed_after_app_window_exits(self):
        fake_server = MagicMock()
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        def launch(*args, **kwargs):
            desktop.server.LAST_HEARTBEAT = 100.0
            return fake_process
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(desktop, "find_edge", return_value=Path("edge.exe")),
                patch.object(desktop.server, "init_db"),
                patch.object(desktop.server, "ThreadingHTTPServer", return_value=fake_server),
                patch.object(desktop.subprocess, "Popen", side_effect=launch),
                patch.object(desktop.server, "DATA", Path(tmp)),
                patch.object(desktop.time, "monotonic", side_effect=[100.0, 107.0]),
            ):
                self.assertEqual(desktop.main(), 0)
        fake_server.shutdown.assert_called_once()
        fake_server.server_close.assert_called_once()
        fake_process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
