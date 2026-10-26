import json
import unittest
from unittest.mock import Mock, patch

from observations import read_root_variable


class ObservationTests(unittest.TestCase):
    def test_waits_for_exact_root_variable(self):
        request = Mock(side_effect=[
            (200, '{"items": []}'),
            (200, json.dumps({"items": [{"value": '{"result": "expected"}'}]})),
        ])
        with patch("observations.time.sleep"):
            self.assertEqual(read_root_variable(request, "123", "rpc"), {"result": "expected"})
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            self.assertEqual(call.args[1]["filter"],
                             {"processInstanceKey": "123", "scopeKey": "123", "name": "rpc"})
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertLessEqual(call.kwargs["timeout"], 15)

    def test_absence_expires_instead_of_succeeding(self):
        request = Mock(return_value=(200, '{"items": []}'))
        with patch("observations.time.monotonic", side_effect=[0, 0, 1, 1]), \
                patch("observations.time.sleep"):
            with self.assertRaisesRegex(TimeoutError, "rpc in instance 123 was absent after 1 searches"):
                read_root_variable(request, "123", "rpc", seconds=1)
        self.assertEqual(request.call_count, 1)

    def test_failed_search_does_not_retry_or_return_empty_success(self):
        request = Mock(return_value=(401, "not authorized"))
        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            read_root_variable(request, "123", "rpc")
        request.assert_called_once()

    def test_ambiguous_values_fail(self):
        request = Mock(return_value=(200, '{"items": [{"value": "1"}, {"value": "2"}]}'))
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            read_root_variable(request, "123", "rpc")


if __name__ == "__main__":
    unittest.main()
