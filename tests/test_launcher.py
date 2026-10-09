"""The first-run installer must stop together with its launcher."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest


class InstallerCancellationTests(unittest.TestCase):
    def test_interrupt_stops_only_owned_installer_group(self):
        original = Path(__file__).resolve().parents[1] / "start.command"
        for requested_signal in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=requested_signal), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "scripts").mkdir()
                (root / "start.command").write_text(original.read_text())
                (root / "scripts/common.sh").write_text(
                    "dependencies_ready() { return 1; }\nlauncher_failure() { :; }\n")
                (root / "install.command").write_text(
                    "#!/bin/bash\nsleep 60 &\n"
                    'printf "%s %s\\n" "$$" "$!" > "$XVL_MOCK_PIDS"\nwait\n')
                pids_file = root / "pids"
                launcher = subprocess.Popen(
                    ["/bin/bash", str(root / "start.command")], stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env={**os.environ, "XVL_MOCK_PIDS": str(pids_file)}, start_new_session=True)
                installer = child = None
                try:
                    deadline = time.monotonic() + 5
                    while not pids_file.exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(pids_file.exists(), "mock installer did not start")
                    installer, child = map(int, pids_file.read_text().split())
                    self.assertEqual(os.getpgid(installer), installer)
                    self.assertEqual(os.getpgid(child), installer)
                    self.assertNotEqual(os.getpgid(launcher.pid), installer)
                    launcher.send_signal(requested_signal)
                    self.assertEqual(launcher.wait(timeout=5),
                                     130 if requested_signal == signal.SIGINT else 143)
                    deadline = time.monotonic() + 5
                    while any(self.is_running(pid) for pid in (installer, child)):
                        self.assertLess(time.monotonic(), deadline, "installer child survived")
                        time.sleep(.02)
                finally:
                    if launcher.poll() is None:
                        launcher.kill(); launcher.wait(timeout=5)
                    if installer is not None:
                        try:
                            os.killpg(installer, signal.SIGTERM)
                        except ProcessLookupError:
                            pass

    @staticmethod
    def is_running(pid):
        state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                               capture_output=True, text=True).stdout.strip()
        return bool(state) and not state.startswith("Z")
