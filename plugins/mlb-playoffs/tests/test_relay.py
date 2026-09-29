"""Tests for relay/mlb_relay.py with the network mocked.

Run from the plugin directory: python3 -m unittest discover tests
"""

import io
import json
import os
import sys
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "relay"))

import mlb_relay  # noqa: E402

WEBHOOK = "https://trmnl.com/api/custom_plugins/00000000-secret-uuid"
FEED = {"series": [{"series": {"id": "F_1"}, "games": []}]}


def response(body, status=200):
    """Fake urlopen() context manager returning ``body``."""
    r = io.BytesIO(json.dumps(body).encode())
    r.status = status
    return r


class BuildRequest(unittest.TestCase):
    def test_trmnl_payload_wrapped_in_merge_variables(self):
        with mock.patch.dict(os.environ, {"TRMNL_WEBHOOK_URL": WEBHOOK}):
            request = mlb_relay.build_request(FEED, local=False)
        self.assertEqual(request.full_url, WEBHOOK)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"merge_variables": FEED})

    def test_sets_user_agent(self):
        # Cloudflare in front of trmnl.com blocks Python-urllib's default (403, error 1010).
        request = mlb_relay.build_request(FEED, local=True)
        self.assertEqual(request.get_header("User-agent"), mlb_relay.USER_AGENT)

    def test_local_payload_is_raw_feed(self):
        request = mlb_relay.build_request(FEED, local=True)
        self.assertEqual(request.full_url, mlb_relay.LOCAL_WEBHOOK)
        self.assertEqual(json.loads(request.data), FEED)

    def test_requires_https_webhook_url(self):
        for url in ("", "http://trmnl.com/api/custom_plugins/x"):
            with mock.patch.dict(os.environ, {"TRMNL_WEBHOOK_URL": url}), self.assertRaises(ValueError):
                mlb_relay.build_request(FEED, local=False)


class Main(unittest.TestCase):
    def run_main(self, *responses):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"TRMNL_WEBHOOK_URL": WEBHOOK}), \
                mock.patch("urllib.request.urlopen", side_effect=list(responses)) as urlopen, \
                redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            code = mlb_relay.main([])
        return code, urlopen, stderr.getvalue()

    def test_fetches_then_posts(self):
        code, urlopen, _ = self.run_main(response(FEED), response({"message": "ok"}))
        self.assertEqual(code, 0)
        self.assertIn("statsapi.mlb.com", urlopen.call_args_list[0].args[0].full_url)
        self.assertEqual(urlopen.call_args_list[1].args[0].full_url, WEBHOOK)

    def test_bad_feed_is_not_posted(self):
        code, urlopen, err = self.run_main(response({"message": "maintenance"}))
        self.assertEqual(code, 1)
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("no 'series'", err)

    def test_rate_limit_error_does_not_leak_webhook_uuid(self):
        limited = urllib.error.HTTPError(WEBHOOK, 429, "Too Many Requests", {}, io.BytesIO(b"rate limited"))
        code, _, err = self.run_main(response(FEED), limited)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 429", err)
        self.assertNotIn("secret-uuid", err)


if __name__ == "__main__":
    unittest.main()
