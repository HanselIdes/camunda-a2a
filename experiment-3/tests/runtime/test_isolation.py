import socket
import subprocess
import unittest
from unittest.mock import patch

from isolation import IsolatedCompose


class IsolationTest(unittest.TestCase):
    def test_runs_have_distinct_projects_and_reserved_loopback_ports(self):
        first, second = IsolatedCompose("compose.yml", {}), IsolatedCompose("compose.yml", {})
        try:
            self.assertNotEqual(first.project, second.project)
            ports = [int(stack.env[name]) for stack in (first, second)
                     for name in ("PROOF_ENGINE_PORT", "PROOF_CONNECTORS_PORT")]
            self.assertEqual(len(set(ports)), 4)
            for port in ports:
                with socket.socket() as contender:
                    with self.assertRaises(OSError):
                        contender.bind(("127.0.0.1", port))
        finally:
            first.close()
            second.close()

    @patch("isolation.subprocess.run")
    def test_collision_never_starts_or_tears_down_existing_resources(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, stdout="pre-existing-resource\n")
        stack = IsolatedCompose("compose.yml", {})
        try:
            with self.assertRaisesRegex(RuntimeError, "pre-existing"):
                stack.start()
        finally:
            stack.close()
        self.assertEqual(run.call_count, 1)
        self.assertNotIn("up", run.call_args.args[0])
        self.assertNotIn("down", run.call_args.args[0])

    @patch("isolation.subprocess.run")
    def test_partial_start_failure_cleans_only_owned_project(self, run):
        empty = subprocess.CompletedProcess([], 0, stdout="")
        run.side_effect = [empty, empty, empty,
                           subprocess.CalledProcessError(1, ["docker", "compose", "up"]), empty]
        stack = IsolatedCompose("compose.yml", {})
        try:
            with self.assertRaises(subprocess.CalledProcessError):
                stack.start()
            self.assertFalse(stack.reservations)
        finally:
            stack.close()
        self.assertEqual(run.call_args.args[0], stack.command + ["down"])
        self.assertIn(stack.project, run.call_args.args[0])
        stack.close()
        self.assertEqual(run.call_count, 5)

    @patch("isolation.subprocess.run")
    def test_successful_start_teardown_is_owned_and_idempotent(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, stdout="")
        stack = IsolatedCompose("compose.yml", {})
        try:
            stack.start()
            self.assertTrue(stack.started)
            self.assertFalse(stack.reservations)
        finally:
            stack.close()
        stack.close()
        self.assertEqual(run.call_count, 5)
        self.assertEqual(run.call_args.args[0], stack.command + ["down"])


if __name__ == "__main__":
    unittest.main()
