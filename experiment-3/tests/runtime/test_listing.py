import json
from pathlib import Path
import tempfile
import unittest
import uuid

from listing import run


class ListingProofTest(unittest.TestCase):
    def exercise(self, directory, defect=None):
        stored = []

        def rpc(request):
            params = request["params"]
            if request["method"] == "SendMessage":
                task = {"id": str(uuid.uuid4()), "contextId": params["message"]["contextId"],
                        "status": {"state": "TASK_STATE_COMPLETED", "timestamp": "2026-10-27T00:00:00Z",
                                   "message": {"parts": params["message"]["parts"]}}}
                stored.append(task)
                result = {"task": task}
            else:
                tasks = sorted(stored, key=lambda task: task["id"], reverse=True)
                if params.get("status") or params.get("statusTimestampAfter"):
                    tasks = []
                elif defect == "omitted":
                    tasks = tasks[:-1]
                start = int(params.get("pageToken") or 0) if defect != "repeated" else 0
                result = {"totalSize": len(stored), "pageSize": 37, "tasks": tasks[start:start + 37],
                          "nextPageToken": str(start + 37) if start + 37 < len(tasks) else ""}
                if defect == "repeated":
                    result["nextPageToken"] = "unchanged"
            return 200, {"jsonrpc": "2.0", "id": request["id"], "result": result}

        run(Path(directory), rpc)

    def test_exact_collection_records_all_four_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            self.exercise(directory)
            report = json.loads((Path(directory) / "listing-checks.json").read_text())
            self.assertEqual(report["verdict"], "PASS")
            self.assertEqual([row["count"] for row in report["records"][:-1]], [37, 37, 37, 14])
            self.assertEqual(report["records"][-1]["uniqueIds"], 125)

    def test_missing_task_is_not_a_passing_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AssertionError, "Paginated tasks differ"):
                self.exercise(directory, "omitted")
            self.assertEqual(json.loads((Path(directory) / "listing-checks.json").read_text())["verdict"], "FAIL")

    def test_repeated_page_token_is_not_a_passing_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AssertionError, "did not advance"):
                self.exercise(directory, "repeated")
            self.assertEqual(json.loads((Path(directory) / "listing-checks.json").read_text())["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
