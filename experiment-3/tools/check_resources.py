#!/usr/bin/env python3
"""Check candidate import reference closure and print immutable resource URLs."""
import argparse
import json
import re
import xml.etree.ElementTree as ET

from build_core import B, Z, ROOT

PATHS = (
    "blueprint/profiles/basic/a2a-protocol.bpmn",
    "dmn/a2a-validate.dmn",
    "blueprint/demo/a2a-card.bpmn",
    "blueprint/demo/a2a-card-dispute.bpmn",
    "blueprint/demo/a2a-client.bpmn",
    "blueprint/demo/a2a-client-ask.form",
    "blueprint/demo/a2a-client-answer.form",
    "blueprint/demo/a2a-client-result.form",
    "blueprint/templates/a2a-core-rpc.json",
    "blueprint/templates/a2a-core-card.json",
    "blueprint/templates/http-json.json",
)
AI_URL = ("https://raw.githubusercontent.com/camunda/connectors/"
          "844cb028a43e2a15d31f5a49e6cb0a9961c0f208/"
          "connectors/agentic-ai/element-templates/versioned/agenticai-aiagent-job-worker-5.json")
EXTERNAL_TEMPLATES = {("io.camunda.connectors.agenticai.aiagent.jobworker.v1", "5")}


def check(resources=None):
    if resources is None:
        resources = {path: (ROOT / path).read_bytes() for path in PATHS}
    if set(resources) != set(PATHS):
        raise ValueError("Candidate resource set differs from the selected Basic import set")
    names = [path.rsplit("/", 1)[-1] for path in PATHS] + [AI_URL.rsplit("/", 1)[-1]]
    if len(set(names)) != len(names):
        raise ValueError("Import resources have duplicate flattened filenames")
    models, templates, forms, processes, decisions = [], set(EXTERNAL_TEMPLATES), set(), set(), set()
    for path, content in resources.items():
        if path.endswith(".bpmn"):
            root = ET.fromstring(content)
            models.append((path, root))
            processes.update(p.get("id") for p in root.iter(f"{{{B}}}process"))
        elif path.endswith(".dmn"):
            root = ET.fromstring(content)
            decisions.update(e.get("id") for e in root.iter() if e.tag.endswith("}decision"))
        else:
            data = json.loads(content)
            if path.endswith(".form"):
                forms.add(data["id"])
            else:
                templates.add((data["id"], str(data["version"])))
    errors = []
    for path, root in models:
        for element in root.iter():
            template = element.get(f"{{{Z}}}modelerTemplate")
            if template and (template, element.get(f"{{{Z}}}modelerTemplateVersion")) not in templates:
                errors.append(f"{path}:{element.get('id')}: missing template {template}@"
                              f"{element.get(f'{{{Z}}}modelerTemplateVersion')}")
            for tag, attribute, available in (("formDefinition", "formId", forms),
                                              ("calledElement", "processId", processes),
                                              ("calledDecision", "decisionId", decisions)):
                reference = element.get(attribute)
                if element.tag == f"{{{Z}}}{tag}" and reference and reference not in available:
                    errors.append(f"{path}: unresolved {attribute} {reference}")
    if errors:
        raise ValueError("\n".join(errors))
    return len(names)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", help="Full public commit SHA for immutable raw URLs")
    args = parser.parse_args()
    count = check()
    if args.ref:
        if not re.fullmatch(r"[0-9a-f]{40}", args.ref):
            parser.error("--ref must be a full lowercase commit SHA")
        prefix = f"https://raw.githubusercontent.com/HanselIdes/camunda-a2a/{args.ref}/experiment-3/"
        print(json.dumps([{"name": p.rsplit("/", 1)[-1], "url": prefix + p} for p in PATHS]
                         + [{"name": AI_URL.rsplit("/", 1)[-1], "url": AI_URL}], indent=2))
    else:
        print(f"{count} candidate import resources: templates, forms, decisions and process references resolve")
