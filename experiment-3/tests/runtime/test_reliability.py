import copy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from reliability import B, DI, TIMER_SECONDS, check_completed, peak_concurrency, run_agent, timed_echo, write_json


def completed(text="Exact result"):
    return {
        "id": "test-task", "contextId": "load-alpha",
        "status": {"state": "TASK_STATE_COMPLETED", "message": {"parts": [{"text": text}]}},
        "history": [{"parts": [{"text": text}]}, {"parts": [{"text": text}]}],
    }


class ReliabilityTest(unittest.TestCase):
    def test_exact_result_check_rejects_wrong_text_context_history_and_state(self):
        task = completed()
        check_completed(task, "Exact result", "load-alpha")
        for field, value in (("contextId", "foreign"), ("status", {"state": "TASK_STATE_WORKING"}),
                             ("history", []), ("artifacts", [{"parts": [{"text": "unexpected"}]}])):
            broken = copy.deepcopy(task)
            broken[field] = value
            with self.assertRaises((AssertionError, KeyError)):
                check_completed(broken, "Exact result", "load-alpha")
        with self.assertRaises(AssertionError):
            check_completed(task, "Wrong result", "load-alpha")

    def test_touching_intervals_are_not_concurrent(self):
        self.assertEqual(peak_concurrency([{"started": 1, "finished": 2}, {"started": 2, "finished": 3}]), 1)
        self.assertEqual(peak_concurrency([{"started": 1, "finished": 3}, {"started": 2, "finished": 4}]), 2)

    def test_timed_fixture_has_connected_timer_and_complete_di(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "timed.bpmn"
            source = Path(__file__).resolve().parents[2] / "bpmn/a2a-echo.bpmn"
            original = source.read_bytes()
            timed_echo(source, target)
            root = ET.parse(target).getroot()
            process = root.find(f"{{{B}}}process")
            timer = process.find(f"{{{B}}}intermediateCatchEvent")
            self.assertEqual(timer.find(f"{{{B}}}timerEventDefinition/{{{B}}}timeDuration").text,
                             f'="PT{TIMER_SECONDS}S"')
            self.assertEqual(timer.find(f"{{{B}}}incoming").text, "Flow_Received_Hold")
            self.assertEqual(timer.find(f"{{{B}}}outgoing").text, "Flow_Hold_Echo")
            elements = {node.get("id") for node in process}
            represented = {node.get("bpmnElement") for node in root.iter()
                           if node.tag in (f"{{{DI}}}BPMNEdge", f"{{{DI}}}BPMNShape")}
            for flow in process.findall(f"{{{B}}}sequenceFlow"):
                self.assertIn(flow.get("sourceRef"), elements)
                self.assertIn(flow.get("targetRef"), elements)
                self.assertIn(flow.get("id"), represented)
            self.assertIn(timer.get("id"), represented)
            self.assertEqual(source.read_bytes(), original)

    def test_agent_requests_nonblocking_work_and_polls_to_exact_result(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory) / "alpha"
            control.mkdir()
            write_json(control / "command-0.json", {"operation": "send", "text": "Exact result"})
            write_json(control / "command-1.json", {"operation": "stop"})
            calls = []

            def rpc(request, timeout):
                calls.append(request)
                task = completed()
                if request["method"] == "SendMessage":
                    task["status"] = {"state": "TASK_STATE_WORKING"}
                    result = {"task": task}
                else:
                    result = task
                return 200, {"jsonrpc": "2.0", "id": request["id"], "result": result}

            run_agent({"PROOF_LOAD_AGENT": "alpha", "PROOF_CONTROL_DIR": directory},
                      Path(directory), rpc, None, None, None)
            self.assertEqual(calls[0]["params"]["configuration"], {"returnImmediately": True})
            self.assertEqual([call["method"] for call in calls], ["SendMessage", "GetTask"])
            self.assertEqual(json.loads((Path(directory) / "workload.json").read_text())["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
