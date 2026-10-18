#!/usr/bin/env python3
"""Merges the CPT coverage report of every suite per process and lists the elements and flows no test completed.

Run after `cd tests && mvn verify`:  python3 scripts/coverage.py
"""
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
d = json.load(open(os.path.join(ROOT, "tests", "target", "coverage-report", "report.json")))
NODE = (r"startEvent|endEvent|task|serviceTask|scriptTask|userTask|businessRuleTask|callActivity|subProcess|"
        r"adHocSubProcess|exclusiveGateway|eventBasedGateway|parallelGateway|intermediateCatchEvent|"
        r"intermediateThrowEvent|boundaryEvent")
total_missing = 0
for m in d["processModels"]:
    pid = m["processDefinitionId"]
    if pid.startswith("h-") or ("<bpmn:process id=\"%s\"" % pid) not in m["xml"] or "tck-ghost" in pid or pid == "ghost":
        continue
    xml = m["xml"]
    block = xml[xml.index('<bpmn:process id="%s"' % pid):]
    block = block[:block.index("</bpmn:process>")]
    ids = set(re.findall(r"<bpmn:(?:%s) [^>]*?id=\"([^\"]+)\"" % NODE, block))
    flows = set(re.findall(r"<bpmn:sequenceFlow [^>]*?id=\"([^\"]+)\"", block))
    done, taken = set(), set()
    for c in d["processCoverages"]:
        if c["processDefinitionId"] == pid:
            done |= set(c["completedElements"])
            taken |= set(c["takenSequenceFlows"])
    print("%-18s elements %3d/%-3d flows %3d/%-3d" % (pid, len(ids & done), len(ids), len(flows & taken), len(flows)))
    if ids - done:
        print("   missing elements:", ", ".join(sorted(ids - done)))
    if flows - taken:
        print("   missing flows:   ", ", ".join(sorted(flows - taken)))
    total_missing += len(ids - done) + len(flows - taken)
for c in d["decisionCoverages"]:
    print("%-18s rules %.0f%%" % (c["decisionDefinitionId"], c["coverage"] * 100))
sys.exit(1 if total_missing else 0)
