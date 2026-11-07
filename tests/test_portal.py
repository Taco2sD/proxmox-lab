"""Unit tests for the portal's web side (ansible/roles/portal/files/portal.py): username
rules, the admin session cookie, and the Guacamole login it builds.
Run by tools/check: python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault("LAB_STATE", tempfile.mkdtemp())
os.environ["LAB_REPO"] = str(REPO)
sys.path.insert(0, str(REPO / "ansible" / "roles" / "runner" / "files"))
sys.path.insert(0, str(REPO / "ansible" / "roles" / "portal" / "files"))
import lablib as L  # noqa: E402
import portal  # noqa: E402


class Usernames(unittest.TestCase):
    def setUp(self):
        L.PASSWORDS.mkdir(parents=True, exist_ok=True)

    def test_rules(self):
        self.assertIsNone(portal.username_problem("ann"))
        self.assertIsNone(portal.username_problem("a23456789012"))      # 12: ws-<name> fits NetBIOS
        for bad in ("an", "a234567890123", "1ann", "Ann", "an-n", "root", "labadmin"):
            self.assertIsNotNone(portal.username_problem(bad), bad)

    def test_taken(self):
        (L.PASSWORDS / "zed").write_text("x")
        self.assertIn("taken", portal.username_problem("zed"))


class AdminSession(unittest.TestCase):
    def setUp(self):
        key = Path(tempfile.mkdtemp()) / "session-key"
        key.write_text("ab" * 32)
        portal.SESSION_KEY = key

    def test_round_trip_and_tampering(self):
        cookie = portal.session_cookie("jrhodes")
        self.assertEqual(portal.session_user(cookie), "jrhodes")
        b64, sig = cookie.split(".")
        self.assertIsNone(portal.session_user(b64 + "." + "0" * len(sig)))
        self.assertIsNone(portal.session_user("garbage"))


class GuacamoleLogin(unittest.TestCase):
    def test_decrypts_with_the_shared_key(self):
        try:
            from cryptography.hazmat.primitives import padding
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except ImportError:
            self.skipTest("python3-cryptography not installed")
        import base64
        import hashlib
        import hmac
        import json
        tmp = Path(tempfile.mkdtemp())
        (tmp / "key").write_text("00112233445566778899aabbccddeeff")
        portal.JSON_KEY = tmp / "key"
        L.PASSWORDS.mkdir(parents=True, exist_ok=True)
        (L.PASSWORDS / "gus").write_text("pw")
        blob = base64.b64decode(portal.guacamole_login({"owner": "gus", "host": "ws-gus", "ip": "10.10.10.31"}))
        key = bytes.fromhex((tmp / "key").read_text())
        d = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).decryptor()
        u = padding.PKCS7(128).unpadder()
        plain = u.update(d.update(blob) + d.finalize()) + u.finalize()
        sig, payload = plain[:32], plain[32:]
        self.assertEqual(sig, hmac.new(key, payload, hashlib.sha256).digest())
        self.assertEqual(json.loads(payload)["connections"]["ws-gus"]["parameters"]["hostname"], "10.10.10.31")


if __name__ == "__main__":
    unittest.main()
