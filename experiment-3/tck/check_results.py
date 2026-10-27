#!/usr/bin/env python3
"""Judges one TCK run. Never trusts the exit code of the TCK, because it turns setup failures into skips.

Usage: python3 -I tck/check_results.py <reports dir> [--rest http://localhost:28080] [--push]
Exit 0 only if every condition holds; prints one RESULT line and every violation otherwise.

--push judges a run with push notifications switched on (A2A_PUSH_ENABLED=true): the card declares the capability, so
every PUSH-* requirement must PASS, and CORE-CAP-001 (the error for an unsupported capability) is skipped by the TCK.
"""
import fnmatch
import json
import os
from pathlib import Path
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REASONS = {"capability-not-declared", "capability-declared", "other-binding", "client-side", "not-exercised"}
RELEVANT = {"jsonrpc", "agent_card"}
# These pinned TCK tests skip before the collector records their requirement.
EARLY_SKIP_REQUIREMENTS = {
    "core_operations.test_transport_behavior.TestJsonRpcStreaming::test_streaming_content_type":
        ["JSONRPC-SSE-001"],
    "core_operations.test_transport_behavior.TestRestFormat::test_response_content_type":
        ["HTTP_JSON-SVC-001"],
    "core_operations.test_transport_behavior.TestRestFormat::test_response_validates_against_schema":
        ["HTTP_JSON-SVC-001"],
}
# Must be PASS and may never be allowlisted.
NEVER_ALLOWED = [
    "CORE-SEND-001", "CORE-SEND-003", "CORE-GET-*", "CORE-CANCEL-*", "CORE-LIST-*", "CORE-EXECUTION-MODE-*",
    "CORE-MULTI-001a", "CORE-MULTI-002a", "CORE-MULTI-003", "CORE-MULTI-004", "CORE-MULTI-005", "CORE-MULTI-006",
    "CORE-HIST-002", "CORE-ERR-*", "CORE-CAP-001", "CORE-CAP-002", "CORE-CAP-003",
    "JSONRPC-FMT-*", "JSONRPC-SVC-*", "JSONRPC-ERR-*", "JSONRPC-SSE-002", "DM-*",
    "CARD-DISC-001", "CARD-PROTO-*", "CARD-STRUCT-001", "VER-SERVER-002", "VER-SERVER-003",
]


def never_allowed(req_id):
    return any(fnmatch.fnmatchcase(req_id, p) for p in NEVER_ALLOWED)


def load_allowlist(path):
    reqs, skips, errors = {}, [], []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 3)
        if len(parts) < 3 or parts[0] not in ("REQ", "SKIP"):
            errors.append("allowlist line %d is malformed: %s" % (n, line))
            continue
        kind, target, reason = parts[0], parts[1], parts[2]
        note = parts[3] if len(parts) > 3 else ""
        if kind == "SKIP":
            # the regex may contain no spaces, so target is the whole pattern
            pass
        if reason not in REASONS:
            errors.append("allowlist line %d has reason %r outside %s" % (n, reason, sorted(REASONS)))
        if not note:
            errors.append("allowlist line %d has no note" % n)
        if kind == "REQ":
            if never_allowed(target):
                errors.append("allowlist line %d: %s must be PASS and cannot be allowlisted" % (n, target))
            reqs[target] = {"reason": reason, "note": note}
        else:
            skips.append((re.compile(target, re.I), reason, note))
    return reqs, skips, errors


def main(argv):
    if not argv:
        sys.exit(__doc__)
    reports = argv[0]
    rest = "http://localhost:28080"
    if "--rest" in argv:
        rest = argv[argv.index("--rest") + 1]
    problems = []
    reqs_allowed, skip_rules, errs = load_allowlist(os.path.join(HERE, "allowed-not-passing.txt"))
    problems += errs
    push = "--push" in argv
    if push:
        # the capability is declared: the PUSH-* requirements are not optional any more
        reqs_allowed = {k: v for k, v in reqs_allowed.items() if not k.startswith("PUSH-")}
        skip_rules = [(rx, r, note) for rx, r, note in skip_rules if "PUSH" not in rx.pattern.upper()]
        skip_rules.append((re.compile(r"TestCapabilityPushNotifications::test_push_not_supported|test_push_notification_not_supported_error"),
                           "capability-declared", "Push is declared; unsupported-capability error does not apply."))

    # 1. junit: failures, errors, and a plausible number of executed tests
    suite = ET.parse(os.path.join(reports, "junitreport.xml")).getroot()
    suites = [suite] if suite.tag == "testsuite" else list(suite.iter("testsuite"))
    tests = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) for s in suites)
    errors = sum(int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    executed = tests - skipped
    if failures or errors:
        problems.append("junit has %d failures and %d errors" % (failures, errors))
    if executed < 50:
        problems.append("only %d tests executed (expected 50 or more): a run that executes nothing is a failure" % executed)

    # 2. every junit skip must match an allowlisted pattern
    compat = json.loads(Path(reports, "compatibility.json").read_text())
    requirements_by_test = {}
    for rid, requirement in compat["per_requirement"].items():
        for test_id in requirement.get("test_ids", []):
            normalized = test_id.replace(".py::", ".").replace("::", ".").replace("/", ".")
            requirements_by_test.setdefault(normalized, []).append(rid)
    unmatched = []
    skip_audit = []
    for tc in ET.parse(os.path.join(reports, "junitreport.xml")).getroot().iter("testcase"):
        if tc.find("skipped") is None:
            continue
        node = (tc.get("classname") or "").replace("tests.compatibility.", "") + "::" + (tc.get("name") or "")
        matched = [{"pattern": rx.pattern, "reason": reason, "note": note}
                   for rx, reason, note in skip_rules if rx.search(node)]
        msg = tc.find("skipped").get("message") or ""
        normalized = (tc.get("classname") or "") + "." + (tc.get("name") or "")
        requirement_ids = requirements_by_test.get(normalized, EARLY_SKIP_REQUIREMENTS.get(node, []))
        skip_audit.append({"test": node, "message": msg, "requirementIds": requirement_ids,
                           "requirementMapping": "collector" if normalized in requirements_by_test
                           else "pinned TCK source: test_transport_behavior.py",
                           "allowlistMatches": matched})
        if not matched:
            msg = msg[:80]
            unmatched.append("%s (%s)" % (node, msg))
        if not requirement_ids:
            problems.append("skipped test has no requirement mapping: " + node)
    for u in unmatched:
        problems.append("skip not allowlisted: " + u)

    # 3. every MUST requirement is PASS on jsonrpc/agent_card unless allowlisted
    passed = allowlisted = 0
    seen = set()
    requirement_audit = []
    for rid, v in compat["per_requirement"].items():
        if v["level"] != "MUST":
            continue
        seen.add(rid)
        relevant = {t: s for t, s in v["transports"].items() if t in RELEVANT}
        if relevant:
            ok = all(s == "PASS" for s in relevant.values())
        else:  # only checked on another binding without touching the SUT's interface (static TCK checks)
            ok = v["status"] == "PASS"
        requirement_audit.append({"id": rid, "status": v["status"], "transports": v["transports"],
                                  "passesGate": ok, "exclusion": None if ok else reqs_allowed.get(rid)})
        if ok:
            passed += 1
            continue
        if push and rid == "CORE-CAP-001" and v["status"] == "SKIPPED":
            allowlisted += 1  # the error for an unsupported capability cannot be tested when the capability is declared
            continue
        if rid in reqs_allowed:
            allowlisted += 1
            continue
        problems.append("%s is %s on %s and not allowlisted: %s" % (
            rid, v["status"], v["transports"], "; ".join(v["errors"])[:200]))
    for rid in reqs_allowed:
        if rid not in seen:
            problems.append("allowlist names unknown MUST requirement %s" % rid)

    # 4. no incidents in the engine
    try:
        req = urllib.request.Request(rest + "/v2/incidents/search", data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        authorization = os.environ.get("A2A_TCK_ENGINE_AUTHORIZATION")
        if authorization:
            req.add_header("Authorization", authorization)
        with urllib.request.urlopen(req, timeout=20) as response:
            total = json.load(response)["page"]["totalItems"]
        if total != 0:
            problems.append("engine reports %d incidents" % total)
    except Exception as e:  # noqa: BLE001
        problems.append("could not query incidents at %s: %s" % (rest, e))
        total = -1

    line = ("RESULT executed=%d skipped=%d failures=%d errors=%d must_pass=%d must_allowlisted=%d incidents=%s verdict=%s"
            % (executed, skipped, failures, errors, passed, allowlisted, total, "FAIL" if problems else "OK"))
    print(line)
    for p in problems:
        print("  PROBLEM: " + p)
    with open(os.path.join(reports, "gate.json"), "w") as file:
        json.dump({"executed": executed, "skipped": skipped, "failures": failures, "errors": errors,
                   "mustPass": passed, "mustAllowlisted": allowlisted, "incidents": total,
                   "verdict": "FAIL" if problems else "OK", "problems": problems,
                   "mustRequirements": requirement_audit, "skippedTests": skip_audit}, file, indent=2)
        file.write("\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
