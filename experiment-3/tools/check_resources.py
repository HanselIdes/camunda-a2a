#!/usr/bin/env python3
"""Check candidate import reference closure and print immutable resource URLs."""
import argparse
import json
import re
import xml.etree.ElementTree as ET

from build_core import B, Z, ROOT
from build_blueprint import AI_CLIENT

PATHS = (
    "blueprint/demo/01-client-agent.bpmn",
    "blueprint/profiles/basic/02-a2a-server.bpmn",
    "blueprint/demo/03-server-agent-card-dispute.bpmn",
    "blueprint/demo/04-client-agent-ask.form",
    "blueprint/demo/05-client-agent-confirm.form",
    "blueprint/demo/06-client-agent-result.form",
    "blueprint/demo/07-server-request-validation.dmn",
    "blueprint/templates/08-server-a2a-rpc-endpoint.json",
    "blueprint/templates/09-server-agent-card-endpoint.json",
    "blueprint/templates/10-server-http-json-v13.json",
    "blueprint/templates/11-client-a2a.json",
    "blueprint/demo/01-client-agent.integration.test.json",
    "blueprint/profiles/basic/02-a2a-server.test.json",
    "blueprint/demo/03-server-agent-card-dispute.test.json",
    "blueprint/demo/README.md",
)
AI_URL = ("https://raw.githubusercontent.com/camunda/connectors/"
          "844cb028a43e2a15d31f5a49e6cb0a9961c0f208/"
          "connectors/agentic-ai/element-templates/versioned/agenticai-aiagent-job-worker-5.json")
EXTERNAL_TEMPLATES = {
    ("io.camunda.connectors.agenticai.aiagent.jobworker.v1", "5"),
    ("io.camunda.connectors.agenticai.ai-agent-subprocess.v2", "1"),
}


def check(resources=None):
    if resources is None:
        resources = {path: (ROOT / path).read_bytes() for path in PATHS}
    if set(resources) != set(PATHS):
        raise ValueError("Candidate resource set differs from the selected Basic import set")
    names = [path.rsplit("/", 1)[-1] for path in PATHS] + [
        url.rsplit("/", 1)[-1] for url in (AI_URL, AI_CLIENT)]
    if len(set(names)) != len(names):
        raise ValueError("Import resources have duplicate flattened filenames")
    models, templates, forms, processes, decisions = [], set(EXTERNAL_TEMPLATES), set(), set(), set()
    scenarios = []
    for path, content in resources.items():
        if path.endswith(".bpmn"):
            root = ET.fromstring(content)
            models.append((path, root))
            processes.update(p.get("id") for p in root.iter(f"{{{B}}}process"))
        elif path.endswith(".dmn"):
            root = ET.fromstring(content)
            decisions.update(e.get("id") for e in root.iter() if e.tag.endswith("}decision"))
        elif path.endswith(".md"):
            continue
        else:
            data = json.loads(content)
            if path.endswith(".form"):
                forms.add(data["id"])
            elif path.endswith(".test.json"):
                scenarios.append((path, data))
            else:
                templates.add((data["id"], str(data["version"])))
    errors = []
    for path, data in scenarios:
        if data.get("processId") not in processes:
            errors.append(f"{path}: unresolved scenario processId {data.get('processId')}")
        if not isinstance(data.get("testCases"), list) or not data["testCases"]:
            errors.append(f"{path}: missing Web Modeler test cases")
    for path, root in models:
        for element in root.iter():
            template = element.get(f"{{{Z}}}modelerTemplate")
            if template and (template, element.get(f"{{{Z}}}modelerTemplateVersion")) not in templates:
                errors.append(f"{path}:{element.get('id')}: missing template {template}@"
                              f"{element.get(f'{{{Z}}}modelerTemplateVersion')}")
            if template:
                for header in element.findall(f"{{{B}}}extensionElements/{{{Z}}}taskHeaders/{{{Z}}}header"):
                    if (header.get("key") == "elementTemplateVersion"
                            and header.get("value") != element.get(f"{{{Z}}}modelerTemplateVersion")):
                        errors.append(f"{path}:{element.get('id')}: task-header template version "
                                      f"{header.get('value')} differs from Modeler assignment")
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
                         + [{"name": url.rsplit("/", 1)[-1], "url": url}
                            for url in (AI_URL, AI_CLIENT)], indent=2))
    else:
        print(f"{count} candidate import resources: templates, forms, decisions and process references resolve")
