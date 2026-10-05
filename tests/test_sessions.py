import unittest

from backend.sessions import SessionManager


class SessionTests(unittest.TestCase):
    def test_touch_revoke_and_restore(self):
        manager = SessionManager()
        sid, session = manager.touch(None, "192.168.1.10", "TestBrowser", "http://example.test/")
        self.assertTrue(sid)
        self.assertEqual(session.ip, "192.168.1.10")
        self.assertFalse(manager.is_revoked(sid))

        self.assertTrue(manager.revoke(sid))
        self.assertTrue(manager.is_revoked(sid))
        self.assertIsNone(manager.touch_existing(sid, "192.168.1.10", "TestBrowser", "http://example.test/"))

        self.assertTrue(manager.restore(sid))
        self.assertFalse(manager.is_revoked(sid))
        self.assertIsNotNone(manager.touch_existing(sid, "192.168.1.10", "TestBrowser", "http://example.test/again"))

    def test_bulk_revoke_and_restore(self):
        manager = SessionManager()
        a, _ = manager.touch(None, "192.168.1.10", "A", "http://x/")
        b, _ = manager.touch(None, "192.168.1.11", "B", "http://y/")
        self.assertEqual(manager.counts()["active"], 2)

        self.assertEqual(manager.revoke_all(), 2)
        counts = manager.counts()
        self.assertEqual(counts["revoked"], 2)
        self.assertEqual(counts["active"], 0)

        self.assertEqual(manager.restore_all(), 2)
        counts = manager.counts()
        self.assertEqual(counts["revoked"], 0)
        self.assertEqual(counts["active"], 2)
        self.assertFalse(manager.is_revoked(a))
        self.assertFalse(manager.is_revoked(b))

    def test_active_count(self):
        manager = SessionManager()
        manager.touch(None, "192.168.1.10", "A", "http://x/")
        self.assertEqual(manager.active_count(), 1)


if __name__ == "__main__":
    unittest.main()
