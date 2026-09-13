import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.git import redact


class TestRedact(unittest.TestCase):
    def test_openai_key(self):
        out = redact("key is sk-abcdefghijklmnopqrstuvwxyz123456")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("sk-abcdefghijklmnopqr", out)

    def test_github_token(self):
        out = redact("token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")
        self.assertIn("[REDACTED]", out)

    def test_composio_key(self):
        out = redact("COMPOSIO_API_KEY=ak_SomeApiTokenValue12345")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("ak_SomeApiToken", out)

    def test_authorization_header(self):
        out = redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def")
        self.assertIn("[REDACTED]", out)

    def test_private_key(self):
        out = redact("data: -----BEGIN RSA PRIVATE KEY----- AAABBB")
        self.assertIn("[REDACTED]", out)

    def test_plain_text_untouched(self):
        out = redact("hello world, nothing secret here")
        self.assertEqual(out, "hello world, nothing secret here")


if __name__ == "__main__":
    unittest.main()