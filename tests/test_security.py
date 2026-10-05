import unittest

from backend.security import constant_time_equal, safe_target_url, validate_loopback_target, validate_upstream_url


class SecurityTests(unittest.TestCase):
    def test_loopback_is_allowed(self):
        validate_loopback_target("127.0.0.1")
        validate_loopback_target("localhost")

    def test_public_target_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_loopback_target("example.com")

    def test_upstream_url(self):
        host, port = validate_upstream_url("http://127.0.0.1:5500")
        self.assertEqual((host, port), ("127.0.0.1", 5500))

    def test_target_building(self):
        self.assertEqual(safe_target_url("http://127.0.0.1:5500", "/index.html", "a=1"), "http://127.0.0.1:5500/index.html?a=1")

    def test_token_compare(self):
        self.assertTrue(constant_time_equal("abc", "abc"))
        self.assertFalse(constant_time_equal("abc", "abd"))


if __name__ == "__main__":
    unittest.main()
