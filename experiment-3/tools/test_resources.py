import unittest

from check_resources import PATHS, ROOT, check


class ResourceClosureTest(unittest.TestCase):
    def setUp(self):
        self.resources = {path: (ROOT / path).read_bytes() for path in PATHS}

    def test_selected_import_set_is_closed(self):
        self.assertEqual(check(self.resources), 12)

    def test_template_version_mismatch_is_rejected(self):
        path = "blueprint/profiles/basic/a2a-protocol.bpmn"
        self.resources[path] = self.resources[path].replace(
            b'zeebe:modelerTemplateVersion="12"', b'zeebe:modelerTemplateVersion="18"', 1)
        with self.assertRaisesRegex(ValueError, "missing template .*@18"):
            check(self.resources)

    def test_missing_form_is_rejected(self):
        path = "blueprint/demo/a2a-client-ask.form"
        self.resources[path] = self.resources[path].replace(b'"a2a-client-ask"', b'"missing-form"')
        with self.assertRaisesRegex(ValueError, "unresolved formId a2a-client-ask"):
            check(self.resources)

    def test_connector_task_header_version_mismatch_is_rejected(self):
        path = "blueprint/profiles/basic/a2a-protocol.bpmn"
        self.resources[path] = self.resources[path].replace(
            b'key="elementTemplateVersion" value="12"', b'key="elementTemplateVersion" value="18"', 1)
        with self.assertRaisesRegex(ValueError, "task-header template version 18 differs"):
            check(self.resources)

    def test_missing_called_process_is_rejected(self):
        path = "blueprint/demo/a2a-card-dispute.bpmn"
        self.resources[path] = self.resources[path].replace(b'processId="a2a-task-update"',
                                                           b'processId="missing-process"')
        with self.assertRaisesRegex(ValueError, "unresolved processId missing-process"):
            check(self.resources)


if __name__ == "__main__":
    unittest.main()
