import json
import unittest

from prompt_inputs import CASES, assert_literal_input


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
