from __future__ import annotations

import os
import unittest

from rabotyaga_gateway.protection import WindowsDPAPIProtector


@unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
class DPAPITests(unittest.TestCase):
    def test_round_trip_uses_current_user_scope(self) -> None:
        protector = WindowsDPAPIProtector()
        secret = b"test-signing-key-material"
        encrypted = protector.protect(secret)
        self.assertNotEqual(encrypted, secret)
        self.assertEqual(protector.unprotect(encrypted), secret)


if __name__ == "__main__":
    unittest.main()
