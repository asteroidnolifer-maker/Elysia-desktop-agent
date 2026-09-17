"""Tests for the universal install + launch scripts.

`scripts/elysia_boot.py` is the single implementation for Linux, macOS and
Windows; the `.sh` / `.ps1` / `.cmd` files are shims that must only locate a
Python interpreter and forward to it. These tests pin that contract so a
rename or a typo in a shim cannot silently break installation elsewhere.

Everything here is offline-safe: no model, no network, no credentials, and the
dry-run modes must not create files or start services.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BOOT = os.path.join(ROOT, "scripts", "elysia_boot.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import elysia_boot as eb  # noqa: E402

VERBS = ("install", "start", "stop", "restart", "status", "doctor")
SHIMS = ("install.sh", "start.sh", "install.ps1", "start.ps1",
         "install.cmd", "start.cmd")


def boot(*args, timeout=120):
    return subprocess.run([sys.executable, BOOT, *args], capture_output=True,
                          text=True, timeout=timeout, cwd=ROOT)


class TestBootCli(unittest.TestCase):
    def test_every_subcommand_has_help(self):
        for verb in VERBS:
            r = boot(verb, "--help")
            self.assertEqual(r.returncode, 0, f"{verb} --help: {r.stderr}")
            self.assertIn(verb, r.stdout)

    def test_no_args_prints_help(self):
        r = boot()
        self.assertEqual(r.returncode, 0)
        self.assertIn("install", r.stdout)

    def test_install_dry_run_changes_nothing(self):
        r = boot("install", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("dry run: nothing was changed", r.stdout)
        self.assertIn("would write", r.stdout)          # manifest, not written
        self.assertIn("would create", r.stdout)         # directories, not made

    def test_install_dry_run_with_deps_shows_package_command(self):
        r = boot("install", "--dry-run", "--deps")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # a missing tool must be reported with the exact install command
        if "tool: go: not found" in r.stdout:
            self.assertIn("would install via", r.stdout)
            self.assertIn("install -y golang-go", r.stdout)

    def test_start_dry_run_never_claims_a_service_is_up(self):
        r = boot("start", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("dry run: nothing was started", r.stdout)
        # it must say "would start", never that something is already up
        self.assertNotIn(": up on", r.stdout)
        self.assertNotIn("[ok  ] hud: up", r.stdout)

    def test_status_reports_down_ports_without_a_service(self):
        r = boot("status", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        import json
        data = json.loads(r.stdout)
        self.assertEqual(len(data["services"]), 3)
        for svc in data["services"]:
            self.assertIn("port_open", svc)
            self.assertIn(svc["service"], ("model", "agent", "hud"))

    def test_stop_without_services_is_a_clean_noop(self):
        r = boot("stop")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestShellShims(unittest.TestCase):
    def _read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return f.read()

    def test_shell_shims_are_posix_clean(self):
        for name in ("install.sh", "start.sh"):
            path = os.path.join(ROOT, name)
            self.assertTrue(os.path.isfile(path), f"{name} is missing")
            for shell in ("sh", "bash"):
                if not shutil.which(shell):
                    continue
                r = subprocess.run([shell, "-n", path], capture_output=True,
                                   text=True)
                self.assertEqual(r.returncode, 0,
                                 f"{shell} -n {name}: {r.stderr}")

    def test_shims_forward_to_the_boot_script(self):
        for name in SHIMS:
            body = self._read(name)
            self.assertIn("elysia_boot.py", body,
                          f"{name} must call scripts/elysia_boot.py")

    def test_default_verbs(self):
        self.assertIn("install", self._read("install.sh"))
        self.assertIn("install", self._read("install.ps1"))
        self.assertIn('VERB=start', self._read("start.cmd"))
        self.assertIn("'start'", self._read("start.ps1"))
        self.assertIn("start|stop|restart|status", self._read("start.sh"))

    def test_install_sh_fails_clearly_without_python(self):
        """A shim must explain the problem, not fail silently."""
        body = self._read("install.sh")
        self.assertIn("Python 3.8+ is required", body)


class TestServiceLifecycle(unittest.TestCase):
    """The launcher's real spawn -> liveness -> stop path (no server needed)."""

    def setUp(self):
        self.ui = eb.Ui(quiet=True)
        self.args = argparse.Namespace(dry_run=False, json=False, yes=True)
        self.name = "hud"
        self.started = None

    def tearDown(self):
        if self.started and eb._alive(self.started):
            try:
                os.kill(self.started, 9)
            except OSError:
                pass

    def _spawn_sleeper(self):
        ok = eb._spawn(self.ui, self.name,
                       [sys.executable, "-c", "import time; time.sleep(60)"],
                       eb.ROOT, None)
        self.assertTrue(ok, "spawn must succeed")
        pid = eb._read_pid(self.name)
        self.assertTrue(pid, "a pid file must be written")
        self.started = pid
        return pid

    def test_spawn_then_stop_terminates_and_cleans_up(self):
        pid = self._spawn_sleeper()
        self.assertTrue(eb._alive(pid), "the spawned process must be alive")
        eb.cmd_stop(self.ui, self.args)
        # `stop` may only report success if the process is really gone
        self.assertFalse(eb._alive(pid), "stop must terminate the service")
        self.assertFalse(eb._pid_file(self.name).exists(),
                         "stop must remove the pid file")

    def test_stop_is_idempotent(self):
        self._spawn_sleeper()
        self.assertEqual(eb.cmd_stop(self.ui, self.args), 0)
        self.assertEqual(eb.cmd_stop(self.ui, self.args), 0)

    def test_stale_pid_file_is_cleaned_not_reported_stopped(self):
        dead = 999999                                   # nothing owns this
        eb._pid_file(self.name).parent.mkdir(parents=True, exist_ok=True)
        eb._pid_file(self.name).write_text(str(dead))
        if eb._alive(dead):                             # pragma: no cover
            self.skipTest("pid 999999 unexpectedly exists")
        eb.cmd_stop(self.ui, self.args)
        self.assertFalse(eb._pid_file(self.name).exists())


class TestPortHelpers(unittest.TestCase):
    def test_port_open_detects_a_listening_socket(self):
        import socket
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            self.assertTrue(eb.port_open(port))
        finally:
            srv.close()
        self.assertFalse(eb.port_open(port))

    def test_wait_port_times_out_honestly(self):
        import socket
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.close()
        t0 = time.time()
        self.assertFalse(eb.wait_port(port, seconds=0.5))
        self.assertLess(time.time() - t0, 5)


if __name__ == "__main__":
    unittest.main()
