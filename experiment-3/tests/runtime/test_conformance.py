import unittest
from types import SimpleNamespace
from unittest.mock import patch

from conformance import route_request, source_snapshot


class URL(SimpleNamespace):
    def copy_with(self, **fields):
        return URL(**(vars(self) | fields))


class TargetRoutingTest(unittest.TestCase):
    def request(self, **fields):
        return SimpleNamespace(
            url=URL(**({"scheme": "https", "host": "127.0.0.1", "port": 40000,
                        "path": "/inbound/a2a"} | fields)), headers={"Content-Type": "text/plain"})

    def test_only_exact_target_receives_credentials(self):
        for fields in ({"host": "example.org"}, {"port": 40001}, {"scheme": "http"},
                       {"path": "/other-agent"}, {"path": "/inbound/a2a/other"}):
            request = self.request(**fields)
            route_request(request, 40000, "private-key")
            self.assertNotIn("X-A2A-Api-Key", request.headers)
        for host in ("127.0.0.1", "host.docker.internal"):
            request = self.request(host=host)
            route_request(request, 40000, "private-key")
            self.assertEqual(request.headers["X-A2A-Api-Key"], "private-key")
            self.assertEqual(request.headers["Content-Type"], "text/plain")

    def test_explicit_discovery_is_public(self):
        request = self.request(path="/.well-known/agent-card.json")
        route_request(request, 40000, "private-key")
        self.assertEqual(request.url.path, "/inbound/a2a-card")
        self.assertNotIn("X-A2A-Api-Key", request.headers)

    def test_runner_appended_slash_does_not_change_configured_endpoint(self):
        request = self.request(path="/inbound/a2a/")
        route_request(request, 40000, "private-key")
        self.assertEqual(request.url.path, "/inbound/a2a")
        self.assertEqual(request.headers["X-A2A-Api-Key"], "private-key")

    def test_source_snapshot_records_commit_and_rejectable_dirty_state(self):
        for status, dirty in (("", False), (" M tracked.py\n", True), ("?? untracked.py\n", True)):
            with patch("conformance.subprocess.check_output", side_effect=["abc123\n", status]):
                self.assertEqual(source_snapshot("/repository"),
                                 {"targetCommit": "abc123", "targetWorktreeDirty": dirty})


if __name__ == "__main__":
    unittest.main()
