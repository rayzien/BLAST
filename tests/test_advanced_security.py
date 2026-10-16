"""Unit tests for Advanced Security System: Identity Protection & Strict Input Guard.
Guaranteed zero emojis.
"""

import json
import unittest
from config import BlastConfig
from security.identity import IdentityProtectionGuard
from security.input_guard import StrictInputValidator
from server import create_app


class TestIdentityProtection(unittest.TestCase):
    def setUp(self):
        self.cfg = BlastConfig(
            API_KEYS=["test-master-key-xyz"],
            REQUIRE_API_KEY=True,
            TESTING=True,
        )
        self.guard = IdentityProtectionGuard(self.cfg)

    def test_strip_untrusted_identity_headers(self):
        headers = {
            "Content-Type": "application/json",
            "X-Blast-Key": "test-master-key-xyz",
            "X-Blast-Client-Id": "spoofed-admin-id",
            "X-User-Id": "spoofed-user-id",
            "X-Remote-User": "hacker",
        }
        cleaned = self.guard.sanitize_inbound_identity_headers(headers)
        self.assertNotIn("X-Blast-Client-Id", cleaned)
        self.assertNotIn("X-User-Id", cleaned)
        self.assertNotIn("X-Remote-User", cleaned)
        self.assertIn("Content-Type", cleaned)
        self.assertIn("X-Blast-Key", cleaned)

    def test_identity_token_derivation_and_verification(self):
        client_id = "client-alpha"
        secret = "super-secret-key"
        token = self.guard.generate_identity_token(client_id, secret)
        self.assertTrue(self.guard.verify_identity_token(client_id, secret, token))
        self.assertFalse(self.guard.verify_identity_token(client_id, "wrong-secret", token))
        self.assertFalse(self.guard.verify_identity_token("other-client", secret, token))

    def test_replay_attack_nonce_protection(self):
        headers = {"X-Blast-Nonce": "nonce-unique-12345"}
        is_ok, err = self.guard.verify_request_identity("client-abc", "secret", headers)
        self.assertTrue(is_ok)

        # Duplicate nonce rejected
        is_ok2, err2 = self.guard.verify_request_identity("client-abc", "secret", headers)
        self.assertFalse(is_ok2)
        self.assertIn("Replay attack", err2)

    def test_anonymous_assumption_blocked_in_strict_mode(self):
        is_ok, err = self.guard.verify_request_identity("anonymous", None, {})
        self.assertFalse(is_ok)
        self.assertIn("Strict identity protection", err)


class TestStrictInputValidator(unittest.TestCase):
    def setUp(self):
        self.cfg = BlastConfig(TESTING=True)
        self.validator = StrictInputValidator(self.cfg)

    def test_prototype_pollution_blocked(self):
        payload = {"__proto__": {"polluted": True}}
        is_ok, code, details = self.validator.validate_inbound_input(
            method="POST",
            path="/v1/proxy/rest/v1/orders",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload),
        )
        self.assertFalse(is_ok)
        self.assertEqual(code, "INPUT_GUARD_REJECTION")
        self.assertIn("Prototype manipulation prohibited", details["message"])

    def test_constructor_prototype_blocked(self):
        payload = {"constructor": {"prototype": {"polluted": True}}}
        is_ok, code, details = self.validator.validate_inbound_input(
            method="POST",
            path="/v1/proxy/rest/v1/orders",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload),
        )
        self.assertFalse(is_ok)
        self.assertEqual(code, "INPUT_GUARD_REJECTION")

    def test_command_injection_heuristic_blocked(self):
        payload = {"script": "; rm -rf /"}
        is_ok, code, details = self.validator.validate_inbound_input(
            method="POST",
            path="/v1/proxy/rest/v1/orders",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload),
        )
        self.assertFalse(is_ok)
        self.assertEqual(code, "COMMAND_INJECTION_DETECTED")

    def test_excessive_json_depth_blocked(self):
        nested = {"level": 1}
        cur = nested
        for i in range(15):
            cur["child"] = {"level": i + 2}
            cur = cur["child"]
        is_ok, code, details = self.validator.validate_inbound_input(
            method="POST",
            path="/v1/proxy/rest/v1/orders",
            headers={"Content-Type": "application/json"},
            body=json.dumps(nested),
        )
        self.assertFalse(is_ok)
        self.assertEqual(code, "INPUT_GUARD_REJECTION")
        self.assertIn("nesting depth exceeds", details["message"])

    def test_valid_payload_passes(self):
        payload = {"item": "Laptop", "price": 999.99, "tags": ["tech", "work"]}
        is_ok, code, details = self.validator.validate_inbound_input(
            method="POST",
            path="/v1/proxy/rest/v1/orders",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload),
        )
        self.assertTrue(is_ok)
        self.assertIsNone(code)


if __name__ == "__main__":
    unittest.main()
