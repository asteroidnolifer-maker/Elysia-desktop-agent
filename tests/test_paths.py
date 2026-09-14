import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.paths import PathEscapeError, resolve_path, validate_file_list
from elysia.core.workspace import Workspace


class TestPaths(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="elysia-ws-")

    def test_normal_resolution(self):
        p = resolve_path(self.root, "src/foo.py")
        self.assertEqual(os.path.join(self.root, "src", "foo.py"), p)

    def test_rejects_traversal(self):
        with self.assertRaises(PathEscapeError):
            resolve_path(self.root, "../evil.py")
        with self.assertRaises(PathEscapeError):
            resolve_path(self.root, "a/../../etc/passwd")

    def test_rejects_absolute(self):
        with self.assertRaises(PathEscapeError):
            resolve_path(self.root, "/etc/passwd")

    def test_rejects_empty_components(self):
        with self.assertRaises(PathEscapeError):
            resolve_path(self.root, "//etc")   # cleaned to absolute

    def test_rejects_symlink_escape(self):
        outside = tempfile.mkdtemp(prefix="elysia-out-")
        link = os.path.join(self.root, "escape")
        os.symlink(outside, link)
        with self.assertRaises(PathEscapeError):
            resolve_path(self.root, "escape/x.py")

    def test_symlink_inside_ok(self):
        os.makedirs(os.path.join(self.root, "real"), exist_ok=True)
        os.symlink(os.path.join(self.root, "real"),
                   os.path.join(self.root, "alias"))
        p = resolve_path(self.root, "alias/f.py")
        self.assertTrue(p.startswith(os.path.join(self.root, "real")))

    def test_list_validation(self):
        good = validate_file_list(self.root, ["src/a.py", "b/c.ts"])
        self.assertEqual(good, ["src/a.py", "b/c.ts"])


class TestWorkspace(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="elysia-ws-")
        self.ws = Workspace(self.root)

    def test_owned_write_and_read(self):
        path = self.ws.write_owned("docs/a.md", "# A\nhello")
        self.assertTrue(os.path.isfile(path))
        self.assertIn("hello", self.ws.read("docs/a.md"))

    def test_write_blocks_traversal(self):
        with self.assertRaises(PathEscapeError):
            self.ws.write_owned("../evil.txt", "x")

    def test_write_requires_valid_path(self):
        with self.assertRaises(PathEscapeError):
            self.ws.write_owned("/etc/cron.d/x", "x")


if __name__ == "__main__":
    unittest.main()