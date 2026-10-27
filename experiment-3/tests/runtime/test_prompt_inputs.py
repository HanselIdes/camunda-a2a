import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prompt_inputs import CASES, assert_literal_input, run


class LiteralModelInputTest(unittest.TestCase):
    @staticmethod
    def context(text):
        return {"context": {"conversation": {"messages": [
            {"role": "system", "content": [{"type": "text", "text": "Synthetic test"}]},
            {"role": "user", "content": [{"type": "text", "text": text}]},
        ]}}}

    def test_exact_input_characters_are_required(self):
        for label, text in CASES:
            with self.subTest(case=label):
                request = {"message": {"parts": [{"text": text}]}}
                self.assertEqual(assert_literal_input(text, request, self.context(text)), text)

    def test_json_encoded_model_text_is_not_accepted(self):
        for label, text in CASES:
            with self.subTest(case=label):
                with self.assertRaisesRegex(AssertionError, "Model input differs"):
                    assert_literal_input(text, {"message": {"parts": [{"text": text}]}},
                                         self.context(json.dumps(text)))

    def test_changed_task_request_is_not_accepted(self):
        with self.assertRaisesRegex(AssertionError, "Original task input changed"):
            assert_literal_input("original", {"message": {"parts": [{"text": "changed"}]}},
                                 self.context("original"))

    def test_semantic_failure_retains_exact_input_and_still_raises(self):
        text = '={"synthetic":true}'
        task = {"id": "test", "status": {"state": "TASK_STATE_COMPLETED"},
                "artifacts": [{"name": "unexpected"}]}
        req = {"message": {"parts": [{"text": text}]}}
        with tempfile.TemporaryDirectory() as directory:
            with patch("prompt_inputs.CASES", (("expression", text),)), patch(
                    "prompt_inputs.read_root_variable", side_effect=[req, self.context(text)]):
                with self.assertRaises(AssertionError):
                    run(Path(directory), lambda message: (200, {"result": task}),
                        lambda *args: (200, '{"items":[{"processInstanceKey":"test"}]}'),
                        lambda response: response["result"])
            report = json.loads((Path(directory) / "literal-model-inputs.json").read_text())
            self.assertEqual(report["literalInputVerdict"], "PASS")
            self.assertEqual(report["semanticVerdict"], "FAIL")
            self.assertEqual(report["verdict"], "FAIL")
            self.assertEqual(report["records"][0]["modelUserText"], text)
            self.assertEqual(report["records"][0]["task"], task)
